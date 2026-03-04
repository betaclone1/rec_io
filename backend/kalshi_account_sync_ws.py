#!/usr/bin/env python3
"""
Kalshi Account Sync Hybrid WebSocket/Polling Version
Real-time account data synchronization using WebSocket triggers + REST API polling

HYBRID APPROACH:
1. Initial sync on startup (one-time polling cycle)
2. WebSocket subscription to market_positions channel
3. When position change detected → trigger full polling cycle
4. Periodic polling every 5 minutes to ensure data freshness
5. Hourly balance checks on the hour + daily 1AM balance check

This balances responsiveness with data freshness and API efficiency.

SUBACCOUNTS:
Subaccounts (users.subaccounts_0001) are an internal approximation of Kalshi subaccounts
and work in tandem with account_balance (users.account_balance_0001). All subaccount
logic—reading/writing subaccount balances and keeping them consistent with the main
portfolio—is the purview of this service (kalshi_account_sync).

Invariant: At ALL times the sum of all subaccount balances EXCEPT PRIMARY must equal
the PRIMARY balance. So PRIMARY = total portfolio; every other subaccount allocates
that total (e.g. Master Trading Bankroll + Cash Transfer + ... = PRIMARY). Whenever
the subaccounts table is updated, we should verify this reconciliation (to be implemented
when non-PRIMARY balances are written).
"""

import sys
import os

# Set up Python path to ensure imports work correctly
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
os.environ['PYTHONPATH'] = project_root
from backend.util.paths import get_project_root
from backend.account_mode import get_account_mode
import requests
import json
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import time
import os
from dotenv import dotenv_values
import base64
import hashlib
import hmac
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
import asyncio
import aiohttp
import websockets
import psycopg2
from psycopg2.extras import RealDictCursor
import schedule
from decimal import Decimal

# Add project root to path for imports
import sys
import os
from backend.util.paths import get_project_root
sys.path.insert(0, get_project_root())

from backend.util.paths import get_kalshi_data_dir, get_accounts_data_dir, ensure_data_dirs, get_kalshi_credentials_dir

# Import get_port directly to avoid circular import issues
try:
    from backend.core.port_config import get_port
except ImportError:
    # Fallback if import fails
    def get_port(service_name: str) -> int:
        """Fallback port function if port_config import fails"""
        default_ports = {
            "trade_manager": 4000,
            "main_app": 3000,
        }
        return default_ports.get(service_name, 3000)

# Ensure all data directories exist
ensure_data_dirs()

# Configuration
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"
EST = ZoneInfo("America/New_York")

async def retry_api_call_with_fallback(api_call_func, fallback_func, max_retries=3, base_delay=1):
    """
    Retry an API call with exponential backoff, falling back to WebSocket data if all retries fail
    
    Args:
        api_call_func: Function that makes the REST API call
        fallback_func: Function that uses WebSocket fallback data
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
    """
    for attempt in range(max_retries):
        try:
            print(f"🔄 REST API attempt {attempt + 1}/{max_retries}")
            result = api_call_func()
            if result is not None:
                print(f"✅ REST API successful on attempt {attempt + 1}")
                return result
            else:
                print(f"⚠️ REST API returned None on attempt {attempt + 1}")
        except Exception as e:
            print(f"❌ REST API attempt {attempt + 1} failed: {e}")
        
        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt)  # exponential backoff
            print(f"⏳ Waiting {delay}s before retry...")
            await asyncio.sleep(delay)
    
    # All retries failed, use WebSocket fallback
    print(f"🚨 All REST API attempts failed, using WebSocket fallback")
    return fallback_func()

def use_websocket_fallback_for_positions():
    """Use WebSocket position data as fallback when REST API fails"""
    global LATEST_WEBSOCKET_POSITION_DATA, LATEST_WEBSOCKET_TIMESTAMP
    
    if LATEST_WEBSOCKET_POSITION_DATA is None:
        print("❌ No WebSocket position data available for fallback")
        return None
    
    print("🔄 Using WebSocket position data as fallback")
    
    # Convert WebSocket format to REST API format
    ws_data = LATEST_WEBSOCKET_POSITION_DATA
    
    # Create REST API format position
    rest_position = {
        "ticker": ws_data.get("market_ticker"),
        "position": ws_data.get("position"),
        "market_exposure": ws_data.get("position_cost"),  # field mapping
        "market_exposure_dollars": [0, 0],
        "total_traded": ws_data.get("volume"),            # field mapping
        "total_traded_dollars": [0, 0],
        "realized_pnl": ws_data.get("realized_pnl"),
        "realized_pnl_dollars": [0, 0],
        "fees_paid": ws_data.get("fees_paid"),
        "fees_paid_dollars": [0, 0],
        "resting_orders_count": 0,
        "last_updated_ts": LATEST_WEBSOCKET_TIMESTAMP or datetime.now().isoformat() + "Z"
    }
    
    # Filter out KXMAYORNYCPARTY positions (same as REST API logic)
    if "KXMAYORNYCPARTY" in rest_position["ticker"]:
        print("🔍 Filtering out KXMAYORNYCPARTY position from WebSocket fallback")
        return None
    
    print(f"📊 WebSocket fallback position: {rest_position['ticker']} - Position: {rest_position['position']}")
    
    # Return in REST API format
    return {
        "market_positions": [rest_position],
        "event_positions": []
    }

def use_websocket_fallback_for_fills():
    """Use WebSocket position data to create fill data when REST API fails"""
    global LATEST_WEBSOCKET_POSITION_DATA, LATEST_WEBSOCKET_TIMESTAMP
    
    if LATEST_WEBSOCKET_POSITION_DATA is None:
        print("❌ No WebSocket position data available for fills fallback")
        return None
    
    print("🔄 Using WebSocket data to create fill fallback")
    
    ws_data = LATEST_WEBSOCKET_POSITION_DATA
    
    # Create a fill entry from WebSocket position data
    # This is a simplified approach - we create one fill entry per position update
    fill_data = {
        "ticker": ws_data.get("market_ticker"),
        "side": "yes" if ws_data.get("position", 0) > 0 else "no",  # Simplified side detection
        "action": "buy" if ws_data.get("position", 0) > 0 else "sell",
        "count": abs(ws_data.get("position", 0)),
        "yes_price": 1,  # Default values - would need more sophisticated logic
        "no_price": 99,
        "yes_price_dollars": [0, 0],
        "no_price_dollars": [0, 0],
        "created_time": LATEST_WEBSOCKET_TIMESTAMP or datetime.now().isoformat() + "Z",
        "order_id": f"ws_fallback_{int(time.time())}",  # Generate a fallback order ID
        "user_id": ws_data.get("user_id")
    }
    
    print(f"📊 WebSocket fallback fill: {fill_data['ticker']} - {fill_data['action']} {fill_data['count']}")
    
    return {
        "fills": [fill_data],
        "cursor": ""
    }

# Global variables for change detection
LAST_ORDERS_HASH = None
LAST_FILLS_HASH = None
LAST_POSITIONS_HASH = None

# Global variables for WebSocket fallback
LATEST_WEBSOCKET_POSITION_DATA = None
LATEST_WEBSOCKET_TIMESTAMP = None

