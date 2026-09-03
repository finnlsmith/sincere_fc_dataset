"""
Reconcile "new" players — players in fresh 2026/27 data that didn't match
any existing identity in master_player_table.csv — by matching them against
EACH OTHER across the 3 sources (Opta, WhoScored, FotMob), using name+team
similarity. This is the second half of player identity resolution:
match_players_to_master.py handles "does this player already exist in our
system", this script handles "do these 3 unlinked new-player sightings
across sources actually refer to the same real person".

Approach: normalize team names (strip accents/punctuation, lowercase) since
we don't have the original team_crosswalk.json used to build the master
table. Group unmatched players by normalized team, then fuzzy-match names
within each team group using difflib. This is deliberately conservative —
requires both a team match and a high name-similarity score — to avoid
false-positive links.

Usage:
    python reconcile_new_players.py <master_table_csv> <opta_csv> <whoscored_meta_csv> <fotmob_player_stats_csv> <output_csv> [other_league_teams_csv]

Example:
    python reconcile_new_players.py master_player_table.csv \\
        "English Premier League_..._merged_df_clean.csv" \\
        EPL_2026_27_player_meta.csv \\
        eng_47_player_stats.csv \\
        reconciled_new_players_EPL_2026-08-29.csv \\
        other_league_teams_for_EPL.csv
"""

import sys
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

# NOTE: the Bundesliga stopgap list (previously kept in sync with
# match_players_to_master.py) has been removed now that real Bundesliga
# data and reference_data/other_league_teams_for_Bundesliga.csv exist. It
# was being merged in unconditionally regardless of which league was being
# processed, so a Bundesliga run would incorrectly treat Bundesliga's own
# clubs as "other league" and wrongly reject/reclassify correct matches.

NAME_MATCH_THRESHOLD = 0.82  # fuzzy ratio, conservative to avoid false links


def normalize(s) -> str:
    if pd.isna(s):
        return ""
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


TEAM_NAME_STOPWORDS = {"de", "la", "el", "a", "fc", "cf"}


def team_core_tokens(name: str) -> frozenset:
    """Tokens of a team name with small connector words stripped, so e.g.
    'atletico de madrid' and 'atletico madrid' reduce to the same set."""
    return frozenset(t for t in name.split() if t not in TEAM_NAME_STOPWORDS)


