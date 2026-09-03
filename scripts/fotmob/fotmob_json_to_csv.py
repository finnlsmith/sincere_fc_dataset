"""
Parse raw FotMob match-detail JSON (as produced by scrape_match_details.py)
into per-player-per-match, per-shot, and per-team-stat-category CSVs.

Expects the input directory to contain one JSON file per match, as saved by
scrape_match_details.py (i.e. data/fotmob/raw/<league_key>/<match_id>.json).

Output granularity is match-level, not season-aggregated — this is
deliberate: FotMob is the pipeline's only true timeline source, so keeping
one row per player per match (rather than summing to a season total) is
what makes the rest/fatigue and per-round splits work downstream.

Output is organized as:
    <output_base_dir>/<date>/<league_code>/<table_name>.csv
so each league gets its own folder, and different scrape dates don't
collide or overwrite each other.

Usage:
    python fotmob_json_to_csv.py <input_dir> [output_base_dir]

If output_base_dir is omitted, defaults to "data/fotmob/parsed". The league code
is derived automatically from the input directory's folder name (e.g.
"eng_47_2026_2027"), and today's date is used for the dated subfolder.

Example:
    python fotmob_json_to_csv.py data/fotmob/raw/eng_47_2026_2027
    # -> data/fotmob/parsed/2026-08-28/eng_47_2026_2027/player_stats.csv, etc.

    python fotmob_json_to_csv.py data/fotmob/raw/eng_47_2026_2027 data/fotmob/parsed
"""

import sys
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

RENAME_MAP = {
    'Accurate passes_total':      'Passes attempted',
    'Accurate long balls_total':  'Long balls attempted',
    'Aerial duels won_total':     'Aerial duels',
    'Ground duels won_total':     'Ground duels',
    'Shot accuracy_total':        'Shots taken',
    'Successful dribbles_total':  'Dribbles attempted',
    'Accurate crosses_total':     'Crosses attempted',
}


def fotmob_json_to_csv(input_dir: str, output_base_dir: str | None = None) -> Path:
    raw_dir = Path(input_dir)

    if not raw_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {raw_dir}")

    # League code derived from the input folder's own name, e.g.
    # "data/fotmob/raw/eng_47_2026_2027" -> "eng_47_2026_2027"
    league_code = raw_dir.name

    if output_base_dir is None:
        output_base_dir = "data/fotmob/parsed"

    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(output_base_dir) / today / league_code
    out_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(raw_dir.glob("*.json"))
    if not json_files:
        raise ValueError(f"No .json files found in {raw_dir}")

    print(f"League:  {league_code}")
    print(f"Found {len(json_files)} JSON files\n")

    all_shots = []
    all_player_stats = []
    all_team_stats = defaultdict(list)
    skipped = 0
    warnings = []

    for path in json_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        general = data.get("pageProps", {}).get("general", {})

        if not general.get("finished"):
            skipped += 1
            continue

        meta = {
            "match_id":     general.get("matchId"),
            "match_date":   general.get("matchTimeUTCDate"),
            "match_round":  general.get("matchRound"),
            "league_name":  general.get("leagueName"),
            "home_team":    general.get("homeTeam", {}).get("name"),
            "home_team_id": general.get("homeTeam", {}).get("id"),
            "away_team":    general.get("awayTeam", {}).get("name"),
            "away_team_id": general.get("awayTeam", {}).get("id"),
        }

        content = data.get("pageProps", {}).get("content", {})

        # --- Shotmap ---
        try:
            shots = content["shotmap"]["shots"]
            for shot in shots:
                all_shots.append({**meta, **shot})
        except (KeyError, TypeError):
            warnings.append(f"No shotmap: {path.name}")

        # --- Team stats ---
        try:
            full_match = content["stats"]["Periods"]["All"]
            for group in full_match["stats"]:
                group_name = group["title"]
                for stat in group["stats"]:
                    if stat["stats"][0] is None:
                        continue
                    all_team_stats[group_name].append({
                        **meta,
                        "stat": stat["title"],
                        "home": stat["stats"][0],
                        "away": stat["stats"][1],
                    })
        except (KeyError, TypeError):
            warnings.append(f"No team stats: {path.name}")

        # --- Player stats (one row per player per match) ---
        try:
            player_stats = content["playerStats"]
            for player_id, player in player_stats.items():
                row = {
                    **meta,
                    "player_id":     player_id,
                    "player_name":   player["name"],
                    "team_name":     player["teamName"],
                    "team_id":       player["teamId"],
                    "is_goalkeeper": player["isGoalkeeper"],
                }
                for section in player["stats"]:
                    for stat_name, stat_info in section["stats"].items():
                        stat_obj = stat_info["stat"]
                        row[stat_name] = stat_obj.get("value")
                        if stat_obj.get("total") is not None:
                            row[f"{stat_name}_total"] = stat_obj["total"]
                all_player_stats.append(row)
        except (KeyError, TypeError):
            warnings.append(f"No player stats: {path.name}")

    if warnings:
        print(f"⚠️  {len(warnings)} warning(s) during parse:")
        for w in warnings[:10]:
            print(f"  {w}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more")

    print(f"\nParsed {len(json_files) - skipped} matches ({skipped} skipped, not finished)\n")

    df_shots = pd.DataFrame(all_shots)

    df_player_stats = pd.DataFrame(all_player_stats)
    # NOTE: fillna(0) means "stat not present for this match" and "stat was
    # genuinely zero" become indistinguishable downstream. Fine for most
    # counting stats, but worth remembering if a metric behaves oddly later.
    df_player_stats = df_player_stats.fillna(0)
    df_player_stats = df_player_stats.rename(columns=RENAME_MAP)
    if "Shotmap" in df_player_stats.columns:
        df_player_stats = df_player_stats.drop(columns=["Shotmap"])

    team_stat_dfs = {
        group_name: pd.DataFrame(rows)
        for group_name, rows in all_team_stats.items()
    }

    shots_path = out_dir / "shots.csv"
    df_shots.to_csv(shots_path, index=False)
    print(f"Saved {shots_path.relative_to(out_dir.parent.parent)}          — {len(df_shots)} rows")

    player_stats_path = out_dir / "player_stats.csv"
    df_player_stats.to_csv(player_stats_path, index=False)
    print(f"Saved {player_stats_path.relative_to(out_dir.parent.parent)}   — {len(df_player_stats)} rows")

    for group_name, df in team_stat_dfs.items():
        safe_name = group_name.lower().replace(" ", "_").replace("/", "_")
        team_path = out_dir / f"team_stats_{safe_name}.csv"
        df.to_csv(team_path, index=False)
        print(f"Saved {team_path.relative_to(out_dir.parent.parent)} — {len(df)} rows")

    print(f"\nDone. Output in: {out_dir}")
    return out_dir


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage: python fotmob_json_to_csv.py <input_dir> [output_base_dir]")
        print("Example: python fotmob_json_to_csv.py data/fotmob/raw/eng_47_2026_2027")
        sys.exit(1)

    output_base_dir = sys.argv[2] if len(sys.argv) == 3 else None

    try:
        fotmob_json_to_csv(sys.argv[1], output_base_dir)
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)