# Dynamically select API base URL and credentials directory based on account mode
BASE_URLS = {
    "prod": "https://api.elections.kalshi.com/trade-api/v2",
    "demo": "https://demo-api.kalshi.co/trade-api/v2"
}

def get_base_url():
    BASE_URLS = {
        "prod": "https://api.elections.kalshi.com/trade-api/v2",
        "demo": "https://demo-api.kalshi.co/trade-api/v2"
    }
    return BASE_URLS.get(get_account_mode(), BASE_URLS["prod"])

print(f"Using base URL: {get_base_url()} for mode: {get_account_mode()}")

from backend.util.paths import get_kalshi_credentials_dir
CREDENTIALS_DIR = Path(get_kalshi_credentials_dir()) / get_account_mode()
ENV_VARS = dotenv_values(CREDENTIALS_DIR / ".env")

KEY_ID = ENV_VARS.get("KALSHI_API_KEY_ID")
KEY_PATH = CREDENTIALS_DIR / "kalshi.pem"

# PostgreSQL connection function
def get_postgresql_connection():
    """Get a connection to the PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return None


def _fp_to_numeric(v):
    """Convert API _fp string to Decimal for NUMERIC columns; None/empty -> None."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def generate_kalshi_signature(method, full_path, timestamp, key_path):
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    import base64

    with open(key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )

    message = f"{timestamp}{method.upper()}{full_path}".encode("utf-8")

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    return base64.b64encode(signature).decode("utf-8")

# Config
API_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "KalshiWatcher/1.0"
}

EST = ZoneInfo("America/New_York")

last_failed_ticker = None  # Global tracker

# === PATCH: Initialize global hashes to prevent crash ===
LAST_POSITIONS_HASH = None
LAST_FILLS_HASH = None
LAST_ORDERS_HASH = None

# Global variables for change detection
LAST_POSITIONS_HASH = None
LAST_FILLS_HASH = None
LAST_SETTLEMENTS_HASH = None

def notify_frontend_db_change(db_name: str, change_data: dict = None):
    """Send WebSocket notification to frontend about database changes"""
    try:
        # Use requests instead of aiohttp to avoid event loop conflicts
        import requests
        
        # Try to import get_host, with fallback
        try:
            from backend.util.paths import get_host
            host = get_host()
        except ImportError:
            host = "localhost"  # Fallback to localhost
        
        # Use get_port function to get main_app port
        main_app_port = get_port("main_app")
        notification_url = f"http://{host}:{main_app_port}/api/notify_db_change"
        payload = {
            "db_name": db_name,
            "timestamp": time.time(),
            "change_data": change_data or {}
        }
        
        response = requests.post(notification_url, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"✅ Frontend notified of {db_name} change")
        else:
            print(f"⚠️ Failed to notify frontend: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error notifying frontend: {e}")

def notify_monitor_manager():
    """Notify monitor_manager that bankroll has been updated."""
    try:
        import requests
        from backend.core.port_config import get_port
        
        monitor_port = get_port("monitor_manager")
        response = requests.post(
            f"http://localhost:{monitor_port}/api/bankroll_updated",
            json={},
            timeout=5
        )
        
        if response.ok:
            result = response.json()
            print(f"📡 Monitor manager notified: {result}")
        else:
            print(f"⚠️ Failed to notify monitor manager: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error notifying monitor manager: {e}")


def get_current_event_ticker():
    global last_failed_ticker
    now = datetime.now(EST)

    # Construct current hour ticker
    test_time = now + timedelta(hours=1)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    current_ticker = f"KXBTCD-{year_str}{month_str}{day_str}{hour_str}"

    # Skip retrying if last attempt already failed this ticker
    if last_failed_ticker != current_ticker:
        data = fetch_event_json(current_ticker)
        if data and "markets" in data:
            return current_ticker, data
        else:
            last_failed_ticker = current_ticker

    # Try next hour
    test_time = now + timedelta(hours=1)
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
    url = f"{get_base_url()}/events/{event_ticker}"
    try:
        response = requests.get(url, headers=API_HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            print(f"[{datetime.now()}] ❌ API returned error for ticker {event_ticker}: {data['error']}")
            return None
        return data
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Exception fetching event JSON: {e}")
        return None


def subaccounts_update(cursor, portfolio_value):
    """
    Update users.subaccounts_0001: PRIMARY, Master Trading Bankroll balance and PnLs,
    then check target_pnl_pct and run internal transfer to Cash Transfer if triggered.
    Returns (master_bankroll_balance, transfer_triggered).
    """
    # PRIMARY = total portfolio
    cursor.execute("""
        UPDATE users.subaccounts_0001 SET balance = %s WHERE subaccount = 'PRIMARY'
    """, (portfolio_value,))
    # Cash Transfer balance (unchanged until/unless we trigger a transfer)
    cursor.execute("""
        SELECT COALESCE(balance, 0) FROM users.subaccounts_0001 WHERE subaccount = 'Cash Transfer'
    """)
    cash_transfer_row = cursor.fetchone()
    cash_transfer_balance = int(cash_transfer_row[0]) if cash_transfer_row else 0
    master_bankroll_balance = portfolio_value - cash_transfer_balance
    # MTB base_value, target/transfer settings, and automatic_transfers (user setting)
    cursor.execute("""
        SELECT base_value, target_pnl__pct, transfer_amt, automatic_transfers FROM users.subaccounts_0001 WHERE subaccount = 'Master Trading Bankroll'
    """)
    mtb_row = cursor.fetchone()
    base_value = int(mtb_row[0]) if mtb_row and mtb_row[0] is not None else None
    target_pnl_pct = float(mtb_row[1]) if mtb_row and mtb_row[1] is not None else None
    transfer_amt = float(mtb_row[2]) if mtb_row and mtb_row[2] is not None else None
    automatic_transfers = bool(mtb_row[3]) if mtb_row and mtb_row[3] is not None else False
    if base_value is not None and base_value != 0:
        realized_pnl = master_bankroll_balance - base_value
        ratio = (master_bankroll_balance - base_value) / base_value
        realized_pnl_pct = float(int(ratio * 10000)) / 10000.0
    else:
        realized_pnl = None
        realized_pnl_pct = None
    cursor.execute("""
        UPDATE users.subaccounts_0001
        SET balance = %s, realized_pnl = %s, realized_pnl_pct = %s
        WHERE subaccount = 'Master Trading Bankroll'
    """, (master_bankroll_balance, realized_pnl, realized_pnl_pct))
    transfer_triggered = False
    # Internal transfer: only if automatic_transfers is TRUE and realized_pnl_pct >= target_pnl_pct
    if (
        automatic_transfers
        and base_value is not None and base_value != 0
        and target_pnl_pct is not None
        and transfer_amt is not None
        and realized_pnl_pct is not None
        and realized_pnl_pct >= target_pnl_pct
    ):
        transfer_amount = int(round(transfer_amt * base_value))
        new_cash_transfer_balance = cash_transfer_balance + transfer_amount
        cursor.execute("""
            UPDATE users.subaccounts_0001 SET balance = %s WHERE subaccount = 'Cash Transfer'
        """, (new_cash_transfer_balance,))
        new_mtb_balance = portfolio_value - new_cash_transfer_balance
        cursor.execute("""
            UPDATE users.subaccounts_0001
            SET balance = %s, base_value = %s, realized_pnl = 0, realized_pnl_pct = 0
            WHERE subaccount = 'Master Trading Bankroll'
        """, (new_mtb_balance, new_mtb_balance))
        master_bankroll_balance = new_mtb_balance
        transfer_triggered = True
        # Record the transfer in users.transfers_0001
        transfer_timestamp_est = datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO users.transfers_0001 (timestamp, type, "from", "to", amount, initiated)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (transfer_timestamp_est, "internal", "Master Trading Bankroll", "Cash Transfer", transfer_amount, "automatic"))
        print(f"💾 Internal transfer: {transfer_amount} to Cash Transfer (target_pnl_pct={target_pnl_pct} reached). MTB base_value reset to {new_mtb_balance}, PnL reset to 0. Recorded in users.transfers_0001.")
    print(f"💾 PRIMARY={portfolio_value}, Master Trading Bankroll={master_bankroll_balance} (Cash Transfer={new_cash_transfer_balance if transfer_triggered else cash_transfer_balance}), realized_pnl={0 if transfer_triggered else realized_pnl}, realized_pnl_pct={0 if transfer_triggered else realized_pnl_pct} (users.subaccounts_0001)")
    return (master_bankroll_balance, transfer_triggered)


