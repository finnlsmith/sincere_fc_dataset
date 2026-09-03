"""
Parse raw WhoScored JSON (as produced by whoscored_scrape_update_2.py) into
per-league, per-metric DataFrames plus a player-meta table.

Expects the input directory to contain JSON files directly (flat, no
subfolders), named like: <LeagueKey>_<season>_<category>_<subcategory>.json
e.g. "EPL_2026_27_goals_situations.json"
(this matches the raw_json_<date>/ output of whoscored_scrape_update_2.py)

Usage:
    python parse_whoscored_jsons.py <input_dir> [output_dir]

If output_dir is omitted, defaults to parsed_whoscored_<today's date>, to
avoid manual output-folder naming drift (the same kind of mismatch that
produced opta_json_to_csv.py's 2026-08-28 / retest / retest2 duplicate-
folder mess earlier this season). Pass an explicit output_dir to override,
e.g. for a deliberate one-off reparse during debugging.

Example:
    python parse_whoscored_jsons.py data/whoscored/raw/whoscored_raw_json_2026-08-27
    python parse_whoscored_jsons.py data/whoscored/raw/whoscored_raw_json_2026-08-27 data/whoscored/parsed/parsed_whoscored_manual_debug_run
"""

import json
import os
import pickle
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

META_COLS = [
    "name", "playerId", "teamId", "teamName",
    "age", "height", "weight", "positionText",
]


def parse_whoscored_jsons(input_dir: str, output_dir: str | None = None) -> Path:
    in_dir = Path(input_dir)
    if output_dir is None:
        output_dir = f"data/whoscored/parsed/parsed_whoscored_{datetime.now().strftime('%Y-%m-%d')}"
    out_dir = Path(output_dir)

    if not in_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {in_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    json_files = [f for f in os.listdir(in_dir) if f.endswith(".json")]

    if not json_files:
        raise ValueError(f"No .json files found in {in_dir}")

    # Group files by league, inferred from the filename prefix (everything
    # before the season component), since the scraper saves flat files
    # rather than one subfolder per league.
    files_by_league = defaultdict(list)
    for fname in json_files:
        base_name = os.path.splitext(fname)[0]
        parts = base_name.split("_")
        if len(parts) < 4:
            print(f"  Skipping {fname} (unexpected filename format)")
            continue
        league_name = parts[0]
        files_by_league[league_name].append(fname)

    if not files_by_league:
        raise ValueError(f"No usable JSON filenames found in {in_dir}")

    for league_name, fnames in files_by_league.items():
        print(f"\nProcessing: {league_name} ({len(fnames)} files)")

        dfs_by_metric = {}
        player_meta = None
        season = None

        for fname in fnames:
            file_path = in_dir / fname

            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            if "playerTableStats" not in data:
                print(f"  Skipping {fname} (no playerTableStats)")
                continue

            df = pd.DataFrame(data["playerTableStats"])
            df = df.loc[:, ~df.columns.duplicated()]

            base_name = os.path.splitext(fname)[0]
            parts = base_name.split("_")

            # e.g. "EPL_2026_27_goals_situations" -> season="2026_27", metric="goals_situations"
            season = "_".join(parts[1:3])
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
            print(f"  No usable data found for {league_name}, skipping save")
            continue

        dfs_by_metric = {
            k: pd.concat(v, ignore_index=True)
            for k, v in dfs_by_metric.items()
        }

        pkl_path = out_dir / f"{league_name}_{season}_dfs_by_metric.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump(dfs_by_metric, f)

        if player_meta is not None:
            meta_path = out_dir / f"{league_name}_{season}_player_meta.csv"
            player_meta.to_csv(meta_path, index=False)

        print(f"  Saved: {league_name} ({len(dfs_by_metric)} metrics, "
              f"{len(player_meta) if player_meta is not None else 0} players)")

    print(f"\nDone. Output in: {out_dir}")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage: python parse_whoscored_jsons.py <input_dir> [output_dir]")
        print("Example: python parse_whoscored_jsons.py data/whoscored/raw/whoscored_raw_json_2026-08-27")
        print("         python parse_whoscored_jsons.py data/whoscored/raw/whoscored_raw_json_2026-08-27 data/whoscored/parsed/parsed_whoscored_manual_debug_run")
        sys.exit(1)

    try:
        output_dir = sys.argv[2] if len(sys.argv) == 3 else None
        parse_whoscored_jsons(sys.argv[1], output_dir)
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
