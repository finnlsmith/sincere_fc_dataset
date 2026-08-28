import requests
import json
from datetime import datetime
from playwright.sync_api import sync_playwright

url = "https://theanalyst.com/wp-json/sdapi/v1/soccerdata/tournamentstats"

leagues = {
    
    "Bundesliga": ("2bchmrj23l9u42d68ntcekob8", 135740, "https://theanalyst.com/competition/bundesliga/stats"),
    "LaLiga":     ("80zg2v1cuqcfhphn56u4qpyqc", 135739, "https://theanalyst.com/competition/la-liga/stats"),
    "Ligue1":     ("dbxs75cag7zyip5re0ppsanmc", 135741, "https://theanalyst.com/competition/ligue-1/stats"),
    "SerieA":     ("emdmtfr1v8rey2qru3xzfwges", 135738, "https://theanalyst.com/competition/serie-a/stats"),
}

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    
    for league_name, (tmcl_id, post_id, league_url) in leagues.items():
        print(f"Getting data for {league_name}...")
        page = browser.new_page()
        page.goto(league_url)
        page.wait_for_selector("table", timeout=15000)
        cookies = {c["name"]: c["value"] for c in page.context.cookies() if "theanalyst.com" in c["domain"]}
        page.close()
        
        params = {"tmcl": tmcl_id, "_meta_post_id": post_id, "_meta_subpage": "stats"}
        r = requests.get(url, params=params, cookies=cookies, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        
        if r.status_code == 200:
            data = r.json()
            filename = f"{league_name}_stats_{timestamp}.json"
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Saved: {filename}")
        else:
            print(f"Failed: {league_name} (status {r.status_code})")
    
    browser.close()