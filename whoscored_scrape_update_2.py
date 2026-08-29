# Make sure to install selenium before running this script:
# pip install selenium

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import re

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def season_label_from_url(page_url: str) -> str:
    """
    Derive the season label from the page URL itself (e.g. ".../2026-2027"
    -> "2026_27") instead of hardcoding it, so this can't silently drift to
    a stale/finished season again like it did last time.
    """
    m = re.search(r"(\d{4})-(\d{4})$", page_url)
    if not m:
        raise ValueError(f"Could not find a season pattern (YYYY-YYYY) at the end of: {page_url}")
    start_year, end_year = m.group(1), m.group(2)
    return f"{start_year}_{end_year[-2:]}"

##############################
# LEAGUE CONFIG
##############################

# Updated for the 2026/27 season (previously hardcoded to the now-finished
# 2025/26 season — stageId is tied to a specific season instance, not just
# the league, so last season's ID silently points at stale/finished data
# rather than erroring). player counts bumped up with a buffer vs. last
# season's exact figures, since summer transfers can push squad sizes past
# the old cutoff and numberOfPlayersToPick silently truncates rather than
# erroring if it's too low.

LEAGUES = {

"EPL": {
"stageId":25544,
"players":560,
"page_url":
"https://www.whoscored.com/regions/252/tournaments/2/seasons/11141/stages/25544/playerstatistics/england-premier-league-2026-2027"
},

"SerieA":{
"stageId":25518,
"players":600,
"page_url":
"https://www.whoscored.com/regions/108/tournaments/5/seasons/11126/stages/25518/playerstatistics/italy-serie-a-2026-2027"
},

"Ligue1":{
"stageId":25554,
"players":555,
"page_url":
"https://www.whoscored.com/regions/74/tournaments/22/seasons/11150/stages/25554/playerstatistics/france-ligue-1-2026-2027"
},

"LaLiga":{
"stageId":25662,
"players":595,
"page_url":
"https://www.whoscored.com/regions/206/tournaments/4/seasons/11213/stages/25662/playerstatistics/spain-laliga-2026-2027"
},

"Bundesliga":{
"stageId":25666,
"players":510,
"page_url":
"https://www.whoscored.com/regions/81/tournaments/3/seasons/11217/stages/25666/playerstatistics/germany-bundesliga-2026-2027"
}

}


##############################
# API TEMPLATE
##############################

BASE_API = (
"https://www.whoscored.com/statisticsfeed/1/getplayerstatistics"
"?category={category}"
"&subcategory={subcategory}"
"&statsAccumulationType=2"
"&isCurrent=true"
"&stageId={stageId}"
"&tournamentOptions=2"
"&sortBy=Rating"
"&positionOptions=%27FW%27,%27AML%27,%27AMC%27,%27AMR%27,"
"%27ML%27,%27MC%27,%27MR%27,%27DMC%27,%27DL%27,"
"%27DC%27,%27DR%27,%27GK%27,%27Sub%27"
"&timeOfTheGameEnd=5"
"&timeOfTheGameStart=0"
"&page=1"
"&numberOfPlayersToPick={players}"
)


##############################
# WHAT TO COLLECT
##############################

COLLECTIONS = [
("goals","situations"),
("shots","situations"),
("dribbles","success"),
("possession-loss","type"),
("passes","type"),
("key-passes","type"),
("passes", "length"),
("key-passes","length"),
("tackles","success"),
("interception", "success"),
("blocks", "type"),
("clearances", "success"),
("aerial", "success")
]


##############################
# COOKIE BANNER DISMISSAL
##############################
#
# NOTE: these selectors are best-guesses based on common consent-management
# vendors (OneTrust, Quantcast/Sourcepoint, generic "Accept" text buttons).
# Not yet confirmed against WhoScored's actual banner from this environment
# (no network access to whoscored.com here). Run once with headless=False
# to visually confirm this actually dismisses the real banner, and adjust
# the selector list below if it doesn't.

