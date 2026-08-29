"""
Match fresh 2026/27 per-source player data against master_player_table.csv
(built from 2025/26 data) using each source's own native platform player ID
— not fuzzy name matching. Platform IDs (Opta's numeric ID, WhoScored's
playerId, FotMob's player_id) are assigned once per player and don't change
season to season, so a direct ID lookup against the master table is far more
reliable than re-deriving name/team matches from scratch.

For each source, every fresh player ID either:
  - matches an ID already in master_player_table.csv -> gets that player's
    canonical_player_id (Opta's own ID system, since Opta is the table's
    anchor spine)
  - doesn't match anything in the table -> flagged as "new_this_season",
    given a temporary source-prefixed ID (e.g. "opta_new_551230"), and kept
    (never silently dropped), consistent with master_player_table's own
    build philosophy.

Usage:
    python match_players_to_master.py <master_table_csv> <opta_csv> <whoscored_meta_csv> <fotmob_player_stats_csv> <output_csv>

Example:
    python match_players_to_master.py master_player_table.csv \\
        "English_Premier_League_..._merged_df_clean.csv" \\
        EPL_2026_27_player_meta.csv \\
        eng_47_player_stats.csv \\
        crosswalk_EPL_2026-08-28.csv
"""

import sys
from pathlib import Path

import pandas as pd


def build_crosswalk(
    master_table_csv: str,
    opta_csv: str,
    whoscored_meta_csv: str,
    fotmob_player_stats_csv: str,
    output_csv: str,
) -> Path:
    print("Loading master_player_table.csv ...")
    master = pd.read_csv(
        master_table_csv,
        usecols=["player_id", "player", "fotmob_player_id", "whoscored_playerId", "canon_team", "confidence_tier"],
        low_memory=False,
    )
    master["player_id"] = pd.to_numeric(master["player_id"], errors="coerce").astype("Int64")
    master["fotmob_player_id"] = pd.to_numeric(master["fotmob_player_id"], errors="coerce").astype("Int64")
    master["whoscored_playerId"] = pd.to_numeric(master["whoscored_playerId"], errors="coerce").astype("Int64")

    master_by_opta_id = master.dropna(subset=["player_id"]).drop_duplicates("player_id").set_index("player_id")
    master_by_fotmob_id = master.dropna(subset=["fotmob_player_id"]).drop_duplicates("fotmob_player_id").set_index("fotmob_player_id")
    master_by_ws_id = master.dropna(subset=["whoscored_playerId"]).drop_duplicates("whoscored_playerId").set_index("whoscored_playerId")

    rows = []

    # ─── Opta ────────────────────────────────────────────────────────────────
    print("Matching Opta ...")
    opta = pd.read_csv(opta_csv, low_memory=False)

    # Prefer the coalesced opta_player_id column (covers every player,
    # including goalkeepers) if present; fall back to attack_player_id for
    # CSVs generated before this fix (will undercount goalkeepers).
    opta_id_col = "opta_player_id" if "opta_player_id" in opta.columns else "attack_player_id"
    if opta_id_col == "attack_player_id":
        print("  ⚠️  Using attack_player_id (older parser output) — goalkeepers will likely be "
              "missing IDs. Re-run opta_json_to_csv.py to fix this properly.")

    opta_players = opta[["player", opta_id_col]].drop_duplicates()
    opta_players[opta_id_col] = pd.to_numeric(opta_players[opta_id_col], errors="coerce").astype("Int64")

    opta_matched = 0
    opta_no_id = 0
    for _, r in opta_players.iterrows():
        pid = r[opta_id_col]
        if pd.isna(pid):
            opta_no_id += 1
            rows.append({
                "source": "opta",
                "source_native_id": None,
                "source_name": r["player"],
                "canonical_player_id": f"opta_no_id_{r['player']}",
                "matched_to_master": False,
            })
            continue
        if pid in master_by_opta_id.index:
            canonical_id = int(pid)
            opta_matched += 1
        else:
            canonical_id = f"opta_new_{int(pid)}"
        rows.append({
            "source": "opta",
            "source_native_id": int(pid),
            "source_name": r["player"],
            "canonical_player_id": canonical_id,
            "matched_to_master": pid in master_by_opta_id.index,
        })

    n_with_id = len(opta_players) - opta_no_id
    print(f"  {opta_matched}/{n_with_id} matched ({100*opta_matched/n_with_id:.1f}%)"
          + (f" — {opta_no_id} players had no ID at all (kept, unmatched)" if opta_no_id else ""))

    # ─── WhoScored ───────────────────────────────────────────────────────────
    print("Matching WhoScored ...")
    ws = pd.read_csv(whoscored_meta_csv)
    ws_players = ws[["name", "playerId"]].drop_duplicates()
    ws_players["playerId"] = pd.to_numeric(ws_players["playerId"], errors="coerce").astype("Int64")

    ws_matched = 0
    for _, r in ws_players.iterrows():
        pid = r["playerId"]
        if pd.isna(pid):
            continue
        if pid in master_by_ws_id.index and pd.notna(master_by_ws_id.loc[pid, "player_id"]):
            canonical_id = int(master_by_ws_id.loc[pid, "player_id"])
            is_matched = True
            ws_matched += 1
        else:
            canonical_id = f"whoscored_new_{int(pid)}"
            is_matched = False
        rows.append({
            "source": "whoscored",
            "source_native_id": int(pid),
            "source_name": r["name"],
            "canonical_player_id": canonical_id,
            "matched_to_master": is_matched,
        })

    print(f"  {ws_matched}/{len(ws_players)} matched ({100*ws_matched/len(ws_players):.1f}%)")

    # ─── FotMob ──────────────────────────────────────────────────────────────
    print("Matching FotMob ...")
    fm = pd.read_csv(fotmob_player_stats_csv)
    fm_players = fm[["player_name", "player_id"]].drop_duplicates()
    fm_players["player_id"] = pd.to_numeric(fm_players["player_id"], errors="coerce").astype("Int64")

    fm_matched = 0
    for _, r in fm_players.iterrows():
        pid = r["player_id"]
        if pd.isna(pid):
            continue
        if pid in master_by_fotmob_id.index and pd.notna(master_by_fotmob_id.loc[pid, "player_id"]):
            canonical_id = int(master_by_fotmob_id.loc[pid, "player_id"])
            is_matched = True
            fm_matched += 1
        else:
            canonical_id = f"fotmob_new_{int(pid)}"
            is_matched = False
        rows.append({
            "source": "fotmob",
            "source_native_id": int(pid),
            "source_name": r["player_name"],
            "canonical_player_id": canonical_id,
            "matched_to_master": is_matched,
        })

    print(f"  {fm_matched}/{len(fm_players)} matched ({100*fm_matched/len(fm_players):.1f}%)")

    crosswalk = pd.DataFrame(rows)

    out_path = Path(output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(out_path, index=False)

    print(f"\nSaved crosswalk: {out_path} ({len(crosswalk)} rows)")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print("Usage: python match_players_to_master.py <master_table_csv> <opta_csv> <whoscored_meta_csv> <fotmob_player_stats_csv> <output_csv>")
        sys.exit(1)

    try:
        build_crosswalk(*sys.argv[1:6])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
