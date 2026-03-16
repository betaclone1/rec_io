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
import logging

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

# Logging: one formatter (EST), one line format; quiet by default (INFO = startup, errors, one-line outcome); flush after each line for real-time visibility
def _est_formatter():
    """Formatter that uses EST for asctime (ISO 8601 with offset)."""
    class ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=EST)
            if datefmt:
                return dt.strftime(datefmt)
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)

    return ESTFormatter(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _FlushingStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every emit so supervisor-captured logs appear in real time."""

    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_logging():
    logger = logging.getLogger("kalshi_account_sync")
    if logger.handlers:
        return logger
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_est_formatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = _configure_logging()


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
            logger.debug("REST API attempt %s/%s", attempt + 1, max_retries)
            result = api_call_func()
            if result is not None:
                logger.debug("REST API successful on attempt %s", attempt + 1)
                return result
            else:
                logger.debug("REST API returned None on attempt %s", attempt + 1)
        except Exception as e:
            logger.debug("REST API attempt %s failed: %s", attempt + 1, e)

        if attempt < max_retries - 1:
            delay = base_delay * (2 ** attempt)  # exponential backoff
            logger.debug("Waiting %ss before retry", delay)
            await asyncio.sleep(delay)

    # All retries failed, use WebSocket fallback
    logger.warning("All REST API attempts failed, using WebSocket fallback")
    return fallback_func()

def use_websocket_fallback_for_positions():
    """Use WebSocket position data as fallback when REST API fails"""
    global LATEST_WEBSOCKET_POSITION_DATA, LATEST_WEBSOCKET_TIMESTAMP
    
    if LATEST_WEBSOCKET_POSITION_DATA is None:
        logger.warning("No WebSocket position data available for fallback")
        return None

    logger.debug("Using WebSocket position data as fallback")
    
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
        logger.debug("Filtering out KXMAYORNYCPARTY position from WebSocket fallback")
        return None

    logger.debug("WebSocket fallback position: %s - Position: %s", rest_position["ticker"], rest_position["position"])
    
    # Return in REST API format
    return {
        "market_positions": [rest_position],
        "event_positions": []
    }

def use_websocket_fallback_for_fills():
    """Use WebSocket position data to create fill data when REST API fails"""
    global LATEST_WEBSOCKET_POSITION_DATA, LATEST_WEBSOCKET_TIMESTAMP
    
    if LATEST_WEBSOCKET_POSITION_DATA is None:
        logger.warning("No WebSocket position data available for fills fallback")
        return None

    logger.debug("Using WebSocket data to create fill fallback")
    
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
    
    logger.debug("WebSocket fallback fill: %s - %s %s", fill_data["ticker"], fill_data["action"], fill_data["count"])

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

logger.info("Started kalshi_account_sync (base_url=%s, mode=%s)", get_base_url(), get_account_mode())

from backend.util.paths import get_kalshi_credentials_dir
CREDENTIALS_DIR = Path(get_kalshi_credentials_dir()) / get_account_mode()
ENV_VARS = dotenv_values(CREDENTIALS_DIR / ".env")

KEY_ID = ENV_VARS.get("KALSHI_API_KEY_ID")
KEY_PATH = CREDENTIALS_DIR / "kalshi.pem"

# PostgreSQL connection function
def get_postgresql_connection():
    """Get a connection to the PostgreSQL database (uses centralized config)."""
    from backend.core.config.database import get_postgresql_connection as _get_pg
    return _get_pg()


def _fp_to_numeric(v):
    """Convert API _fp string to Decimal for NUMERIC columns; None/empty -> None."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _dollars_to_cents(value):
    """
    Convert Kalshi *_dollars string/number fields to integer cents for storage in legacy columns.

    We keep both:
    - *_dollars TEXT in the DB mirroring the API field
    - integer cent columns for existing consumers (e.g. trade_manager)
    """
    if value is None:
        return None
    try:
        if isinstance(value, str):
            return int(round(float(value) * 100))
        if isinstance(value, (int, float, Decimal)):
            return int(round(float(value) * 100))
        return None
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
            logger.debug("Frontend notified of %s change", db_name)
        else:
            logger.warning("Failed to notify frontend: %s", response.status_code)

    except Exception as e:
        logger.error("Error notifying frontend: %s", e)

def notify_monitor_manager(bankroll_stepped_down=False):
    """Notify monitor_manager that bankroll has been updated. Pass bankroll_stepped_down=True when bankroll was stepped down due to significant drawdown (MTB <= 70% of mtb_base_value, or 70% of prev bankroll if base not set)."""
    try:
        import requests
        from backend.core.port_config import get_port
        
        monitor_port = get_port("monitor_manager")
        response = requests.post(
            f"http://localhost:{monitor_port}/api/bankroll_updated",
            json={"bankroll_stepped_down": bankroll_stepped_down},
            timeout=5
        )
        
        if response.ok:
            logger.debug("Monitor manager notified: %s", response.json())
        else:
            logger.warning("Failed to notify monitor manager: %s", response.status_code)

    except Exception as e:
        logger.error("Error notifying monitor manager: %s", e)


# --- Kalshi v1 account/history (deposits/withdrawals) ---
KALSHI_V1_BASE_URL = "https://api.elections.kalshi.com"


def fetch_v1_account_history_page(kalshi_user_id, page_number=1, page_size=200):
    """GET one page of v1 account/history (DEPRECATED by Kalshi; returns 404). Use fetch_v1_deposits_page and fetch_v1_withdrawals_page instead. Returns (entries list, None) or ([], error string)."""
    path = f"/v1/users/{kalshi_user_id}/account/history"
    url = KALSHI_V1_BASE_URL + path
    params = {"deposits": "true", "withdrawals": "true", "page_size": page_size, "page_number": page_number}
    timestamp = str(int(time.time() * 1000))
    signature = generate_kalshi_signature("GET", path, timestamp, str(KEY_PATH))
    headers = {
        "Accept": "application/json",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return [], f"HTTP {r.status_code}"
        body = r.json()
        return body.get("entries") or [], None
    except Exception as e:
        return [], str(e)


def _v1_request(kalshi_user_id, path, page_number=1, page_size=200):
    """GET v1 path with auth. Returns (response_dict, None) or (None, error string)."""
    params = {"page_size": page_size, "page_number": page_number}
    url = KALSHI_V1_BASE_URL + path
    timestamp = str(int(time.time() * 1000))
    signature = generate_kalshi_signature("GET", path, timestamp, str(KEY_PATH))
    headers = {
        "Accept": "application/json",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "KALSHI-ACCESS-SIGNATURE": signature,
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except Exception as e:
        return None, str(e)


def fetch_v1_deposits_page(kalshi_user_id, page_number=1, page_size=200):
    """GET one page of v1 /deposits. Returns (deposits list, None) or ([], error string)."""
    path = f"/v1/users/{kalshi_user_id}/deposits"
    body, err = _v1_request(kalshi_user_id, path, page_number=page_number, page_size=page_size)
    if err:
        return [], err
    return (body.get("deposits") or []), None


def fetch_v1_withdrawals_page(kalshi_user_id, page_number=1, page_size=200):
    """GET one page of v1 /withdrawals. Returns (withdrawals list, None) or ([], error string)."""
    path = f"/v1/users/{kalshi_user_id}/withdrawals"
    body, err = _v1_request(kalshi_user_id, path, page_number=page_number, page_size=page_size)
    if err:
        return [], err
    return (body.get("withdrawals") or []), None


def _normalize_created_at(created_at):
    """Normalize API created_at to datetime for matching. Handles ISO string or datetime."""
    if created_at is None:
        return None
    if hasattr(created_at, "replace") and hasattr(created_at, "hour"):
        return created_at
    s = str(created_at).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _backfill_account_history_vendor_rail(conn, all_deposits, all_withdrawals):
    """Update existing account_history_0001 rows that have NULL kalshi_id/vendor/rail from API data.
    Matches by (entry_type, amount) and created_at within 2 seconds. Then refreshes transfer from/to."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, created_at, entry_type, amount
            FROM users.account_history_0001
            WHERE kalshi_id IS NULL
            ORDER BY id
        """)
        rows = cur.fetchall()
    if not rows:
        return
    api_entries = []
    for item in all_deposits or []:
        created_at = _normalize_created_at(item.get("created_ts") or item.get("created_at"))
        amount = item.get("amount_cents") if item.get("amount_cents") is not None else item.get("amount")
        if amount is not None and created_at is not None:
            try:
                amount_int = int(amount)
            except (TypeError, ValueError):
                continue
            api_entries.append((
                created_at, "Deposit", amount_int,
                str(item.get("id") or "").strip() or None,
                (str(item.get("vendor") or "").strip() or None),
                (str(item.get("rail") or "").strip() or None),
            ))
    for item in all_withdrawals or []:
        created_at = _normalize_created_at(item.get("created_ts") or item.get("created_at"))
        amount = item.get("amount_cents") if item.get("amount_cents") is not None else item.get("amount")
        if amount is not None and created_at is not None:
            try:
                amount_int = int(amount)
            except (TypeError, ValueError):
                continue
            api_entries.append((
                created_at, "Withdrawal", amount_int,
                str(item.get("id") or "").strip() or None,
                (str(item.get("vendor") or "").strip() or None),
                (str(item.get("rail") or "").strip() or None),
            ))
    updated = 0
    for ah_id, db_created_at, entry_type, amount in rows:
        if db_created_at is None or amount is None:
            continue
        try:
            amount_int = int(amount)
        except (TypeError, ValueError):
            continue
        db_ts = db_created_at
        if hasattr(db_ts, "timestamp"):
            db_seconds = db_ts.timestamp()
        else:
            continue
        best = None
        for api_created, api_type, api_amt, kalshi_id, vendor, rail in api_entries:
            if api_type != entry_type or api_amt != amount_int:
                continue
            if api_created is None:
                continue
            if hasattr(api_created, "timestamp"):
                api_seconds = api_created.timestamp()
            else:
                continue
            if abs(api_seconds - db_seconds) < 2:
                best = (kalshi_id, vendor, rail)
                break
        if best is None:
            continue
        kalshi_id, vendor, rail = best
        if not kalshi_id:
            continue
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users.account_history_0001 WHERE kalshi_id = %s LIMIT 1", (kalshi_id,))
            if cur.fetchone():
                continue
            cur.execute("""
                UPDATE users.account_history_0001
                SET kalshi_id = %s, vendor = %s, rail = %s
                WHERE id = %s
            """, (kalshi_id, vendor, rail, ah_id))
        updated += 1
    conn.commit()
    _refresh_transfer_from_to_from_account_history(conn)


def _refresh_transfer_from_to_from_account_history(conn):
    """Update transfers_0001 from/to and status from their linked account_history_0001 row (vendor/rail/deposit_type)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.id, ah.entry_type, ah.deposit_type, ah.vendor, ah.rail, ah.status
            FROM users.transfers_0001 t
            JOIN users.account_history_0001 ah ON ah.id = t.external_transfer_id
            WHERE t.external_transfer_id IS NOT NULL
        """)
        rows = cur.fetchall()
    for t_id, entry_type, deposit_type, vendor, rail, status in rows:
        if entry_type == "Deposit":
            raw = (vendor or deposit_type or "External").strip()
            from_str = "ACH" if raw and raw.lower() == "ach" else (raw.title() or "External")
            to_str = "Cash Transfer"
        else:
            from_str = "Cash Transfer"
            to_str = (rail or "ACH").strip() if rail else "ACH"
        status_str = (status or "").strip() or None
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users.transfers_0001
                SET "from" = %s, "to" = %s, status = %s
                WHERE id = %s
            """, (from_str, to_str, status_str, t_id))
    conn.commit()


def _deposit_item_to_row(item):
    """Convert one v1 /deposits API item to a dict for account_history_0001."""
    amount = item.get("amount_cents") if item.get("amount_cents") is not None else item.get("amount")
    if amount is None:
        return None
    created_at = _normalize_created_at(item.get("created_ts") or item.get("created_at"))
    if created_at is None:
        return None
    updated_at = _normalize_created_at(item.get("updated_ts") or item.get("updated_at")) or created_at
    fee = item.get("fee") or item.get("fee_cents") or 0
    try:
        amount_int = int(amount)
        fee_int = int(fee)
    except (TypeError, ValueError):
        return None
    return {
        "entry_type": "Deposit",
        "amount": amount_int,
        "fee": fee_int,
        "created_at": created_at,
        "updated_at": updated_at,
        "status": (item.get("status") or "").strip() or None,
        "returned_amount": int(item.get("returned_amount") or item.get("returned_amount_cents") or 0),
        "deposit_type": (item.get("deposit_type") or item.get("rail") or "").strip() or None,
        "immediate_amount": int(item["immediate_amount"]) if item.get("immediate_amount") is not None else None,
        "immediate_status": (item.get("immediate_status") or "").strip() or None,
    }


def _withdrawal_item_to_row(item):
    """Convert one v1 /withdrawals API item to a dict for account_history_0001."""
    amount = item.get("amount_cents") if item.get("amount_cents") is not None else item.get("amount")
    if amount is None:
        return None
    created_at = _normalize_created_at(item.get("created_ts") or item.get("created_at"))
    if created_at is None:
        return None
    updated_at = _normalize_created_at(item.get("updated_ts") or item.get("updated_at")) or created_at
    fee = item.get("fee") or item.get("fee_cents") or 0
    try:
        amount_int = int(amount)
        fee_int = int(fee)
    except (TypeError, ValueError):
        return None
    return {
        "entry_type": "Withdrawal",
        "amount": amount_int,
        "fee": fee_int,
        "created_at": created_at,
        "updated_at": updated_at,
        "status": (item.get("status") or "").strip() or None,
        "returned_amount": int(item.get("returned_amount") or item.get("returned_amount_cents") or 0),
        "deposit_type": None,
        "immediate_amount": None,
        "immediate_status": None,
    }


def _upsert_account_history(conn, rows):
    """Insert or update rows in users.account_history_0001. Simple UPDATE-then-INSERT per row; no ON CONFLICT, no unique constraint required."""
    if not rows:
        return 0

    with conn.cursor() as cur:
        for r in rows:
            cur.execute("""
                UPDATE users.account_history_0001 SET
                    updated_at = %s,
                    status = %s,
                    returned_amount = %s,
                    deposit_type = %s,
                    immediate_amount = %s,
                    immediate_status = %s,
                    synced_at = CURRENT_TIMESTAMP
                WHERE created_at = %s AND entry_type = %s AND amount = %s
            """, (
                r["updated_at"], r["status"], r["returned_amount"], r["deposit_type"],
                r["immediate_amount"], r["immediate_status"],
                r["created_at"], r["entry_type"], r["amount"]
            ))
            if cur.rowcount == 0:
                cur.execute(f"""
                    INSERT INTO users.account_history_0001 (entry_type, amount, fee, created_at, updated_at, status, returned_amount, deposit_type, immediate_amount, immediate_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    r["entry_type"], r["amount"], r["fee"], r["created_at"], r["updated_at"],
                    r["status"], r["returned_amount"], r["deposit_type"],
                    r["immediate_amount"], r["immediate_status"]
                ))
    conn.commit()
    return len(rows)


