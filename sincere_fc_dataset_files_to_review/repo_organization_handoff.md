# SincereFC — Repo Organization Handoff (for Claude Desktop)

## Context

A full season-pipeline (4 sources: FotMob, WhoScored, Opta, DataMB) has been
built and debugged across many chat sessions. Separately, a one-off deep-dive
project split LaLiga's accidentally-double-round matchday-1 data into clean
MD1/MD2 splits across all three active sources. Both are now functionally
complete. This doc is a full inventory to use for repo cleanup — organizing
what's needed, identifying what's safe to delete, and locating where things
actually live.

**Important: there are TWO separate repos/folders in play, not one:**
1. **Main pipeline repo** (`sincere_fc_regular_scrape_sources` or similar —
   the one used all season) — the weekly scraper/identity pipeline
2. **A separate local folder for the WhoScored event-data SDK**
   (`Scrape-Whoscored-Event-Data`) — used only for the LaLiga MD1/MD2
   splitting side-project, contains its own scripts, not part of the main
   pipeline

---

## 1. Core pipeline scripts — KEEP, these are the real infrastructure

All confirmed working and current as of the last session. Each should be a
single, canonical copy in the main repo — no duplicates, no `_v2`/`_final`/
`_retest` suffixed variants sitting around.

**FotMob:**
- `fetch_fixtures.py` — pulls fixture lists per league/season
- `scrape_match_details.py` — scrapes per-match JSON (skips already-scraped matches)
- `fotmob_json_to_csv.py` — parses raw match JSON into player_stats/shots/team_stats CSVs, organized `parsed_fotmob/<date>/<league_code>/`

**WhoScored (season-aggregate scraper, separate from the event-data tool below):**
- `whoscored_scrape_update_2.py` — scrapes season-cumulative situational stats, automated (no manual pause), season-label auto-derived from URL
- `parse_whoscored_jsons.py` — parses raw JSON into per-league `dfs_by_metric.pkl` + `player_meta.csv`

**Opta:**
- `grab_data_from_opta_api_2.py` — scrapes theanalyst.com, shared context across leagues, EPL placeholder needs its `tmcl_id`/`post_id` filled in (see TODO in the file itself)
- `opta_json_to_csv.py` — parses raw JSON, coalesces `opta_player_id`/`opta_team_id`/`opta_player_uuid`/`opta_team_uuid` across ALL Opta categories (fixes the goalkeeper-exclusion bug — goalkeepers aren't in Opta's "attack" category)

