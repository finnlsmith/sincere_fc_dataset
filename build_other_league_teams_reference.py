"""
Build an "other_league_teams.csv" reference file for match_players_to_master.py's
cross-league safeguard, by combining the current team names from whichever
leagues' live data you pass in.

IMPORTANT: only pass in files for leagues OTHER than the one you're about to
match against. Including the target league's own team data here would cause
the safeguard to wrongly reject that league's own real players as
"cross-league" — this script does no exclusion logic itself, so getting the
inputs right is on the caller.

Usage:
    python build_other_league_teams_reference.py <output_csv> <whoscored_meta_csv_1> <fotmob_player_stats_csv_1> [<whoscored_meta_csv_2> <fotmob_player_stats_csv_2> ...]

Example (building the reference to use when matching LaLiga — so pass in
EPL, Ligue1, and SerieA's files, NOT LaLiga's own):
    python build_other_league_teams_reference.py other_league_teams_for_LaLiga.csv \\
        EPL_2026_27_player_meta.csv eng_47_player_stats.csv \\
        Ligue1_2026_27_player_meta.csv fra_53_player_stats.csv \\
        SerieA_2026_27_player_meta.csv ita_55_player_stats.csv
"""

import sys
from pathlib import Path

import pandas as pd


def build_other_league_teams_reference(output_csv: str, *file_pairs: str) -> Path:
    if len(file_pairs) % 2 != 0:
        raise ValueError("File arguments must come in (whoscored_meta_csv, fotmob_player_stats_csv) pairs")

    teams = set()

    for i in range(0, len(file_pairs), 2):
        ws_csv, fm_csv = file_pairs[i], file_pairs[i + 1]

        ws = pd.read_csv(ws_csv)
        if "teamName" not in ws.columns:
            raise ValueError(f"{ws_csv} has no 'teamName' column — is this really a WhoScored player_meta file?")
        teams |= set(ws["teamName"].dropna().unique())

        fm = pd.read_csv(fm_csv)
        if "team_name" not in fm.columns:
            raise ValueError(f"{fm_csv} has no 'team_name' column — is this really a FotMob player_stats file?")
        teams |= set(fm["team_name"].dropna().unique())

        print(f"  + {ws_csv} / {fm_csv} -> {len(teams)} distinct teams so far")

    out_path = Path(output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"team_name": sorted(teams)}).to_csv(out_path, index=False)

    print(f"\nSaved {len(teams)} team names to: {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 4 or len(sys.argv) % 2 != 0:
        print("Usage: python build_other_league_teams_reference.py <output_csv> <whoscored_meta_csv_1> <fotmob_player_stats_csv_1> [...]")
        sys.exit(1)

    try:
        build_other_league_teams_reference(sys.argv[1], *sys.argv[2:])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
