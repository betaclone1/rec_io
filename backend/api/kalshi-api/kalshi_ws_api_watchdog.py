#!/usr/bin/env python3
"""
Kalshi WebSocket API Watchdog
Real-time orderbook monitoring using WebSocket connections
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from backend.util.paths import get_project_root, get_kalshi_credentials_dir
from backend.core.config.settings import config
import requests
import json
import asyncio
import websockets
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import time
from pathlib import Path
from dotenv import dotenv_values
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import psycopg2
from psycopg2.extras import RealDictCursor

from backend.core.time_eastern import merge_psycopg2_connect_kwargs

# Configuration
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
EST = ZoneInfo("America/New_York")

def get_base_url():
    return "https://api.elections.kalshi.com/trade-api/v2"


print(f"Using base URL: {get_base_url()} (prod)")

def load_kalshi_credentials():
    """Load Kalshi API credentials"""
    cred_dir = Path(get_kalshi_credentials_dir()) / "prod"

    if not cred_dir.exists():
        print(f"❌ No prod credentials found at {cred_dir}")
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

def get_current_event_ticker():
    """Get current Bitcoin event ticker using time-based prediction"""
    now = datetime.now(EST)
    
    # Try current hour + 1
    test_time = now + timedelta(hours=1)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    current_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"
    
    # Verify this ticker exists via REST API
    data = fetch_event_json(current_ticker)
    if data and "markets" in data:
        return current_ticker, data
    
    # Try next hour
    test_time = now + timedelta(hours=2)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    next_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"
    
    data = fetch_event_json(next_ticker)
    if data and "markets" in data:
        return next_ticker, data
    
    return None, None

def fetch_event_json(event_ticker):
    """Fetch event data from REST API"""
    url = f"{get_base_url()}/events/{event_ticker}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            print(f"[{datetime.now()}] ❌ API returned error for ticker {event_ticker}: {data['error']}")
            return None
        return data
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Exception fetching event JSON: {e}")
        return None

class KalshiOrderbookWatchdog:
    def __init__(self):
        self.websocket = None
        self.subscription_id = None
        self.command_id = 1
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.current_markets = []
        self.db_connection = None
        self.orderbook_state = {}  # Track current orderbook state per market
        
    def connect_database(self):
        """Connect to PostgreSQL database"""
        try:
            self.db_connection = psycopg2.connect(
                **merge_psycopg2_connect_kwargs(
                    {
                        "host": "localhost",
                        "database": "rec_io_db",
                        "user": "rec_io_user",
                        "password": "rec_io_password",
                    }
                )
            )
            print(f"[{datetime.now(EST)}] ✅ Connected to PostgreSQL database")
            return True
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to connect to database: {e}")
            return False
    
    def clear_previous_data(self):
        """Clear previous orderbook data to start fresh"""
        if not self.db_connection:
            return False
        
        try:
            with self.db_connection.cursor() as cursor:
                # Clear all previous data
                cursor.execute("DELETE FROM testing.kalshi_orderbook_snapshot")
                cursor.execute("DELETE FROM testing.kalshi_orderbook_deltas")
                cursor.execute("DELETE FROM testing.kalshi_level2_orderbook")
                self.db_connection.commit()
            
            print(f"[{datetime.now(EST)}] 🧹 Cleared all previous orderbook data - starting fresh")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error clearing previous data: {e}")
            try:
                self.db_connection.rollback()
            except:
                pass
            return False
    
    def extract_strike_price(self, market_ticker):
        """Extract strike price from market ticker and format it"""
        try:
            # Extract the strike price from ticker like "KXBTCD-25AUG0316-T114249.99"
            if "-T" in market_ticker:
                strike_part = market_ticker.split("-T")[1]
                # Convert to integer (remove .99 or similar)
                strike_int = int(float(strike_part))
                # Format as currency string
                return f"${strike_int:,}"
            return "Unknown"
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error extracting strike price: {e}")
            return "Unknown"
    
    def save_orderbook_snapshot(self, market_ticker, orderbook_data, sequence_number):
        """Save complete orderbook snapshot to PostgreSQL database"""
        if not self.db_connection:
            return False
        
        try:
            # Check if connection is in a bad state and reconnect if needed
            try:
                self.db_connection.rollback()
            except:
                # If rollback fails, reconnect
                self.connect_database()
                if not self.db_connection:
                    return False
            
            with self.db_connection.cursor() as cursor:
                # Clear existing snapshot for this market
                cursor.execute(
                    "DELETE FROM testing.kalshi_orderbook_snapshot WHERE market_ticker = %s",
                    (market_ticker,)
                )
                
                # Insert new snapshot data
                for side in ['yes', 'no']:
                    if side in orderbook_data:
                        for price_level in orderbook_data[side]:
                            price, size = price_level
                            cursor.execute("""
                                INSERT INTO testing.kalshi_orderbook_snapshot 
                                (market_ticker, side, price, size, sequence_number)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (market_ticker, side, price, size, sequence_number))
                
                self.db_connection.commit()
            
            print(f"[{datetime.now(EST)}] 📊 Saved orderbook snapshot for {market_ticker} (seq: {sequence_number})")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error saving orderbook snapshot: {e}")
            try:
                self.db_connection.rollback()
            except:
                pass
            return False
    
    def save_orderbook_delta(self, market_ticker, side, price, delta, sequence_number):
        """Save orderbook delta to PostgreSQL database"""
        if not self.db_connection:
            return False
        
        try:
            # Check if connection is in a bad state and reconnect if needed
            try:
                self.db_connection.rollback()
            except:
                # If rollback fails, reconnect
                self.connect_database()
                if not self.db_connection:
                    return False
            
            with self.db_connection.cursor() as cursor:
                # Insert delta record
                cursor.execute("""
                    INSERT INTO testing.kalshi_orderbook_deltas 
                    (market_ticker, side, price, delta, sequence_number)
                    VALUES (%s, %s, %s, %s, %s)
                """, (market_ticker, side, price, delta, sequence_number))
                
                # Update snapshot table
                if delta > 0:
                    # Add or update size
                    cursor.execute("""
                        INSERT INTO testing.kalshi_orderbook_snapshot 
                        (market_ticker, side, price, size, sequence_number)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (market_ticker, side, price)
                        DO UPDATE SET 
                            size = testing.kalshi_orderbook_snapshot.size + %s,
                            sequence_number = %s
                    """, (market_ticker, side, price, delta, sequence_number, delta, sequence_number))
                else:
                    # Remove or reduce size
                    cursor.execute("""
                        UPDATE testing.kalshi_orderbook_snapshot 
                        SET size = size + %s, sequence_number = %s
                        WHERE market_ticker = %s AND side = %s AND price = %s
                    """, (delta, sequence_number, market_ticker, side, price))
                    
                    # Remove if size becomes 0 or negative
                    cursor.execute("""
                        DELETE FROM testing.kalshi_orderbook_snapshot 
                        WHERE market_ticker = %s AND side = %s AND price = %s AND size <= 0
                    """, (market_ticker, side, price))
                
                self.db_connection.commit()
            
            print(f"[{datetime.now(EST)}] 📈 Delta: {market_ticker} {side} {price} {delta:+d} (seq: {sequence_number})")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error saving orderbook delta: {e}")
            try:
                self.db_connection.rollback()
            except:
                pass
            return False
    
    def display_orderbook_state(self, market_ticker):
        """Display current orderbook state from database"""
        if not self.db_connection:
            return
        
        try:
            with self.db_connection.cursor() as cursor:
                # Get current orderbook state
                cursor.execute("""
                    SELECT side, price, size 
                    FROM testing.kalshi_orderbook_snapshot 
                    WHERE market_ticker = %s 
                    ORDER BY side, price DESC
                """, (market_ticker,))
                
                rows = cursor.fetchall()
                
                if rows:
                    print(f"\n[{datetime.now(EST)}] 📊 LIVE ORDERBOOK: {market_ticker}")
                    print("=" * 60)
                    
                    # Separate YES and NO sides
                    yes_orders = [(price, size) for side, price, size in rows if side == 'yes']
                    no_orders = [(price, size) for side, price, size in rows if side == 'no']
                    
                    # Display YES side (descending price)
                    print("YES (Price >= Strike):")
                    for price, size in yes_orders[:10]:  # Top 10 levels
                        print(f"  {price:3d} | {size:6d} shares")
                    
                    print("-" * 30)
                    
                    # Display NO side (ascending price)
                    print("NO (Price < Strike):")
                    for price, size in reversed(no_orders[-10:]):  # Top 10 levels
                        print(f"  {price:3d} | {size:6d} shares")
                    
                    print("=" * 60)
                else:
                    print(f"[{datetime.now(EST)}] ⚠️ No orderbook data found for {market_ticker}")
                    
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error displaying orderbook: {e}")
    
    def save_level2_orderbook(self, market_ticker, sequence_number):
        """Save Level 2 orderbook data as individual price level rows"""
        if not self.db_connection:
            return False
        
        try:
            with self.db_connection.cursor() as cursor:
                # Get current orderbook state
                cursor.execute("""
                    SELECT side, price, size 
                    FROM testing.kalshi_orderbook_snapshot 
                    WHERE market_ticker = %s 
                    ORDER BY side, price DESC
                """, (market_ticker,))
                
                rows = cursor.fetchall()
                
                if not rows:
                    return False
                
                # Extract strike price from market ticker
                try:
                    strike_price = float(market_ticker.split("-T")[1])
                except:
                    strike_price = 0
                
                # Separate YES and NO sides
                yes_orders = [(price, size) for side, price, size in rows if side == 'yes']
                no_orders = [(price, size) for side, price, size in rows if side == 'no']
                
                # Sort orders properly
                yes_orders.sort(key=lambda x: x[0], reverse=True)  # Highest price first (best ask)
                no_orders.sort(key=lambda x: x[0], reverse=True)   # Highest price first (best bid)
                
                # Calculate totals
                total_bid_volume = sum(size for _, size in no_orders)
                total_ask_volume = sum(size for _, size in yes_orders)
                
                # Calculate best bid/ask and spread
                best_bid_price = no_orders[0][0] if no_orders else None
                best_ask_price = yes_orders[0][0] if yes_orders else None
                spread = (best_ask_price - best_bid_price) if (best_bid_price and best_ask_price) else None
                mid_price = ((best_bid_price + best_ask_price) / 2) if (best_bid_price and best_ask_price) else None
                
                # Clear existing Level 2 data for this market
                cursor.execute("DELETE FROM testing.kalshi_level2_orderbook WHERE market_ticker = %s", (market_ticker,))
                
                # Insert NO side (bids) - up to top 10 levels
                for rank, (price, size) in enumerate(no_orders[:10], 1):
                    is_best_bid = (rank == 1)
                    cursor.execute("""
                        INSERT INTO testing.kalshi_level2_orderbook 
                        (market_ticker, strike_price, side, price, size, level_rank, is_best_bid, is_best_ask,
                         spread, mid_price, total_bid_volume, total_ask_volume, sequence_number)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (market_ticker, strike_price, 'no', price, size, rank, is_best_bid, False,
                          spread, mid_price, total_bid_volume, total_ask_volume, sequence_number))
                
                # Insert YES side (asks) - up to top 10 levels
                for rank, (price, size) in enumerate(yes_orders[:10], 1):
                    is_best_ask = (rank == 1)
                    cursor.execute("""
                        INSERT INTO testing.kalshi_level2_orderbook 
                        (market_ticker, strike_price, side, price, size, level_rank, is_best_bid, is_best_ask,
                         spread, mid_price, total_bid_volume, total_ask_volume, sequence_number)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (market_ticker, strike_price, 'yes', price, size, rank, False, is_best_ask,
                          spread, mid_price, total_bid_volume, total_ask_volume, sequence_number))
                
                self.db_connection.commit()
            
            # Display Level 2 orderbook
            self.display_level2_orderbook(market_ticker)
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error saving Level 2 orderbook: {e}")
            try:
                self.db_connection.rollback()
            except:
                pass
            return False
    
    def display_level2_orderbook(self, market_ticker):
        """Display Level 2 orderbook from database"""
        if not self.db_connection:
            return
        
        try:
            with self.db_connection.cursor() as cursor:
                # Get Level 2 orderbook data
                cursor.execute("""
                    SELECT side, price, size, level_rank, is_best_bid, is_best_ask, spread, mid_price,
                           total_bid_volume, total_ask_volume, strike_price
                    FROM testing.kalshi_level2_orderbook 
                    WHERE market_ticker = %s 
                    ORDER BY side, level_rank
                """, (market_ticker,))
                
                rows = cursor.fetchall()
                
                if not rows:
                    print(f"[{datetime.now(EST)}] ⚠️ No Level 2 orderbook data found for {market_ticker}")
                    return
                
                # Get first row for summary data
                first_row = rows[0]
                strike_price = first_row[10]
                spread = first_row[6]
                mid_price = first_row[7]
                total_bid_volume = first_row[8]
                total_ask_volume = first_row[9]
                
                print(f"\n[{datetime.now(EST)}] 📊 LEVEL 2 ORDERBOOK: {market_ticker}")
                print(f"Strike: ${strike_price:,.2f}")
                
                if spread is not None and mid_price is not None:
                    print(f"Spread: {spread:2d} | Mid: {mid_price:5.2f}")
                
                print("=" * 60)
                
                # Display BID levels (NO side)
                print("BID LEVELS (NO - Price < Strike):")
                bid_rows = [row for row in rows if row[0] == 'no']
                for row in bid_rows[:5]:  # Top 5 levels
                    side, price, size, rank, is_best_bid, is_best_ask, _, _, _, _, _ = row
                    marker = "★" if is_best_bid else " "
                    print(f"  {marker} {rank}. {price:3d} | {size:6d} shares")
                
                print("-" * 30)
                
                # Display ASK levels (YES side)
                print("ASK LEVELS (YES - Price >= Strike):")
                ask_rows = [row for row in rows if row[0] == 'yes']
                for row in ask_rows[:5]:  # Top 5 levels
                    side, price, size, rank, is_best_bid, is_best_ask, _, _, _, _, _ = row
                    marker = "★" if is_best_ask else " "
                    print(f"  {marker} {rank}. {price:3d} | {size:6d} shares")
                
                print(f"Total Bid Volume: {total_bid_volume:,} | Total Ask Volume: {total_ask_volume:,}")
                print("=" * 60)
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error displaying Level 2 orderbook: {e}")
    
    async def connect_websocket(self):
        """Connect to Kalshi WebSocket API"""
        try:
            # Load credentials
            credentials = load_kalshi_credentials()
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
            
            print(f"[{datetime.now(EST)}] 🔐 Attempting Market Ticker WebSocket connection...")
            print(f"[{datetime.now(EST)}] 📊 Kalshi: prod")
            print(f"[{datetime.now(EST)}] 🔑 Using API Key: {credentials['KEY_ID'][:8]}...")
            
            # Connect with authentication headers
            self.websocket = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=10
            )
            
            print(f"[{datetime.now(EST)}] ✅ Connected to Kalshi Market Ticker WebSocket API")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ WebSocket connection failed: {e}")
            return False
    
    def get_current_bitcoin_price(self):
        """Get current Bitcoin price from a reliable source"""
        try:
            # Use CoinGecko API to get current BTC price
            response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10)
            response.raise_for_status()
            data = response.json()
            btc_price = data.get("bitcoin", {}).get("usd", 0)
            print(f"[{datetime.now(EST)}] 💰 Current Bitcoin price: ${btc_price:,.2f}")
            return btc_price
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to get Bitcoin price: {e}")
            return 118000  # Fallback price
    
    def find_nearest_strike_market(self, btc_price):
        """Find the market with strike price closest to current BTC price"""
        current_ticker, data = get_current_event_ticker()
        if not current_ticker or not data:
            print(f"[{datetime.now(EST)}] ❌ No current Bitcoin markets found")
            return None
        
        markets = data.get("markets", [])
        nearest_market = None
        min_distance = float('inf')
        
        for market in markets:
            ticker = market.get("ticker")
            if ticker and "KXBTC" in ticker and "-T" in ticker:
                # Extract strike price from ticker like "KXBTCD-25SEP1415-T115499.99"
                try:
                    strike_part = ticker.split("-T")[1]
                    strike_price = float(strike_part)
                    distance = abs(strike_price - btc_price)
                    
                    if distance < min_distance:
                        min_distance = distance
                        nearest_market = ticker
                        
                except (ValueError, IndexError) as e:
                    print(f"[{datetime.now(EST)}] ⚠️ Could not parse strike from {ticker}: {e}")
                    continue
        
        if nearest_market:
            strike_price = float(nearest_market.split("-T")[1])
            print(f"[{datetime.now(EST)}] 🎯 Nearest strike: {nearest_market} (${strike_price:,.2f}, distance: ${min_distance:,.2f})")
        
        return nearest_market
    
    def get_current_markets(self):
        """Get the single nearest-to-money Bitcoin market to subscribe to"""
        btc_price = self.get_current_bitcoin_price()
        nearest_market = self.find_nearest_strike_market(btc_price)
        
        if nearest_market:
            print(f"[{datetime.now(EST)}] 📊 Subscribing to nearest-to-money market: {nearest_market}")
            return [nearest_market]
        else:
            print(f"[{datetime.now(EST)}] ❌ No suitable Bitcoin market found")
            return []
    
    async def subscribe_to_orderbook_updates(self, market_tickers):
        """Subscribe to orderbook delta channel for specific markets"""
        if not self.websocket:
            return False
        
        try:
            # Use correct subscription format from Kalshi documentation
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": market_tickers
                }
            }
            
            await self.websocket.send(json.dumps(subscription_message))
            print(f"[{datetime.now(EST)}] 📡 Sent orderbook subscription: {json.dumps(subscription_message)}")
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            if response_data.get("type") == "subscribed":
                self.subscription_id = response_data.get("msg", {}).get("sid")
                print(f"[{datetime.now(EST)}] ✅ Subscribed to orderbook updates with SID: {self.subscription_id}")
                return True
            else:
                print(f"[{datetime.now(EST)}] ❌ Orderbook subscription failed: {response_data}")
                return False
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to subscribe to orderbook updates: {e}")
            return False
    
    async def handle_orderbook_message(self, message):
        """Handle incoming orderbook messages"""
        try:
            data = json.loads(message)
            
            if data.get("type") == "orderbook_snapshot":
                # Handle initial orderbook snapshot
                snapshot_data = data.get("msg", {})
                market_ticker = snapshot_data.get('market_ticker', '')
                sequence_number = data.get('seq', 0)
                
                # Only process KXBTC entries
                if "KXBTC" in market_ticker:
                    print(f"\n[{datetime.now(EST)}] 📊 ORDERBOOK SNAPSHOT!")
                    print(f"   Market Ticker: {market_ticker}")
                    print(f"   Sequence: {sequence_number}")
                    
                    # Extract orderbook data
                    orderbook_data = {}
                    for side in ['yes', 'no']:
                        if side in snapshot_data:
                            orderbook_data[side] = snapshot_data[side]
                            print(f"   {side.upper()}: {len(snapshot_data[side])} levels")
                    
                    print("=" * 50)
                    
                    # Save snapshot to database
                    if self.save_orderbook_snapshot(market_ticker, orderbook_data, sequence_number):
                        # Save and display Level 2 orderbook
                        self.save_level2_orderbook(market_ticker, sequence_number)
                else:
                    print(f"[{datetime.now(EST)}] ⚠️ Non-KXBTC orderbook snapshot ignored: {market_ticker}")
                    
            elif data.get("type") == "orderbook_delta":
                # Handle orderbook delta updates
                delta_data = data.get("msg", {})
                market_ticker = delta_data.get('market_ticker', '')
                side = delta_data.get('side', '')
                price = delta_data.get('price', 0)
                delta = delta_data.get('delta', 0)
                sequence_number = data.get('seq', 0)
                
                # Only process KXBTC entries
                if "KXBTC" in market_ticker:
                    print(f"[{datetime.now(EST)}] 📈 ORDERBOOK DELTA: {market_ticker} {side} {price} {delta:+d} (seq: {sequence_number})")
                    
                    # Save delta to database
                    if self.save_orderbook_delta(market_ticker, side, price, delta, sequence_number):
                        # Save and display Level 2 orderbook
                        self.save_level2_orderbook(market_ticker, sequence_number)
                else:
                    print(f"[{datetime.now(EST)}] ⚠️ Non-KXBTC orderbook delta ignored: {market_ticker}")
                
            elif data.get("type") == "subscribed":
                print(f"[{datetime.now(EST)}] ✅ Subscription confirmed: {data}")
                
            elif data.get("type") == "error":
                print(f"[{datetime.now(EST)}] ❌ WebSocket error: {data}")
                
            else:
                print(f"[{datetime.now(EST)}] 📨 Other message: {data}")
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error handling message: {e}")
            print(f"Raw message: {message}")
    
    async def run_websocket(self):
        """Main WebSocket connection and message handling loop"""
        while True:
            try:
                # Connect to database
                if not self.connect_database():
                    print(f"[{datetime.now(EST)}] ❌ Failed to connect to database, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue
                
                # Clear previous data to start fresh
                self.clear_previous_data()
                
                # Connect to WebSocket
                if not await self.connect_websocket():
                    print(f"[{datetime.now(EST)}] ❌ Failed to connect, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue
                
                # Get current markets
                market_tickers = self.get_current_markets()
                if not market_tickers:
                    print(f"[{datetime.now(EST)}] ❌ No markets found, retrying in 30 seconds...")
                    await asyncio.sleep(30)
                    continue
                
                # Subscribe to orderbook updates
                if not await self.subscribe_to_orderbook_updates(market_tickers):
                    print(f"[{datetime.now(EST)}] ❌ Failed to subscribe, retrying...")
                    continue
                
                print(f"[{datetime.now(EST)}] 🎧 Listening for orderbook updates...")
                print(f"[{datetime.now(EST)}] 💡 Real-time orderbook data will be written to PostgreSQL!")
                
                # Listen for messages
                async for message in self.websocket:
                    await self.handle_orderbook_message(message)
                    
            except Exception as e:
                if "ConnectionClosed" in str(e) or "connection closed" in str(e).lower():
                    print(f"[{datetime.now(EST)}] ❌ WebSocket connection closed")
                    self.reconnect_attempts += 1
                    
                    if self.reconnect_attempts >= self.max_reconnect_attempts:
                        print(f"[{datetime.now(EST)}] ❌ Max reconnection attempts reached, exiting...")
                        break
                    
                    print(f"[{datetime.now(EST)}] 🔄 Attempting to reconnect in 5 seconds... (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
                    await asyncio.sleep(5)
                else:
                    print(f"[{datetime.now(EST)}] ❌ Unexpected error: {e}")
                    await asyncio.sleep(5)

def main():
    print("🔌 Kalshi Orderbook WebSocket Watchdog Starting...")
    
    # Create and run WebSocket watchdog
    watchdog = KalshiOrderbookWatchdog()
    
    try:
        # Run the WebSocket watchdog
        asyncio.run(watchdog.run_websocket())
    except KeyboardInterrupt:
        print("🛑 Orderbook watchdog stopped by user")
    except Exception as e:
        print(f"❌ Error in orderbook watchdog: {e}")

if __name__ == "__main__":
    main() 