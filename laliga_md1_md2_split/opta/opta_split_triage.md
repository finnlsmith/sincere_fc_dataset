# Opta LaLiga Round-1 Stat-Split Triage — Field by Field

**Key correction to the V1 hypothesis:** FotMob's `esp_87_player_stats.csv` is
already match-level, not cumulative — it carries a real `match_round` column
(452 rows for round 1, 455 for round 2, one row per player per match).
So every "FotMob" bucket below means **filter `match_round == 1`**, not
subtract round 2 from combined. Simpler and safer (no risk of a squad/appearance
mismatch between rounds corrupting a subtraction).

Legend:
- **FOTMOB** — direct column, isolate via `match_round==1` filter, no other work needed
- **FOTMOB†** — FotMob column exists but naming/definition needs a quick check against Opta's definition before trusting it
- **WS** — needs WhoScored round-1 event data (already being pulled in the parallel thread)
- **WS?** — plausible via WhoScored event qualifiers, but unverified — needs a check against `whoscored_match_metrics.py` / `METRIC_COLUMN_MAP` or raw event inspection
- **HYBRID** — base number from FotMob, but a WhoScored tag is needed to carve out a sub-case (e.g. penalties)
- **DERIVED** — pure arithmetic once its inputs are settled, no new sourcing needed
- **NONE** — not splittable with either source; flag as still combined R1+R2

---

## attack.overall (7 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `goals` | FOTMOB | `Goals` |
| `xg` | FOTMOB | `Expected goals (xG)` |
| `goals_vs_xg` | DERIVED | `goals − xg` once both split |
| `shots` | FOTMOB | `Total shots` |
| `shots_on_target` | FOTMOB | `Shots on target` |
| `shot_conv` | DERIVED | `goals / shots` |
| `xg_per_shot` | DERIVED | `xg / shots` |

