"""
Build the final per-league player identity legend by consolidating the
outputs of match_players_to_master.py and reconcile_new_players.py into
one wide table: one row per real player, with each source's native ID
sitting alongside a single canonical_id. This is the join key to use for
every future weekly scrape this season.

canonical_id is STABLE across weeks (changed 2026-10-27 — it used to be a
"new_2026_<n>" counter for new players, re-numbered every run, so new
players couldn't be joined from one week to the next):
  - Opta's numeric player_id whenever the player has an Opta sighting —
    the same ID system master_player_table.csv uses, so master players and
    new players share one key space.
  - "ws_<whoscored_id>" / "fm_<fotmob_id>" for players first seen without
    an Opta sighting. Once written to player_id_map.csv this stays the
    player's ID even if an Opta ID turns up later.

status:
  - existing             in master_player_table.csv (2025/26)
  - new_linked_full      new this season, IDs from all 3 sources
  - new_linked_partial   new this season, IDs from 2 sources
  - new_unverified       new this season, only 1 source so far
known_via says how a row was recognised this week: master, master_transfer
(moved between top-5 leagues), id_map (worked out in an earlier week), or
blank for players reconciled for the first time this week.

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

from known_identities import teams_match

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


# team_core_tokens / teams_match live in known_identities.py (single copy,
# shared with the other identity scripts, including the club alias table).


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
    matched["canonical_player_id"] = matched["canonical_player_id"].astype(str)
    if "team" not in matched.columns:      # crosswalks from before 2026-10-27
        matched["team"] = None
    if "match_via" not in matched.columns:
        matched["match_via"] = "master"
    print(f"  {len(matched)} matched rows across all sources")

    conflicts = []

    # ─── Pivot matched rows: group by canonical numeric ID ──────────────────
    legend_rows = []

    for canonical_id, group in matched.groupby("canonical_player_id"):
        row = {"canonical_id": canonical_id, "status": "existing", "_known": True}
        name = None
        team = None
        vias = set()
        for _, r in group.iterrows():
            vias.add(r["match_via"])
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
            # this season's team as the source reports it (not master's
            # 2025/26 team, which is stale for anyone who moved)
            if pd.notna(r["team"]) and (team is None or r["source"] == "opta"):
                team = r["team"]
        row["name"] = name
        row["team"] = team  # master backfill below only fills gaps
        row["known_via"] = ("master_transfer" if "master_transfer" in vias
                            else "id_map" if "id_map" in vias else "master")
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

        ids = {s: group.loc[group["source"] == s, "native_id"].iloc[0]
               for s in ("opta", "whoscored", "fotmob") if (group["source"] == s).any()}
        if "opta" in ids:
            stable_id = str(int(ids["opta"]))
        elif "whoscored" in ids:
            stable_id = f"ws_{int(ids['whoscored'])}"
        else:
            stable_id = f"fm_{int(ids['fotmob'])}"
        row = {"canonical_id": stable_id, "status": status, "_known": False, "known_via": None}
        name = None
        team = None
        for _, r in group.iterrows():
            col = f"{r['source']}_id"
            new_val = r["native_id"]
            if col in row and pd.notna(row.get(col)) and row[col] != new_val:
                conflicts.append({
                    "canonical_id": stable_id,
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
            if pd.notna(r["team_name"]) and (team is None or r["source"] == "opta"):
                team = r["team_name"]  # prefer Opta's naming, same as known rows
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
            if r["_known"]:
                cid = pd.to_numeric(r["canonical_id"], errors="coerce")
                if pd.notna(cid) and cid in team_by_id.index:
                    return team_by_id.loc[cid]
            return r["team"]

        legend["team"] = legend.apply(fill_team, axis=1)
        n_still_missing = legend["team"].isna().sum()
        print(f"  {len(legend) - n_still_missing}/{len(legend)} rows now have a team ({n_still_missing} still missing)")

        # ─── Cross-pool merge: existing <-> new, gated on name+team match ────
        print("\nAttempting cross-pool merge (existing <-> new) by name+team ...")
        existing_idx = legend[legend["_known"]].index
        new_idx = legend[~legend["_known"]].index

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

    # Status: "existing" = in the 2025/26 master; everyone else is graded
    # by how many sources we now hold an ID for. Recomputed here so a
    # player first seen in one source moves up to partial/full as their
    # other sightings get linked in later weeks (or by the merge above).
    master_ids = set()
    if master_table_csv is not None:
        master_ids = set(master["player_id"].dropna().astype(int).astype(str))
    def grade(r):
        if str(r["canonical_id"]) in master_ids:
            return "existing"
        n = sum(pd.notna(r[c]) for c in ID_COLS)
        return {3: "new_linked_full", 2: "new_linked_partial"}.get(n, "new_unverified")
    if master_ids:
        legend["status"] = legend.apply(grade, axis=1)

    legend = legend[["canonical_id", "name", "team", "status"] + ID_COLS + ["known_via"]]
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
