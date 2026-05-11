#!/usr/bin/env python3
"""
Active Trade Supervisor - MONITOR-AWARE VERSION

Monitors currently open trades and maintains a standalone database
for active trade management. Gets notified when trade_manager confirms
new open trades and creates corresponding entries in ACTIVE_TRADES.DB.
Supports multiple monitors with monitor-specific configuration.
"""

import logging
import os
import json
import re
import time
import threading
import signal
import subprocess
from datetime import datetime, timezone, time as datetime_time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import requests
from typing import Any, Dict, List, Optional, Set, Tuple
from contextvars import ContextVar
from contextlib import contextmanager
import psycopg2
import sys
# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.core.port_config import (
    default_pool_user_number,
    get_monitor_port,
    get_port,
    register_monitor_ports,
    unified_active_trade_supervisor_service_name,
)
from backend.core.exchange_ids import DEFAULT_EXCHANGE
from backend.core.strike_ladder_fetch import (
    fetch_strike_ladder_prefer_snapshot,
    find_ladder_strike_by_ticker,
    probability_from_ladder_by_strike,
    probability_from_strike_row_side_aware,
    strike_table_name_for_market,
)
from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import effective_tenant_context_for_sql_rewrite
from backend.core.tenant_legacy_sql import (
    legacy_active_trades_pool_15m,
    legacy_active_trades_pool_hourly,
    legacy_users_monitor_list,
    legacy_users_trades,
)
from backend.core.auto_entry_settings_store import monitor_list_flip_columns_available
from backend.core.strike_pipeline_health import evaluate_pipeline_gate_conn
from backend.util.paths import get_host
from backend.core.time_eastern import now_est as wall_now, EST
from backend.core.kalshi_contract_settlement import kalshi_contract_settlement_end_est
from backend.trading_mode import _norm_slot

# Cached per symbol; same master lookup tables as strike_table_generator (not fingerprint calc).
_lookup_probability_calculator_cache: Dict[str, Any] = {}
_lookup_probability_calculator_failed: Set[str] = set()

# trade_ids logged once when we skip auto-close past Kalshi settlement (avoid log spam)
_auto_close_suppress_past_settlement_logged: Set[int] = set()

# One volume/precheck close-retry loop per (tenant slot, monitor id, trade pk); see handle_close_attempt_failed_trade.
_close_volume_retry_active: Set[Tuple[str, str, int]] = set()
_close_volume_retry_lock = threading.Lock()

def should_suppress_auto_close_past_kalshi_settlement(
    ticker: Optional[str], trade_id: Optional[int]
) -> bool:
    """
    If the Kalshi contract's settlement instant has passed, do not POST market close orders.
    trade_manager may still be catching up (open in main DB) after spot/scheduler issues.
    """
    end = kalshi_contract_settlement_end_est(ticker)
    if end is None:
        return False
    grace = timedelta(seconds=10)
    now_est = wall_now()
    if now_est <= end + grace:
        return False
    tid = int(trade_id) if trade_id is not None else 0
    if tid not in _auto_close_suppress_past_settlement_logged:
        _auto_close_suppress_past_settlement_logged.add(tid)
        if len(_auto_close_suppress_past_settlement_logged) > 8000:
            _auto_close_suppress_past_settlement_logged.clear()
        log(
            f"[AUTO STOP] Skipping close for trade {tid}: Kalshi contract past settlement "
            f"(ticker={ticker}, settlement_end_est={end.isoformat()}). "
            f"Waiting for trade_manager expiry or manual handling."
        )
    return True


# Remove pool/per-monitor rows if trade_manager never expired the main trade but Kalshi settlement is long gone.
STALE_ACTIVE_TRADE_FLUSH_AFTER_SETTLEMENT = timedelta(hours=2)

# Add these functions after the existing imports and before the get_monitor_identifier function

def create_unified_15m_active_trades_pool_table():
    """Single users.active_trades_15m_<user> table for all 15m monitors (monitor_id column)."""
    try:
        conn = get_postgresql_connection()
        if not conn:
            return
        slot = effective_tenant_context_for_sql_rewrite().user_no
        tbl = legacy_active_trades_pool_15m(slot)
        with conn.cursor() as cursor:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS users.{tbl} (
                    id SERIAL PRIMARY KEY,
                    monitor_id VARCHAR(20) NOT NULL,
                    trade_id INTEGER NOT NULL,
                    ticket_id VARCHAR(50),
                    date DATE,
                    time TIME,
                    strike VARCHAR(50),
                    side VARCHAR(10),
                    buy_price DECIMAL(10,4),
                    position NUMERIC(12,2),
                    contract VARCHAR(50),
                    ticker VARCHAR(50),
                    symbol VARCHAR(10),
                    exchange VARCHAR(50),
                    trade_strategy VARCHAR(50),
                    symbol_open DECIMAL(10,2),
                    momentum DECIMAL(5,2),
                    prob DECIMAL(5,2),
                    fees DECIMAL(10,4),
                    diff DECIMAL(10,4),
                    status VARCHAR(20) DEFAULT 'active',
                    current_symbol_price DECIMAL(20,8),
                    current_probability DECIMAL(5,2),
                    buffer_from_entry DECIMAL(20,8),
                    time_since_entry INTEGER,
                    current_close_price DECIMAL(10,4),
                    current_pnl VARCHAR(20),
                    high_price DECIMAL(10,4),
                    low_price DECIMAL(10,4),
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT {tbl}_trade_id_key UNIQUE (trade_id)
                )
            """)
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{tbl}_monitor_status
                ON users.{tbl} (monitor_id, status)
                """
            )
            conn.commit()
        conn.close()
        log_debug(f"Ensured unified 15m active trades pool table: {tbl}")
    except Exception as e:
        log(f"[ACTIVE_TRADES] ❌ Error creating unified 15m pool table: {e}")


def create_unified_hourly_active_trades_pool_table():
    """Single users.active_trades_hourly_<user> table for all hourly monitors (monitor_id column)."""
    try:
        conn = get_postgresql_connection()
        if not conn:
            return
        slot = effective_tenant_context_for_sql_rewrite().user_no
        tbl = legacy_active_trades_pool_hourly(slot)
        with conn.cursor() as cursor:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS users.{tbl} (
                    id SERIAL PRIMARY KEY,
                    monitor_id VARCHAR(20) NOT NULL,
                    trade_id INTEGER NOT NULL,
                    ticket_id VARCHAR(50),
                    date DATE,
                    time TIME,
                    strike VARCHAR(50),
                    side VARCHAR(10),
                    buy_price DECIMAL(10,4),
                    position NUMERIC(12,2),
                    contract VARCHAR(50),
                    ticker VARCHAR(50),
                    symbol VARCHAR(10),
                    exchange VARCHAR(50),
                    trade_strategy VARCHAR(50),
                    symbol_open DECIMAL(10,2),
                    momentum DECIMAL(5,2),
                    prob DECIMAL(5,2),
                    fees DECIMAL(10,4),
                    diff DECIMAL(10,4),
                    status VARCHAR(20) DEFAULT 'active',
                    current_symbol_price DECIMAL(20,8),
                    current_probability DECIMAL(5,2),
                    buffer_from_entry DECIMAL(20,8),
                    time_since_entry INTEGER,
                    current_close_price DECIMAL(10,4),
                    current_pnl VARCHAR(20),
                    high_price DECIMAL(10,4),
                    low_price DECIMAL(10,4),
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT {tbl}_trade_id_key UNIQUE (trade_id)
                )
            """)
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{tbl}_monitor_status
                ON users.{tbl} (monitor_id, status)
                """
            )
            conn.commit()
        conn.close()
        log_debug(f"Ensured unified hourly active trades pool table: {tbl}")
    except Exception as e:
        log(f"[ACTIVE_TRADES] ❌ Error creating unified hourly pool table: {e}")


def create_monitor_active_trades_table():
    """Create per-monitor table (legacy hourly) or unified pool table (15m or hourly; monitor_id column)."""
    if ATS_UNIFIED_ALL:
        create_unified_15m_active_trades_pool_table()
        create_unified_hourly_active_trades_pool_table()
        return
    if ATS_UNIFIED_15M:
        create_unified_15m_active_trades_pool_table()
        return
    if ATS_UNIFIED_HOURLY:
        create_unified_hourly_active_trades_pool_table()
        return
    try:
        conn = get_postgresql_connection()
        if not conn:
            return
        with conn.cursor() as cursor:
            active_trades_table = f"active_trades_{ctx_user()}_{ctx_mid()}"
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS users.{active_trades_table} (
                    id SERIAL PRIMARY KEY,
                    trade_id INTEGER NOT NULL,
                    ticket_id VARCHAR(50),
                    date DATE,
                    time TIME,
                    strike VARCHAR(50),
                    side VARCHAR(10),
                    buy_price DECIMAL(10,4),
                    position NUMERIC(12,2),
                    contract VARCHAR(50),
                    ticker VARCHAR(50),
                    symbol VARCHAR(10),
                    exchange VARCHAR(50),
                    trade_strategy VARCHAR(50),
                    symbol_open DECIMAL(10,2),
                    momentum DECIMAL(5,2),
                    prob DECIMAL(5,2),
                    fees DECIMAL(10,4),
                    diff DECIMAL(10,4),
                    status VARCHAR(20) DEFAULT 'active',
                    current_symbol_price DECIMAL(20,8),
                    current_probability DECIMAL(5,2),
                    buffer_from_entry DECIMAL(20,8),
                    time_since_entry INTEGER,
                    current_close_price DECIMAL(10,4),
                    current_pnl VARCHAR(20),
                    high_price DECIMAL(10,4),
                    low_price DECIMAL(10,4),
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        conn.close()
        log_debug(f"Created monitor-specific active trades table: {active_trades_table}")
    except Exception as e:
        log(f"[ACTIVE_TRADES] ❌ Error creating active trades table: {e}")

def drop_monitor_active_trades_table():
    """Drop monitor-specific active trades table when supervisor stops"""
    if ATS_UNIFIED_POOL:
        return
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Drop monitor-specific active trades table
            active_trades_table = f"active_trades_{ctx_user()}_{ctx_mid()}"
            cursor.execute(f"DROP TABLE IF EXISTS users.{active_trades_table}")
            conn.commit()
        conn.close()
        log_debug(f"Dropped monitor-specific active trades table: {active_trades_table}")
    except Exception as e:
        log(f"[ACTIVE_TRADES] ❌ Error dropping active trades table: {e}")

def get_monitor_active_trades_table():
    """Per-monitor legacy table or unified pool active_trades_15m_*|active_trades_hourly_* (tenant rewrite)."""
    slot = effective_tenant_context_for_sql_rewrite().user_no
    if ATS_UNIFIED_15M:
        return legacy_active_trades_pool_15m(slot)
    if ATS_UNIFIED_HOURLY:
        return legacy_active_trades_pool_hourly(slot)
    if ATS_UNIFIED_ALL:
        from backend.core.port_config import monitor_suffix_uses_unified_15m_pool

        suffix = f"{ctx_user()}_{ctx_mid()}"
        if monitor_suffix_uses_unified_15m_pool(suffix):
            return legacy_active_trades_pool_15m(slot)
        return legacy_active_trades_pool_hourly(slot)
    return f"active_trades_{ctx_user()}_{ctx_mid()}"


def _active_trades_monitor_scope_sql():
    """Extra WHERE fragment for unified pool (monitor_id scoping)."""
    if ATS_UNIFIED_POOL:
        return " AND monitor_id = %s", (ctx_mid(),)
    return "", ()

# Monitor identification - extract from script name or command line args
def get_monitor_identifier():
    """Extract monitor identifier from script name or command line arguments"""
    script_name = os.path.basename(sys.argv[0])
    
    # Check if script name contains monitor identifier (e.g., active_trade_supervisor_<slot>_10001)
    if '_' in script_name and script_name.count('_') >= 3:
        parts = script_name.split('_')
        if len(parts) >= 4:
            user_number = parts[-2]  # four-digit tenant slot
            monitor_id = parts[-1]   # monitor id
            return f"{user_number}_{monitor_id}"
    
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "unified_15m":
            return "unified_15m"
        if sys.argv[1] == "unified_hourly":
            return "unified_hourly"
        if sys.argv[1] == "unified":
            return "unified"
        return sys.argv[1]  # Use first argument as monitor identifier
    
    # Default to first active monitor if no identifier provided
    raise ValueError("No monitor identifier found in script name")

# Get monitor identifier
MONITOR_IDENTIFIER = get_monitor_identifier()
ATS_UNIFIED_15M = MONITOR_IDENTIFIER == "unified_15m"
ATS_UNIFIED_HOURLY = MONITOR_IDENTIFIER == "unified_hourly"
ATS_UNIFIED_ALL = MONITOR_IDENTIFIER == "unified"
ATS_UNIFIED_POOL = ATS_UNIFIED_15M or ATS_UNIFIED_HOURLY or ATS_UNIFIED_ALL


def _unified_pool_accepts_monitor_suffix(monitor_suffix: str) -> bool:
    """
    Unified 15m and unified hourly ATS both subscribe to the same Redis enrollment/TM channels.
    Ignore messages for monitors that belong to the other pool so rows do not land in the wrong table.
    """
    if not ATS_UNIFIED_POOL:
        return True
    s = str(monitor_suffix or "").strip()
    if "_" not in s:
        return False
    from backend.core.port_config import (
        monitor_suffix_uses_unified_15m_pool,
        monitor_suffix_uses_unified_hourly_pool,
        monitor_suffix_uses_unified_aes_ats_pool,
    )

    if ATS_UNIFIED_ALL:
        return monitor_suffix_uses_unified_aes_ats_pool(s)
    if ATS_UNIFIED_15M:
        return monitor_suffix_uses_unified_15m_pool(s)
    if ATS_UNIFIED_HOURLY:
        return monitor_suffix_uses_unified_hourly_pool(s)
    return False


if ATS_UNIFIED_POOL:
    USER_NUMBER = default_pool_user_number()
    MONITOR_ID = "0"
else:
    USER_NUMBER = MONITOR_IDENTIFIER.split('_')[0]
    MONITOR_ID = MONITOR_IDENTIFIER.split('_')[1]

_ats_bind_u: ContextVar[Optional[str]] = ContextVar("_ats_bind_u", default=None)
_ats_bind_m: ContextVar[Optional[str]] = ContextVar("_ats_bind_m", default=None)


def ctx_user() -> str:
    u = _ats_bind_u.get()
    return u if u is not None else USER_NUMBER


def ctx_mid() -> str:
    m = _ats_bind_m.get()
    return m if m is not None else MONITOR_ID


def ctx_ident() -> str:
    return f"{ctx_user()}_{ctx_mid()}"


def scoped_trade_manager_http_port() -> int:
    """HTTP port for ``trade_manager_<this slot>`` (same tenant as ctx_user); never abstract ``trade_manager``."""
    return get_port(f"trade_manager_{ctx_user()}")


@contextmanager
def ats_monitor_bind(user_num: str, monitor_id: str):
    if not ATS_UNIFIED_POOL:
        yield
        return
    t1 = _ats_bind_u.set(user_num)
    t2 = _ats_bind_m.set(monitor_id)
    try:
        yield
    finally:
        _ats_bind_u.reset(t1)
        _ats_bind_m.reset(t2)


def _ats_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _AtsFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_ats_logging():
    logr = logging.getLogger("active_trade_supervisor")
    if logr.handlers:
        return logr
    h = _AtsFlushHandler(sys.stdout)
    h.setFormatter(_ats_est_formatter())
    logr.addHandler(h)
    # Default to INFO in normal operation; DEBUG must be explicitly enabled.
    logr.setLevel(logging.INFO)
    return logr


_ats_logger = _configure_ats_logging()
HEARTBEAT_INTERVAL_SEC = 300


def _ats_heartbeat_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SEC)
        _ats_logger.info("heartbeat")


_ats_hb_thread = threading.Thread(target=_ats_heartbeat_loop, daemon=True)
_ats_hb_thread.start()

ATS_HTTP_FALLBACK_ENABLED = (os.getenv("ATS_HTTP_FALLBACK_ENABLED") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def log(message: str):
    """Stdout log at INFO (use log_debug for plumbing)."""
    _ats_logger.info("%s", message)


def log_debug(message: str):
    """Stdout log at DEBUG for plumbing/repetitive messages."""
    _ats_logger.debug("%s", message)


_ats_logger.info(
    "Monitor-aware supervisor starting user=%s monitor=%s unified_15m=%s unified_hourly=%s unified_all=%s",
    ctx_user(),
    ctx_mid(),
    ATS_UNIFIED_15M,
    ATS_UNIFIED_HOURLY,
    ATS_UNIFIED_ALL,
)
try:
    from backend.core.trading_redis_comms import redis_client_optional, use_trading_redis_comms

    if use_trading_redis_comms():
        _rc = redis_client_optional()
        _ats_logger.info(
            "Trading Redis: enabled, connection=%s",
            "ok" if _rc else "failed (falling back to HTTP for preferences)",
        )
    else:
        _ats_logger.info(
            "Trading Redis: disabled (USE_TRADING_REDIS_COMMS unset); "
            "active_trades UI events will POST main_app unless env is set"
        )
    _ats_logger.info(
        "ATS HTTP fallback: %s (ATS_HTTP_FALLBACK_ENABLED=%s)",
        "enabled" if ATS_HTTP_FALLBACK_ENABLED else "disabled",
        "1" if ATS_HTTP_FALLBACK_ENABLED else "0",
    )
except Exception as _e:
    _ats_logger.info("Trading Redis startup check: %s", _e)

# Get symbol for this monitor (will be updated dynamically)
def get_monitor_symbol():
    """Get the symbol for the current monitor from database"""
    try:
        import psycopg2

        if ATS_UNIFIED_15M:
            from backend.core.unified_15m_monitors import list_active_15m_monitor_rows

            rows = list_active_15m_monitor_rows()
            if not rows:
                log("[ACTIVE_TRADE_SUPERVISOR] ❌ unified_15m: no active 15m monitors in DB; exiting")
                os._exit(0)
            uid0 = rows[0]["user_number"]
            mid0 = rows[0]["monitor_id"]
        elif ATS_UNIFIED_HOURLY:
            from backend.core.unified_hourly_monitors import list_active_hourly_monitor_rows

            rows = list_active_hourly_monitor_rows()
            if not rows:
                log("[ACTIVE_TRADE_SUPERVISOR] ❌ unified_hourly: no active hourly monitors in DB; exiting")
                os._exit(0)
            uid0 = rows[0]["user_number"]
            mid0 = rows[0]["monitor_id"]
        elif ATS_UNIFIED_ALL:
            from backend.core.unified_all_monitors import list_active_unified_monitor_rows

            rows = list_active_unified_monitor_rows()
            if not rows:
                log("[ACTIVE_TRADE_SUPERVISOR] ❌ unified: no active 15m or hourly-pool monitors in DB; exiting")
                os._exit(0)
            uid0 = rows[0]["user_number"]
            mid0 = rows[0]["monitor_id"]
        else:
            uid0, mid0 = ctx_user(), ctx_mid()

        conn = get_postgresql_connection()
        if not conn:
            log(f"[ACTIVE_TRADE_SUPERVISOR] ❌ No database connection available when resolving symbol for monitor {MONITOR_IDENTIFIER}")
            os._exit(0)

        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT symbol, COALESCE(market, 'hourly') FROM {legacy_users_monitor_list(uid0)}
            WHERE id = %s
        """, (mid0,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            log(f"[ACTIVE_TRADE_SUPERVISOR] ❌ Monitor {uid0}_{mid0} not found in monitor_list_{uid0}; shutting down supervisor to avoid ghost activity")
            os._exit(0)

        symbol_value, market_value = result
        if not symbol_value:
            log(f"[ACTIVE_TRADE_SUPERVISOR] ❌ Monitor {uid0}_{mid0} has no symbol configured; shutting down supervisor")
            os._exit(0)

        return symbol_value.upper(), (market_value or "hourly").strip().lower()
    except Exception as e:
        log(f"[ACTIVE_TRADE_SUPERVISOR] ❌ Error getting monitor symbol: {e}, defaulting to BTC")
        return "BTC", "hourly"

def get_strike_table_name(symbol: str, market: str) -> str:
    """Strike table name from symbol and market (hourly or 15m)."""
    return strike_table_name_for_market(symbol, market)

_sym_mkt = get_monitor_symbol()
MONITOR_SYMBOL = _sym_mkt[0] if isinstance(_sym_mkt, tuple) else _sym_mkt
MONITOR_MARKET = _sym_mkt[1] if isinstance(_sym_mkt, tuple) else 'hourly'
_ats_logger.info("Initial symbol=%s market=%s", MONITOR_SYMBOL, MONITOR_MARKET)

def get_current_monitor_symbol_and_market():
    """Get (symbol, market) for this monitor from database. market is 'hourly' or '15m'."""
    global MONITOR_SYMBOL, MONITOR_MARKET
    try:
        if ATS_UNIFIED_POOL and _ats_bind_m.get() is None:
            return MONITOR_SYMBOL, MONITOR_MARKET
        conn = get_postgresql_connection()
        if not conn:
            return "BTC", "hourly"
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT symbol, COALESCE(market, 'hourly') FROM {legacy_users_monitor_list(ctx_user())}
            WHERE id = %s
        """, (ctx_mid(),))
        result = cursor.fetchone()
        conn.close()
        if result and result[0]:
            sym = result[0].upper()
            mkt = (result[1] or 'hourly').strip().lower()
            if mkt not in ('hourly', '15m'):
                mkt = 'hourly'
            if sym != MONITOR_SYMBOL or mkt != MONITOR_MARKET:
                log_debug(f"Monitor symbol/market: {MONITOR_SYMBOL}/{MONITOR_MARKET} -> {sym}/{mkt}")
                MONITOR_SYMBOL, MONITOR_MARKET = sym, mkt
            return sym, mkt
        return "BTC", "hourly"
    except Exception as e:
        return "BTC", "hourly"

def get_current_monitor_symbol():
    """Get the current symbol for this monitor (dynamic lookup)"""
    sym, _ = get_current_monitor_symbol_and_market()
    return sym

def _get_symbol_and_market_for_strike(symbol: str = None):
    """Resolve (symbol, market) for strike table. Always use this monitor's market (hourly or 15m)."""
    sym, mkt = get_current_monitor_symbol_and_market()
    s = (symbol or sym).upper() if (symbol or sym) else "BTC"
    return s, mkt

# Get port from monitor-specific system
if ATS_UNIFIED_15M:
    ACTIVE_TRADE_SUPERVISOR_PORT = get_port("active_trade_supervisor_15m")
    _ats_logger.info("Using unified 15m ATS port: %s", ACTIVE_TRADE_SUPERVISOR_PORT)
elif ATS_UNIFIED_HOURLY:
    ACTIVE_TRADE_SUPERVISOR_PORT = get_port("active_trade_supervisor_hourly")
    _ats_logger.info("Using unified hourly ATS port: %s", ACTIVE_TRADE_SUPERVISOR_PORT)
elif ATS_UNIFIED_ALL:
    ACTIVE_TRADE_SUPERVISOR_PORT = get_port(unified_active_trade_supervisor_service_name())
    _ats_logger.info("Using pool ATS port (15m+hourly): %s", ACTIVE_TRADE_SUPERVISOR_PORT)
else:
    register_monitor_ports(MONITOR_IDENTIFIER)
    ACTIVE_TRADE_SUPERVISOR_PORT = get_monitor_port("active_trade_supervisor", MONITOR_IDENTIFIER)
    _ats_logger.info("Using monitor-specific port: %s", ACTIVE_TRADE_SUPERVISOR_PORT)


