"""
Shared "do we already know this player?" lookup, used by both
match_players_to_master.py and reconcile_new_players.py so the two scripts
can never disagree about who counts as matched (they used to keep separate
copies of this logic, which is how players went missing in the past).

A player is "known" if their source-native ID (Opta player_id, WhoScored
playerId or FotMob player_id) appears in either:

  1. reference_data/player_id_map.csv — the persistent, season-long ID map
     that update_player_id_map.py grows after every weekly run. Checked
     FIRST, since it holds the most recent team and every cross-source link
     worked out so far this season.
  2. master_player_table.csv — the 2025/26 table. Never written to.

CROSS-LEAGUE SAFEGUARD (revised 2026-10-27)
The original safeguard rejected every ID match whose master row sat at a
club in a different top-5 league, to catch stale/wrong IDs (Rodri, Gulácsi,
Bayindir). Checked against the 2026-10-23 run, all 615 rejections across
the five leagues were the same person — same native ID, same name — who had
simply transferred between top-5 leagues over the summer (Chilwell,
Gallagher, Barcola, ...). Matching is by native ID, so ID + agreeing name is
effectively certain. The safeguard now only rejects when the names DON'T
agree, which is the genuine wrong-ID case it was written for. Accepted
cross-league matches are returned with via="master_transfer" so the caller
can log them as club changes.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

TEAM_NAME_STOPWORDS = {"de", "la", "el", "a", "fc", "cf"}
NAME_MATCH_THRESHOLD = 0.82
SOURCES = ("opta", "whoscored", "fotmob")
ID_MAP_COLUMNS = [
    "canonical_id", "name", "team", "league",
    "opta_id", "whoscored_id", "fotmob_id",
    "link_status", "first_seen", "last_seen",
]


# ─── normalisation helpers (single copy, imported by the other scripts) ─────

def normalize(s) -> str:
    if pd.isna(s):
        return ""
    s = str(s).lower().strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s)


def name_similarity(a, b) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def names_agree(a, b) -> bool:
    """Loose on purpose: only used where the native ID ALREADY matches, to
    tell "same person, different spelling/length of name" (accept) from
    "a different person sitting on this ID" (reject). Accepts high fuzzy
    similarity, one name's tokens being a subset of the other's (e.g.
    "Vitinha" / "Vitor Machado Ferreira Vitinha"), or a shared token of 4+
    letters (shared surname)."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    if SequenceMatcher(None, na, nb).ratio() >= NAME_MATCH_THRESHOLD:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if ta <= tb or tb <= ta:
        return True
    return any(len(t) >= 4 for t in ta & tb)


# Club spellings that share no token across sources (checked all five
# leagues on 2026-10-23 — only these two Bundesliga clubs failed). Applied
# after normalize(), so accents and punctuation are already gone.
TEAM_ALIASES = [
    (r"\bm ?gladbach\b", "monchengladbach"),   # WhoScored "Borussia M.Gladbach"
    (r"\bmunchen\b", "munich"),                # FotMob "FC Bayern München"
]


def normalize_team(name) -> str:
    s = normalize(str(name).replace(".", " ")) if pd.notna(name) else ""
    for pattern, repl in TEAM_ALIASES:
        s = re.sub(pattern, repl, s)
    return s


def team_core_tokens(name) -> frozenset:
    return frozenset(t for t in normalize_team(name).split() if t not in TEAM_NAME_STOPWORDS)


