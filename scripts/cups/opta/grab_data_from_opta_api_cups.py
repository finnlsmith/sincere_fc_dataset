"""
Scrape Opta stats (via theanalyst.com's public API) for the domestic cups.

Standalone copy of scripts/opta/grab_data_from_opta_api_2.py; the only real
difference is that the competitions come from scripts/cups/cups_config.py.
Cups with no confirmed tmcl yet are skipped with a message, not an error.

Usage:
    python scripts/cups/opta/grab_data_from_opta_api_cups.py [output_dir] [--cups EFLCup,DFBPokal]

Default output: data/opta/raw/opta_raw_cups_<YYYYMMDD_HHMMSS>/<CupKey>_stats.json
Parse it afterwards with the domestic parser (it's competition-agnostic):
    python scripts/opta/opta_json_to_csv.py data/opta/raw/opta_raw_cups_<TIMESTAMP> data/opta/parsed/opta_parsed_cups_<DATE>
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cups_config import CUPS  # noqa: E402

URL = "https://theanalyst.com/wp-json/sdapi/v1/soccerdata/tournamentstats"


def scrape_opta_cups(output_dir: str | None = None, only: list[str] | None = None) -> Path:
    from playwright.sync_api import sync_playwright

    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"data/opta/raw/opta_raw_cups_{timestamp}"

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output: {out_dir}")

    results = {}
    todo = {}
    for key, cup in CUPS.items():
        if only and key not in only:
            continue
        if not cup.get("opta_tmcl") or not cup.get("opta_url"):
            results[key] = "skipped (no tmcl/url in cups_config.py yet)"
            continue
        todo[key] = cup

    if todo:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()  # shared across all cups

            for key, cup in todo.items():
                tmcl_id, page_url = cup["opta_tmcl"], cup["opta_url"]
                print(f"Getting data for {key}...")
                page = context.new_page()

                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_selector("table", timeout=20000)
                except Exception as e:
                    print(f"  ✗ Page load failed: {e}")
                    results[key] = f"failed (page load: {e})"
                    page.close()
                    continue

                cookies = {c["name"]: c["value"] for c in context.cookies() if "theanalyst.com" in c["domain"]}
                user_agent = page.evaluate("() => navigator.userAgent")
                page.close()

                headers = {
                    "accept": "application/json, text/plain, */*",
                    "accept-language": "en-US,en;q=0.9",
                    "user-agent": user_agent,
                    "referer": page_url,
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                }

                try:
                    r = requests.get(URL, params={"tmcl": tmcl_id}, cookies=cookies, headers=headers, timeout=30)
                except requests.RequestException as e:
                    print(f"  ✗ Request failed: {e}")
                    results[key] = f"failed ({e})"
                    continue

                if r.status_code != 200:
                    print(f"  ✗ HTTP {r.status_code}")
                    results[key] = f"failed (HTTP {r.status_code})"
                    continue

                data = r.json()
                if "player" not in data:
                    print("  ⚠️  200 OK but response missing 'player' key (empty cup feed?)")
                filename = out_dir / f"{key}_stats.json"
                with open(filename, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"  ✓ Saved: {filename}")
                results[key] = "success"

            browser.close()

    print("\nSummary:")
    for key, status in results.items():
        print(f"  {key}: {status}")

    return out_dir


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
    scrape_opta_cups(output_dir, only)
