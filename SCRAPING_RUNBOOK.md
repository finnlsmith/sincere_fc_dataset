# Matchday Scraping Runbook

How to pull and process a new matchday's data from each source. **Run every
command from the repo root** (`sincere_fc_dataset/`) — output paths are
relative to the current directory, not to the script's location.

Output folders below are auto-dated by the scripts themselves; you don't
need to (and shouldn't) invent folder names by hand. The double-duplicate
mess from earlier this season came from manually-named `retest`/`retest2`
folders — that's exactly what auto-dating exists to prevent.

## FotMob

Three steps: fetch the fixture list, scrape match details for whichever
fixtures have finished, then parse the raw JSON into CSVs.

```bash
# 1. Refresh the fixture list for a league (overwrites in place — always
#    reflects the current schedule, not a snapshot per matchday)
python scripts/fotmob/fotmob_fetch_fixtures.py LaLiga "2026/2027"
# -> data/fixtures/esp_87_2026_2027_fixtures.json

# 2. Scrape match details for the finished fixtures in that file.
#    output_dir is a required arg you choose — keep it under data/fotmob/raw/
python scripts/fotmob/fotmob_scrape_match_details.py \
  data/fixtures/esp_87_2026_2027_fixtures.json \
  data/fotmob/raw/esp_87_2026_2027 \
  "LaLiga"

# 3. Parse that raw JSON into CSVs (shots, player_stats, team_stats_*)
python scripts/fotmob/fotmob_json_to_csv.py data/fotmob/raw/esp_87_2026_2027
# -> data/fotmob/parsed/<today's date>/esp_87/{shots,player_stats,team_stats_*}.csv
```

Run step 2/3 again after later matchdays with the same `output_dir` in
step 2 — the script only scrapes fixtures it hasn't already got, and step 3
re-parses whatever's accumulated in that raw folder into a freshly-dated
parsed folder.

Repeat for each of the other four leagues (EPL = `eng_47`, Ligue1 =
`fra_53`, SerieA = `ita_55`, Bundesliga = `ger_54`), substituting the
league name/season string and the matching fixtures file.

**Caution — Bundesliga name collision:** `master_leagues.json` has *two*
entries named "Bundesliga" — id `54` (Germany, the one we want) and id `38`
(Austria). Before trusting `python fotmob_fetch_fixtures.py Bundesliga
"2026/2027"`, confirm `fotmob_fetch_fixtures.py` disambiguates by country
and not just by name string — otherwise it could silently resolve to the
Austrian league instead. Check the fixtures file it writes
(`data/fixtures/ger_54_2026_2027_fixtures.json`, not `_38_`) before relying
on it in a real run.

## WhoScored

Two steps: scrape, then parse the raw event data into per-player summary
CSVs. Uses Selenium (`webdriver.Chrome()`), not Playwright.

Covers all five leagues (EPL, SerieA, Ligue1, LaLiga, Bundesliga) in one
run — Bundesliga is already configured in the script's `LEAGUES` dict, no
argument or edit needed.

```bash
# 1. Scrape (no argument needed — auto-dates its own output dir)
python scripts/whoscored/whoscored_scrape_update_2.py
# -> data/whoscored/raw/whoscored_raw_json_<today's date>/

# 2. Parse that raw folder into CSVs
python scripts/whoscored/parse_whoscored_jsons.py \
  data/whoscored/raw/whoscored_raw_json_<today's date>
# -> data/whoscored/parsed/parsed_whoscored_<today's date>/
```

Note: WhoScored's raw-to-per-round-summary consolidation used for the
LaLiga MD1/MD2 split project (`whoscored_match_metrics.py`) is a separate,
unfinished piece of work — not part of this regular weekly scrape/parse
pair. See `laliga_md1_md2_split/README.md` for that project's status.

## Opta

Two steps: scrape, then parse.

**Bundesliga is not yet enabled.** The `LEAGUES` dict in
`grab_data_from_opta_api_2.py` has a Bundesliga entry but it's commented
out:

```python
# "Bundesliga": ("8h5xijv2u4mlf5028gso6kw7o", "https://theanalyst.com/competition/bundesliga/stats"),
```

Its tmcl value was reconfirmed live along with the other four (per the
script's comments, Aug 28 2026) — uncomment that line before running to
include Bundesliga in the scrape. Until then, Opta output covers only the
original four leagues.

```bash
# 1. Scrape (no argument needed — auto-dates its own output dir)
python scripts/opta/grab_data_from_opta_api_2.py
# -> data/opta/raw/opta_raw_<YYYYMMDD_HHMMSS>/

# 2. Parse that raw folder into CSVs
python scripts/opta/opta_json_to_csv.py data/opta/raw/opta_raw_<timestamp>
# -> data/opta/parsed/opta_parsed_<today's date>/
```

## DataMB

```bash
python scripts/datamb/scrape_datamb.py
# -> data/datamb/snapshots/<today's date>/
```

**Currently paused** — DataMB hadn't rolled over to 2026/27 season data as
of the last check. Confirm it has before relying on a fresh scrape.

This script pulls pre-aggregated "top 7 leagues" position files rather
than selecting leagues itself, so there's nothing to configure for
Bundesliga — but whether Bundesliga is actually among those 7 isn't
knowable from the script. Check the combined snapshot's league coverage
once DataMB is unpaused.

## Identity pipeline (run after the above, once new player rows exist)

Resolves player identities across all four sources against
`reference_data/master_player_table.csv`, then rebuilds the per-league
crosswalk/legend files in `identity_legends/`. Run per league.

```bash
# 1. Match this league's newly-parsed rows to the master table
python scripts/identity/match_players_to_master.py \
  reference_data/master_player_table.csv \
  data/opta/parsed/<latest>/<opta_csv_for_league> \
  data/whoscored/parsed/<latest>/<whoscored_meta_csv_for_league> \
  data/fotmob/parsed/<latest>/<league_code>/player_stats.csv \
  identity_legends/crosswalk_<League>_final.csv \
  reference_data/other_league_teams_for_<League>.csv   # optional but recommended

# 2. Reconcile anyone the matcher couldn't resolve automatically
python scripts/identity/reconcile_new_players.py \
  reference_data/master_player_table.csv \
  data/opta/parsed/<latest>/<opta_csv_for_league> \
  data/whoscored/parsed/<latest>/<whoscored_meta_csv_for_league> \
  data/fotmob/parsed/<latest>/<league_code>/player_stats.csv \
  identity_legends/reconciled_<League>_final.csv \
  reference_data/other_league_teams_for_<League>.csv   # optional but recommended

# 3. Rebuild the final legend from the crosswalk + reconciled output
python scripts/identity/build_player_legend.py \
  identity_legends/crosswalk_<League>_final.csv \
  identity_legends/reconciled_<League>_final.csv \
  identity_legends/legend_<League>_final.csv \
  reference_data/master_player_table.csv   # optional
```

`build_other_league_teams_reference.py` only needs to be re-run if a
player transfers between the tracked leagues mid-season (it rebuilds
`reference_data/other_league_teams_for_<League>.csv` from the current
WhoScored + FotMob parsed data of the *other* leagues) — not part of the
normal per-matchday cycle:

```bash
python scripts/identity/build_other_league_teams_reference.py \
  reference_data/other_league_teams_for_LaLiga.csv \
  data/whoscored/parsed/<latest>/<whoscored_meta_csv_EPL> \
  data/fotmob/parsed/<latest>/eng_47/player_stats.csv \
  data/whoscored/parsed/<latest>/<whoscored_meta_csv_Ligue1> \
  data/fotmob/parsed/<latest>/fra_53/player_stats.csv \
  data/whoscored/parsed/<latest>/<whoscored_meta_csv_SerieA> \
  data/fotmob/parsed/<latest>/ita_55/player_stats.csv \
  data/whoscored/parsed/<latest>/<whoscored_meta_csv_Bundesliga> \
  data/fotmob/parsed/<latest>/ger_54/player_stats.csv
```

(pairs of `<whoscored_meta_csv>`/`<fotmob player_stats.csv>` for every
league *except* the one you're building the reference for.)

**Bundesliga (5th league) one-time setup:** now that a 5th league is
tracked, this needs to run twice as much as before:
1. Build `other_league_teams_for_Bundesliga.csv`, passing in EPL,
   LaLiga, Ligue1, and SerieA's files (not Bundesliga's own).
2. Re-run it for each of the *existing* four leagues' reference files too,
   adding a Bundesliga WhoScored-meta/FotMob-player_stats pair to each —
   otherwise those four files predate Bundesliga and will wrongly flag any
   Bundesliga-to-{EPL,LaLiga,Ligue1,SerieA} transfer as cross-league.

After that one-time rebuild, Bundesliga folds into the normal per-matchday
cycle above like any other league.

## After scraping: commit

Nothing above commits automatically. Once output looks right, `git add`
the new dated folders and commit as usual — the dated-folder convention
means every matchday's scrape/parse output stays in git history rather
than overwriting the last one.
