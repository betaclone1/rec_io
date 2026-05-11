#!/usr/bin/env python3
"""
Kalshi Account Sync Hybrid WebSocket/Polling Version
Real-time account data synchronization using WebSocket triggers + REST API polling

HYBRID APPROACH:
1. Initial sync on startup (one-time polling cycle)
2. WebSocket: market_positions, fill, user_orders (ACCOUNT_SYNC_WS_CHANNELS)
3. Debounced per-resource REST syncs (ACCOUNT_SYNC_DEBOUNCE_MS); no direct DB writes from WS payloads
4. Quick periodic: settlements + balance (ACCOUNT_SYNC_QUICK_PERIODIC_SEC, default 300s)
5. Full reconcile: all five syncs (ACCOUNT_SYNC_FULL_RECONCILE_SEC, default 900s)
6. Hourly balance checks on the hour + daily 1AM balance check

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
from backend.account_mode import get_account_mode  # always prod; kept for logging compatibility
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
from psycopg2 import sql as psql
from psycopg2.extras import RealDictCursor
import schedule
from decimal import Decimal
import logging
from typing import Optional

# Add project root to path for imports
import sys
import os
from backend.util.paths import get_project_root
sys.path.insert(0, get_project_root())

from backend.util.paths import get_kalshi_data_dir, get_accounts_data_dir, ensure_data_dirs, get_kalshi_credentials_dir
from backend.core.time_eastern import utc_now_iso_z, now_est

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


def _account_sync_debounce_sec() -> float:
    try:
        return max(0.05, float(os.getenv("ACCOUNT_SYNC_DEBOUNCE_MS", "400")) / 1000.0)
    except ValueError:
        return 0.4


def _account_sync_quick_periodic_sec() -> int:
    try:
        return max(60, int(os.getenv("ACCOUNT_SYNC_QUICK_PERIODIC_SEC", "300")))
    except ValueError:
        return 300


def _account_sync_full_reconcile_sec() -> int:
    try:
        return max(120, int(os.getenv("ACCOUNT_SYNC_FULL_RECONCILE_SEC", "900")))
    except ValueError:
        return 900


def _account_sync_poc_log_max() -> int:
    try:
        return max(0, int(os.getenv("ACCOUNT_SYNC_POC_LOG_MAX", "20")))
    except ValueError:
        return 20


def _account_sync_ws_channels():
    raw = os.getenv("ACCOUNT_SYNC_WS_CHANNELS", "market_positions,fill,user_orders")
    return [c.strip() for c in raw.split(",") if c.strip()]


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
        "last_updated_ts": LATEST_WEBSOCKET_TIMESTAMP or utc_now_iso_z()
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
        "created_time": LATEST_WEBSOCKET_TIMESTAMP or utc_now_iso_z(),
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

KALSHI_TRADE_API_V2 = "https://api.elections.kalshi.com/trade-api/v2"


def get_base_url():
    return KALSHI_TRADE_API_V2


logger.info("Started kalshi_account_sync (base_url=%s)", get_base_url())

from backend.util.paths import get_kalshi_credentials_dir

CREDENTIALS_DIR = Path(get_kalshi_credentials_dir()) / "prod"
ENV_VARS = dotenv_values(CREDENTIALS_DIR / ".env")

KEY_ID = ENV_VARS.get("KALSHI_API_KEY_ID")
KEY_PATH = CREDENTIALS_DIR / "kalshi.pem"

# PostgreSQL connection function
def get_postgresql_connection():
    """Get a connection to the PostgreSQL database (uses centralized config)."""
    from backend.core.config.database import get_postgresql_connection as _get_pg
    return _get_pg()


def _kas_process_user_no() -> str:
    from backend.core.tenant_context import process_tenant_context

    return process_tenant_context().user_no


def _kalshi_user_id_for_history() -> Optional[str]:
    try:
        from backend.core.config.database import get_system_postgresql_connection

        sconn = get_system_postgresql_connection()
        if not sconn:
            return None
        try:
            with sconn.cursor() as sc:
                sc.execute(
                    """
                    SELECT kalshi_user_id FROM system.master_users
                    WHERE LPAD(TRIM(user_no::text), 4, '0') = %s
                    LIMIT 1
                    """,
                    (_kas_process_user_no(),),
                )
                row = sc.fetchone()
            return (row[0] or "").strip() if row and row[0] else None
        finally:
            sconn.close()
    except Exception:
        return None


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
        import requests
        from backend.util.paths import get_host
        from backend.core.trading_redis_comms import publish_db_change_json, use_trading_redis_comms

        change_data = change_data or {}
        if use_trading_redis_comms() and publish_db_change_json(
            db_name,
            {"timestamp": time.time(), "change_data": change_data},
        ):
            logger.debug("Frontend notified of %s change (Redis)", db_name)
            return

        logger.debug(
            "Frontend notify skipped for %s: Redis unavailable and HTTP fallback removed",
            db_name,
        )

    except Exception as e:
        logger.error("Error notifying frontend: %s", e)

def notify_monitor_manager(bankroll_stepped_down=False):
    """Notify monitor_manager that bankroll has been updated. Pass bankroll_stepped_down=True when bankroll stepped down (drawdown halt on; MTB at/below configured % of prior bankroll_current)."""
    try:
        import requests
        from backend.core.port_config import get_port
        from backend.core.trading_redis_comms import (
            channel_monitor_manager,
            redis_client_optional,
            use_trading_redis_comms,
        )

        body = {"type": "bankroll_updated", "bankroll_stepped_down": bankroll_stepped_down}
        if use_trading_redis_comms():
            r = redis_client_optional()
            if r:
                try:
                    r.publish(channel_monitor_manager(), json.dumps(body))
                    logger.debug("Monitor manager notified via Redis")
                    return
                except Exception:
                    pass

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
    s = str(created_at).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        # Kalshi often returns fractional seconds with fewer than 6 digits (e.g. .26132Z).
        # datetime.fromisoformat rejects those on Python 3.10; dateutil handles them.
        try:
            from dateutil.parser import isoparse

            return isoparse(s)
        except Exception:
            return None
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
                ts_est = now_est()
            timestamp_str = ts_est.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = now_est().strftime("%Y-%m-%d %H:%M:%S")
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
    now = now_est()

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


def sync_balance():
    logger.debug("Sync attempt...")
    method = "GET"
    path = "/portfolio/balance"
    url = f"{get_base_url()}{path}"

    if not KEY_ID or not KEY_PATH.exists():
        logger.error("Missing Kalshi API credentials or PEM file")
        return

    pg_conn = None
    _slot = None
    new_deposit_amounts = []
    new_withdrawal_amounts = []
    try:
        pg_conn = get_postgresql_connection()
    except Exception as pg_err:
        logger.error("Failed to open PostgreSQL connection: %s", pg_err)
        pg_conn = None

    if pg_conn:
        try:
            from backend.core.tenant_context import process_tenant_context
            from backend.trading_mode import (
                sql_ident_qualified_table,
                subaccounts_table_for_user,
            )

            _slot = process_tenant_context().user_no
            kalshi_user_id_for_history = _kalshi_user_id_for_history()
            if kalshi_user_id_for_history:
                n_upserted, sync_err, new_deposit_amounts, new_withdrawal_amounts = sync_account_history(
                    pg_conn,
                    kalshi_user_id_for_history,
                )
                if sync_err:
                    logger.warning("Account history sync failed: %s", sync_err)
                    new_deposit_amounts = []
                    new_withdrawal_amounts = []
                else:
                    logger.debug("Account history: %s entries synced to users.account_history_0001", n_upserted)

                if new_deposit_amounts:
                    _sa_id = sql_ident_qualified_table(
                        subaccounts_table_for_user(_slot, force_live=True)
                    )
                    with pg_conn.cursor() as cur:
                        for amount_net in new_deposit_amounts:
                            cur.execute(
                                psql.SQL(
                                    "UPDATE {} SET balance = balance + %s WHERE subaccount = 'Cash Transfer'"
                                ).format(_sa_id),
                                (amount_net,),
                            )
                    pg_conn.commit()
                    logger.debug(
                        "New deposit(s) pre-applied to Cash Transfer before balance snapshot: %s cents total",
                        sum(new_deposit_amounts),
                    )
        except Exception as sync_exc:
            logger.warning("Account history pre-sync error: %s", sync_exc)
            new_deposit_amounts = []
            new_withdrawal_amounts = []
    else:
        logger.warning("Skipping account history pre-sync - no PostgreSQL connection available")

    timestamp = str(int(time.time() * 1000))  # milliseconds
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
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    current_timestamp = now_est().isoformat()

                    from backend.balance_snapshot import (
                        append_account_balance_after_withdrawal_cycle,
                        apply_balance_snapshot,
                        update_mtb_balance_from_primary_and_ct,
                    )
                    from backend.core.tenant_context import process_tenant_context
                    from backend.trading_mode import (
                        account_balance_table_for_user,
                        sql_ident_qualified_table,
                        subaccounts_table_for_user,
                        transfers_table_for_user,
                    )

                    portfolio_value = int(total_portfolio_value)
                    positions_value = int(portfolio_value_raw)
                    total_exposure = positions_value
                    if _slot is None:
                        _slot = process_tenant_context().user_no
                    _ab_fqn = account_balance_table_for_user(
                        _slot, force_live=True
                    )
                    _sa_fqn = subaccounts_table_for_user(_slot, force_live=True)

                    if new_deposit_amounts:
                        _sa_id = sql_ident_qualified_table(_sa_fqn)
                        cursor.execute(
                            psql.SQL(
                                "UPDATE {} SET balance = %s WHERE subaccount = 'PRIMARY'"
                            ).format(_sa_id),
                            (portfolio_value,),
                        )
                        update_mtb_balance_from_primary_and_ct(cursor, _sa_fqn, portfolio_value)

                    inserted, _ = apply_balance_snapshot(
                        cursor,
                        balance_amount=balance_amount,
                        portfolio_value_raw=portfolio_value_raw,
                        positions_value=positions_value,
                        total_exposure=total_exposure,
                        portfolio_value=portfolio_value,
                        account_balance_table=_ab_fqn,
                        subaccounts_table=_sa_fqn,
                        current_timestamp=current_timestamp,
                        throttle=True,
                        notify_db_name="account_balance",
                        record_internal_transfers=True,
                    )
                    pg_conn.commit()
                    if inserted:
                        logger.debug(
                            "Balance written to %s (portfolio=%s)",
                            _ab_fqn,
                            portfolio_value,
                        )
                if new_deposit_amounts:
                    notify_frontend_db_change("subaccounts", {"source": "external_deposit"})
                    notify_frontend_db_change("transfers", {"source": "external_deposit"})
                    notify_monitor_manager()
                    logger.debug("New deposit(s) applied to Cash Transfer + PRIMARY: %s cents total", sum(new_deposit_amounts))
                if new_withdrawal_amounts:
                    _sa_fqn = subaccounts_table_for_user(_slot, force_live=True)
                    _ab_fqn = account_balance_table_for_user(_slot, force_live=True)
                    _sa_id = sql_ident_qualified_table(_sa_fqn)
                    _ab_id = sql_ident_qualified_table(_ab_fqn)
                    _xfer_id = sql_ident_qualified_table(
                        transfers_table_for_user(_slot, force_live=True)
                    )
                    _ts_est = now_est().strftime("%Y-%m-%d %H:%M:%S")
                    inserted_w, stepped = False, False
                    with pg_conn.cursor() as cur:
                        for amount_net in new_withdrawal_amounts:
                            cur.execute(
                                psql.SQL(
                                    "UPDATE {} SET balance = balance - %s WHERE subaccount = 'Cash Transfer'"
                                ).format(_sa_id),
                                (int(amount_net),),
                            )
                        cur.execute(
                            psql.SQL("SELECT portfolio FROM {} ORDER BY id DESC LIMIT 1").format(
                                _ab_id
                            )
                        )
                        row = cur.fetchone()
                        primary_cents = int(row[0]) if row and row[0] is not None else None
                        if primary_cents is not None:
                            cur.execute(
                                psql.SQL(
                                    "UPDATE {} SET balance = %s WHERE subaccount = 'PRIMARY'"
                                ).format(_sa_id),
                                (primary_cents,),
                            )
                            update_mtb_balance_from_primary_and_ct(cur, _sa_fqn, primary_cents)
                        cur.execute(
                            psql.SQL(
                                "SELECT COALESCE(balance, 0) FROM {} WHERE subaccount = 'Cash Transfer'"
                            ).format(_sa_id)
                        )
                        ct_after = int((cur.fetchone() or (0,))[0])
                        if ct_after < 0:
                            topup = -ct_after
                            cur.execute(
                                psql.SQL(
                                    "UPDATE {} SET balance = balance - %s WHERE subaccount = 'Master Trading Bankroll'"
                                ).format(_sa_id),
                                (topup,),
                            )
                            cur.execute(
                                psql.SQL(
                                    "UPDATE {} SET balance = balance + %s WHERE subaccount = 'Cash Transfer'"
                                ).format(_sa_id),
                                (topup,),
                            )
                            cur.execute(
                                psql.SQL(
                                    """
                                    INSERT INTO {} (timestamp, type, "from", "to", amount, initiated)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                    """
                                ).format(_xfer_id),
                                (
                                    _ts_est,
                                    "internal",
                                    "Master Trading Bankroll",
                                    "Cash Transfer",
                                    topup,
                                    "automatic",
                                ),
                            )
                            if primary_cents is not None:
                                update_mtb_balance_from_primary_and_ct(cur, _sa_fqn, primary_cents)
                        if primary_cents is not None:
                            inserted_w, stepped = append_account_balance_after_withdrawal_cycle(
                                cur,
                                account_balance_table=_ab_fqn,
                                subaccounts_table=_sa_fqn,
                                current_timestamp=current_timestamp,
                            )
                            if not inserted_w:
                                logger.warning(
                                    "Withdrawal cycle: append account_balance after drawdown ratchet skipped (no prior row?)"
                                )
                        else:
                            logger.warning(
                                "external withdrawal: skipping MTB reconcile and bankroll append (no portfolio row)"
                            )
                    pg_conn.commit()
                    notify_frontend_db_change("subaccounts", {"source": "external_withdrawal"})
                    notify_frontend_db_change("transfers", {"source": "external_withdrawal"})
                    if not inserted_w:
                        notify_monitor_manager()
                    logger.debug(
                        "New withdrawal(s): CT reduced by net %s; MTB reconciled; drawdown row inserted=%s stepped=%s",
                        sum(new_withdrawal_amounts),
                        inserted_w,
                        stepped,
                    )
            else:
                logger.warning("Skipping PostgreSQL write - no connection available")
        except Exception as pg_err:
            logger.error("Failed to write balance to PostgreSQL: %s", pg_err)

    except Exception as e:
        logger.error("Failed to fetch balance: %s", e)
        return
    finally:
        if pg_conn:
            pg_conn.close()
    logger.info("Balance sync OK")


# --- New sync functions for positions, fills, settlements using PostgreSQL ---


def _notify_trade_manager_positions_updated(payload):
    """Notify trade_manager: Redis when USE_TRADING_REDIS_COMMS, else POST /api/positions_updated with retries."""
    try:
        from backend.core.trading_redis_comms import (
            is_probably_startup_connect_refused,
            publish_positions_updated_notification,
            use_trading_redis_comms,
        )

        if use_trading_redis_comms() and publish_positions_updated_notification(payload):
            logger.debug("Notified trade_manager (Redis) about %s", payload.get("database", "update"))
            return
    except Exception as e:
        logger.debug("Redis positions_updated notify failed: %s", e)
    trade_manager_port = get_port("trade_manager")
    url = f"http://localhost:{trade_manager_port}/api/positions_updated"
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                logger.debug("Notified trade_manager (HTTP) about %s", payload.get("database", "update"))
                return
            logger.warning("trade_manager returned %s on attempt %s/%s", response.status_code, attempt + 1, max_attempts)
        except Exception as e:
            if attempt < max_attempts - 1:
                delay = 1 * (2 ** attempt)
                logger.debug("trade_manager unreachable (attempt %s/%s): %s; retry in %ss", attempt + 1, max_attempts, e, delay)
                time.sleep(delay)
            else:
                if is_probably_startup_connect_refused(e):
                    logger.debug(
                        "Failed to notify trade_manager after %s attempts: %s",
                        max_attempts,
                        e,
                    )
                else:
                    logger.warning(
                        "Failed to notify trade_manager after %s attempts: %s",
                        max_attempts,
                        e,
                    )


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


def _flush_debounced_pending(pending: set) -> None:
    """REST syncs for keys accumulated from debounced WS triggers."""
    if not pending:
        return
    need_balance = False
    if "positions" in pending:
        sync_positions()
        need_balance = True
    if "fills" in pending:
        sync_fills()
        need_balance = True
    if "orders" in pending:
        sync_orders()
        need_balance = True
    if "settlements" in pending:
        sync_settlements()
        need_balance = True
    if "balance" in pending:
        need_balance = True
    if need_balance:
        sync_balance()


def _quick_periodic_sync() -> None:
    sync_settlements()
    sync_balance()


def _full_reconcile_sync() -> None:
    sync_positions()
    sync_fills()
    sync_orders()
    sync_settlements()
    sync_balance()


class KalshiWebSocketSync:
    def __init__(self):
        self.websocket = None
        self.subscription_id = None
        self.command_id = 1
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self._pending: set = set()
        self._debounce_task: Optional[asyncio.Task] = None
        self._debounce_sec = _account_sync_debounce_sec()
        self._quick_sec = _account_sync_quick_periodic_sec()
        self._full_sec = _account_sync_full_reconcile_sec()
        self._poc_fill_count = 0
        self._poc_order_count = 0
        
    def load_kalshi_credentials(self):
        """Load Kalshi API credentials"""
        cred_dir = Path(get_kalshi_credentials_dir()) / "prod"

        if not cred_dir.exists():
            logger.error("No prod credentials found at %s", cred_dir)
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
            
            logger.info("Connecting to Kalshi User Fills WebSocket (prod)")

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
    
    async def subscribe_to_portfolio_channels(self):
        """Subscribe to market_positions, fill, user_orders (configurable via ACCOUNT_SYNC_WS_CHANNELS)."""
        if not self.websocket:
            return False

        channels = _account_sync_ws_channels()
        if not channels:
            logger.error("ACCOUNT_SYNC_WS_CHANNELS resolved empty")
            return False

        try:
            subscription_message = {
                "id": self.command_id,
                "cmd": "subscribe",
                "params": {"channels": channels},
            }
            self.command_id += 1
            await self.websocket.send(json.dumps(subscription_message))
            logger.debug("Sent portfolio channel subscription: %s", channels)

            deadline = time.time() + 15.0
            while time.time() < deadline:
                remaining = min(5.0, max(0.1, deadline - time.time()))
                response = await asyncio.wait_for(self.websocket.recv(), timeout=remaining)
                response_data = json.loads(response)
                if response_data.get("type") == "subscribed":
                    self.subscription_id = response_data.get("msg", {}).get("sid")
                    logger.info("Subscribed to portfolio channels %s (sid=%s)", channels, self.subscription_id)
                    return True
                if response_data.get("type") == "error":
                    logger.error("Portfolio subscription error: %s", response_data)
                    return False
                logger.debug("Pre-subscribe message: %s", response_data.get("type"))

            logger.error("Portfolio subscription timed out waiting for subscribed ack")
            return False

        except Exception as e:
            logger.error("Failed to subscribe to portfolio channels: %s", e)
            return False

    async def _add_pending_and_debounce(self, keys) -> None:
        for k in keys:
            self._pending.add(k)
        await self._schedule_debounced_flush()

    async def _schedule_debounced_flush(self) -> None:
        async def _run():
            try:
                await asyncio.sleep(self._debounce_sec)
                pending = self._pending.copy()
                self._pending.clear()
                if not pending:
                    return
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _flush_debounced_pending, pending)
            except asyncio.CancelledError:
                raise
            finally:
                self._debounce_task = None

        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass
        self._debounce_task = asyncio.create_task(_run())

    async def handle_ws_message(self, message):
        """Route Kalshi WS messages to debounced REST syncs; PoC logging for fill / user_orders."""
        try:
            data = json.loads(message)
            t = data.get("type")
            max_poc = _account_sync_poc_log_max()

            if t == "market_position":
                position_data = data.get("msg", {})
                global LATEST_WEBSOCKET_POSITION_DATA, LATEST_WEBSOCKET_TIMESTAMP
                LATEST_WEBSOCKET_POSITION_DATA = position_data
                LATEST_WEBSOCKET_TIMESTAMP = utc_now_iso_z()
                logger.debug(
                    "Market position update: ticker=%s position=%s",
                    position_data.get("market_ticker"),
                    position_data.get("position"),
                )
                await self._add_pending_and_debounce({"positions", "balance"})

            elif t == "fill":
                if self._poc_fill_count < max_poc:
                    self._poc_fill_count += 1
                    logger.info("PoC fill WS message (compare to REST): %s", json.dumps(data, default=str)[:3000])
                await self._add_pending_and_debounce({"fills", "balance"})

            elif t in ("order", "user_order", "orders", "order_update"):
                if self._poc_order_count < max_poc:
                    self._poc_order_count += 1
                    logger.info("PoC user_orders WS message (compare to REST): %s", json.dumps(data, default=str)[:3000])
                await self._add_pending_and_debounce({"orders", "balance"})

            elif t == "subscribed":
                logger.debug("Subscription confirmed: %s", data)

            elif t == "error":
                logger.warning("WebSocket error: %s", data)

            else:
                logger.debug("WebSocket message: type=%s", t)

        except Exception as e:
            logger.error("Error handling message: %s", e)
            logger.debug("Raw message: %s", message)

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

    async def periodic_quick_task(self):
        """Settlements + balance on ACCOUNT_SYNC_QUICK_PERIODIC_SEC (default 300s)."""
        while True:
            try:
                await asyncio.sleep(self._quick_sec)
                logger.info("heartbeat")
                logger.debug("quick periodic: settlements + balance")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _quick_periodic_sync)
            except Exception as e:
                logger.error("Error in quick periodic task: %s", e)

    async def periodic_full_task(self):
        """Full five-way REST reconcile on ACCOUNT_SYNC_FULL_RECONCILE_SEC (default 900s)."""
        while True:
            try:
                await asyncio.sleep(self._full_sec)
                logger.debug("full reconcile periodic")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _full_reconcile_sync)
            except Exception as e:
                logger.error("Error in full reconcile periodic task: %s", e)

    async def run_websocket(self):
        """WebSocket triggers (debounced per resource) + quick + full periodic REST."""
        logger.info("Starting Kalshi Hybrid WebSocket/Polling Sync")

        asyncio.create_task(self.periodic_quick_task())
        asyncio.create_task(self.periodic_full_task())
        logger.debug(
            "Started periodic quick every %ss + full reconcile every %ss",
            self._quick_sec,
            self._full_sec,
        )

        while True:
            try:
                if not await self.connect():
                    logger.warning("Failed to connect, retrying in 5 seconds")
                    await asyncio.sleep(5)
                    continue

                if not await self.subscribe_to_portfolio_channels():
                    logger.warning("Failed to subscribe, retrying in 5 seconds")
                    await asyncio.sleep(5)
                    continue

                logger.info(
                    "Listening for portfolio WS (debounced REST) + quick (settle/bal) + full reconcile"
                )

                async for message in self.websocket:
                    await self.handle_ws_message(message)

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

    from backend.core.exchange_credentials import block_forever_if_kalshi_authenticated_api_disallowed

    block_forever_if_kalshi_authenticated_api_disallowed(logger, "kalshi_account_sync")

    _wait_for_trade_manager()

    # Initial sync to establish baseline data (one-time only)
    logger.info("Performing initial baseline data sync")
    sync_positions()
    sync_fills()
    sync_orders()
    sync_settlements()
    sync_balance()  # Update balance LAST so it can reference latest positions data

    logger.info("Initial baseline sync complete; starting hybrid mode (WS debounced + quick + full reconcile)")

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