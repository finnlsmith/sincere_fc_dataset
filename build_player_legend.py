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

Two safeguards added after bugs found while cross-referencing LaLiga
round-1 splits against this legend:

  1. CONFLICT DETECTION — if a canonical ID would receive two different
     native IDs from the SAME source (e.g. two rows both claiming to be
     that player's fotmob_id, with different values), we no longer
     silently keep whichever one happened to be seen last. The first
     value is kept, the conflict is logged, and a
     "<output>_CONFLICTS.csv" file is written alongside the legend for
     manual review — never silently swallowed.

  2. CROSS-POOL MERGE — a player who matched the master table via ONE
     source but not another (e.g. matched via Opta, but their WhoScored
     ID wasn't in the table) previously ended up as two separate,
     unlinked legend rows: one "existing" row with only the matched
     source's ID, and one "new_unverified" row with only the unmatched
     source's ID. This pass looks for exactly that pattern — an
     "existing" row and a "new_*" row that share a name+team — and
     merges them into one row. Merging REQUIRES a team match, not just a
     name match (using the same token-based team-clustering logic as
     reconcile_new_players.py), specifically to avoid wrongly merging two
     different real people who happen to share a common name but play
     for different clubs (found a live example of this risk: two
     different "Fran García"s, one at Real Madrid, one at Real Betis —
     must stay separate). Only runs when master_table_csv is provided,
     since it needs "existing" rows to already have a team.

Usage:
    python build_player_legend.py <crosswalk_csv> <reconciled_csv> <output_legend_csv> [master_table_csv]

Passing master_table_csv also backfills the "team" column for "existing"
(matched-to-master) rows, joining canonical_id against the table's own
player_id/canon_team columns — without it, only new players get a team,
and the cross-pool merge pass is skipped.

Example:
    python build_player_legend.py crosswalk_EPL_2026-08-28.csv reconciled_EPL_2026-08-28.csv legend_EPL_2026-08-28.csv master_player_table.csv
"""

import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

NAME_MATCH_THRESHOLD = 0.82
TEAM_NAME_STOPWORDS = {"de", "la", "el", "a", "fc", "cf"}
ID_COLS = ["opta_id", "whoscored_id", "fotmob_id"]


def normalize(s) -> str:
    if pd.isna(s):
        return ""
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def name_similarity(a, b) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def team_core_tokens(name: str) -> frozenset:
    return frozenset(t for t in normalize(name).split() if t not in TEAM_NAME_STOPWORDS)


def teams_match(team_a, team_b) -> bool:
    """
    True if two team names plausibly refer to the same club. Same logic as
    reconcile_new_players.py's team clustering: substring containment
    (e.g. "Tottenham" / "Tottenham Hotspur") OR token-set equality/subset
    after stripping small connector words (e.g. "Atletico Madrid" /
    "Atletico de Madrid"). Deliberately strict — this is the safeguard
    against merging two different real people who share a name but not a
    team (e.g. the two distinct "Fran García"s).
    """
    na, nb = normalize(team_a), normalize(team_b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ca, cb = team_core_tokens(team_a), team_core_tokens(team_b)
    if ca and cb and (ca == cb or ca.issubset(cb) or cb.issubset(ca)):
        return True
    return False


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

    conflicts = []

    # ─── Pivot matched rows: group by canonical numeric ID ──────────────────
    legend_rows = []

    for canonical_id, group in matched.groupby("canonical_player_id"):
        row = {"canonical_id": canonical_id, "status": "existing"}
        name = None
        for _, r in group.iterrows():
            col = f"{r['source']}_id"
            new_val = r["source_native_id"]
            if col in row and pd.notna(row.get(col)) and row[col] != new_val:
                conflicts.append({
                    "canonical_id": canonical_id,
                    "name": r["source_name"],
                    "source": r["source"],
                    "kept_value": row[col],
                    "discarded_value": new_val,
                    "stage": "matched-pool pivot",
                })
                continue  # keep the first-seen value; do not silently overwrite
            row[col] = new_val
            if name is None or r["source"] == "opta":
                name = r["source_name"]
        row["name"] = name
        row["team"] = None  # backfilled below if master_table_csv is given
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
            col = f"{r['source']}_id"
            new_val = r["native_id"]
            if col in row and pd.notna(row.get(col)) and row[col] != new_val:
                conflicts.append({
                    "canonical_id": cluster_id,
                    "name": r["name"],
                    "source": r["source"],
                    "kept_value": row[col],
                    "discarded_value": new_val,
                    "stage": "reconciled-cluster pivot (likely a clustering bug upstream in reconcile_new_players.py)",
                })
                continue
            row[col] = new_val
            if name is None or r["source"] == "opta":
                name = r["name"]
            if team is None:
                team = r["team_name"]
        row["name"] = name
        row["team"] = team
        legend_rows.append(row)

    legend = pd.DataFrame(legend_rows)

    for col in ID_COLS:
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

        # ─── Cross-pool merge: existing <-> new, gated on name+team match ────
        print("\nAttempting cross-pool merge (existing <-> new) by name+team ...")
        existing_idx = legend[legend["status"] == "existing"].index
        new_idx = legend[legend["status"] != "existing"].index

        merged_new_indices = set()
        n_merged = 0

        for i in existing_idx:
            e_name, e_team = legend.at[i, "name"], legend.at[i, "team"]
            if pd.isna(e_team):
                continue
            for j in new_idx:
                if j in merged_new_indices:
                    continue
                n_name, n_team = legend.at[j, "name"], legend.at[j, "team"]
                if pd.isna(n_team):
                    continue
                if not teams_match(e_team, n_team):
                    continue
                if name_similarity(e_name, n_name) < NAME_MATCH_THRESHOLD:
                    continue

                merged_any = False
                for col in ID_COLS:
                    e_val, n_val = legend.at[i, col], legend.at[j, col]
                    if pd.isna(e_val) and pd.notna(n_val):
                        legend.at[i, col] = n_val
                        merged_any = True
                    elif pd.notna(e_val) and pd.notna(n_val) and e_val != n_val:
                        conflicts.append({
                            "canonical_id": legend.at[i, "canonical_id"],
                            "name": e_name,
                            "source": col.replace("_id", ""),
                            "kept_value": e_val,
                            "discarded_value": n_val,
                            "stage": "cross-pool merge",
                        })

                if merged_any:
                    merged_new_indices.add(j)
                    n_merged += 1
                    break  # this "new" row is consumed; move to the next existing row

        if merged_new_indices:
            legend = legend.drop(index=merged_new_indices).reset_index(drop=True)
        print(f"  Merged {n_merged} cross-pool matches (e.g. players matched via one source but not another)")
    else:
        print("\n(No master_table_csv given — skipping cross-pool merge, since it needs "
              "'existing' rows to already have a team to match against.)")

    legend = legend[["canonical_id", "name", "team", "status"] + ID_COLS]
    legend = legend.sort_values(["status", "name"])

    out_path = Path(output_legend_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    legend.to_csv(out_path, index=False)

    if conflicts:
        conflicts_df = pd.DataFrame(conflicts)
        conflicts_path = out_path.parent / f"{out_path.stem}_CONFLICTS.csv"
        conflicts_df.to_csv(conflicts_path, index=False)
        print(f"\n⚠️  {len(conflicts)} ID conflict(s) found — kept the first-seen value in "
              f"each case, did NOT silently overwrite. See: {conflicts_path}")

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