def _count_active_trades_across_unified_pool_monitors() -> int:
    """Rows in unified 15m or hourly pool that need the monitoring loop (active, pending, or closing)."""
    # Bind explicitly to this worker slot so counts never follow a stray HTTP/API tenant context.
    conn = get_postgresql_connection(tenant_user_no=USER_NUMBER)
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        if ATS_UNIFIED_ALL:
            total = 0
            wh = effective_tenant_context_for_sql_rewrite().user_no
            for tbl in (
                legacy_active_trades_pool_15m(wh),
                legacy_active_trades_pool_hourly(wh),
            ):
                cur.execute(
                    f"""
                    SELECT COUNT(*) FROM users.{tbl}
                    WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active')
                        IN ('active', 'pending', 'closing')
                    """
                )
                total += int(cur.fetchone()[0])
            return total
        tbl = get_monitor_active_trades_table()
        cur.execute(
            f"""
            SELECT COUNT(*) FROM users.{tbl}
            WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active')
                IN ('active', 'pending', 'closing')
            """
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


# Import centralized path utilities
from backend.util.paths import get_project_root, get_data_dir, get_trade_history_dir, get_kalshi_data_dir, get_service_url, get_active_trades_dir



# Import centralized path utilities
from backend.core.config.settings import config
from flask import Flask, request, jsonify
from flask_cors import CORS

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variable to track monitoring thread
monitoring_thread = None
monitoring_thread_lock = threading.Lock()

# Cache for active trades data to reduce frontend load
active_trades_cache = None
active_trades_cache_time = 0
CACHE_DURATION = 2  # Cache for 2 seconds

# Health check endpoint
@app.route("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": f"active_trade_supervisor_{MONITOR_IDENTIFIER}",
        "monitor_identifier": MONITOR_IDENTIFIER,
        "user_number": ctx_user(),
        "monitor_id": ctx_mid(),
        "port": ACTIVE_TRADE_SUPERVISOR_PORT,
        "timestamp": wall_now().isoformat(),
        "port_system": "centralized"
    }

# Active trades data endpoint (legacy - for backward compatibility)
@app.route("/api/active_trades")
def get_active_trades():
    """Get all active trades for frontend display with caching to prevent backend interference"""
    global active_trades_cache, active_trades_cache_time
    
    try:
        current_time = time.time()
        
        # Check if auto-stop is enabled to determine caching behavior
        auto_stop_enabled = is_auto_stop_enabled()
        
        # If auto-stop is disabled, always return fresh data (no caching)
        if not auto_stop_enabled:
            active_trades = get_all_active_trades()
            return jsonify({
                "status": "success",
                "timestamp": wall_now().isoformat(),
                "active_trades": active_trades,
                "count": len(active_trades),
                "cached": False,
                "auto_stop_enabled": False
            })
        
        # Auto-stop is enabled - use caching to protect critical functionality
        # Return cached data if it's still fresh
        if (active_trades_cache is not None and 
            current_time - active_trades_cache_time < CACHE_DURATION):
            return jsonify({
                "status": "success",
                "timestamp": wall_now().isoformat(),
                "active_trades": active_trades_cache,
                "count": len(active_trades_cache),
                "cached": True,
                "auto_stop_enabled": True
            })
        
        # Fetch fresh data from database
        active_trades = get_all_active_trades()
        
        # Update cache
        active_trades_cache = active_trades
        active_trades_cache_time = current_time
        
        return jsonify({
            "status": "success",
            "timestamp": wall_now().isoformat(),
            "active_trades": active_trades,
            "count": len(active_trades),
            "cached": False,
            "auto_stop_enabled": True
        })
    except Exception as e:
        log(f"❌ Error serving active trades: {e}")
        return jsonify({"error": str(e)}), 500

# Monitor-specific active trades data endpoint
@app.route("/api/active_trades/<monitor_identifier>")
def get_active_trades_for_monitor(monitor_identifier):
    """Get all active trades for a specific monitor"""
    try:
        # Validate monitor identifier format
        if not monitor_identifier or '_' not in monitor_identifier:
            return jsonify({"error": "Invalid monitor identifier format"}), 400

        u, mid = str(monitor_identifier).split("_", 1)
        if ATS_UNIFIED_POOL:
            with ats_monitor_bind(u, mid):
                active_trades = _get_all_active_trades_for_current_monitor()
        else:
            if monitor_identifier != MONITOR_IDENTIFIER:
                return jsonify({"error": "Wrong supervisor instance for this monitor"}), 400
            active_trades = _get_all_active_trades_for_current_monitor()

        return jsonify({
            "status": "success",
            "timestamp": wall_now().isoformat(),
            "active_trades": active_trades,
            "count": len(active_trades),
            "monitor_identifier": monitor_identifier,
            "current_monitor": MONITOR_IDENTIFIER
        })
    except Exception as e:
        log(f"❌ Error serving active trades for monitor {monitor_identifier}: {e}")
        return jsonify({"error": str(e)}), 500

# Port information endpoint
@app.route("/api/ports")
def get_ports():
    """Get port information for this service"""
    return {
        "service": f"active_trade_supervisor_{MONITOR_IDENTIFIER}",
        "monitor_identifier": MONITOR_IDENTIFIER,
        "port": ACTIVE_TRADE_SUPERVISOR_PORT,
        "host": get_host()
    }

# Automated trade close notification endpoint
@app.route("/api/notify_automated_close", methods=['POST'])
def notify_automated_close():
    """Notify the frontend that an automated trade close was triggered"""
    try:
        data = request.json
        log_debug(f"Notifying frontend of automated trade close: {data}")
        
        try:
            from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms

            if use_trading_redis_comms():
                publish_preferences_event("automated_trade_closed", data)
                log_debug("Frontend notification sent via Redis")
        except Exception as e:
            log(f"[AUTO STOP] ❌ Error sending frontend notification: {e}")
        
        return jsonify({"success": True, "message": "Automated trade close notification sent"})
    except Exception as e:
        log(f"[AUTO STOP] ❌ Error in notify_automated_close: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/sync_and_monitor", methods=['POST'])
def sync_and_monitor():
    """Manually trigger sync and monitoring for active trades"""
    try:
        log("🔄 Manual sync and monitor triggered")
        sync_on_demand()
        update_monitoring_on_demand()
        return {"status": "success", "message": "Sync and monitoring completed"}
    except Exception as e:
        log(f"❌ Error in manual sync and monitor: {e}")
        return {"status": "error", "message": str(e)}, 500

def get_momentum_percentile_from_postgresql(symbol="BTC"):
    """Get current momentum_5s_avg from live price log for the specified symbol."""
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum_5s_avg FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return float(result[0])
        else:
            return None
    except Exception as e:
        log(f"[MOMENTUM SPIKE] Error getting momentum_5s_avg from PostgreSQL: {e}")
        return None

def get_momentum_5s_avg_from_postgresql(symbol="BTC"):
    """Get current momentum_5s_avg directly from PostgreSQL for the specified symbol."""
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum_5s_avg FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return float(result[0])
        else:
            return None
    except Exception as e:
        log(f"[MOMENTUM SPIKE] Error getting momentum_5s_avg from PostgreSQL: {e}")
        return None

_broadcast_fail_last_log_ts: float = 0.0
_BROADCAST_FAIL_LOG_INTERVAL_SEC = 60.0


def _log_broadcast_failure_throttled(message: str) -> None:
    """Avoid IO storm when main_app is slow or down (Redis disabled / publish failed)."""
    global _broadcast_fail_last_log_ts
    now = time.time()
    if now - _broadcast_fail_last_log_ts >= _BROADCAST_FAIL_LOG_INTERVAL_SEC:
        _broadcast_fail_last_log_ts = now
        log(message)
    else:
        log_debug(message)


def broadcast_active_trades_change():
    """Broadcast active trades change via WebSocket to main app (Redis preferred)."""
    try:
        active_trades = get_all_active_trades()
        body = {
            "active_trades": active_trades,
            "count": len(active_trades),
            "timestamp": wall_now().isoformat(),
        }
        try:
            from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms

            if use_trading_redis_comms() and publish_preferences_event(
                "active_trades_change", body, tenant_user_no=ctx_user()
            ):
                return
        except Exception as e:
            _log_broadcast_failure_throttled(
                f"⚠️ Active trades broadcast Redis path failed: {e}"
            )

        _log_broadcast_failure_throttled(
            "⚠️ Active trades broadcast dropped: Redis unavailable and HTTP fallback removed"
        )
        return

    except Exception as e:
        _log_broadcast_failure_throttled(
            f"❌ Error in broadcast_active_trades_change: {e}"
        )

def check_for_open_trades():
    """
    Check trades.db for any OPEN trades and add them to active monitoring.
    """
    pass

def check_for_closed_trades():
    """
    Check if any active trades have been closed in trades.db.
    """
    pass

# HTTP endpoints for receiving notifications


def process_trade_manager_notification_core(trade_id, ticket_id, status: str) -> bool:
    """Apply trade_manager status to this monitor's active_trades (shared by HTTP and Redis enrollment)."""
    success = False
    if status == 'pending':
        success = add_pending_trade(trade_id, ticket_id)
        if success:
            log(f"✅ Successfully added pending trade: {trade_id}")
        else:
            log(f"❌ Failed to add pending trade: {trade_id}")

    elif status == 'open':
        success = confirm_pending_trade(trade_id, ticket_id)
        if success:
            log(f"✅ Successfully confirmed pending trade as open: {trade_id}")
        else:
            success = add_new_active_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully added new active trade: {trade_id}")
            else:
                log(f"❌ Failed to add new active trade: {trade_id}")

    elif status == 'partial':
        success = confirm_pending_trade(trade_id, ticket_id)
        if success:
            log(f"✅ Successfully confirmed pending trade as partial: {trade_id}")
        else:
            success = add_new_active_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully added new active trade (partial): {trade_id}")
            else:
                log(f"❌ Failed to add new active trade (partial): {trade_id}")

    elif status == 'error':
        success = remove_failed_trade(trade_id, ticket_id)
        if success:
            log(f"✅ Successfully removed failed trade: {trade_id}")
        else:
            log(f"❌ Failed to remove failed trade: {trade_id}")

    elif status == 'expired':
        success = remove_closed_trade(trade_id)
        if success:
            log(f"✅ Successfully removed expired trade: {trade_id}")
        else:
            log(f"❌ Failed to remove expired trade: {trade_id}")

    elif status == 'closing':
        success = update_trade_status_to_closing(trade_id)
        if success:
            log(f"✅ Successfully updated trade to closing status: {trade_id}")
        else:
            log(f"❌ Failed to update trade to closing status: {trade_id}")

    elif status == 'closed':
        success = remove_closed_trade(trade_id)
        if success:
            log(f"✅ Successfully removed closed trade: {trade_id}")
        else:
            log(f"❌ Failed to remove closed trade: {trade_id}")

    elif status == 'close_attempt_failed':
        success = handle_close_attempt_failed_trade(trade_id, ticket_id)
        if success:
            log(f"✅ Successfully handled close_attempt_failed trade: {trade_id}")
        else:
            log(f"❌ Failed to handle close_attempt_failed trade: {trade_id}")

    elif status == 'deleted':
        success = remove_failed_trade(trade_id, ticket_id)
        if success:
            log(f"✅ Successfully removed deleted trade: {trade_id}")
        else:
            log(f"❌ Failed to remove deleted trade: {trade_id}")
    else:
        log(f"⚠️ Unknown status in trade_manager notification: {status}")
        return False

    return success


def _open_enrollment_ack_payload(
    correlation_id: str, trade_id: int, enroll_ok: bool, error: str | None = None
) -> dict:
    """Build Redis ACK JSON after open enrollment attempt."""
    has_quote = False
    ticker = None
    side = None
    degraded = False
    if enroll_ok:
        try:
            conn = get_trades_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT ticker, side, symbol FROM {legacy_users_trades(ctx_user())}
                WHERE id = %s AND LOWER(TRIM(status)) IN ('open', 'partial')
                """,
                (trade_id,),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                ticker, side, tr_sym = row[0], row[1], row[2]
                sym_m, mkt_m = get_current_monitor_symbol_and_market()
                tsym = (
                    str(tr_sym).strip().upper()
                    if tr_sym is not None and str(tr_sym).strip()
                    else sym_m
                )
                snapshot = get_kalshi_market_snapshot_cached(symbol=tsym, market=mkt_m)
                if snapshot and ticker:
                    mp = get_current_closing_price_for_trade(
                        ticker,
                        side,
                        snapshot_data=snapshot,
                        symbol=tsym,
                        market=mkt_m,
                    )
                    has_quote = mp is not None
                if not has_quote:
                    degraded = True
        except Exception as e:
            log(f"⚠️ open enrollment ack quote check: {e}")
            degraded = True

    phase = "tracking" if enroll_ok else "failed"
    return {
        "type": "ats_track_ack",
        "correlation_id": correlation_id,
        "trade_id": trade_id,
        "monitor_identifier": ctx_ident(),
        "ok": enroll_ok and phase == "tracking",
        "phase": phase,
        "has_market_quote": has_quote,
        "degraded": degraded,
        "error": error,
    }


def _handle_ats_enroll_redis_message(data: dict) -> None:
    """Subscribe callback: enroll open trades addressed to this monitor."""
    try:
        if data.get("type") != "ats_trade_open":
            return
        suffix = data.get("monitor_suffix") or ""
        if ATS_UNIFIED_POOL:
            if "_" not in suffix:
                return
            if not _unified_pool_accepts_monitor_suffix(suffix):
                log_debug(
                    f"ATS ENROLL Redis: skip mon={suffix} (not this unified pool)"
                )
                return
            u, mid = suffix.split("_", 1)
            try:
                if _norm_slot(u) != _norm_slot(USER_NUMBER):
                    log_debug(
                        f"ATS ENROLL Redis: skip mon={suffix} trade={data.get('trade_id')} "
                        f"(this unified ATS is user {USER_NUMBER}, not {_norm_slot(u)})"
                    )
                    return
            except ValueError:
                return
            correlation_id = data.get("correlation_id")
            trade_id = data.get("trade_id")
            ticket_id = data.get("ticket_id") or ""
            if not correlation_id or trade_id is None:
                return
            from backend.core.ats_enrollment_redis import redis_client_optional, store_enroll_ack

            r = redis_client_optional()
            if not r:
                return
            log(
                f"📮 ATS ENROLL (Redis): trade_id={trade_id} ticket_id={ticket_id} cid={correlation_id} mon={suffix}"
            )
            with ats_monitor_bind(u, mid):
                enroll_ok = process_trade_manager_notification_core(trade_id, ticket_id, "open")
                payload = _open_enrollment_ack_payload(
                    correlation_id, int(trade_id), enroll_ok
                )
                store_enroll_ack(r, correlation_id, payload)
            if payload.get("ok"):
                q = "has quote" if payload.get("has_market_quote") else "no live quote (degraded)"
                log(f"✅ ATS ENROLL ACK ok trade={trade_id} {q}")
            else:
                log(f"❌ ATS ENROLL ACK failed trade={trade_id}")
            return

        if suffix != MONITOR_IDENTIFIER:
            return
        correlation_id = data.get("correlation_id")
        trade_id = data.get("trade_id")
        ticket_id = data.get("ticket_id") or ""
        if not correlation_id or trade_id is None:
            return
        from backend.core.ats_enrollment_redis import redis_client_optional, store_enroll_ack

        r = redis_client_optional()
        if not r:
            return
        log(
            f"📮 ATS ENROLL (Redis): trade_id={trade_id} ticket_id={ticket_id} cid={correlation_id}"
        )
        enroll_ok = process_trade_manager_notification_core(trade_id, ticket_id, "open")
        payload = _open_enrollment_ack_payload(correlation_id, int(trade_id), enroll_ok)
        store_enroll_ack(r, correlation_id, payload)
        if payload.get("ok"):
            q = "has quote" if payload.get("has_market_quote") else "no live quote (degraded)"
            log(f"✅ ATS ENROLL ACK ok trade={trade_id} {q}")
        else:
            log(f"❌ ATS ENROLL ACK failed trade={trade_id}")
    except Exception as e:
        log(f"❌ ATS enroll redis handler: {e}")


def start_ats_enroll_redis_subscriber():
    """Daemon thread: consume rec_io:ats_enroll_request for this monitor."""
    t = threading.Thread(target=_ats_enroll_subscriber_thread_main, daemon=True)
    t.start()


def _handle_ats_tm_notification_redis(data: dict) -> None:
    """trade_manager → ATS status fanout (non-open); same routing as /api/trade_manager_notification."""
    try:
        if data.get("type") != "ats_tm_notification":
            return
        trade_id = data.get("trade_id")
        ticket_id = (data.get("ticket_id") or "").strip() or None
        status = data.get("status")
        monitor_identifier = data.get("monitor_identifier")
        if trade_id is None or not status:
            return
        if not ticket_id:
            u_trade = USER_NUMBER
            if monitor_identifier and "_" in str(monitor_identifier):
                u_trade = str(monitor_identifier).split("_")[0]
            elif not ATS_UNIFIED_POOL and MONITOR_IDENTIFIER and "_" in MONITOR_IDENTIFIER:
                u_trade = MONITOR_IDENTIFIER.split("_", 1)[0]
            slot = _norm_slot(str(u_trade).strip())
            pg = get_postgresql_connection(tenant_user_no=slot)
            if pg:
                try:
                    with pg.cursor() as cur:
                        cur.execute(
                            f"SELECT ticket_id FROM {legacy_users_trades(slot)} WHERE id = %s",
                            (trade_id,),
                        )
                        row = cur.fetchone()
                        if row and row[0]:
                            ticket_id = str(row[0]).strip() or None
                except Exception as e:
                    log(f"⚠️ ticket_id backfill failed for trade {trade_id}: {e}")
                finally:
                    pg.close()
        if not ticket_id:
            ticket_id = ""
        if ATS_UNIFIED_POOL:
            if not monitor_identifier or "_" not in str(monitor_identifier):
                log(f"⚠️ ATS Redis tm notify: missing monitor_identifier trade={trade_id}")
                return
            mon_s = str(monitor_identifier).strip()
            if not _unified_pool_accepts_monitor_suffix(mon_s):
                log_debug(
                    f"ATS Redis tm notify: skip mon={mon_s} trade={trade_id} (wrong unified pool)"
                )
                return
            u, mid = mon_s.split("_", 1)
            try:
                if _norm_slot(u) != _norm_slot(USER_NUMBER):
                    log_debug(
                        f"ATS Redis tm notify: skip mon={mon_s} trade={trade_id} "
                        f"(this unified ATS is user {USER_NUMBER}, not {_norm_slot(u)})"
                    )
                    return
            except ValueError:
                return
            log(
                f"📡 REDIS TM NOTIFY (unified pool): mon={monitor_identifier} trade={trade_id} status={status}"
            )
            with ats_monitor_bind(u, mid):
                process_trade_manager_notification_core(trade_id, ticket_id, status)
            return
        if monitor_identifier and monitor_identifier != MONITOR_IDENTIFIER:
            return
        log(f"📡 REDIS TM NOTIFY: Trade ID: {trade_id}, Ticket ID: {ticket_id}, Status: {status}")
        process_trade_manager_notification_core(trade_id, ticket_id, status)
    except Exception as e:
        log(f"❌ ATS tm notification redis: {e}")


def _ats_enroll_subscriber_thread_main():
    try:
        from backend.core.ats_enrollment_redis import start_enroll_subscriber_loop

        start_enroll_subscriber_loop(_handle_ats_enroll_redis_message, _handle_ats_tm_notification_redis)
    except Exception as e:
        log(f"❌ ATS enrollment subscriber exit: {e}")


@app.route('/api/trade_manager_notification', methods=['POST'])
def handle_trade_manager_notification():
    """Handle direct notifications from trade_manager about trade status changes"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received", "success": False}), 200
        
        trade_id = data.get("trade_id")
        ticket_id = (data.get("ticket_id") or "").strip() or None
        status = data.get("status")
        monitor_identifier = data.get("monitor_identifier")

        if trade_id is None or not status:
            return jsonify(
                {
                    "error": "Missing required fields: trade_id, status",
                    "success": False,
                }
            ), 200

        # Some callers omit ticket_id; enrollment reads authoritative fields from trades rows anyway.
        if not ticket_id:
            u_trade = USER_NUMBER
            if monitor_identifier and "_" in str(monitor_identifier):
                u_trade = str(monitor_identifier).split("_")[0]
            elif not ATS_UNIFIED_POOL and MONITOR_IDENTIFIER and "_" in MONITOR_IDENTIFIER:
                u_trade = MONITOR_IDENTIFIER.split("_", 1)[0]
            slot = _norm_slot(str(u_trade).strip())
            pg = get_postgresql_connection(tenant_user_no=slot)
            if pg:
                try:
                    with pg.cursor() as cur:
                        cur.execute(
                            f"SELECT ticket_id FROM {legacy_users_trades(slot)} WHERE id = %s",
                            (trade_id,),
                        )
                        row = cur.fetchone()
                        if row and row[0]:
                            ticket_id = str(row[0]).strip() or None
                except Exception as e:
                    log(f"⚠️ ticket_id backfill failed for trade {trade_id}: {e}")
                finally:
                    pg.close()
        if not ticket_id:
            ticket_id = ""
        
        if ATS_UNIFIED_POOL:
            if not monitor_identifier or "_" not in str(monitor_identifier):
                return jsonify(
                    {
                        "error": "monitor_identifier required (format: <user_slot>_<monitor_id>)",
                        "success": False,
                    }
                ), 200
            mon_s = str(monitor_identifier).strip()
            if not _unified_pool_accepts_monitor_suffix(mon_s):
                log_debug(
                    f"📡 DIRECT NOTIFICATION (unified pool): ignored mon={mon_s} "
                    f"(wrong pool for this ATS process) trade={trade_id}"
                )
                return jsonify(
                    {
                        "status": "ignored",
                        "message": f"Monitor {mon_s} is not enrolled in this unified pool",
                        "success": True,
                    }
                ), 200
            u, mid = mon_s.split("_", 1)
            log(
                f"📡 DIRECT NOTIFICATION (unified pool): mon={monitor_identifier} trade={trade_id} status={status}"
            )
            with ats_monitor_bind(u, mid):
                success = process_trade_manager_notification_core(trade_id, ticket_id, status)
        else:
            if monitor_identifier and monitor_identifier != MONITOR_IDENTIFIER:
                log(f"📡 DIRECT NOTIFICATION: Ignoring notification for different monitor")
                log(f"📡 DIRECT NOTIFICATION: Expected: {MONITOR_IDENTIFIER}, Received: {monitor_identifier}")
                return jsonify(
                    {
                        "status": "ignored",
                        "message": f"Notification for different monitor: {monitor_identifier}",
                        "success": True,
                    }
                ), 200

            log(f"📡 DIRECT NOTIFICATION: Received from trade_manager for monitor {MONITOR_IDENTIFIER}")
            log(f"📡 DIRECT NOTIFICATION: Trade ID: {trade_id}, Ticket ID: {ticket_id}, Status: {status}")

            success = process_trade_manager_notification_core(trade_id, ticket_id, status)

        if status not in (
            "pending",
            "open",
            "error",
            "expired",
            "closing",
            "closed",
            "close_attempt_failed",
            "deleted",
        ):
            return jsonify(
                {"error": f"Unknown status: {status}", "success": False}
            ), 200

        # Always return 200 to trade_manager; surface failures in the JSON payload and logs
        return jsonify(
            {
                "status": "success" if success else "error",
                "message": f"Trade {trade_id} {status} notification processed",
                "success": success,
            }
        ), 200

    except Exception as e:
        log(f"❌ Error handling trade_manager notification: {e}")
        # Do not propagate HTTP 500 back to trade_manager; report error in payload instead
        return jsonify({"status": "error", "error": str(e), "success": False}), 200

def migrate_database_schema():
    """Migrate the database schema if needed"""
    pass

def init_active_trades_db():
    """Initialize the active trades database"""
    pass

def get_db_connection():
    """Get database connection with appropriate timeout (uses centralized config)."""
    return get_postgresql_connection()

def get_trades_db_connection():
    """Get connection to the main trades database"""
    return get_postgresql_connection()


_trades_venue_column_cache: Dict[str, str] = {}


def trades_venue_sql_column(user_num: str) -> str:
    """
    Column on users_<user>.trades_<user> that holds execution venue slug.
    Post-migration name is exchange; older DBs still have market.
    """
    u = str(user_num).strip()
    if not re.fullmatch(r"\d{4}", u):
        return "exchange"
    if u in _trades_venue_column_cache:
        return _trades_venue_column_cache[u]
    col = "exchange"
    pg_schema = f"users_{u}"
    conn = get_postgresql_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                      AND column_name IN ('exchange', 'market')
                    ORDER BY CASE column_name WHEN 'exchange' THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (pg_schema, f"trades_{u}"),
                )
                row = cur.fetchone()
                if row and row[0] in ("exchange", "market"):
                    col = row[0]
        except Exception:
            pass
        finally:
            conn.close()
    _trades_venue_column_cache[u] = col
    return col


def add_new_active_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Add a new trade to the active trades database when trade_manager confirms it as open.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully added, False otherwise
    """
    try:
        # Get the trade data from PostgreSQL
        conn = get_trades_db_connection()
        cursor = conn.cursor()
        vcol = trades_venue_sql_column(ctx_user())
        cursor.execute(f"""
            SELECT id, ticket_id, date, time, strike, side, buy_price, position,
                   contract, ticker, symbol, {vcol}, trade_strategy, symbol_open,
                   momentum, prob, fees, diff
            FROM {legacy_users_trades(ctx_user())}
            WHERE id = %s AND LOWER(TRIM(status)) IN ('open', 'partial')
        """, (trade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            log(f"No open/partial trade found with id {trade_id}")
            return False
            
        # Unpack the row data
        (db_id, ticket_id, date, time, strike, side, buy_price, position,
         contract, ticker, symbol, exchange, trade_strategy, symbol_open,
         momentum, prob, fees, diff) = row
        
        # Insert into active trades database
        # Initialize high_price and low_price to buy_price for active trades
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(
            f"SELECT id, status FROM users.{active_trades_table} WHERE trade_id = %s",
            (trade_id,),
        )
        existing = cursor.fetchone()
        if existing:
            st_raw = existing[1]
            st = str(st_raw or "").strip().lower()
            if st == "active":
                # Keep active pool row synchronized with canonical trades row values.
                # This is critical for stop-loss logic after partial/top-up fills where
                # position/buy_price/fees may change while status stays active.
                if ATS_UNIFIED_POOL:
                    cursor.execute(
                        f"""
                        UPDATE users.{active_trades_table}
                        SET ticket_id = %s,
                            date = %s,
                            time = %s,
                            strike = %s,
                            side = %s,
                            buy_price = %s,
                            position = %s,
                            contract = %s,
                            ticker = %s,
                            symbol = %s,
                            exchange = %s,
                            trade_strategy = %s,
                            symbol_open = %s,
                            momentum = %s,
                            prob = %s,
                            fees = %s,
                            diff = %s
                        WHERE trade_id = %s AND status = 'active' AND monitor_id = %s
                        """,
                        (
                            ticket_id,
                            date,
                            time,
                            strike,
                            side,
                            buy_price,
                            position,
                            contract,
                            ticker,
                            symbol,
                            exchange,
                            trade_strategy,
                            symbol_open,
                            momentum,
                            prob,
                            fees,
                            diff,
                            trade_id,
                            ctx_mid(),
                        ),
                    )
                else:
                    cursor.execute(
                        f"""
                        UPDATE users.{active_trades_table}
                        SET ticket_id = %s,
                            date = %s,
                            time = %s,
                            strike = %s,
                            side = %s,
                            buy_price = %s,
                            position = %s,
                            contract = %s,
                            ticker = %s,
                            symbol = %s,
                            exchange = %s,
                            trade_strategy = %s,
                            symbol_open = %s,
                            momentum = %s,
                            prob = %s,
                            fees = %s,
                            diff = %s
                        WHERE trade_id = %s AND status = 'active'
                        """,
                        (
                            ticket_id,
                            date,
                            time,
                            strike,
                            side,
                            buy_price,
                            position,
                            contract,
                            ticker,
                            symbol,
                            exchange,
                            trade_strategy,
                            symbol_open,
                            momentum,
                            prob,
                            fees,
                            diff,
                            trade_id,
                        ),
                    )
                conn.commit()
                conn.close()
                log_debug(f"Trade {trade_id} already active; refreshed pool row from trades")
                return True
            if st == "pending":
                conn.close()
                return confirm_pending_trade(trade_id, ticket_id)
            if st == "closing":
                conn.close()
                log_debug(f"Trade {trade_id} already in closing state in pool (skip insert)")
                return True
            # Stale terminal row (closed/removed/etc.) still holds unique trade_id — sync would
            # think the trade is missing and retry INSERT → duplicate key. Replace the row.
            log_debug(
                f"Trade {trade_id} pool row status={st_raw!r} not open lifecycle; "
                f"deleting stale row before re-enroll ({ctx_ident()})"
            )
            cursor.execute(
                f"DELETE FROM users.{active_trades_table} WHERE trade_id = %s",
                (trade_id,),
            )
            conn.commit()

        if ATS_UNIFIED_POOL:
            # Always set status: some tenant pool tables were created without DEFAULT 'active', leaving NULL
            # rows that monitoring COUNT queries (status IN (...)) never see.
            cursor.execute(f"""
                INSERT INTO users.{active_trades_table} (
                    monitor_id, trade_id, ticket_id, date, time, strike, side, buy_price, position,
                    contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                    momentum, prob, fees, diff, high_price, low_price, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
            """, (
                ctx_mid(), trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, fees, diff, buy_price, buy_price
            ))
        else:
            cursor.execute(f"""
                INSERT INTO users.{active_trades_table} (
                    trade_id, ticket_id, date, time, strike, side, buy_price, position,
                    contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                    momentum, prob, fees, diff, high_price, low_price
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, fees, diff, buy_price, buy_price
            ))
        
        conn.commit()
        conn.close()
        
        # Log the new open trade with detailed information
        log(f"🆕 NEW OPEN TRADE ADDED TO ACTIVE_TRADES.DB")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   Ticker: {ticker}")
        log(f"   Strike: {strike}")
        log(f"   Side: {side}")
        log(f"   Buy Price: ${buy_price}")
        log(f"   Position: {position}")
        log(f"   Contract: {contract}")
        log(f"   Strategy: {trade_strategy}")
        log(f"   Entry Time: {date} {time}")
        log(f"   Prob: {prob}%")
        log(f"   Diff: {diff}")
        log(f"   Fees: ${fees}")
        log(f"   Symbol Open: ${symbol_open}")
        log(f"   Momentum: {momentum}")

        log(f"   Exchange: {exchange}")
        log(f"   Symbol: {symbol}")
        log(f"   ========================================")
        
        # Invalidate cache when new trade is added
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        start_monitoring_loop()
        
        return True
        
    except Exception as e:
        log(f"❌ Error adding new active trade {trade_id}: {e}")
        return False