def teams_match(team_a, team_b) -> bool:
    """Same logic as match_players_to_master.py / build_player_legend.py:
    substring containment, or token-set equality/subset after stripping
    small connector words."""
    na, nb = normalize(team_a), normalize(team_b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ca, cb = team_core_tokens(na), team_core_tokens(nb)
    if ca and cb and (ca == cb or ca.issubset(cb) or cb.issubset(ca)):
        return True
    return False


def team_is_other_league(canon_team, other_league_teams: set) -> bool:
    """True only if canon_team confidently matches a team known to belong
    to a DIFFERENT league. Must be kept consistent with
    match_players_to_master.py's version of this check."""
    if pd.isna(canon_team) or not other_league_teams:
        return False
    return any(teams_match(canon_team, t) for t in other_league_teams)


def build_team_clusters(team_names: set[str]) -> dict[str, str]:
    """
    Group team names that refer to the same club under different naming
    conventions using two rules found necessary during testing:
      1. Substring containment (e.g. Opta/WhoScored's "Tottenham" vs
         FotMob's "Tottenham Hotspur")
      2. Token-set equality/subset after stripping small connector words
         like "de"/"la"/"a" (e.g. "Atletico Madrid" vs "Atletico de
         Madrid", "Racing Santander" vs "Racing de Santander",
         "Deportivo de A Coruna" vs "Deportivo de La Coruna") — plain
         substring matching misses these since the connector word sits
         in the middle, not as a prefix/suffix difference.
    We don't have the original team_crosswalk.json used to build
    master_player_table.csv, so this is a lighter-weight approximation —
    good for these two common patterns, but won't catch a totally
    different naming convention (e.g. a nickname with no shared token
    or substring at all).
    """
    names = sorted(n for n in team_names if n)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            # keep the shorter name as the cluster's canonical key
            keep, drop = (ra, rb) if len(ra) <= len(rb) else (rb, ra)
            parent[drop] = keep

    core = {n: team_core_tokens(n) for n in names}

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a in b or b in a:
                union(a, b)
                continue
            ca, cb = core[a], core[b]
            if ca and cb and (ca == cb or ca.issubset(cb) or cb.issubset(ca)):
                union(a, b)

    return {n: find(n) for n in names}


def reconcile_new_players(
    master_table_csv: str,
    opta_csv: str,
    whoscored_meta_csv: str,
    fotmob_player_stats_csv: str,
    output_csv: str,
    other_league_teams_csv: str | None = None,
) -> Path:
    print("Loading master_player_table.csv ...")
    master = pd.read_csv(
        master_table_csv,
        usecols=["player_id", "team_id", "canon_team", "fotmob_player_id", "whoscored_playerId"],
        low_memory=False,
    )
    for c in ["player_id", "team_id", "fotmob_player_id", "whoscored_playerId"]:
        master[c] = pd.to_numeric(master[c], errors="coerce").astype("Int64")

    master_by_opta_id = master.dropna(subset=["player_id"]).drop_duplicates("player_id").set_index("player_id")
    master_by_fotmob_id = master.dropna(subset=["fotmob_player_id"]).drop_duplicates("fotmob_player_id").set_index("fotmob_player_id")
    master_by_ws_id = master.dropna(subset=["whoscored_playerId"]).drop_duplicates("whoscored_playerId").set_index("whoscored_playerId")
    master_team_by_opta_id = master.dropna(subset=["player_id"]).drop_duplicates("player_id").set_index("player_id")["canon_team"]
    master_team_by_fotmob_id = master.dropna(subset=["fotmob_player_id"]).drop_duplicates("fotmob_player_id").set_index("fotmob_player_id")["canon_team"]
    master_team_by_ws_id = master.dropna(subset=["whoscored_playerId"]).drop_duplicates("whoscored_playerId").set_index("whoscored_playerId")["canon_team"]

    team_map = master.dropna(subset=["team_id"]).drop_duplicates("team_id").set_index("team_id")["canon_team"]

    # Same cross-league safeguard as match_players_to_master.py — MUST be
    # kept consistent between the two scripts. Without this, a player whose
    # raw ID happens to be present in master's index gets treated as
    # "already matched" here even when match_players_to_master.py correctly
    # rejected that same match as cross-league-implausible — meaning the
    # player would vanish from BOTH the matched pool AND this unmatched
    # pool entirely, disappearing from the final legend rather than
    # correctly appearing as a new/unverified entry. (Found via a real
    # case: Rodri, Péter Gulácsi, and Altay Bayindir all went missing
    # entirely until this fix.)
    other_league_teams = set()
    if other_league_teams_csv is not None:
        ref = pd.read_csv(other_league_teams_csv)
        other_league_teams |= set(ref.iloc[:, 0].dropna().unique())
        print(f"Cross-league safeguard active: {len(other_league_teams)} known other-league teams")
    else:
        print("Cross-league safeguard skipped — no other_league_teams_csv passed in")

    # ─── Opta unmatched ─────────────────────────────────────────────────────
    print("Finding unmatched Opta players ...")
    opta = pd.read_csv(opta_csv, low_memory=False)
    id_col = "opta_player_id" if "opta_player_id" in opta.columns else "attack_player_id"
    # Same coalesce-vs-fallback pattern as the player ID: attack_team_id is
    # null for anyone absent from Opta's "attack" category (goalkeepers,
    # confirmed — possibly others), which silently orphaned them from
    # name+team matching entirely. Prefer the coalesced opta_team_id
    # (covers every player) when the parser producing it is in use.
    team_id_col = "opta_team_id" if "opta_team_id" in opta.columns else "attack_team_id"
    if team_id_col == "attack_team_id":
        print("  ⚠️  Using attack_team_id (older parser output) — players missing from "
              "Opta's 'attack' category (e.g. goalkeepers) will have no team and won't "
              "be matchable here. Re-run opta_json_to_csv.py to fix this properly.")
    opta_sub = opta[["player", id_col, team_id_col]].drop_duplicates()
    opta_sub[id_col] = pd.to_numeric(opta_sub[id_col], errors="coerce").astype("Int64")
    opta_sub["team_name"] = opta_sub[team_id_col].map(team_map)

    def opta_is_unmatched(pid):
        if pd.isna(pid):
            return False
        if pid not in master_by_opta_id.index:
            return True
        return team_is_other_league(master_team_by_opta_id.get(pid), other_league_teams)

    opta_unmatched = opta_sub[opta_sub[id_col].apply(opta_is_unmatched)].copy()
    opta_unmatched["source"] = "opta"
    opta_unmatched = opta_unmatched.rename(columns={"player": "name", id_col: "native_id"})[
        ["source", "native_id", "name", "team_name"]
    ]
    print(f"  {len(opta_unmatched)} unmatched")

    # ─── WhoScored unmatched ────────────────────────────────────────────────
    print("Finding unmatched WhoScored players ...")
    ws = pd.read_csv(whoscored_meta_csv)
    ws_sub = ws[["name", "playerId", "teamName"]].drop_duplicates()
    ws_sub["playerId"] = pd.to_numeric(ws_sub["playerId"], errors="coerce").astype("Int64")

    def ws_is_unmatched(pid):
        if pd.isna(pid):
            return False
        if pid not in master_by_ws_id.index:
            return True
        # A player can be present in master_by_ws_id but with no valid Opta
        # anchor (confidence_tier="whoscored_only") — match_players_to_master.py
        # correctly treats this as unmatched too (no valid canonical_id to
        # assign); this script previously didn't check for it, so those
        # players were wrongly treated as "already matched elsewhere" and
        # silently excluded from reconciliation entirely.
        if pd.isna(master_by_ws_id.loc[pid, "player_id"]):
            return True
        return team_is_other_league(master_team_by_ws_id.get(pid), other_league_teams)

    ws_unmatched = ws_sub[ws_sub["playerId"].apply(ws_is_unmatched)].copy()
    ws_unmatched["source"] = "whoscored"
    ws_unmatched = ws_unmatched.rename(columns={"playerId": "native_id", "teamName": "team_name"})[
        ["source", "native_id", "name", "team_name"]
    ]
    print(f"  {len(ws_unmatched)} unmatched")

    # ─── FotMob unmatched ───────────────────────────────────────────────────
    print("Finding unmatched FotMob players ...")
    fm = pd.read_csv(fotmob_player_stats_csv)
    fm_sub = fm[["player_name", "player_id", "team_name"]].drop_duplicates()
    fm_sub["player_id"] = pd.to_numeric(fm_sub["player_id"], errors="coerce").astype("Int64")

    def fm_is_unmatched(pid):
        if pd.isna(pid):
            return False
        if pid not in master_by_fotmob_id.index:
            return True
        # Same fotmob_only-tier issue as the WhoScored branch above — see
        # that comment for the full explanation. Confirmed real case:
        # Andriy Lunin, fotmob_id=800882, master row has fotmob_player_id
        # set but player_id (Opta anchor) is null, confidence_tier=fotmob_only.
        if pd.isna(master_by_fotmob_id.loc[pid, "player_id"]):
            return True
        return team_is_other_league(master_team_by_fotmob_id.get(pid), other_league_teams)

    fm_unmatched = fm_sub[fm_sub["player_id"].apply(fm_is_unmatched)].copy()
    fm_unmatched["source"] = "fotmob"
    fm_unmatched = fm_unmatched.rename(columns={"player_id": "native_id", "player_name": "name"})[
        ["source", "native_id", "name", "team_name"]
    ]
    print(f"  {len(fm_unmatched)} unmatched")

    all_unmatched = pd.concat([opta_unmatched, ws_unmatched, fm_unmatched], ignore_index=True)
    all_unmatched["team_norm"] = all_unmatched["team_name"].apply(normalize)

    team_cluster_map = build_team_clusters(set(all_unmatched["team_norm"]))
    all_unmatched["team_cluster"] = all_unmatched["team_norm"].map(team_cluster_map)

    # ─── Cluster by team, then fuzzy name match within each team ───────────
    print("\nReconciling across sources by name+team ...")
    all_unmatched["cluster_id"] = None
    next_cluster_id = 0

    for team, group in all_unmatched.groupby("team_cluster"):
        if not team:
            continue
        idxs = group.index.tolist()
        assigned = set()
        for i in idxs:
            if all_unmatched.at[i, "cluster_id"] is not None:
                continue
            cluster = [i]
            assigned.add(i)
            for j in idxs:
                if j in assigned:
                    continue
                cluster_sources = {all_unmatched.at[c, "source"] for c in cluster}
                if all_unmatched.at[j, "source"] in cluster_sources:
                    continue  # don't add a second row from a source already in this cluster
                # must be similar enough to EVERY member already in the cluster, not just
                # the seed row — otherwise two rows can each independently match the seed
                # on name similarity without ever being compared to each other, letting two
                # same-source rows (a real case found: two different FotMob IDs, "Miguel
                # Rodríguez" and "Mikel Rodríguez", both matching the same Opta seed) both
                # slip into one cluster despite being mutually incompatible
                if all(
                    name_similarity(all_unmatched.at[c, "name"], all_unmatched.at[j, "name"]) >= NAME_MATCH_THRESHOLD
                    for c in cluster
                ):
                    cluster.append(j)
                    assigned.add(j)
            cluster_id = f"new_2026_{next_cluster_id}"
            for c in cluster:
                all_unmatched.at[c, "cluster_id"] = cluster_id
            next_cluster_id += 1

    # Any row that never got a cluster_id — e.g. team_cluster was NaN
    # because this player's team_id never resolved via team_map (a
    # confirmed real case: some Opta rows' team lookups fail silently) —
    # would otherwise vanish downstream, since build_player_legend.py's
    # groupby("cluster_id") also drops NaN group keys by default. Give
    # each of these its own singleton cluster so they still surface as an
    # unverified new-player row instead of disappearing entirely.
    unclustered = all_unmatched["cluster_id"].isna()
    n_unclustered = int(unclustered.sum())
    if n_unclustered:
        print(f"  ⚠️  {n_unclustered} players had no usable team info (couldn't be "
              f"clustered by team, e.g. an unresolved Opta team_id) — assigning "
              f"each its own singleton entry rather than dropping them")
        for idx in all_unmatched[unclustered].index:
            all_unmatched.at[idx, "cluster_id"] = f"new_2026_{next_cluster_id}"
            next_cluster_id += 1

    n_clusters = all_unmatched["cluster_id"].nunique()
    cluster_sizes = all_unmatched.groupby("cluster_id")["source"].nunique()
    fully_linked = (cluster_sizes == 3).sum()
    partially_linked = (cluster_sizes == 2).sum()
    singletons = (cluster_sizes == 1).sum()

    print(f"\n{n_clusters} distinct new players identified:")
    print(f"  {fully_linked} linked across all 3 sources")
    print(f"  {partially_linked} linked across 2 sources")
    print(f"  {singletons} seen in only 1 source (unverified — could be a real gap or a name-match miss)")

    out_path = Path(output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    all_unmatched = all_unmatched.sort_values(["cluster_id", "source"])
    all_unmatched.to_csv(out_path, index=False)

    print(f"\nSaved: {out_path}")
    return out_path


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7):
        print("Usage: python reconcile_new_players.py <master_table_csv> <opta_csv> <whoscored_meta_csv> <fotmob_player_stats_csv> <output_csv> [other_league_teams_csv]")
        sys.exit(1)

    other_league_teams_csv = sys.argv[6] if len(sys.argv) == 7 else None

    try:
        reconcile_new_players(*sys.argv[1:6], other_league_teams_csv)
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
