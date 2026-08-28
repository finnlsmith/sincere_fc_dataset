# SincereFC Master Player Table — Data Dictionary

**File:** `master_player_table.csv`
**Rows:** 16,871 (one row per real player)
**Columns:** 350
**Season:** 2025/26, top-5 European leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1) as the primary scope, plus DataMB's wider league coverage folded in at lower confidence.

---

## 1. What this table is

Four independent data sources — **DataMB**, **WhoScored**, **Opta**, and **FotMob** — have been matched together at the player level and combined into one wide table. Each row is one real person; columns from each source that could be matched to that person sit side by side, prefixed by source name.

No player from any source was silently dropped. Where a match could be confirmed, sources sit in the same row. Where a match could not be confirmed, the player still appears — as their own row, clearly labeled — rather than being discarded.

---

## 2. The `confidence_tier` column — read this first

This is the single most important column. It tells you how much cross-source agreement stands behind each row.

| Tier | Rows | Meaning |
|---|---|---|
| `gold` | 1,494 | All 4 sources matched to this player. Highest confidence. |
| `silver` | 986 | 3 of 4 sources matched. |
| `bronze` | 641 | 2 of 4 sources matched (either Opta+FotMob, or Opta+WhoScored). |
| `opta_only` | 24 | Only Opta has this player. Mostly unused squad players with 0 minutes played all season (expected — Opta appears to track full registered squads; the other sources generally only capture players who actually played). |
| `fotmob_only` | 315 | Real player, in FotMob, but never matched to Opta. |
| `whoscored_only` | 11 | Real player, in WhoScored, but never matched to Opta. |
| `fotmob_whoscored_no_opta` | 1 | Matched across FotMob + WhoScored, but not Opta. |
| `fotmob_datamb_no_opta` | 2 | Matched across FotMob + DataMB, but not Opta. |
| `whoscored_datamb_no_opta` | 5 | Matched across WhoScored + DataMB, but not Opta. |
| `datamb_unmatched_top5` | 41 | DataMB player in a top-5 league who could not be matched to Opta (usually a transfer-timing mismatch between sources, or a genuine gap). |
| `datamb_only` | 13,351 | DataMB player in a league **outside** the top-5 scope (Eredivisie, Primeira Liga, and DataMB's broader "PRO" league coverage — e.g. Danish, Colombian leagues). This is out-of-scope by design, not a failed match. |

**Practical guidance:** for anything precision-sensitive, filter to `gold`/`silver`/`bronze`. For broad-coverage work (e.g. total dataset size, checking if a specific player from any league exists at all), the full table is usable, but treat `datamb_only` rows as DataMB's data alone — no cross-verification exists for them.

---

## 3. Column groups

Columns are prefixed by source. Identity/provenance columns are unprefixed.

| Prefix | Column count | Source | Contents |
|---|---|---|---|
| `opta_` | 88 | Opta | Attacking, passing, defending, carries, discipline, and goalkeeping stats (season totals) |
| `fotmob_` | 70 | FotMob | Season totals aggregated from match-by-match data (see §5 on how this was built) |
| `whoscored_` | 6 | WhoScored | Bio/meta only — age, height, weight, position. WhoScored did not provide performance stats in the file used for this build. |
| `datamb_` | 141 | DataMB | Wide per-90 and percentage-based performance metrics |

**Unprefixed identity/provenance columns:**
- `player`, `player_id`, `date_of_birth`, `canon_team` — Opta's identity fields, used as the anchor spine
- `Player`, `Team within selected timeframe`, `Age` — DataMB's own identity fields (kept as-is where DataMB is the primary/only source for a row)
- `has_opta`, `has_fotmob`, `has_whoscored`, `has_datamb` — booleans, which sources contributed to this row
- `n_sources` — count of the above
- `confidence_tier` — see §2
- `reep_id` — see §4

---

## 4. `reep_id` (bonus column, not load-bearing)

`reep_id` is populated for **2,756 of 16,871 rows** (all from the Opta-anchored side of the table). It comes from [Reep](https://reep.football), a free public football-identity crosswalk.

**Important:** Reep was evaluated as a potential backbone for the entire matching process and found to have too little coverage to serve that role (WhoScored coverage in Reep's public v0 register was only ~30% of our actual player pool). The real matching in this table was done via direct name+team+age fuzzy matching between the four sources, not via Reep. `reep_id` is included purely as an optional bonus cross-check/tiebreaker for anyone auditing a specific row later — it is not required for the table to be internally consistent, and its absence on a row says nothing about that row's quality.

---

## 5. Key methodology notes

- **FotMob was originally match-by-match** (one row per player per match). It was aggregated to season totals before matching: counting stats summed, and `FotMob_rating_season` computed as a **minutes-weighted average** (so a 5-minute cameo doesn't count equally to a full 90).
- **Team names were reconciled via a hand-built crosswalk** (`team_crosswalk.json`, 75 entries covering 32 clubs) to handle spelling differences across sources — e.g. "Atlético de Madrid" (Opta) / "Atletico Madrid" (WhoScored) / "Atlético Madrid" (DataMB) all resolve to one canonical name. This crosswalk is specific to the ~100 clubs in scope across the 5 leagues; it does not cover DataMB's non-top-5 clubs (correctly, since those are out of scope).
- **DataMB has no native player ID** — it was matched using a composite key of (initial + surname parsed from DataMB's "F. Surname" format) + team + soft age validation.
- **Name-matching handled several real-world edge cases**: nicknames vs. legal names (e.g. "Cucho Hernández" = "Juan Hernández"), reversed name order for Korean players ("Lee Kang-In" vs "Kang-In Lee"), non-standard Latin characters (German ß, Polish Ł, Turkish İ/ı/ğ), and hyphenated surnames.

---

## 6. Known limitations — read before relying on edge cases

- **B. Dlamini (Polokwane City)** — two DataMB rows exist under this name with a large age gap (29 vs 35). Neither we nor the person building this dataset could confirm whether this is one real player with a data-entry error, or two different real players. Both rows are preserved, unresolved, in `datamb_only`.
- **~5 remaining unresolved cases in the `opta_only` tier** with some playing time (e.g. "Dani Martinez," "Lancinet Kourouma," "Daniel Díaz") could not be confidently matched to any other source despite having real minutes played. Checked directly against FotMob/WhoScored rosters and found no confident match — treated as genuine gaps, not asserted as certain.
- **~34 DataMB-to-Opta unmatched cases** are believed to be transfer-timing mismatches (the two sources were likely snapshotted at slightly different points in a transfer window), not spelling or logic errors.
- **Zé Carlos, K. Hashimoto, S. Jovanović, and other genuine same-name-different-person collisions** were manually researched and confirmed as truly distinct individuals earlier in this project. They appear correctly as separate rows. If you ever see two rows with an identical name and wonder if it's a bug — check here first; it may be a confirmed real collision.
- **WhoScored's overall coverage is lower than the other three sources** (~80% match rate against Opta, vs. ~96% for FotMob) — this reflects WhoScored's own dataset simply containing fewer total players, not a matching-quality gap.
