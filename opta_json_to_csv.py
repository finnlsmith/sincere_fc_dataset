"""
Parse raw Opta/theanalyst JSON (as produced by grab_data_from_opta_api_2.py) into
one merged per-player CSV per league.

Expects the input directory to contain the raw *_stats_<timestamp>.json files
(one per league) as saved by grab_data_from_opta_api_2.py.

Usage:
    python opta_json_to_csv.py <input_dir> <output_dir>

Example:
    python opta_json_to_csv.py opta_raw_2026-08-18 opta_parsed_2026-08-18
"""

import json
import os
import sys
from collections import defaultdict
from functools import reduce
from pathlib import Path

import pandas as pd

STATS_KEYS = ["attack", "carries", "defending", "goalkeeping", "possession"]


def merge_without_duplicates_and_report(dfs, merge_key="player", stats_keys=STATS_KEYS):
    """
    Merge dataframes while dropping duplicate columns (keeping only from first df).
    Also reports which columns were removed as duplicates.
    """
    if not dfs:
        return pd.DataFrame(), [], {}

    result = dfs[0].copy()
    seen_base_names = set()
    removed_columns = []
    base_names_removed = defaultdict(list)

    for col in result.columns:
        if col == merge_key:
            continue
        for prefix in stats_keys:
            if col.startswith(f"{prefix}_"):
                base_name = col[len(f"{prefix}_"):]
                seen_base_names.add(base_name)
                break

    for df in dfs[1:]:
        cols_to_keep = [merge_key]
        for col in df.columns:
            if col == merge_key:
                continue

            is_duplicate = False
            for prefix in stats_keys:
                if col.startswith(f"{prefix}_"):
                    base_name = col[len(f"{prefix}_"):]
                    if base_name in seen_base_names:
                        is_duplicate = True
                        removed_columns.append(col)
                        base_names_removed[base_name].append(col)
                    else:
                        seen_base_names.add(base_name)
                    break

            if not is_duplicate:
                cols_to_keep.append(col)

        result = pd.merge(result, df[cols_to_keep], on=merge_key, how="outer")

    return result, removed_columns, base_names_removed


def parse_league_json(json_study: dict) -> tuple[str, str, pd.DataFrame]:
    """Parse one league's raw Opta JSON into a single merged, deduped DataFrame."""
    json_study_player = json_study["player"]
    league_name = json_study_player["league"]
    stats_time = json_study_player["lastUpdated"]

    dfs = []
    for key in STATS_KEYS:
        player_stats = json_study_player[key]

        if key == "possession":
            for sub_key in ["chanceCreation", "passing"]:
                if sub_key in player_stats:
                    inner_list = player_stats[sub_key]
                    df = pd.DataFrame(inner_list)
                    df = df.add_prefix(f"{key}_{sub_key}_")
                    if f"{key}_{sub_key}_player" in df.columns:
                        df = df.rename(columns={f"{key}_{sub_key}_player": "player"})
                    dfs.append(df)
        else:
            if isinstance(player_stats, dict) and "overall" in player_stats:
                inner_list = player_stats["overall"]
            else:
                inner_list = player_stats
            df = pd.DataFrame(inner_list)
            df = df.add_prefix(f"{key}_")
            if f"{key}_player" in df.columns:
                df = df.rename(columns={f"{key}_player": "player"})
            dfs.append(df)

    merged_df_clean, removed_columns, base_names_removed = merge_without_duplicates_and_report(
        dfs, merge_key="player", stats_keys=STATS_KEYS
    )

    if "player" in merged_df_clean.columns:
        cols = list(merged_df_clean.columns)
        cols.insert(0, cols.pop(cols.index("player")))
        merged_df_clean = merged_df_clean[cols]

    return league_name, stats_time, merged_df_clean


def opta_json_to_csv(input_dir: str, output_dir: str) -> Path:
    in_dir = Path(input_dir)
    out_dir = Path(output_dir)

    if not in_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {in_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    json_files = [f for f in os.listdir(in_dir) if f.endswith(".json")]
    if not json_files:
        raise ValueError(f"No .json files found in {in_dir}")

    for filename in json_files:
        file_path = in_dir / filename
        with open(file_path, encoding="utf-8") as f:
            json_study = json.load(f)

        if "player" not in json_study:
            print(f"Skipping {filename} (no 'player' key — not a valid Opta stats payload)")
            continue

        league_name, stats_time, merged_df_clean = parse_league_json(json_study)
        print(f"Processed {league_name} ({len(merged_df_clean)} players)")

        out_csv_path = out_dir / f"{league_name}_{stats_time}_merged_df_clean.csv"
        merged_df_clean.to_csv(out_csv_path, index=False)
        print(f"  Saved: {out_csv_path}")

    print(f"\nDone. Output in: {out_dir}")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python opta_json_to_csv.py <input_dir> <output_dir>")
        print("Example: python opta_json_to_csv.py opta_raw_2026-08-18 opta_parsed_2026-08-18")
        sys.exit(1)

    try:
        opta_json_to_csv(sys.argv[1], sys.argv[2])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
