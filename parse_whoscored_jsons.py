"""
Parse raw WhoScored JSON (as produced by whoscored_scrape_update_2.py) into
per-league, per-metric DataFrames plus a player-meta table.

Expects the input directory to contain one subfolder per league, each holding
JSON files named like: <LeagueKey>_<season>_<category>_<subcategory>.json
e.g. "EPL_2025_26_goals_situations.json"
(this matches the raw_json_<date>/ output of whoscored_scrape_update_2.py)

Usage:
    python parse_whoscored_jsons.py <input_dir> <output_dir>

Example:
    python parse_whoscored_jsons.py raw_json_2026-08-18 parsed_whoscored_2026-08-18
"""

import json
import os
import pickle
import sys
from pathlib import Path

import pandas as pd

META_COLS = [
    "name", "playerId", "teamId", "teamName",
    "age", "height", "weight", "positionText",
]


def parse_whoscored_jsons(input_dir: str, output_dir: str) -> Path:
    in_dir = Path(input_dir)
    out_dir = Path(output_dir)

    if not in_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {in_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    league_folders = [f for f in os.listdir(in_dir) if (in_dir / f).is_dir()]

    if not league_folders:
        raise ValueError(f"No league subfolders found in {in_dir}")

    for league_folder in league_folders:
        raw_dir = in_dir / league_folder
        print(f"\nProcessing: {league_folder}")

        json_files = [f for f in os.listdir(raw_dir) if f.endswith(".json")]

        dfs_by_metric = {}
        player_meta = None

        for fname in json_files:
            file_path = raw_dir / fname

            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            if "playerTableStats" not in data:
                print(f"  Skipping {fname} (no playerTableStats)")
                continue

            df = pd.DataFrame(data["playerTableStats"])
            df = df.loc[:, ~df.columns.duplicated()]

            base_name = os.path.splitext(fname)[0]
            parts = base_name.split("_")

            # e.g. "EPL_2025_26_goals_situations" -> season="EPL_2025_26", metric="goals_situations"
            season = "_".join(parts[:3])
            metric = "_".join(parts[3:])

            stat_cols = [c for c in df.columns if c not in META_COLS]

            if player_meta is None:
                player_meta = df[META_COLS].drop_duplicates()
                player_meta["season"] = season

            metric_df = df[["name", "teamId"] + stat_cols].copy()
            metric_df["metric"] = metric
            metric_df["season"] = season

            dfs_by_metric.setdefault(metric, []).append(metric_df)

        if not dfs_by_metric:
            print(f"  No usable data found for {league_folder}, skipping save")
            continue

        dfs_by_metric = {
            k: pd.concat(v, ignore_index=True)
            for k, v in dfs_by_metric.items()
        }

        safe_name = league_folder.replace(" ", "_").replace(",", "")

        pkl_path = out_dir / f"{safe_name}_dfs_by_metric.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump(dfs_by_metric, f)

        if player_meta is not None:
            meta_path = out_dir / f"{safe_name}_player_meta.csv"
            player_meta.to_csv(meta_path, index=False)

        print(f"  Saved: {safe_name} ({len(dfs_by_metric)} metrics, "
              f"{len(player_meta) if player_meta is not None else 0} players)")

    print(f"\nDone. Output in: {out_dir}")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python parse_whoscored_jsons.py <input_dir> <output_dir>")
        print("Example: python parse_whoscored_jsons.py raw_json_2026-08-18 parsed_whoscored_2026-08-18")
        sys.exit(1)

    try:
        parse_whoscored_jsons(sys.argv[1], sys.argv[2])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