**DataMB (paused — provider hasn't rolled over to 2026/27 yet):**
- `scrape_datamb.py` — no auth needed, works whenever DataMB updates; check back periodically via the DevTools method from earlier in the season rather than assuming it's still broken

**Identity/matching pipeline (the biggest piece of debugging this season):**
- `match_players_to_master.py` — direct native-ID join against `master_player_table.csv`, includes the cross-league safeguard (rejects a match if the master row's team belongs to a different league entirely — catches stale data-entry errors like Rodri/Gulácsi/Bayındır)
- `reconcile_new_players.py` — fuzzy name+team clustering for players not in the master table, same cross-league safeguard applied consistently
- `build_player_legend.py` — final consolidation: conflict detection (never silently overwrites a disputed ID) + cross-pool merging (stitches together players matched via one source but not another)
- `build_other_league_teams_reference.py` — helper that builds the `other_league_teams_for_<League>.csv` reference files the cross-league safeguard needs (run once per league, using the *other* leagues' data, never that league's own)

**Reference data files (not scripts, but load-bearing):**
- `master_player_table.csv` + `master_player_table_DATA_DICTIONARY.md` — the season-opening identity crosswalk (2025/26-based)
- `master_leagues.json` — FotMob's full competition/league ID catalog

---

## 2. The FINAL, correct identity legends — one set, dated, keep only these

The identity pipeline was re-run multiple times this season as bugs were
found and fixed. **Only the most recent run (after the goalkeeper-coalescing
fix AND the cross-league-safeguard-consistency fix) is correct.** Everything
before it should be deleted, not archived — it's confirmed stale, not just
old.

**Keep (the final, fully-verified versions):**
- `legend_EPL_final.csv` — 398 players (290 existing / 87 new-linked / 21 unverified)
- `legend_LaLiga_final.csv` — 481 players (326 existing / 117 new-linked / 38 unverified)
- `legend_Ligue1_final.csv` — 361 players (243 existing / 102 new-linked / 16 unverified)
- `legend_SerieA_final.csv` — 473 players (324 existing / 118 new-linked / 31 unverified)

Along with each league's matching `crosswalk_<League>_final.csv`,
`reconciled_<League>_final.csv`, and `crosswalk_<League>_final_CROSS_LEAGUE_REJECTIONS.csv`
(the rejections file is useful reference — shows exactly which players were
caught by the safeguard and why).

**Safe to delete — earlier, superseded runs (any of these naming patterns):**
- `legend_LaLiga_2026-08-28.csv` (pre-goalkeeper-fix)
- `legend_LaLiga_REGENERATED.csv`, `legend_LaLiga_test*.csv`, `legend_LaLiga_local*.csv`
- `crosswalk_LaLiga_2026-08-28.csv`, `crosswalk_LaLiga_retest.csv`, `crosswalk_LaLiga_test*.csv`
- `reconciled_LaLiga_2026-08-28.csv`, `reconciled_LaLiga_retest.csv`, `reconciled_LaLiga_test*.csv`
- Any `_CONFLICTS.csv` files from earlier runs (none should exist for the final versions — if one's sitting around, it's from a stale run)
- `opta_parsed_2026-08-28/` (superseded by `opta_parsed_LaLiga_retest2/`, which has the goalkeeper-fixed data for ALL 4 leagues despite the LaLiga-specific folder name)
- `opta_parsed_LaLiga_retest/` (the intermediate retest — has `opta_player_id` but not `opta_team_id`; superseded by `retest2`)

**Note on `opta_parsed_LaLiga_retest2/`:** despite the name, this folder
contains the correctly re-parsed Opta data for **all 4 leagues**, not just
LaLiga (confirmed — the parser processes every JSON in the raw folder in one
pass). Worth renaming to something like `opta_parsed_final/` during cleanup
so the name doesn't mislead anyone later.

---

## 3. LaLiga MD1/MD2 split data — scattered across multiple locations, needs consolidating

This is the messiest part to organize, since it was built across two
separate chat threads with different working directories. Locations as of
the last session:

**WhoScored (100% split, all 20 matches, both rounds):**
- Lives in the **separate** `Scrape-Whoscored-Event-Data` folder, not the
  main pipeline repo
- `la liga MD 1 data/<match_id>/` — one folder per MD1 match (10 folders),
  each with `raw_events_<id>.csv` + 13 metric CSVs
- `la liga MD 2 data/<match_id>/` — same structure for MD2 (10 folders)
- Also in that folder: `whoscored_match_metrics.py`, `whoscored_batch_extract.py`,
  `whoscored_batch_extract_md2.py`, `whoscored_event_diagnostic.py` — these
  are WhoScored-event-specific tools, separate from `whoscored_scrape_update_2.py`
  in the main pipeline (different approach — event-level vs season-aggregate)

**Opta (56/67 fields genuinely split, 11/67 imputed):**
- `laliga_r1_opta_split.csv` / `laliga_r2_opta_split.csv` — the real,
  verified split (389 players each round)
- `laliga_r1_unresolved_identities.csv` / `laliga_r2_unresolved_identities.csv`
  — the ~160-170 players per round without full Opta coverage (real gaps,
  not bugs — see the reason-category breakdown in each file)
- `laliga_carries_imputed.csv` (MD1) / `laliga_r2_carries_imputed.csv` (MD2)
  — the 11 unsplittable fields (carries family + `op_xa`), proportionally
  imputed using FotMob touches data, clearly labeled with an
  `imputation_source` column — **keep these in a clearly-separate location
  from the real split data**, never merge into the same file
- `opta_split_triage.md` — the full field-by-field methodology doc (67
  fields, which bucket each fell into) — worth keeping as documentation
  even though the work itself is done

**FotMob (100%, was always match-level, no extra work needed):**
- Already split by nature — just filter `esp_87_player_stats.csv` by
  `match_round == 1` or `match_round == 2`

**Suggested consolidation for the cleanup:** create one clear folder, e.g.
`laliga_md1_md2_split/`, with subfolders `whoscored/`, `opta/`, `fotmob/`
(or just a note pointing at where FotMob's filter lives), so this doesn't
stay scattered across two repos and multiple loose CSVs in a downloads
folder.

---

## 4. What's still genuinely open (not done, not blocking, just not started)

- **Scheduler** — the piece that watches fixtures and auto-triggers weekly
  scrapes after each matchday. Never built.
- **Status tracker / dashboard** — never built.
- **Bundesliga** — hasn't started this season yet; `whoscored_scrape_update_2.py`
  and the Opta/FotMob scripts will just correctly return 0 finished matches
  until it does. Nothing broken, nothing to do yet.
- **DataMB** — paused, provider hasn't rolled the "CURRENT" dataset over to
  2026/27 yet. Check every week or two via DevTools on their site (same
  method as originally discovering the URL pattern) rather than assuming
  it's still stuck.
- **The ~11-38 unresolved players per league** in each legend (the
  `new_unverified` status) — expected to shrink over time as Opta/WhoScored's
  own tracking catches up on newly-promoted clubs and summer transfers.
  Worth periodically re-running the 3-script identity chain to pick up new
  links, not something to chase manually right now.

---

## 5. Suggested cleanup checklist for Claude Desktop

1. Confirm which repo is "the" repo going forward — recommend merging the
   WhoScored event-data folder's *outputs* (the MD1/MD2 data + the split
   CSVs) into the main pipeline repo, even if the SDK/scripts themselves
   stay separate (they're a different tool, reasonable to keep apart)
2. Delete every superseded legend/crosswalk/reconciled file per the list in
   section 2 — keep only the `_final` versions
3. Delete `opta_parsed_2026-08-28/` and `opta_parsed_LaLiga_retest/`,
   rename `opta_parsed_LaLiga_retest2/` to something accurate
4. Consolidate the LaLiga MD1/MD2 split outputs into one clear location per
   section 3's suggestion
5. Confirm all "core pipeline scripts" from section 1 exist as a single
   canonical copy each, no stray duplicates from earlier debugging sessions
6. Leave `opta_split_triage.md` and this handoff doc as documentation —
   worth keeping even after cleanup, since they explain *why* things are
   structured the way they are