def _ensure_external_transfers_from_account_history(conn):
    """Create transfer rows for account_history entries that don't have one. Returns (inserted_count, new_deposit_amounts, new_withdrawal_amounts)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, entry_type, amount, fee, created_at, status, deposit_type
            FROM users.account_history_0001
            WHERE id NOT IN (SELECT external_transfer_id FROM users.transfers_0001 WHERE external_transfer_id IS NOT NULL)
            ORDER BY id
        """)
        rows = cur.fetchall()
    if not rows:
        return 0, [], []
    inserted = 0
    new_deposit_amounts = []
    new_withdrawal_amounts = []
    for row in rows:
        ah_id, entry_type, amount, fee, created_at, status, deposit_type = row
        amount_net = int(amount) - int(fee or 0)
        if created_at:
            try:
                ts_est = created_at.astimezone(EST) if hasattr(created_at, "astimezone") else datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).astimezone(EST)
            except Exception:
                ts_est = datetime.now(EST)
            timestamp_str = ts_est.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S")
        status_str = (status or "").strip() or None
        if entry_type == "Deposit":
            raw = (deposit_type or "External").strip()
            from_str = "ACH" if raw.lower() == "ach" else (raw.title() or "External")
            to_str = "Cash Transfer"
        else:
            from_str = "Cash Transfer"
            to_str = "ACH"  # no deposit_type for withdrawals; assume destination is ACH
        # Deposits: positive amount. Withdrawals: negative amount.
        amount_for_transfer = amount_net if entry_type == "Deposit" else -amount_net
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users.transfers_0001 (timestamp, type, "from", "to", amount, initiated, status, external_transfer_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (timestamp_str, "external", from_str, to_str, amount_for_transfer, "manual", status_str, ah_id))
        inserted += 1
        if entry_type == "Deposit":
            new_deposit_amounts.append(amount_net)
        elif entry_type == "Withdrawal":
            new_withdrawal_amounts.append(amount_net)
    conn.commit()
    return inserted, new_deposit_amounts, new_withdrawal_amounts