def add_pending_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Add a new pending trade to the active trades database when trade_manager creates it.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully added, False otherwise
    """
    try:
        # Get the trade data from trades.db
        conn = get_trades_db_connection()
        cursor = conn.cursor()
        vcol = trades_venue_sql_column(ctx_user())
        cursor.execute(f"""
            SELECT id, ticket_id, date, time, strike, side, buy_price, position,
                   contract, ticker, symbol, {vcol}, trade_strategy, symbol_open,
                   momentum, prob, fees, diff
            FROM {legacy_users_trades(ctx_user())}
            WHERE id = %s AND status = 'pending'
        """, (trade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            # Common race: by the time ATS receives "pending", trade_manager may have already
            # advanced the row to open/closed and pending no longer exists.
            # Treat this as idempotent by checking canonical trade status.
            tr_conn = get_trades_db_connection()
            tr_status = None
            if tr_conn:
                try:
                    tr_cur = tr_conn.cursor()
                    tr_cur.execute(
                        f"SELECT status FROM {legacy_users_trades(ctx_user())} WHERE id = %s",
                        (trade_id,),
                    )
                    tr_row = tr_cur.fetchone()
                    if tr_row and tr_row[0]:
                        tr_status = str(tr_row[0]).strip().lower()
                except Exception:
                    tr_status = None
                finally:
                    tr_conn.close()

            if tr_status in ("open", "partial"):
                log_debug(
                    f"Pending notify race for trade {trade_id}: row already open/partial; enrolling as active"
                )
                return add_new_active_trade(trade_id, ticket_id)
            if tr_status in ("closing", "closed", "expired", "error", "deleted"):
                log_debug(
                    f"Pending notify stale for trade {trade_id}: status={tr_status}; skipping"
                )
                return True

            log(f"No pending trade found with id {trade_id}")
            return False
            
        # Unpack the row data
        (db_id, ticket_id, date, time, strike, side, buy_price, position,
         contract, ticker, symbol, exchange, trade_strategy, symbol_open,
         momentum, prob, fees, diff) = row
        
        # Insert into active trades database with 'pending' status
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        if ATS_UNIFIED_POOL:
            cursor.execute(f"""
                INSERT INTO users.{active_trades_table} (
                    monitor_id, trade_id, ticket_id, date, time, strike, side, buy_price, position,
                    contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                    momentum, prob, fees, diff, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """, (
                ctx_mid(), trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, fees, diff
            ))
        else:
            cursor.execute(f"""
                INSERT INTO users.{active_trades_table} (
                    trade_id, ticket_id, date, time, strike, side, buy_price, position,
                    contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                    momentum, prob, fees, diff, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """, (
                trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, fees, diff
            ))
        
        conn.commit()
        conn.close()
        
        # Log the new pending trade
        log(f"⏳ NEW PENDING TRADE ADDED TO ACTIVE_TRADES.DB")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   Ticker: {ticker}")
        log(f"   Strike: {strike}")
        log(f"   Side: {side}")
        log(f"   Contract: {contract}")
        log(f"   Strategy: {trade_strategy}")
        log(f"   Entry Time: {date} {time}")
        log(f"   Prob: {prob}%")
        log(f"   Exchange: {exchange}")
        log(f"   Symbol: {symbol}")
        log(f"   ========================================")
        
        # Invalidate cache when new trade is added
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        start_monitoring_loop()
        
        return True
        
    except Exception as e:
        log(f"❌ Error adding pending trade {trade_id}: {e}")
        return False

def confirm_pending_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Confirm a pending trade has been filled and update it to 'active' status.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully confirmed, False otherwise
    """
    try:
        # Get the updated trade data from PostgreSQL
        conn = get_trades_db_connection()
        cursor = conn.cursor()
        vcol = trades_venue_sql_column(ctx_user())
        cursor.execute(f"""
            SELECT id, ticket_id, date, time, strike, side, buy_price, position,
                   contract, ticker, symbol, {vcol}, trade_strategy, symbol_open,
                   momentum, prob, fees, diff
            FROM {legacy_users_trades(ctx_user())}
            WHERE id = %s AND LOWER(TRIM(status)) IN ('open', 'partial')
        """, (trade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            log(f"No open/partial trade found with id {trade_id}")
            return False
            
        # Unpack the row data
        (db_id, ticket_id, date, time, strike, side, buy_price, position,
         contract, ticker, symbol, exchange, trade_strategy, symbol_open,
         momentum, prob, fees, diff) = row
        
        # Update the pending row to active and refresh from trades (incl. exchange — trades.market → exchange).
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        scope_sql, scope_params = _active_trades_monitor_scope_sql()
        q = f"""
            UPDATE users.{active_trades_table}
            SET status = 'active',
                ticket_id = %s,
                date = %s,
                time = %s,
                strike = %s,
                side = %s,
                buy_price = %s,
                position = %s,
                contract = %s,
                ticker = %s,
                symbol = %s,
                exchange = %s,
                trade_strategy = %s,
                symbol_open = %s,
                momentum = %s,
                prob = %s,
                fees = %s,
                diff = %s,
                high_price = %s,
                low_price = %s
            WHERE trade_id = %s AND status = 'pending'{scope_sql}
        """
        cursor.execute(
            q,
            (
                ticket_id,
                date,
                time,
                strike,
                side,
                buy_price,
                position,
                contract,
                ticker,
                symbol,
                exchange,
                trade_strategy,
                symbol_open,
                momentum,
                prob,
                fees,
                diff,
                buy_price,
                buy_price,
                trade_id,
            )
            + scope_params,
        )
        
        if cursor.rowcount == 0:
            cursor.execute(
                f"SELECT status FROM users.{active_trades_table} WHERE trade_id = %s{scope_sql}",
                (trade_id,) + scope_params,
            )
            already = cursor.fetchone()
            if already and str(already[0] or "").strip().lower() == "active":
                conn.close()
                log_debug(
                    f"Trade {trade_id} already active in pool (confirm idempotent) ({ctx_ident()})"
                )
                return True
            log(f"No pending trade found in active_trades.db for trade_id {trade_id}")
            conn.close()
            return False

        conn.commit()
        conn.close()

        # Log the confirmed trade
        log(f"✅ PENDING TRADE CONFIRMED AND ACTIVATED")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   Ticker: {ticker}")
        log(f"   Strike: {strike}")
        log(f"   Side: {side}")
        log(f"   Buy Price: ${buy_price}")
        log(f"   Position: {position}")
        log(f"   Contract: {contract}")
        log(f"   Strategy: {trade_strategy}")
        log(f"   Entry Time: {date} {time}")
        log(f"   Prob: {prob}%")
        log(f"   Diff: {diff}")
        log(f"   Fees: ${fees}")
        log(f"   Symbol Open: ${symbol_open}")
        log(f"   Momentum: {momentum}")
        log(f"   Exchange: {exchange}")
        log(f"   Symbol: {symbol}")
        log(f"   ========================================")
        
        # Invalidate cache when trade is confirmed
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        start_monitoring_loop()
        
        return True
        
    except Exception as e:
        log(f"❌ Error confirming pending trade {trade_id}: {e}")
        return False

def remove_pending_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Remove a pending trade that failed to fill from active_trades.db.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully removed, False otherwise
    """
    try:
        # Remove the pending trade from active_trades.db
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            DELETE FROM users.{active_trades_table}
            WHERE trade_id = %s AND status = 'pending'
        """, (trade_id,))
        
        if cursor.rowcount == 0:
            log_debug(
                f"No pending row in active_trades pool for trade_id={trade_id} "
                f"(remove idempotent)"
            )
            conn.close()
            return True
        
        conn.commit()
        conn.close()
        
        # Log the removed pending trade
        log(f"❌ PENDING TRADE REMOVED (NO FILL)")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   ========================================")
        
        # Invalidate cache when trade is removed
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        return True
        
    except Exception as e:
        log(f"❌ Error removing pending trade {trade_id}: {e}")
        return False

def remove_failed_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Remove a trade from the monitor's active_trades *pool* table (PostgreSQL
    ``users.active_trades_15m_*`` / ``active_trades_hourly_*``), e.g. after
    ``error`` or ``deleted`` from trade_manager. Does not touch ``trades_*``.

    Idempotent: if there is no pool row (common for precheck-cancelled trades
    that never enrolled), return True so callers do not treat it as a failure.
    """
    try:
        # Remove the failed trade from active_trades.db (any status)
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            DELETE FROM users.{active_trades_table}
            WHERE trade_id = %s
        """, (trade_id,))
        
        if cursor.rowcount == 0:
            log_debug(
                f"No active_trades pool row for trade_id={trade_id} "
                f"(delete idempotent; ok for deleted/error sync)"
            )
            conn.close()
            return True
        
        conn.commit()
        conn.close()
        
        # Log the removed failed trade
        log(f"❌ FAILED TRADE REMOVED (ERROR STATUS)")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   ========================================")
        
        # Invalidate cache when trade is removed
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        return True
        
    except Exception as e:
        log(f"❌ Error removing failed trade {trade_id}: {e}")
        return False

def remove_closed_trade(trade_id: int) -> bool:
    """
    Remove a trade from active trades when it's closed.
    
    Args:
        trade_id: The ID from trades.db
        
    Returns:
        bool: True if successfully removed, False otherwise
    """
    try:
        # Check if trade exists before trying to remove it
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE trade_id = %s", (trade_id,))
        exists = cursor.fetchone()[0] > 0
        conn.close()
        
        if not exists:
            # Trade doesn't exist, no need to log this as an error
            return True  # Consider this a successful "no-op"
        
        # Remove the trade
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM users.{active_trades_table} WHERE trade_id = %s", (trade_id,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            log(f"🔚 CLOSED TRADE REMOVED FROM ACTIVE_TRADES.DB")
            log(f"   Trade ID: {trade_id}")
            log(f"   ========================================")
            
            # Invalidate cache when trade is removed
            invalidate_active_trades_cache()
            
            # Broadcast active trades change
            broadcast_active_trades_change()
            
            return True
        else:
            log(f"⚠️ No active trade found to remove: id={trade_id}")
            return False
            
    except Exception as e:
        log(f"❌ Error removing closed trade {trade_id}: {e}")
        return False


def _users_trade_status_for_stale_flush(trade_id: int) -> Optional[str]:
    """Best-effort status from users.trades_* for traceability."""
    try:
        conn = get_trades_db_connection()
        if not conn:
            return None
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT status FROM {legacy_users_trades(ctx_user())} WHERE id = %s",
                (trade_id,),
            )
            row = cur.fetchone()
        conn.close()
        if row and row[0] is not None:
            return str(row[0])
        return None
    except Exception as e:
        log_debug(f"[STALE FLUSH] users.trades lookup failed trade_id={trade_id}: {e}")
        return None


def flush_stale_active_trades_past_contract_settlement() -> None:
    """
    DELETE active_trades rows that are still present but Kalshi settlement was more than
    STALE_ACTIVE_TRADE_FLUSH_AFTER_SETTLEMENT ago. Covers lapses in trade_manager expiry or
    price feeds without posting close orders (those are suppressed earlier).

    Logs one INFO line per removed row with identifiers and users.trades status for postmortems.
    """
    est_now = wall_now()
    min_past_settlement = STALE_ACTIVE_TRADE_FLUSH_AFTER_SETTLEMENT
    tbl = get_monitor_active_trades_table()

    conn = get_postgresql_connection()
    if not conn:
        log_debug("[STALE FLUSH] skipped — no PostgreSQL connection")
        return
    try:
        if ATS_UNIFIED_POOL:
            q = f"""
                SELECT id, trade_id, ticket_id, monitor_id, ticker, status, contract, symbol,
                       trade_strategy, strike, side, created_at, last_updated
                FROM users.{tbl}
                WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
            """
        else:
            q = f"""
                SELECT id, trade_id, ticket_id, ticker, status, contract, symbol,
                       trade_strategy, strike, side, created_at, last_updated
                FROM users.{tbl}
                WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
            """
        with conn.cursor() as cur:
            cur.execute(q)
            colnames = [d[0] for d in cur.description]
            fetched = cur.fetchall()
    except Exception as e:
        log(f"[STALE FLUSH] failed to list rows from users.{tbl}: {e}")
        conn.close()
        return
    conn.close()

    to_delete: List[Any] = []
    for row in fetched:
        r = dict(zip(colnames, row))
        ticker = r.get("ticker")
        end = kalshi_contract_settlement_end_est(ticker if isinstance(ticker, str) else None)
        if end is None:
            continue
        if est_now <= end + min_past_settlement:
            continue
        trade_id = r.get("trade_id")
        main_st = _users_trade_status_for_stale_flush(int(trade_id)) if trade_id is not None else None
        mon_disp = r.get("monitor_id") if ATS_UNIFIED_POOL else ctx_mid()
        age_sec = (est_now - end).total_seconds()
        log(
            "[STALE FLUSH] scheduled DELETE — "
            f"active_trades_table={tbl} row_id={r.get('id')} trade_id={trade_id} "
            f"monitor_id={mon_disp!r} ticket_id={r.get('ticket_id')!r} "
            f"active_row_status={r.get('status')!r} ticker={ticker!r} "
            f"contract={r.get('contract')!r} symbol={r.get('symbol')!r} "
            f"trade_strategy={r.get('trade_strategy')!r} strike={r.get('strike')!r} side={r.get('side')!r} "
            f"settlement_end_est={end.isoformat()} "
            f"seconds_past_settlement={age_sec:.0f} "
            f"required_past_settlement_sec={min_past_settlement.total_seconds():.0f} "
            f"users_trades_status={main_st!r} "
            f"created_at={r.get('created_at')} last_updated={r.get('last_updated')}"
        )
        row_pk = r.get("id")
        if row_pk is not None:
            to_delete.append(row_pk)

    if not to_delete:
        return

    conn = get_postgresql_connection()
    if not conn:
        return
    try:
        removed = 0
        with conn.cursor() as cur:
            for row_pk in to_delete:
                cur.execute(f"DELETE FROM users.{tbl} WHERE id = %s", (row_pk,))
                removed += cur.rowcount
        conn.commit()
        log(
            f"[STALE FLUSH] completed — table={tbl} deleted_rows={removed} "
            f"(cutoff = settlement_end + {min_past_settlement!r} America/New_York)"
        )
    except Exception as e:
        log(f"[STALE FLUSH] DELETE batch failed for users.{tbl}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

    invalidate_active_trades_cache()
    broadcast_active_trades_change()

def update_trade_status_to_closing(trade_id: int) -> bool:
    """
    Update a trade's status to 'closing' in active_trades.db.
    
    Args:
        trade_id: The ID from trades.db
        
    Returns:
        bool: True if successfully updated, False otherwise
    """
    try:
        # Check if trade exists in active_trades.db
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE trade_id = %s", (trade_id,))
        exists = cursor.fetchone()[0] > 0
        conn.close()
        
        if not exists:
            log(f"⚠️ No active trade found to update status: id={trade_id}")
            return False
        
        # Update the trade status to 'closing'
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"UPDATE users.{active_trades_table} SET status = 'closing' WHERE trade_id = %s", (trade_id,))
        updated_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if updated_count > 0:
            log(f"🔄 TRADE STATUS UPDATED TO CLOSING IN ACTIVE_TRADES.DB")
            log(f"   Trade ID: {trade_id}")
            log(f"   ========================================")
            
            # Invalidate cache when trade status changes
            invalidate_active_trades_cache()
            
            # Broadcast active trades change immediately for status change
            broadcast_active_trades_change()
            
            return True
        else:
            log(f"⚠️ No active trade found to update status: id={trade_id}")
            return False
            
    except Exception as e:
        log(f"❌ Error updating trade status to closing {trade_id}: {e}")
        return False