COOKIE_BANNER_SELECTORS = [
    (By.ID, "onetrust-accept-btn-handler"),
    (By.CSS_SELECTOR, "button.qc-cmp2-summary-buttons > button[mode='primary']"),
    (By.CSS_SELECTOR, "#qc-cmp2-container button[mode='primary']"),
    (By.CSS_SELECTOR, "button[aria-label='Accept all']"),
    (By.XPATH, "//button[contains(translate(normalize-space(text()), 'ACEPT', 'acept'), 'accept')]"),
]


def dismiss_cookie_banner(driver, timeout=8) -> bool:
    """
    Best-effort automated dismissal of the cookie/ad consent banner.
    Tries a list of known selector patterns; if none match within `timeout`
    seconds each, gives up and lets the script continue anyway (the banner
    not being dismissed doesn't block the underlying fetch() calls — it's
    purely a page-interaction nicety, not an auth requirement).
    """
    for by, selector in COOKIE_BANNER_SELECTORS:
        try:
            btn = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, selector))
            )
            btn.click()
            print(f"  ✓ Dismissed cookie banner via selector: {selector}")
            time.sleep(1)  # let any overlay animation finish
            return True
        except (TimeoutException, NoSuchElementException):
            continue

    print("  ⚠️  No known cookie banner selector matched (may already be "
          "dismissed, or WhoScored changed their banner) — proceeding anyway")
    return False


##############################
# MAIN SCRAPE
##############################

def scrape_whoscored(output_dir: str | None = None) -> Path:
    if output_dir is None:
        todays_date = datetime.now().strftime("%Y-%m-%d")
        output_dir = f"whoscored_raw_json_{todays_date}"

    raw_json_dir = Path(output_dir)
    raw_json_dir.mkdir(parents=True, exist_ok=True)

    driver = webdriver.Chrome()

    results = {}

    try:
        first_league = list(LEAGUES.values())[0]
        print("Opening first league for cookies...")
        driver.get(first_league["page_url"])
        dismiss_cookie_banner(driver)

        for league_name, league in LEAGUES.items():
            print(f"\n========== {league_name} ==========")

            stageId = league["stageId"]
            players = league["players"]
            season_label = season_label_from_url(league["page_url"])

            print("Opening league page...")
            driver.get(league["page_url"])
            time.sleep(5)  # allow JS + ads to settle

            league_success = 0
            league_failed = 0

            for category, subcategory in COLLECTIONS:
                print(f"Collecting {category} / {subcategory}")

                api_url = BASE_API.format(
                    category=category,
                    subcategory=subcategory,
                    stageId=stageId,
                    players=players
                )

                data = driver.execute_async_script(f"""
                const done = arguments[0];
                fetch("{api_url}", {{ credentials: "include" }})
                .then(r => r.json())
                .then(d => done(JSON.stringify(d)))
                .catch(e => done(JSON.stringify({{error:e.toString()}})));
                """)

                data = json.loads(data)

                if "error" in data:
                    print(f"  ✗ ERROR: {data}")
                    league_failed += 1
                    continue

                filename = raw_json_dir / f"{league_name}_{season_label}_{category}_{subcategory}.json"
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)

                league_success += 1
                time.sleep(2)

            results[league_name] = f"{league_success} ok, {league_failed} failed"
            print(f"{league_name}: {league_success} ok, {league_failed} failed")

    finally:
        driver.quit()

    print("\nSummary:")
    for league, status in results.items():
        print(f"  {league}: {status}")

    print(f"\nALL LEAGUES COMPLETE. Output in: {raw_json_dir}")
    return raw_json_dir


if __name__ == "__main__":
    if len(sys.argv) > 2:
        print("Usage: python whoscored_scrape_update_2.py [output_dir]")
        sys.exit(1)

    output_dir = sys.argv[1] if len(sys.argv) == 2 else None
    scrape_whoscored(output_dir)