## attack.nonPenalty (7 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `np_goals` | FOTMOB | `Goals` (R1) minus penalty goals — `esp_87_shots.csv`, `situation=='Penalty'` rows, R1 has exactly 4, all `eventType=='Goal'`, one per named player |
| `np_xg` | FOTMOB | `xG Non-penalty` — exists directly, no penalty math needed |
| `np_goals_vs_xg` | DERIVED | once `np_goals`/`np_xg` settled |
| `np_shots` | FOTMOB | `Total shots` (R1) minus the same 4 penalty-shot rows per player |
| `np_shots_on_target` | FOTMOB | `Shots on target` (R1) minus the same 4 — all 4 are confirmed on-target (they're goals), so safe to subtract |
| `np_shot_conv` | DERIVED | once above settled |
| `np_xg_per_shot` | DERIVED | once above settled |

*Resolved via `esp_87_shots.csv` (shot-by-shot shotmap with a `situation` field). Shot counts from this file were cross-validated against `esp_87_player_stats.csv`'s `Total shots` — exact match for all 452 R1 players — so it's trustworthy for identifying which specific shots were penalties. No WhoScored dependency after all.*
*On-target definition note: this file's raw `isOnTarget` flag does NOT match the player-stats file's `Shots on target` aggregate on its own (52/452 players differed — blocked shots were sometimes flagged on-target). Filtering `isOnTarget==True AND isBlocked==False` instead reproduces `Shots on target` exactly, 0/452 mismatches. Use that combined filter for any on-target logic from this file, not the raw flag alone.*

## possession.chanceCreation (8 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `chances_created` | FOTMOB | `Chances created` |
| `op_chances_created` | WS — VERIFIED | sum of `keyPass*` flattened columns from raw WhoScored events, **excluding** `keyPassCorner` and `keyPassFreekick`. Checked `keyPassFreekick` against the raw `qualifiers` JSON's genuine `FreekickTaken` tag — matches exactly (6/6), so this flattened column is trustworthy (unlike `passFreekick`, see below). R1 league total: 168. |
| `chances_per_100_pass` | DERIVED | once `chances_created` + `passes` split |
| `chances_sp_op_ratio` | DERIVED | once `op_chances_created` settled |
| `xa` | FOTMOB | `Expected assists (xA)` |
| `op_xa` | NONE | no open-play-only xA anywhere in FotMob, and WhoScored doesn't track xG/xA at all (confirmed in handoff) — not splittable |
| `assists` | FOTMOB | `Assists` |
| `op_assists` | WS — VERIFIED | `assist==1` excluding `assistCorner==1`/`assistFreekick==1`. R1 total: 17 (all assists this round happened to be open-play — 0 corner/freekick assists occurred, so this round it equals total `assist`, but the exclusion logic is real and will matter in rounds with set-piece assists). |

## possession.passing (12 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `passes` | FOTMOB | `Passes attempted` |
| `successful_passes` | FOTMOB | `Accurate passes` |
| `pass_perc` | DERIVED | |
| `total_final_third_passes` | WS — VERIFIED | WhoScored `Pass` events with `x < 66.7` and `endX ≥ 66.7` (i.e. the pass starts outside the final third and crosses into it — not just any pass ending inside it, which was a wrong first guess that overcounted by ~2.7x). Confirmed `x`/`endX` are already normalized to "always attacking toward 100" regardless of team/half (checked clearance-event x-position stays low for every team in both halves across all 10 matches — no halftime flip). League total: 1,068, vs FotMob's own `Passes into final third` aggregate of 1,070 — 2-pass gap, within normal cross-provider noise, confirming this is the right definition. |
| `successful_final_third_passes` | WS — VERIFIED | same filter + `outcomeType=='Successful'` |
| `ft_pass_perc` | DERIVED | now computable from the two above |
| `op_crosses` | WS — VERIFIED | raw `qualifiers` JSON `Cross` tag, excluding rows also tagged `CornerTaken` or `FreekickTaken`. **Do not use the flattened `passFreekick` column** — see data-quality note below. R1 league total: 210. |
| `successful_op_crosses` | WS — VERIFIED | same filter + `passCrossAccurate==1`. R1 total: 38. |
| `cross_perc` | DERIVED | once above settled |
| `through_balls` | WS — VERIFIED | `passThroughBallAccurate` + `passThroughBallInaccurate` (raw tag count matches exactly, 35/35 — this flattened column is reliable). R1 total: 35. |
| `successful_through_balls` | WS — VERIFIED | `passThroughBallAccurate`. R1 total: 13. |
| `through_ball_perc` | DERIVED | once above two settled |

> **Data-quality finding — `passFreekick` flattened column is mismapped.** It's set to `1` on the exact same 89 rows as `passCornerAccurate`/`passCornerInaccurate` (89/89 identical across all 10 matches) — it's tagging corner events, not free kicks. The raw `qualifiers` JSON has a genuine `FreekickTaken` tag (282 real instances), 18 of which are crosses that `passFreekick` completely misses. Using the buggy column would have put `op_crosses` at 228 instead of the correct 210 (~8% overcount). **`keyPassFreekick` and `assistFreekick` do not have this bug** — `keyPassFreekick` matches the genuine tag exactly (6/6 checked). Only the general `passFreekick` column is affected; anything touching free-kick exclusion should parse the raw `qualifiers` field directly, not trust that one flattened column.

> **Data-quality finding — Opta's own combined discipline totals have gaps for low-minute players.** Cross-checking the WhoScored R1 card counts against Opta's combined (R1+R2) `defending.discipline` table (as a "R1 split shouldn't exceed combined" sanity ceiling) turned up 4 players where it does: `Johaneko Louis-Jean`, `Jonathan Dubasin`, `Xavi Espart`, `Marcos Alonso`. All 4 are real, clearly-tagged `type=='Card'` events in the raw WhoScored data (proper `cardType`, correct match/period) — not a parsing artifact. Opta's combined record for `Johaneko Louis-Jean` even shows `apps=0, mins=0`, despite him clearly having played and been booked. This looks like Opta's own source data undercounting these players (likely deep-bench/late-sub players), not an error in the WhoScored derivation. Worth knowing before treating Opta's combined totals as ground truth for validation elsewhere in the pipeline.

## carries.overall (10 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `carries`, `carry_distance`, `progressive_carries`, `progressive_distance`, `shot_ending`, `goal_ending`, `chance_ending`, `assist_ending`, `dist_per_carry`, `dist_per_progressive_carry` | **NONE** (all 10) | FotMob has zero carry-tracking columns; WhoScored has no ball-carry/progression metric (confirmed in handoff — it's a tracking-data-adjacent Opta metric neither source reconstructs). Flag entire block as still R1+R2 combined. |

## defending.overall (11 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `tackles` | FOTMOB | `Tackles` |
| `interceptions` | FOTMOB | `Interceptions` |
| `recoveries` | FOTMOB | `Recoveries` |
| `blocks` | FOTMOB | `Blocks` |
| `clearances` | FOTMOB | `Clearances` |
| `ground_duels` | FOTMOB | `Ground duels` |
| `ground_duels_won` | FOTMOB | `Ground duels won` |
| `ground_duel_perc` | DERIVED | |
| `aerial_duels` | FOTMOB | `Aerial duels` |
| `aerial_duels_won` | FOTMOB | `Aerial duels won` |
| `aerial_duel_perc` | DERIVED | |

## defending.discipline (5 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `yellows` | WS — VERIFIED | `yellowCard==1` count on raw WhoScored events (`voidYellowCard` correctly excluded — 0 instances this round anyway). R1 league total: 46. |
| `reds` | WS — VERIFIED | `redCard==1` OR `secondYellow==1`. R1 total: 3. |
| `fouls_commited` | FOTMOB | `Fouls committed` |
| `pens_conceded` | FOTMOB | `Conceded penalty` |
| `offsides` | FOTMOB | `Offsides` |

## goalkeeping.overall (7 fields)
| Field | Bucket | Source field / logic |
|---|---|---|
| `ogs` | FOTMOB | `esp_87_shots.csv`'s `isOwnGoal` is `False` for all 465 rows (both rounds) — resolves to 0 for every keeper in R1. Cross-checked against the raw Opta JSON: every goalkeeper's combined-season `ogs` is already 0, consistent with zero own goals happening in these matches at all. No WhoScored needed. |
| `goals_conceded` | FOTMOB | `Goals conceded` |
| `saves_made` | FOTMOB | `Saves` |
| `save_perc` | DERIVED | |
| `goals_prevented` | FOTMOB | `Goals prevented` |
| `goals_prevented_rate` | DERIVED | once `goals_prevented` + `xgot_conceded` split — confirm Opta's exact formula (likely `goals_prevented / xgot_conceded`) before deriving |
| `xgot_conceded` | FOTMOB | `xGOT faced` |

---

## Summary counts (updated after `esp_87_shots.csv` and raw WhoScored event data)

| Bucket | Count | Notes |
|---|---|---|
| FOTMOB (direct filter / resolved) | 28 | zero WhoScored dependency — filter, subtract penalty rows where relevant, or rename |
| FOTMOB† (verify definition first) | 2 | `total_final_third_passes`, `successful_final_third_passes` — still open |
| DERIVED | 15 | pure arithmetic once inputs above are in place |
| WS — VERIFIED | 8 | `through_balls`, `successful_through_balls`, `yellows`, `reds`, `op_chances_created`, `op_assists`, `op_crosses`, `successful_op_crosses` — all computed and cross-checked against the 10 R1 raw event files |
| WS? (unverified) | 0 | *(was 4 — all resolved this pass)* |
| HYBRID | 0 | |
| NONE (not splittable) | 11 | all 10 `carries.overall` fields + `op_xa` |

67 fields total. **56 of 67 are now fully resolved** (28 FOTMOB + 15 DERIVED + 8 WS + the trivially-resolved `ogs`/penalty fields folded into the FOTMOB count above), 2 need a quick definition check, and 11 are confirmed unsplittable with current sources.

## Open item before batch execution across all 449 players

Spot-checked whether FotMob/Opta/WhoScored player IDs line up for a direct join — **they don't**. Three separate ID systems (Opta `player_id`, FotMob `player_id`, WhoScored `playerId`), and a name-based join has real gaps (e.g. `Kiko`, `Antonio Sivera`, `David Soria` didn't resolve against Opta's name field on a first pass — likely nickname/short-name formatting differences, not genuinely missing players). The card cross-check above only worked because I did a manual name-list comparison for ~46 players; doing that reliably across all 449 players for every FOTMOB/WS field needs an actual crosswalk, not a fragile name-string join, or attribution errors will land silently in the pipeline.

If the parallel WhoScored thread already built a player-identity crosswalk (as distinct from its metric column mapping), that's the thing to reuse here before running Phase 2 batch execution.