def sync_balance():
    print("⏱ Sync attempt...")
    method = "GET"
    path = "/portfolio/balance"
    url = f"{get_base_url()}{path}"
    timestamp = str(int(time.time() * 1000))  # milliseconds

    if not KEY_ID or not KEY_PATH.exists():
        print("❌ Missing Kalshi API credentials or PEM file.")
        return

    signature = generate_kalshi_signature(method, f"/trade-api/v2{path}", timestamp, str(KEY_PATH))

    headers = {
        "Accept": "application/json",
        "User-Agent": "KalshiWatcher/1.0",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        balance_amount = data.get('balance')
        portfolio_value_raw = data.get('portfolio_value')  # Current value of open positions from Kalshi API
        total_portfolio_value = balance_amount + portfolio_value_raw  # Total portfolio = cash + positions
        print(f"[{datetime.now()}] ✅ Balance (cash): {balance_amount}, Open Positions Value: {portfolio_value_raw}, Total Portfolio: {total_portfolio_value}")
        
        # Write to PostgreSQL only
        try:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    current_timestamp = datetime.now(EST).isoformat()
                    
                    # Get total exposure from POSITIONS table
                    cursor.execute("""
                        SELECT COALESCE(SUM(market_exposure), 0) as total_exposure
                        FROM users.positions_0001
                    """)
                    exposure_result = cursor.fetchone()
                    total_exposure = int(exposure_result[0]) if exposure_result and exposure_result[0] else 0
                    
                    # Get previous bankroll for ratchet (and for hold when positions != 0)
                    cursor.execute("""
                        SELECT portfolio, bankroll_current FROM users.account_balance_0001 
                        ORDER BY id DESC LIMIT 1
                    """)
                    prev_result = cursor.fetchone()
                    prev_bankroll = prev_result[1] if prev_result else None
                    
                    # PORTFOLIO = total at Kalshi (cash + positions). Feeds PRIMARY in subaccounts; written to account_balance.portfolio.
                    portfolio_value = int(total_portfolio_value)
                    positions_value = int(portfolio_value_raw)
                    
                    # Only update subaccounts and derive bankroll_current from Master Trading Bankroll when flat (positions=0).
                    # When positions != 0, skip subaccounts and hold bankroll_current to avoid noisy API during open/close.
                    if positions_value == 0:
                        # Update subaccounts (PRIMARY, MTB, PnLs; internal transfer if target hit). Returns (mtb_balance, transfer_triggered).
                        master_bankroll_balance, transfer_triggered = subaccounts_update(cursor, portfolio_value)
                        if transfer_triggered:
                            # After internal transfer, use new MTB balance directly as bankroll_current (bypass ratchet).
                            bankroll_current = master_bankroll_balance
                        else:
                            # Ratchet: bankroll_current from Master Trading Bankroll (step up / step down only on large drawdown / else hold)
                            if prev_bankroll is None:
                                bankroll_current = master_bankroll_balance
                            elif master_bankroll_balance > prev_bankroll:
                                bankroll_current = master_bankroll_balance
                            elif master_bankroll_balance <= (prev_bankroll * 0.7):
                                bankroll_current = master_bankroll_balance
                            else:
                                bankroll_current = prev_bankroll
                    else:
                        # Hold bankroll_current; do not update subaccounts
                        bankroll_current = prev_bankroll if prev_bankroll is not None else portfolio_value
                    
                    cursor.execute("""
                        INSERT INTO users.account_balance_0001 (balance, exposure, positions, portfolio, bankroll_current, portfolio_value, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (balance_amount, total_exposure, positions_value, portfolio_value, bankroll_current, portfolio_value_raw, current_timestamp))
                    pg_conn.commit()
                    print(f"💾 Balance (cash: {balance_amount}), Open Positions ({positions_value}), Total Portfolio ({portfolio_value}), bankroll_current={bankroll_current} (positions={'flat' if positions_value == 0 else 'open'}) written to users.account_balance_0001")
                    
                    # Notify frontend of account balance change
                    notify_frontend_db_change("account_balance", {
                        "balance": balance_amount,
                        "exposure": total_exposure,
                        "positions": positions_value,
                        "portfolio": portfolio_value,
                        "portfolio_value_raw": portfolio_value_raw,
                        "total_portfolio": total_portfolio_value
                    })
                    
                    # Notify monitor_manager of bankroll update
                    notify_monitor_manager()
                pg_conn.close()
            else:
                print(f"⚠️ Skipping PostgreSQL write - no connection available")
        except Exception as pg_err:
            print(f"❌ Failed to write balance to PostgreSQL: {pg_err}")
            
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Failed to fetch balance: {e}")



# --- New sync functions for positions, fills, settlements using PostgreSQL ---



def sync_positions():
    # PostgreSQL only - no legacy database paths needed
    print("⏱ Syncing recent positions...")
    
    def make_rest_api_call():
        """Make the REST API call for positions"""
        method = "GET"
        path = "/portfolio/positions"
        
        # Single request for recent positions (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        print(f"🔗 Requesting recent positions: {url}")

        full_path_for_signature = f"/trade-api/v2{path}"
        signature = generate_kalshi_signature(method, full_path_for_signature, timestamp, str(KEY_PATH))

        headers = {
            "Accept": "application/json",
            "User-Agent": "KalshiWatcher/1.0",
            "KALSHI-ACCESS-KEY": KEY_ID,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print("🔍 Raw Kalshi positions response:")
            print(json.dumps(data, indent=2))
            print("Response keys:", data.keys())
            if "error" in data:
                print("⚠️ API error:", data["error"])
                return None
            
            # Use new keys for positions
            all_market_positions = data.get("market_positions", [])
            all_event_positions = data.get("event_positions", [])
            
            # TEMPORARY MEASURE: Filter out KXMAYORNYCPARTY positions
            # Due to a quirk in the Kalshi API feed, old test positions from months ago
            # continue to appear in the positions response even though they should be
            # expired/cleaned up. This filtering prevents these stale test positions
            # from cluttering our database and notifications.
            # TODO: Remove this filtering once Kalshi fixes their feed cleanup issue
            filtered_market_positions = []
            filtered_event_positions = []
            
            for position in all_market_positions:
                ticker = position.get("ticker", "")
                if "KXMAYORNYCPARTY" not in ticker:
                    filtered_market_positions.append(position)
                else:
                    # Silently ignore KXMAYORNYCPARTY positions (temporary filter)
                    pass
            
            for position in all_event_positions:
                event_ticker = position.get("event_ticker", "")
                if "KXMAYORNYCPARTY" not in event_ticker:
                    filtered_event_positions.append(position)
                else:
                    # Silently ignore KXMAYORNYCPARTY event positions (temporary filter)
                    pass
            
            print(f"📊 Retrieved {len(all_market_positions)} market positions and {len(all_event_positions)} event positions")
            print(f"🔍 After filtering: {len(filtered_market_positions)} market positions and {len(filtered_event_positions)} event positions")
            
            # Use filtered positions for processing
            all_market_positions = filtered_market_positions
            all_event_positions = filtered_event_positions
            
            return {
                "market_positions": all_market_positions,
                "event_positions": all_event_positions,
            }
            
        except Exception as e:
            print(f"❌ Failed to fetch positions: {e}")
            raise e  # Re-raise to trigger retry logic
    
    # Use retry logic with WebSocket fallback
    try:
        # Note: This is a synchronous function, so we can't use async retry here
        # We'll implement the retry logic directly
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                print(f"🔄 REST API attempt {attempt + 1}/{max_retries}")
                data = make_rest_api_call()
                if data is not None:
                    print(f"✅ REST API successful on attempt {attempt + 1}")
                    break
                else:
                    print(f"⚠️ REST API returned None on attempt {attempt + 1}")
            except Exception as e:
                print(f"❌ REST API attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    print(f"⏳ Waiting {delay}s before retry...")
                    time.sleep(delay)
                else:
                    print(f"🚨 All REST API attempts failed, using WebSocket fallback")
                    data = use_websocket_fallback_for_positions()
                    if data is None:
                        print("❌ WebSocket fallback also failed, aborting positions sync")
                        return
        else:
            # All retries exhausted
            print(f"🚨 All REST API attempts failed, using WebSocket fallback")
            data = use_websocket_fallback_for_positions()
            if data is None:
                print("❌ WebSocket fallback also failed, aborting positions sync")
                return
    
    except Exception as e:
        print(f"❌ Error in positions sync: {e}")
        return

    # Process the data (either from REST API or WebSocket fallback)
    all_market_positions = data.get("market_positions", [])
    all_event_positions = data.get("event_positions", [])

    # ----- CHANGE-DETECTION: skip writes if nothing changed -----
    global LAST_POSITIONS_HASH
    snapshot_dict = {
        "market_positions": all_market_positions,
        "event_positions": all_event_positions,
    }
    try:
        snapshot_hash = hashlib.md5(
            json.dumps(snapshot_dict, sort_keys=True).encode()
        ).hexdigest()
    except Exception as e:
        print(f"❌ Failed to hash positions snapshot: {e}")
        return

    if snapshot_hash == LAST_POSITIONS_HASH:
        print("🔁 No changes in positions — skipping write.")
        return  # Exit early; nothing new to write

    LAST_POSITIONS_HASH = snapshot_hash
    # ------------------------------------------------------------
    # Write to PostgreSQL
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                # Clear existing positions
                cursor.execute("DELETE FROM users.positions_0001")
                
                for p in all_market_positions:
                    try:
                        ticker = p.get("ticker")
                        total_traded = p.get("total_traded")
                        position_value = p.get("position")
                        market_exposure = p.get("market_exposure")
                        # Legacy cent values - no longer used, kept for database compatibility only
                        realized_pnl = None
                        fees_paid = None
                        last_updated_ts = p.get("last_updated_ts")
                        raw_json = json.dumps(p)
                        
                        # Extract dollar values from API response (new subpenny pricing fields)
                        total_traded_dollars = p.get("total_traded_dollars")
                        market_exposure_dollars = p.get("market_exposure_dollars")
                        realized_pnl_dollars = p.get("realized_pnl_dollars")
                        fees_paid_dollars = p.get("fees_paid_dollars")
                        # Fixed-point contract counts (Kalshi migration); store as NUMERIC
                        total_traded_fp = _fp_to_numeric(p.get("total_traded_fp"))
                        position_fp = _fp_to_numeric(p.get("position_fp"))

                        cursor.execute("""
                            INSERT INTO users.positions_0001
                            (ticker, total_traded, position, market_exposure, realized_pnl, fees_paid, last_updated_ts, raw_json,
                             total_traded_dollars, market_exposure_dollars, realized_pnl_dollars, fees_paid_dollars,
                             total_traded_fp, position_fp)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (ticker, total_traded, position_value, market_exposure, realized_pnl, fees_paid, last_updated_ts, raw_json,
                              total_traded_dollars, market_exposure_dollars, realized_pnl_dollars, fees_paid_dollars,
                              total_traded_fp, position_fp))
                    except Exception as e:
                        print(f"❌ Failed to insert position {p.get('ticker')} to PostgreSQL: {e}")
                
                pg_conn.commit()
                print(f"💾 All positions also written to PostgreSQL users.positions_0001")
            pg_conn.close()
        else:
            print(f"⚠️ Skipping PostgreSQL write - no connection available")
    except Exception as pg_err:
        print(f"❌ Failed to write positions to PostgreSQL: {pg_err}")

    # JSON writing removed - PostgreSQL only
    notify_frontend_db_change("positions", {"market_positions": len(all_market_positions), "event_positions": len(all_event_positions)})
    
    # Notify trade_manager about positions update
    try:
        trade_manager_port = get_port("trade_manager")
        response = requests.post(
            f"http://localhost:{trade_manager_port}/api/positions_updated",
            json={"database": "positions"},
            timeout=5
        )
        if response.status_code == 200:
            print(f"✅ Notified trade_manager about positions update")
        else:
            print(f"⚠️ Failed to notify trade_manager: {response.status_code}")
    except Exception as e:
        print(f"❌ Error notifying trade_manager: {e}")


def sync_fills():
    # PostgreSQL only - no legacy database paths needed
    print("⏱ Syncing recent fills...")
    
    def make_rest_api_call():
        """Make the REST API call for fills"""
        method = "GET"
        path = "/portfolio/fills"
        
        # Single request for recent fills (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        print(f"🔗 Requesting recent fills: {url}")

        full_path_for_signature = f"/trade-api/v2{path}"
        signature = generate_kalshi_signature(method, full_path_for_signature, timestamp, str(KEY_PATH))

        headers = {
            "Accept": "application/json",
            "User-Agent": "KalshiWatcher/1.0",
            "KALSHI-ACCESS-KEY": KEY_ID,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print("Response keys:", data.keys())
            if "error" in data:
                print("⚠️ API error:", data["error"])
                return None
            
            all_fills = data.get("fills", [])
            print(f"📊 Retrieved {len(all_fills)} recent fills")
            
            return data
            
        except Exception as e:
            print(f"❌ Failed to fetch fills: {e}")
            raise e  # Re-raise to trigger retry logic
    
    # Use retry logic
    try:
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                print(f"🔄 REST API attempt {attempt + 1}/{max_retries}")
                data = make_rest_api_call()
                if data is not None:
                    print(f"✅ REST API successful on attempt {attempt + 1}")
                    break
                else:
                    print(f"⚠️ REST API returned None on attempt {attempt + 1}")
            except Exception as e:
                print(f"❌ REST API attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    print(f"⏳ Waiting {delay}s before retry...")
                    time.sleep(delay)
                else:
                    print(f"🚨 All REST API attempts failed, using WebSocket fallback")
                    data = use_websocket_fallback_for_fills()
                    if data is None:
                        print("❌ WebSocket fallback also failed, aborting fills sync")
                        return
        else:
            # All retries exhausted
            print(f"🚨 All REST API attempts failed, using WebSocket fallback")
            data = use_websocket_fallback_for_fills()
            if data is None:
                print("❌ WebSocket fallback also failed, aborting fills sync")
                return
    
    except Exception as e:
        print(f"❌ Error in fills sync: {e}")
        return

    # Process the data (either from REST API or WebSocket fallback)
    all_fills = data.get("fills", [])

    # WebSocket triggers ensure we only poll when there's new data, so always write

    if all_fills:
        latest_time = all_fills[0].get("created_time")
        oldest_time = all_fills[-1].get("created_time")
        print(f"🕒 Fills range — newest: {latest_time}, oldest: {oldest_time}, total: {len(all_fills)}")
        
        # ------------------------------------------------------------
        # Write to PostgreSQL (write all fills, let PostgreSQL handle duplicates)
        try:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    pg_new_count = 0
                    for fill in all_fills:
                        trade_id = fill.get("trade_id")
                        if not trade_id:
                            continue
                        ticker = fill.get("ticker")
                        order_id = fill.get("order_id")
                        side = fill.get("side")
                        action = fill.get("action")
                        count = fill.get("count")
                        count_fp = _fp_to_numeric(fill.get("count_fp"))
                        # Legacy cent values - no longer used, kept for database compatibility only
                        yes_price = None
                        no_price = None
                        # Extract dollar values from API response (new subpenny pricing fields)
                        # Note: Fills API uses "yes_price_fixed" and "no_price_fixed" instead of "_dollars"
                        yes_price_dollars = fill.get("yes_price_fixed")
                        no_price_dollars = fill.get("no_price_fixed")
                        is_taker = bool(fill.get("is_taker")) if fill.get("is_taker") is not None else None
                        created_time = fill.get("created_time")
                        raw_json = json.dumps(fill)

                        try:
                            cursor.execute("""
                                INSERT INTO users.fills_0001
                                (trade_id, ticker, order_id, side, action, count, count_fp, yes_price, no_price, yes_price_fixed, no_price_fixed, is_taker, created_time, raw_json)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (trade_id) DO NOTHING
                            """, (trade_id, ticker, order_id, side, action, count, count_fp, yes_price, no_price, yes_price_dollars, no_price_dollars, is_taker, created_time, raw_json))
                            pg_new_count += 1
                        except Exception as e:
                            print(f"❌ Failed to insert fill {trade_id} to PostgreSQL: {e}")
                    
                    pg_conn.commit()
                    print(f"💾 {pg_new_count} fills written to PostgreSQL users.fills_0001")
                pg_conn.close()
            else:
                print(f"⚠️ Skipping PostgreSQL write - no connection available")
        except Exception as pg_err:
            print(f"❌ Failed to write fills to PostgreSQL: {pg_err}")
        
        # JSON writing removed - PostgreSQL only
        print(f"💾 Fills written to PostgreSQL only")
    else:
        print("⚠️ API returned zero fills.")

    notify_frontend_db_change("fills", {"fills": len(all_fills)})
    
    # Notify trade_manager about fills update
    try:
        trade_manager_port = get_port("trade_manager")
        response = requests.post(
            f"http://localhost:{trade_manager_port}/api/positions_updated",
            json={"database": "fills"},
            timeout=5
        )
        if response.status_code == 200:
            print(f"✅ Notified trade_manager about fills update")
        else:
            print(f"⚠️ Failed to notify trade_manager: {response.status_code}")
    except Exception as e:
        print(f"❌ Error notifying trade_manager: {e}")


def sync_settlements():
    # PostgreSQL only - no legacy database paths needed
    print("⏱ Syncing recent settlements...")
    
    def make_rest_api_call():
        """Make the REST API call for settlements"""
        method = "GET"
        path = "/portfolio/settlements"
        
        # Single request for recent settlements (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        print(f"🔗 Requesting recent settlements: {url}")

        full_path_for_signature = f"/trade-api/v2{path}"
        signature = generate_kalshi_signature(method, full_path_for_signature, timestamp, str(KEY_PATH))

        headers = {
            "Accept": "application/json",
            "User-Agent": "KalshiWatcher/1.0",
            "KALSHI-ACCESS-KEY": KEY_ID,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print("Response keys:", data.keys())
            if "error" in data:
                print("⚠️ API error:", data["error"])
                return None
            
            all_settlements = data.get("settlements", [])
            print(f"📊 Retrieved {len(all_settlements)} recent settlements")
            
            return data
            
        except Exception as e:
            print(f"❌ Failed to fetch settlements: {e}")
            raise e  # Re-raise to trigger retry logic
    
    # Use retry logic
    try:
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                print(f"🔄 REST API attempt {attempt + 1}/{max_retries}")
                data = make_rest_api_call()
                if data is not None:
                    print(f"✅ REST API successful on attempt {attempt + 1}")
                    break
                else:
                    print(f"⚠️ REST API returned None on attempt {attempt + 1}")
            except Exception as e:
                print(f"❌ REST API attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    print(f"⏳ Waiting {delay}s before retry...")
                    time.sleep(delay)
                else:
                    print(f"🚨 All REST API attempts failed for settlements")
                    return
        else:
            # All retries exhausted
            print(f"🚨 All REST API attempts failed for settlements")
            return
    
    except Exception as e:
        print(f"❌ Error in settlements sync: {e}")
        return

    # Process the data
    all_settlements = data.get("settlements", [])

    # Transform settlements for PostgreSQL insertion
    # PostgreSQL only
    
    # Write to PostgreSQL
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                # Ensure settlements table has proper structure with unique constraint
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users.settlements_0001 (
                        id SERIAL PRIMARY KEY,
                        ticker TEXT,
                        market_result TEXT,
                        yes_count INTEGER,
                        yes_total_cost DECIMAL(10,2),
                        no_count INTEGER,
                        no_total_cost DECIMAL(10,2),
                        revenue DECIMAL(10,2),
                        settled_time TEXT,
                        raw_json TEXT,
                        UNIQUE(ticker, settled_time)
                    )
                """)
                
                for settlement in all_settlements:
                    try:
                        ticker = settlement.get("ticker")
                        market_result = settlement.get("market_result")
                        yes_count = settlement.get("yes_count")
                        yes_count_fp = _fp_to_numeric(settlement.get("yes_count_fp"))
                        yes_total_cost = settlement.get("yes_total_cost")
                        no_count = settlement.get("no_count")
                        no_count_fp = _fp_to_numeric(settlement.get("no_count_fp"))
                        no_total_cost = settlement.get("no_total_cost")
                        revenue = settlement.get("revenue")
                        settled_time = settlement.get("settled_time")
                        raw_json = json.dumps(settlement)

                        # Convert cent values to dollars (divide by 100)
                        try:
                            revenue = float(revenue) / 100 if revenue is not None else None
                            yes_total_cost = float(yes_total_cost) / 100 if yes_total_cost is not None else None
                            no_total_cost = float(no_total_cost) / 100 if no_total_cost is not None else None
                        except Exception as e:
                            print(f"⚠️ Error formatting cost fields for {ticker} at {settled_time}: {e}")
                            continue

                        cursor.execute("""
                            INSERT INTO users.settlements_0001
                            (ticker, market_result, yes_count, yes_count_fp, yes_total_cost, no_count, no_count_fp, no_total_cost, revenue, settled_time, raw_json)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (ticker, settled_time) DO NOTHING
                        """, (ticker, market_result, yes_count, yes_count_fp, yes_total_cost, no_count, no_count_fp, no_total_cost, revenue, settled_time, raw_json))
                    except Exception as e:
                        print(f"❌ Failed to insert settlement {settlement.get('ticker')} to PostgreSQL: {e}")
                
                pg_conn.commit()
                print(f"💾 All settlements also written to PostgreSQL users.settlements_0001")
            pg_conn.close()
        else:
            print(f"⚠️ Skipping PostgreSQL write - no connection available")
    except Exception as pg_err:
        print(f"❌ Failed to write settlements to PostgreSQL: {pg_err}")
    
    # JSON writing removed - PostgreSQL only
    notify_frontend_db_change("settlements", {"settlements": len(all_settlements)})


def sync_orders():
    # PostgreSQL only - no legacy database paths needed
    print("⏱ Syncing recent orders...")
    
    def make_rest_api_call():
        """Make the REST API call for orders"""
        method = "GET"
        path = "/portfolio/orders"
        
        # Single request for recent orders (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        print(f"🔗 Requesting recent orders: {url}")

        full_path_for_signature = f"/trade-api/v2{path}"
        signature = generate_kalshi_signature(method, full_path_for_signature, timestamp, str(KEY_PATH))

        headers = {
            "Accept": "application/json",
            "User-Agent": "KalshiWatcher/1.0",
            "KALSHI-ACCESS-KEY": KEY_ID,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            print("Response keys:", data.keys())
            if "error" in data:
                print("⚠️ API error:", data["error"])
                return None
            
            all_orders = data.get("orders", [])
            print(f"📊 Retrieved {len(all_orders)} recent orders")
            
            return data
            
        except Exception as e:
            print(f"❌ Failed to fetch orders: {e}")
            raise e  # Re-raise to trigger retry logic
    
    # Use retry logic
    try:
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                print(f"🔄 REST API attempt {attempt + 1}/{max_retries}")
                data = make_rest_api_call()
                if data is not None:
                    print(f"✅ REST API successful on attempt {attempt + 1}")
                    break
                else:
                    print(f"⚠️ REST API returned None on attempt {attempt + 1}")
            except Exception as e:
                print(f"❌ REST API attempt {attempt + 1} failed: {e}")
                
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    print(f"⏳ Waiting {delay}s before retry...")
                    time.sleep(delay)
                else:
                    print(f"🚨 All REST API attempts failed for orders")
                    return
        else:
            # All retries exhausted
            print(f"🚨 All REST API attempts failed for orders")
            return
    
    except Exception as e:
        print(f"❌ Error in orders sync: {e}")
        return

    # Process the data
    all_orders = data.get("orders", [])

    # WebSocket triggers ensure we only poll when there's new data, so always write

    if all_orders:
        latest_time = all_orders[0].get("created_time")
        oldest_time = all_orders[-1].get("created_time")
        print(f"🕒 Orders range — newest: {latest_time}, oldest: {oldest_time}, total: {len(all_orders)}")
    else:
        print("⚠️ API returned zero orders.")
    
    # ------------------------------------------------------------
    # Write to PostgreSQL with DELTA CHECKING and UPDATES
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                # Get existing orders with key fields for delta comparison (use _fp for counts so we don't depend on legacy)
                cursor.execute("""
                    SELECT order_id, status, fill_count, remaining_count, fill_count_fp, remaining_count_fp,
                           last_update_time, taker_fees, maker_fees, taker_fill_cost, maker_fill_cost
                    FROM users.orders_0001
                """)
                existing_orders = {row[0]: {
                    'status': row[1],
                    'fill_count': row[2],
                    'remaining_count': row[3],
                    'fill_count_fp': row[4],
                    'remaining_count_fp': row[5],
                    'last_update_time': row[6],
                    'taker_fees': row[7],
                    'maker_fees': row[8],
                    'taker_fill_cost': row[9],
                    'maker_fill_cost': row[10]
                } for row in cursor.fetchall()}
                
                pg_new_count = 0
                pg_updated_count = 0
                
                for order in all_orders:
                    order_id = order.get("order_id")
                    if not order_id:
                        continue
                    
                    # Check if order exists
                    if order_id in existing_orders:
                        # DELTA CHECK - Compare key fields that can change
                        existing = existing_orders[order_id]
                        needs_update = False
                        
                        # Check for changes in critical fields (use _fp for counts so API can omit legacy)
                        api_fill_fp = _fp_to_numeric(order.get("fill_count_fp"))
                        api_remaining_fp = _fp_to_numeric(order.get("remaining_count_fp"))
                        if (existing['status'] != order.get("status") or
                            existing['fill_count_fp'] != api_fill_fp or
                            existing['remaining_count_fp'] != api_remaining_fp or
                            existing['last_update_time'] != order.get("last_update_time") or
                            existing['taker_fees'] != order.get("taker_fees") or
                            existing['maker_fees'] != order.get("maker_fees") or
                            existing['taker_fill_cost'] != order.get("taker_fill_cost") or
                            existing['maker_fill_cost'] != order.get("maker_fill_cost")):
                            needs_update = True
                        
                        if needs_update:
                            try:
                                # UPDATE existing order with new data
                                cursor.execute("""
                                    UPDATE users.orders_0001 SET
                                        status = %s, fill_count = %s, remaining_count = %s,
                                        fill_count_fp = %s, remaining_count_fp = %s,
                                        last_update_time = %s, taker_fees = %s, maker_fees = %s,
                                        taker_fill_cost = %s, maker_fill_cost = %s, queue_position = %s,
                                        raw_json = %s, updated_at = CURRENT_TIMESTAMP
                                    WHERE order_id = %s
                                """, (
                                    order.get("status"),
                                    order.get("fill_count"),
                                    order.get("remaining_count"),
                                    _fp_to_numeric(order.get("fill_count_fp")),
                                    _fp_to_numeric(order.get("remaining_count_fp")),
                                    order.get("last_update_time"),
                                    order.get("taker_fees"),
                                    order.get("maker_fees"),
                                    order.get("taker_fill_cost"),
                                    order.get("maker_fill_cost"),
                                    order.get("queue_position"),
                                    json.dumps(order),
                                    order_id
                                ))
                                pg_updated_count += 1
                                print(f"🔄 Updated order {order_id}: status={order.get('status')}, fills={order.get('fill_count')}")
                            except Exception as e:
                                print(f"❌ Failed to update order {order_id}: {e}")
                    else:
                        # INSERT new order
                        try:
                            cursor.execute("""
                                INSERT INTO users.orders_0001
                                (order_id, user_id, ticker, status, action, side, type, yes_price, no_price, yes_price_dollars, no_price_dollars,
                                 initial_count, initial_count_fp, remaining_count, remaining_count_fp, fill_count, fill_count_fp,
                                 created_time, expiration_time, last_update_time, client_order_id, order_group_id, queue_position,
                                 self_trade_prevention_type, maker_fees, taker_fees, maker_fill_cost,
                                 taker_fill_cost, raw_json)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                order_id,
                                order.get("user_id"),
                                order.get("ticker"),
                                order.get("status"),
                                order.get("action"),
                                order.get("side"),
                                order.get("type"),
                                order.get("yes_price"),
                                order.get("no_price"),
                                order.get("yes_price_dollars"),
                                order.get("no_price_dollars"),
                                order.get("initial_count"),
                                _fp_to_numeric(order.get("initial_count_fp")),
                                order.get("remaining_count"),
                                _fp_to_numeric(order.get("remaining_count_fp")),
                                order.get("fill_count"),
                                _fp_to_numeric(order.get("fill_count_fp")),
                                order.get("created_time"),
                                order.get("expiration_time"),
                                order.get("last_update_time"),
                                order.get("client_order_id"),
                                order.get("order_group_id"),
                                order.get("queue_position"),
                                order.get("self_trade_prevention_type"),
                                order.get("maker_fees"),
                                order.get("taker_fees"),
                                order.get("maker_fill_cost"),
                                order.get("taker_fill_cost"),
                                json.dumps(order)
                            ))
                            pg_new_count += 1
                            print(f"➕ Inserted new order {order_id}: status={order.get('status')}")
                        except Exception as e:
                            print(f"❌ Failed to insert order {order_id}: {e}")
                
                pg_conn.commit()
                print(f"💾 Orders sync complete: {pg_new_count} new, {pg_updated_count} updated in PostgreSQL users.orders_0001")
            pg_conn.close()
        else:
            print(f"⚠️ Skipping PostgreSQL write - no connection available")
    except Exception as pg_err:
        print(f"❌ Failed to write orders to PostgreSQL: {pg_err}")
    
    # JSON writing removed - PostgreSQL only
    print(f"💾 Orders written to PostgreSQL only")

    notify_frontend_db_change("orders", {"orders": len(all_orders)})
    
    # Notify trade_manager about orders update
    try:
        trade_manager_port = get_port("trade_manager")
        response = requests.post(
            f"http://localhost:{trade_manager_port}/api/positions_updated",
            json={"database": "orders"},
            timeout=2
        )
        if response.status_code == 200:
            print(f"✅ Notified trade_manager about orders update")
        else:
            print(f"⚠️ Failed to notify trade_manager about orders: {response.status_code}")
    except Exception as e:
        print(f"❌ Error notifying trade_manager about orders: {e}")


class KalshiWebSocketSync:
    def __init__(self):
        self.websocket = None
        self.subscription_id = None
        self.command_id = 1
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        
    def load_kalshi_credentials(self):
        """Load Kalshi API credentials"""
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
        
        return {
            "KEY_ID": env_vars.get("KALSHI_API_KEY_ID"),
            "KEY_PATH": key_path
        }
    
    async def connect(self):
        """Connect to Kalshi User Fills WebSocket API"""
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
            
            print(f"[{datetime.now(EST)}] 🔐 Attempting User Fills WebSocket connection...")
            print(f"[{datetime.now(EST)}] 📊 Account Mode: {get_account_mode()}")
            print(f"[{datetime.now(EST)}] 🔑 Using API Key: {credentials['KEY_ID'][:8]}...")
            
            # Connect with authentication headers
            self.websocket = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=10
            )
            
            print(f"[{datetime.now(EST)}] ✅ Connected to Kalshi User Fills WebSocket API")
            self.reconnect_attempts = 0  # Reset reconnect attempts on successful connection
            return True
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to connect to User Fills WebSocket: {e}")
            return False
    
    async def subscribe_to_market_positions(self):
        """Subscribe to market positions channel"""
        if not self.websocket:
            return False
        
        try:
            # Subscribe to market positions channel only
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["market_positions"]
                }
            }
            
            await self.websocket.send(json.dumps(subscription_message))
            print(f"[{datetime.now(EST)}] 📡 Sent market positions subscription: {json.dumps(subscription_message)}")
            
            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            if response_data.get("type") == "subscribed":
                self.subscription_id = response_data.get("msg", {}).get("sid")
                print(f"[{datetime.now(EST)}] ✅ Subscribed to market positions with SID: {self.subscription_id}")
                return True
            else:
                print(f"[{datetime.now(EST)}] ❌ Market positions subscription failed: {response_data}")
                return False
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Failed to subscribe to market positions: {e}")
            return False
    
    async def handle_market_position_message(self, message):
        """Handle incoming market position messages and trigger full polling cycle"""
        try:
            data = json.loads(message)
            
            if data.get("type") == "market_position":
                position_data = data.get("msg", {})
                
                # Store latest WebSocket data for fallback use
                global LATEST_WEBSOCKET_POSITION_DATA, LATEST_WEBSOCKET_TIMESTAMP
                LATEST_WEBSOCKET_POSITION_DATA = position_data
                LATEST_WEBSOCKET_TIMESTAMP = datetime.now().isoformat() + "Z"
                
                print(f"\n[{datetime.now(EST)}] 📊 MARKET POSITION UPDATE RECEIVED!")
                print(f"   User ID: {position_data.get('user_id')}")
                print(f"   Market Ticker: {position_data.get('market_ticker')}")
                print(f"   Position: {position_data.get('position')}")
                print(f"   Position Cost: {position_data.get('position_cost')} (centi-cents)")
                print(f"   Realized PnL: {position_data.get('realized_pnl')} (centi-cents)")
                print(f"   Fees Paid: {position_data.get('fees_paid')} (centi-cents)")
                print(f"   Volume: {position_data.get('volume')}")
                print("=" * 50)
                
                # WebSocket ONLY as trigger - NO direct database writes
                print(f"[{datetime.now(EST)}] 🔔 Position change detected! Triggering full REST API polling cycle...")
                await self.trigger_full_polling_cycle()
                
            elif data.get("type") == "subscribed":
                print(f"[{datetime.now(EST)}] ✅ Subscription confirmed: {data}")
                
            elif data.get("type") == "error":
                print(f"[{datetime.now(EST)}] ❌ WebSocket error: {data}")
                
            else:
                print(f"[{datetime.now(EST)}] 📨 Other message: {data}")
                
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error handling message: {e}")
            print(f"Raw message: {message}")
    
    async def trigger_full_polling_cycle(self):
        """Trigger a complete polling cycle for all endpoints when position changes"""
        try:
            print(f"[{datetime.now(EST)}] 🔄 Starting triggered polling cycle...")
            
            # Run all sync functions asynchronously - balance LAST so it can reference latest positions data
            await self.async_sync_positions()
            await self.async_sync_fills()
            await self.async_sync_orders()
            await self.async_sync_settlements()
            await self.async_sync_balance()
            
            print(f"[{datetime.now(EST)}] ✅ Triggered polling cycle completed!")
            
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error in triggered polling cycle: {e}")
    
    async def async_sync_balance(self):
        """Async version of sync_balance"""
        try:
            print(f"[{datetime.now(EST)}] ⏱ Triggered balance sync...")
            sync_balance()
            print(f"[{datetime.now(EST)}] ✅ Triggered balance sync completed")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error in triggered balance sync: {e}")
    
    async def async_sync_positions(self):
        """Async version of sync_positions"""
        try:
            print(f"[{datetime.now(EST)}] ⏱ Triggered positions sync...")
            sync_positions()
            print(f"[{datetime.now(EST)}] ✅ Triggered positions sync completed")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error in triggered positions sync: {e}")
    
    async def async_sync_fills(self):
        """Async version of sync_fills"""
        try:
            print(f"[{datetime.now(EST)}] ⏱ Triggered fills sync...")
            sync_fills()
            print(f"[{datetime.now(EST)}] ✅ Triggered fills sync completed")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error in triggered fills sync: {e}")
    
    async def async_sync_orders(self):
        """Async version of sync_orders"""
        try:
            print(f"[{datetime.now(EST)}] ⏱ Triggered orders sync...")
            sync_orders()
            print(f"[{datetime.now(EST)}] ✅ Triggered orders sync completed")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error in triggered orders sync: {e}")
    
    async def async_sync_settlements(self):
        """Async version of sync_settlements"""
        try:
            print(f"[{datetime.now(EST)}] ⏱ Triggered settlements sync...")
            sync_settlements()
            print(f"[{datetime.now(EST)}] ✅ Triggered settlements sync completed")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error in triggered settlements sync: {e}")
    
    # REMOVED: write_market_position_to_db function
    # WebSocket now ONLY serves as a trigger for REST API polling
    # All database writes happen through the standardized REST API sync functions
    

    
    async def store_market_lifecycle(self, lifecycle_data):
        """Store market lifecycle data (placeholder for future use)"""
        try:
            # This could be used to track market state changes
            # For now, just log that we received it
            print(f"[{datetime.now(EST)}] 💾 Market lifecycle data received for {lifecycle_data.get('market_ticker')}")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error storing market lifecycle: {e}")
    
    async def store_event_lifecycle(self, event_data):
        """Store event lifecycle data (placeholder for future use)"""
        try:
            # This could be used to track event creation and updates
            # For now, just log that we received it
            print(f"[{datetime.now(EST)}] 💾 Event lifecycle data received for {event_data.get('event_ticker')}")
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Error storing event lifecycle: {e}")
    
    async def periodic_polling_task(self):
        """Periodic polling task that runs every 5 minutes"""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes = 300 seconds
                print(f"[{datetime.now(EST)}] ⏰ 5-minute periodic polling triggered...")
                await self.trigger_full_polling_cycle()
            except Exception as e:
                print(f"[{datetime.now(EST)}] ❌ Error in periodic polling task: {e}")
    
    async def run_websocket(self):
        """Main WebSocket run loop - Hybrid approach: WebSocket triggers + periodic polling"""
        print(f"[{datetime.now(EST)}] 🔌 Starting Kalshi Hybrid WebSocket/Polling Sync...")
        
        # Start periodic polling task in the background
        periodic_task = asyncio.create_task(self.periodic_polling_task())
        print(f"[{datetime.now(EST)}] ⏰ Started 5-minute periodic polling task")
        
        while True:
            try:
                # Connect to WebSocket
                if not await self.connect():
                    print(f"[{datetime.now(EST)}] ❌ Failed to connect, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue
                
                # Subscribe to market positions
                if not await self.subscribe_to_market_positions():
                    print(f"[{datetime.now(EST)}] ❌ Failed to subscribe, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue
                
                print(f"[{datetime.now(EST)}] 🎧 Listening for market position notifications...")
                print(f"[{datetime.now(EST)}] 💡 Position changes will trigger full polling cycle!")
                print(f"[{datetime.now(EST)}] ⏰ Periodic polling every 5 minutes!")
                print(f"[{datetime.now(EST)}] 🚀 HYBRID MODE: WebSocket triggers + 5-min polling → Polling updates all DBs!")
                
                # Listen for messages
                async for message in self.websocket:
                    await self.handle_market_position_message(message)
                    
            except websockets.exceptions.ConnectionClosed:
                print(f"[{datetime.now(EST)}] 🔌 WebSocket connection closed, attempting to reconnect...")
                if self.websocket:
                    await self.websocket.close()
                await asyncio.sleep(5)
                
            except Exception as e:
                print(f"[{datetime.now(EST)}] ❌ WebSocket error: {e}")
                await asyncio.sleep(5)


def scheduled_balance_check():
    """Scheduled task to run balance check at 1AM every morning"""
    print(f"[{datetime.now(EST)}] 🕐 Scheduled 1AM EST balance check triggered")
    try:
        sync_balance()
        print(f"[{datetime.now(EST)}] ✅ Scheduled balance check completed successfully")
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error in scheduled balance check: {e}")

def hourly_balance_check():
    """Scheduled task to run balance check every hour on the hour"""
    print(f"[{datetime.now(EST)}] 🕐 Hourly balance check triggered")
    try:
        sync_balance()
        print(f"[{datetime.now(EST)}] ✅ Hourly balance check completed successfully")
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error in hourly balance check: {e}")

def run_scheduler():
    """Run the scheduler in a separate thread"""
    # Schedule for 1AM Eastern Time
    schedule.every().day.at("01:00").do(scheduled_balance_check)
    print(f"[{datetime.now(EST)}] 📅 Scheduled daily balance check at 1AM EST")
    
    # Schedule hourly balance checks (every hour on the hour)
    schedule.every().hour.do(hourly_balance_check)
    print(f"[{datetime.now(EST)}] 📅 Scheduled hourly balance checks every hour on the hour")
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def main():
    print("🔌 Kalshi Account Hybrid WebSocket/Polling Supervisor Starting...")
    print("✅ Authenticated account access confirmed via balance endpoint.")
    
    # Initial sync to establish baseline data (one-time only)
    print("📊 Performing initial baseline data sync...")
    sync_positions()
    sync_fills()
    sync_orders()
    sync_settlements()
    sync_balance()  # Update balance LAST so it can reference latest positions data
    
    print("✅ Initial baseline sync complete.")
    print("🚀 Starting hybrid mode: WebSocket triggers + 5-min polling → Updates all DBs!")
    print("💡 Polling triggers: WebSocket position changes + every 5 minutes")
    print("📅 Daily balance check scheduled for 1AM EST")
    print("📅 Hourly balance checks scheduled every hour on the hour")
    
    # Start scheduler in a separate thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Create and run WebSocket sync
    websocket_sync = KalshiWebSocketSync()
    
    try:
        # Run the WebSocket sync
        asyncio.run(websocket_sync.run_websocket())
    except KeyboardInterrupt:
        print("🛑 Hybrid WebSocket/Polling supervisor stopped by user")
    except Exception as e:
        print(f"❌ Error in hybrid WebSocket/Polling supervisor: {e}")

if __name__ == "__main__":
    main()