def get_current_symbol_price(symbol: str = None) -> Optional[Decimal]:
    """Latest spot from live_data.live_price_log_1s_<symbol> as Decimal (full DB precision)."""
    try:
        # Use current monitor symbol if no symbol specified
        if symbol is None:
            symbol = get_current_monitor_symbol()
        
        # Get PostgreSQL connection
        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL")
            return None
            
        cursor = conn.cursor()
        
        # Map symbol to the appropriate price log table
        table_name = f"live_data.live_price_log_1s_{symbol.lower()}"
            
        cursor.execute(f"SELECT price FROM {table_name} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            raw = result[0]
            price = raw if isinstance(raw, Decimal) else Decimal(str(raw))
            # Only log price every 30 seconds to reduce noise
            current_time = time.time()
            if not hasattr(get_current_symbol_price, 'last_log_time') or current_time - get_current_symbol_price.last_log_time > 30:
                # Only log price occasionally to reduce noise
                get_current_symbol_price.last_log_time = current_time
            return price
        else:
            log(f"⚠️ No {symbol} price found in PostgreSQL database")
            return None
            
    except Exception as e:
        log(f"Error getting current {symbol} price: {e}")
        return None

def get_kalshi_market_snapshot(symbol: str = None, market: str = None) -> Optional[Dict[str, Any]]:
    """Get the latest Kalshi market snapshot data from PostgreSQL.
    15m: reads configured unified source (`market_kalshi_ws_15m` default, legacy fallback `market_kalshi_15m`).
    Legacy per-symbol ``market_kalshi_15m_btc`` tables are not updated by that pipeline and are ignored.
    Hourly: unified ``live_data.market_kalshi_hourly`` (filter by symbol)."""
    try:
        # Use current monitor symbol and market if not specified
        if symbol is None or market is None:
            sym, mkt = get_current_monitor_symbol_and_market()
            if symbol is None:
                symbol = sym
            if market is None:
                market = mkt or "hourly"
        market = (market or "hourly").strip().lower()
        if market not in ("hourly", "15m"):
            market = "hourly"
        sym_u = (symbol or "BTC").strip().upper()

        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL")
            return None

        cursor = conn.cursor()

        if market == "15m":
            source = os.getenv("KALSHI_15M_MARKET_SOURCE", "legacy").strip().lower()
            market_table = "market_kalshi_ws_15m" if source == "ws" else "market_kalshi_15m"
            cursor.execute(
                f"""
                SELECT
                    market_ticker,
                    yes_ask_dollars,
                    no_ask_dollars,
                    volume_fp,
                    event_ticker,
                    strike
                FROM live_data.{market_table}
                WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                  AND UPPER(TRIM(symbol::text)) = %s
                ORDER BY updated_at DESC
                """,
                (sym_u,),
            )
        else:
            cursor.execute(
                """
                SELECT
                    market_ticker,
                    yes_ask_dollars,
                    no_ask_dollars,
                    volume_fp,
                    event_ticker,
                    strike
                FROM live_data.market_kalshi_hourly
                WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                  AND UPPER(TRIM(symbol::text)) = %s
                ORDER BY updated_at DESC
                """,
                (sym_u,),
            )

        markets_data = cursor.fetchall()
        conn.close()

        if not markets_data:
            log("⚠️ No Kalshi market data found in PostgreSQL")
            return None

        # Convert to the same format as the JSON file (volume_fp -> "volume" for compatibility)
        markets = []
        for row in markets_data:
            mk = {
                "ticker": row[0],
                "yes_ask_dollars": row[1],
                "no_ask_dollars": row[2],
                "volume": row[3],
                "event_ticker": row[4],
                "strike": row[5],
            }
            markets.append(mk)
        
        # Return in the same format as the JSON file
        return {
            "markets": markets,
            "timestamp": wall_now().isoformat()
        }
        
    except Exception as e:
        log(f"Error reading Kalshi market snapshot from PostgreSQL: {e}")
        return None


# Per (symbol, market) so unified 15m does not reuse hourly/BTC stale rows for ETH 15m, etc.
_kalshi_snapshot_cache: Dict[str, Dict[str, Any]] = {}
KALSHI_SNAPSHOT_STALE_MAX_SEC = 120.0

# Stop-loss floor: consecutive ticks where opp ask is past threshold (anti single-tick glitch).
_stop_loss_floor_confirm_ticks: Dict[int, int] = {}


def _stop_loss_floor_guard_enabled() -> bool:
    return os.getenv("ATS_STOP_LOSS_FLOOR_GUARD", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _stop_loss_floor_max_quote_disagree() -> float:
    try:
        return max(0.01, float(os.getenv("ATS_STOP_LOSS_FLOOR_MAX_QUOTE_DISAGREE", "0.18")))
    except ValueError:
        return 0.18


def _stop_loss_floor_confirm_ticks_required() -> int:
    try:
        v = int(os.getenv("ATS_STOP_LOSS_FLOOR_CONFIRM_TICKS", "2"))
        return max(1, min(v, 10))
    except ValueError:
        return 2


def _stop_loss_floor_prob_mark_divergence_max_points() -> float:
    """
    If > 0: do not fire stop-loss floor when model probability (0–100) exceeds
    implied exit mark in \"points\" by more than this amount.

    Implied exit mark uses complementary of opposite-side ask in contract space:
    ``(1 - opp_ask) * 100`` (same scale as ``sell_price * 100`` for the NO leg when
    ``opp_ask`` is YES ask). Catches bogus high YES-ask ticks while probability
    still shows a strong winning position.

    Set env ``ATS_STOP_LOSS_FLOOR_PROB_MARK_DIVERGENCE_POINTS`` to 0 to disable.
    """
    try:
        v = float(os.getenv("ATS_STOP_LOSS_FLOOR_PROB_MARK_DIVERGENCE_POINTS", "50"))
        return max(0.0, v)
    except ValueError:
        return 50.0


def _kalshi_snapshot_cache_key(symbol: str, market: str) -> str:
    s = (symbol or "BTC").strip().lower()
    m = (market or "hourly").strip().lower()
    if m not in ("hourly", "15m"):
        m = "hourly"
    return f"{s}:{m}"


def _normalize_kalshi_ticker(t: Optional[str]) -> str:
    if t is None:
        return ""
    return str(t).strip().upper()


_last_market_notfound_log: Dict[str, float] = {}


def _log_market_notfound_throttled(ticker: str, interval_sec: float = 60.0) -> None:
    """Rate-limit noisy per-tick warnings when ladder omits a contract (rotation, etc.)."""
    key = _normalize_kalshi_ticker(ticker)
    now = time.time()
    last = _last_market_notfound_log.get(key, 0.0)
    if not key:
        return
    if now - last >= interval_sec:
        _last_market_notfound_log[key] = now
        log(f"⚠️ Market not found for ticker: {ticker}")
    else:
        log_debug(f"⚠️ Market not found for ticker (throttled): {ticker}")


def _kalshi_direct_closing_price_for_ticker(
    trade_ticker: str,
    trade_side: str,
    symbol: Optional[str],
    market: str,
) -> Optional[float]:
    """
    Point lookup in live_data Kalshi tables when the bulk snapshot list misses a row
    (normalization, race, or rare ingestion gaps). Same tables as get_kalshi_market_snapshot.
    """
    tt = _normalize_kalshi_ticker(trade_ticker)
    if not tt:
        return None
    sym_u = (symbol or "").strip().upper()
    mkt = (market or "hourly").strip().lower()
    if mkt not in ("hourly", "15m"):
        mkt = "hourly"
    conn = get_postgresql_connection()
    if not conn:
        return None
    side_u = (trade_side or "").strip().upper()
    if side_u in ("YES",):
        side_u = "Y"
    if side_u in ("NO",):
        side_u = "N"
    try:
        cursor = conn.cursor()
        row = None
        if mkt == "15m":
            source = os.getenv("KALSHI_15M_MARKET_SOURCE", "legacy").strip().lower()
            market_table = "market_kalshi_ws_15m" if source == "ws" else "market_kalshi_15m"
            cursor.execute(
                f"""
                SELECT yes_ask_dollars, no_ask_dollars
                FROM live_data.{market_table}
                WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                  AND UPPER(TRIM(market_ticker::text)) = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tt,),
            )
            row = cursor.fetchone()
            if row is None and sym_u:
                cursor.execute(
                    f"""
                    SELECT yes_ask_dollars, no_ask_dollars
                    FROM live_data.{market_table}
                    WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                      AND UPPER(TRIM(symbol::text)) = %s
                      AND UPPER(TRIM(market_ticker::text)) = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (sym_u, tt),
                )
                row = cursor.fetchone()
        else:
            cursor.execute(
                """
                SELECT yes_ask_dollars, no_ask_dollars
                FROM live_data.market_kalshi_hourly
                WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                  AND UPPER(TRIM(market_ticker::text)) = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tt,),
            )
            row = cursor.fetchone()
            if row is None and sym_u:
                cursor.execute(
                    """
                    SELECT yes_ask_dollars, no_ask_dollars
                    FROM live_data.market_kalshi_hourly
                    WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                      AND UPPER(TRIM(symbol::text)) = %s
                      AND UPPER(TRIM(market_ticker::text)) = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (sym_u, tt),
                )
                row = cursor.fetchone()
        if not row:
            return None
        yes_d, no_d = row[0], row[1]
        if side_u == "Y":
            closing_price_dollars = no_d
        elif side_u == "N":
            closing_price_dollars = yes_d
        else:
            log(f"⚠️ Unknown trade side: {trade_side}")
            return None
        if closing_price_dollars is None:
            return None
        return float(closing_price_dollars)
    except Exception as e:
        log_debug(f"direct Kalshi quote for {trade_ticker}: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_kalshi_market_snapshot_cached(
    symbol: str = None, market: str = None,
) -> Optional[Dict[str, Any]]:
    """Like get_kalshi_market_snapshot but reuse the last good snapshot for up to KALSHI_SNAPSHOT_STALE_MAX_SEC."""
    global _kalshi_snapshot_cache
    if symbol is None or market is None:
        sym, mkt = get_current_monitor_symbol_and_market()
        if symbol is None:
            symbol = sym
        if market is None:
            market = mkt or "hourly"
    market = (market or "hourly").strip().lower()
    if market not in ("hourly", "15m"):
        market = "hourly"
    symbol = (symbol or "BTC").strip().upper()
    key = _kalshi_snapshot_cache_key(symbol, market)

    fresh = get_kalshi_market_snapshot(symbol, market)
    if fresh and fresh.get("markets"):
        _kalshi_snapshot_cache[key] = {"t": time.time(), "data": fresh}
        return fresh
    entry = _kalshi_snapshot_cache.get(key) or {}
    age = time.time() - float(entry.get("t") or 0)
    stale = entry.get("data")
    if stale and stale.get("markets") and age < KALSHI_SNAPSHOT_STALE_MAX_SEC:
        log_debug(f"Using stale Kalshi snapshot ({key}, age {age:.1f}s)")
        return stale
    return fresh


def get_current_closing_price_for_trade(
    trade_ticker: str,
    trade_side: str,
    snapshot_data: Optional[Dict[str, Any]] = None,
    *,
    symbol: Optional[str] = None,
    market: Optional[str] = None,
) -> Optional[float]:
    """
    Get the current closing price for a specific trade from Kalshi market snapshot.
    
    Args:
        trade_ticker: The ticker of the trade (e.g., "KXBTCD-25JUL1617-T119499.99" or "KXETHD-25JUL1617-T119499.99")
        trade_side: The side of the trade ("Y" for YES, "N" for NO)
        snapshot_data: Optional pre-fetched snapshot (e.g. cached); default uses get_kalshi_market_snapshot_cached.
        symbol: Trade symbol for DB point-lookup when the snapshot omits the ticker.
        market: Monitor market ('hourly' or '15m') for DB fallback.

    Returns:
        The closing price as a decimal (e.g., 0.94 for 94 cents), or None if not found
    """
    try:
        if snapshot_data is None:
            snapshot_data = get_kalshi_market_snapshot_cached(
                symbol=symbol,
                market=market,
            )
        if not snapshot_data or "markets" not in snapshot_data:
            snapshot_data = {"markets": []}

        markets = snapshot_data["markets"]
        tt_norm = _normalize_kalshi_ticker(trade_ticker)
        side_u = (trade_side or "").strip().upper()
        if side_u in ("YES",):
            side_u = "Y"
        if side_u in ("NO",):
            side_u = "N"

        for mrec in markets:
            if _normalize_kalshi_ticker(mrec.get("ticker")) != tt_norm:
                continue
            if side_u == "Y":  # YES trade
                closing_price_dollars = mrec.get("no_ask_dollars")
            elif side_u == "N":  # NO trade
                closing_price_dollars = mrec.get("yes_ask_dollars")
            else:
                log(f"⚠️ Unknown trade side: {trade_side}")
                return None

            if closing_price_dollars is not None:
                return float(closing_price_dollars)
            log(f"⚠️ No closing price (_dollars) found for {trade_ticker} ({trade_side})")
            return None

        mkt_fb = market
        sym_fb = symbol
        if mkt_fb is None or sym_fb is None:
            sym_d, mkt_d = get_current_monitor_symbol_and_market()
            if mkt_fb is None:
                mkt_fb = mkt_d
            if sym_fb is None:
                sym_fb = sym_d
        direct = _kalshi_direct_closing_price_for_ticker(
            trade_ticker, trade_side, sym_fb, mkt_fb or "hourly"
        )
        if direct is not None:
            return direct

        _log_market_notfound_throttled(trade_ticker)
        return None

    except Exception as e:
        log(f"Error getting closing price for trade {trade_ticker}: {e}")
        return None


def get_current_probability_from_live_strike_table(
    trade_ticker: Optional[str],
    trade_symbol: str,
    trade_side: Optional[str],
) -> Optional[float]:
    """
    Model probability from the same live strike row the UI / strike_table_generator uses.

    Latest row for this Kalshi ``ticker``; side-aware (YES -> yes_prob_* , NO -> no_prob_*),
    with ``probability_hourly`` / ``probability_15m`` as fallback when a leg column is NULL.

    Returns None if the ticker is missing or no row exists yet (caller may fall back).
    """
    ticker = (trade_ticker or "").strip()
    if not ticker:
        return None
    sym, mkt = _get_symbol_and_market_for_strike(trade_symbol)
    table_name = get_strike_table_name(sym, mkt)
    if table_name not in ("strike_table_hourly", "strike_table_15m", "strike_table_ws_15m"):
        return None
    ladder = fetch_strike_ladder_prefer_snapshot(sym, mkt, DEFAULT_EXCHANGE)
    snap_row = find_ladder_strike_by_ticker(ladder, ticker)
    if snap_row is not None:
        v_snap = probability_from_strike_row_side_aware(snap_row, mkt, trade_side)
        if v_snap is not None:
            return v_snap
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT yes_prob_hourly, no_prob_hourly, probability_hourly,
                       yes_prob_15m, no_prob_15m, probability_15m
                FROM live_data.{table_name}
                WHERE ticker = %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (ticker,),
            )
            row = cursor.fetchone()
    except Exception as e:
        log_debug(
            "Strike-table prob by ticker failed ticker=%s table=%s: %s",
            ticker,
            table_name,
            e,
        )
        return None
    finally:
        conn.close()

    if not row:
        return None

    yh, nh, ph, y15, n15, p15 = row
    su = (trade_side or "").strip().upper()
    if su in ("Y", "YES"):
        if (mkt or "").strip().lower() == "15m":
            v = y15 if y15 is not None else p15
        else:
            v = yh if yh is not None else ph
    elif su in ("N", "NO"):
        if (mkt or "").strip().lower() == "15m":
            v = n15 if n15 is not None else p15
        else:
            v = nh if nh is not None else ph
    else:
        return None
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _get_lookup_probability_calculator(symbol_upper: str):
    """Strike-table generator's LookupProbabilityCalculator (analytics.probability_lookup_*_master_*)."""
    key = (symbol_upper or "BTC").strip().lower()
    if key in _lookup_probability_calculator_failed:
        return None
    cached = _lookup_probability_calculator_cache.get(key)
    if cached is not None:
        return cached
    try:
        from backend.strike_table_generator import LookupProbabilityCalculator

        calc = LookupProbabilityCalculator(symbol_upper or "BTC")
        _lookup_probability_calculator_cache[key] = calc
        return calc
    except Exception as e:
        log_debug(f"LookupProbabilityCalculator init failed for {symbol_upper}: {e}")
        _lookup_probability_calculator_failed.add(key)
        return None


def get_current_probability(strike: float, current_price: float, ttc_seconds: float, momentum_score: Optional[float] = None, symbol: str = None) -> Optional[float]:
    """
    Recompute model probability (LookupProbabilityCalculator + strike-table-by-strike fallback).

    Used only when ``get_current_probability_from_live_strike_table`` has no row for the
    trade ticker (e.g. empty table between refreshes). Normal monitoring reads the live
    strike row by ticker first.
    """
    sym, mkt = _get_symbol_and_market_for_strike(symbol)
    sym_u = sym or "BTC"
    cp = float(current_price)
    st = float(strike)
    ttc_i = int(round(float(ttc_seconds)))

    calc = _get_lookup_probability_calculator(sym_u)
    if calc is not None:
        try:
            from backend.strike_table_generator import round_price_buffer, uses_high_precision_price

            raw_buf = abs(cp - st)
            buffer = round_price_buffer(raw_buf) if uses_high_precision_price(sym_u) else float(raw_buf)
            mb = int(round(float(momentum_score))) if momentum_score is not None else 0
            pos_prob, neg_prob = calc.get_probability(ttc_i, float(buffer), mb)
            if pos_prob is not None and neg_prob is not None:
                return float(pos_prob) if st < cp else float(neg_prob)
        except Exception as e:
            log_debug(f"Master lookup probability failed ({sym_u}): {e}")

    ladder_fb = fetch_strike_ladder_prefer_snapshot(sym_u, mkt, DEFAULT_EXCHANGE)
    prob_ladder = probability_from_ladder_by_strike(ladder_fb, st, mkt)
    if prob_ladder is not None:
        return float(prob_ladder)

    try:
        table_name = get_strike_table_name(sym, mkt)
        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL for strike-table probability fallback")
            return None

        cursor = conn.cursor()

        prob_col = "probability_15m" if mkt == "15m" else "probability_hourly"
        if prob_col not in ("probability_15m", "probability_hourly"):
            prob_col = "probability_hourly"

        strike_key = int(round(float(strike)))

        cursor.execute(
            f"""
            SELECT {prob_col}
            FROM live_data.{table_name}
            WHERE strike = %s AND {prob_col} IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (strike_key,),
        )
        result = cursor.fetchone()

        if not result or result[0] is None:
            cursor.execute(
                f"""
                SELECT t.{prob_col}
                FROM live_data.{table_name} t
                INNER JOIN (
                    SELECT MAX(timestamp) AS ts FROM live_data.{table_name}
                ) u ON t.timestamp = u.ts
                WHERE t.{prob_col} IS NOT NULL
                ORDER BY ABS(t.strike - %s)
                LIMIT 1
                """,
                (strike_key,),
            )
            result = cursor.fetchone()
            if result and result[0] is not None:
                log_debug(
                    f"Probability fallback: nearest strike in latest batch for {sym}/{mkt} (wanted {strike_key})"
                )

        conn.close()

        if result and result[0] is not None:
            return float(result[0])
        log_debug(f"No strike-table probability for strike {strike_key} ({table_name})")

    except Exception as e:
        log(f"⚠️ Strike-table probability fallback exception: {e}")
    return None

def _iter_unified_pool_monitor_bindings_for_monitoring():
    """
    Monitors to tick in unified ATS: active rows in monitor_list for this pool, plus any
    monitor_id that still has an active row in the pool (reconcile may enroll paused monitors).
    """
    seen = set()
    out: List[Tuple[str, str]] = []
    if ATS_UNIFIED_ALL:
        from backend.core.unified_all_monitors import iter_active_unified_monitor_bindings

        iter_bindings = iter_active_unified_monitor_bindings()
    elif ATS_UNIFIED_15M:
        from backend.core.unified_15m_monitors import iter_active_15m_monitor_bindings

        iter_bindings = iter_active_15m_monitor_bindings()
    elif ATS_UNIFIED_HOURLY:
        from backend.core.unified_hourly_monitors import iter_active_hourly_monitor_bindings

        iter_bindings = iter_active_hourly_monitor_bindings()
    else:
        return out
    for u, m in iter_bindings:
        t = (u, m)
        if t not in seen:
            seen.add(t)
            out.append(t)
    u = USER_NUMBER
    pool_tables: List[str]
    if ATS_UNIFIED_ALL:
        wh = effective_tenant_context_for_sql_rewrite().user_no
        pool_tables = [
            legacy_active_trades_pool_15m(wh),
            legacy_active_trades_pool_hourly(wh),
        ]
    else:
        pool_tables = [get_monitor_active_trades_table()]
    conn = get_postgresql_connection(tenant_user_no=USER_NUMBER)
    if conn:
        try:
            with conn.cursor() as cur:
                for tbl in pool_tables:
                    cur.execute(
                        f"""
                        SELECT DISTINCT monitor_id FROM users.{tbl}
                        WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                        """
                    )
                    for (mid,) in cur.fetchall():
                        if mid is None:
                            continue
                        m = str(mid).strip()
                        t = (u, m)
                        if t not in seen:
                            seen.add(t)
                            out.append(t)
        except Exception as e:
            log_debug(f"monitor bindings from pool: {e}")
        finally:
            conn.close()
    return out


def update_active_trade_monitoring_data():
    """
    Update monitoring data for all active trades:
    - Current symbol price (live symbol price)
    - Current market ask prices from Kalshi snapshot
    - Buffer from strike (absolute value, negative when crossed)
    - Time since entry
    - Current probability from master prob lookup tables (same as strike_table_generator), then strike_table_* fallback, with buffer-based flip
    """
    try:
        # Get current symbol price for each trade
        # Note: We'll get the price per trade since each trade might have a different symbol
        
        # Snapshots keyed by trade symbol so rows match the correct Kalshi ladder (monitor symbol + ETH/BTC mismatches).
        sym, mkt = get_current_monitor_symbol_and_market()
        snap_cache: Dict[str, Dict[str, Any]] = {}

        def _snapshot_for_trade_symbol(trade_symbol) -> Dict[str, Any]:
            base = sym or "BTC"
            ts = trade_symbol
            if ts is not None and str(ts).strip():
                tsu = str(ts).strip().upper()
            else:
                tsu = str(base).strip().upper()
            key = _kalshi_snapshot_cache_key(tsu, mkt)
            if key not in snap_cache:
                sd = get_kalshi_market_snapshot_cached(symbol=tsu, market=mkt)
                snap_cache[key] = sd if sd else {"markets": [], "timestamp": None}
            out = snap_cache[key]
            if "markets" not in out:
                out["markets"] = []
            return out

        if not _snapshot_for_trade_symbol(sym).get("markets"):
            log_debug("⚠️ Kalshi snapshot empty; using per-trade DB fallbacks where possible")
        
        # Get all active trades
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        scope_sql, scope_params = _active_trades_monitor_scope_sql()
        cursor.execute(f"""
            SELECT id, trade_id, buy_price, position, fees, prob, time, date, strike, side, momentum, ticker, symbol, high_price, low_price, current_close_price
            FROM users.{active_trades_table} 
            WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') = 'active'{scope_sql}
        """, scope_params)
        active_trades = cursor.fetchall()
        conn.close()
        
        if not active_trades:
            return
        
        for (
            active_id,
            trade_id,
            buy_price,
            position,
            fees,
            prob,
            time_str,
            date_str,
            strike,
            side,
            momentum,
            ticker,
            symbol,
            current_high_price,
            current_low_price,
            current_close_price_db,
        ) in active_trades:
            try:
                # Parse strike price - handle currency formatting (Decimal: match spot precision)
                strike_clean = str(strike).replace('$', '').replace(',', '')
                try:
                    strike_price = Decimal(strike_clean)
                except InvalidOperation:
                    log(f"⚠️ Invalid strike for trade {trade_id}: {strike!r}")
                    continue
                
                # Get current symbol price for this specific trade
                current_symbol_price = get_current_symbol_price(symbol)
                if current_symbol_price is None:
                    log(f"⚠️ Could not get current {symbol} price for trade {trade_id}, skipping")
                    continue
                
                trade_sym_u = (
                    str(symbol).strip().upper()
                    if symbol is not None and str(symbol).strip()
                    else str(sym or "BTC").strip().upper()
                )
                snapshot_data = _snapshot_for_trade_symbol(trade_sym_u)
                current_market_price = get_current_closing_price_for_trade(
                    ticker,
                    side,
                    snapshot_data=snapshot_data,
                    symbol=trade_sym_u,
                    market=mkt,
                )
                if current_market_price is None and current_close_price_db is not None:
                    current_market_price = float(current_close_price_db)
                    log_debug(
                        f"Trade {trade_id}: using last stored current_close_price (stale quote fallback)"
                    )
                if current_market_price is None:
                    log(f"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping")
                    continue
                
                # Calculate buffer using the actual symbol price difference from strike
                # Buffer = current_symbol_price - strike_price
                # For YES trades: positive buffer when symbol > strike (safe), negative when symbol < strike (dangerous)
                # For NO trades: positive buffer when symbol < strike (safe), negative when symbol > strike (dangerous)
                raw_buffer = current_symbol_price - strike_price
                
                if side.upper() == 'Y':  # YES trade
                    # For YES trades, positive buffer when symbol > strike (safe)
                    buffer_from_strike = raw_buffer
                else:  # NO trade
                    # For NO trades, positive buffer when symbol < strike (safe)
                    # So we need to flip the sign
                    buffer_from_strike = -raw_buffer
                
                # Calculate time since entry
                try:
                    if hasattr(date_str, 'year') and hasattr(time_str, 'hour'):
                        # Handle new date/time objects
                        entry_datetime = datetime.combine(date_str, time_str)
                    else:
                        # Handle legacy text format
                        entry_datetime = datetime.strptime(f"{str(date_str)} {str(time_str)}", "%Y-%m-%d %H:%M:%S")
                    entry_datetime = entry_datetime.replace(tzinfo=EST)
                except Exception as e:
                    log(f"Error calculating entry_datetime for trade {trade_id}: {e}, date_str: {date_str}, time_str: {time_str}")
                    # Use current time as fallback
                    entry_datetime = wall_now()
                now = wall_now()
                time_since_entry = int((now - entry_datetime).total_seconds())
                
                # Get unified TTC from master strike table
                ttc_seconds = get_unified_ttc_seconds(symbol)
                
                # Get momentum score if available
                momentum_score = float(momentum) if momentum is not None else None

                buy_price_float = float(buy_price) if hasattr(buy_price, '__float__') else buy_price
                try:
                    qty = float(position) if position is not None else 1.0
                    if qty <= 0 or qty != qty:  # NaN
                        qty = 1.0
                except (TypeError, ValueError):
                    qty = 1.0
                try:
                    fees_val = float(fees) if fees is not None else 0.0
                except (TypeError, ValueError):
                    fees_val = 0.0

                # Model probability: read from live strike row for this ticker (same source as UI / archive).
                # Fallback only when the row is missing (e.g. transient gap before WS refresh).
                current_probability = get_current_probability_from_live_strike_table(
                    ticker, trade_sym_u, side
                )
                if current_probability is None:
                    current_probability = get_current_probability(
                        float(strike_price),
                        float(current_symbol_price),
                        ttc_seconds,
                        momentum_score,
                        symbol,
                    )
                if current_probability is not None:
                    if buffer_from_strike < 0:
                        current_probability = 100 - current_probability

                # Per-contract unrealized (Kalshi 0–1 $ space): mark from complementary ask vs entry.
                # YES row: current_market_price is the NO-side ask in $ space → implied YES mark ≈ 1 − that quote.
                per_contract_pnl = 1.0 - float(current_market_price) - buy_price_float
                # Total dollars: scale by contracts, subtract fees paid (sunk cost on the trade).
                total_unrealized = float(per_contract_pnl * qty - fees_val)
                pnl_val = round(total_unrealized, 6)
                pnl_formatted = f"{round(total_unrealized, 2):.2f}"

                # Position value from exit ask (high/low tracking)
                position_value = 1.0 - float(current_market_price)

                # Compare and determine new high_price and low_price
                # If high_price or low_price is NULL (shouldn't happen for active trades, but handle gracefully),
                # initialize to buy_price. Otherwise compare with position_value
                if current_high_price is None:
                    current_high_price = buy_price_float
                if current_low_price is None:
                    current_low_price = buy_price_float
                
                # high_price should be the maximum of current_high_price and position_value
                new_high_price = max(float(current_high_price), position_value)
                # low_price should be the minimum of current_low_price and position_value
                new_low_price = min(float(current_low_price), position_value)
                
                # Update the monitoring data
                conn = get_db_connection()
                cursor = conn.cursor()
                trades_tbl = f"trades_{ctx_user()}"
                # Trade log: mirror unrealized pnl to users.trades_* so NOTIFY refetches /trades.
                # Lock order: touch trades_* before active_trades_* to match lifecycle_ws
                # (kalshi_lifecycle_trade_outcome: FOR UPDATE on tenant trades first), reducing deadlocks.
                # SAVEPOINT so deadlock / errors on the mirror do not abort the active_trades UPDATE.
                try:
                    tid_int = int(trade_id)
                except (TypeError, ValueError):
                    pnl_val = tid_int = None
                if pnl_val is not None and tid_int is not None:
                    mark_sell_price = float(position_value)
                    buy_val = buy_price_float * qty
                    roi_pct_val = None
                    if buy_val > 0:
                        roi_pct_val = round((pnl_val / buy_val) * 100.0, 5)
                    ret_pct_val = None
                    ret_pct_base_val = None
                    try:
                        cursor.execute(
                            f"""
                            SELECT bankroll, mtb_base_value
                            FROM users.{trades_tbl}
                            WHERE id = %s AND LOWER(TRIM(status)) IN ('open', 'partial')
                            """,
                            (tid_int,),
                        )
                        br_row = cursor.fetchone()
                        if br_row:
                            bankroll = br_row[0]
                            mtb_base = br_row[1] if len(br_row) > 1 else None
                            if bankroll is not None:
                                try:
                                    brf = float(bankroll)
                                    if brf > 0:
                                        ret_pct_val = round((pnl_val / (brf / 100.0)) * 100, 5)
                                except (TypeError, ValueError):
                                    pass
                            if mtb_base is not None:
                                try:
                                    mbf = float(mtb_base)
                                    if mbf > 0:
                                        ret_pct_base_val = round(
                                            (pnl_val / (mbf / 100.0)) * 100, 5
                                        )
                                except (TypeError, ValueError):
                                    pass
                    except Exception as br_e:
                        log_debug(
                            f"Open-trade mirror: bankroll read skipped trade_id={trade_id}: {br_e}"
                        )

                    cursor.execute("SAVEPOINT ats_pnl_mirror")
                    try:
                        mirror_sets = (
                            (
                                "pnl = %s, sell_price = %s, ret_pct = %s, ret_pct_base = %s, "
                                "roi_pct = %s, ats_updated = NOW()",
                                (
                                    pnl_val,
                                    mark_sell_price,
                                    ret_pct_val,
                                    ret_pct_base_val,
                                    roi_pct_val,
                                    tid_int,
                                ),
                            ),
                            (
                                "pnl = %s, sell_price = %s, ret_pct = %s, ret_pct_base = %s, roi_pct = %s",
                                (
                                    pnl_val,
                                    mark_sell_price,
                                    ret_pct_val,
                                    ret_pct_base_val,
                                    roi_pct_val,
                                    tid_int,
                                ),
                            ),
                            (
                                "pnl = %s, sell_price = %s, ret_pct = %s",
                                (pnl_val, mark_sell_price, ret_pct_val, tid_int),
                            ),
                            ("pnl = %s", (pnl_val, tid_int)),
                        )
                        applied = False
                        for set_clause, params in mirror_sets:
                            try:
                                cursor.execute(
                                    f"""
                                    UPDATE users.{trades_tbl}
                                    SET {set_clause}
                                    WHERE id = %s AND LOWER(TRIM(status)) IN ('open', 'partial')
                                    """,
                                    params,
                                )
                                applied = True
                                break
                            except Exception as e2:
                                if getattr(e2, "pgcode", None) == "42703":
                                    continue
                                raise
                        if not applied:
                            raise RuntimeError(
                                "ats_open_trade_mirror: no compatible UPDATE variant succeeded"
                            )
                        cursor.execute("RELEASE SAVEPOINT ats_pnl_mirror")
                    except Exception as sync_e:
                        try:
                            cursor.execute("ROLLBACK TO SAVEPOINT ats_pnl_mirror")
                        except Exception:
                            pass
                        log_debug(
                            f"Open-trade pnl mirror to users.trades skipped trade_id={trade_id}: {sync_e}"
                        )
                cursor.execute(f"""
                    UPDATE users.{active_trades_table} 
                    SET current_symbol_price = %s, 
                        current_probability = %s,
                        buffer_from_entry = %s,
                        time_since_entry = %s,
                        current_close_price = %s,
                        current_pnl = %s,
                        high_price = %s,
                        low_price = %s,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (current_symbol_price, current_probability, buffer_from_strike, time_since_entry, current_market_price, pnl_formatted, new_high_price, new_low_price, active_id))
                conn.commit()
                conn.close()
                
                # Invalidate cache when trade data is updated
                invalidate_active_trades_cache()
                
                # Broadcast throttled: integer time_since_entry % 1 was always true → Redis/HTTP storm.
                _mb_interval = 2.0
                _now_br = time.time()
                _last_br = getattr(
                    update_active_trade_monitoring_data, "_last_monitor_broadcast_ts", 0.0
                )
                if _now_br - _last_br >= _mb_interval:
                    update_active_trade_monitoring_data._last_monitor_broadcast_ts = _now_br
                    broadcast_active_trades_change()
                
                # Only log significant updates (every 60 seconds) to reduce noise
                if time_since_entry % 60 == 0:
                    log(f"📊 MONITORING: Updated trade {trade_id} - {symbol}_price: {current_symbol_price}, market_price: {current_market_price}, buffer: {buffer_from_strike}, prob: {current_probability}, pnl: {pnl_formatted}")
                
            except Exception as e:
                log(f"Error updating monitoring data for trade {trade_id}: {e}")
                
    except Exception as e:
        log(f"Error in update_active_trade_monitoring_data: {e}")

def check_monitoring_failsafe():
    """
    Bulletproof failsafe: Check if monitoring should be running and restart if needed.
    First attempts thread restart, then escalates to process restart if that fails.
    """
    global monitoring_thread
    
    # Track restart attempts to prevent infinite loops
    if not hasattr(check_monitoring_failsafe, 'restart_attempts'):
        check_monitoring_failsafe.restart_attempts = {}
        check_monitoring_failsafe.last_process_restart = 0
        check_monitoring_failsafe.process_restart_cooldown = 300  # 5 minutes between process restarts
    
    try:
        # Check if there are active trades
        conn = get_db_connection()
        if conn is None:
            log("❌ FAILSAFE: No DB connection; skipping failsafe check (restart would not help)")
            return
        cursor = conn.cursor()
        if ATS_UNIFIED_POOL:
            active_count = _count_active_trades_across_unified_pool_monitors()
        else:
            active_trades_table = get_monitor_active_trades_table()
            cursor.execute(
                f"""
                SELECT COUNT(*) FROM users.{active_trades_table}
                WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                """
            )
            active_count = cursor.fetchone()[0]
        conn.close()

        # If there are tracked trades but no monitoring thread, restart it
        if active_count > 0:
            with monitoring_thread_lock:
                thread_alive = False
                try:
                    thread_alive = monitoring_thread is not None and monitoring_thread.is_alive()
                except Exception as e:
                    log(f"⚠️ FAILSAFE: Thread object corrupted ({e}), forcing cleanup")
                    monitoring_thread = None
                    thread_alive = False

                if not thread_alive:
                    log(
                        f"🔄 FAILSAFE: Found {active_count} tracked trade row(s) "
                        f"(active/pending/closing) but monitoring not running"
                    )
                    
                    # Step 1: Try thread restart first (quick recovery)
                    log("🔄 FAILSAFE: Attempting thread restart...")
                    thread_restart_succeeded = False
                    try:
                        start_monitoring_loop()
                        
                        # Verify thread restart succeeded
                        time.sleep(1)  # Give thread time to start
                        with monitoring_thread_lock:
                            if monitoring_thread is not None:
                                try:
                                    if monitoring_thread.is_alive():
                                        log("✅ FAILSAFE: Thread restart succeeded and verified")
                                        thread_restart_succeeded = True
                                        # Reset restart attempts on success
                                        check_monitoring_failsafe.restart_attempts = {}
                                except Exception as e:
                                    log(f"⚠️ FAILSAFE: Thread verification failed ({e}), escalating to process restart")
                    except Exception as e:
                        log(f"❌ FAILSAFE: Thread restart failed ({e}), escalating to process restart")
                        import traceback
                        log(f"❌ FAILSAFE: Thread restart stack trace: {traceback.format_exc()}")
                    
                    # Step 2: Thread restart failed or verification failed - restart entire process
                    if not thread_restart_succeeded:
                        current_time = time.time()
                        time_since_last_restart = current_time - check_monitoring_failsafe.last_process_restart
                        
                        if time_since_last_restart < check_monitoring_failsafe.process_restart_cooldown:
                            log(f"⏳ FAILSAFE: Process restart on cooldown ({int(check_monitoring_failsafe.process_restart_cooldown - time_since_last_restart)}s remaining)")
                            return
                        
                        log(f"🚨 CRITICAL FAILSAFE: Thread restart failed, restarting entire process!")
                        log(f"🚨 CRITICAL: {active_count} active trades are UNPROTECTED - process restart required!")
                        
                        # Restart this process via supervisorctl
                        restart_active_trade_supervisor_process()
                        
                        # Update cooldown
                        check_monitoring_failsafe.last_process_restart = current_time
        
    except Exception as e:
        log(f"❌ CRITICAL: Failsafe check itself failed: {e}")
        import traceback
        log(f"❌ CRITICAL: Failsafe stack trace: {traceback.format_exc()}")
        # Even the failsafe failed - try process restart as last resort
        try:
            restart_active_trade_supervisor_process()
        except Exception as restart_error:
            log(f"❌ CATASTROPHIC: Process restart also failed: {restart_error}")

def restart_active_trade_supervisor_process():
    """
    Restart the entire active_trade_supervisor process via supervisorctl.
    This will cause this process to exit and supervisor will restart it.
    """
    try:
        from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
        
        if ATS_UNIFIED_15M:
            service_name = "active_trade_supervisor_15m"
        elif ATS_UNIFIED_HOURLY:
            service_name = "active_trade_supervisor_hourly"
        elif ATS_UNIFIED_ALL:
            service_name = unified_active_trade_supervisor_service_name()
        else:
            service_name = f"active_trade_supervisor_{MONITOR_IDENTIFIER}"
        
        log(f"🔄 PROCESS RESTART: Restarting {service_name} via supervisorctl...")
        log(f"🚨 CRITICAL: Process restart initiated due to monitoring failure")
        
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()
        
        # Restart the service
        result = subprocess.run(
            [supervisorctl_path, "-c", supervisor_config_path, "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            log(f"✅ PROCESS RESTART: Successfully initiated restart of {service_name}")
            log(f"✅ PROCESS RESTART: Supervisor output: {result.stdout}")
            
            # Give supervisor time to restart the process
            time.sleep(2)
            
            # This process will be terminated by supervisor, so we can exit
            log("🔄 PROCESS RESTART: Process restart initiated, supervisor will handle termination")
        else:
            log(f"❌ PROCESS RESTART: Failed to restart {service_name}")
            log(f"❌ PROCESS RESTART: Return code: {result.returncode}")
            log(f"❌ PROCESS RESTART: stderr: {result.stderr}")
            log(f"❌ PROCESS RESTART: stdout: {result.stdout}")
            
            # If supervisorctl fails, try alternative: exit and let supervisor auto-restart
            log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
            sys.exit(1)  # Exit with error code, supervisor will restart
            
    except subprocess.TimeoutExpired:
        log(f"❌ PROCESS RESTART: Timeout waiting for supervisorctl")
        # Fall back to exit
        log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
        sys.exit(1)
    except Exception as e:
        log(f"❌ PROCESS RESTART: Exception during restart: {e}")
        import traceback
        log(f"❌ PROCESS RESTART: Stack trace: {traceback.format_exc()}")
        # Fall back to exit
        log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
        sys.exit(1)

def start_monitoring_loop():
    """
    Start monitoring loop when there are active trades.
    This should be called when trades are added to active_trades.
    """
    global monitoring_thread
    
    # Clean up any corrupted state first
    try:
        with monitoring_thread_lock:
            if monitoring_thread is not None:
                try:
                    if not monitoring_thread.is_alive():
                        log("🧹 CLEANUP: Clearing dead thread reference")
                        monitoring_thread = None
                except Exception as e:
                    log(f"🧹 CLEANUP: Thread object corrupted ({e}), forcing cleanup")
                    monitoring_thread = None
    except Exception as e:
        log(f"⚠️ Cleanup check failed: {e}")
    
    # Check if monitoring thread is already running
    with monitoring_thread_lock:
        if monitoring_thread is not None:
            try:
                if monitoring_thread.is_alive():
                    log("📊 MONITORING: Monitoring thread already running, skipping")
                    return
            except Exception as e:
                log(f"⚠️ Thread object corrupted ({e}), clearing and continuing")
                monitoring_thread = None
    
    def monitoring_worker():
        global monitoring_thread
        log("📊 MONITORING: Starting monitoring loop for active trades")
        auto_stop_triggered_trades = set()
        verification_pending_trades = {}  # trade_id -> (trigger_time, verification_end_time)
        log("🔄 AUTO STOP: Reset auto-stop triggered trades set (clearing any failed attempts)")
        
        try:
            while True:
                if ATS_UNIFIED_POOL:
                    _ats_monitors = _iter_unified_pool_monitor_bindings_for_monitoring()
                else:
                    _ats_monitors = [(USER_NUMBER, MONITOR_ID)]

                for _ats_u, _ats_mid in _ats_monitors:
                    with ats_monitor_bind(_ats_u, _ats_mid):
                        try:
                            reconcile_active_trades_with_trade_log_each_tick()
                        except Exception as _rec_e:
                            log_debug(
                                f"TICK RECONCILE: exception ({ctx_ident()}): {_rec_e}"
                            )

                        # Check if there are still active trades
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        active_trades_table = get_monitor_active_trades_table()
                        scope_sql, scope_params = _active_trades_monitor_scope_sql()
                        cursor.execute(
                            f"SELECT * FROM users.{active_trades_table} WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') = 'active'{scope_sql}",
                            scope_params,
                        )
                        columns = [desc[0] for desc in cursor.description]
                        active_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
                        conn.close()

                        if not active_trades:
                            continue

                        # Update monitoring data
                        update_active_trade_monitoring_data()

                        # Refetch active_trades after update to get fresh current_probability values for auto-stop
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        active_trades_table = get_monitor_active_trades_table()
                        scope_sql, scope_params = _active_trades_monitor_scope_sql()
                        cursor.execute(
                            f"SELECT * FROM users.{active_trades_table} WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') = 'active'{scope_sql}",
                            scope_params,
                        )
                        columns = [desc[0] for desc in cursor.description]
                        active_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
                        conn.close()

                        # Log monitoring status every 60 seconds
                        current_time = time.time()
                        if not hasattr(monitoring_worker, 'last_status_log') or current_time - monitoring_worker.last_status_log > 60:
                            log_debug(f"MONITORING: Checking {len(active_trades)} active trades")
                            monitoring_worker.last_status_log = current_time
                
                        # Add heartbeat log every 30 seconds to track monitoring health
                        if not hasattr(monitoring_worker, 'last_heartbeat') or current_time - monitoring_worker.last_heartbeat > 30:
                            log_debug(f"MONITORING HEARTBEAT: Monitoring loop healthy, {len(active_trades)} active trades")
                            monitoring_worker.last_heartbeat = current_time
                
                        # Run failsafe check every 60 seconds
                        if not hasattr(monitoring_worker, 'last_failsafe_check') or current_time - monitoring_worker.last_failsafe_check > 60:
                            check_monitoring_failsafe()
                            monitoring_worker.last_failsafe_check = current_time
                
                        # === AUTO STOP LOGIC ===
                        auto_stop_enabled = is_auto_stop_enabled()
                        if auto_stop_enabled:
                            check_auto_stop_conditions(active_trades, auto_stop_triggered_trades, verification_pending_trades)
                
                        # === MOMENTUM SPIKE AUTO-STOPOUT LOGIC ===
                        # Skip momentum spike logic for Momentum Scalp and Momentum Reversal monitors
                        strategy = get_trade_strategy()
                        if strategy != "Momentum Scalp" and strategy != "Momentum Reversal":
                            # Get momentum spike settings from monitor's assigned strategy
                            try:
                                import psycopg2
                                conn = get_postgresql_connection()
                                with conn.cursor() as cursor:
                                    # First get the strategy name for this monitor
                                    cursor.execute(f"""
                                        SELECT strategy FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
                                    """, (ctx_mid(),))
                                    monitor_result = cursor.fetchone()
                            
                                    if monitor_result and monitor_result[0]:
                                        strategy_name = monitor_result[0]
                                
                                        # Get momentum spike settings from the monitor
                                        cursor.execute(f"""
                                            SELECT momentum_spike_enabled, momentum_spike_threshold
                                            FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
                                        """, (ctx_mid(),))
                                        result = cursor.fetchone()
                                
                                        if result:
                                            momentum_spike_enabled = result[0]
                                            momentum_spike_threshold = result[1]  # Use percentage directly
                                        else:
                                            momentum_spike_enabled = True
                                            momentum_spike_threshold = 35  # Use percentage directly
                                            log_debug(f"No strategy found: {strategy_name}, using defaults")
                                    else:
                                        momentum_spike_enabled = True
                                        momentum_spike_threshold = 35  # Use percentage directly
                                        log_debug(f"No strategy assigned to monitor {ctx_mid()}, using defaults")
                        
                                conn.close()
                        
                                # Only proceed if momentum spike is enabled
                                if momentum_spike_enabled:
                                    # Get verification settings (same as probability-based auto stop)
                                    verification_enabled = get_verification_period_enabled()
                                    verification_seconds = get_verification_period_seconds()
                                    current_time = time.time()
                            
                                    # Get current momentum (use 5s average from live price log to smooth noise)
                                    current_momentum = get_momentum_5s_avg_from_postgresql(get_current_monitor_symbol())
                            
                                    if current_momentum is not None:
                                        # Refresh active trades
                                        conn = get_db_connection()
                                        cursor = conn.cursor()
                                        active_trades_table = get_monitor_active_trades_table()
                                        scope_sql, scope_params = _active_trades_monitor_scope_sql()
                                        cursor.execute(
                                            f"SELECT * FROM users.{active_trades_table} WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') = 'active'{scope_sql}",
                                            scope_params,
                                        )
                                        columns = [desc[0] for desc in cursor.description]
                                        refreshed_active_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
                                        conn.close()
                                
                                        # Determine which trades are affected by current momentum
                                        positive_spike = current_momentum >= momentum_spike_threshold
                                        negative_spike = current_momentum <= -momentum_spike_threshold
                                
                                        if positive_spike:  # Positive spike - close all NO trades
                                            # Filter eligible NO trades
                                            eligible_trades = [t for t in refreshed_active_trades 
                                                               if t.get('status') == 'active' 
                                                               and t.get('side', '').upper() in ['N', 'NO']
                                                               and t.get('trade_id') not in auto_stop_triggered_trades]
                                    
                                            successful_closes = 0
                                            for trade in eligible_trades:
                                                trade_id = trade.get('trade_id')
                                        
                                                # Check if trade is in verification period
                                                if trade_id in verification_pending_trades:
                                                    trigger_time, verification_end_time = verification_pending_trades[trade_id]
                                            
                                                    # Check if verification period has ended
                                                    if current_time >= verification_end_time:
                                                        # Verification period ended - re-check current momentum to verify spike conditions still met
                                                        current_momentum_after_verification = get_momentum_5s_avg_from_postgresql(get_current_monitor_symbol())
                                                        if current_momentum_after_verification is not None:
                                                            spike_still_active = current_momentum_after_verification >= momentum_spike_threshold
                                                            if spike_still_active:
                                                                # Conditions still met after verification - trigger auto-stop
                                                                log_debug(f"[MOMENTUM SPIKE] Verification period ended - triggering auto stop for NO trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: +{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                                if trigger_auto_stop_close(
                                                                    trade,
                                                                    trigger_reason="momentum_spike",
                                                                    trigger_detail=(
                                                                        f"positive close_NO momentum={current_momentum_after_verification:.2f} "
                                                                        f"threshold=+{momentum_spike_threshold} after_verification"
                                                                    ),
                                                                ):
                                                                    auto_stop_triggered_trades.add(trade_id)
                                                                    del verification_pending_trades[trade_id]
                                                                    successful_closes += 1
                                                                else:
                                                                    log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                                                                    del verification_pending_trades[trade_id]
                                                            else:
                                                                # Conditions no longer met - cancel verification
                                                                log(f"[MOMENTUM SPIKE] ❌ Verification period ended - conditions no longer met for NO trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: +{momentum_spike_threshold})")
                                                                del verification_pending_trades[trade_id]
                                                        else:
                                                            # Could not get momentum - cancel verification to retry
                                                            log(f"[MOMENTUM SPIKE] ⚠️ Verification period ended but could not get current momentum for NO trade {trade_id}, cancelling verification")
                                                            del verification_pending_trades[trade_id]
                                                    else:
                                                        # Still in verification period - just wait, don't check conditions during wait
                                                        remaining_time = verification_end_time - current_time
                                                        if not hasattr(monitoring_worker, 'last_momentum_verification_log') or current_time - monitoring_worker.last_momentum_verification_log > 10:
                                                            log_debug(f"NO trade {trade_id} in verification period - {remaining_time:.1f}s remaining (momentum: {current_momentum:.2f})")
                                                            monitoring_worker.last_momentum_verification_log = current_time
                                                        continue
                                                else:
                                                    # Not in verification period - check if spike conditions are met
                                                    if positive_spike:
                                                        if verification_enabled:
                                                            # Start verification period
                                                            verification_end_time = current_time + verification_seconds
                                                            verification_pending_trades[trade_id] = (current_time, verification_end_time)
                                                            log_debug(f"Starting verification period for NO trade {trade_id} (momentum: {current_momentum:.2f}, threshold: +{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                        else:
                                                            # No verification - trigger immediately
                                                            log(f"[MOMENTUM SPIKE] 🚨 POSITIVE SPIKE - Triggering close for NO trade {trade_id} (momentum: {current_momentum:.2f})")
                                                            if trigger_auto_stop_close(
                                                                trade,
                                                                trigger_reason="momentum_spike",
                                                                trigger_detail=(
                                                                    f"positive close_NO momentum={current_momentum:.2f} "
                                                                    f"threshold=+{momentum_spike_threshold} immediate"
                                                                ),
                                                            ):
                                                                auto_stop_triggered_trades.add(trade_id)
                                                                successful_closes += 1
                                                            else:
                                                                log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
                                    
                                            if successful_closes > 0:
                                                log(f"[MOMENTUM SPIKE] ✅ Closed {successful_closes} NO trades due to positive momentum spike")
                                        
                                        elif negative_spike:  # Negative spike - close all YES trades
                                            # Filter eligible YES trades
                                            eligible_trades = [t for t in refreshed_active_trades 
                                                               if t.get('status') == 'active' 
                                                               and t.get('side', '').upper() in ['Y', 'YES']
                                                               and t.get('trade_id') not in auto_stop_triggered_trades]
                                    
                                            successful_closes = 0
                                            for trade in eligible_trades:
                                                trade_id = trade.get('trade_id')
                                        
                                                # Check if trade is in verification period
                                                if trade_id in verification_pending_trades:
                                                    trigger_time, verification_end_time = verification_pending_trades[trade_id]
                                            
                                                    # Check if verification period has ended
                                                    if current_time >= verification_end_time:
                                                        # Verification period ended - re-check current momentum to verify spike conditions still met
                                                        current_momentum_after_verification = get_momentum_5s_avg_from_postgresql(get_current_monitor_symbol())
                                                        if current_momentum_after_verification is not None:
                                                            spike_still_active = current_momentum_after_verification <= -momentum_spike_threshold
                                                            if spike_still_active:
                                                                # Conditions still met after verification - trigger auto-stop
                                                                log_debug(f"[MOMENTUM SPIKE] Verification period ended - triggering auto stop for YES trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: -{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                                if trigger_auto_stop_close(
                                                                    trade,
                                                                    trigger_reason="momentum_spike",
                                                                    trigger_detail=(
                                                                        f"negative close_YES momentum={current_momentum_after_verification:.2f} "
                                                                        f"threshold=-{momentum_spike_threshold} after_verification"
                                                                    ),
                                                                ):
                                                                    auto_stop_triggered_trades.add(trade_id)
                                                                    del verification_pending_trades[trade_id]
                                                                    successful_closes += 1
                                                                else:
                                                                    log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                                                                    del verification_pending_trades[trade_id]
                                                            else:
                                                                # Conditions no longer met - cancel verification
                                                                log(f"[MOMENTUM SPIKE] ❌ Verification period ended - conditions no longer met for YES trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: -{momentum_spike_threshold})")
                                                                del verification_pending_trades[trade_id]
                                                        else:
                                                            # Could not get momentum - cancel verification to retry
                                                            log(f"[MOMENTUM SPIKE] ⚠️ Verification period ended but could not get current momentum for YES trade {trade_id}, cancelling verification")
                                                            del verification_pending_trades[trade_id]
                                                    else:
                                                        # Still in verification period - just wait, don't check conditions during wait
                                                        remaining_time = verification_end_time - current_time
                                                        if not hasattr(monitoring_worker, 'last_momentum_verification_log') or current_time - monitoring_worker.last_momentum_verification_log > 10:
                                                            log_debug(f"YES trade {trade_id} in verification period - {remaining_time:.1f}s remaining (momentum: {current_momentum:.2f})")
                                                            monitoring_worker.last_momentum_verification_log = current_time
                                                        continue
                                                else:
                                                    # Not in verification period - check if spike conditions are met
                                                    if negative_spike:
                                                        if verification_enabled:
                                                            # Start verification period
                                                            verification_end_time = current_time + verification_seconds
                                                            verification_pending_trades[trade_id] = (current_time, verification_end_time)
                                                            log_debug(f"Starting verification period for YES trade {trade_id} (momentum: {current_momentum:.2f}, threshold: -{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                        else:
                                                            # No verification - trigger immediately
                                                            log(f"[MOMENTUM SPIKE] 🚨 NEGATIVE SPIKE - Triggering close for YES trade {trade_id} (momentum: {current_momentum:.2f})")
                                                            if trigger_auto_stop_close(
                                                                trade,
                                                                trigger_reason="momentum_spike",
                                                                trigger_detail=(
                                                                    f"negative close_YES momentum={current_momentum:.2f} "
                                                                    f"threshold=-{momentum_spike_threshold} immediate"
                                                                ),
                                                            ):
                                                                auto_stop_triggered_trades.add(trade_id)
                                                                successful_closes += 1
                                                            else:
                                                                log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
                                    
                                            if successful_closes > 0:
                                                log(f"[MOMENTUM SPIKE] ✅ Closed {successful_closes} YES trades due to negative momentum spike")
                                
                                        # Log momentum monitoring (every 30 seconds to reduce noise)
                                        if not hasattr(monitoring_worker, 'last_momentum_log') or current_time - monitoring_worker.last_momentum_log > 30:
                                            log_debug(f"[MOMENTUM SPIKE] Monitoring momentum: {current_momentum:.2f} (threshold: ±{momentum_spike_threshold})")
                                            monitoring_worker.last_momentum_log = current_time
                            except Exception as e:
                                log(f"[MOMENTUM SPIKE] Error in momentum spike logic: {e}")

                if ATS_UNIFIED_POOL:
                    tracked_left = _count_active_trades_across_unified_pool_monitors()
                else:
                    try:
                        _tconn = get_db_connection()
                        _ttbl = get_monitor_active_trades_table()
                        _tc = _tconn.cursor()
                        _tc.execute(
                            f"""
                            SELECT COUNT(*) FROM users.{_ttbl}
                            WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                            """
                        )
                        tracked_left = int(_tc.fetchone()[0])
                        _tconn.close()
                    except Exception:
                        tracked_left = 0

                if tracked_left == 0:
                    log(
                        "📊 MONITORING: No active, pending, or closing trades; stopping monitoring loop"
                    )
                    break
                # Sleep for 1 second
                time.sleep(1)

        except Exception as e:
            log(f"🚨 CRITICAL: Monitoring loop crashed with error: {e}")
            log(f"🚨 CRITICAL: Stack trace: {e.__class__.__name__}: {str(e)}")
            
            # Check if there are still active trades that need monitoring
            try:
                if ATS_UNIFIED_POOL:
                    active_count = _count_active_trades_across_unified_pool_monitors()
                else:
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        f"""
                        SELECT COUNT(*) FROM users.active_trades_{ctx_user()}_{ctx_mid()}
                        WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                        """
                    )
                    active_count = cursor.fetchone()[0]
                    conn.close()

                if active_count > 0:
                    log(
                        f"🚨 CRITICAL: Monitoring loop crashed but {active_count} tracked trade row(s) "
                        f"(active/pending/closing) still need monitoring"
                    )
                    log("🔄 AUTO-RESTART: Attempting to restart monitoring loop in 5 seconds...")
                    
                    # Clear the thread reference so we can restart
                    with monitoring_thread_lock:
                        monitoring_thread = None
                    
                    # Wait 5 seconds then restart
                    time.sleep(5)
                    start_monitoring_loop()
                    return
                else:
                    log("📊 MONITORING: No active trades, monitoring loop can safely stop")
            except Exception as restart_error:
                log(f"🚨 CRITICAL: Failed to check for active trades during restart: {restart_error}")
                log(f"🚨 CRITICAL: Restart stack trace: {restart_error.__class__.__name__}: {str(restart_error)}")
        

        
        # Clear the global monitoring thread reference when done
        with monitoring_thread_lock:
            monitoring_thread = None
        log("📊 MONITORING: Monitoring thread finished")
    
    # Start monitoring in a separate thread WITH EXCEPTION HANDLING
    with monitoring_thread_lock:
        try:
            monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
            monitoring_thread.start()
            
            # Verify thread actually started
            if not monitoring_thread.is_alive():
                raise RuntimeError("Thread failed to start after start() call")
            
            log("📊 MONITORING: Monitoring thread started and verified alive")
            
        except Exception as e:
            log(f"❌ CRITICAL: Failed to start monitoring thread: {e}")
            log(f"❌ CRITICAL: Exception type: {type(e).__name__}")
            import traceback
            log(f"❌ CRITICAL: Stack trace: {traceback.format_exc()}")
            # Clear thread reference on failure
            monitoring_thread = None
            raise  # Re-raise to let caller know it failed

def update_monitoring_on_demand():
    """
    Update monitoring data on demand (called by other scripts when needed)
    """
    update_active_trade_monitoring_data()

def invalidate_active_trades_cache():
    """Invalidate the active trades cache to force fresh data on next request"""
    global active_trades_cache, active_trades_cache_time
    active_trades_cache = None
    active_trades_cache_time = 0



def _active_trades_result_dicts(columns: List[str], rows) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for row in rows:
        trade_dict = dict(zip(columns, row))
        for key, value in trade_dict.items():
            if hasattr(value, "isoformat"):
                trade_dict[key] = value.isoformat()
            elif hasattr(value, "__float__"):
                trade_dict[key] = float(value)
        result.append(trade_dict)
    return result


def _get_all_active_trades_for_current_monitor() -> List[Dict[str, Any]]:
    """Rows from this monitor's active_trades table (requires correct ctx bind for unified pool)."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        scope_sql, scope_params = _active_trades_monitor_scope_sql()
        cursor.execute(
            f"""
            SELECT * FROM users.{active_trades_table}
            WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing'){scope_sql}
            ORDER BY created_at DESC
            """,
            scope_params,
        )

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        return _active_trades_result_dicts(columns, rows)

    except Exception as e:
        log(f"Error getting active trades: {e}")
        return []


def _get_all_active_trades_unified_pool_unbound() -> List[Dict[str, Any]]:
    """All monitors' rows from pool table(s) (no ContextVar bind). unified_all = 15m + hourly tables."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if ATS_UNIFIED_ALL:
            combined: List[Dict[str, Any]] = []
            wh = effective_tenant_context_for_sql_rewrite().user_no
            for tbl in (
                legacy_active_trades_pool_15m(wh),
                legacy_active_trades_pool_hourly(wh),
            ):
                cursor.execute(
                    f"""
                    SELECT * FROM users.{tbl}
                    WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                    """
                )
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                combined.extend(_active_trades_result_dicts(columns, rows))
            conn.close()

            def _created_sort_key(d: Dict[str, Any]) -> str:
                v = d.get("created_at")
                return str(v) if v is not None else ""

            combined.sort(key=_created_sort_key, reverse=True)
            return combined

        tbl = get_monitor_active_trades_table()
        cursor.execute(
            f"""
            SELECT * FROM users.{tbl}
            WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
            ORDER BY created_at DESC
            """
        )
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return _active_trades_result_dicts(columns, rows)
    except Exception as e:
        log(f"Error getting unified pool active trades: {e}")
        return []


def get_all_active_trades() -> List[Dict[str, Any]]:
    """Get all currently active, pending, and closing trades (unified pool = one table)."""
    if ATS_UNIFIED_POOL and _ats_bind_m.get() is None:
        return _get_all_active_trades_unified_pool_unbound()
    return _get_all_active_trades_for_current_monitor()

def _sync_with_trades_db_for_current_monitor():
    """Sync active_trades for the monitor bound in context (single monitor)."""
    # Canonical trade log rows for this monitor (must match reconcile_active_trades_with_trade_log_each_tick).
    # Using only status='open' wrongly treats pending/closing log rows as absent and removes pool rows.
    mon_tag = f"mon_{ctx_user()}_{ctx_mid()}"
    conn = get_trades_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT id FROM {legacy_users_trades(ctx_user())}
        WHERE monitor = %s
          AND LOWER(TRIM(status)) IN ('pending', 'open', 'closing')
        """,
        (mon_tag,),
    )
    tracked_trade_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    # Get all active trade IDs
    conn = get_db_connection()
    cursor = conn.cursor()
    active_trades_table = get_monitor_active_trades_table()
    scope_sql, scope_params = _active_trades_monitor_scope_sql()
    cursor.execute(
        f"""
        SELECT trade_id FROM users.{active_trades_table}
        WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing'){scope_sql}
        """,
        scope_params,
    )
    active_trade_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    # Find trades that should be active but aren't
    missing_trades = set(tracked_trade_ids) - set(active_trade_ids)
    for trade_id in missing_trades:
        log(f"🔄 SYNC: Found missing active trade: {trade_id}, adding...")
        add_new_active_trade(trade_id, "SYNC")  # Use "SYNC" as ticket_id for auto-added trades

    # Find trades that are active but should be closed
    closed_trades = set(active_trade_ids) - set(tracked_trade_ids)
    for trade_id in closed_trades:
        log(f"🔄 SYNC: Found closed trade still in active: {trade_id}, removing...")
        remove_closed_trade(trade_id)

    if missing_trades or closed_trades:
        log(
            f"Sync complete ({ctx_ident()}): added {len(missing_trades)}, removed {len(closed_trades)}"
        )
    else:
        log(f"Sync complete ({ctx_ident()}): no changes needed")


def reconcile_active_trades_with_trade_log_each_tick() -> None:
    """
    Per monitoring tick: align users.<active_trades> with users.trades_* for the bound monitor.

    - Enrolls missing pending / open rows from the trade log (same monitor tag as sync).
    - Promotes pool pending → active when the log shows open.
    - Marks pool active/pending → closing when the log shows closing.
    - Drops pool rows when the canonical trade is terminal or gone (same monitor only).

    Uses existing add_pending_trade / add_new_active_trade / confirm_pending_trade /
    update_trade_status_to_closing / remove_closed_trade (no pricing-path changes).
    """
    u = ctx_user()
    mid = ctx_mid()
    mon_tag = f"mon_{u}_{mid}"
    tbl = get_monitor_active_trades_table()
    scope_sql, scope_params = _active_trades_monitor_scope_sql()

    conn_tr = get_trades_db_connection()
    if not conn_tr:
        return
    try:
        cur = conn_tr.cursor()
        cur.execute(
            f"""
            SELECT id, ticket_id, status FROM {legacy_users_trades(u)}
            WHERE monitor = %s AND LOWER(TRIM(status)) IN ('pending', 'open', 'closing')
            """,
            (mon_tag,),
        )
        trade_rows = cur.fetchall()
    except Exception as e:
        log_debug(f"TICK RECONCILE: trades read failed ({ctx_ident()}): {e}")
        return
    finally:
        conn_tr.close()

    trade_by_id: Dict[int, Tuple[str, str]] = {}
    for tid, ticket_id, st in trade_rows:
        st_l = str(st or "").strip().lower()
        trade_by_id[int(tid)] = (
            str(ticket_id).strip() if ticket_id is not None else "",
            st_l,
        )

    conn_at = get_db_connection()
    if not conn_at:
        return
    try:
        cur = conn_at.cursor()
        cur.execute(
            f"""
            SELECT trade_id, status FROM users.{tbl}
            WHERE status IN ('pending', 'active', 'closing'){scope_sql}
            """,
            scope_params,
        )
        pool_rows = {int(r[0]): str(r[1] or "").strip().lower() for r in cur.fetchall()}
    except Exception as e:
        log_debug(f"TICK RECONCILE: pool read failed ({ctx_ident()}): {e}")
        return
    finally:
        conn_at.close()

    for tid, (ticket_id, st) in trade_by_id.items():
        ps = pool_rows.get(tid)
        if ps is None:
            if st == "pending":
                add_pending_trade(tid, ticket_id or "")
            elif st == "open":
                add_new_active_trade(tid, ticket_id or "RECONCILE_OPEN")
            elif st == "closing":
                log_debug(
                    f"TICK RECONCILE: trade {tid} closing in log but no pool row ({ctx_ident()}); "
                    "skipping insert (needs open snapshot)"
                )
            continue
        if ps == "pending" and st == "open":
            confirm_pending_trade(tid, ticket_id or "")
        elif ps in ("pending", "active") and st == "closing":
            update_trade_status_to_closing(tid)

    stale_tids = [t for t in pool_rows if t not in trade_by_id]
    if not stale_tids:
        return

    conn_tr2 = get_trades_db_connection()
    if not conn_tr2:
        return
    try:
        cur2 = conn_tr2.cursor()
        cur2.execute(
            f"SELECT id, monitor, status FROM {legacy_users_trades(u)} WHERE id = ANY(%s)",
            (stale_tids,),
        )
        meta_rows = cur2.fetchall()
    except Exception as e:
        log_debug(f"TICK RECONCILE: stale lookup failed ({ctx_ident()}): {e}")
        return
    finally:
        conn_tr2.close()

    meta = {
        int(r[0]): (r[1], str(r[2] or "").strip().lower()) for r in meta_rows
    }
    for tid in stale_tids:
        m = meta.get(tid)
        if m is None:
            remove_closed_trade(tid)
            continue
        mon_db, st = m[0], m[1]
        if str(mon_db or "").strip() != mon_tag:
            continue
        if st in ("closed", "expired", "error", "deleted"):
            remove_closed_trade(tid)


def _purge_unified_active_trades_wrong_market() -> int:
    """
    Delete pool rows whose monitor_id is not in this pool's market (15m vs hourly).
    Both unified ATS processes share Redis fanout; stray rows can land in the wrong table.
    """
    from backend.core.port_config import (
        monitor_suffix_uses_unified_15m_pool,
        monitor_suffix_uses_unified_hourly_pool,
    )

    user = USER_NUMBER
    wh = _norm_slot(str(user).strip())
    specs: List[Tuple[str, Any, str]] = []
    if ATS_UNIFIED_ALL:
        specs = [
            (legacy_active_trades_pool_15m(wh), monitor_suffix_uses_unified_15m_pool, "15m"),
            (legacy_active_trades_pool_hourly(wh), monitor_suffix_uses_unified_hourly_pool, "hourly"),
        ]
    elif ATS_UNIFIED_15M:
        specs = [(legacy_active_trades_pool_15m(wh), monitor_suffix_uses_unified_15m_pool, "15m")]
    elif ATS_UNIFIED_HOURLY:
        specs = [(legacy_active_trades_pool_hourly(wh), monitor_suffix_uses_unified_hourly_pool, "hourly")]
    else:
        return 0

    total_removed = 0
    for tbl, belongs, pool_label in specs:
        conn = get_db_connection()
        if not conn:
            continue
        removed = 0
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT DISTINCT monitor_id FROM users.{tbl}
                    WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                    """
                )
                mismatched: List[str] = []
                for (mid,) in cur.fetchall():
                    if mid is None:
                        continue
                    sm = str(mid).strip()
                    if not sm:
                        continue
                    suffix = f"{user}_{sm}"
                    try:
                        in_pool = belongs(suffix)
                    except Exception as e:
                        log_debug(
                            f"🧹 Purge wrong-pool: skip monitor_id={sm} ({pool_label}): classify error: {e}"
                        )
                        continue
                    if not in_pool:
                        mismatched.append(sm)
                for sm in mismatched:
                    cur.execute(
                        f"""
                        DELETE FROM users.{tbl}
                        WHERE monitor_id::text = %s
                          AND COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                        """,
                        (sm,),
                    )
                    removed += cur.rowcount
            conn.commit()
        except Exception as e:
            log(f"🧹 Purge wrong-pool rows failed ({pool_label}): {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if removed:
            log(
                f"🧹 Removed {removed} row(s) from {tbl} — monitors not in {pool_label} pool "
                f"(repair stray Redis/HTTP enrollments)"
            )
        total_removed += removed
    return total_removed


def _reconcile_unified_pool_open_trades_full_scan() -> None:
    """
    Failsafe: enroll any open trade whose monitor uses this unified pool (by monitor_list market),
    even if that monitor is not in iter_active_*_monitor_bindings (e.g. paused list row).
    """
    from backend.core.port_config import (
        monitor_suffix_uses_unified_15m_pool,
        monitor_suffix_uses_unified_hourly_pool,
    )

    if ATS_UNIFIED_ALL:
        wh = effective_tenant_context_for_sql_rewrite().user_no
        tbl_15 = legacy_active_trades_pool_15m(wh)
        tbl_h = legacy_active_trades_pool_hourly(wh)
        conn = get_postgresql_connection()
        if not conn:
            log("🔄 RECONCILE: no DB connection; skipping unified open-trade scan")
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT trade_id FROM users.{tbl_15}
                    WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                    """
                )
                tracked_15m = {int(r[0]) for r in cur.fetchall()}
                cur.execute(
                    f"""
                    SELECT trade_id FROM users.{tbl_h}
                    WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                    """
                )
                tracked_h = {int(r[0]) for r in cur.fetchall()}
        finally:
            conn.close()

        conn_tr = get_trades_db_connection()
        if not conn_tr:
            return
        try:
            c2 = conn_tr.cursor()
            scan_slot = effective_tenant_context_for_sql_rewrite().user_no
            c2.execute(
                f"""
                SELECT id, monitor FROM {legacy_users_trades(scan_slot)}
                WHERE LOWER(TRIM(status)) IN ('open', 'partial') AND monitor IS NOT NULL AND monitor LIKE 'mon_%%'
                """
            )
            candidates = c2.fetchall()
        finally:
            conn_tr.close()

        added = 0
        for trade_id, monitor in candidates:
            tid = int(trade_id)
            mon = str(monitor).strip()
            if not mon.startswith("mon_"):
                continue
            suffix = mon[4:]
            parts = suffix.split("_", 1)
            if len(parts) != 2:
                continue
            nu, mid = parts[0], parts[1]
            if monitor_suffix_uses_unified_15m_pool(suffix):
                if tid in tracked_15m:
                    continue
                with ats_monitor_bind(nu, mid):
                    if add_new_active_trade(tid, "RECONCILE"):
                        added += 1
                        tracked_15m.add(tid)
            elif monitor_suffix_uses_unified_hourly_pool(suffix):
                if tid in tracked_h:
                    continue
                with ats_monitor_bind(nu, mid):
                    if add_new_active_trade(tid, "RECONCILE"):
                        added += 1
                        tracked_h.add(tid)
        if added:
            log(f"🔄 RECONCILE (full scan): added {added} open unified trade(s) to pool")
        _purge_unified_active_trades_wrong_market()
        return

    wh2 = effective_tenant_context_for_sql_rewrite().user_no
    if ATS_UNIFIED_15M:
        tbl = legacy_active_trades_pool_15m(wh2)

        def _use_unified_pool(suffix: str) -> bool:
            return monitor_suffix_uses_unified_15m_pool(suffix)

        pool_label = "15m"
    elif ATS_UNIFIED_HOURLY:
        tbl = legacy_active_trades_pool_hourly(wh2)

        def _use_unified_pool(suffix: str) -> bool:
            return monitor_suffix_uses_unified_hourly_pool(suffix)

        pool_label = "hourly"
    else:
        return
    conn = get_postgresql_connection()
    if not conn:
        log(f"🔄 RECONCILE: no DB connection; skipping unified {pool_label} open-trade scan")
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT trade_id FROM users.{tbl}
                WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                """
            )
            tracked = {int(r[0]) for r in cur.fetchall()}
    finally:
        conn.close()

    conn_tr = get_trades_db_connection()
    if not conn_tr:
        return
    try:
        c2 = conn_tr.cursor()
        scan_slot2 = effective_tenant_context_for_sql_rewrite().user_no
        c2.execute(
            f"""
            SELECT id, monitor FROM {legacy_users_trades(scan_slot2)}
            WHERE LOWER(TRIM(status)) IN ('open', 'partial') AND monitor IS NOT NULL AND monitor LIKE 'mon_%%'
            """
        )
        candidates = c2.fetchall()
    finally:
        conn_tr.close()

    added = 0
    for trade_id, monitor in candidates:
        tid = int(trade_id)
        if tid in tracked:
            continue
        mon = str(monitor).strip()
        if not mon.startswith("mon_"):
            continue
        suffix = mon[4:]
        if not _use_unified_pool(suffix):
            continue
        parts = suffix.split("_", 1)
        if len(parts) != 2:
            continue
        nu, mid = parts[0], parts[1]
        with ats_monitor_bind(nu, mid):
            if add_new_active_trade(tid, "RECONCILE"):
                added += 1
                tracked.add(tid)
    if added:
        log(f"🔄 RECONCILE (full scan): added {added} open {pool_label} trade(s) to pool")
    _purge_unified_active_trades_wrong_market()


def sync_with_trades_db():
    """
    Sync active trades database with main trades.db to ensure consistency.
    This should be called on demand to catch any missed updates.
    """
    try:
        if ATS_UNIFIED_POOL:
            if ATS_UNIFIED_15M:
                from backend.core.unified_15m_monitors import iter_active_15m_monitor_bindings

                iter_bindings = iter_active_15m_monitor_bindings()
            elif ATS_UNIFIED_HOURLY:
                from backend.core.unified_hourly_monitors import iter_active_hourly_monitor_bindings

                iter_bindings = iter_active_hourly_monitor_bindings()
            else:
                from backend.core.unified_all_monitors import iter_active_unified_monitor_bindings

                iter_bindings = iter_active_unified_monitor_bindings()
            for u, m in iter_bindings:
                with ats_monitor_bind(u, m):
                    _sync_with_trades_db_for_current_monitor()
            _reconcile_unified_pool_open_trades_full_scan()
            return
        _sync_with_trades_db_for_current_monitor()
    except Exception as e:
        import traceback

        log(f"Error in sync_with_trades_db: {e}")
        log(traceback.format_exc())

def sync_on_demand():
    """
    Sync on demand (called by other scripts when needed)
    """
    sync_with_trades_db()

def start_event_driven_supervisor():
    """Start the event-driven active trade supervisor with HTTP server"""
    log("🚀 Starting event-driven active trade supervisor")
    log("📡 Waiting for trade notifications...")
    start_ats_enroll_redis_subscriber()

    # Check if there are already active trades and start monitoring if needed
    if ATS_UNIFIED_POOL:
        active_count = _count_active_trades_across_unified_pool_monitors()
        if active_count > 0:
            if ATS_UNIFIED_ALL:
                pool_n = "unified"
            else:
                pool_n = "15m" if ATS_UNIFIED_15M else "hourly"
            log(
                f"📊 MONITORING: Found {active_count} existing tracked row(s) in {pool_n} pool "
                f"(active/pending/closing), starting monitoring"
            )
            start_monitoring_loop()
    else:
        conn = get_db_connection()
        if not conn:
            log("❌ Failed to connect to PostgreSQL; cannot start event-driven supervisor")
            sys.exit(1)
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM users.{active_trades_table}
            WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
            """
        )
        active_count = cursor.fetchone()[0]
        conn.close()

        if active_count > 0:
            log(
                f"📊 MONITORING: Found {active_count} existing trade row(s) "
                f"(active/pending/closing), starting monitoring"
            )
            start_monitoring_loop()
    
    # Start HTTP server in a separate thread
    def start_http_server():
        try:
            host = "0.0.0.0"  # Listen on all interfaces for mobile access
            port = ACTIVE_TRADE_SUPERVISOR_PORT
            log(f"🌐 Starting HTTP server on {host}:{port}")
            app.run(host=host, port=port, debug=False, use_reloader=False)
        except Exception as e:
            log(f"❌ Error starting HTTP server: {e}")
    
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    def _startup_reconcile():
        time.sleep(5)
        try:
            log("🔄 Startup reconcile: sync_with_trades_db() (missed Redis/HTTP enrollments)")
            sync_with_trades_db()
        except Exception as e:
            log(f"❌ Startup reconcile failed: {e}")

    threading.Thread(target=_startup_reconcile, daemon=True).start()

    # Keep the process alive with brute force failsafe
    try:
        while True:
            # BRUTE FORCE FAILSAFE: Check database every 10 seconds for tracked trades
            # If there are active/pending/closing rows but no monitoring thread, restart it
            if ATS_UNIFIED_POOL:
                active_count = _count_active_trades_across_unified_pool_monitors()
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                active_trades_table = get_monitor_active_trades_table()
                cursor.execute(
                    f"""
                    SELECT COUNT(*) FROM users.{active_trades_table}
                    WHERE COALESCE(NULLIF(TRIM(LOWER(status::text)), ''), 'active') IN ('active', 'pending', 'closing')
                    """
                )
                active_count = cursor.fetchone()[0]
                conn.close()

            # Check if monitoring thread is alive
            monitoring_thread_alive = False
            with monitoring_thread_lock:
                if monitoring_thread is not None and monitoring_thread.is_alive():
                    monitoring_thread_alive = True

            # If there are tracked trades but no monitoring thread, restart it
            if active_count > 0 and not monitoring_thread_alive:
                log(
                    f"🚨 BRUTE FORCE FAILSAFE: Found {active_count} tracked trade row(s) "
                    f"but monitoring thread is dead"
                )
                
                # Try thread restart first
                thread_restart_succeeded = False
                try:
                    log("🔄 BRUTE FORCE FAILSAFE: Attempting thread restart...")
                    start_monitoring_loop()
                    time.sleep(1)  # Give thread time to start
                    
                    # Verify
                    with monitoring_thread_lock:
                        if monitoring_thread is not None:
                            try:
                                if monitoring_thread.is_alive():
                                    log("✅ BRUTE FORCE FAILSAFE: Thread restart succeeded and verified")
                                    thread_restart_succeeded = True
                            except Exception as e:
                                log(f"⚠️ BRUTE FORCE FAILSAFE: Thread verification failed ({e})")
                    
                except Exception as e:
                    log(f"❌ BRUTE FORCE FAILSAFE: Thread restart exception: {e}")
                    import traceback
                    log(f"❌ BRUTE FORCE FAILSAFE: Stack trace: {traceback.format_exc()}")
                
                # If thread restart failed, restart process
                if not thread_restart_succeeded:
                    log("🚨 BRUTE FORCE FAILSAFE: Thread restart failed, restarting process...")
                    try:
                        restart_active_trade_supervisor_process()
                    except Exception as e:
                        log(f"❌ BRUTE FORCE FAILSAFE: Process restart failed: {e}")
            
            # Log failsafe status every 5 minutes (30 iterations)
            if not hasattr(start_event_driven_supervisor, 'failsafe_log_counter'):
                start_event_driven_supervisor.failsafe_log_counter = 0
            start_event_driven_supervisor.failsafe_log_counter += 1
            
            if start_event_driven_supervisor.failsafe_log_counter >= 30:  # Every 5 minutes
                log(f"🛡️ BRUTE FORCE FAILSAFE: Health check - {active_count} active trades, monitoring thread alive: {monitoring_thread_alive}")
                flush_stale_active_trades_past_contract_settlement()
                start_event_driven_supervisor.failsafe_log_counter = 0
            
            # Sleep for 10 seconds (much more frequent than the old 60 seconds)
            time.sleep(10)
            
            # Run existing failsafe check every 60 seconds (6 iterations)
            if not hasattr(start_event_driven_supervisor, 'failsafe_counter'):
                start_event_driven_supervisor.failsafe_counter = 0
            start_event_driven_supervisor.failsafe_counter += 1
            
            if start_event_driven_supervisor.failsafe_counter >= 6:  # Every 60 seconds
                check_monitoring_failsafe()
                start_event_driven_supervisor.failsafe_counter = 0
                
    except KeyboardInterrupt:
        log("🛑 Active trade supervisor stopped by user")
    except Exception as e:
        log(f"❌ Error in supervisor: {e}")

def is_auto_stop_enabled():
    """Check if AUTO STOP is enabled by checking auto_trade boolean in monitor_list"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Check auto_trade boolean from the specific monitor's row in monitor_list
            cursor.execute(f"SELECT auto_trade FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            if result:
                auto_trade_enabled = result[0]
                return auto_trade_enabled
            else:
                log_debug(f"No monitor found with ID {ctx_mid()} in monitor_list")
                return False
    except Exception as e:
        log(f"[AUTO STOP] Error reading auto_trade from monitor_list: {e}")
        return False


def _close_method_for_auto_trigger(trigger_reason: str) -> str:
    """Tenant ``trades_*``.``close_method`` for ATS-triggered closes (distinct from manual / expired)."""
    key = (trigger_reason or "").strip().lower()
    if not key or key == "unknown":
        return "auto"
    mapped = {
        "stop_loss_floor": "auto_stop_loss_floor",
        "probability_auto_stop": "auto_probability",
        "momentum_spike": "auto_momentum_spike",
        "scalp_max_profit": "auto_scalp_max_profit",
        "scalp_trailing_stop": "auto_scalp_trailing_stop",
        "scalp_profit_target": "auto_scalp_profit_target",
        "reversal_max_profit": "auto_reversal_max_profit",
        "reversal_trailing_stop": "auto_reversal_trailing_stop",
        "reversal_profit_target": "auto_reversal_profit_target",
        "close_attempt_failed_retry": "auto_close_retry",
        "close_failed_retry": "auto_close_retry",  # legacy trigger_reason only
    }
    return mapped.get(key, f"auto_{key}")


def _defer_unified_ats_close_followup(
    ticket_id: str,
    log_message: str,
    notification_data: dict,
) -> None:
    """trade_logger + close notify off the unified ATS hot path (same idea as unified AES)."""
    slot = ctx_user()

    def _run():
        import requests as _req

        try:
            from backend.util.trade_logger import log_trade_event

            log_trade_event(ticket_id, log_message, service="active_trade_supervisor")
        except Exception:
            pass
        try:
            from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms

            if use_trading_redis_comms():
                publish_preferences_event(
                    "automated_trade_closed",
                    notification_data,
                    tenant_user_no=slot,
                )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def _ats_monitor_flip_boolean_strictly_true(val: Any) -> bool:
    """
    Flip sell must only run when the monitor row has an explicit PostgreSQL TRUE.
    NULL, FALSE, or any other value never enables flip sell.
    """
    return val is True


def parse_flip_sell_multiplier(mult_raw: Optional[Any]) -> float:
    """
    Parse monitor flip_sell_*_mult (e.g. '1', '2', '3', '1x', '2x') to a positive float.
    Defaults to 1.0 when unset/empty (only used after the monitor flag is already TRUE).
    """
    if mult_raw is None:
        return 1.0
    s = str(mult_raw).strip().lower()
    if not s:
        return 1.0
    if s.endswith("x"):
        s = s[:-1].strip()
    try:
        m = float(s)
    except (TypeError, ValueError):
        return 1.0
    if m <= 0:
        return 1.0
    return m


def _ats_trade_log_entry_method(trade_id: int) -> Optional[str]:
    """Tenant trades row entry_method for flip-chain guard."""
    conn = get_trades_db_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT entry_method FROM {legacy_users_trades(ctx_user())} WHERE id = %s",
                (int(trade_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            em = row[0]
            return str(em).strip().lower() if em is not None else None
    except Exception as e:
        log_debug(f"[FLIP SELL] entry_method lookup failed trade_id={trade_id}: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _defer_unified_ats_flip_sell_followup(
    ticket_id: str, log_message: str, notification_data: dict
) -> None:
    """trade_logger + preferences notify off the unified ATS flip-sell hot path (same idea as AES)."""
    slot = ctx_user()

    def _run():
        try:
            from backend.util.trade_logger import log_trade_event

            log_trade_event(ticket_id, log_message, service="active_trade_supervisor")
        except Exception:
            pass
        try:
            from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms

            if use_trading_redis_comms():
                publish_preferences_event(
                    "automated_trade_triggered",
                    notification_data,
                    tenant_user_no=slot,
                )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def _ats_fetch_flip_sell_monitor_row() -> Optional[Tuple[Any, Any, Any, Any, Any]]:
    """
    Returns (flip_sell_prob, flip_sell_prob_mult, flip_sell_floor, flip_sell_floor_mult, paper_trade)
    or None if columns are absent or the monitor row cannot be read.
    """
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            if not monitor_list_flip_columns_available(cur):
                return None
            cur.execute(
                f"""
                SELECT flip_sell_prob, flip_sell_prob_mult, flip_sell_floor, flip_sell_floor_mult, paper_trade
                FROM {legacy_users_monitor_list(ctx_user())}
                WHERE id = %s
                """,
                (ctx_mid(),),
            )
            row = cur.fetchone()
            return tuple(row) if row else None
    except Exception as e:
        log_debug(f"[FLIP SELL] monitor flip row read failed: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _ats_flip_sell_position_after_loss_prevention(flip_count: int) -> Tuple[int, bool]:
    """Return (contracts, loss_prevention_trade_payload). Mirrors AES fractional sim tiers."""
    try:
        from backend.core.symbol_wide_loss_prevention import (
            is_loss_prevention_sizing_state,
            normalize_loss_prevention_state_for_sizing,
            resolve_effective_loss_prevention_state,
        )

        conn = get_db_connection()
        with conn.cursor() as cursor:
            loss_prevention = resolve_effective_loss_prevention_state(
                cursor,
                legacy_users_monitor_list(ctx_user()),
                str(ctx_mid()),
            )
        conn.close()
        lp = normalize_loss_prevention_state_for_sizing(loss_prevention)
        if lp in ("sim_loss_50", "sim_loss_25", "sim_loss_1c", "live_loss_1c"):
            if lp in ("sim_loss_1c", "live_loss_1c"):
                return 1, True
            if lp == "sim_loss_25":
                return max(1, int(round(flip_count * 0.25))), True
            return max(1, int(round(flip_count * 0.5))), True
        if lp == "symbol_one_contract":
            return 1, True
        if lp in ("one_contract", "win_streak_one_contract"):
            return 1, True
        return flip_count, is_loss_prevention_sizing_state(loss_prevention)
    except Exception as e:
        log_debug(f"[FLIP SELL] loss_prevention read failed: {e}")
        return flip_count, False


def _ats_get_multiplier_from_monitor() -> float:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT multiplier FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s",
                (ctx_mid(),),
            )
            result = cursor.fetchone()
        conn.close()
        if result and result[0] is not None:
            return float(result[0])
    except Exception as e:
        log_debug(f"[FLIP SELL] multiplier read failed: {e}")
    return 1.0


def _ats_get_bankroll_allotment() -> Optional[Any]:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT bankroll_allotment_total FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s",
                (ctx_mid(),),
            )
            result = cursor.fetchone()
        conn.close()
        if result:
            return result[0]
    except Exception as e:
        log_debug(f"[FLIP SELL] bankroll_allotment read failed: {e}")
    return None


def _ats_get_paper_trade_from_monitor() -> bool:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT paper_trade FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s",
                (ctx_mid(),),
            )
            result = cursor.fetchone()
        conn.close()
        if result and result[0] is not None:
            v = result[0]
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes")
            return bool(v)
    except Exception as e:
        log_debug(f"[FLIP SELL] paper_trade read failed: {e}")
    return False


def trigger_flip_sell_open_after_auto_stop(
    trade: Dict[str, Any],
    trigger_reason: str,
    pos_closed: int,
    inverted_side: str,
) -> bool:
    """
    After a successful auto-stop close enqueue, optionally open a flip leg on the same monitor.

    **Strict:** only ``stop_loss_floor`` / ``probability_auto_stop`` plus matching monitor
    ``flip_sell_floor`` / ``flip_sell_prob`` must be the PostgreSQL boolean TRUE (not NULL).
    """
    tr = (trigger_reason or "").strip().lower()
    if tr not in ("stop_loss_floor", "probability_auto_stop"):
        return False

    row = _ats_fetch_flip_sell_monitor_row()
    if row is None:
        log_debug("[FLIP SELL] skip: flip columns absent or monitor row unavailable")
        return False

    flip_prob, prob_mult_raw, flip_floor, floor_mult_raw, _paper_col = row
    if tr == "stop_loss_floor":
        if not _ats_monitor_flip_boolean_strictly_true(flip_floor):
            log_debug(
                f"[FLIP SELL] skip floor stop: flip_sell_floor is not TRUE for monitor {ctx_mid()}"
            )
            return False
        mult_raw = floor_mult_raw
    else:
        if not _ats_monitor_flip_boolean_strictly_true(flip_prob):
            log_debug(
                f"[FLIP SELL] skip prob stop: flip_sell_prob is not TRUE for monitor {ctx_mid()}"
            )
            return False
        mult_raw = prob_mult_raw

    tid = trade.get("trade_id")
    try:
        tid_int = int(tid) if tid is not None else None
    except (TypeError, ValueError):
        tid_int = None
    if tid_int is None:
        return False

    em = _ats_trade_log_entry_method(tid_int)
    if em == "flip_sell":
        log_debug(f"[FLIP SELL] skip: trade {tid_int} already flip_sell entry_method (no chain)")
        return False

    mult = parse_flip_sell_multiplier(mult_raw)
    flip_count = max(1, int(round(float(pos_closed) * mult)))
    if flip_count < 1:
        return False

    if not trade.get("ticker") or trade.get("strike") is None:
        log_debug(f"[FLIP SELL] skip trade_id={tid}: missing ticker or strike")
        return False

    current_close_price = trade.get("current_close_price")
    symbol_close = trade.get("current_symbol_price")
    if current_close_price is None or symbol_close is None:
        log_debug(f"[FLIP SELL] skip trade_id={tid}: missing price snapshot for open")
        return False

    try:
        flip_buy_price = float(current_close_price)
    except (TypeError, ValueError):
        log_debug(f"[FLIP SELL] skip trade_id={tid}: invalid current_close_price")
        return False

    conn = None
    try:
        symbol, market = get_current_monitor_symbol_and_market()
        mnorm = (market or "").strip().lower()
        if mnorm in ("15m", "hourly"):
            conn = get_db_connection()
            try:
                ok, reason = evaluate_pipeline_gate_conn(
                    conn,
                    exchange="kalshi",
                    market=mnorm,
                    symbol=str(symbol or "").upper(),
                )
            finally:
                conn.close()
                conn = None
            if not ok:
                log(
                    f"[FLIP SELL] 🚫 BLOCKED by pipeline gate symbol={symbol} market={mnorm} "
                    f"reason={reason} trade_id={tid}"
                )
                return False
    except Exception as gate_err:
        log(f"[FLIP SELL] 🚫 BLOCKED by pipeline gate check error: {gate_err} trade_id={tid}")
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        return False

    import random

    ticket_id = f"TICKET-{random.getrandbits(32):08x}-{int(time.time() * 1000)}"
    now = wall_now()
    eastern_date = now.strftime("%Y-%m-%d")
    eastern_time = now.strftime("%H:%M:%S")
    current_symbol = get_current_monitor_symbol()
    trade_strategy = get_trade_strategy()
    paper_trade = _ats_get_paper_trade_from_monitor()
    position_out, loss_prevention_flag = _ats_flip_sell_position_after_loss_prevention(flip_count)
    bankroll_allotment = _ats_get_bankroll_allotment()
    if bankroll_allotment is None:
        log(f"[FLIP SELL] skip trade_id={tid}: no bankroll_allotment_total on monitor")
        return False

    monitor_key = trade.get("monitor") or f"mon_{ctx_user()}_{ctx_mid()}"
    prob_out = trade.get("current_probability")
    diff_out = trade.get("diff")

    open_payload: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "status": "pending",
        "date": eastern_date,
        "time": eastern_time,
        "symbol": current_symbol,
        "exchange": "kalshi",
        "trade_strategy": trade_strategy,
        "contract": trade.get("contract"),
        "strike": trade.get("strike"),
        "side": inverted_side,
        "ticker": trade.get("ticker"),
        "prob": prob_out,
        "diff": diff_out,
        "buy_price": flip_buy_price,
        "position": position_out,
        "count_fp": f"{float(position_out):.2f}",
        "monitor": monitor_key,
        "bankroll_allotment_total": bankroll_allotment,
        "entry_method": "flip_sell",
        "loss_prevention": loss_prevention_flag,
        "multiplier": _ats_get_multiplier_from_monitor(),
        "paper_trade": paper_trade,
    }

    log_message = (
        f"FLIP_SELL OPEN | trigger={tr} | {trade.get('ticker')} | {trade.get('strike')} | "
        f"side={inverted_side} | count={position_out} (closed={pos_closed} mult={mult}) | "
        f"buy_price={flip_buy_price}"
    )
    notification_data = {
        "strike": trade.get("strike"),
        "side": inverted_side,
        "ticker": trade.get("ticker"),
        "buy_price": flip_buy_price,
        "probability": prob_out,
        "contract": trade.get("contract"),
        "position": position_out,
        "entry_method": "flip_sell",
        "auto_stop_trigger": tr,
    }

    try:
        from backend.core.trading_redis_comms import publish_trade_manager_command, use_trading_redis_comms

        use_redis = use_trading_redis_comms()
        if use_redis and publish_trade_manager_command(
            "add_trade",
            open_payload,
            "active_trade_supervisor",
            correlation_id=ticket_id,
            tenant_user_no=ctx_user(),
        ):
            if ATS_UNIFIED_POOL:
                log(
                    f"[FLIP SELL] OPEN enqueued (Redis) trade_id={tid} ticker={trade.get('ticker')} "
                    f"position={position_out} trigger={tr}"
                )
                _defer_unified_ats_flip_sell_followup(ticket_id, log_message, notification_data)
                return True

            from backend.util.trade_logger import log_trade_event

            log_trade_event(ticket_id, log_message, service="active_trade_supervisor")
            try:
                from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms as _use_trc

                if _use_trc():
                    publish_preferences_event(
                        "automated_trade_triggered",
                        notification_data,
                        tenant_user_no=ctx_user(),
                    )
            except Exception:
                pass
            log(
                f"[FLIP SELL] OPEN enqueued (Redis) trade_id={tid} ticker={trade.get('ticker')} "
                f"position={position_out} trigger={tr}"
            )
            return True

        if not ATS_HTTP_FALLBACK_ENABLED:
            log(
                f"[FLIP SELL] Redis open enqueue unavailable trade_id={tid}; "
                "ATS_HTTP_FALLBACK_ENABLED=0 so HTTP fallback is disabled"
            )
            return False

        tm_port = scoped_trade_manager_http_port()
        url = get_service_url(tm_port) + "/trades"
        resp = requests.post(url, json=open_payload, timeout=10)
        if resp.status_code in (200, 201):
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get("error"):
                    log(f"[FLIP SELL] Open rejected trade_id={tid}: {body.get('error')}")
                    return False
            except Exception:
                pass
            from backend.util.trade_logger import log_trade_event

            log_trade_event(ticket_id, log_message, service="active_trade_supervisor")
            try:
                from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms as _use_trc2

                if _use_trc2():
                    publish_preferences_event(
                        "automated_trade_triggered",
                        notification_data,
                        tenant_user_no=ctx_user(),
                    )
            except Exception:
                pass
            log(
                f"[FLIP SELL] OPEN via HTTP trade_id={tid} ticker={trade.get('ticker')} "
                f"position={position_out} trigger={tr}"
            )
            return True
        log(
            f"[FLIP SELL] OPEN failed trade_id={tid}: {resp.status_code} {getattr(resp, 'text', '')}"
        )
        return False
    except Exception as e:
        log(f"[FLIP SELL] OPEN exception trade_id={tid}: {e}")
        return False


def _ats_after_successful_auto_stop_close_enqueue_flip(
    trade: Dict[str, Any],
    *,
    trigger_reason: str,
    pos_int: int,
    inverted_side: str,
) -> None:
    """Never raises; flip is strictly opt-in per monitor boolean."""
    try:
        trigger_flip_sell_open_after_auto_stop(trade, trigger_reason, pos_int, inverted_side)
    except Exception as e:
        log(f"[FLIP SELL] post-close hook error trade_id={trade.get('trade_id')}: {e}")


def trigger_auto_stop_close(
    trade,
    *,
    trigger_reason: str = "unknown",
    trigger_detail: Optional[str] = None,
):
    """Trigger a close for the given trade using the same payload as manual close.

    trigger_reason (stable codes for grep / analytics):
      stop_loss_floor, probability_auto_stop, momentum_spike,
      scalp_max_profit, scalp_trailing_stop, scalp_profit_target,
      reversal_max_profit, reversal_trailing_stop, reversal_profit_target,
      close_attempt_failed_retry, unknown

    trigger_detail: short human-readable context (thresholds, prob, momentum, etc.).

    close_method on the tenant trades row is set via _close_method_for_auto_trigger(trigger_reason).
    Returns True if close was successful, False otherwise.
    """
    import requests
    import random

    tid = trade.get("trade_id")
    if should_suppress_auto_close_past_kalshi_settlement(trade.get("ticker"), tid):
        return False

    conn = None
    try:
        symbol, market = get_current_monitor_symbol_and_market()
        mnorm = (market or "").strip().lower()
        if mnorm in ("15m", "hourly"):
            conn = get_db_connection()
            try:
                ok, reason = evaluate_pipeline_gate_conn(
                    conn,
                    exchange="kalshi",
                    market=mnorm,
                    symbol=str(symbol or "").upper(),
                )
            finally:
                conn.close()
            if not ok:
                log(
                    f"[AUTO STOP] 🚫 BLOCKED by pipeline gate symbol={symbol} market={mnorm} "
                    f"reason={reason} trigger={trigger_reason} trade_id={tid}"
                )
                return False
    except Exception as gate_err:
        log(
            f"[AUTO STOP] 🚫 BLOCKED by pipeline gate check error: {gate_err} "
            f"trigger={trigger_reason} trade_id={tid}"
        )
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        return False

    # Generate unique ticket ID (single braces: random/time must run)
    ticket_id = f"TICKET-{random.getrandbits(32):08x}-{int(time.time() * 1000)}"
    # Position leg (YES/NO) as stored on the trade — same convention as manual opens and trade_executor:
    # all orders are "buys"; trade_executor maps intent=close to buying the *opposite* leg.
    # Do NOT send inverted side here; that doubled exposure (e.g. NO position + close with YES legacy → buy more NO / ask again).
    position_side = trade["side"]
    su = str(position_side).strip().upper()
    inverted_side = (
        "N"
        if su in ("Y", "YES")
        else "Y"
        if su in ("N", "NO")
        else position_side
    )
    # Get current_close_price (opposite side's ask) and convert to actual sell_price
    # current_close_price is the opposite side's ask, so sell_price = 1 - current_close_price
    current_close_price = trade.get('current_close_price')
    symbol_close = trade.get('current_symbol_price')
    if current_close_price is None or symbol_close is None:
        log(
            f"[AUTO STOP] Skipping close trigger={trigger_reason} trade_id={tid} "
            f"— missing price data (current_close_price or current_symbol_price)"
        )
        return False
    
    # Convert current_close_price (opposite side's ask) to actual sell_price
    # For both YES and NO trades: sell_price = 1 - opposite_side_ask
    sell_price = 1.0 - float(current_close_price) if hasattr(current_close_price, '__float__') else 1.0 - current_close_price
    
    # Convert Decimal objects to float for JSON serialization
    sell_price_float = float(sell_price) if hasattr(sell_price, '__float__') else sell_price
    symbol_close_float = float(symbol_close) if hasattr(symbol_close, '__float__') else symbol_close
    
    position_val = trade.get('position', 1)
    close_method_val = _close_method_for_auto_trigger(trigger_reason)
    try:
        trade_pk = int(trade["trade_id"]) if trade.get("trade_id") is not None else None
    except (TypeError, ValueError):
        trade_pk = trade.get("trade_id")
    try:
        pos_f = round(float(position_val), 2) if position_val is not None else 1.0
    except (TypeError, ValueError):
        pos_f = 1.0
    if pos_f <= 0:
        pos_f = 1.0
    try:
        pos_int = max(1, int(round(pos_f)))
    except (TypeError, ValueError):
        pos_int = 1
    payload = {
        "id": trade_pk,
        "ticket_id": ticket_id,
        "intent": "close",
        "ticker": trade["ticker"],
        "side": position_side,
        "count": pos_f,
        "count_fp": f"{pos_f:.2f}",
        "action": "close",
        "type": "market",
        "order_type": "market",
        "time_in_force": "immediate_or_cancel",
        "buy_price": float(sell_price_float),
        "symbol_close": float(symbol_close_float),
        "close_method": close_method_val,
        "monitor": trade.get("monitor"),
    }
    try:
        from backend.core.trading_redis_comms import publish_trade_manager_command, use_trading_redis_comms

        detail_part = f" | {trigger_detail}" if trigger_detail else ""
        log_message = (
            f"CLOSE | close_method={close_method_val} | trigger={trigger_reason} | {trigger_detail or '-'} | "
            f"{trade.get('ticker', 'Unknown')} | {trade.get('strike')} | {trade.get('side')} | "
            f"{trade.get('position')} | {sell_price} | {trade.get('current_probability')} | "
            f"{trade.get('current_pnl', 'Unknown')}"
        )
        buy_price_float = (
            float(trade.get("buy_price"))
            if hasattr(trade.get("buy_price"), "__float__")
            else trade.get("buy_price")
        )
        probability_float = (
            float(trade.get("current_probability"))
            if hasattr(trade.get("current_probability"), "__float__")
            else trade.get("current_probability")
        )
        notification_data = {
            "type": "automated_trade_closed",
            "trade_id": trade["trade_id"],
            "ticker": trade["ticker"],
            "strike": trade["strike"],
            "side": trade["side"],
            "buy_price": buy_price_float,
            "sell_price": sell_price_float,
            "position": trade["position"],
            "probability": probability_float,
            "pnl": trade.get("current_pnl"),
            "timestamp": wall_now().isoformat(),
            "close_method": close_method_val,
            "auto_stop_trigger": trigger_reason,
            "auto_stop_trigger_detail": trigger_detail,
        }

        use_redis = use_trading_redis_comms()
        resp = None
        if use_redis and publish_trade_manager_command(
            "add_trade",
            payload,
            "active_trade_supervisor",
            correlation_id=ticket_id,
            tenant_user_no=ctx_user(),
        ):
            if ATS_UNIFIED_POOL:
                log(
                    f"[AUTO STOP] CLOSE enqueued (Redis) trigger={trigger_reason}{detail_part} "
                    f"close_method={close_method_val} trade_id={tid} ticker={trade.get('ticker')} "
                    f"prob={trade.get('current_probability')} sell_price={sell_price_float:.4f}"
                )
                _defer_unified_ats_close_followup(ticket_id, log_message, notification_data)
                _ats_after_successful_auto_stop_close_enqueue_flip(
                    trade,
                    trigger_reason=trigger_reason,
                    pos_int=pos_int,
                    inverted_side=inverted_side,
                )
                return True

            class _Ok:
                status_code = 201
                text = ""

                def json(self):
                    return {}

            resp = _Ok()
        if resp is None:
            if not ATS_HTTP_FALLBACK_ENABLED:
                log(
                    f"[AUTO STOP] Redis close enqueue unavailable trigger={trigger_reason} trade_id={tid}; "
                    "ATS_HTTP_FALLBACK_ENABLED=0 so HTTP fallback is disabled"
                )
                return False
            if ATS_UNIFIED_POOL:
                log(
                    "[AUTO STOP] ⚠️ Unified pool: Redis add_trade unavailable; "
                    f"falling back to HTTP POST trade_manager_{ctx_user()} /trades (same as AES)"
                )
            tm_port = scoped_trade_manager_http_port()
            url = get_service_url(tm_port) + "/trades"
            resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 201 or resp.status_code == 200:
            try:
                body = resp.json()
                if isinstance(body, dict) and body.get("error"):
                    log(
                        f"[AUTO STOP] Close rejected (proxy/body error) trigger={trigger_reason} "
                        f"trade_id={tid}: {body.get('error')}"
                    )
                    return False
            except Exception:
                pass
            log(
                f"[AUTO STOP] CLOSE trigger={trigger_reason}{detail_part} "
                f"close_method={close_method_val} trade_id={tid} ticker={trade.get('ticker')} "
                f"prob={trade.get('current_probability')} sell_price={sell_price_float:.4f}"
            )

            from backend.util.trade_logger import log_trade_event

            log_trade_event(ticket_id, log_message, service="active_trade_supervisor")

            try:
                notification_url = (
                    get_service_url(ACTIVE_TRADE_SUPERVISOR_PORT) + "/api/notify_automated_close"
                )
                notification_response = requests.post(
                    notification_url, json=notification_data, timeout=2
                )
                if notification_response.ok:
                    log_debug("Frontend notification sent for automated trade close")
                else:
                    log(
                        f"[AUTO STOP] ⚠️ Frontend notification failed: "
                        f"{notification_response.status_code}"
                    )
            except Exception as e:
                log(f"[AUTO STOP] ❌ Error sending frontend notification: {e}")

            _ats_after_successful_auto_stop_close_enqueue_flip(
                trade,
                trigger_reason=trigger_reason,
                pos_int=pos_int,
                inverted_side=inverted_side,
            )
            return True
        log(
            f"[AUTO STOP] Failed to trigger close trigger={trigger_reason} trade_id={tid}: "
            f"{resp.status_code} {getattr(resp, 'text', '')}"
        )
        return False
    except Exception as e:
        # Check if this is a timeout exception
        is_timeout = 'timeout' in str(e).lower() or 'timed out' in str(e).lower()
        
        if is_timeout:
            # For timeout exceptions, check if the trade status changed to "closing" or "closed"
            # This indicates the request was processed even though the response timed out
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                active_trades_table = get_monitor_active_trades_table()
                cursor.execute(f"SELECT status FROM users.{active_trades_table} WHERE trade_id = %s", (trade['trade_id'],))
                result = cursor.fetchone()
                conn.close()
                
                if result and result[0] in ['closing', 'closed']:
                    # Trade status changed, so the close request was processed successfully
                    log(
                        f"[AUTO STOP] ⚠️ Request timeout trigger={trigger_reason} trade_id={tid}, "
                        f"but trade status is '{result[0]}' - treating as success"
                    )
                    _ats_after_successful_auto_stop_close_enqueue_flip(
                        trade,
                        trigger_reason=trigger_reason,
                        pos_int=pos_int,
                        inverted_side=inverted_side,
                    )
                    return True
            except Exception as db_check_error:
                log(f"[AUTO STOP] ⚠️ Timeout for trade {trade['trade_id']}, but could not verify status: {db_check_error}")
        
        log(f"[AUTO STOP] Exception posting close trigger={trigger_reason} trade_id={tid}: {e}")
        return False


def _ats_fetch_tenant_trade_status(trade_id: int) -> Optional[str]:
    """Lowercase ``status`` from tenant ``trades_*`` for ``id``, or None if missing."""
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT status FROM {legacy_users_trades(ctx_user())} WHERE id = %s",
                (trade_id,),
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                return None
            return str(row[0]).strip().lower()
    finally:
        conn.close()


def _ats_fetch_pool_row_for_close_retry(trade_id: int):
    """Pool row columns for auto-close payload, or None."""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(
            f"""
            SELECT trade_id, ticker, strike, side, position, buy_price,
                   current_close_price, current_symbol_price, current_probability, current_pnl
            FROM users.{active_trades_table}
            WHERE trade_id = %s
            """,
            (trade_id,),
        )
        return cursor.fetchone()
    finally:
        conn.close()


def _ats_trade_dict_from_close_retry_pool_row(trade_data) -> Dict[str, Any]:
    (
        trade_id_db,
        ticker,
        strike,
        side,
        position,
        buy_price,
        current_close_price,
        current_symbol_price,
        current_probability,
        current_pnl,
    ) = trade_data
    return {
        "trade_id": trade_id_db,
        "ticker": ticker,
        "strike": strike,
        "side": side,
        "position": position,
        "buy_price": buy_price,
        "current_close_price": current_close_price,
        "current_symbol_price": current_symbol_price,
        "current_probability": current_probability,
        "current_pnl": current_pnl,
    }


def _close_volume_retry_worker(user_num: str, monitor_id: str, trade_id: int) -> None:
    """Every ``ATS_CLOSE_VOLUME_RETRY_INTERVAL_SEC`` (default 10), retry auto-close while trade is still open."""
    interval = max(1.0, float(os.getenv("ATS_CLOSE_VOLUME_RETRY_INTERVAL_SEC", "10")))
    key = (user_num, monitor_id, trade_id)
    try:
        with ats_monitor_bind(user_num, monitor_id):
            log(
                f"[CLOSE RETRY] Started {interval:g}s loop for volume/precheck failures "
                f"trade_id={trade_id} user={user_num} monitor={monitor_id}"
            )
            while True:
                time.sleep(interval)
                pg_status = _ats_fetch_tenant_trade_status(trade_id)
                if pg_status is None:
                    log_debug(f"[CLOSE RETRY] trade_id={trade_id} missing tenant trades row; stopping loop")
                    break
                if pg_status in ("closed", "expired"):
                    log(f"[CLOSE RETRY] trade_id={trade_id} PG status={pg_status}; stopping loop")
                    break
                if pg_status == "closing":
                    log_debug(f"[CLOSE RETRY] trade_id={trade_id} PG status=closing; waiting")
                    continue
                if pg_status not in ("open", "partial"):
                    log_debug(
                        f"[CLOSE RETRY] trade_id={trade_id} PG status={pg_status} (not open/partial); stopping loop"
                    )
                    break

                trade_data = _ats_fetch_pool_row_for_close_retry(trade_id)
                if not trade_data:
                    log(f"[CLOSE RETRY] trade_id={trade_id} not in monitor pool; stopping loop")
                    break
                ticker = trade_data[1]
                if should_suppress_auto_close_past_kalshi_settlement(ticker, trade_id):
                    log(
                        f"[CLOSE RETRY] trade_id={trade_id} past Kalshi close/settlement window; stopping loop"
                    )
                    break

                trade_dict = _ats_trade_dict_from_close_retry_pool_row(trade_data)
                log(f"[CLOSE RETRY] trade_id={trade_id} enqueue auto close (volume/precheck retry)")
                trigger_auto_stop_close(
                    trade_dict,
                    trigger_reason="close_attempt_failed_retry",
                    trigger_detail="volume_precheck_retry_loop",
                )
    except Exception as e:
        log(f"[CLOSE RETRY] trade_id={trade_id} worker error: {e}")
    finally:
        with _close_volume_retry_lock:
            _close_volume_retry_active.discard(key)
        log_debug(f"[CLOSE RETRY] trade_id={trade_id} loop ended")


def handle_close_attempt_failed_trade(trade_id: int, ticket_id: str) -> bool:
    """
    trade_manager reverted the tenant trade row to ``open`` after a failed close (volume/precheck).
    Revert the monitor pool row to ``active`` and run a 10s retry loop until closed, expired, or
    past the Kalshi auto-close window (see ``should_suppress_auto_close_past_kalshi_settlement``).
    """
    user_num = ctx_user()
    monitor_id = ctx_mid()
    key = (user_num, monitor_id, int(trade_id))
    try:
        conn = get_db_connection()
        if not conn:
            log(f"⚠️ close_attempt_failed: no DB connection for trade_id={trade_id}")
            return False
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(
            f"""
            SELECT trade_id, ticker, strike, side, position, buy_price,
                   current_close_price, current_symbol_price, current_probability, current_pnl
            FROM users.{active_trades_table}
            WHERE trade_id = %s
            """,
            (trade_id,),
        )
        trade_data = cursor.fetchone()
        conn.close()

        if not trade_data:
            log(f"⚠️ Trade with ID {trade_id} not found in monitor pool for close_attempt_failed.")
            return False

        ticker = trade_data[1]

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE users.{active_trades_table}
            SET status = 'active',
                current_close_price = NULL,
                current_pnl = NULL,
                last_updated = CURRENT_TIMESTAMP
            WHERE trade_id = %s
            """,
            (trade_id,),
        )
        conn.commit()
        conn.close()

        log("🔄 CLOSE ATTEMPT FAILED - REVERTING POOL ROW TO ACTIVE STATUS")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticker: {ticker}")
        log("   ========================================")

        invalidate_active_trades_cache()
        broadcast_active_trades_change()

        start_worker = False
        with _close_volume_retry_lock:
            if key not in _close_volume_retry_active:
                _close_volume_retry_active.add(key)
                start_worker = True

        if start_worker:
            try:
                threading.Thread(
                    target=_close_volume_retry_worker,
                    args=(user_num, monitor_id, int(trade_id)),
                    daemon=True,
                    name=f"ats-close-vol-retry-{trade_id}",
                ).start()
            except Exception as te:
                with _close_volume_retry_lock:
                    _close_volume_retry_active.discard(key)
                log(f"❌ close_attempt_failed: could not start retry thread trade_id={trade_id}: {te}")
                return False
        else:
            log_debug(
                f"[CLOSE RETRY] trade_id={trade_id} retry loop already running; pool row refreshed to active"
            )
        return True

    except Exception as e:
        log(f"❌ Error handling close_attempt_failed trade {trade_id}: {e}")
        with _close_volume_retry_lock:
            _close_volume_retry_active.discard(key)
        return False

# Auto stop settings read from the tenant monitor_list row for ctx_user()/ctx_mid().

def get_trade_strategy():
    """Get trade strategy from monitor-specific configuration"""
    conn = None
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT strategy FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            if result:
                trade_strategy = result[0]
                return trade_strategy
            else:
                log(f"[AUTO STOP] No monitor configuration found for monitor {ctx_mid()}")
                return "Hourly HTC"  # Default fallback
    except Exception as e:
        log(f"[AUTO STOP] Error loading trade strategy from monitor {ctx_mid()}: {e}")
        return "Hourly HTC"  # Default fallback
    finally:
        if conn:
            conn.close()

def get_momentum_scalp_trailing_stop_amount():
    """Get momentum scalp trailing stop amount from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT momentum_scalp_trailing_stop_amount FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No trailing stop amount found for monitor {ctx_mid()}, using default 0.10")
                return 0.10  # Default 10% trailing stop
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading trailing stop amount: {e}")
        return 0.10  # Default fallback

def get_momentum_scalp_profit_target():
    """Get momentum scalp profit target from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT momentum_scalp_profit_target FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No profit target found for monitor {ctx_mid()}, using default 0.50")
                return 0.50  # Default 50% profit target
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading profit target: {e}")
        return 0.50  # Default fallback

def get_max_profit():
    """Get max_profit from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT max_profit FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No max_profit found for monitor {ctx_mid()}, using default 0.9900")
                return 0.9900  # Default 99% max profit
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading max_profit: {e}")
        return 0.9900  # Default fallback

def get_momentum_scalp_entry_threshold():
    """Get momentum scalp entry threshold from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT momentum_scalp_entry_threshold FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No momentum_scalp_entry_threshold found for monitor {ctx_mid()}, using default 35.0")
                return 35.0  # Default threshold
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading momentum_scalp_entry_threshold: {e}")
        return 35.0  # Default fallback

def get_auto_stop_threshold():
    """Get auto stop probability threshold from monitor's assigned strategy"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {ctx_mid()}")
                return 40
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {ctx_mid()}")
                return 40
            
            # Get the threshold from the monitor
            cursor.execute(f"""
                SELECT current_probability FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                threshold = result[0]
                return threshold
            else:
                log_debug(f"No strategy found with name: {strategy_name}")
                return 40
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading threshold from strategy: {e}")
        return 40

def get_unified_ttc_seconds(symbol: str = None):
    """Get unified TTC from master strike table (uses monitor symbol+market when symbol is None)."""
    try:
        sym, mkt = _get_symbol_and_market_for_strike(symbol)
        ladder = fetch_strike_ladder_prefer_snapshot(sym, mkt, DEFAULT_EXCHANGE)
        if ladder is not None and ladder.get("ttc") is not None:
            return int(ladder["ttc"])
        table_name = get_strike_table_name(sym, mkt)
        conn = get_db_connection()
        cursor = conn.cursor()
        ttc_column = "ttc_15m" if mkt == "15m" else "ttc_hourly"
        cursor.execute(
            f"""
            SELECT {ttc_column} FROM live_data.{table_name}
            WHERE exchange = %s AND symbol = %s
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (DEFAULT_EXCHANGE, sym.upper()),
        )
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return int(result[0])
        else:
            log_debug(f"No TTC data from master strike table, using fallback calculation")
            # Fallback to simple calculation
            now = wall_now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            return max(1, int((next_hour - now).total_seconds()))
            
    except Exception as e:
        log(f"[AUTO STOP] Error reading TTC from master strike table: {e}")
        # Fallback to simple calculation
        now = wall_now()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return max(1, int((next_hour - now).total_seconds()))

def get_min_ttc_seconds():
    """Get the minimum TTC seconds setting from monitor's assigned strategy"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {ctx_mid()}")
                return 60
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {ctx_mid()}")
                return 60
            
            # Get the min_ttc_seconds from the monitor
            cursor.execute(f"""
                SELECT min_ttc_seconds FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                min_ttc = result[0]
                return min_ttc
            else:
                log_debug(f"No strategy found with name: {strategy_name}")
                return 60
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading min_ttc_seconds from strategy: {e}")
        return 60

def get_verification_period_enabled():
    """Get the verification period enabled setting from monitor's assigned strategy"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {ctx_mid()}")
                return False
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {ctx_mid()}")
                return False
            
            # Get the verification_period_enabled from the monitor
            cursor.execute(f"""
                SELECT verification_period_enabled FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                enabled = result[0]
                return enabled
            else:
                log_debug(f"No strategy found with name: {strategy_name}")
                return False
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading verification_period_enabled from strategy: {e}")
        return False

def get_verification_period_seconds():
    """Get the verification period seconds setting from monitor's assigned strategy"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {ctx_mid()}")
                return 15
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {ctx_mid()}")
                return 15
            
            # Get the verification_period_seconds from the monitor
            cursor.execute(f"""
                SELECT verification_period_seconds FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s
            """, (ctx_mid(),))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                seconds = result[0]
                return seconds
            else:
                log_debug(f"No strategy found with name: {strategy_name}")
                return 15
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading verification_period_seconds from strategy: {e}")
        return 15

def get_stop_loss_price():
    """Opposite-side ask stop floor in contract dollars; 0.0000 means disabled (never triggers)."""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT stop_loss_price FROM {legacy_users_monitor_list(ctx_user())} WHERE id = %s",
                (ctx_mid(),),
            )
            row = cursor.fetchone()
            conn.close()
            if row and row[0] is not None:
                v = float(row[0])
                return max(0.0, min(v, 0.99))
            return 0.0
    except Exception as e:
        log(f"[AUTO STOP] Error reading stop_loss_price: {e}")
        return 0.0


def _try_stop_loss_ask_floor(
    trade,
    stop_floor: float,
    auto_stop_triggered_trades,
    verification_pending_trades,
    min_ttc_seconds,
    ttc_seconds,
) -> bool:
    """
    Rip-cord when opposite-side ask (current_close_price) > (1 - stop_loss_price).

    With ATS_STOP_LOSS_FLOOR_GUARD (default on): requires point DB quote agreement within
    ATS_STOP_LOSS_FLOOR_MAX_QUOTE_DISAGREE, direct ask past the same threshold, and
    ATS_STOP_LOSS_FLOOR_CONFIRM_TICKS consecutive evaluations (default 2, ~1s apart) so a
    single bad snapshot row cannot close the trade.

    With ATS_STOP_LOSS_FLOOR_PROB_MARK_DIVERGENCE_POINTS (default 50): skips the close when
    current_probability (0–100) minus ``(1 - opp_ask) * 100`` exceeds that margin (API/quote
    glitch vs model path disagree).

    Ignores probability verification. Respects min_ttc_seconds like probability auto-stop.
    Returns True if this trade was handled (caller should continue to next trade).
    """
    try:
        sf = float(stop_floor)
    except (TypeError, ValueError):
        return False
    if sf <= 0:
        return False
    trade_id = trade.get("trade_id")
    if trade.get("status") != "active" or trade_id in auto_stop_triggered_trades:
        return False
    try:
        mttc = int(min_ttc_seconds) if min_ttc_seconds is not None else 0
    except (TypeError, ValueError):
        mttc = 0
    if ttc_seconds is None:
        return False
    try:
        if int(ttc_seconds) < mttc:
            return False
    except (TypeError, ValueError):
        return False
    ccp = trade.get("current_close_price")
    if ccp is None:
        return False
    try:
        opp_ask = float(ccp)
        threshold_ask = 1.0 - sf
        try:
            tid_key = int(trade_id) if trade_id is not None else None
        except (TypeError, ValueError):
            tid_key = None

        if opp_ask <= threshold_ask:
            if tid_key is not None:
                _stop_loss_floor_confirm_ticks.pop(tid_key, None)
            return False

        if trade_id in verification_pending_trades:
            del verification_pending_trades[trade_id]

        direct: Optional[float] = None
        if _stop_loss_floor_guard_enabled() and tid_key is not None:
            sym_m, mkt_m = get_current_monitor_symbol_and_market()
            t_sym = trade.get("symbol") or sym_m
            direct = _kalshi_direct_closing_price_for_ticker(
                trade.get("ticker"),
                trade.get("side"),
                str(t_sym).strip() if t_sym else None,
                (mkt_m or "hourly"),
            )
            if direct is None:
                log_debug(
                    f"[AUTO STOP FLOOR] guard: no direct Kalshi quote trade_id={trade_id} "
                    f"ticker={trade.get('ticker')}"
                )
                _stop_loss_floor_confirm_ticks.pop(tid_key, None)
                return False
            max_d = _stop_loss_floor_max_quote_disagree()
            if abs(opp_ask - direct) > max_d:
                log(
                    f"[AUTO STOP FLOOR] blocked: stored vs direct disagree beyond {max_d:.2f} "
                    f"stored_opp={opp_ask:.4f} direct_opp={direct:.4f} "
                    f"threshold_ask={threshold_ask:.4f} trade_id={trade_id}"
                )
                _stop_loss_floor_confirm_ticks.pop(tid_key, None)
                return False
            if direct <= threshold_ask:
                log(
                    f"[AUTO STOP FLOOR] suppressed: direct quote not past floor "
                    f"direct_opp={direct:.4f} stored_opp={opp_ask:.4f} "
                    f"threshold_ask={threshold_ask:.4f} trade_id={trade_id}"
                )
                _stop_loss_floor_confirm_ticks.pop(tid_key, None)
                return False

            need = _stop_loss_floor_confirm_ticks_required()
            cnt = _stop_loss_floor_confirm_ticks.get(tid_key, 0) + 1
            if cnt < need:
                _stop_loss_floor_confirm_ticks[tid_key] = cnt
                log(
                    f"[AUTO STOP FLOOR] confirm pending {cnt}/{need} "
                    f"opp_ask={opp_ask:.4f} direct_opp={direct if direct is not None else 'n/a'} "
                    f"threshold_ask={threshold_ask:.4f} trade_id={trade_id}"
                )
                return False
            _stop_loss_floor_confirm_ticks.pop(tid_key, None)
        elif tid_key is not None:
            _stop_loss_floor_confirm_ticks.pop(tid_key, None)

        div_max = _stop_loss_floor_prob_mark_divergence_max_points()
        if div_max > 0:
            prob_raw = trade.get("current_probability")
            if prob_raw is not None:
                try:
                    prob_f = float(prob_raw)
                    mark_pts = (1.0 - opp_ask) * 100.0
                    diff = prob_f - mark_pts
                    if diff > div_max:
                        log(
                            f"[AUTO STOP FLOOR] blocked: probability vs implied exit mark divergence "
                            f"prob={prob_f:.2f} implied_exit_mark_pts={mark_pts:.2f} "
                            f"diff={diff:.2f} max_diff={div_max:.2f} opp_ask={opp_ask:.4f} "
                            f"trade_id={trade_id}"
                        )
                        if tid_key is not None:
                            _stop_loss_floor_confirm_ticks.pop(tid_key, None)
                        return False
                except (TypeError, ValueError):
                    pass

        detail = (
            f"opposite_ask={opp_ask:.4f} threshold_ask={threshold_ask:.4f} stop_loss_price={sf:.4f}"
        )
        if direct is not None:
            detail += f" direct_opp={direct:.4f}"
        if trigger_auto_stop_close(
            trade,
            trigger_reason="stop_loss_floor",
            trigger_detail=detail,
        ):
            auto_stop_triggered_trades.add(trade_id)
        else:
            log(f"[AUTO STOP FLOOR] close failed for trade {trade_id}, will retry")
        return True
    except (TypeError, ValueError) as ex:
        log_debug(f"[AUTO STOP FLOOR] skip trade {trade_id}: {ex}")
    return False


def check_auto_stop_conditions(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Router function to check auto-stop conditions based on monitor's strategy.
    Routes to strategy-specific auto-stop logic.
    """
    strategy = get_trade_strategy()
    
    if strategy == "Momentum Scalp":
        check_auto_stop_conditions_momentum_scalp(active_trades, auto_stop_triggered_trades, verification_pending_trades)
    elif strategy == "Momentum Reversal":
        check_auto_stop_conditions_momentum_reversal(active_trades, auto_stop_triggered_trades, verification_pending_trades)
    elif strategy == "Reverse HTC":
        # Reverse HTC uses the same auto-stop logic as Hourly HTC
        check_auto_stop_conditions_hourly_htc(active_trades, auto_stop_triggered_trades, verification_pending_trades)
    else:
        # Default to Hourly HTC (fallback for any other strategy or missing strategy)
        check_auto_stop_conditions_hourly_htc(active_trades, auto_stop_triggered_trades, verification_pending_trades)

def check_auto_stop_conditions_hourly_htc(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Check auto-stop conditions for Hourly HTC strategy.
    This is the original auto-stop logic - DO NOT MODIFY.
    """
    threshold = get_auto_stop_threshold()
    min_ttc_seconds = get_min_ttc_seconds()
    verification_enabled = get_verification_period_enabled()
    verification_seconds = get_verification_period_seconds()
    current_time = time.time()
    stop_floor = get_stop_loss_price()
    
    for trade in active_trades:
        prob = trade.get('current_probability')
        trade_id = trade.get('trade_id')
        ttc_seconds = get_unified_ttc_seconds()
        
        if _try_stop_loss_ask_floor(
            trade, stop_floor, auto_stop_triggered_trades,
            verification_pending_trades, min_ttc_seconds, ttc_seconds,
        ):
            continue
        
        # Check if trade is in verification period
        if trade_id in verification_pending_trades:
            trigger_time, verification_end_time = verification_pending_trades[trade_id]
            
            # Check if verification period has ended
            if current_time >= verification_end_time:
                # Verification period ended - check if conditions still met
                if (
                    prob is not None and
                    (isinstance(prob, (int, float)) or hasattr(prob, '__float__')) and
                    float(prob) < threshold and
                    trade.get('status') == 'active'
                ):
                    # Conditions still met after verification - trigger auto-stop
                    log(f"[AUTO STOP HTC] ✅ Verification period ended - triggering auto stop for trade {trade_id} (prob={prob}, verification_duration={verification_seconds}s)")
                    if trigger_auto_stop_close(
                        trade,
                        trigger_reason="probability_auto_stop",
                        trigger_detail=(
                            f"after_verification prob={prob} threshold={threshold} duration_s={verification_seconds}"
                        ),
                    ):
                        auto_stop_triggered_trades.add(trade_id)
                        del verification_pending_trades[trade_id]
                    else:
                        log(f"[AUTO STOP HTC] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                        del verification_pending_trades[trade_id]
                else:
                    # Conditions no longer met - cancel verification
                    log(f"[AUTO STOP HTC] ❌ Verification period ended - conditions no longer met for trade {trade_id} (prob={prob}, threshold={threshold})")
                    del verification_pending_trades[trade_id]
            else:
                # Still in verification period - just wait, don't check conditions during wait
                remaining_time = verification_end_time - current_time
                if not hasattr(check_auto_stop_conditions_hourly_htc, 'last_verification_log') or current_time - check_auto_stop_conditions_hourly_htc.last_verification_log > 10:
                    log_debug(f"Trade {trade_id} in verification period - {remaining_time:.1f}s remaining")
                    check_auto_stop_conditions_hourly_htc.last_verification_log = current_time
                continue
        
        # Check for new auto-stop conditions
        # Debug logging for trade 2448
        if trade_id == 2448:
            log_debug(f"Trade {trade_id} - prob: {prob}, threshold: {threshold}, status: {trade.get('status')}, in_triggered: {trade_id in auto_stop_triggered_trades}, ttc: {ttc_seconds}, min_ttc: {min_ttc_seconds}")
        
        # Debug logging for trade 2448
        if trade_id == 2448:
            log_debug(f"Trade {trade_id} conditions - prob_valid: {prob is not None}, prob_type: {type(prob)}, prob_lt_threshold: {float(prob) < threshold if prob is not None else 'N/A'}, status_active: {trade.get('status') == 'active'}, not_triggered: {trade_id not in auto_stop_triggered_trades}, ttc_valid: {ttc_seconds is not None}, ttc_ge_min: {ttc_seconds >= min_ttc_seconds if ttc_seconds is not None else 'N/A'}")
        
        auto_stop_conditions_met = (
            prob is not None and
            (isinstance(prob, (int, float)) or hasattr(prob, '__float__')) and
            float(prob) < threshold and
            trade.get('status') == 'active' and
            trade_id not in auto_stop_triggered_trades and
            ttc_seconds is not None and
            ttc_seconds >= min_ttc_seconds # Respect min_ttc_seconds setting
        )
        
        # Debug logging for trade 2448
        if trade_id == 2448:
            log_debug(f"Trade {trade_id} - auto_stop_conditions_met: {auto_stop_conditions_met}")
        
        if auto_stop_conditions_met:
            # Debug logging for trade 2448
            if trade_id == 2448:
                log(f"[AUTO STOP HTC DEBUG] Trade 2448 - verification_enabled: {verification_enabled}")
            
            if verification_enabled:
                # Start verification period
                verification_end_time = current_time + verification_seconds
                verification_pending_trades[trade_id] = (current_time, verification_end_time)
                log(f"[AUTO STOP HTC] 🔍 Starting verification period for trade {trade_id} (prob={prob}, threshold={threshold}, verification_duration={verification_seconds}s)")
            else:
                # No verification - trigger immediately
                log(f"[AUTO STOP HTC] Triggering auto stop for trade {trade_id} (prob={prob}, ttc={ttc_seconds}s, min_ttc={min_ttc_seconds}s)")
                if trigger_auto_stop_close(
                    trade,
                    trigger_reason="probability_auto_stop",
                    trigger_detail=(
                        f"immediate prob={prob} threshold={threshold} ttc={ttc_seconds}s min_ttc={min_ttc_seconds}s"
                    ),
                ):
                    auto_stop_triggered_trades.add(trade_id)
                else:
                    log(f"[AUTO STOP HTC] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
        elif (
            prob is not None and
            (isinstance(prob, (int, float)) or hasattr(prob, '__float__')) and
            float(prob) < threshold and
            trade.get('status') == 'active' and
            trade_id not in auto_stop_triggered_trades and
            (ttc_seconds is None or ttc_seconds < min_ttc_seconds)
        ):
            log(f"[AUTO STOP HTC] Skipping auto stop for trade {trade_id} - TTC ({ttc_seconds}s) below minimum ({min_ttc_seconds}s)")

def check_auto_stop_conditions_momentum_scalp(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Check auto-stop conditions for Momentum Scalp strategy.
    Uses trailing stop and profit target logic instead of probability-based stops.
    """
    trailing_stop_amount = get_momentum_scalp_trailing_stop_amount()
    profit_target = get_momentum_scalp_profit_target()
    max_profit = get_max_profit()
    momentum_threshold = get_momentum_scalp_entry_threshold()
    current_time = time.time()
    stop_floor = get_stop_loss_price()
    min_ttc_seconds = get_min_ttc_seconds()
    
    # Get current momentum percentile for the monitor's symbol
    symbol = get_current_monitor_symbol()
    current_momentum_percentile = get_momentum_percentile_from_postgresql(symbol)
    
    for trade in active_trades:
        trade_id = trade.get('trade_id')
        current_close_price = trade.get('current_close_price')
        high_price = trade.get('high_price')
        buy_price = trade.get('buy_price')
        
        # Skip if required data is missing
        if current_close_price is None or high_price is None or buy_price is None:
            continue
        
        # Convert to float if needed
        try:
            current_close_price = float(current_close_price) if hasattr(current_close_price, '__float__') else current_close_price
            high_price = float(high_price) if hasattr(high_price, '__float__') else high_price
            buy_price = float(buy_price) if hasattr(buy_price, '__float__') else buy_price
        except (ValueError, TypeError):
            log(f"[AUTO STOP MS] ⚠️ Invalid price data for trade {trade_id}, skipping")
            continue
        
        ttc_s = get_unified_ttc_seconds(trade.get("symbol"))
        if _try_stop_loss_ask_floor(
            trade, stop_floor, auto_stop_triggered_trades,
            verification_pending_trades, min_ttc_seconds, ttc_s,
        ):
            continue
        
        # Calculate current position value: 1 - current_close_price
        current_position_value = 1.0 - current_close_price
        
        # Calculate profit target threshold: buy_price + profit_target (relative offset)
        profit_target_threshold = buy_price + profit_target
        
        # PRIORITY 1: Max profit check - immediate close, bypasses verification
        if trade.get('status') == 'active' and trade_id not in auto_stop_triggered_trades:
            if current_position_value >= max_profit:
                log(f"[AUTO STOP MS] 🚨 MAX PROFIT REACHED - Immediate close for trade {trade_id}")
                log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Max profit: {max_profit:.4f}")
                if trigger_auto_stop_close(
                    trade,
                    trigger_reason="scalp_max_profit",
                    trigger_detail=f"position_value={current_position_value:.4f} max_profit={max_profit:.4f}",
                ):
                    auto_stop_triggered_trades.add(trade_id)
                    # Remove from verification if it was pending
                    if trade_id in verification_pending_trades:
                        del verification_pending_trades[trade_id]
                    continue
                else:
                    log(f"[AUTO STOP MS] ❌ Max profit auto stop failed for trade {trade_id}, will retry on next check")
                    continue
        
        # Check if trade is in verification period
        if trade_id in verification_pending_trades:
            trigger_time, verification_end_time = verification_pending_trades[trade_id]
            
            # Check if verification period has ended
            if current_time >= verification_end_time:
                # Re-check conditions after verification period
                trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
                # Profit target only triggers if momentum has fallen below threshold
                profit_target_triggered = False
                if current_position_value >= profit_target_threshold:
                    if current_momentum_percentile is not None:
                        # Only trigger if momentum is below threshold (absolute value check for both positive and negative)
                        if abs(current_momentum_percentile) < abs(momentum_threshold):
                            profit_target_triggered = True
                    else:
                        # If momentum data unavailable, don't trigger profit target
                        log(f"[AUTO STOP MS] ⚠️ Momentum data unavailable for trade {trade_id}, skipping profit target check")
                
                if trailing_stop_triggered or profit_target_triggered:
                    # Conditions still met after verification - trigger auto-stop
                    reason = "trailing stop" if trailing_stop_triggered else "profit target"
                    scalp_trig = "scalp_trailing_stop" if trailing_stop_triggered else "scalp_profit_target"
                    log(f"[AUTO STOP MS] ✅ Verification period ended - triggering auto stop for trade {trade_id} ({reason})")
                    log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    if current_momentum_percentile is not None:
                        log(f"[AUTO STOP MS]   Current momentum: {current_momentum_percentile:.2f}, Threshold: {momentum_threshold:.2f}")
                    if trigger_auto_stop_close(
                        trade,
                        trigger_reason=scalp_trig,
                        trigger_detail=f"after_verification {reason}",
                    ):
                        auto_stop_triggered_trades.add(trade_id)
                        del verification_pending_trades[trade_id]
                    else:
                        log(f"[AUTO STOP MS] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                        del verification_pending_trades[trade_id]
                else:
                    # Conditions no longer met - cancel verification
                    log(f"[AUTO STOP MS] ❌ Verification period ended - conditions no longer met for trade {trade_id}")
                    log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    if current_momentum_percentile is not None:
                        log(f"[AUTO STOP MS]   Current momentum: {current_momentum_percentile:.2f}, Threshold: {momentum_threshold:.2f} (momentum still above threshold, profit target not triggered)")
                    del verification_pending_trades[trade_id]
            else:
                # Still in verification period - just wait
                remaining_time = verification_end_time - current_time
                if not hasattr(check_auto_stop_conditions_momentum_scalp, 'last_verification_log') or current_time - check_auto_stop_conditions_momentum_scalp.last_verification_log > 10:
                    log(f"[AUTO STOP MS] ⏳ Trade {trade_id} in verification period - {remaining_time:.1f}s remaining")
                    check_auto_stop_conditions_momentum_scalp.last_verification_log = current_time
                continue
        
        # Check for new auto-stop conditions
        # Condition 1: Trailing stop - position value has dropped by trailing_stop_amount from high
        trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
        
        # Condition 2: Profit target - position value has reached or exceeded profit target threshold (buy_price + profit_target offset)
        # BUT only triggers if momentum has fallen below threshold
        profit_target_triggered = False
        if current_position_value >= profit_target_threshold:
            if current_momentum_percentile is not None:
                # Only trigger if momentum is below threshold (absolute value check for both positive and negative)
                if abs(current_momentum_percentile) < abs(momentum_threshold):
                    profit_target_triggered = True
            else:
                # If momentum data unavailable, don't trigger profit target
                log(f"[AUTO STOP MS] ⚠️ Momentum data unavailable for trade {trade_id}, skipping profit target check")
        
        auto_stop_conditions_met = (
            trade.get('status') == 'active' and
            trade_id not in auto_stop_triggered_trades and
            (trailing_stop_triggered or profit_target_triggered)
        )
        
        if auto_stop_conditions_met:
            reason = "trailing stop" if trailing_stop_triggered else "profit target"
            scalp_trig = "scalp_trailing_stop" if trailing_stop_triggered else "scalp_profit_target"
            log(f"[AUTO STOP MS] 🎯 Triggering auto stop for trade {trade_id} ({reason})")
            log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
            if current_momentum_percentile is not None:
                log(f"[AUTO STOP MS]   Current momentum: {current_momentum_percentile:.2f}, Threshold: {momentum_threshold:.2f}")
            
            if trigger_auto_stop_close(
                trade,
                trigger_reason=scalp_trig,
                trigger_detail=f"immediate {reason}",
            ):
                auto_stop_triggered_trades.add(trade_id)
            else:
                log(f"[AUTO STOP MS] ❌ Auto stop failed for trade {trade_id}, will retry on next check")

def check_auto_stop_conditions_momentum_reversal(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Check auto-stop conditions for Momentum Reversal strategy.
    Uses trailing stop and profit target logic - NO momentum checks.
    Trade immediately goes into profit taking and stop loss monitoring mode.
    """
    trailing_stop_amount = get_momentum_scalp_trailing_stop_amount()
    profit_target = get_momentum_scalp_profit_target()
    max_profit = get_max_profit()
    current_time = time.time()
    stop_floor = get_stop_loss_price()
    min_ttc_seconds = get_min_ttc_seconds()
    
    for trade in active_trades:
        trade_id = trade.get('trade_id')
        current_close_price = trade.get('current_close_price')
        high_price = trade.get('high_price')
        buy_price = trade.get('buy_price')
        
        # Skip if required data is missing
        if current_close_price is None or high_price is None or buy_price is None:
            continue
        
        # Convert to float if needed
        try:
            current_close_price = float(current_close_price) if hasattr(current_close_price, '__float__') else current_close_price
            high_price = float(high_price) if hasattr(high_price, '__float__') else high_price
            buy_price = float(buy_price) if hasattr(buy_price, '__float__') else buy_price
        except (ValueError, TypeError):
            log(f"[AUTO STOP MR] ⚠️ Invalid price data for trade {trade_id}, skipping")
            continue
        
        ttc_s = get_unified_ttc_seconds(trade.get("symbol"))
        if _try_stop_loss_ask_floor(
            trade, stop_floor, auto_stop_triggered_trades,
            verification_pending_trades, min_ttc_seconds, ttc_s,
        ):
            continue
        
        # Calculate current position value: 1 - current_close_price
        current_position_value = 1.0 - current_close_price
        
        # Calculate profit target threshold: buy_price + profit_target (relative offset)
        profit_target_threshold = buy_price + profit_target
        
        # PRIORITY 1: Max profit check - immediate close, bypasses verification
        if trade.get('status') == 'active' and trade_id not in auto_stop_triggered_trades:
            if current_position_value >= max_profit:
                log(f"[AUTO STOP MR] 🚨 MAX PROFIT REACHED - Immediate close for trade {trade_id}")
                log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Max profit: {max_profit:.4f}")
                if trigger_auto_stop_close(
                    trade,
                    trigger_reason="reversal_max_profit",
                    trigger_detail=f"position_value={current_position_value:.4f} max_profit={max_profit:.4f}",
                ):
                    auto_stop_triggered_trades.add(trade_id)
                    # Remove from verification if it was pending
                    if trade_id in verification_pending_trades:
                        del verification_pending_trades[trade_id]
                    continue
                else:
                    log(f"[AUTO STOP MR] ❌ Max profit auto stop failed for trade {trade_id}, will retry on next check")
                    continue
        
        # Check if trade is in verification period
        if trade_id in verification_pending_trades:
            trigger_time, verification_end_time = verification_pending_trades[trade_id]
            
            # Check if verification period has ended
            if current_time >= verification_end_time:
                # Re-check conditions after verification period
                trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
                # Profit target triggers immediately when reached (NO momentum check)
                profit_target_triggered = current_position_value >= profit_target_threshold
                
                if trailing_stop_triggered or profit_target_triggered:
                    # Conditions still met after verification - trigger auto-stop
                    reason = "trailing stop" if trailing_stop_triggered else "profit target"
                    rev_trig = "reversal_trailing_stop" if trailing_stop_triggered else "reversal_profit_target"
                    log(f"[AUTO STOP MR] ✅ Verification period ended - triggering auto stop for trade {trade_id} ({reason})")
                    log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    if trigger_auto_stop_close(
                        trade,
                        trigger_reason=rev_trig,
                        trigger_detail=f"after_verification {reason}",
                    ):
                        auto_stop_triggered_trades.add(trade_id)
                        del verification_pending_trades[trade_id]
                    else:
                        log(f"[AUTO STOP MR] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                        del verification_pending_trades[trade_id]
                else:
                    # Conditions no longer met - cancel verification
                    log(f"[AUTO STOP MR] ❌ Verification period ended - conditions no longer met for trade {trade_id}")
                    log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    del verification_pending_trades[trade_id]
            else:
                # Still in verification period - just wait
                remaining_time = verification_end_time - current_time
                if not hasattr(check_auto_stop_conditions_momentum_reversal, 'last_verification_log') or current_time - check_auto_stop_conditions_momentum_reversal.last_verification_log > 10:
                    log(f"[AUTO STOP MR] ⏳ Trade {trade_id} in verification period - {remaining_time:.1f}s remaining")
                    check_auto_stop_conditions_momentum_reversal.last_verification_log = current_time
                continue
        
        # Check for new auto-stop conditions
        # Condition 1: Trailing stop - position value has dropped by trailing_stop_amount from high
        trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
        
        # Condition 2: Profit target - position value has reached or exceeded profit target threshold (buy_price + profit_target offset)
        # NO momentum check - triggers immediately when reached
        profit_target_triggered = current_position_value >= profit_target_threshold
        
        auto_stop_conditions_met = (
            trade.get('status') == 'active' and
            trade_id not in auto_stop_triggered_trades and
            (trailing_stop_triggered or profit_target_triggered)
        )
        
        if auto_stop_conditions_met:
            reason = "trailing stop" if trailing_stop_triggered else "profit target"
            rev_trig = "reversal_trailing_stop" if trailing_stop_triggered else "reversal_profit_target"
            log(f"[AUTO STOP MR] 🎯 Triggering auto stop for trade {trade_id} ({reason})")
            log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
            
            if trigger_auto_stop_close(
                trade,
                trigger_reason=rev_trig,
                trigger_detail=f"immediate {reason}",
            ):
                auto_stop_triggered_trades.add(trade_id)
            else:
                log(f"[AUTO STOP MR] ❌ Auto stop failed for trade {trade_id}, will retry on next check")

# Signal handlers for graceful shutdown
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    log(f"🛑 Received signal {signum}, shutting down gracefully...")
    drop_monitor_active_trades_table()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    create_monitor_active_trades_table()

    # Sync with existing trades on startup
    sync_on_demand()
    
    # Start the event-driven supervisor
    start_event_driven_supervisor() 