# sincere_fc_dataset

Season-long data pipeline for the 2026/27 season across four leagues (EPL,
LaLiga, Ligue1, SerieA). It scrapes match and player data from four sources
(FotMob, Opta, WhoScored, DataMB), parses each source's raw output into
CSVs, and resolves player identities across all four sources into one
master crosswalk so per-source stats can be joined together.

**For step-by-step commands to run after each matchday, see
[`SCRAPING_RUNBOOK.md`](SCRAPING_RUNBOOK.md).** This file is orientation —
what's here and why.

## Layout

```
scripts/            one folder per source, the actual pipeline code
  fotmob/
  opta/
  whoscored/
  datamb/
  identity/          cross-source player identity resolution
data/                scraped + parsed output, one folder per source
  <source>/raw/       raw scraped output (JSON, per scrape)
  <source>/parsed/    parsed CSVs (per parse run)
  fixtures/            FotMob fixture lists (one JSON per league/season)
reference_data/      hand-maintained reference inputs the scripts read
identity_legends/    final, current player identity outputs
laliga_md1_md2_split/  one-off project: see its own README
repo_organization_handoff.md   historical note from the Aug 2026 repo cleanup
```

### `scripts/`

Each source folder holds that source's scrape script(s) and its
JSON-to-CSV parser. `scripts/identity/` holds the cross-source matching
pipeline, which reads the parsed CSVs from all four sources plus
`reference_data/master_player_table.csv` and writes into
`identity_legends/`. Full command sequences for all of these are in
`SCRAPING_RUNBOOK.md`.

### `data/`

All scrape and parse output. Every source follows the same shape:
`data/<source>/raw/` for what the scraper writes, `data/<source>/parsed/`
for what the CSV parser writes. Within each, output is auto-dated by the
script itself (e.g. `opta_raw_20260831_140502/`, `parsed_whoscored_2026-08-31/`)
so re-running a scrape never silently overwrites or gets merged into a
previous one — no manual folder naming needed. `data/fixtures/` is the
exception: FotMob's fixture-list JSON, one file per league/season
(`esp_87_2026_2027_fixtures.json`), overwritten in place each time fixtures
are re-fetched, since it's meant to always reflect the current schedule.

### `reference_data/`

Inputs the scripts read rather than produce:
- `master_player_table.csv` (+ `master_player_table_DATA_DICTIONARY.md`) —
  the master player identity table that everything else resolves against.
- `master_leagues.json` — league name/id/key lookup used by the FotMob
  scripts.
- `other_league_teams_for_<League>.csv` — cross-league team reference used
  by the identity pipeline to catch players who moved leagues.

### `identity_legends/`

The current, correct output of the identity pipeline, one set per league
(EPL, LaLiga, Ligue1, SerieA): `crosswalk_<League>_final.csv`,
`crosswalk_<League>_final_CROSS_LEAGUE_REJECTIONS.csv`,
`reconciled_<League>_final.csv`, `legend_<League>_final.csv`. Also holds
`laliga_legend_regression_20_goalkeepers.csv`, a fixture used to check for
regressions on the goalkeeper-exclusion bug, kept here as documentation
rather than run automatically.

### `laliga_md1_md2_split/`

A one-off project, separate from the ongoing weekly pipeline: LaLiga's
matchday 1 was accidentally played as two rounds, so this folder holds the
work to split each source's data cleanly by round. Status differs by
source — see `laliga_md1_md2_split/README.md` before assuming any part of
it is finished.

### `repo_organization_handoff.md`

Kept at the root as a historical record of the August 2026 repo cleanup
(what was stale vs. current at the time, and why). Not required reading
for day-to-day use — `SCRAPING_RUNBOOK.md` and this file supersede it going
forward.

## Conventions worth knowing

- **Run everything from the repo root.** Every script's default paths
  (input and output) are relative to the current working directory, not to
  where the script file lives — running `python scripts/fotmob/foo.py`
  from anywhere other than the repo root will read/write in the wrong
  place.
- **Auto-dated output, with manual override.** Parse scripts accept an
  optional output-dir argument for a one-off/debug run; leave it off for
  normal use so output lands in the standard dated location under `data/`.
- `.gitignore` excludes `__pycache__/`, `*.pyc`, `.DS_Store`, `.venv/`,
  `*.egg-info/` — nothing under `data/` or the CSV outputs is ignored, all
  scraped/parsed data is tracked in git.
