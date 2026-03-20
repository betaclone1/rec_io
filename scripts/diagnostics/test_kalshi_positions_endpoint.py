#!/usr/bin/env python3
"""
Test GET /portfolio/positions on Kalshi trade-api v2.
Uses same auth and base URL as kalshi_account_sync_ws. No DB writes.
Run from project root: python3 scripts/diagnostics/test_kalshi_positions_endpoint.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import requests

from backend.account_mode import get_account_mode
from backend.kalshi_account_sync_ws import (
    KEY_ID,
    KEY_PATH,
    generate_kalshi_signature,
    get_base_url,
)


def main():
    if not KEY_ID or not KEY_PATH.exists():
        print("Missing Kalshi API credentials or PEM file.")
        print(f"  KEY_ID present: {bool(KEY_ID)}")
        print(f"  KEY_PATH exists: {KEY_PATH}")
        sys.exit(1)

    method = "GET"
    path = "/portfolio/positions"
    query = "?limit=50"
    timestamp = str(int(time.time() * 1000))
    full_path_for_signature = f"/trade-api/v2{path}"
    signature = generate_kalshi_signature(method, full_path_for_signature, timestamp, str(KEY_PATH))

    url = f"{get_base_url()}{path}{query}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "KalshiWatcher/1.0",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }

    print(f"Mode: {get_account_mode()}")
    print(f"URL:  {url}")
    print()

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Status: {response.status_code}")
        if response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
            print(json.dumps(data, indent=2))
            market_positions = data.get("market_positions", [])
            event_positions = data.get("event_positions", [])
            if market_positions or event_positions:
                print()
                print(f"market_positions: {len(market_positions)}")
                print(f"event_positions:  {len(event_positions)}")
        else:
            print(response.text[:500])
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
