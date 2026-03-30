#!/usr/bin/env python3
"""
Kalshi WebSocket Market Data Watchdog
Uses official Kalshi WebSocket API for real-time market data
"""

import asyncio
import websockets
import json
import sqlite3
import time
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from dotenv import dotenv_values
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import base64

# Import from backend modules
from backend.util.paths import get_kalshi_data_dir, ensure_data_dirs
from backend.account_mode import get_account_mode
from backend.core.config.feature_flags import (
    websocket_timeout, websocket_max_retries, 
    websocket_fallback_to_http, websocket_debug
)

# Ensure all data directories exist
ensure_data_dirs()

# Configuration
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
REST_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
EST = ZoneInfo("America/New_York")

# Data paths
DB_PATH = Path(get_kalshi_data_dir()) / "kalshi_websocket_market_log.db"
JSON_SNAPSHOT_PATH = Path(get_kalshi_data_dir()) / "latest_websocket_market_snapshot.json"
HEARTBEAT_PATH = Path(get_kalshi_data_dir()) / "kalshi_websocket_heartbeat.txt"


def _cents_to_dollar_text(cents):
    if cents is None:
        return None
    try:
        x = float(cents) / 100.0
    except (TypeError, ValueError):
        return None
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


class KalshiWebSocketWatchdog:
    def __init__(self):
        self.websocket = None
        self.subscription_id = None
        self.command_id = 1
        self.fallback_to_http = websocket_fallback_to_http()
        self.max_retries = websocket_max_retries()
        self.timeout = websocket_timeout()
        self.debug = websocket_debug()
        
        # Market data cache for building complete snapshots
        self.market_cache = {}  # event_ticker -> {markets: [], event_data: {}, last_update: timestamp}
        self.snapshot_interval = 5  # seconds between complete snapshots
        
        # Initialize database
        self.init_db()
        
    def load_kalshi_credentials(self):
        """Load Kalshi API credentials"""
        account_mode = get_account_mode()
        from backend.util.paths import get_kalshi_credentials_dir
        cred_dir = Path(get_kalshi_credentials_dir()) / account_mode
        
        if not cred_dir.exists():
            print(f"❌ No {account_mode} credentials found at {cred_dir}")
            return None
        
        env_vars = dotenv_values(cred_dir / ".env")
        key_path = cred_dir / "kalshi.pem"
        
        if not key_path.exists():
            print(f"❌ No private key file found at {key_path}")
            return None
        
        return {
            "KEY_ID": env_vars.get("KALSHI_API_KEY_ID"),
            "KEY_PATH": key_path
        }
    
    def generate_kalshi_signature(self, timestamp, method, path, body=""):
        """Generate Kalshi API signature"""
        credentials = self.load_kalshi_credentials()
        if not credentials:
            return None
        
        # Load private key
        with open(credentials["KEY_PATH"], "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend()
            )
        
        # Create signature string
        signature_string = f"{timestamp}{method}{path}{body}"
        
        # Sign the string
        signature = private_key.sign(
            signature_string.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        
        # Return headers
        return {
            "X-Kalshi-Api-Key": credentials["KEY_ID"],
            "X-Kalshi-Timestamp": str(timestamp),
            "X-Kalshi-Signature": base64.b64encode(signature).decode('utf-8')
        }
    
    def get_current_bitcoin_markets(self):
        """Get current Bitcoin markets for WebSocket subscription"""
        try:
            # First, get the current Bitcoin event ticker
            current_ticker = self.get_current_bitcoin_event_ticker()
            if not current_ticker:
                print(f"[{datetime.now(EST)}] ⚠️ No current Bitcoin event found, using fallback markets")
                return self.get_fallback_markets()
            
            # Get all markets for this event
            event_data = self.fetch_event_data(current_ticker)
            if not event_data or "markets" not in event_data:
                print(f"[{datetime.now(EST)}] ⚠️ No markets found for {current_ticker}, using fallback")
                return self.get_fallback_markets()
            
            # Extract market tickers
            market_tickers = [market.get("ticker") for market in event_data["markets"] if market.get("ticker")]
            
            print(f"[{datetime.now(EST)}] 🪙 Using Bitcoin markets for {current_ticker}: {len(market_tickers)} markets")
            return market_tickers[:10]  # Limit to first 10 markets for testing
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error getting Bitcoin markets: {e}")
            return self.get_fallback_markets()
    
    def get_current_bitcoin_event_ticker(self):
        """Get current Bitcoin event ticker using REST API"""
        try:
            credentials = self.load_kalshi_credentials()
            if not credentials:
                return None
            
            # Generate signature for REST API call
            timestamp_ms = str(int(time.time() * 1000))
            method = "GET"
            path = "/events"
            
            signature_text = timestamp_ms + method + path
            
            # Load private key and sign
            with open(credentials["KEY_PATH"], "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            
            signature = private_key.sign(
                signature_text.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            signature_b64 = base64.b64encode(signature).decode('utf-8')
            
            headers = {
                "Accept": "application/json",
                "KALSHI-ACCESS-KEY": credentials["KEY_ID"],
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
                "KALSHI-ACCESS-SIGNATURE": signature_b64
            }
            
            url = f"{REST_BASE_URL}{path}?series_ticker=KXBTCD&limit=1"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if "error" in data:
                print(f"[{datetime.now(EST)}] ❌ API error getting events: {data['error']}")
                return None
            
            events = data.get("events", [])
            if events:
                return events[0].get("event_ticker")
            
            return None
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to get current Bitcoin event: {e}")
            return None
    
    def get_fallback_markets(self):
        """Get fallback markets for testing when Bitcoin markets aren't available"""
        fallback_markets = [
            "KXWTAMATCH-25JUL24PONVAL-VAL",  # Tennis match
            "KXAAPLPRICE17OVER16-25-799.01",  # Apple price prediction
            "KXATPMATCH-25JUL24RINHAN-RIN"   # Another tennis match
        ]
        print(f"[{datetime.now(EST)}] 🎾 Using fallback markets: {fallback_markets}")
        return fallback_markets
    
    def fetch_event_data(self, event_ticker):
        """Fetch complete event data from REST API"""
        try:
            credentials = self.load_kalshi_credentials()
            if not credentials:
                return None
            
            # Generate signature for REST API call
            timestamp_ms = str(int(time.time() * 1000))
            method = "GET"
            path = f"/events/{event_ticker}"
            
            signature_text = timestamp_ms + method + path
            
            # Load private key and sign
            with open(credentials["KEY_PATH"], "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            
            signature = private_key.sign(
                signature_text.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            signature_b64 = base64.b64encode(signature).decode('utf-8')
            
            headers = {
                "Accept": "application/json",
                "KALSHI-ACCESS-KEY": credentials["KEY_ID"],
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
                "KALSHI-ACCESS-SIGNATURE": signature_b64
            }
            
            url = f"{REST_BASE_URL}{path}"
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if "error" in data:
                print(f"[{datetime.now(EST)}] ❌ API error for {event_ticker}: {data['error']}")
                return None
                
            return data
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to fetch event data for {event_ticker}: {e}")
            return None
    
    def extract_event_ticker(self, market_ticker):
        """Extract event ticker from market ticker"""
        # Handle different market ticker formats
        if "-T" in market_ticker:
            # Format: KXBTCD-25JUL2323-T108999.99 -> KXBTCD-25JUL2323
            return market_ticker.split("-T")[0]
        elif "-" in market_ticker:
            # Format: KXATPMATCH-25JUL24RINHAN-RIN -> KXATPMATCH-25JUL24RINHAN
            parts = market_ticker.split("-")
            if len(parts) >= 3:
                return "-".join(parts[:-1])
        return market_ticker
    
    def update_market_cache(self, market_data):
        """Update market cache with new market data"""
        market_ticker = market_data.get("market_ticker")
        if not market_ticker:
            return
        
        event_ticker = self.extract_event_ticker(market_ticker)
        
        if event_ticker not in self.market_cache:
            self.market_cache[event_ticker] = {
                "markets": {},
                "event_data": None,
                "last_update": datetime.now(EST),
                "last_snapshot": None
            }
        
        # Update market data
        self.market_cache[event_ticker]["markets"][market_ticker] = market_data
        self.market_cache[event_ticker]["last_update"] = datetime.now(EST)
        
        if self.debug:
            print(f"[{datetime.now(EST)}] 📊 Updated cache for {event_ticker}: {market_ticker}")
    
    def build_complete_snapshot(self, event_ticker):
        """Build complete market snapshot for an event"""
        if event_ticker not in self.market_cache:
            return None
        
        cache = self.market_cache[event_ticker]
        
        # Fetch event data if not cached
        if not cache["event_data"]:
            cache["event_data"] = self.fetch_event_data(event_ticker)
            if not cache["event_data"]:
                return None
        
        # Build complete snapshot
        snapshot = {
            "event": cache["event_data"].get("event", {}),
            "markets": []
        }
        
        # Get all markets for this event from REST API
        event_markets = cache["event_data"].get("markets", [])
        
        # Update market data with WebSocket updates
        for market in event_markets:
            market_ticker = market.get("ticker")
            if market_ticker in cache["markets"]:
                ws_data = cache["markets"][market_ticker]
                patch = {"ts": ws_data.get("ts", int(time.time()))}
                yb = ws_data.get("yes_bid")
                if yb is not None:
                    patch["yes_bid_dollars"] = _cents_to_dollar_text(int(yb))
                ya = ws_data.get("yes_ask")
                if ya is not None:
                    patch["yes_ask_dollars"] = _cents_to_dollar_text(int(ya))
                price = ws_data.get("price")
                if price is not None:
                    patch["last_price_dollars"] = _cents_to_dollar_text(int(price))
                vol_d = ws_data.get("volume_delta")
                if vol_d is not None:
                    patch["volume_fp"] = str(int(vol_d))
                market.update(patch)
            
            snapshot["markets"].append(market)
        
        # Add title at root level for frontend compatibility
        if "event" in snapshot and "title" in snapshot["event"]:
            snapshot["title"] = snapshot["event"]["title"]
        
        return snapshot
    
    def init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS websocket_market_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                market_ticker TEXT NOT NULL,
                price INTEGER,
                y_bid_cents INTEGER,
                y_ask_cents INTEGER,
                volume_delta INTEGER,
                open_interest_delta INTEGER,
                dollar_volume_delta INTEGER,
                dollar_open_interest_delta INTEGER,
                ts INTEGER
            )
        """)
        conn.commit()
        conn.close()
        print(f"[{datetime.now(EST)}] ✅ WebSocket database initialized at {DB_PATH}")
    
    def save_market_data(self, market_data):
        """Save market data to database"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        timestamp = datetime.now(EST).isoformat()
        
        try:
            c.execute("""
                INSERT INTO websocket_market_data (
                    timestamp, market_ticker, price, y_bid_cents, y_ask_cents,
                    volume_delta, open_interest_delta, dollar_volume_delta,
                    dollar_open_interest_delta, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                market_data.get("market_ticker"),
                market_data.get("price"),
                market_data.get("yes_bid"),
                market_data.get("yes_ask"),
                market_data.get("volume_delta"),
                market_data.get("open_interest_delta"),
                market_data.get("dollar_volume_delta"),
                market_data.get("dollar_open_interest_delta"),
                market_data.get("ts")
            ))
            conn.commit()
            if self.debug:
                print(f"[{datetime.now(EST)}] ✅ Saved market data for {market_data.get('market_ticker')}")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to save market data: {e}")
        finally:
            conn.close()
    
    def save_json_snapshot(self, data):
        """Save JSON snapshot"""
        try:
            # If this is a ticker_v2 message, update cache and build complete snapshot
            if data.get("type") == "ticker_v2":
                market_data = data.get("msg", {})
                if market_data:
                    self.update_market_cache(market_data)
                    
                    # Build complete snapshot for the event
                    market_ticker = market_data.get("market_ticker")
                    if market_ticker:
                        event_ticker = self.extract_event_ticker(market_ticker)
                        complete_snapshot = self.build_complete_snapshot(event_ticker)
                        
                        if complete_snapshot:
                            with open(JSON_SNAPSHOT_PATH, "w") as f:
                                json.dump(complete_snapshot, f, indent=2)
                            
                            if self.debug:
                                print(f"[{datetime.now(EST)}] ✅ Complete snapshot saved for {event_ticker} with {len(complete_snapshot.get('markets', []))} markets")
                        else:
                            # Fallback: save individual ticker data if complete snapshot fails
                            with open(JSON_SNAPSHOT_PATH, "w") as f:
                                json.dump(data, f, indent=2)
                            if self.debug:
                                print(f"[{datetime.now(EST)}] ⚠️ Saved individual ticker data (complete snapshot failed)")
            else:
                # For non-ticker messages, save as-is
                with open(JSON_SNAPSHOT_PATH, "w") as f:
                    json.dump(data, f, indent=2)
                    
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to save JSON snapshot: {e}")
    
    def write_heartbeat(self):
        """Write heartbeat file"""
        try:
            with open(HEARTBEAT_PATH, "w") as f:
                f.write(f"{datetime.now(EST).isoformat()} WebSocket watchdog alive\n")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to write heartbeat: {e}")
    
    async def connect(self):
        """Connect to Kalshi WebSocket API"""
        try:
            # Load credentials
            credentials = self.load_kalshi_credentials()
            if not credentials:
                print(f"[{datetime.now(EST)}] ❌ No credentials available")
                return False
            
            # Generate signature using the same method as REST API
            timestamp_ms = str(int(time.time() * 1000))
            signature_text = timestamp_ms + "GET" + "/trade-api/ws/v2"
            
            # Load private key and sign
            with open(credentials["KEY_PATH"], "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            
            # Sign the signature text
            signature = private_key.sign(
                signature_text.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Base64 encode the signature
            signature_b64 = base64.b64encode(signature).decode('utf-8')
            
            # Use the correct Kalshi header names
            headers = {
                "KALSHI-ACCESS-KEY": credentials["KEY_ID"],
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
                "KALSHI-ACCESS-SIGNATURE": signature_b64
            }
            
            print(f"[{datetime.now(EST)}] 🔐 Attempting WebSocket connection with proper Kalshi authentication...")
            
            # Connect with authentication headers
            self.websocket = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=10
            )
            
            print(f"[{datetime.now(EST)}] ✅ Connected to Kalshi WebSocket API")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to connect to WebSocket: {e}")
            return False
    
    async def subscribe_to_ticker_v2(self, markets):
        """Subscribe to ticker_v2 channel"""
        if not self.websocket:
            return False
        
        try:
            # Use correct subscription format from Kalshi documentation
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["ticker_v2"],
                    "market_tickers": markets
                }
            }
            
            await self.websocket.send(json.dumps(subscription_message))
            print(f"[{datetime.now(EST)}] 📡 Sent subscription: {json.dumps(subscription_message)}")
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            if response_data.get("type") == "subscribed":
                self.subscription_id = response_data.get("msg", {}).get("sid")
                print(f"[{datetime.now(EST)}] ✅ Subscribed to ticker_v2 with SID: {self.subscription_id}")
                return True
            else:
                print(f"[{datetime.now(EST)}] ❌ Subscription failed: {response_data}")
                return False
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to subscribe: {e}")
            return False
    
    async def handle_message(self, message):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)
            
            if self.debug:
                print(f"[{datetime.now(EST)}] 📨 Received: {message[:200]}...")
            
            if data.get("type") == "ticker_v2":
                market_data = data.get("msg", {})
                if market_data:
                    self.save_market_data(market_data)
                    self.save_json_snapshot(data)
                    self.write_heartbeat()
                    
                    market_ticker = market_data.get("market_ticker")
                    event_ticker = self.extract_event_ticker(market_ticker) if market_ticker else "unknown"
                    
                    print(f"[{datetime.now(EST)}] 📊 Market update: {market_ticker} - Price: {market_data.get('price')} - Event: {event_ticker}")
                else:
                    print(f"[{datetime.now(EST)}] ⚠️ No market data in ticker_v2 message")
                    
            elif data.get("type") == "error":
                print(f"[{datetime.now(EST)}] ❌ WebSocket error: {data.get('msg', {}).get('msg')}")
                
            elif data.get("type") == "subscribed":
                print(f"[{datetime.now(EST)}] ✅ Subscription confirmed: {data}")
                
            else:
                if self.debug:
                    print(f"[{datetime.now(EST)}] ℹ️ Unknown message type: {data.get('type')}")
                    
        except json.JSONDecodeError as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to parse message: {e}")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error handling message: {e}")
    
    async def run(self):
        """Main WebSocket watchdog loop"""
        print(f"[{datetime.now(EST)}] 🔌 Starting Kalshi WebSocket Watchdog...")
        
        retry_count = 0
        websocket_success = False
        
        while retry_count < self.max_retries:
            try:
                # Connect to WebSocket
                if not await self.connect():
                    retry_count += 1
                    print(f"[{datetime.now(EST)}] 🔄 Retry {retry_count}/{self.max_retries}")
                    await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                    continue
                
                # Get markets to subscribe to
                markets = self.get_current_bitcoin_markets()
                
                # Subscribe to ticker_v2 channel
                if not await self.subscribe_to_ticker_v2(markets):
                    retry_count += 1
                    print(f"[{datetime.now(EST)}] 🔄 Retry {retry_count}/{self.max_retries}")
                    await asyncio.sleep(2 ** retry_count)
                    continue
                
                websocket_success = True
                print(f"[{datetime.now(EST)}] 🎧 Listening for WebSocket messages...")
                
                # Listen for messages
                async for message in self.websocket:
                    await self.handle_message(message)
                    self.write_heartbeat()
                    
            except websockets.exceptions.ConnectionClosed:
                print(f"[{datetime.now(EST)}] 🔌 WebSocket connection closed")
                retry_count += 1
                await asyncio.sleep(2 ** retry_count)
                
            except Exception as e:
                print(f"[{datetime.now(EST)}] ❌ WebSocket error: {e}")
                retry_count += 1
                await asyncio.sleep(2 ** retry_count)
        
        # Fallback to HTTP if WebSocket fails
        if not websocket_success and self.fallback_to_http:
            print(f"[{datetime.now(EST)}] 🔄 Switching to HTTP polling mode...")
            # Don't call http_main() here as it would create a recursive loop
            # Instead, just exit and let the user restart in HTTP mode
            print(f"[{datetime.now(EST)}] 💡 To use HTTP mode, run: ./scripts/disable_websocket.sh && python kalshi_api_watchdog.py")
            return
        else:
            print(f"[{datetime.now(EST)}] ❌ WebSocket failed after {self.max_retries} retries")

async def main():
    """Main entry point"""
    watchdog = KalshiWebSocketWatchdog()
    await watchdog.run()

if __name__ == "__main__":
    asyncio.run(main()) 