#!/usr/bin/env python3
"""
Debug WebSocket Messages
Capture and display raw WebSocket messages from Kalshi to understand the structure
"""

import asyncio
import json
import websockets
import requests
import base64
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from backend.util.paths import get_project_root, get_kalshi_credentials_dir
from backend.core.config.settings import config
from backend.account_mode import get_account_mode
from pathlib import Path
from dotenv import dotenv_values

EST = timezone(timedelta(hours=-5))

def load_kalshi_credentials():
    """Load Kalshi API credentials using the same method as the working script"""
    try:
        account_mode = get_account_mode()
        cred_dir = Path(get_kalshi_credentials_dir()) / account_mode
        
        if not cred_dir.exists():
            print(f"❌ No {account_mode} credentials found at {cred_dir}")
            return None
        
        env_vars = dotenv_values(cred_dir / ".env")
        key_path = cred_dir / "kalshi.pem"
        
        if not key_path.exists():
            print(f"❌ No private key file found at {key_path}")
            return None
        
        # Load private key
        with open(key_path, 'rb') as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend()
            )
        
        return {
            "KEY_ID": env_vars.get("KALSHI_API_KEY_ID"),
            "KEY_PATH": key_path,
            "private_key": private_key
        }
    except Exception as e:
        print(f"❌ Error loading credentials: {e}")
        return None

def get_current_event_ticker():
    """Get current Bitcoin event ticker"""
    now = datetime.now(EST)
    
    # Try current hour + 2 (for markets that are offset)
    test_time = now + timedelta(hours=2)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    current_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"
    
    # Verify this ticker exists via REST API
    try:
        response = requests.get(f"https://external-api.kalshi.com/trade-api/v2/events/{current_ticker}", timeout=10)
        if response.status_code == 200:
            data = response.json()
            if "markets" in data:
                markets = data.get("markets", [])
                market_tickers = [market.get("ticker", "") for market in markets if market.get("ticker")]
                return current_ticker, market_tickers[:5]  # Just get first 5 for debugging
    except Exception as e:
        print(f"❌ Error fetching event {current_ticker}: {e}")
    
    return None, []

async def debug_websocket_messages():
    """Debug WebSocket messages to understand structure"""
    print(f"[{datetime.now(EST)}] 🔍 Starting WebSocket Message Debug")
    
    # Load credentials
    credentials = load_kalshi_credentials()
    if not credentials:
        return
    
    # Get current markets
    event_ticker, market_tickers = get_current_event_ticker()
    if not market_tickers:
        print(f"❌ No markets found for event: {event_ticker}")
        return
    
    print(f"📊 Event: {event_ticker}")
    print(f"📊 Markets to debug: {market_tickers}")
    
    # Create authentication signature using the same method as the working script
    import time
    timestamp_ms = str(int(time.time() * 1000))
    signature_text = timestamp_ms + "GET" + "/trade-api/ws/v2"
    
    signature = credentials['private_key'].sign(
        signature_text.encode('utf-8'),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    
    signature_b64 = base64.b64encode(signature).decode('utf-8')
    
    headers = {
        "KALSHI-ACCESS-KEY": credentials["KEY_ID"],
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature_b64
    }
    
    # Connect to WebSocket
    uri = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
    
    try:
        async with websockets.connect(uri, additional_headers=headers) as websocket:
            print(f"✅ Connected to WebSocket")
            
            # Subscribe to orderbook_delta for first market
            subscribe_msg = {
                "type": "subscribe",
                "channel": "orderbook_delta",
                "market_tickers": [market_tickers[0]]  # Just one market for debugging
            }
            
            await websocket.send(json.dumps(subscribe_msg))
            print(f"📡 Subscribed to orderbook_delta for: {market_tickers[0]}")
            
            # Listen for messages
            message_count = 0
            async for message in websocket:
                try:
                    data = json.loads(message)
                    message_count += 1
                    
                    print(f"\n--- MESSAGE {message_count} ---")
                    print(f"Type: {data.get('type', 'unknown')}")
                    
                    if data.get("type") == "orderbook_snapshot":
                        print("📸 ORDERBOOK SNAPSHOT:")
                        msg_data = data.get("msg", {})
                        print(f"  Market: {msg_data.get('market_ticker')}")
                        print(f"  YES orders: {len(msg_data.get('yes', []))}")
                        print(f"  NO orders: {len(msg_data.get('no', []))}")
                        
                        # Show first few YES orders
                        yes_orders = msg_data.get('yes', [])
                        if yes_orders:
                            print("  YES orders (first 5):")
                            for i, order in enumerate(yes_orders[:5]):
                                print(f"    {i+1}: Price={order[0]}, Size={order[1]}")
                        
                        # Show first few NO orders
                        no_orders = msg_data.get('no', [])
                        if no_orders:
                            print("  NO orders (first 5):")
                            for i, order in enumerate(no_orders[:5]):
                                print(f"    {i+1}: Price={order[0]}, Size={order[1]}")
                    
                    elif data.get("type") == "orderbook_delta":
                        print("🔄 ORDERBOOK DELTA:")
                        msg_data = data.get("msg", {})
                        print(f"  Market: {msg_data.get('market_ticker')}")
                        print(f"  Side: {msg_data.get('side')}")
                        print(f"  Price: {msg_data.get('price')}")
                        print(f"  Delta: {msg_data.get('delta')}")
                    
                    elif data.get("type") == "error":
                        print(f"❌ ERROR: {data.get('msg')}")
                    
                    else:
                        print(f"📄 Raw message: {json.dumps(data, indent=2)}")
                    
                    # Stop after 10 messages
                    if message_count >= 10:
                        print(f"\n🛑 Stopping after {message_count} messages")
                        break
                        
                except json.JSONDecodeError as e:
                    print(f"❌ JSON decode error: {e}")
                except Exception as e:
                    print(f"❌ Error processing message: {e}")
                    
    except Exception as e:
        print(f"❌ WebSocket error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_websocket_messages())
