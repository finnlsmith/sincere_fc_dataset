"""
Scrape WhoScored player statistics for the domestic cups.

Standalone copy of scripts/whoscored/whoscored_scrape_update_2.py, with one
real difference: on WhoScored a cup is usually split into one stage per
round, and the stats feed only takes one stageId at a time. So for each cup
this fetches every round listed in cups_config.py and merges them into one
season-to-date row per player (merge_stage_payloads below):
  - counting stats (apps, minsPlayed, goals, tackles...) are summed
  - rating is a minutes-weighted average across rounds
  - isManOfTheMatch is True if it was True in any round
  - descriptive fields (name, team, age, positions...) come from the latest round
  - ranking is recomputed by merged rating

The merged file is written in exactly the same format and naming as the
domestic scraper (<CupKey>_<season>_<category>_<subcategory>.json), so the
domestic parser reads it unchanged:
    python scripts/whoscored/parse_whoscored_jsons.py data/whoscored/raw/whoscored_raw_json_cups_<DATE> data/whoscored/parsed/parsed_whoscored_cups_<DATE>

Each round's raw response is also kept in _stages/ inside the output folder,
for checking.

Usage:
    python scripts/cups/whoscored/whoscored_scrape_cups.py [output_dir] [--cups EFLCup,DFBPokal]
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cups_config import CUPS  # noqa: E402


def season_label_from_url(page_url: str) -> str:
    """'.../2026-2027' -> '2026_27' (same rule as the domestic scraper)."""
    m = re.search(r"(\d{4})-(\d{4})$", page_url)
    if not m:
        raise ValueError(f"Could not find a season pattern (YYYY-YYYY) at the end of: {page_url}")
    return f"{m.group(1)}_{m.group(2)[2:]}"


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

COLLECTIONS = [
    ("goals", "situations"),
    ("shots", "situations"),
    ("dribbles", "success"),
    ("possession-loss", "type"),
    ("passes", "type"),
    ("key-passes", "type"),
    ("passes", "length"),
    ("key-passes", "length"),
    ("tackles", "success"),
    ("interception", "success"),
    ("blocks", "type"),
    ("clearances", "success"),
    ("aerial", "success"),
]

# Fields that describe the player rather than count something. Never summed;
# taken from the most recent round the player appears in.
DESCRIPTIVE_FIELDS = {
    "height", "weight", "age", "isActive", "playedPositions", "playedPositionsShort",
    "teamRegionName", "regionCode", "tournamentShortName", "name", "firstName", "lastName",
    "playerId", "positionText", "teamId", "teamName", "seasonId", "seasonName", "isOpta",
    "tournamentId", "tournamentRegionId", "tournamentRegionCode", "tournamentRegionName",
    "tournamentName", "ranking",
}


##############################
# MERGING ROUNDS
##############################

def merge_stage_payloads(payloads: list[dict]) -> dict:
    """
    Merge several getplayerstatistics responses (one per round, oldest first)
    into one response with a single season-to-date row per player.
    A single payload is returned unchanged.
    """
    payloads = [p for p in payloads if isinstance(p, dict) and "playerTableStats" in p]
    if not payloads:
        return {"playerTableStats": [], "paging": {}, "statColumns": []}
    if len(payloads) == 1:
        return payloads[0]

    merged: dict[tuple, dict] = {}
    rating_weight: dict[tuple, float] = {}
    rating_sum: dict[tuple, float] = {}

    for payload in payloads:  # oldest round first, so later rounds win for descriptive fields
        for row in payload["playerTableStats"]:
            key = (row.get("playerId"), row.get("teamId"))
            mins = row.get("minsPlayed") or 0
            apps = row.get("apps") or 0
            weight = mins if mins else apps

            rating = row.get("rating")
            if isinstance(rating, (int, float)) and weight:
                rating_sum[key] = rating_sum.get(key, 0.0) + rating * weight
                rating_weight[key] = rating_weight.get(key, 0.0) + weight

            if key not in merged:
                merged[key] = dict(row)
                continue

            out = merged[key]
            for field, value in row.items():
                if field == "rating":
                    continue
                if field in DESCRIPTIVE_FIELDS:
                    out[field] = value
                elif field == "isManOfTheMatch":
                    out[field] = bool(out.get(field)) or bool(value)
                elif isinstance(value, bool):
                    out[field] = value
                elif isinstance(value, (int, float)):
                    prev = out.get(field)
                    out[field] = (prev if isinstance(prev, (int, float)) and not isinstance(prev, bool) else 0) + value
                else:
                    out[field] = value

    rows = list(merged.values())
    for key, row in merged.items():
        if rating_weight.get(key):
            row["rating"] = round(rating_sum[key] / rating_weight[key], 3)

    rows.sort(key=lambda r: (r.get("rating") if isinstance(r.get("rating"), (int, float)) else -1), reverse=True)
    for i, row in enumerate(rows, start=1):
        row["ranking"] = i

    base = payloads[-1]
    paging = dict(base.get("paging") or {})
    if "totalResults" in paging:
        paging["totalResults"] = len(rows)
    return {
        "playerTableStats": rows,
        "paging": paging,
        "statColumns": base.get("statColumns", []),
        "mergedStageCount": len(payloads),
    }


##############################
# COOKIE BANNER DISMISSAL (same as domestic)
##############################

def dismiss_cookie_banner(driver, timeout=8) -> bool:
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    selectors = [
        (By.ID, "onetrust-accept-btn-handler"),
        (By.CSS_SELECTOR, "button.qc-cmp2-summary-buttons > button[mode='primary']"),
        (By.CSS_SELECTOR, "#qc-cmp2-container button[mode='primary']"),
        (By.CSS_SELECTOR, "button[aria-label='Accept all']"),
        (By.XPATH, "//button[contains(translate(normalize-space(text()), 'ACEPT', 'acept'), 'accept')]"),
    ]
    for by, selector in selectors:
        try:
            WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector))).click()
            print(f"  ✓ Dismissed cookie banner via selector: {selector}")
            time.sleep(1)
            return True
        except (TimeoutException, NoSuchElementException):
            continue
    print("  ⚠️  No known cookie banner selector matched — proceeding anyway")
    return False


##############################
# MAIN SCRAPE
##############################

def fetch_json(driver, api_url: str) -> dict:
    data = driver.execute_async_script(f"""
    const done = arguments[0];
    fetch("{api_url}", {{ credentials: "include" }})
    .then(r => r.json())
    .then(d => done(JSON.stringify(d)))
    .catch(e => done(JSON.stringify({{error:e.toString()}})));
    """)
    return json.loads(data)


def scrape_whoscored_cups(output_dir: str | None = None, only: list[str] | None = None) -> Path:
    from selenium import webdriver

    if output_dir is None:
        output_dir = f"data/whoscored/raw/whoscored_raw_json_cups_{datetime.now().strftime('%Y-%m-%d')}"
    raw_json_dir = Path(output_dir)
    stage_dir = raw_json_dir / "_stages"
    stage_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    todo = {}
    for key, cup in CUPS.items():
        if only and key not in only:
            continue
        if not cup.get("whoscored_stages") or not cup.get("whoscored_page_url"):
            results[key] = "skipped (no stages/page_url in cups_config.py yet)"
            continue
        todo[key] = cup

    if todo:
        driver = webdriver.Chrome()
        try:
            first = next(iter(todo.values()))
            print("Opening first cup for cookies...")
            driver.get(first["whoscored_page_url"])
            dismiss_cookie_banner(driver)

            for key, cup in todo.items():
                print(f"\n========== {key} ({len(cup['whoscored_stages'])} round stage(s)) ==========")
                season_label = season_label_from_url(cup["whoscored_page_url"])
                driver.get(cup["whoscored_page_url"])
                time.sleep(5)

                ok = failed = 0
                for category, subcategory in COLLECTIONS:
                    print(f"Collecting {category} / {subcategory}")
                    payloads = []
                    for stage_id in cup["whoscored_stages"]:
                        api_url = BASE_API.format(category=category, subcategory=subcategory,
                                                  stageId=stage_id, players=cup["whoscored_players"])
                        data = fetch_json(driver, api_url)
                        if "error" in data:
                            print(f"  ✗ stage {stage_id}: {data}")
                            continue
                        n = len(data.get("playerTableStats", []))
                        if n >= cup["whoscored_players"]:
                            print(f"  ⚠️  stage {stage_id}: hit the {n}-player cap; raise whoscored_players")
                        print(f"  stage {stage_id}: {n} players")
                        with open(stage_dir / f"{key}_{season_label}_{stage_id}_{category}_{subcategory}.json", "w",
                                  encoding="utf-8") as f:
                            json.dump(data, f, indent=2)
                        payloads.append(data)
                        time.sleep(2)

                    if not payloads:
                        failed += 1
                        continue

                    merged = merge_stage_payloads(payloads)
                    filename = raw_json_dir / f"{key}_{season_label}_{category}_{subcategory}.json"
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(merged, f, indent=2)
                    print(f"  → merged {len(payloads)} round(s): {len(merged['playerTableStats'])} players")
                    ok += 1

                results[key] = f"{ok} ok, {failed} failed"
                print(f"{key}: {ok} ok, {failed} failed")
        finally:
            driver.quit()

    print("\nSummary:")
    for key, status in results.items():
        print(f"  {key}: {status}")
    print(f"\nOutput in: {raw_json_dir}")
    return raw_json_dir


def _parse_cli(argv):
    only, rest = None, []
    i = 0
    while i < len(argv):
        if argv[i] == "--cups":
            only = [c.strip() for c in argv[i + 1].split(",") if c.strip()]
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return (rest[0] if rest else None), only


if __name__ == "__main__":
    output_dir, only = _parse_cli(sys.argv[1:])
    scrape_whoscored_cups(output_dir, only)
