"""
Match fresh 2026/27 per-source player data against what we already know,
using each source's own native player ID (Opta player_id, WhoScored
playerId, FotMob player_id) — not fuzzy name matching. Platform IDs don't
change season to season, so a direct ID lookup is far more reliable than
re-deriving name/team matches from scratch.

"What we already know" is, in order (see known_identities.py):
  1. reference_data/player_id_map.csv (with --id-map) — every player
     identified in earlier weeks this season, including new players and
     cross-source links worked out by reconcile_new_players.py.
  2. master_player_table.csv — the 2025/26 table.

For each source, every fresh player ID either:
  - is known -> gets that player's canonical ID (Opta's numeric ID for
    master players and for new players with an Opta sighting; "ws_<id>" /
    "fm_<id>" for players first seen without one)
  - isn't known -> "new_this_season", given a temporary source-prefixed ID
    (e.g. "opta_new_551230"), kept (never silently dropped), and handed on
    to reconcile_new_players.py.

CROSS-LEAGUE SAFEGUARD: an ID match against a master row at a club in a
different top-5 league is accepted when the names agree (a summer transfer,
logged to <output>_TRANSFERS.csv) and only rejected when they don't (a
stale/wrong ID, logged to <output>_CROSS_LEAGUE_REJECTIONS.csv as before).
See known_identities.py for the history.

Usage:
    python match_players_to_master.py <master_table_csv> <opta_csv> <whoscored_meta_csv> \\
        <fotmob_player_stats_csv> <output_csv> [other_league_teams_csv] [--id-map <player_id_map_csv>]
"""

import sys
from pathlib import Path

import pandas as pd

from known_identities import KnownIdentities, one_row_per_id, opta_team_names


def build_crosswalk(
    master_table_csv: str,
    opta_csv: str,
    whoscored_meta_csv: str,
    fotmob_player_stats_csv: str,
    output_csv: str,
    other_league_teams_csv: str | None = None,
    id_map_csv: str | None = None,
) -> Path:
    known = KnownIdentities(master_table_csv, other_league_teams_csv, id_map_csv)

    # ─── one tidy frame per source: native_id, name, team ───────────────────
    opta = pd.read_csv(opta_csv, low_memory=False)
    opta_id_col = "opta_player_id" if "opta_player_id" in opta.columns else "attack_player_id"
    team_id_col = "opta_team_id" if "opta_team_id" in opta.columns else "attack_team_id"
    if opta_id_col == "attack_player_id":
        print("  ⚠️  Using attack_player_id (older parser output) — goalkeepers will likely be "
              "missing IDs. Re-run opta_json_to_csv.py to fix this properly.")
    opta["_team"] = opta_team_names(opta, team_id_col, known.team_map)
    opta_players = one_row_per_id(opta[["player", opta_id_col, "_team"]], opta_id_col, "player", "_team")
    opta_players.columns = ["name", "native_id", "team"]

    ws = pd.read_csv(whoscored_meta_csv)
    ws_players = one_row_per_id(ws[["name", "playerId", "teamName"]], "playerId", "name", "teamName")
    ws_players.columns = ["name", "native_id", "team"]

    fm = pd.read_csv(fotmob_player_stats_csv)
    fm_players = one_row_per_id(fm[["player_name", "player_id", "team_name"]], "player_id", "player_name", "team_name")
    fm_players.columns = ["name", "native_id", "team"]

    rows, transfers, rejections = [], [], []

    for source, players, label in [("opta", opta_players, "Opta"),
                                   ("whoscored", ws_players, "WhoScored"),
                                   ("fotmob", fm_players, "FotMob")]:
        print(f"Matching {label} ...")
        players = players.copy()
        players["native_id"] = pd.to_numeric(players["native_id"], errors="coerce").astype("Int64")
        n_matched = n_no_id = 0
        via_counts = {}
        for _, r in players.iterrows():
            pid = r["native_id"]
            if pd.isna(pid):
                n_no_id += 1
                if source == "opta":  # same behaviour as before: keep, unmatched
                    rows.append({"source": source, "source_native_id": None, "source_name": r["name"],
                                 "team": r["team"], "canonical_player_id": f"opta_no_id_{r['name']}",
                                 "matched_to_master": False, "match_via": None})
                continue

            canonical, via, _, master_team = known.lookup(source, pid, r["name"])
            if via == "master_transfer":
                transfers.append({"source": source, "name": r["name"], "native_id": int(pid),
                                  "canonical_id": canonical, "old_team": master_team, "new_team": r["team"]})
            elif via == "rejected":
                rejections.append({"source": source, "name": r["name"], "native_id": int(pid),
                                   "master_team": master_team})

            matched = canonical is not None
            if matched:
                n_matched += 1
                via_counts[via] = via_counts.get(via, 0) + 1
            rows.append({
                "source": source,
                "source_native_id": int(pid),
                "source_name": r["name"],
                "team": r["team"],
                "canonical_player_id": canonical if matched else f"{source}_new_{int(pid)}",
                "matched_to_master": matched,  # name kept for compatibility: means "already known"
                "match_via": via if matched else None,
            })

        n_with_id = len(players) - n_no_id
        detail = ", ".join(f"{k} {v}" for k, v in sorted(via_counts.items()))
        print(f"  {n_matched}/{n_with_id} known ({100 * n_matched / max(n_with_id, 1):.1f}%)"
              + (f" — {detail}" if detail else "")
              + (f" — {n_no_id} had no ID at all" if n_no_id else ""))

    crosswalk = pd.DataFrame(rows)
    out_path = Path(output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(out_path, index=False)
    print(f"\nSaved crosswalk: {out_path} ({len(crosswalk)} rows)")

    if transfers:
        p = out_path.parent / f"{out_path.stem}_TRANSFERS.csv"
        pd.DataFrame(transfers).to_csv(p, index=False)
        print(f"↔  {len(transfers)} ID match(es) to a master row at another top-5 league's club with an "
              f"agreeing name — accepted as summer transfers. See: {p}")
    if rejections:
        p = out_path.parent / f"{out_path.stem}_CROSS_LEAGUE_REJECTIONS.csv"
        pd.DataFrame(rejections).to_csv(p, index=False)
        print(f"⚠️  {len(rejections)} match(es) rejected: master row is at another league's club AND the "
              f"name doesn't agree (likely a wrong ID in master) — routed to 'new'. See: {p}")
    else:
        print("No cross-league rejections (no ID matches with disagreeing names).")

    return out_path


def parse_args(argv):
    args = list(argv)
    id_map = None
    if "--id-map" in args:
        i = args.index("--id-map")
        id_map = args[i + 1]
        del args[i:i + 2]
    return args, id_map


if __name__ == "__main__":
    args, id_map_csv = parse_args(sys.argv[1:])
    if len(args) not in (5, 6):
        print(__doc__)
        sys.exit(1)
    other_league_teams_csv = args[5] if len(args) == 6 else None
    try:
        build_crosswalk(*args[:5], other_league_teams_csv, id_map_csv)
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
