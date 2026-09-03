# LaLiga MD1/MD2 Split — Status

LaLiga's matchday 1 was accidentally played as two rounds (R1/R2). This
folder holds the work to split each of the 4 sources' data cleanly into
per-round tables. Status is **not uniform across sources** — see below
before assuming anything here is finished.

## Opta — done

- `opta/laliga_r1_opta_split.csv`, `opta/laliga_r2_opta_split.csv` — the
  verified per-round split, 389 players each round, 75 columns.
- `opta/laliga_r1_unresolved_identities.csv` (169 rows),
  `opta/laliga_r2_unresolved_identities.csv` (159 rows) — players without
  full Opta identity coverage per round. Real gaps, not bugs.
- `opta/laliga_carries_imputed.csv` (R1), `opta/laliga_r2_carries_imputed.csv`
  (R2) — the 11 fields (10 `carries.overall` fields + `op_xa`) that aren't
  splittable from any source, proportionally imputed from FotMob touches
  data. Kept separate from the real split data on purpose — never merge
  the two.
- `opta/opta_split_triage.md` — the full field-by-field methodology (67
  fields total: 56 resolved directly, 11 confirmed unsplittable).
- `opta/impute_carries_op_xa.py` — the imputation script.

## FotMob — done, no copy needed

FotMob's `esp_87_player_stats.csv` (in `data/fotmob/parsed/`) was always
match-level, with a real `match_round` column. Filter `match_round == 1`
or `match_round == 2` — no separate split file needed here.

## WhoScored — NOT done, don't assume otherwise

`whoscored/md1/` and `whoscored/md2/` each hold 10 per-match folders
(raw event data: `raw_events_<id>.csv` + 13 metric CSVs per match). That's
only step one.

Turning that raw event data into clean, one-row-per-player summary tables
(the WhoScored equivalent of `laliga_r1_opta_split.csv`) happens via
`whoscored_match_metrics.py`, built in a separate thread ("LEARNING TO USE
WHOSCORED EVENT DATA REPO") in the separate `Scrape-Whoscored-Event-Data`
repo/folder — not this one. As of the last check, it had only been proven
on one trial match (`1993897`). The batch run across the other 9 MD1
matches was planned but not confirmed to have happened, and MD2's
equivalent hasn't been started at all.

**So: 20 raw per-match folders present (MD1 x10 + MD2 x10); consolidation
into per-round summary tables via `whoscored_match_metrics.py` is
incomplete/unverified — check the "LEARNING TO USE WHOSCORED EVENT DATA
REPO" thread for status before assuming this is finished.**
