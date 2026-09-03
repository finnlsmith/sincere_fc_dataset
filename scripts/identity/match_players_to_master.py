"""
Match fresh 2026/27 per-source player data against master_player_table.csv
(built from 2025/26 data) using each source's own native platform player ID
— not fuzzy name matching. Platform IDs (Opta's numeric ID, WhoScored's
playerId, FotMob's player_id) are assigned once per player and don't change
season to season, so a direct ID lookup against the master table is far more
reliable than re-deriving name/team matches from scratch.

For each source, every fresh player ID either:
  - matches an ID already in master_player_table.csv, AND that master row's
    team is plausible for the league currently being processed -> gets that
    player's canonical_player_id (Opta's own ID system, since Opta is the
    table's anchor spine)
  - doesn't match anything in the table, OR matches a master row whose team
    is implausible for this league (see CROSS-LEAGUE SAFEGUARD below) ->
    flagged as "new_this_season", given a temporary source-prefixed ID
    (e.g. "opta_new_551230"), and kept (never silently dropped), consistent
    with master_player_table's own build philosophy.

CROSS-LEAGUE SAFEGUARD — added after finding real cases (Rodri, Péter
Gulácsi, Altay Bayindir) where a LaLiga scrape matched against a master
row whose canon_team was Manchester City / RB Leipzig / Manchester United
— clubs that aren't even in LaLiga. Unlike a same-league name collision
(e.g. two different real "Fran García"s, both actually in LaLiga), a
cross-LEAGUE collision like this is essentially never a coincidence — it's
almost certainly a stale/wrong ID baked into master_player_table.csv
during its original build, silently corrupting every future match against
that ID.

IMPORTANT — this check is deliberately narrower than "is this team in
today's specific league scrape": that version was tried first and produced
false positives, rejecting genuinely correct matches for players who
transferred out of a club not currently active in the league being
processed (e.g. relegated clubs like Mallorca/Girona/Real Oviedo — a
player who moved from one of those to a current LaLiga club over the
summer should still match correctly; their master row's team is just
stale, not wrong). The distinguishing signal that actually matters is
whether the master row's team belongs to a DIFFERENT LEAGUE ENTIRELY, not
merely whether it's absent from this round's specific club list.

So the check instead uses `other_league_teams_csv` (optional) — a simple
one-column CSV of team names known to belong to OTHER leagues, built from
each league's own live scrape data (see build_other_league_teams_reference
below), and built PER TARGET LEAGUE so it never includes that league's own
clubs. A match is only rejected if the master row's team is confidently
one of THOSE clubs. Without this file, the safeguard is skipped entirely
rather than guessing.

Usage:
    python match_players_to_master.py <master_table_csv> <opta_csv> <whoscored_meta_csv> <fotmob_player_stats_csv> <output_csv> [other_league_teams_csv]

Example:
    python match_players_to_master.py master_player_table.csv \\
        "English_Premier_League_..._merged_df_clean.csv" \\
        EPL_2026_27_player_meta.csv \\
        eng_47_player_stats.csv \\
        crosswalk_EPL_2026-08-28.csv \\
        other_league_teams.csv
"""

import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

TEAM_NAME_STOPWORDS = {"de", "la", "el", "a", "fc", "cf"}

# NOTE: the Bundesliga stopgap list (hardcoded club names used before
# Bundesliga had any live scrape to build a real other_league_teams CSV
# from) has been removed now that data/whoscored + data/fotmob have real
# Bundesliga data and reference_data/other_league_teams_for_Bundesliga.csv
# exists. That list was merged in unconditionally regardless of which
# league was being processed, so on a Bundesliga run it would incorrectly
# treat Bundesliga's own clubs as "other league" and wrongly reject
# correct matches. other_league_teams_csv (built per-league, correctly
# excluding the target league's own clubs) is now the only source for
# this safeguard.


def normalize(s) -> str:
    if pd.isna(s):
        return ""
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s)


def team_core_tokens(name: str) -> frozenset:
    return frozenset(t for t in normalize(name).split() if t not in TEAM_NAME_STOPWORDS)