def teams_match(team_a, team_b) -> bool:
    na, nb = normalize_team(team_a), normalize_team(team_b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    ca, cb = team_core_tokens(team_a), team_core_tokens(team_b)
    return bool(ca and cb and (ca == cb or ca.issubset(cb) or cb.issubset(ca)))


def team_is_other_league(team, other_league_teams: set) -> bool:
    if pd.isna(team) or not other_league_teams:
        return False
    return any(teams_match(team, t) for t in other_league_teams)


def load_other_league_teams(path) -> set:
    if path is None:
        print("Cross-league safeguard skipped — no other_league_teams_csv passed in")
        return set()
    ref = pd.read_csv(path)
    teams = set(ref.iloc[:, 0].dropna().unique())
    print(f"Cross-league safeguard active: {len(teams)} known other-league teams ({path})")
    return teams


# ─── one row per player ──────────────────────────────────────────────────────

def one_row_per_id(df: pd.DataFrame, id_col: str, name_col: str, team_col: str) -> pd.DataFrame:
    """Collapse a source's player rows to exactly one per native ID.
    FotMob in particular spells the same player with and without accents
    in different matches ("Edin Džeko" / "Edin Dzeko", same player_id), and
    de-duplicating on name+ID used to turn each spelling into a separate
    player — ~40 duplicate FotMob IDs across the five legends on 2026-10-23.
    Keeps the spelling with the most accented characters (the proper one)
    and the team the player appears for most often. Rows without an ID are
    kept as they are."""
    df = df.copy()
    df[id_col] = pd.to_numeric(df[id_col], errors="coerce").astype("Int64")
    no_id = df[df[id_col].isna()].drop_duplicates(subset=[name_col])
    has_id = df[df[id_col].notna()]
    if has_id.empty:
        return no_id

    def pick(g):
        names = g[name_col].dropna().astype(str)
        name = max(names, key=lambda n: sum(ord(ch) > 127 for ch in n)) if len(names) else None
        teams = g[team_col].dropna()
        team = teams.mode().iloc[0] if len(teams) else None
        return pd.Series({name_col: name, team_col: team})

    collapsed = has_id.groupby(id_col, sort=False)[[name_col, team_col]].apply(pick).reset_index()
    out = pd.concat([collapsed, no_id[[id_col, name_col, team_col]]], ignore_index=True)
    return out[list(df.columns)]  # keep the caller's column order


# ─── Opta team names ─────────────────────────────────────────────────────────

def opta_team_names(opta: pd.DataFrame, team_id_col: str, team_map: pd.Series) -> pd.Series:
    """Team name per Opta row: the master table's canon_team for that
    team_id when it knows the club, otherwise Opta's own contestant name.
    The master only knows 2025/26 clubs, so promoted sides (Elversberg,
    Paderborn, Coventry, Venezia, ...) used to come back blank — about 360
    players across the five leagues on 2026-10-23 — and could never be
    clustered with their WhoScored/FotMob sightings."""
    tid = pd.to_numeric(opta[team_id_col], errors="coerce")
    names = tid.map(team_map)
    for suffix in ("_contestantClubName", "_contestantShortName", "_contestantName"):
        cols = [c for c in opta.columns if c.endswith(suffix)]
        if cols:
            names = names.fillna(opta[cols].bfill(axis=1).iloc[:, 0])
    return names


# ─── the lookup itself ───────────────────────────────────────────────────────

class KnownIdentities:
    def __init__(self, master_table_csv, other_league_teams_csv=None, id_map_csv=None):
        print("Loading master_player_table.csv ...")
        master = pd.read_csv(
            master_table_csv,
            usecols=["player_id", "player", "team_id", "canon_team", "fotmob_player_id", "whoscored_playerId"],
            low_memory=False,
        )
        for c in ["player_id", "team_id", "fotmob_player_id", "whoscored_playerId"]:
            master[c] = pd.to_numeric(master[c], errors="coerce").astype("Int64")
        self.team_map = master.dropna(subset=["team_id"]).drop_duplicates("team_id").set_index("team_id")["canon_team"]

        native_col = {"opta": "player_id", "whoscored": "whoscored_playerId", "fotmob": "fotmob_player_id"}
        self.master_by = {
            src: master.dropna(subset=[col]).drop_duplicates(col).set_index(col, drop=False)
            for src, col in native_col.items()
        }

        self.other_league_teams = load_other_league_teams(other_league_teams_csv)

        self.map_by = {src: {} for src in SOURCES}
        self.id_map_path = id_map_csv
        if id_map_csv is not None and Path(id_map_csv).exists():
            idm = pd.read_csv(id_map_csv, dtype={"canonical_id": str})
            for _, r in idm.iterrows():
                for src in SOURCES:
                    v = r.get(f"{src}_id")
                    if pd.notna(v):
                        self.map_by[src][int(v)] = r
            print(f"Player ID map loaded: {len(idm)} players already known this season ({id_map_csv})")
        elif id_map_csv is not None:
            print(f"Player ID map not found yet ({id_map_csv}) — it will be created by update_player_id_map.py")

    def lookup(self, source: str, native_id, scraped_name):
        """Returns (canonical_id, via, known_team, master_team):
          via = "id_map"           known from earlier weeks this season
                "master"           in the 2025/26 master table
                "master_transfer"  in master at a club in another top-5
                                   league, names agree → accepted, a transfer
                None               unknown (canonical_id is None)
                "rejected"         in master, other-league club AND the
                                   names disagree → treated as unknown
        """
        if pd.isna(native_id):
            return None, None, None, None
        pid = int(native_id)

        hit = self.map_by[source].get(pid)
        if hit is not None:
            return str(hit["canonical_id"]), "id_map", hit.get("team"), None

        idx = self.master_by[source]
        if pid not in idx.index:
            return None, None, None, None
        row = idx.loc[pid]
        # Master rows without an Opta anchor (whoscored_only / fotmob_only
        # confidence tiers) have no canonical ID to hand out → unknown.
        if pd.isna(row["player_id"]):
            return None, None, None, None
        canonical = str(int(row["player_id"]))
        master_team = row["canon_team"]
        if team_is_other_league(master_team, self.other_league_teams):
            if names_agree(scraped_name, row["player"]):
                return canonical, "master_transfer", None, master_team
            return None, "rejected", None, master_team
        return canonical, "master", master_team, master_team
