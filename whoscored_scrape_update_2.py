# Make sure to install selenium before running this script:
# pip install selenium

from selenium import webdriver
import json
import time
import os


##############################
# LEAGUE CONFIG
##############################

LEAGUES = {

"EPL": {
"stageId":24533,
"players":528,
"page_url":
"https://www.whoscored.com/regions/252/tournaments/2/seasons/10743/stages/24533/playerstatistics/england-premier-league-2025-2026"
},

"SerieA":{
"stageId":24500, #the code for this season 
"players":571, #how many players are in the league
"page_url":
"https://www.whoscored.com/regions/108/tournaments/5/seasons/10732/stages/24500/playerstatistics/italy-serie-a-2025-2026" #the url for the league
},

"Ligue1":{
"stageId":24609,
"players":525,
"page_url":
"https://www.whoscored.com/regions/74/tournaments/22/seasons/10792/stages/24609/playerstatistics/france-ligue-1-2025-2026"
},

"LaLiga":{
"stageId":24622,
"players":566,
"page_url":
"https://www.whoscored.com/regions/206/tournaments/4/seasons/10803/stages/24622/playerstatistics/spain-laliga-2025-2026"
},

"Bundesliga":{
"stageId":24478,
"players":481,
"page_url":
"https://www.whoscored.com/regions/81/tournaments/3/seasons/10720/stages/24478/playerstatistics/germany-bundesliga-2025-2026"
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

from datetime import datetime
todays_date = datetime.now().strftime("%Y-%m-%d")

raw_json_dir = f"raw_json_{todays_date}"
os.makedirs(raw_json_dir, exist_ok=True)


##############################
# START BROWSER
##############################

driver = webdriver.Chrome()


##############################
# FIRST LOAD (COOKIES)
##############################

first_league = list(LEAGUES.values())[0]

print("Opening first league for cookies...")

driver.get(first_league["page_url"])

print("\nAccept cookies + close ads.\nThen press ENTER.")
input()


##############################
# MAIN LOOP
##############################

for league_name, league in LEAGUES.items():

    print(f"\n========== {league_name} ==========")

    stageId = league["stageId"]
    players = league["players"]

    print("Opening league page...")

    driver.get(league["page_url"])

    time.sleep(5)   # allow JS + ads to settle

    for category, subcategory in COLLECTIONS:

        print(f"\nCollecting {category} / {subcategory}")

        api_url = BASE_API.format(
            category=category,
            subcategory=subcategory,
            stageId=stageId,
            players=players
        )

        data = driver.execute_async_script(f"""

        const done = arguments[0];

        fetch("{api_url}", {{
            credentials: "include"
        }})
        .then(r => r.json())
        .then(d => done(JSON.stringify(d)))
        .catch(e => done(JSON.stringify({{error:e.toString()}})));

        """)

        data = json.loads(data)

        if "error" in data:

            print("ERROR:", data)
            continue

        filename = (
            f"{raw_json_dir}/"
            f"{league_name}_2025_26_{category}_{subcategory}.json"
        )

        print("Saving:", filename)

        # Ensure the directory exists before writing the file
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        time.sleep(2)


driver.quit()

print("\nALL LEAGUES COMPLETE.")