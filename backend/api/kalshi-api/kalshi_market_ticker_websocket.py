#!/usr/bin/env python3
"""
Kalshi Market Ticker WebSocket (testing): orderbook → `testing.market_kalshi_btc_websocket`
with dollar-quote TEXT columns and `volume_fp` / `open_interest_fp` only (no cent integer fields).
"""

import asyncio
import json
import time
import websockets
import psycopg2
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import requests
import os
import sys

# Add the backend directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from backend.util.paths import get_project_root, get_kalshi_credentials_dir, get_logs_dir
from backend.core.config.settings import config
from pathlib import Path
from dotenv import dotenv_values

# Timezone
EST = timezone(timedelta(hours=-5))


def _cents_to_dollar_text(cents):
    if cents is None:
        return None
    try:
        x = float(cents) / 100.0
    except (TypeError, ValueError):
        return None
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _contracts_fp_text(n):
    if n is None:
        return None
    try:
        return str(int(n))
    except (TypeError, ValueError):
        try:
            return str(int(float(n)))
        except (TypeError, ValueError):
            return None


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

class KalshiMarketTickerWebSocket:
    def __init__(self):
        self.websocket = None
        self.db_connection = None
        self.command_id = 1
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.orderbook_state = {}  # Maintain orderbook state for each market
        
    def connect_database(self):
        """Connect to PostgreSQL database"""
        try:
            from backend.core.config.database import get_postgresql_connection
            self.db_connection = get_postgresql_connection()
            if not self.db_connection:
                return False
            print(f"[{datetime.now(EST)}] ✅ Connected to PostgreSQL database")
            return True
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Database connection failed: {e}")
            return False
    
    def clear_previous_data(self):
        """Clear previous data from the testing table on startup"""
        try:
            with self.db_connection.cursor() as cursor:
                cursor.execute("DELETE FROM testing.market_kalshi_btc_websocket")
                self.db_connection.commit()
                print(f"[{datetime.now(EST)}] 🗑️ Cleared previous data from testing.market_kalshi_btc_websocket")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error clearing previous data: {e}")
            raise
    
    def get_current_bitcoin_price(self):
        """Get current Bitcoin price from CoinGecko"""
        try:
            response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data["bitcoin"]["usd"]
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error fetching Bitcoin price: {e}")
        return None
    
    def get_current_event_ticker(self):
        """Get current Bitcoin event ticker using time-based prediction"""
        now = datetime.now(EST)
        
        # Try current hour + 2 (for markets that are offset)
        test_time = now + timedelta(hours=2)
        year_str = test_time.strftime("%y")
        month_str = test_time.strftime("%b").upper()
        day_str = test_time.strftime("%d")
        hour_str = test_time.strftime("%H")
        current_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"
        
        # Verify this ticker exists via REST API
        data = self.fetch_event_json(current_ticker)
        if data and "markets" in data:
            return current_ticker, data
        
        # Try current hour + 1 (fallback to standard logic)
        test_time = now + timedelta(hours=1)
        year_str = test_time.strftime("%y")
        month_str = test_time.strftime("%b").upper()
        day_str = test_time.strftime("%d")
        hour_str = test_time.strftime("%H")
        next_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"
        
        data = self.fetch_event_json(next_ticker)
        if data and "markets" in data:
            return next_ticker, data
        
        return None, None

    def fetch_event_json(self, event_ticker):
        """Fetch event data from REST API"""
        try:
            response = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/events/{event_ticker}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "error" in data:
                    print(f"[{datetime.now(EST)}] ❌ API error for {event_ticker}: {data['error']}")
                    return None
                return data
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error fetching event {event_ticker}: {e}")
        return None

    def find_nearest_strike_market(self, btc_price):
        """Find the Bitcoin market ticker nearest to current Bitcoin price"""
        if not btc_price:
            return None
            
        try:
            # Get current event ticker and markets
            event_ticker, data = self.get_current_event_ticker()
            if not event_ticker or not data:
                print(f"[{datetime.now(EST)}] ❌ No current Bitcoin event found")
                return None
                
            markets = data.get("markets", [])
            
            if not markets:
                return None
            
            # Find market closest to current Bitcoin price
            closest_market = None
            min_diff = float('inf')
            
            for market in markets:
                try:
                    strike_str = market["ticker"].split("-T")[1]
                    strike_price = float(strike_str)
                    diff = abs(strike_price - btc_price)
                    
                    if diff < min_diff:
                        min_diff = diff
                        closest_market = market["ticker"]
                except:
                    continue
            
            return closest_market
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error finding nearest strike market: {e}")
        
        return None
    
    
    def get_current_markets(self):
        """Get current Bitcoin market tickers using proper event discovery"""
        event_ticker, data = self.get_current_event_ticker()
        if not event_ticker or not data:
            print(f"[{datetime.now(EST)}] ❌ No current Bitcoin event found")
            return []
        
        markets = data.get("markets", [])
        market_tickers = [market.get("ticker", "") for market in markets if market.get("ticker")]
        print(f"[{datetime.now(EST)}] 📊 Found {len(market_tickers)} markets in current event: {event_ticker}")
        return market_tickers
    
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
            
            signature = private_key.sign(
                signature_text.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Convert signature to base64
            import base64
            signature_b64 = base64.b64encode(signature).decode('utf-8')
            
            # WebSocket headers
            headers = {
                "KALSHI-ACCESS-KEY": credentials["KEY_ID"],
                "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
                "KALSHI-ACCESS-SIGNATURE": signature_b64
            }
            
            # Connect to WebSocket
            uri = "wss://api.elections.kalshi.com/trade-api/ws/v2"
            self.websocket = await websockets.connect(
                uri, 
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=10
            )
            
            print(f"[{datetime.now(EST)}] ✅ Connected to Kalshi WebSocket")
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ WebSocket connection failed: {e}")
            return False
    
    async def subscribe_to_market_tickers(self, market_tickers):
        """Subscribe to orderbook delta channel for specific markets"""
        if not self.websocket:
            return False
        
        try:
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": market_tickers
                }
            }
            
            await self.websocket.send(json.dumps(subscription_message))
            self.command_id += 1
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10.0)
            response_data = json.loads(response)
            
            if response_data.get("type") == "subscribed":
                print(f"[{datetime.now(EST)}] ✅ Subscribed to market ticker updates for {len(market_tickers)} markets")
                return True
            else:
                print(f"[{datetime.now(EST)}] ❌ Subscription failed: {response_data}")
                return False
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error subscribing to market tickers: {e}")
            return False
    
    def calculate_market_data_from_orderbook(self, orderbook_data):
        """Best quotes and depth from internal orderbook (prices in cents); output dollars + fp text only."""
        try:
            yes_orders = orderbook_data.get("yes", [])
            no_orders = orderbook_data.get("no", [])

            best_yes_bid = max(yes_orders, key=lambda x: x[0])[0] if yes_orders else None
            best_no_bid = max(no_orders, key=lambda x: x[0])[0] if no_orders else None

            yes_ask_cents = None
            no_ask_cents = None
            if yes_orders:
                yc = [price for price, size in yes_orders if size > 0]
                yes_ask_cents = min(yc) if yc else None
            if no_orders:
                nc = [price for price, size in no_orders if size > 0]
                no_ask_cents = min(nc) if nc else None

            yes_volume_total = (
                sum(size for price, size in yes_orders if price < 99 and size > 0) if yes_orders else 0
            )
            no_volume_total = (
                sum(size for price, size in no_orders if price < 99 and size > 0) if no_orders else 0
            )

            total_yes_volume = sum(order[1] for order in yes_orders)
            total_no_volume = sum(order[1] for order in no_orders)
            total_volume = total_yes_volume + total_no_volume

            last_price_dollars = None
            if best_yes_bid is not None and best_no_bid is not None:
                yes_mid = (best_yes_bid + yes_ask_cents) / 2 if yes_ask_cents is not None else best_yes_bid
                no_mid = (best_no_bid + no_ask_cents) / 2 if no_ask_cents is not None else best_no_bid
                lp_cents = int((yes_mid + (100 - no_mid)) / 2)
                last_price_dollars = _cents_to_dollar_text(lp_cents)
            elif best_yes_bid is not None:
                last_price_dollars = _cents_to_dollar_text(best_yes_bid)
            elif best_no_bid is not None:
                last_price_dollars = _cents_to_dollar_text(100 - best_no_bid)

            return {
                "yes_bid_dollars": _cents_to_dollar_text(best_yes_bid),
                "yes_ask_dollars": _cents_to_dollar_text(yes_ask_cents),
                "no_bid_dollars": _cents_to_dollar_text(best_no_bid),
                "no_ask_dollars": _cents_to_dollar_text(no_ask_cents),
                "last_price_dollars": last_price_dollars,
                "volume_fp": _contracts_fp_text(total_volume),
                "open_interest_fp": _contracts_fp_text(total_volume),
                "yes_volume": yes_volume_total,
                "no_volume": no_volume_total,
            }

        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error calculating market data: {e}")
            return {
                "yes_bid_dollars": None,
                "yes_ask_dollars": None,
                "no_bid_dollars": None,
                "no_ask_dollars": None,
                "last_price_dollars": None,
                "volume_fp": None,
                "open_interest_fp": None,
                "yes_volume": None,
                "no_volume": None,
            }
    
    def update_market_ticker(self, market_ticker, orderbook_data):
        """Update market ticker data in PostgreSQL - populate all fields to match production table"""
        if not self.db_connection:
            return False
        
        try:
            # Calculate all market data from orderbook data
            market_data = self.calculate_market_data_from_orderbook(orderbook_data)
            
            # Extract event ticker and strike from market ticker
            # e.g., KXBTCD-25SEP1417-T115999.99 -> event_ticker=KXBTCD-25SEP1417, strike=115999.99
            parts = market_ticker.split("-")
            event_ticker = "-".join(parts[:-1])
            strike = parts[-1].replace("T", "") if len(parts) > 1 else None
            
            with self.db_connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO testing.market_kalshi_btc_websocket
                    (event_ticker, market_ticker, strike,
                     yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars,
                     last_price_dollars, volume_fp, open_interest_fp, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (event_ticker, market_ticker)
                    DO UPDATE SET
                        strike = EXCLUDED.strike,
                        yes_bid_dollars = EXCLUDED.yes_bid_dollars,
                        yes_ask_dollars = EXCLUDED.yes_ask_dollars,
                        no_bid_dollars = EXCLUDED.no_bid_dollars,
                        no_ask_dollars = EXCLUDED.no_ask_dollars,
                        last_price_dollars = EXCLUDED.last_price_dollars,
                        volume_fp = EXCLUDED.volume_fp,
                        open_interest_fp = EXCLUDED.open_interest_fp,
                        updated_at = NOW()
                """,
                    (
                        event_ticker,
                        market_ticker,
                        strike,
                        market_data["yes_bid_dollars"],
                        market_data["yes_ask_dollars"],
                        market_data["no_bid_dollars"],
                        market_data["no_ask_dollars"],
                        market_data["last_price_dollars"],
                        market_data["volume_fp"],
                        market_data["open_interest_fp"],
                    ),
                )

                self.db_connection.commit()

            print(
                f"[{datetime.now(EST)}] 📊 Updated {market_ticker}: "
                f"YA$={market_data['yes_ask_dollars']} NA$={market_data['no_ask_dollars']} "
                f"vol_fp={market_data['volume_fp']} oi_fp={market_data['open_interest_fp']}"
            )
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error updating market ticker: {e}")
            try:
                self.db_connection.rollback()
            except:
                pass
            return False
    
    def apply_orderbook_delta(self, market_ticker, side, price, delta):
        """Apply delta to orderbook state"""
        if market_ticker not in self.orderbook_state:
            self.orderbook_state[market_ticker] = {"yes": [], "no": []}
        
        orderbook = self.orderbook_state[market_ticker]
        
        # Find existing price level
        price_levels = orderbook[side]
        for i, (existing_price, existing_size) in enumerate(price_levels):
            if existing_price == price:
                new_size = existing_size + delta
                if new_size <= 0:
                    # Remove price level if size becomes 0 or negative
                    orderbook[side].pop(i)
                else:
                    # Update size
                    orderbook[side][i] = (price, new_size)
                return
        
        # If price level doesn't exist and delta is positive, add it
        if delta > 0:
            orderbook[side].append((price, delta))
            # Keep sorted by price (descending)
            orderbook[side].sort(key=lambda x: x[0], reverse=True)
    
    async def handle_orderbook_message(self, message):
        """Handle orderbook messages from WebSocket"""
        try:
            # DEBUG: Print raw message structure
            if message.get("type") == "orderbook_snapshot":
                print(f"\n🔍 RAW ORDERBOOK SNAPSHOT:")
                print(f"  Type: {message.get('type')}")
                msg_data = message.get("msg", {})
                print(f"  Market: {msg_data.get('market_ticker')}")
                print(f"  YES orders count: {len(msg_data.get('yes', []))}")
                print(f"  NO orders count: {len(msg_data.get('no', []))}")
                if msg_data.get('yes'):
                    print(f"  YES orders (first 3): {msg_data.get('yes', [])[:3]}")
                if msg_data.get('no'):
                    print(f"  NO orders (first 3): {msg_data.get('no', [])[:3]}")
                
                # Handle initial orderbook snapshot (Kalshi fixed-point: normalize price_dollars/size_fp to cents/int)
                market_ticker = msg_data.get("market_ticker")
                orderbook_data = msg_data
                def _norm_snapshot_levels(levels):
                    out = []
                    for item in levels or []:
                        p = item[0] if len(item) >= 1 else 0
                        s = item[1] if len(item) >= 2 else 0
                        p_cents = int(round(float(p) * 100)) if isinstance(p, str) else int(p)
                        s_int = int(float(s)) if isinstance(s, str) else int(s)
                        out.append((p_cents, s_int))
                    return out
                if market_ticker:
                    # Store the full orderbook state
                    self.orderbook_state[market_ticker] = {
                        "yes": _norm_snapshot_levels(orderbook_data.get("yes", [])),
                        "no": _norm_snapshot_levels(orderbook_data.get("no", []))
                    }
                    self.update_market_ticker(market_ticker, self.orderbook_state[market_ticker])
                    
            elif message.get("type") == "orderbook_delta":
                print(f"\n🔄 RAW ORDERBOOK DELTA:")
                print(f"  Type: {message.get('type')}")
                delta_data = message.get("msg", {})
                print(f"  Market: {delta_data.get('market_ticker')}")
                print(f"  Side: {delta_data.get('side')}")
                print(f"  Price: {delta_data.get('price')}")
                print(f"  Delta: {delta_data.get('delta')}")
                
                # Handle orderbook delta updates (Kalshi fixed-point March 12 2026: accept price_dollars or price in cents)
                market_ticker = delta_data.get("market_ticker", "")
                side = delta_data.get("side", "")
                price_raw = delta_data.get("price_dollars") or delta_data.get("price") or 0
                if isinstance(price_raw, str):
                    price = int(round(float(price_raw) * 100))
                else:
                    price = int(price_raw)
                delta_raw = delta_data.get("delta_fp") or delta_data.get("delta") or 0
                delta = int(float(delta_raw)) if isinstance(delta_raw, str) else int(delta_raw)
                
                if market_ticker:
                    # Apply delta to orderbook state
                    self.apply_orderbook_delta(market_ticker, side, price, delta)
                    
                    # Update market ticker with current state
                    if market_ticker in self.orderbook_state:
                        self.update_market_ticker(market_ticker, self.orderbook_state[market_ticker])
                    
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error handling orderbook message: {e}")
    
    async def run_websocket(self):
        """Main WebSocket loop"""
        print(f"[{datetime.now(EST)}] 🚀 Starting Kalshi Market Ticker WebSocket")
        
        # Connect to database
        if not self.connect_database():
            return
        
        # Clear previous data on startup
        self.clear_previous_data()
        
        # Get markets to subscribe to
        market_tickers = self.get_current_markets()
        if not market_tickers:
            print(f"[{datetime.now(EST)}] ❌ No markets to subscribe to")
            return
        
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                # Connect to WebSocket
                if not await self.connect_websocket():
                    self.reconnect_attempts += 1
                    await asyncio.sleep(5)
                    continue
                
                # Subscribe to market tickers
                if not await self.subscribe_to_market_tickers(market_tickers):
                    self.reconnect_attempts += 1
                    await asyncio.sleep(5)
                    continue
                
                # Reset reconnect attempts on successful connection
                self.reconnect_attempts = 0
                
                # Listen for messages
                async for message in self.websocket:
                    try:
                        data = json.loads(message)
                        await self.handle_orderbook_message(data)
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        print(f"[{datetime.now(EST)}] ❌ Error processing message: {e}")
                        
            except websockets.exceptions.ConnectionClosed:
                print(f"[{datetime.now(EST)}] ⚠️ WebSocket connection closed, reconnecting...")
                self.reconnect_attempts += 1
                await asyncio.sleep(5)
                
            except Exception as e:
                print(f"[{datetime.now(EST)}] ❌ WebSocket error: {e}")
                self.reconnect_attempts += 1
                await asyncio.sleep(5)
        
        print(f"[{datetime.now(EST)}] ❌ Max reconnection attempts reached, stopping")

async def main():
    watchdog = KalshiMarketTickerWebSocket()
    await watchdog.run_websocket()

if __name__ == "__main__":
    # Write log to logs/ instead of cwd (e.g. when run via nohup from project root)
    log_dir = get_logs_dir()
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "kalshi_websocket_market.log")
    log_file = open(log_path, "a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
    try:
        asyncio.run(main())
    finally:
        log_file.flush()
        log_file.close()
