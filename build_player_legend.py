"""
Build the final per-league player identity legend by consolidating the
outputs of match_players_to_master.py and reconcile_new_players.py into
one wide table: one row per real player, with each source's native ID
sitting alongside a single canonical_id. This is the join key to use for
every future weekly scrape this season.

Two kinds of canonical_id appear in the output:
  - A numeric ID (Opta's own player_id) for anyone who matched an existing
    identity in master_player_table.csv.
  - A "new_2026_<n>" ID for anyone new this season, assigned during
    reconciliation (linked across sources where possible, kept as a
    single-source entry — never dropped — where it couldn't be verified
    against another source yet).

Usage:
    python build_player_legend.py <crosswalk_csv> <reconciled_csv> <output_legend_csv> [master_table_csv]

Passing master_table_csv also backfills the "team" column for "existing"
(matched-to-master) rows, joining canonical_id against the table's own
player_id/canon_team columns — without it, only new players get a team.

Example:
    python build_player_legend.py crosswalk_EPL_2026-08-28.csv reconciled_EPL_2026-08-28.csv legend_EPL_2026-08-28.csv master_player_table.csv
"""

import sys
from pathlib import Path

import pandas as pd


def build_player_legend(
    crosswalk_csv: str,
    reconciled_csv: str,
    output_legend_csv: str,
    master_table_csv: str | None = None,
) -> Path:
    print("Loading crosswalk (matched-to-master) ...")
    crosswalk = pd.read_csv(crosswalk_csv)

    print("Loading reconciled (new players) ...")
    reconciled = pd.read_csv(reconciled_csv)

    matched = crosswalk[crosswalk["matched_to_master"] == True].copy()
    print(f"  {len(matched)} matched rows across all sources")

    # ─── Pivot matched rows: group by canonical numeric ID ──────────────────
    legend_rows = []

    for canonical_id, group in matched.groupby("canonical_player_id"):
        row = {"canonical_id": canonical_id, "status": "existing"}
        name = None
        for _, r in group.iterrows():
            row[f"{r['source']}_id"] = r["source_native_id"]
            if name is None or r["source"] == "opta":
                name = r["source_name"]
        row["name"] = name
        row["team"] = None  # not tracked for matched rows; join back to master_player_table for team if needed
        legend_rows.append(row)

    # ─── Pivot reconciled (new) rows: group by cluster_id ────────────────────
    for cluster_id, group in reconciled.groupby("cluster_id"):
        n_sources = group["source"].nunique()
        if n_sources == 3:
            status = "new_linked_full"
        elif n_sources == 2:
            status = "new_linked_partial"
        else:
            status = "new_unverified"

        row = {"canonical_id": cluster_id, "status": status}
        name = None
        team = None
        for _, r in group.iterrows():
            row[f"{r['source']}_id"] = r["native_id"]
            if name is None or r["source"] == "opta":
                name = r["name"]
            if team is None:
                team = r["team_name"]
        row["name"] = name
        row["team"] = team
        legend_rows.append(row)

    legend = pd.DataFrame(legend_rows)

    for col in ["opta_id", "whoscored_id", "fotmob_id"]:
        if col not in legend.columns:
            legend[col] = None

    if master_table_csv is not None:
        print("Backfilling team for existing (matched) rows from master table ...")
        master = pd.read_csv(master_table_csv, usecols=["player_id", "canon_team"], low_memory=False)
        master["player_id"] = pd.to_numeric(master["player_id"], errors="coerce")
        team_by_id = master.dropna(subset=["player_id"]).drop_duplicates("player_id").set_index("player_id")["canon_team"]

        def fill_team(r):
            if pd.notna(r["team"]):
                return r["team"]
            if r["status"] == "existing":
                cid = pd.to_numeric(r["canonical_id"], errors="coerce")
                if pd.notna(cid) and cid in team_by_id.index:
                    return team_by_id.loc[cid]
            return r["team"]

        legend["team"] = legend.apply(fill_team, axis=1)
        n_still_missing = legend["team"].isna().sum()
        print(f"  {len(legend) - n_still_missing}/{len(legend)} rows now have a team ({n_still_missing} still missing)")

    legend = legend[["canonical_id", "name", "team", "status", "opta_id", "whoscored_id", "fotmob_id"]]
    legend = legend.sort_values(["status", "name"])

    out_path = Path(output_legend_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    legend.to_csv(out_path, index=False)

    print(f"\nLegend built: {len(legend)} total players")
    print(legend["status"].value_counts().to_string())
    print(f"\nSaved: {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        print("Usage: python build_player_legend.py <crosswalk_csv> <reconciled_csv> <output_legend_csv> [master_table_csv]")
        sys.exit(1)

    master_table_csv = sys.argv[4] if len(sys.argv) == 5 else None

    try:
        build_player_legend(sys.argv[1], sys.argv[2], sys.argv[3], master_table_csv)
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