def _update_external_transfer_status_from_account_history(conn):
    """Refresh status (and other synced fields) on existing external transfers from their account_history row.
    When a withdrawal is first reported it may have status other than 'applied'; when Kalshi updates it
    we update account_history on next sync, then this updates the transfer row via external_transfer_id."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users.transfers_0001 t
            SET status = ah.status
            FROM users.account_history_0001 ah
            WHERE t.external_transfer_id = ah.id AND t.external_transfer_id IS NOT NULL
        """)
    conn.commit()


def sync_account_history(conn, kalshi_user_id):
    """Fetch v1 /deposits and /withdrawals, upsert account_history_0001, create external transfers.
    Returns (n_upserted, error_str, new_deposit_amounts, new_withdrawal_amounts).
    Uses deposits and withdrawals endpoints only; v1 account/history is deprecated (404)."""
    page_size = 200
    all_deposits = []
    page_number = 1
    while True:
        deposits, err = fetch_v1_deposits_page(kalshi_user_id, page_number=page_number, page_size=page_size)
        if err:
            return 0, err, [], []
        all_deposits.extend(deposits)
        if len(deposits) < page_size:
            break
        page_number += 1
    all_withdrawals = []
    page_number = 1
    while True:
        withdrawals, err = fetch_v1_withdrawals_page(kalshi_user_id, page_number=page_number, page_size=page_size)
        if err:
            return 0, err, [], []
        all_withdrawals.extend(withdrawals)
        if len(withdrawals) < page_size:
            break
        page_number += 1
    rows = []
    for item in all_deposits:
        r = _deposit_item_to_row(item)
        if r is not None:
            rows.append(r)
    for item in all_withdrawals:
        r = _withdrawal_item_to_row(item)
        if r is not None:
            rows.append(r)
    if not rows:
        return 0, None, [], []
    rows.sort(key=lambda r: (r["created_at"], r["entry_type"], r["amount"]))
    try:
        n = _upsert_account_history(conn, rows)
        _backfill_account_history_vendor_rail(conn, all_deposits, all_withdrawals)
        _, new_deposit_amounts, new_withdrawal_amounts = _ensure_external_transfers_from_account_history(conn)
        _update_external_transfer_status_from_account_history(conn)
        return n, None, new_deposit_amounts, new_withdrawal_amounts
    except Exception as e:
        return 0, str(e), [], []


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
            logger.error("API returned error for ticker %s: %s", event_ticker, data["error"])
            return None
        return data
    except Exception as e:
        logger.error("Exception fetching event JSON: %s", e)
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
        # New base_value = old base_value raised by (target_pnl_pct - transfer_amt), not set to new_mtb_balance
        base_step_pct = target_pnl_pct - transfer_amt
        new_base_value = int(round(base_value * (1 + base_step_pct)))
        post_transfer_realized_pnl = new_mtb_balance - new_base_value
        post_transfer_ratio = (new_mtb_balance - new_base_value) / new_base_value if new_base_value else 0
        post_transfer_realized_pnl_pct = float(int(post_transfer_ratio * 10000)) / 10000.0
        cursor.execute("""
            UPDATE users.subaccounts_0001
            SET balance = %s, base_value = %s, realized_pnl = %s, realized_pnl_pct = %s
            WHERE subaccount = 'Master Trading Bankroll'
        """, (new_mtb_balance, new_base_value, post_transfer_realized_pnl, post_transfer_realized_pnl_pct))
        master_bankroll_balance = new_mtb_balance
        transfer_triggered = True
        # Record the transfer in users.transfers_0001
        transfer_timestamp_est = datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO users.transfers_0001 (timestamp, type, "from", "to", amount, initiated)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (transfer_timestamp_est, "internal", "Master Trading Bankroll", "Cash Transfer", transfer_amount, "automatic"))
        logger.debug("Internal transfer: %s to Cash Transfer (target_pnl_pct reached). Recorded in users.transfers_0001", transfer_amount)
    _pnl = post_transfer_realized_pnl if transfer_triggered else realized_pnl
    _pnl_pct = post_transfer_realized_pnl_pct if transfer_triggered else realized_pnl_pct
    logger.debug("PRIMARY=%s, Master Trading Bankroll=%s, realized_pnl=%s (users.subaccounts_0001)", portfolio_value, master_bankroll_balance, _pnl)
    return (master_bankroll_balance, transfer_triggered)


def _get_mtb_snapshot_from_subaccounts(cur):
    """
    Return (master_trading_bankroll, mtb_base_value) in cents from users.subaccounts_0001
    for the 'Master Trading Bankroll' subaccount, or (None, None) if not present.
    """
    cur.execute("""
        SELECT balance, base_value
        FROM users.subaccounts_0001
        WHERE subaccount = 'Master Trading Bankroll'
    """)
    row = cur.fetchone()
    if not row:
        return None, None
    balance, base_value = row
    return (int(balance) if balance is not None else None,
            int(base_value) if base_value is not None else None)


