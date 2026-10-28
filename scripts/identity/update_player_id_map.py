"""
Fold one league's weekly legend into reference_data/player_id_map.csv — the
persistent, season-long record of who's who. Run it after
build_player_legend.py, once per league. Next week, match_players_to_master.py
and reconcile_new_players.py read this map (with --id-map) BEFORE the master
table, so everyone identified this week is recognised instantly by native ID
and only genuinely new sightings go through name+team reconciliation.

One row per real player, keyed by a canonical_id that never changes once
written. For each legend row:
  - no map row shares any of its native IDs      -> added
  - exactly one map row shares a native ID       -> updated: missing IDs
    filled in (e.g. a new player's FotMob ID turning up), team / league /
    last_seen refreshed, link_status upgraded. An ID is never overwritten
    with a different value — that's logged as a conflict instead.
  - native IDs point at two different map rows   -> conflict, logged, map
    left untouched for that player (needs a manual look)

Conflicts go to <map_dir>/player_id_map_CONFLICTS_<league>_<date>.csv. No
file means no conflicts.

Usage:
    python update_player_id_map.py <legend_csv> <league> <date> [player_id_map_csv]

Example:
    python update_player_id_map.py legend_EPL_2026-10-23.csv EPL 2026-10-23 reference_data/player_id_map.csv
"""

import sys
from pathlib import Path

import pandas as pd

from known_identities import ID_MAP_COLUMNS, SOURCES, teams_match

DEFAULT_MAP = "reference_data/player_id_map.csv"
ID_COLS = [f"{s}_id" for s in SOURCES]
STATUS_RANK = {"new_unverified": 0, "new_linked_partial": 1, "new_linked_full": 2, "existing": 3}


def load_map(path: Path) -> pd.DataFrame:
    if path.exists():
        idm = pd.read_csv(path, dtype={"canonical_id": str})
    else:
        idm = pd.DataFrame(columns=ID_MAP_COLUMNS)
    for c in ID_COLS:
        idm[c] = pd.to_numeric(idm[c], errors="coerce").astype("Int64")
    return idm[ID_MAP_COLUMNS]


def update_player_id_map(legend_csv, league, date, map_csv=DEFAULT_MAP) -> Path:
    map_path = Path(map_csv)
    idm = load_map(map_path)
    legend = pd.read_csv(legend_csv, dtype={"canonical_id": str})
    for c in ID_COLS:
        legend[c] = pd.to_numeric(legend[c], errors="coerce").astype("Int64")
    print(f"Player ID map: {len(idm)} players before; folding in {len(legend)} from {legend_csv}")

    # native ID -> map row index, per source
    index = {c: {int(v): i for i, v in idm[c].items() if pd.notna(v)} for c in ID_COLS}
    canon_taken = set(idm["canonical_id"].astype(str))

    new_rows, conflicts = [], []
    n_updated = n_ids_filled = n_team_changes = n_upgraded = 0

    for _, r in legend.iterrows():
        hits = {index[c][int(r[c])] for c in ID_COLS if pd.notna(r[c]) and int(r[c]) in index[c]}

        if len(hits) > 1:
            conflicts.append({"canonical_id": r["canonical_id"], "name": r["name"], "team": r["team"],
                              "problem": "native IDs point at different map rows",
                              "map_rows": "; ".join(str(idm.at[i, "canonical_id"]) for i in hits)})
            continue

        if not hits:
            cid = str(r["canonical_id"])
            if cid in canon_taken:
                conflicts.append({"canonical_id": cid, "name": r["name"], "team": r["team"],
                                  "problem": "canonical_id already used by a different map row",
                                  "map_rows": cid})
                continue
            canon_taken.add(cid)
            row = {"canonical_id": cid, "name": r["name"], "team": r["team"], "league": league,
                   "link_status": r["status"], "first_seen": date, "last_seen": date}
            row.update({c: r[c] for c in ID_COLS})
            new_rows.append(row)
            continue

        i = hits.pop()
        n_updated += 1
        for c in ID_COLS:
            have, got = idm.at[i, c], r[c]
            if pd.isna(got):
                continue
            if pd.isna(have):
                idm.at[i, c] = got
                n_ids_filled += 1
            elif int(have) != int(got):
                conflicts.append({"canonical_id": idm.at[i, "canonical_id"], "name": r["name"],
                                  "team": r["team"], "problem": f"{c} differs (map {have}, legend {got})",
                                  "map_rows": idm.at[i, "canonical_id"]})
        # only a real club change counts — not "Paderborn" vs "SC Paderborn 07"
        if pd.notna(r["team"]) and not teams_match(r["team"], idm.at[i, "team"]):
            if pd.notna(idm.at[i, "team"]):
                n_team_changes += 1
            idm.at[i, "team"] = r["team"]
        if pd.isna(idm.at[i, "name"]) and pd.notna(r["name"]):
            idm.at[i, "name"] = r["name"]
        idm.at[i, "league"] = league
        idm.at[i, "last_seen"] = date
        old = idm.at[i, "link_status"]
        if STATUS_RANK.get(r["status"], -1) > STATUS_RANK.get(old, -1):
            idm.at[i, "link_status"] = r["status"]
            n_upgraded += 1

    if new_rows:
        add = pd.DataFrame(new_rows)
        for c in ID_COLS:
            add[c] = pd.to_numeric(add[c], errors="coerce").astype("Int64")
        idm = pd.concat([idm, add[ID_MAP_COLUMNS]], ignore_index=True)

    map_path.parent.mkdir(parents=True, exist_ok=True)
    idm.sort_values(["league", "team", "name"], na_position="last").to_csv(map_path, index=False)

    print(f"  added {len(new_rows)} | updated {n_updated} "
          f"({n_ids_filled} IDs filled in, {n_team_changes} team changes, {n_upgraded} status upgrades)")
    if conflicts:
        cpath = map_path.parent / f"player_id_map_CONFLICTS_{league}_{date}.csv"
        pd.DataFrame(conflicts).to_csv(cpath, index=False)
        print(f"  ⚠️  {len(conflicts)} conflict(s) left for a manual look: {cpath}")
    print(f"Saved: {map_path} ({len(idm)} players)")
    return map_path


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        sys.exit(1)
    try:
        update_player_id_map(*sys.argv[1:])
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