def teams_match(team_a, team_b) -> bool:
    """Same logic as reconcile_new_players.py / build_player_legend.py:
    substring containment, or token-set equality/subset after stripping
    small connector words."""
    na, nb = normalize(team_a), normalize(team_b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ca, cb = team_core_tokens(team_a), team_core_tokens(team_b)
    if ca and cb and (ca == cb or ca.issubset(cb) or cb.issubset(ca)):
        return True
    return False


def team_is_other_league(canon_team, other_league_teams: set) -> bool:
    """True only if canon_team confidently matches a team known to belong
    to a DIFFERENT league — not simply "isn't in this league's current
    roster" (see module docstring for why that distinction matters)."""
    if pd.isna(canon_team) or not other_league_teams:
        return False
    return any(teams_match(canon_team, t) for t in other_league_teams)


def build_crosswalk(
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
    cross_league_rejections = []

    other_league_teams = set()
    if other_league_teams_csv is not None:
        ref = pd.read_csv(other_league_teams_csv)
        other_league_teams |= set(ref.iloc[:, 0].dropna().unique())
        print(f"Cross-league safeguard active: {len(other_league_teams)} known other-league teams "
              f"({other_league_teams_csv})")
    else:
        print("Cross-league safeguard skipped — no other_league_teams_csv passed in "
              "(matches from other leagues' stale IDs will not be caught)")

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

        is_matched = False
        canonical_id = f"opta_new_{int(pid)}"
        if pid in master_by_opta_id.index:
            master_team = master_by_opta_id.loc[pid, "canon_team"]
            if not team_is_other_league(master_team, other_league_teams):
                canonical_id = int(pid)
                is_matched = True
                opta_matched += 1
            else:
                cross_league_rejections.append({
                    "source": "opta", "name": r["player"], "native_id": int(pid),
                    "master_team": master_team,
                })

        rows.append({
            "source": "opta",
            "source_native_id": int(pid),
            "source_name": r["player"],
            "canonical_player_id": canonical_id,
            "matched_to_master": is_matched,
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

        is_matched = False
        canonical_id = f"whoscored_new_{int(pid)}"
        if pid in master_by_ws_id.index and pd.notna(master_by_ws_id.loc[pid, "player_id"]):
            master_team = master_by_ws_id.loc[pid, "canon_team"]
            if not team_is_other_league(master_team, other_league_teams):
                canonical_id = int(master_by_ws_id.loc[pid, "player_id"])
                is_matched = True
                ws_matched += 1
            else:
                cross_league_rejections.append({
                    "source": "whoscored", "name": r["name"], "native_id": int(pid),
                    "master_team": master_team,
                })

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

        is_matched = False
        canonical_id = f"fotmob_new_{int(pid)}"
        if pid in master_by_fotmob_id.index and pd.notna(master_by_fotmob_id.loc[pid, "player_id"]):
            master_team = master_by_fotmob_id.loc[pid, "canon_team"]
            if not team_is_other_league(master_team, other_league_teams):
                canonical_id = int(master_by_fotmob_id.loc[pid, "player_id"])
                is_matched = True
                fm_matched += 1
            else:
                cross_league_rejections.append({
                    "source": "fotmob", "name": r["player_name"], "native_id": int(pid),
                    "master_team": master_team,
                })

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

    if cross_league_rejections:
        rej_df = pd.DataFrame(cross_league_rejections)
        rej_path = out_path.parent / f"{out_path.stem}_CROSS_LEAGUE_REJECTIONS.csv"
        rej_df.to_csv(rej_path, index=False)
        print(f"⚠️  {len(cross_league_rejections)} match(es) rejected as implausible for this league "
              f"(master row's team isn't in this league at all) — routed to the 'new' bucket instead "
              f"of being silently accepted. See: {rej_path}")

    return out_path


if __name__ == "__main__":
    if len(sys.argv) not in (6, 7):
        print("Usage: python match_players_to_master.py <master_table_csv> <opta_csv> <whoscored_meta_csv> <fotmob_player_stats_csv> <output_csv> [other_league_teams_csv]")
        sys.exit(1)

    other_league_teams_csv = sys.argv[6] if len(sys.argv) == 7 else None

    try:
        build_crosswalk(*sys.argv[1:6], other_league_teams_csv)
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)