def sync_balance():
    logger.debug("Sync attempt...")
    method = "GET"
    path = "/portfolio/balance"
    url = f"{get_base_url()}{path}"
    timestamp = str(int(time.time() * 1000))  # milliseconds

    if not KEY_ID or not KEY_PATH.exists():
        logger.error("Missing Kalshi API credentials or PEM file")
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
        logger.debug("Balance (cash): %s, Open Positions Value: %s, Total Portfolio: %s", balance_amount, portfolio_value_raw, total_portfolio_value)

        # Write to PostgreSQL only
        try:
            pg_conn = get_postgresql_connection()
            kalshi_user_id_for_history = None
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    current_timestamp = datetime.now(EST).isoformat()

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
                    # Use positions_value as our exposure metric in the fixed-point world.
                    total_exposure = positions_value
                    
                    # Only update subaccounts and derive bankroll_current from Master Trading Bankroll when flat (positions=0).
                    # When positions != 0, skip subaccounts and hold bankroll_current to avoid noisy API during open/close.
                    bankroll_stepped_down = False
                    if positions_value == 0:
                        # Update subaccounts (PRIMARY, MTB, PnLs; internal transfer if target hit). Returns (mtb_balance, transfer_triggered).
                        master_bankroll_balance, transfer_triggered = subaccounts_update(cursor, portfolio_value)
                        if transfer_triggered:
                            # After internal transfer, use new MTB balance directly as bankroll_current (bypass ratchet).
                            bankroll_current = master_bankroll_balance
                        else:
                            # Ratchet: bankroll_current from Master Trading Bankroll. Drawdown threshold pegged to mtb_base_value (70% of base); step up when MTB > prev, else hold unless drawdown.
                            _, mtb_base = _get_mtb_snapshot_from_subaccounts(cursor)
                            drawdown_threshold = (mtb_base * 0.7) if (mtb_base is not None and mtb_base > 0) else (prev_bankroll * 0.7) if prev_bankroll else None
                            if prev_bankroll is None:
                                # First bankroll initialization: no drawdown edge to detect yet.
                                bankroll_current = master_bankroll_balance
                            elif master_bankroll_balance > prev_bankroll:
                                # Normal ratchet up when MTB makes a new high.
                                bankroll_current = master_bankroll_balance
                            elif drawdown_threshold is not None and master_bankroll_balance <= drawdown_threshold:
                                # Drawdown branch: only trigger the one-time safety valve when we CROSS the threshold
                                # from above to below (edge detector), not on every poll while below it.
                                bankroll_current = master_bankroll_balance
                                if prev_bankroll > drawdown_threshold:
                                    bankroll_stepped_down = True
                            else:
                                # Hold previous bankroll when neither stepping up nor crossing the drawdown threshold.
                                bankroll_current = prev_bankroll
                    else:
                        # Hold bankroll_current; do not update subaccounts
                        bankroll_current = prev_bankroll if prev_bankroll is not None else portfolio_value

                    # Throttle: skip INSERT and notifies if last row is recent and unchanged (reduces table churn from WS + 5-min polling)
                    skip_balance_write = False
                    cursor.execute("""
                        SELECT balance, exposure, positions, portfolio, bankroll_current,
                               EXTRACT(EPOCH FROM (NOW() - created_at)) AS age_seconds
                        FROM users.account_balance_0001 ORDER BY id DESC LIMIT 1
                    """)
                    last_row = cursor.fetchone()
                    if last_row:
                        last_balance, last_exposure, last_positions, last_portfolio, last_bankroll, age_seconds = last_row
                        if age_seconds is not None and age_seconds < 120 and (
                            int(last_balance or 0) == int(balance_amount or 0)
                            and int(last_exposure or 0) == int(total_exposure or 0)
                            and int(last_positions or 0) == positions_value
                            and int(last_portfolio or 0) == portfolio_value
                            and int(last_bankroll or 0) == bankroll_current
                        ):
                            skip_balance_write = True
                            logger.debug("Balance unchanged, last write %.0fs ago; skipping duplicate row", age_seconds)

                    if skip_balance_write:
                        # Subaccounts may have been updated; commit those, but no new balance row or notifies
                        pg_conn.commit()
                    if not skip_balance_write:
                        # Snapshot MTB state at the same time we write account_balance_0001
                        mtb_balance, mtb_base = _get_mtb_snapshot_from_subaccounts(cursor)
                        cursor.execute("""
                            INSERT INTO users.account_balance_0001 (
                                balance, exposure, positions, portfolio, bankroll_current,
                                portfolio_value, timestamp, master_trading_bankroll, mtb_base_value
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            balance_amount, total_exposure, positions_value, portfolio_value,
                            bankroll_current, portfolio_value_raw, current_timestamp,
                            mtb_balance, mtb_base
                        ))
                        pg_conn.commit()
                        logger.debug(
                            "Balance written to users.account_balance_0001 (portfolio=%s, bankroll_current=%s, mtb=%s, mtb_base_value=%s)",
                            portfolio_value, bankroll_current, mtb_balance, mtb_base
                        )

                        # Notify frontend of account balance change
                        notify_frontend_db_change("account_balance", {
                            "balance": balance_amount,
                            "exposure": total_exposure,
                            "positions": positions_value,
                            "portfolio": portfolio_value,
                            "portfolio_value_raw": portfolio_value_raw,
                            "total_portfolio": total_portfolio_value
                        })

                        # Notify monitor_manager of bankroll update (pass drawdown flag so it can set all auto_trade=FALSE)
                        notify_monitor_manager(bankroll_stepped_down=bankroll_stepped_down)
                    # Sync Kalshi v1 account/history into users.account_history_0001 (simple UPDATE-then-INSERT, no ON CONFLICT)
                    cursor.execute("SELECT kalshi_user_id FROM users.user_info_0001 WHERE user_no = '0001'")
                    kalshi_user_row = cursor.fetchone()
                    kalshi_user_id_for_history = (kalshi_user_row[0] or "").strip() if kalshi_user_row and kalshi_user_row[0] else None
                if pg_conn and kalshi_user_id_for_history:
                    try:
                        n_upserted, sync_err, new_deposit_amounts, new_withdrawal_amounts = sync_account_history(pg_conn, kalshi_user_id_for_history)
                        if sync_err:
                            logger.warning("Account history sync failed: %s", sync_err)
                        else:
                            logger.debug("Account history: %s entries synced to users.account_history_0001", n_upserted)
                        if new_deposit_amounts:
                            with pg_conn.cursor() as cur:
                                for amount_net in new_deposit_amounts:
                                    cur.execute("UPDATE users.subaccounts_0001 SET balance = balance + %s WHERE subaccount = 'Cash Transfer'", (amount_net,))
                                cur.execute("SELECT portfolio FROM users.account_balance_0001 ORDER BY id DESC LIMIT 1")
                                row = cur.fetchone()
                                if row and row[0] is not None:
                                    cur.execute("UPDATE users.subaccounts_0001 SET balance = %s WHERE subaccount = 'PRIMARY'", (int(row[0]),))
                            pg_conn.commit()
                            notify_frontend_db_change("subaccounts", {"source": "external_deposit"})
                            notify_frontend_db_change("transfers", {"source": "external_deposit"})
                            notify_monitor_manager()
                            logger.debug("New deposit(s) applied to Cash Transfer + PRIMARY: %s cents total", sum(new_deposit_amounts))
                        if new_withdrawal_amounts:
                            with pg_conn.cursor() as cur:
                                for amount_net in new_withdrawal_amounts:
                                    cur.execute("SELECT COALESCE(balance, 0) FROM users.subaccounts_0001 WHERE subaccount = 'Cash Transfer'")
                                    cash_balance = (cur.fetchone() or (0,))[0]
                                    amount_subtracted = min(amount_net, cash_balance)
                                    new_cash = cash_balance - amount_subtracted
                                    cur.execute("UPDATE users.subaccounts_0001 SET balance = %s WHERE subaccount = 'Cash Transfer'", (new_cash,))
                                cur.execute("SELECT portfolio FROM users.account_balance_0001 ORDER BY id DESC LIMIT 1")
                                row = cur.fetchone()
                                if row and row[0] is not None:
                                    cur.execute("UPDATE users.subaccounts_0001 SET balance = %s WHERE subaccount = 'PRIMARY'", (int(row[0]),))
                            pg_conn.commit()
                            notify_frontend_db_change("subaccounts", {"source": "external_withdrawal"})
                            notify_frontend_db_change("transfers", {"source": "external_withdrawal"})
                            notify_monitor_manager()
                            logger.debug("New withdrawal(s) applied: Cash Transfer reduced (PRIMARY adjusted), %s cents total", sum(new_withdrawal_amounts))
                    except Exception as sync_exc:
                        logger.warning("Account history sync error: %s", sync_exc)
                if pg_conn:
                    pg_conn.close()
            else:
                logger.warning("Skipping PostgreSQL write - no connection available")
        except Exception as pg_err:
            logger.error("Failed to write balance to PostgreSQL: %s", pg_err)

    except Exception as e:
        logger.error("Failed to fetch balance: %s", e)
        return
    logger.info("Balance sync OK")


# --- New sync functions for positions, fills, settlements using PostgreSQL ---


def _notify_trade_manager_positions_updated(payload):
    """POST to trade_manager /api/positions_updated with retries. Handles connection refused at startup (trade_manager may not be listening yet)."""
    trade_manager_port = get_port("trade_manager")
    url = f"http://localhost:{trade_manager_port}/api/positions_updated"
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.debug("Notified trade_manager about %s", payload.get("database", "update"))
                return
            logger.warning("trade_manager returned %s on attempt %s/%s", response.status_code, attempt + 1, max_attempts)
        except Exception as e:
            if attempt < max_attempts - 1:
                delay = 1 * (2 ** attempt)
                logger.debug("trade_manager unreachable (attempt %s/%s): %s; retry in %ss", attempt + 1, max_attempts, e, delay)
                time.sleep(delay)
            else:
                logger.warning("Failed to notify trade_manager after %s attempts: %s", max_attempts, e)


def sync_positions():
    # PostgreSQL only - no legacy database paths needed
    logger.debug("Syncing recent positions...")

    def make_rest_api_call():
        """Make the REST API call for positions"""
        method = "GET"
        path = "/portfolio/positions"
        
        # Single request for recent positions (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        logger.debug("Requesting recent positions: %s", url)

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
            if "error" in data:
                logger.warning("API error: %s", data["error"])
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
            
            logger.debug("Retrieved %s market and %s event positions; after filtering: %s market, %s event",
                         len(all_market_positions), len(all_event_positions), len(filtered_market_positions), len(filtered_event_positions))

            # Use filtered positions for processing
            all_market_positions = filtered_market_positions
            all_event_positions = filtered_event_positions
            
            return {
                "market_positions": all_market_positions,
                "event_positions": all_event_positions,
            }
            
        except Exception as e:
            logger.debug("Failed to fetch positions: %s", e)
            raise e  # Re-raise to trigger retry logic

    # Use retry logic with WebSocket fallback
    try:
        # Note: This is a synchronous function, so we can't use async retry here
        # We'll implement the retry logic directly
        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                logger.debug("REST API attempt %s/%s", attempt + 1, max_retries)
                data = make_rest_api_call()
                if data is not None:
                    logger.debug("REST API successful on attempt %s", attempt + 1)
                    break
                else:
                    logger.debug("REST API returned None on attempt %s", attempt + 1)
            except Exception as e:
                logger.debug("REST API attempt %s failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    logger.debug("Waiting %ss before retry", delay)
                    time.sleep(delay)
                else:
                    logger.warning("All REST API attempts failed, using WebSocket fallback")
                    data = use_websocket_fallback_for_positions()
                    if data is None:
                        logger.error("WebSocket fallback also failed, aborting positions sync")
                        return
        else:
            # All retries exhausted
            logger.warning("All REST API attempts failed, using WebSocket fallback")
            data = use_websocket_fallback_for_positions()
            if data is None:
                logger.error("WebSocket fallback also failed, aborting positions sync")
                return

    except Exception as e:
        logger.error("Error in positions sync: %s", e)
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
        logger.error("Failed to hash positions snapshot: %s", e)
        return

    if snapshot_hash == LAST_POSITIONS_HASH:
        logger.debug("No changes in positions — skipping write")
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
                            (ticker, last_updated_ts, raw_json,
                             total_traded_dollars, market_exposure_dollars, realized_pnl_dollars, fees_paid_dollars,
                             total_traded_fp, position_fp)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (ticker, last_updated_ts, raw_json,
                              total_traded_dollars, market_exposure_dollars, realized_pnl_dollars, fees_paid_dollars,
                              total_traded_fp, position_fp))
                    except Exception as e:
                        logger.error("Failed to insert position %s to PostgreSQL: %s", p.get("ticker"), e)

                pg_conn.commit()
                logger.debug("All positions written to PostgreSQL users.positions_0001")
            pg_conn.close()
        else:
            logger.warning("Skipping PostgreSQL write - no connection available")
    except Exception as pg_err:
        logger.error("Failed to write positions to PostgreSQL: %s", pg_err)

    # JSON writing removed - PostgreSQL only
    notify_frontend_db_change("positions", {"market_positions": len(all_market_positions), "event_positions": len(all_event_positions)})
    
    # Notify trade_manager about positions update (retry on connection refused at startup)
    _notify_trade_manager_positions_updated({"database": "positions"})

    logger.info("Positions sync OK")


def sync_fills():
    # PostgreSQL only - no legacy database paths needed
    logger.debug("Syncing recent fills...")
    
    def make_rest_api_call():
        """Make the REST API call for fills"""
        method = "GET"
        path = "/portfolio/fills"
        
        # Single request for recent fills (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        logger.debug("Requesting recent fills: %s", url)

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
            logger.debug("Response keys: %s", list(data.keys()))
            if "error" in data:
                logger.warning("API error: %s", data["error"])
                return None
            
            all_fills = data.get("fills", [])
            logger.debug("Retrieved %s recent fills", len(all_fills))
            
            return data
            
        except Exception as e:
            logger.debug("Failed to fetch fills: %s", e)
            raise e  # Re-raise to trigger retry logic
    
    # Use retry logic
    try:
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                logger.debug("REST API attempt %s/%s", attempt + 1, max_retries)
                data = make_rest_api_call()
                if data is not None:
                    logger.debug("REST API successful on attempt %s", attempt + 1)
                    break
                else:
                    logger.debug("REST API returned None on attempt %s", attempt + 1)
            except Exception as e:
                logger.debug("REST API attempt %s failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    logger.debug("Waiting %ss before retry", delay)
                    time.sleep(delay)
                else:
                    logger.warning("All REST API attempts failed, using WebSocket fallback")
                    data = use_websocket_fallback_for_fills()
                    if data is None:
                        logger.error("WebSocket fallback also failed, aborting fills sync")
                        return
        else:
            # All retries exhausted
            logger.warning("All REST API attempts failed, using WebSocket fallback")
            data = use_websocket_fallback_for_fills()
            if data is None:
                logger.error("WebSocket fallback also failed, aborting fills sync")
                return

    except Exception as e:
        logger.error("Error in fills sync: %s", e)
        return

    # Process the data (either from REST API or WebSocket fallback)
    all_fills = data.get("fills", [])

    # WebSocket triggers ensure we only poll when there's new data, so always write

    if all_fills:
        latest_time = all_fills[0].get("created_time")
        oldest_time = all_fills[-1].get("created_time")
        logger.debug("Fills range — newest: %s, oldest: %s, total: %s", latest_time, oldest_time, len(all_fills))
        
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
                        count_fp = _fp_to_numeric(fill.get("count_fp"))
                        # API: yes_price_dollars / no_price_dollars (Kalshi changelog Mar 2026); fallback to _fixed during rollout
                        yes_price_dollars = fill.get("yes_price_dollars") or fill.get("yes_price_fixed")
                        no_price_dollars = fill.get("no_price_dollars") or fill.get("no_price_fixed")
                        is_taker = bool(fill.get("is_taker")) if fill.get("is_taker") is not None else None
                        created_time = fill.get("created_time")
                        raw_json = json.dumps(fill)

                        try:
                            cursor.execute("""
                                INSERT INTO users.fills_0001
                                (trade_id, ticker, order_id, side, action, count_fp, yes_price_dollars, no_price_dollars, is_taker, created_time, raw_json)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (trade_id) DO NOTHING
                            """, (trade_id, ticker, order_id, side, action, count_fp, yes_price_dollars, no_price_dollars, is_taker, created_time, raw_json))
                            pg_new_count += 1
                        except Exception as e:
                            logger.error("Failed to insert fill %s to PostgreSQL: %s", trade_id, e)

                    pg_conn.commit()
                    logger.debug("%s fills written to PostgreSQL users.fills_0001", pg_new_count)
                pg_conn.close()
            else:
                logger.warning("Skipping PostgreSQL write - no connection available")
        except Exception as pg_err:
            logger.error("Failed to write fills to PostgreSQL: %s", pg_err)

        logger.debug("Fills written to PostgreSQL only")
    else:
        logger.debug("API returned zero fills")

    notify_frontend_db_change("fills", {"fills": len(all_fills)})

    _notify_trade_manager_positions_updated({"database": "fills"})

    logger.info("Fills sync OK")


def sync_settlements():
    # PostgreSQL only - no legacy database paths needed
    logger.debug("Syncing recent settlements...")

    def make_rest_api_call():
        """Make the REST API call for settlements"""
        method = "GET"
        path = "/portfolio/settlements"
        
        # Single request for recent settlements (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        logger.debug("Requesting recent settlements: %s", url)

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
            logger.debug("Response keys: %s", list(data.keys()))
            if "error" in data:
                logger.warning("API error: %s", data["error"])
                return None

            all_settlements = data.get("settlements", [])
            logger.debug("Retrieved %s recent settlements", len(all_settlements))

            return data

        except Exception as e:
            logger.debug("Failed to fetch settlements: %s", e)
            raise e  # Re-raise to trigger retry logic
    
    # Use retry logic
    try:
        max_retries = 3
        base_delay = 1
        
        for attempt in range(max_retries):
            try:
                logger.debug("REST API attempt %s/%s", attempt + 1, max_retries)
                data = make_rest_api_call()
                if data is not None:
                    logger.debug("REST API successful on attempt %s", attempt + 1)
                    break
                else:
                    logger.debug("REST API returned None on attempt %s", attempt + 1)
            except Exception as e:
                logger.debug("REST API attempt %s failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    logger.debug("Waiting %ss before retry", delay)
                    time.sleep(delay)
                else:
                    logger.warning("All REST API attempts failed for settlements")
                    return
        else:
            # All retries exhausted
            logger.warning("All REST API attempts failed for settlements")
            return

    except Exception as e:
        logger.error("Error in settlements sync: %s", e)
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
                        revenue DECIMAL(10,2),
                        settled_time TEXT,
                        raw_json TEXT,
                        yes_count_fp NUMERIC(12,2),
                        no_count_fp NUMERIC(12,2),
                        yes_total_cost_dollars DECIMAL(10,2),
                        no_total_cost_dollars DECIMAL(10,2),
                        UNIQUE(ticker, settled_time)
                    )
                """)
                
                for settlement in all_settlements:
                    try:
                        ticker = settlement.get("ticker")
                        market_result = settlement.get("market_result")
                        yes_count_fp = _fp_to_numeric(settlement.get("yes_count_fp"))
                        no_count_fp = _fp_to_numeric(settlement.get("no_count_fp"))
                        revenue = settlement.get("revenue")
                        settled_time = settlement.get("settled_time")
                        raw_json = json.dumps(settlement)

                        # API: yes_total_cost_dollars / no_total_cost_dollars (Kalshi changelog Mar 2026); fallback to cent fields during rollout
                        yes_total_cost_dollars = settlement.get("yes_total_cost_dollars")
                        if yes_total_cost_dollars is None and settlement.get("yes_total_cost") is not None:
                            yes_total_cost_dollars = float(settlement["yes_total_cost"]) / 100
                        no_total_cost_dollars = settlement.get("no_total_cost_dollars")
                        if no_total_cost_dollars is None and settlement.get("no_total_cost") is not None:
                            no_total_cost_dollars = float(settlement["no_total_cost"]) / 100

                        try:
                            revenue = float(revenue) / 100 if revenue is not None else None
                            if yes_total_cost_dollars is not None and not isinstance(yes_total_cost_dollars, (int, float)):
                                yes_total_cost_dollars = float(yes_total_cost_dollars)
                            if no_total_cost_dollars is not None and not isinstance(no_total_cost_dollars, (int, float)):
                                no_total_cost_dollars = float(no_total_cost_dollars)
                        except Exception as e:
                            logger.warning("Error formatting cost fields for %s at %s: %s", ticker, settled_time, e)
                            continue

                        cursor.execute("""
                            INSERT INTO users.settlements_0001
                            (ticker, market_result, revenue, settled_time, raw_json,
                             yes_count_fp, no_count_fp, yes_total_cost_dollars, no_total_cost_dollars)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (ticker, settled_time) DO NOTHING
                        """, (ticker, market_result, revenue, settled_time, raw_json,
                              yes_count_fp, no_count_fp, yes_total_cost_dollars, no_total_cost_dollars))
                    except Exception as e:
                        logger.error("Failed to insert settlement %s to PostgreSQL: %s", settlement.get("ticker"), e)

                pg_conn.commit()
                logger.debug("All settlements written to PostgreSQL users.settlements_0001")
            pg_conn.close()
        else:
            logger.warning("Skipping PostgreSQL write - no connection available")
    except Exception as pg_err:
        logger.error("Failed to write settlements to PostgreSQL: %s", pg_err)

    logger.info("Settlements sync OK")
    # JSON writing removed - PostgreSQL only
    notify_frontend_db_change("settlements", {"settlements": len(all_settlements)})


