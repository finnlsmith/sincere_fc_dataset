"""
Scrape Opta stats (via theanalyst.com's public API) for the top-5 leagues.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = "https://theanalyst.com/wp-json/sdapi/v1/soccerdata/tournamentstats"

# All 5 tmcl values reconfirmed live via DevTools on Aug 28 2026. The
# original script also sent _meta_post_id/_meta_subpage — confirmed via
# DevTools that the real site does NOT send these for ANY league, only
# tmcl. That was likely leftover from an older API version, and combined
# with stale tmcl values for 4/5 leagues, is the most likely actual cause
# of the 401s (simpler than the context-sharing/fingerprint theory).
LEAGUES = {
    "EPL":        ("6pdwluctev9iebv00r4qqukno", "https://theanalyst.com/competition/premier-league/stats"),
    # "Bundesliga": ("8h5xijv2u4mlf5028gso6kw7o", "https://theanalyst.com/competition/bundesliga/stats"),
    "LaLiga":     ("830epggffy1nfkfyrtpqdwhlg", "https://theanalyst.com/competition/la-liga/stats"),
    "Ligue1":     ("bqnc4ccgnrp6pb3bktqet0yz8", "https://theanalyst.com/competition/ligue-1/stats"),
    "SerieA":     ("60cryos85i4bp5ul34tt0brx0", "https://theanalyst.com/competition/serie-a/stats"),
}


def scrape_opta(output_dir: str | None = None) -> Path:
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"opta_raw_{timestamp}"

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()  # shared across all leagues

        for league_name, (tmcl_id, league_url) in LEAGUES.items():
            print(f"Getting data for {league_name}...")
            page = context.new_page()

            try:
                # Use "domcontentloaded" instead of "networkidle" — this page
                # carries heavy continuous ad-tech traffic (prebid, tracking
                # pixels) that may never go fully idle within the timeout.
                # wait_for_selector below is the real signal that the page
                # (and its API call) actually finished loading.
                page.goto(league_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("table", timeout=20000)
            except Exception as e:
                print(f"  ✗ Page load failed: {e}")
                results[league_name] = f"failed (page load: {e})"
                page.close()
                continue

            cookies = {c["name"]: c["value"] for c in context.cookies() if "theanalyst.com" in c["domain"]}
            user_agent = page.evaluate("() => navigator.userAgent")
            page.close()

            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-US,en;q=0.9",
                "user-agent": user_agent,
                "referer": league_url,
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            }

            # Confirmed live for all 5 leagues: only tmcl, nothing else.
            params = {"tmcl": tmcl_id}

            try:
                r = requests.get(URL, params=params, cookies=cookies, headers=headers, timeout=30)
            except requests.RequestException as e:
                print(f"  ✗ Request failed: {e}")
                results[league_name] = f"failed ({e})"
                continue

            if r.status_code == 200:
                data = r.json()
                if "player" not in data:
                    print(f"  ⚠️  200 OK but response missing 'player' key")
                filename = out_dir / f"{league_name}_stats.json"
                with open(filename, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"  ✓ Saved: {filename}")
                results[league_name] = "success"
            else:
                print(f"  ✗ HTTP {r.status_code}")
                results[league_name] = f"failed (HTTP {r.status_code})"

        browser.close()

    print("\nSummary:")
    for league, status in results.items():
        print(f"  {league}: {status}")

    return out_dir


if __name__ == "__main__":
    output_dir = sys.argv[1] if len(sys.argv) > 1 else None
    scrape_opta(output_dir)
