"""
Domestic cups config: the single place every cup ID lives.

Every other script in scripts/cups/ reads from here, so filling in a newly
confirmed ID (or a new WhoScored round stage) is a one-line change in this
file only.

Keys (EFLCup, CoppaItalia, ...) are used in filenames. They must NOT contain
an underscore, because parse_whoscored_jsons.py splits filenames on "_".

What's confirmed and what isn't (as of 2026-10-28):
  - fotmob_name / fotmob_key: confirmed in reference_data/master_leagues.json
    (all five names are unique, so no "(XXX)" country suffix is needed).
  - opta_tmcl / opta_url: NOT YET CONFIRMED. Get them the same way as the
    league and European ones: open the cup's stats page on theanalyst.com,
    DevTools -> Network, filter "tournamentstats", copy the tmcl= value.
    Leave tmcl as None if theanalyst.com has no stats page for that cup;
    the Opta step then skips it and identity runs on WhoScored + FotMob.
  - whoscored_stages: NOT YET CONFIRMED. On WhoScored, cups are usually
    split into one stage per round. Open the cup's "Player Statistics" page,
    use the stage/round dropdown, and add every round's stageId here. The
    scraper fetches each stage and merges them into one season total per
    player. Add new rounds as the cup progresses.
  - domestic_league: which top-5 league the cup belongs to. Used to pick
    reference_data/other_league_teams_for_<league>.csv for identity.
"""

SEASON = "2026/2027"

CUPS = {
    "EFLCup": {
        "display_name": "EFL Cup",
        "domestic_league": "EPL",
        "fotmob_name": "EFL Cup",
        "fotmob_key": "eng_133",
        "opta_tmcl": None,  # TODO: confirm via DevTools
        "opta_url": None,   # TODO: theanalyst.com stats page for the cup, if one exists
        "whoscored_stages": [],  # TODO: one stageId per round, e.g. [25901, 25902]
        "whoscored_players": 600,
        "whoscored_page_url": None,  # TODO: any of the cup's 2026-2027 playerstatistics pages
    },
    "CoppaItalia": {
        "display_name": "Coppa Italia",
        "domestic_league": "SerieA",
        "fotmob_name": "Coppa Italia",
        "fotmob_key": "ita_141",
        "opta_tmcl": None,
        "opta_url": None,
        "whoscored_stages": [],
        "whoscored_players": 600,
        "whoscored_page_url": None,
    },
    "DFBPokal": {
        "display_name": "DFB Pokal",
        "domestic_league": "Bundesliga",
        "fotmob_name": "DFB Pokal",
        "fotmob_key": "ger_209",
        "opta_tmcl": None,
        "opta_url": None,
        "whoscored_stages": [],
        "whoscored_players": 600,
        "whoscored_page_url": None,
    },
    "CopaDelRey": {
        "display_name": "Copa del Rey",
        "domestic_league": "LaLiga",
        "fotmob_name": "Copa del Rey",
        "fotmob_key": "esp_138",
        "opta_tmcl": None,
        "opta_url": None,
        "whoscored_stages": [],
        "whoscored_players": 600,
        "whoscored_page_url": None,
    },
    "CoupeDeFrance": {
        "display_name": "Coupe de France",
        "domestic_league": "Ligue1",
        "fotmob_name": "Coupe de France",
        "fotmob_key": "fra_134",
        "opta_tmcl": None,
        "opta_url": None,
        "whoscored_stages": [],
        "whoscored_players": 600,
        "whoscored_page_url": None,
    },
}


def season_slug(season: str = SEASON) -> str:
    """'2026/2027' -> '2026_2027' (FotMob folder naming)."""
    return season.replace("/", "_")


def check_keys() -> None:
    for key in CUPS:
        if "_" in key:
            raise ValueError(f"Cup key '{key}' contains '_'; the WhoScored parser splits filenames on '_'.")


check_keys()
