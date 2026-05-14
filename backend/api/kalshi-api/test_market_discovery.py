#!/usr/bin/env python3
"""
Test Market Discovery Logic
Debug the dynamic market discovery to see what's happening
"""

import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

# Add the project root to the Python path
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

def get_current_event_ticker():
    """Dynamically find the current active event ticker"""
    est = ZoneInfo("America/New_York")
    now = datetime.now(est)
    
    print(f"Current time (EST): {now}")
    
    # Try current hour first
    test_time = now + timedelta(hours=1)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    current_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"
    
    print(f"Testing current hour ticker: {current_ticker}")
    
    data = fetch_event_json(current_ticker)
    if data and "markets" in data:
        print(f"✅ Found active markets for {current_ticker}")
        return current_ticker, data
    
    # Try next hour if current hour failed
    test_time = now + timedelta(hours=2)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    next_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"
    
    print(f"Testing next hour ticker: {next_ticker}")
    
    data = fetch_event_json(next_ticker)
    if data and "markets" in data:
        print(f"✅ Found active markets for {next_ticker}")
        return next_ticker, data
    
    print("❌ No active markets found")
    return None, None

def fetch_event_json(event_ticker):
    """Fetch event data from Kalshi REST API"""
    base_url = "https://external-api.kalshi.com/trade-api/v2"
    api_headers = {
        "Accept": "application/json",
        "User-Agent": "KalshiWatcher/1.0"
    }
    
    url = f"{base_url}/events/{event_ticker}"
    try:
        print(f"Fetching: {url}")
        response = requests.get(url, headers=api_headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            print(f"❌ API returned error for ticker {event_ticker}: {data['error']}")
            return None
        print(f"✅ Successfully fetched data for {event_ticker}")
        return data
    except Exception as e:
        print(f"❌ Exception fetching event JSON: {e}")
        return None

def main():
    print("🔍 Testing Market Discovery Logic")
    print("=" * 50)
    
    event_ticker, event_data = get_current_event_ticker()
    
    if event_ticker and event_data:
        markets = event_data.get("markets", [])
        print(f"\n📊 Found {len(markets)} markets in {event_ticker}")
        
        # Get current BTC price
        try:
            from backend.util.paths import get_host
            btc_response = requests.get(f"http://{get_host()}:3000/api/btc_price", timeout=5)
            if btc_response.ok:
                btc_data = btc_response.json()
                current_btc_price = btc_data.get("price", 118000)
            else:
                current_btc_price = 118000
        except:
            current_btc_price = 118000
        
        print(f"💰 Current BTC price: ${current_btc_price:,.0f}")
        
        # Find near-the-money strikes
        near_money_markets = []
        for market in markets:
            strike = market.get("floor_strike", 0)
            if abs(strike - current_btc_price) <= 1000:
                near_money_markets.append(market)
        
        print(f"🎯 Found {len(near_money_markets)} near-the-money markets")
        
        # Sort by distance from current price and take top 5
        near_money_markets.sort(key=lambda m: abs(m.get("floor_strike", 0) - current_btc_price))
        selected_markets = near_money_markets[:5]
        
        print("\n📋 Selected markets:")
        for i, market in enumerate(selected_markets):
            ticker = market.get("ticker")
            strike = market.get("floor_strike", 0)
            print(f"  {i+1}. {ticker} (${strike:,.0f})")
    else:
        print("❌ Failed to find any active markets")

if __name__ == "__main__":
    main() 