def sync_orders():
    # PostgreSQL only - no legacy database paths needed
    logger.debug("Syncing recent orders...")

    def make_rest_api_call():
        """Make the REST API call for orders"""
        method = "GET"
        path = "/portfolio/orders"
        
        # Single request for recent orders (no pagination loop)
        timestamp = str(int(time.time() * 1000))
        query = "?limit=50"  # Reduced limit for WebSocket implementation
        url = f"{get_base_url()}{path}{query}"
        logger.debug("Requesting recent orders: %s", url)

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
            logger.debug("Response keys: %s", list(data.keys()))
            if "error" in data:
                logger.warning("API error: %s", data["error"])
                return None

            all_orders = data.get("orders", [])
            logger.debug("Retrieved %s recent orders", len(all_orders))

            return data

        except Exception as e:
            logger.debug("Failed to fetch orders: %s", e)
            raise e  # Re-raise to trigger retry logic

    # Use retry logic
    try:
        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                logger.debug("REST API attempt %s/%s", attempt + 1, max_retries)
                data = make_rest_api_call()
                if data is not None:
                    logger.debug("REST API successful on attempt %s", attempt + 1)
                    break
                else:
                    logger.debug("REST API returned None on attempt %s", attempt + 1)
            except Exception as e:
                logger.debug("REST API attempt %s failed: %s", attempt + 1, e)

                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # exponential backoff
                    logger.debug("Waiting %ss before retry", delay)
                    time.sleep(delay)
                else:
                    logger.warning("All REST API attempts failed for orders")
                    return
        else:
            # All retries exhausted
            logger.warning("All REST API attempts failed for orders")
            return

    except Exception as e:
        logger.error("Error in orders sync: %s", e)
        return

    # Process the data
    all_orders = data.get("orders", [])

    # WebSocket triggers ensure we only poll when there's new data, so always write

    if all_orders:
        latest_time = all_orders[0].get("created_time")
        oldest_time = all_orders[-1].get("created_time")
        logger.debug("Orders range — newest: %s, oldest: %s, total: %s", latest_time, oldest_time, len(all_orders))
    else:
        logger.debug("API returned zero orders")
    
    # ------------------------------------------------------------
    # Write to PostgreSQL with DELTA CHECKING and UPDATES
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                # Get existing orders with key fields for delta comparison (use _fp for counts and *_dollars for prices/fees)
                cursor.execute("""
                    SELECT order_id, status, fill_count_fp, remaining_count_fp,
                           last_update_time,
                           taker_fees_dollars, maker_fees_dollars,
                           taker_fill_cost_dollars, maker_fill_cost_dollars
                    FROM users.orders_0001
                """)
                existing_orders = {row[0]: {
                    'status': row[1],
                    'fill_count_fp': row[2],
                    'remaining_count_fp': row[3],
                    'last_update_time': row[4],
                    'taker_fees_dollars': row[5],
                    'maker_fees_dollars': row[6],
                    'taker_fill_cost_dollars': row[7],
                    'maker_fill_cost_dollars': row[8],
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

                        # Fees and fill cost now come from *_dollars fields post fixed-point migration.
                        api_taker_fees_dollars = order.get("taker_fees_dollars")
                        api_maker_fees_dollars = order.get("maker_fees_dollars")
                        api_taker_fill_cost_dollars = order.get("taker_fill_cost_dollars")
                        api_maker_fill_cost_dollars = order.get("maker_fill_cost_dollars")

                        if (existing['status'] != order.get("status") or
                            existing['fill_count_fp'] != api_fill_fp or
                            existing['remaining_count_fp'] != api_remaining_fp or
                            existing['last_update_time'] != order.get("last_update_time") or
                            existing['taker_fees_dollars'] != api_taker_fees_dollars or
                            existing['maker_fees_dollars'] != api_maker_fees_dollars or
                            existing['taker_fill_cost_dollars'] != api_taker_fill_cost_dollars or
                            existing['maker_fill_cost_dollars'] != api_maker_fill_cost_dollars):
                            needs_update = True
                        
                        if needs_update:
                            try:
                                # UPDATE existing order with new data (no legacy integer columns)
                                cursor.execute("""
                                    UPDATE users.orders_0001 SET
                                        status = %s,
                                        fill_count_fp = %s, remaining_count_fp = %s,
                                        last_update_time = %s,
                                        taker_fees_dollars = %s, maker_fees_dollars = %s,
                                        taker_fill_cost_dollars = %s, maker_fill_cost_dollars = %s,
                                        queue_position = %s,
                                        raw_json = %s, updated_at = CURRENT_TIMESTAMP
                                    WHERE order_id = %s
                                """, (
                                    order.get("status"),
                                    api_fill_fp,
                                    api_remaining_fp,
                                    order.get("last_update_time"),
                                    api_taker_fees_dollars,
                                    api_maker_fees_dollars,
                                    api_taker_fill_cost_dollars,
                                    api_maker_fill_cost_dollars,
                                    order.get("queue_position"),
                                    json.dumps(order),
                                    order_id
                                ))
                                pg_updated_count += 1
                                logger.debug("Updated order %s: status=%s, fills=%s", order_id, order.get("status"), order.get("fill_count"))
                            except Exception as e:
                                logger.error("Failed to update order %s: %s", order_id, e)
                    else:
                        # INSERT new order
                        try:
                            cursor.execute("""
                                INSERT INTO users.orders_0001
                                (order_id, user_id, ticker, status, action, side, type, yes_price_dollars, no_price_dollars,
                                 initial_count_fp, remaining_count_fp, fill_count_fp,
                                 created_time, expiration_time, last_update_time, client_order_id, order_group_id, queue_position,
                                 self_trade_prevention_type,
                                 maker_fees_dollars, taker_fees_dollars, maker_fill_cost_dollars, taker_fill_cost_dollars,
                                 raw_json)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                        %s, %s, %s,
                                        %s, %s, %s, %s, %s, %s, %s,
                                        %s, %s, %s, %s, %s)
                            """, (
                                order_id,
                                order.get("user_id"),
                                order.get("ticker"),
                                order.get("status"),
                                order.get("action"),
                                order.get("side"),
                                order.get("type"),
                                order.get("yes_price_dollars"),
                                order.get("no_price_dollars"),
                                _fp_to_numeric(order.get("initial_count_fp")),
                                _fp_to_numeric(order.get("remaining_count_fp")),
                                _fp_to_numeric(order.get("fill_count_fp")),
                                order.get("created_time"),
                                order.get("expiration_time"),
                                order.get("last_update_time"),
                                order.get("client_order_id"),
                                order.get("order_group_id"),
                                order.get("queue_position"),
                                order.get("self_trade_prevention_type"),
                                order.get("maker_fees_dollars"),
                                order.get("taker_fees_dollars"),
                                order.get("maker_fill_cost_dollars"),
                                order.get("taker_fill_cost_dollars"),
                                json.dumps(order)
                            ))
                            pg_new_count += 1
                            logger.debug("Inserted new order %s: status=%s", order_id, order.get("status"))
                        except Exception as e:
                            logger.error("Failed to insert order %s: %s", order_id, e)

                pg_conn.commit()
                logger.debug("Orders sync complete: %s new, %s updated in PostgreSQL users.orders_0001", pg_new_count, pg_updated_count)
            pg_conn.close()
        else:
            logger.warning("Skipping PostgreSQL write - no connection available")
    except Exception as pg_err:
        logger.error("Failed to write orders to PostgreSQL: %s", pg_err)

    logger.debug("Orders written to PostgreSQL only")

    notify_frontend_db_change("orders", {"orders": len(all_orders)})

    _notify_trade_manager_positions_updated({"database": "orders"})

    logger.info("Orders sync OK")


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
            logger.error("No %s credentials found at %s", account_mode, cred_dir)
            return None
        
        env_vars = dotenv_values(cred_dir / ".env")
        key_path = cred_dir / "kalshi.pem"
        
        if not key_path.exists():
            logger.error("No private key file found at %s", key_path)
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
                logger.error("No credentials available")
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
            
            logger.info("Connecting to Kalshi User Fills WebSocket (mode=%s)", get_account_mode())

            # Connect with authentication headers
            self.websocket = await websockets.connect(
                WS_URL,
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=10
            )
            
            logger.info("Connected to Kalshi User Fills WebSocket API")
            self.reconnect_attempts = 0  # Reset reconnect attempts on successful connection
            return True

        except Exception as e:
            logger.error("Failed to connect to User Fills WebSocket: %s", e)
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
            logger.debug("Sent market positions subscription")

            # Wait for subscription confirmation
            response = await asyncio.wait_for(self.websocket.recv(), timeout=10)
            response_data = json.loads(response)
            
            if response_data.get("type") == "subscribed":
                self.subscription_id = response_data.get("msg", {}).get("sid")
                logger.info("Subscribed to market positions (sid=%s)", self.subscription_id)
                return True
            else:
                logger.error("Market positions subscription failed: %s", response_data)
                return False

        except Exception as e:
            logger.error("Failed to subscribe to market positions: %s", e)
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
                
                logger.debug("Market position update: ticker=%s position=%s", position_data.get("market_ticker"), position_data.get("position"))

                # WebSocket ONLY as trigger - NO direct database writes
                logger.debug("Position change detected, triggering full REST API polling cycle")
                await self.trigger_full_polling_cycle()
                
            elif data.get("type") == "subscribed":
                logger.debug("Subscription confirmed: %s", data)

            elif data.get("type") == "error":
                logger.warning("WebSocket error: %s", data)

            else:
                logger.debug("WebSocket message: type=%s", data.get("type"))

        except Exception as e:
            logger.error("Error handling message: %s", e)
            logger.debug("Raw message: %s", message)
    
    async def trigger_full_polling_cycle(self):
        """Trigger a complete polling cycle for all endpoints when position changes"""
        try:
            logger.debug("Starting triggered polling cycle")

            # Run all sync functions asynchronously - balance LAST so it can reference latest positions data
            await self.async_sync_positions()
            await self.async_sync_fills()
            await self.async_sync_orders()
            await self.async_sync_settlements()
            await self.async_sync_balance()

            logger.debug("Triggered polling cycle completed")

        except Exception as e:
            logger.error("Error in triggered polling cycle: %s", e)
    
    async def async_sync_balance(self):
        """Async version of sync_balance"""
        try:
            logger.debug("Triggered balance sync")
            sync_balance()
        except Exception as e:
            logger.error("Error in triggered balance sync: %s", e)

    async def async_sync_positions(self):
        """Async version of sync_positions"""
        try:
            logger.debug("Triggered positions sync")
            sync_positions()
        except Exception as e:
            logger.error("Error in triggered positions sync: %s", e)

    async def async_sync_fills(self):
        """Async version of sync_fills"""
        try:
            logger.debug("Triggered fills sync")
            sync_fills()
        except Exception as e:
            logger.error("Error in triggered fills sync: %s", e)

    async def async_sync_orders(self):
        """Async version of sync_orders"""
        try:
            logger.debug("Triggered orders sync")
            sync_orders()
        except Exception as e:
            logger.error("Error in triggered orders sync: %s", e)

    async def async_sync_settlements(self):
        """Async version of sync_settlements"""
        try:
            logger.debug("Triggered settlements sync")
            sync_settlements()
        except Exception as e:
            logger.error("Error in triggered settlements sync: %s", e)
    
    # REMOVED: write_market_position_to_db function
    # WebSocket now ONLY serves as a trigger for REST API polling
    # All database writes happen through the standardized REST API sync functions
    

    
    async def store_market_lifecycle(self, lifecycle_data):
        """Store market lifecycle data (placeholder for future use)"""
        try:
            # This could be used to track market state changes
            # For now, just log that we received it
            logger.debug("Market lifecycle data received for %s", lifecycle_data.get("market_ticker"))
        except Exception as e:
            logger.error("Error storing market lifecycle: %s", e)

    async def store_event_lifecycle(self, event_data):
        """Store event lifecycle data (placeholder for future use)"""
        try:
            logger.debug("Event lifecycle data received for %s", event_data.get("event_ticker"))
        except Exception as e:
            logger.error("Error storing event lifecycle: %s", e)

    async def periodic_polling_task(self):
        """Periodic polling task that runs every 5 minutes"""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes = 300 seconds
                logger.info("heartbeat")
                logger.debug("5-minute periodic polling triggered")
                await self.trigger_full_polling_cycle()
            except Exception as e:
                logger.error("Error in periodic polling task: %s", e)

    async def run_websocket(self):
        """Main WebSocket run loop - Hybrid approach: WebSocket triggers + periodic polling"""
        logger.info("Starting Kalshi Hybrid WebSocket/Polling Sync")

        # Start periodic polling task in the background
        periodic_task = asyncio.create_task(self.periodic_polling_task())
        logger.debug("Started 5-minute periodic polling task")

        while True:
            try:
                # Connect to WebSocket
                if not await self.connect():
                    logger.warning("Failed to connect, retrying in 5 seconds")
                    await asyncio.sleep(5)
                    continue
                
                # Subscribe to market positions
                if not await self.subscribe_to_market_positions():
                    logger.warning("Failed to subscribe, retrying in 5 seconds")
                    await asyncio.sleep(5)
                    continue

                logger.info("Listening for market position notifications (hybrid: WS triggers + 5-min polling)")
                
                # Listen for messages
                async for message in self.websocket:
                    await self.handle_market_position_message(message)
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed, attempting to reconnect")
                if self.websocket:
                    await self.websocket.close()
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error("WebSocket error: %s", e)
                await asyncio.sleep(5)


def scheduled_balance_check():
    """Scheduled task to run balance check at 1AM every morning"""
    logger.debug("Scheduled 1AM EST balance check triggered")
    try:
        sync_balance()
    except Exception as e:
        logger.error("Error in scheduled balance check: %s", e)


def hourly_balance_check():
    """Scheduled task to run balance check every hour on the hour"""
    logger.debug("Hourly balance check triggered")
    try:
        sync_balance()
    except Exception as e:
        logger.error("Error in hourly balance check: %s", e)


def run_scheduler():
    """Run the scheduler in a separate thread"""
    # Schedule for 1AM Eastern Time
    schedule.every().day.at("01:00").do(scheduled_balance_check)
    # Schedule hourly balance checks (every hour on the hour)
    schedule.every().hour.do(hourly_balance_check)
    logger.debug("Scheduler started: daily 1AM EST + hourly balance checks")
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def _wait_for_trade_manager(timeout_sec=30, poll_interval=1):
    """Block until trade_manager is listening so initial baseline sync never hits connection refused. Required for MASTER_RESTART ordering."""
    import socket
    port = get_port("trade_manager")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("127.0.0.1", port))
            s.close()
            logger.debug("trade_manager reachable on port %s", port)
            return
        except Exception:
            time.sleep(poll_interval)
    logger.warning("trade_manager not reachable after %ss; proceeding with initial sync anyway (retries will apply)", timeout_sec)


def main():
    logger.info("Kalshi Account Hybrid WebSocket/Polling Supervisor starting")

    _wait_for_trade_manager()

    # Initial sync to establish baseline data (one-time only)
    logger.info("Performing initial baseline data sync")
    sync_positions()
    sync_fills()
    sync_orders()
    sync_settlements()
    sync_balance()  # Update balance LAST so it can reference latest positions data

    logger.info("Initial baseline sync complete; starting hybrid mode (WS triggers + 5-min polling)")

    # Start scheduler in a separate thread
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Create and run WebSocket sync
    websocket_sync = KalshiWebSocketSync()

    try:
        asyncio.run(websocket_sync.run_websocket())
    except KeyboardInterrupt:
        logger.info("Hybrid WebSocket/Polling supervisor stopped by user")
    except Exception as e:
        logger.error("Error in hybrid WebSocket/Polling supervisor: %s", e)

if __name__ == "__main__":
    main()