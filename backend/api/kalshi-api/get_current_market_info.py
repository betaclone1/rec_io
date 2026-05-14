import pytz
from datetime import datetime, timedelta
import os
import requests
import json
import sys

# === LOAD CREDENTIALS ===
# Add backend to path for local imports
from backend.util.paths import get_project_root
sys.path.append(get_project_root())
from load_credentials import read_kalshi_credentials

from backend.util.paths import get_kalshi_credentials_dir
pem_path = os.path.join(get_kalshi_credentials_dir(), "kalshi-auth.txt")
email, api_key = read_kalshi_credentials(pem_path)

# === CONFIG ===
EST = pytz.timezone("America/New_York")
BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

def get_current_event_ticker():
    now_est = datetime.now(EST)
    next_hour = (now_est + timedelta(hours=1)).hour
    hour_str = f"{next_hour:02d}"
    year = now_est.strftime("%y")         # e.g., "25"
    month = now_est.strftime("%b").upper() # e.g., "JUN"
    day = now_est.strftime("%d")          # e.g., "15"
    event_code = f"KXBTCD-{year}{month}{day}{hour_str}"
    return event_code

def get_market_title_from_event(event_json):
    try:
        return event_json["event"]["title"]
    except (KeyError, TypeError):
        return None

def extract_market_info(event_ticker):
    event_url = f"{BASE_URL}/events/{event_ticker}"
    event_response = requests.get(event_url, headers=headers)

    if event_response.status_code != 200:
        return {"error": "Failed to retrieve event info"}

    event_json = event_response.json().get("event", {})
    return {
        "full_title": event_json.get("title"),
        "subtitle": event_json.get("sub_title"),
        "utc_open": event_json.get("strike_date"),  # Kalshi returns this as close time of the hour
        "event_ticker": event_ticker
    }

# === AUTH ===
# api_key already loaded above
headers = {"Authorization": f"Bearer {api_key}"}

# === STATUS-ONLY MODE ===
if "--status-only" in sys.argv:
    test_response = requests.get(f"{BASE_URL}/series/KXBTCD", headers=headers)
    if test_response.status_code == 200:
        print("✅ Kalshi API is connected.")
        sys.exit(0)
    else:
        print("❌ No connection to Kalshi API.")
        sys.exit(1)

# === GET MARKETS ===
current_ticker = get_current_event_ticker()
if "--status-only" not in sys.argv:
    print("Searching for market containing:", current_ticker)

response = requests.get(f"{BASE_URL}/markets?event_ticker={current_ticker}", headers=headers)
if response.status_code != 200:
    print("API call failed.")
    print("Status code:", response.status_code)
    print("Response:", response.text)
    exit(1)
markets = response.json()["markets"]

# === FIND MARKET TITLE FROM FIRST MATCH ===
market = None
for m in markets:
    if m["event_ticker"] == current_ticker:
        market = m
        break  # only print first match

def get_event_json(event_ticker):
    event_url = f"{BASE_URL}/events/{event_ticker}"
    response = requests.get(event_url, headers=headers)
    if response.status_code == 200:
        return response.json()
    return {"error": f"Failed with status {response.status_code}"}

if __name__ == "__main__":
    current_ticker = get_current_event_ticker()
    print("Searching for market containing:", current_ticker)
    event_data = get_event_json(current_ticker)
    print(json.dumps(event_data, indent=2) if event_data else "Event data not found.")