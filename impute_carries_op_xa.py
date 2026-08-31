"""
Impute round-1/round-2 splits for the 11 Opta fields that couldn't be
split via real data (the 10 `carries` fields + `op_xa`) — see
opta_split_triage.md for why these specifically have no path via FotMob
subtraction or WhoScored event data.

METHODOLOGY — read before trusting the output
------------------------------------------------
These are estimates, not observations. Every other field in this pipeline
is either directly measured (FotMob) or reconstructed from real per-match
event data (WhoScored). These 11 fields are NOT — they're a combined
(rounds 1+2) total, proportionally allocated between the two rounds using
a real, match-specific proxy signal, rather than split evenly or guessed.

The proxy: FotMob's actual per-match `Touches` (a player can't carry the
ball without touching it, so this is a tightly-correlated real signal),
falling back to `Minutes played` if touches are unavailable for some
reason, falling back to an even 50/50 split as a last resort if neither
is available for that player. Which method was used for each row is
recorded explicitly in `imputation_source`, so nothing is silently
guessed without a visible flag.

    round_1_estimate = combined_value * (round_1_touches / (round_1_touches + round_2_touches))
    round_2_estimate = combined_value * (round_2_touches / (round_1_touches + round_2_touches))

OUTPUT CONVENTION — do not merge these into the real split files
------------------------------------------------------------------
Every imputed column is suffixed `_imputed_r1` / `_imputed_r2` and kept in
a SEPARATE output file from the genuinely-split, verified stats. Never
copy these into the same columns as real observed data — the suffix and
the separate file are both intentional, load-bearing safeguards against
these being mistaken for real match data later.

Usage:
    python impute_carries_op_xa.py <opta_split_csv> <fotmob_player_stats_csv> <output_csv>

Example:
    python impute_carries_op_xa.py laliga_r1_opta_split.csv esp_87_player_stats.csv laliga_carries_imputed.csv
"""

import sys
from pathlib import Path

import pandas as pd

COMBINED_SUFFIX = "_STILL_COMBINED_R1R2"


def impute_carries_op_xa(opta_split_csv: str, fotmob_player_stats_csv: str, output_csv: str) -> Path:
    print("Loading Opta split data ...")
    opta = pd.read_csv(opta_split_csv)

    combined_cols = [c for c in opta.columns if c.endswith(COMBINED_SUFFIX)]
    if not combined_cols:
        raise ValueError(f"No columns ending in '{COMBINED_SUFFIX}' found — is this really the Opta split output?")
    print(f"  Found {len(combined_cols)} still-combined fields to impute: {[c.replace(COMBINED_SUFFIX, '') for c in combined_cols]}")

    if "fotmob_id" not in opta.columns:
        raise ValueError("Opta split file has no 'fotmob_id' column — needed to link to FotMob's per-match data")

    print("Loading FotMob per-match player stats ...")
    fm = pd.read_csv(fotmob_player_stats_csv)
    for req in ["match_round", "player_id", "Touches", "Minutes played"]:
        if req not in fm.columns:
            raise ValueError(f"FotMob player stats file is missing expected column '{req}'")

    # dtype safety: fotmob_id often comes through as float64 (e.g. 1555492.0)
    # in the Opta split file while FotMob's own player_id is int64
    # (1555492) — pandas won't match those across dtypes, so the merge
    # silently drops real matches without this cast. Do it before the
    # groupby so fm_r1/fm_r2 inherit the corrected dtype too.
    fm["player_id"] = pd.to_numeric(fm["player_id"], errors="coerce").astype("Int64")

    fm_r1 = fm[fm["match_round"] == 1].groupby("player_id", as_index=False)[["Touches", "Minutes played"]].sum()
    fm_r2 = fm[fm["match_round"] == 2].groupby("player_id", as_index=False)[["Touches", "Minutes played"]].sum()
    fm_r1 = fm_r1.rename(columns={"Touches": "touches_r1", "Minutes played": "minutes_r1"})
    fm_r2 = fm_r2.rename(columns={"Touches": "touches_r2", "Minutes played": "minutes_r2"})

    base = opta[["canonical_id", "name", "team", "fotmob_id"] + combined_cols].copy()
    base["fotmob_id"] = pd.to_numeric(base["fotmob_id"], errors="coerce").astype("Int64")

    base = base.merge(fm_r1, left_on="fotmob_id", right_on="player_id", how="left").drop(columns=["player_id"], errors="ignore")
    base = base.merge(fm_r2, left_on="fotmob_id", right_on="player_id", how="left").drop(columns=["player_id"], errors="ignore")

    for c in ["touches_r1", "touches_r2", "minutes_r1", "minutes_r2"]:
        base[c] = base[c].fillna(0)

    # ─── Compute the round-1 weight per player, with a documented fallback chain ──
    def compute_weight(row):
        t1, t2 = row["touches_r1"], row["touches_r2"]
        if (t1 + t2) > 0:
            return t1 / (t1 + t2), "touches"
        m1, m2 = row["minutes_r1"], row["minutes_r2"]
        if (m1 + m2) > 0:
            return m1 / (m1 + m2), "minutes_fallback"
        return 0.5, "even_split_fallback_no_data"

    weights = base.apply(compute_weight, axis=1)
    base["weight_r1"] = [w[0] for w in weights]
    base["imputation_source"] = [w[1] for w in weights]

    n_touches = (base["imputation_source"] == "touches").sum()
    n_minutes = (base["imputation_source"] == "minutes_fallback").sum()
    n_even = (base["imputation_source"] == "even_split_fallback_no_data").sum()
    print(f"\nWeight source breakdown: {n_touches} via touches, {n_minutes} via minutes fallback, "
          f"{n_even} via even-split fallback (no FotMob data found at all for that player in either round)")

    # ─── Apply the weight to every combined field ──────────────────────────────
    for col in combined_cols:
        base_name = col.replace(COMBINED_SUFFIX, "")
        base[f"{base_name}_imputed_r1"] = base[col] * base["weight_r1"]
        base[f"{base_name}_imputed_r2"] = base[col] * (1 - base["weight_r1"])

    out_path = Path(output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.to_csv(out_path, index=False)

    print(f"\nSaved: {out_path} ({len(base)} players, {len(combined_cols)} fields imputed x2 rounds each)")
    print("Reminder: these are estimates (see imputation_source column), not observed data — "
          "keep in this separate file, never merge into the verified split columns.")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python impute_carries_op_xa.py <opta_split_csv> <fotmob_player_stats_csv> <output_csv>")
        sys.exit(1)

    try:
        impute_carries_op_xa(sys.argv[1], sys.argv[2], sys.argv[3])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
