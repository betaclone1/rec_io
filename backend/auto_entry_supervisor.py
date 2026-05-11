#!/usr/bin/env python3
"""
Auto Entry Supervisor - MONITOR-AWARE VERSION

Monitors strike table data directly and triggers automated trades when criteria are met.
Uses atomic operations to prevent rapid-fire trades.
Supports multiple monitors with monitor-specific configuration.

PRIMARY GATE: Now uses auto_trade boolean from monitor_list table instead of 
auto_entry from auto_trade_settings. Each monitor controls its own auto entry 
supervisor via the auto_trade toggle switch.
"""

import logging
import os
import json
import copy
import time
import threading
import requests
import random
import sys
import signal
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple
from contextvars import ContextVar
from contextlib import contextmanager
from collections import defaultdict
from flask import Flask, request, jsonify
from flask_cors import CORS
_HIGH_PRECISION_STRIKE_SYMBOLS = frozenset({"SOL", "XRP"})


def _symbol_from_ticker_hint(ticker: Optional[str]) -> Optional[str]:
    if not ticker:
        return None
    t = str(ticker).upper()
    if "XRP" in t:
        return "XRP"
    if "SOL" in t:
        return "SOL"
    if "BTC" in t:
        return "BTC"
    if "ETH" in t:
        return "ETH"
    return None


def format_trade_strike_label(strike_value, symbol: Optional[str] = None, ticker: Optional[str] = None) -> Optional[str]:
    """
    Preserve strike precision for low-priced symbols when sending payloads to trade_manager.
    BTC/ETH stay as whole-dollar labels for backward compatibility.
    """
    if strike_value is None:
        return None
    sym = (symbol or _symbol_from_ticker_hint(ticker) or "").upper()
    try:
        d = Decimal(str(strike_value))
    except (InvalidOperation, TypeError, ValueError):
        s = str(strike_value).strip()
        if s.startswith("$"):
            return s
        return f"${s}" if s else None

    if sym in _HIGH_PRECISION_STRIKE_SYMBOLS:
        q = d.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        text = format(q, "f").rstrip("0").rstrip(".")
        return f"${text}"

    # Legacy display for high-priced symbols.
    return f"${int(q := d.quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"


def _kalshi_fp_volume_number(volume_fp: Any) -> Optional[float]:
    """Parse Kalshi volume_fp / open_interest_fp text for numeric thresholds."""
    if volume_fp is None:
        return None
    s = str(volume_fp).strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# Add the project root to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the universal centralized port system
from backend.core.port_config import (
    default_pool_user_number,
    get_monitor_port,
    get_port,
    register_monitor_ports,
    unified_auto_entry_supervisor_service_name,
)
from backend.core.config.database import get_postgresql_connection as get_db_connection
from backend.core.time_based_loss_prevention import (
    recompute_monitor_loss_prevention,
    startup_reconcile_simulated_trade_for_tenant,
)
from backend.core.symbol_wide_loss_prevention import (
    is_loss_prevention_sizing_state,
    normalize_loss_prevention_state_for_sizing,
    resolve_effective_loss_prevention_state,
)
from backend.core.strike_pipeline_health import (
    evaluate_pipeline_gate_conn,
    floor_strike_vs_spot_check,
)
from backend.symbol_price_watchdog import get_current_price_from_db
from backend.util.paths import get_host, get_data_dir, get_service_url, get_trade_history_dir, get_logs_dir
from backend.core.time_eastern import now_est as est_now, today_est


def _aes_preferences_notify(event_type: str, data: dict) -> None:
    """Redis-only preferences notify for unified refactor."""
    try:
        from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms

        if use_trading_redis_comms():
            if not publish_preferences_event(event_type, data, tenant_user_no=ctx_user()):
                log(
                    f"[AUTO_ENTRY] Redis publish_preferences_event failed "
                    f"(event_type={event_type})"
                )
    except Exception as exc:
        log(f"[AUTO_ENTRY] preferences notify error (event_type={event_type}): {exc}")


# Monitor identification - extract from script name or command line args
def get_monitor_identifier():
    """Extract monitor identifier from script name or command line arguments"""
    script_name = os.path.basename(sys.argv[0])
    
    # Check if script name contains monitor identifier (e.g., auto_entry_supervisor_0001_10001)
    if '_' in script_name and script_name.count('_') >= 3:
        parts = script_name.split('_')
        if len(parts) >= 4:
            user_number = parts[-2]  # 0001
            monitor_id = parts[-1]   # 10001
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
AES_UNIFIED_15M = MONITOR_IDENTIFIER == "unified_15m"
AES_UNIFIED_HOURLY = MONITOR_IDENTIFIER == "unified_hourly"
AES_UNIFIED_ALL = MONITOR_IDENTIFIER == "unified"
AES_UNIFIED_POOL = AES_UNIFIED_15M or AES_UNIFIED_HOURLY or AES_UNIFIED_ALL
if AES_UNIFIED_POOL:
    USER_NUMBER = default_pool_user_number()
    MONITOR_ID = "0"
else:
    USER_NUMBER = MONITOR_IDENTIFIER.split('_')[0]
    MONITOR_ID = MONITOR_IDENTIFIER.split('_')[1]

_aes_bind_u: ContextVar[Optional[str]] = ContextVar("_aes_bind_u", default=None)
_aes_bind_m: ContextVar[Optional[str]] = ContextVar("_aes_bind_m", default=None)

# Unified pool: one strike-table snapshot per (symbol, market) per monitoring tick (see docs/UNIFIED_AES_TICK_CONTRACT.md).
_aes_unified_tick_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar("_aes_unified_tick_context", default=None)

AES_UNIFIED_PROFILE = os.environ.get("AES_UNIFIED_PROFILE", "").strip().lower() in ("1", "true", "yes")
_unified_profile_state: Dict[str, Any] = {
    "master_cache_hits": 0,
    "master_fetch_sec": 0.0,
    "group_prefetch_sec": 0.0,
    "trigger_trade_sec": 0.0,
    "monitor_wall_sec": [],
}


def _reset_unified_profile_state() -> None:
    _unified_profile_state["master_cache_hits"] = 0
    _unified_profile_state["master_fetch_sec"] = 0.0
    _unified_profile_state["group_prefetch_sec"] = 0.0
    _unified_profile_state["trigger_trade_sec"] = 0.0
    _unified_profile_state["monitor_wall_sec"] = []


def ctx_user() -> str:
    u = _aes_bind_u.get()
    return u if u is not None else USER_NUMBER


def ctx_mid() -> str:
    m = _aes_bind_m.get()
    return m if m is not None else MONITOR_ID


def ctx_ident() -> str:
    return f"{ctx_user()}_{ctx_mid()}"


def _aes_tenant_slot(for_user: Optional[str] = None) -> str:
    """Four-digit slot for ``users.<table>_<slot>`` names (same convention as main.py /api/monitors)."""
    from backend.trading_mode import _norm_slot

    return _norm_slot(str(for_user)) if for_user is not None else _norm_slot(ctx_user())


def _aes_monitor_list_table(for_user: Optional[str] = None) -> str:
    return f"users.monitor_list_{_aes_tenant_slot(for_user)}"


def _aes_trades_table(for_user: Optional[str] = None) -> str:
    return f"users.trades_{_aes_tenant_slot(for_user)}"


def _aes_trades_simulated_table(for_user: Optional[str] = None) -> str:
    return f"users.trades_simulated_{_aes_tenant_slot(for_user)}"


def scoped_trade_manager_http_port() -> int:
    """HTTP port for ``trade_manager_<this slot>`` (same tenant as ctx_user); never abstract ``trade_manager``."""
    return get_port(f"trade_manager_{ctx_user()}")


def _strike_cooldown_key(strike_value, active_side: str) -> str:
    """Cooldown map key; unified pool scopes by monitor_id to avoid cross-monitor suppression."""
    base = f"{strike_value}-{active_side}"
    if AES_UNIFIED_POOL:
        return f"{ctx_mid()}-{base}"
    return base


def _strike_diff_for_traded_side(strike: Optional[dict], traded_side: str) -> Optional[float]:
    """yes_diff / no_diff for the contract side we are buying (matches Hourly HTC / Rising Devil semantics)."""
    if not strike:
        return None
    bucket = _aes_side_bucket_for_dedupe(traded_side)
    key = "yes_diff" if bucket == "yes" else "no_diff" if bucket == "no" else None
    if not key:
        return None
    raw = strike.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _auto_entry_differential_allowed(settings: dict, traded_side: str, strike: dict) -> Tuple[bool, str]:
    """
    When min_differential and/or max_differential are set in auto-trade settings, enforce the same
    rules as Hourly HTC / Rising Devil: min uses a -0.5 cushion; max blocks absurd edge (too good to be true).
    If neither bound is configured, returns (True, 'unbounded').
    """
    min_differential = settings.get("min_differential")
    max_differential = settings.get("max_differential")
    if min_differential is None and max_differential is None:
        return True, "unbounded"
    diff = _strike_diff_for_traded_side(strike, traded_side)
    if min_differential is not None:
        try:
            floor = float(min_differential) - 0.5
        except (TypeError, ValueError):
            floor = None
        if floor is not None and (diff is None or diff < floor):
            return False, f"diff_below_min diff={diff} floor={floor}"
    if max_differential is not None:
        try:
            cap = float(max_differential)
        except (TypeError, ValueError):
            cap = None
        if cap is not None and (diff is None or diff > cap):
            return False, f"diff_above_max diff={diff} cap={cap}"
    return True, "ok"


def _log_aes_trigger_feed_snapshot(strike_data: dict, strike_table_data: Optional[dict]) -> None:
    """Structured INFO line at auto-trigger time: ladder snapshot + live_symbol_status for incident forensics."""
    try:
        strategy = get_trade_strategy()
    except Exception:
        strategy = None
    try:
        sym, mkt = get_current_monitor_symbol_and_market()
    except Exception:
        sym, mkt = "BTC", "hourly"
    row = None
    conn = None
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT symbol, "timestamp", price, one_minute_avg, momentum_30s_avg
                    FROM live_data.live_symbol_status
                    WHERE symbol = %s
                    """,
                    (str(sym).upper(),),
                )
                row = cur.fetchone()
    except Exception:
        row = None
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    status_payload = None
    if row:
        try:
            status_payload = {
                "timestamp": row[1],
                "price": float(row[2]) if row[2] is not None else None,
                "one_minute_avg": float(row[3]) if len(row) > 3 and row[3] is not None else None,
                "momentum_30s_avg": float(row[4]) if len(row) > 4 and row[4] is not None else None,
            }
        except (TypeError, ValueError):
            status_payload = {"timestamp": row[1], "price": row[2], "one_minute_avg": row[3], "momentum_30s_avg": row[4] if len(row) > 4 else None}
    std = strike_table_data or {}
    payload = {
        "aes": "trigger_ctx",
        "user": ctx_user(),
        "monitor_id": ctx_mid(),
        "strategy": strategy,
        "symbol": sym,
        "market": mkt,
        "strike": {
            "label": strike_data.get("strike"),
            "side": strike_data.get("side"),
            "ticker": strike_data.get("ticker"),
            "buy_price": strike_data.get("buy_price"),
            "probability": strike_data.get("probability"),
            "diff": strike_data.get("diff"),
        },
        "ladder": {
            "current_price": std.get("current_price"),
            "ttc": std.get("ttc"),
            "event_ticker": std.get("event_ticker"),
        },
        "live_symbol_status": status_payload,
    }
    try:
        log(f"[AES_TRIGGER_CTX] {json.dumps(payload, default=str)}")
    except Exception:
        log(f"[AES_TRIGGER_CTX] {payload!r}")


def _rising_devil_ratelimit() -> Dict[str, float]:
    """Per-monitor throttles for Rising Devil INFO logs (unified pool safe)."""
    return _RISING_DEVIL_RATELIMIT.setdefault(
        ctx_ident(),
        {"ttc_out": 0.0, "scan": 0.0, "thr": 0.0, "no_range": 0.0, "no_ladder": 0.0},
    )


def _aes_side_bucket_for_dedupe(side) -> str:
    """Map Y/yes/YES/N/no/NO (and a few aliases) to ``yes`` or ``no`` for duplicate-trade checks."""
    if side is None:
        return ""
    s = str(side).strip().upper()
    if s in ("Y", "YES", "TRUE", "1"):
        return "yes"
    if s in ("N", "NO", "FALSE", "0"):
        return "no"
    return ""


@contextmanager
def aes_monitor_bind(user_num: str, monitor_id: str):
    if not AES_UNIFIED_POOL:
        yield
        return
    t1 = _aes_bind_u.set(user_num)
    t2 = _aes_bind_m.set(monitor_id)
    try:
        yield
    finally:
        _aes_bind_u.reset(t1)
        _aes_bind_m.reset(t2)


def _aes_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _AesFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_aes_logging():
    logr = logging.getLogger("auto_entry_supervisor")
    if logr.handlers:
        return logr
    h = _AesFlushHandler(sys.stdout)
    h.setFormatter(_aes_est_formatter())
    logr.addHandler(h)
    # Default to INFO in normal operation; DEBUG must be explicitly enabled.
    logr.setLevel(logging.INFO)
    return logr


_aes_logger = _configure_aes_logging()
HEARTBEAT_INTERVAL_SEC = 300


def _aes_heartbeat_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SEC)
        _aes_logger.info("heartbeat")


_aes_hb_thread = threading.Thread(target=_aes_heartbeat_loop, daemon=True)
_aes_hb_thread.start()


def log(message: str):
    """Stdout log at INFO (use log_debug for plumbing)."""
    _aes_logger.info("%s", message)


def log_debug(message: str):
    """Stdout log at DEBUG for plumbing/repetitive messages."""
    _aes_logger.debug("%s", message)


_aes_logger.info("Monitor-aware supervisor starting user=%s monitor=%s", ctx_user(), ctx_mid())

_LAST_MONITOR_STATE = {
    "contract": None,
    "weekly_cycle": None,
    "modifier": None,
    "max_pct_exposure": None,
    "applied_multiplier": None,
}

MARKET_TITLE_TODAY_PATTERN = re.compile(r"price today at\s+(\d{1,2})\s*(am|pm)", re.IGNORECASE)
# 15m market title: "BTC price today at 12:45pm" -> capture 12, 45, pm
MARKET_TITLE_TODAY_15M_PATTERN = re.compile(r"price today at\s+(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
MARKET_TITLE_DATE_PATTERN = re.compile(r"price on\s+([A-Za-z]{3})\s+(\d{1,2})\s+at\s+(\d{1,2})\s*(am|pm)", re.IGNORECASE)


def _format_time_label(hour_24: int) -> str:
    if hour_24 == 0:
        return "12am"
    if hour_24 == 12:
        return "12pm"
    if hour_24 > 12:
        return f"{hour_24 - 12}pm"
    return f"{hour_24}am"


def _hour_label_to_hour24(hour_value: int, period: str) -> int:
    period = period.lower()
    if period == "am":
        return 0 if hour_value == 12 else hour_value
    # pm
    return 12 if hour_value == 12 else hour_value + 12


def _next_15m_boundary_est() -> tuple[int, int]:
    """Return (hour_24, minute) for the next 15m boundary (expiry of current quarter). Minute in (0, 15, 30, 45)."""
    now = est_now()
    m, h = now.minute, now.hour
    next_m = ((m // 15) + 1) * 15
    if next_m >= 60:
        next_m = 0
        h = (h + 1) % 24
    return h, next_m


def _format_15m_contract_label(symbol: str, hour_24: int, minute: int) -> str:
    """Format contract label with minutes for 15m (e.g. 'BTC 2:15pm'). Matches CONTRACT_15M_FULL_PATTERN in trade_manager."""
    if hour_24 == 0:
        return f"{symbol.upper()} 12:{minute:02d}am"
    if hour_24 == 12:
        return f"{symbol.upper()} 12:{minute:02d}pm"
    if hour_24 > 12:
        return f"{symbol.upper()} {hour_24 - 12}:{minute:02d}pm"
    return f"{symbol.upper()} {hour_24}:{minute:02d}am"


def _kalshi_event_ticker_from_market_ticker(market_ticker: Optional[str]) -> Optional[str]:
    """Strip strike leg (…-T1234.99) so event suffix can be parsed for clock."""
    if not market_ticker or not str(market_ticker).strip():
        return None
    parts = str(market_ticker).strip().split("-")
    if len(parts) < 2:
        return str(market_ticker).strip()
    while len(parts) > 2:
        last = parts[-1]
        if last and last[0] == "T" and any(ch.isdigit() for ch in last[1:]):
            parts = parts[:-1]
        else:
            break
    return "-".join(parts) if parts else None


def _kalshi_clock_from_event_suffix(dt_part: str) -> Optional[Tuple[int, Optional[int]]]:
    """
    Parse hour (and optional minute) from Kalshi event date segments, e.g.
    26MAR2919 -> (19, None) hourly; 29MAR261445 -> (14, 45) for 15m-style HHMM.
    """
    if not dt_part or len(dt_part) < 7:
        return None
    if len(dt_part) >= 10 and dt_part[-4:].isdigit():
        hhmm = int(dt_part[-4:])
        h, m = hhmm // 100, hhmm % 100
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    if len(dt_part) >= 9 and dt_part[-2:].isdigit():
        h = int(dt_part[-2:])
        if 0 <= h <= 23:
            return h, None
    return None


def _resolve_event_time(symbol: str, market_title: Optional[str], event_ticker: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """Return (contract_label, hour_24) if we can parse a time from the market metadata.
    Contract label is simplified for DB: hourly e.g. 'BTC 2pm', 15m e.g. 'BTC 12:45pm'."""
    now_est = est_now()
    time_hour_24 = None
    contract_label = None

    title = market_title or ""

    # 15m: "price today at 12:45pm" -> "BTC 12:45pm"
    match_15m = MARKET_TITLE_TODAY_15M_PATTERN.search(title)
    if match_15m:
        hour_str, minute_str, period = match_15m.groups()
        try:
            hour_val = int(hour_str)
            minute_val = int(minute_str)
            time_hour_24 = _hour_label_to_hour24(hour_val, period)
            time_label = f"{hour_val}:{minute_str}{period.lower()}"
            contract_label = f"{symbol.upper()} {time_label}"
        except Exception:
            pass

    if contract_label is None:
        match = MARKET_TITLE_DATE_PATTERN.search(title)
        if match:
            _, _, hour_str, period = match.groups()
            try:
                hour_val = int(hour_str)
                time_hour_24 = _hour_label_to_hour24(hour_val, period)
            except Exception:
                time_hour_24 = None

    if contract_label is None and time_hour_24 is None:
        match_today = MARKET_TITLE_TODAY_PATTERN.search(title)
        if match_today:
            hour_str, period = match_today.groups()
            try:
                hour_val = int(hour_str)
                time_hour_24 = _hour_label_to_hour24(hour_val, period)
            except Exception:
                time_hour_24 = None

    if contract_label is None and time_hour_24 is None and event_ticker:
        ev = _kalshi_event_ticker_from_market_ticker(event_ticker) or str(event_ticker).strip()
        parts = ev.split("-")
        if len(parts) >= 2:
            dt_part = parts[-1]
            clock = _kalshi_clock_from_event_suffix(dt_part)
            if clock:
                h24, min_opt = clock
                time_hour_24 = h24
                if min_opt is not None:
                    contract_label = _format_15m_contract_label(symbol, h24, min_opt)

    if contract_label is None and time_hour_24 is not None:
        contract_label = f"{symbol.upper()} {_format_time_label(time_hour_24)}"
    if contract_label is None:
        return None, time_hour_24
    return contract_label, time_hour_24


def resolve_auto_entry_contract_name(
    symbol: str,
    strike_table_data: Dict[str, Any],
    strike_ticker: Optional[str],
) -> str:
    """Contract label for DB: metadata and/or Kalshi ticker; legacy segment label only if nothing else parses."""
    sd = strike_table_data or {}
    mt = sd.get("market_title")
    et = sd.get("event_ticker")
    label, _ = _resolve_event_time(symbol, mt, et)
    if label:
        return label
    if strike_ticker:
        label, _ = _resolve_event_time(symbol, None, strike_ticker)
        if label:
            return label
        ev_only = _kalshi_event_ticker_from_market_ticker(strike_ticker)
        if ev_only and ev_only != strike_ticker.strip():
            label, _ = _resolve_event_time(symbol, None, ev_only)
            if label:
                return label
    return f"{symbol.upper()} Market"


def _compute_weekly_cycle(hour_24: Optional[int], reference_dt: Optional[datetime] = None) -> Optional[int]:
    if hour_24 is None:
        return None
    ref = reference_dt or est_now()
    ref_est = ref.astimezone(ZoneInfo("America/New_York"))
    hour_idx = 24 if hour_24 == 0 else hour_24
    day_index = (ref_est.weekday() + 1) % 7
    weekly_cycle = day_index * 24 + hour_idx
    if weekly_cycle < 1 or weekly_cycle > 168:
        return None
    return weekly_cycle


def _fetch_performance_modifier(weekly_cycle: int) -> float:
    try:
        import psycopg2
        from psycopg2 import sql

        conn = get_db_connection()
        u = ctx_user()
        table_identifier = sql.SQL("{}.{}").format(
            sql.Identifier(f"users_{u}"),
            sql.Identifier(f"monitor_cycle_performance_{u}_{ctx_mid()}"),
        )
        with conn.cursor() as cursor:
            cursor.execute(
                    sql.SQL("SELECT performance_modifier FROM {} WHERE weekly_cycle = %s").format(table_identifier),
                (weekly_cycle,)
            )
            row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return round(float(row[0]), 2)
    except Exception as e:
        log(f"[AUTO ENTRY] ⚠️ Unable to load performance modifier for weekly cycle {weekly_cycle}: {e}")
    return 1.00


def _fetch_max_pct_exposure(weekly_cycle: int) -> float:
    try:
        import psycopg2
        from psycopg2 import sql

        conn = get_db_connection()
        u = ctx_user()
        table_identifier = sql.SQL("{}.{}").format(
            sql.Identifier(f"users_{u}"),
            sql.Identifier(f"monitor_cycle_performance_{u}_{ctx_mid()}"),
        )
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT max_pct_exposure FROM {} WHERE weekly_cycle = %s").format(table_identifier),
                (weekly_cycle,)
            )
            row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return round(float(row[0]), 2)
    except Exception as e:
        log(f"[AUTO ENTRY] ⚠️ Unable to load max_pct_exposure for weekly cycle {weekly_cycle}: {e}")
    return 0.25


def _aes_latest_bankroll_cents(cursor, slot: str) -> int:
    """Latest equity cents for the slot (same basis as monitor_manager bankroll allotment)."""
    from backend.trading_mode import account_balance_table_for_user

    tbl = account_balance_table_for_user(slot)
    cursor.execute(
        f"""
        SELECT bankroll_current, portfolio
        FROM {tbl}
        ORDER BY timestamp DESC NULLS LAST, id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row:
        return 0
    bc, pf = row[0], row[1]
    bankroll_value = int(bc) if bc is not None else 0
    portfolio_value = int(pf) if pf is not None else 0
    return bankroll_value if bankroll_value > 0 else portfolio_value


def _aes_expected_total_position(
    *,
    position_size: Optional[int],
    position_type: Optional[str],
    multiplier_value: float,
    bankroll_allotment_total: Optional[Any],
    bankroll_allotment_pct: Optional[Any],
    max_pct_cap: Optional[float],
    cursor,
    slot: str,
) -> int:
    """Mirror monitor_manager.update_monitor_position_variables total_position math (PBA apply path)."""
    mult = float(multiplier_value or 0)
    if mult == 0:
        return 1
    ptype = (position_type or "contracts").lower()
    if ptype == "percent":
        allotment_cents = int(bankroll_allotment_total or 0)
        if allotment_cents <= 0 and bankroll_allotment_pct is not None:
            try:
                pct = float(bankroll_allotment_pct)
            except (TypeError, ValueError):
                pct = 0.0
            if pct > 0:
                br = _aes_latest_bankroll_cents(cursor, slot)
                allotment_cents = int(round(pct * br))
        allotment_dollars = allotment_cents / 100.0
        base_pct = (int(position_size or 0)) / 100.0
        effective_pct = base_pct * mult
        cap = None
        if max_pct_cap is not None:
            try:
                cap = float(max_pct_cap)
            except (TypeError, ValueError):
                cap = None
        if cap is not None and cap > 0:
            effective_pct = min(effective_pct, cap)
        new_total = int(round(allotment_dollars * effective_pct))
        return max(1, new_total)
    return max(1, int(int(position_size or 0) * mult))


def _apply_performance_based_multiplier(multiplier_value: float, position_size: Optional[int], position_type: Optional[str]) -> None:
    """Apply performance-based multiplier via monitor_manager (same handler main_app proxies to).

    Do not call main_app here: ``/api/*`` requires a browser session (WebTenantMiddleware); AES has no token → 401.
    """
    if multiplier_value is None:
        return

    try:
        position_size_val = int(position_size) if position_size is not None else 1
        position_type_val = (position_type or "contracts").lower()
        slot = _aes_tenant_slot()
        mm_key = f"monitor_manager_{slot}"
        port = get_port(mm_key)
        url = f"http://localhost:{port}/api/update_monitor_position"
        monitor_id_value = int(ctx_mid())
        payload = {
            "monitor_id": monitor_id_value,
            "position_size": position_size_val,
            "position_type": position_type_val,
            "multiplier": float(multiplier_value),
            "user_number": slot,
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            log(f"[AUTO ENTRY] ⚠️ Failed to apply performance-based multiplier {multiplier_value} (status {response.status_code}): {response.text}")
        else:
            _LAST_MONITOR_STATE["applied_multiplier"] = float(multiplier_value)
    except Exception as exc:
        log(f"[AUTO ENTRY] ⚠️ Error applying performance-based multiplier {multiplier_value}: {exc}")


def update_monitor_current_state(strike_table_data: Dict[str, Any]) -> None:
    """Update monitor_list with the current contract, weekly cycle, and performance modifier."""
    symbol = (strike_table_data or {}).get("symbol") or MONITOR_SYMBOL or "BTC"
    market_title = (strike_table_data or {}).get("market_title")
    event_ticker = (strike_table_data or {}).get("event_ticker")

    contract_label, hour_24 = _resolve_event_time(symbol, market_title, event_ticker)
    if not contract_label or hour_24 is None:
        return

    weekly_cycle = _compute_weekly_cycle(hour_24)
    if weekly_cycle is None:
        return

    performance_modifier = _fetch_performance_modifier(weekly_cycle)
    max_pct_exposure = _fetch_max_pct_exposure(weekly_cycle)
    position_size = None
    position_type = None
    performance_based_allocation = False
    existing_multiplier = None
    bankroll_allotment_total = None
    bankroll_allotment_pct = None
    total_position_row = None

    try:
        import psycopg2

        slot_norm = _aes_tenant_slot()
        ml_table = _aes_monitor_list_table()
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT performance_based_allocation, position_size, position_type, multiplier,
                       total_position, bankroll_allotment_total, bankroll_allotment_pct
                FROM {ml_table}
                WHERE id = %s
                """,
                (ctx_mid(),)
            )
            settings_row = cursor.fetchone()
            if settings_row:
                performance_based_allocation = bool(settings_row[0])
                position_size = settings_row[1]
                position_type = settings_row[2]
                existing_multiplier = settings_row[3]
                total_position_row = settings_row[4]
                bankroll_allotment_total = settings_row[5]
                bankroll_allotment_pct = settings_row[6]
                if existing_multiplier is not None:
                    try:
                        _LAST_MONITOR_STATE["applied_multiplier"] = float(existing_multiplier)
                    except (TypeError, ValueError):
                        pass

            cursor.execute(
                f"""
                UPDATE {ml_table}
                SET current_contract = %s,
                    current_weekly_cycle = %s,
                    current_performance_modifier = %s,
                    current_max_pct_exposure = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (contract_label, weekly_cycle, performance_modifier,
                 max_pct_exposure, ctx_mid())
            )
        conn.commit()
        conn.close()

        _LAST_MONITOR_STATE["contract"] = contract_label
        _LAST_MONITOR_STATE["weekly_cycle"] = weekly_cycle
        _LAST_MONITOR_STATE["modifier"] = performance_modifier
        _LAST_MONITOR_STATE["max_pct_exposure"] = max_pct_exposure

        if performance_based_allocation:
            new_multiplier = round(float(performance_modifier), 2)
            current_applied = _LAST_MONITOR_STATE.get("applied_multiplier")
            existing_multiplier_value = None
            try:
                if existing_multiplier is not None:
                    existing_multiplier_value = float(existing_multiplier)
            except (TypeError, ValueError):
                existing_multiplier_value = None

            needs_update = False
            if existing_multiplier_value is None:
                needs_update = True
            elif abs(existing_multiplier_value - new_multiplier) > 0.0009:
                needs_update = True
            elif current_applied is None or abs(current_applied - new_multiplier) > 0.0009:
                needs_update = True

            # multiplier can already match performance_modifier while total_position is stale
            # (allotment/bankroll/position_size changed, or a failed prior apply). UI reads
            # current_performance_modifier; trades use total_position — keep them aligned.
            if not needs_update and settings_row:
                sync_conn = None
                try:
                    sync_conn = get_db_connection()
                    if sync_conn:
                        with sync_conn.cursor() as sync_cur:
                            expected = _aes_expected_total_position(
                                position_size=position_size,
                                position_type=position_type,
                                multiplier_value=new_multiplier,
                                bankroll_allotment_total=bankroll_allotment_total,
                                bankroll_allotment_pct=bankroll_allotment_pct,
                                max_pct_cap=max_pct_exposure,
                                cursor=sync_cur,
                                slot=slot_norm,
                            )
                        cur_tp = int(total_position_row or 0)
                        if cur_tp != int(expected):
                            needs_update = True
                            log(
                                f"[AUTO ENTRY] PBA resync: total_position {cur_tp} != expected {expected} "
                                f"(mult={new_multiplier}); forcing monitor_manager apply"
                            )
                except Exception as sync_exc:
                    log(f"[AUTO ENTRY] ⚠️ PBA total_position stale check failed: {sync_exc}")
                finally:
                    if sync_conn:
                        try:
                            sync_conn.close()
                        except Exception:
                            pass

            if needs_update:
                _apply_performance_based_multiplier(new_multiplier, position_size, position_type)
            else:
                _LAST_MONITOR_STATE["applied_multiplier"] = new_multiplier
    except Exception as e:
        log(f"[AUTO ENTRY] ⚠️ Unable to update monitor current state: {e}")

# Get symbol for this monitor
def get_monitor_symbol():
    """Get the symbol for the current monitor from database"""
    try:
        import psycopg2

        if AES_UNIFIED_15M:
            from backend.core.unified_15m_monitors import list_active_15m_monitor_rows

            rows = list_active_15m_monitor_rows()
            if not rows:
                log("[AUTO_ENTRY_SUPERVISOR] ❌ unified_15m: no active 15m monitors in DB; exiting")
                os._exit(0)
            uid0 = rows[0]["user_number"]
            mid0 = rows[0]["monitor_id"]
        elif AES_UNIFIED_HOURLY:
            from backend.core.unified_hourly_monitors import list_active_hourly_monitor_rows

            rows = list_active_hourly_monitor_rows()
            if not rows:
                log("[AUTO_ENTRY_SUPERVISOR] ❌ unified_hourly: no active hourly monitors in DB; exiting")
                os._exit(0)
            uid0 = rows[0]["user_number"]
            mid0 = rows[0]["monitor_id"]
        elif AES_UNIFIED_ALL:
            from backend.core.unified_all_monitors import list_active_unified_monitor_rows

            rows = list_active_unified_monitor_rows()
            if not rows:
                log("[AUTO_ENTRY_SUPERVISOR] ❌ unified: no active 15m or hourly-pool monitors in DB; exiting")
                os._exit(0)
            uid0 = rows[0]["user_number"]
            mid0 = rows[0]["monitor_id"]
        else:
            uid0, mid0 = ctx_user(), ctx_mid()

        conn = get_db_connection()
        if not conn:
            log(f"[AUTO_ENTRY_SUPERVISOR] ❌ No database connection available when resolving symbol for monitor {MONITOR_IDENTIFIER}")
            os._exit(0)

        cursor = conn.cursor()
        _ml = _aes_monitor_list_table(str(uid0))
        cursor.execute(f"""
            SELECT symbol, COALESCE(market, 'hourly') FROM {_ml}
            WHERE id = %s
        """, (mid0,))
        result = cursor.fetchone()
        conn.close()

        if not result:
            log(f"[AUTO_ENTRY_SUPERVISOR] ❌ Monitor {uid0}_{mid0} not found in monitor_list_{uid0}; shutting down supervisor to avoid ghost activity")
            os._exit(0)

        symbol_value, market_value = result
        if not symbol_value:
            log(f"[AUTO_ENTRY_SUPERVISOR] ❌ Monitor {uid0}_{mid0} has no symbol configured; shutting down supervisor")
            os._exit(0)

        return symbol_value.upper(), (market_value or "hourly").strip().lower()  # (symbol, market)
    except Exception as e:
        log(f"[AUTO_ENTRY_SUPERVISOR] ❌ Error getting monitor symbol: {e}, defaulting to BTC")
        return "BTC", "hourly"

def get_strike_table_name(symbol: str, market: str) -> str:
    """Strike table name from symbol and market (hourly or 15m)."""
    from backend.core.strike_ladder_fetch import strike_table_name_for_market

    return strike_table_name_for_market(symbol, market)


def _strike_data_exchange_key() -> str:
    from backend.core.exchange_ids import DEFAULT_EXCHANGE

    return DEFAULT_EXCHANGE

# Get the symbol and market for this monitor (will be updated dynamically)
_monitor_symbol_market = get_monitor_symbol()
MONITOR_SYMBOL = _monitor_symbol_market[0] if isinstance(_monitor_symbol_market, tuple) else _monitor_symbol_market
MONITOR_MARKET = _monitor_symbol_market[1] if isinstance(_monitor_symbol_market, tuple) else 'hourly'
_aes_logger.info("Initial symbol=%s market=%s", MONITOR_SYMBOL, MONITOR_MARKET)

def get_current_monitor_symbol_and_market():
    """Get (symbol, market) for this monitor from database. market is 'hourly' or '15m'."""
    global MONITOR_SYMBOL, MONITOR_MARKET
    try:
        import psycopg2
        if AES_UNIFIED_POOL and _aes_bind_m.get() is None:
            return MONITOR_SYMBOL, MONITOR_MARKET
        conn = get_db_connection()
        if not conn:
            return "BTC", "hourly"
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT symbol, COALESCE(market, 'hourly') FROM {_aes_monitor_list_table()}
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

# Get port from monitor-specific system
if AES_UNIFIED_15M:
    AUTO_ENTRY_SUPERVISOR_PORT = get_port("auto_entry_supervisor_15m")
    _aes_logger.info("Using unified 15m AES port: %s", AUTO_ENTRY_SUPERVISOR_PORT)
elif AES_UNIFIED_HOURLY:
    AUTO_ENTRY_SUPERVISOR_PORT = get_port("auto_entry_supervisor_hourly")
    _aes_logger.info("Using unified hourly AES port: %s", AUTO_ENTRY_SUPERVISOR_PORT)
elif AES_UNIFIED_ALL:
    AUTO_ENTRY_SUPERVISOR_PORT = get_port(unified_auto_entry_supervisor_service_name())
    _aes_logger.info("Using pool AES port (15m+hourly): %s", AUTO_ENTRY_SUPERVISOR_PORT)
else:
    register_monitor_ports(MONITOR_IDENTIFIER)
    AUTO_ENTRY_SUPERVISOR_PORT = get_monitor_port("auto_entry_supervisor", MONITOR_IDENTIFIER)
    _aes_logger.info("Using monitor-specific port: %s", AUTO_ENTRY_SUPERVISOR_PORT)

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
# Mute Flask/Werkzeug dev-server banner to avoid flooding .err.log
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# Global variable to track monitoring thread
monitoring_thread = None
monitoring_thread_lock = threading.Lock()

# SIMPLIFIED: Track last trade time per strike (atomic)
last_trade_times = {}  # strike_key -> timestamp
last_simulated_trade_times = {}  # simulated 15m path only
_simulated_15m_lock = threading.Lock()  # prevent overlapping runs (duplicate inserts)

# Cooldown period (seconds)
TRADE_COOLDOWN = 1

# Global state for auto entry indicator (for frontend display)
AES_INDICATOR_DEFAULTS = {
    "enabled": False,
    "ttc_within_window": False,
    "scanning_active": False,
    "service_healthy": False,
    "spike_alert_active": False,
    "spike_alert_start_time": None,
    "spike_alert_momentum_value": None,
    "spike_alert_recovery_countdown": None,
    "current_momentum": None,
    "current_ttc": 0,
    "min_time": 0,
    "max_time": 3600,
    "last_updated": None,
}

auto_entry_indicator_state = copy.deepcopy(AES_INDICATOR_DEFAULTS)
_aes_indicator_states: Dict[str, dict] = {}


def _aes_indicator_bucket() -> dict:
    """Per-monitor indicator dict in unified pool; singleton for per-monitor AES."""
    if not AES_UNIFIED_POOL:
        return auto_entry_indicator_state
    key = ctx_ident()
    if key not in _aes_indicator_states:
        _aes_indicator_states[key] = copy.deepcopy(AES_INDICATOR_DEFAULTS)
    return _aes_indicator_states[key]

# Track previous settings for change detection
previous_settings = None
# Per-monitor: unified pool must not share one global (false STATUS CHANGE spam across monitors).
_previous_auto_trade_status_by_monitor: Dict[str, Optional[str]] = {}
# Per ctx_ident(): throttle INFO for ACTIVE/INACTIVE flapping at TTC window edges (unified pool × tick rate).
_status_change_info_log_ts: Dict[str, float] = {}
STATUS_CHANGE_INFO_MIN_INTERVAL_SEC = 120.0

# Track previous state to detect changes (per-monitor key in unified pool)
previous_indicator_state = None
_previous_indicator_by_monitor: Dict[str, Any] = {}

# Per-monitor cycle-entry state for unified pool.
# Without monitor scoping, one monitor's contract churn can reset another monitor's
# "already entered this cycle" flag and allow duplicate entries.
_momentum_breakout_cycle_state_by_monitor: Dict[str, Dict[str, Any]] = {}
_momentum_contain_cycle_state_by_monitor: Dict[str, Dict[str, Any]] = {}

# Rising Devil: rate-limited INFO per monitor (ctx_ident).
_RISING_DEVIL_RATELIMIT: Dict[str, Dict[str, float]] = {}

# State tracking for logging reduction



# Database-based state management functions (PRIMARY SYSTEM)
def save_auto_entry_state_to_db(state):
    """Save auto entry state to production database"""
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # LEGACY REMOVED: auto_entry_status updates - now using auto_trade_status only
            # Update only cooldown and timestamp fields
            
            conn.commit()
        conn.close()
    except Exception as e:
        log(f"[AUTO ENTRY STATE DB] Error saving state to production database: {e}")

def load_auto_entry_state_from_db():
    """Load auto entry state from production database (timestamp-based cooldown)"""
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Get monitor's strategy and cooldown state
            cursor.execute(f"""
                SELECT strategy, cooldown_start_time, cooldown_timer, updated_at
                FROM {_aes_monitor_list_table()} WHERE id = %s
            """, (ctx_mid(),))
            monitor_result = cursor.fetchone()
            
            if monitor_result:
                strategy_name, cooldown_start_time, cooldown_timer, updated_at = monitor_result
                
                # Get cooldown settings and time parameters from monitor
                cursor.execute(f"""
                    SELECT spike_alert_cooldown_minutes, min_time, max_time
                    FROM {_aes_monitor_list_table()} WHERE id = %s
                """, (ctx_mid(),))
                strategy_result = cursor.fetchone()
                
                if strategy_result:
                    cooldown_minutes, min_time, max_time = strategy_result
                
                # Calculate remaining time based on timestamp (can go negative to show elapsed time)
                spike_alert_active = False
                remaining_minutes = None
                
                if cooldown_start_time:
                    now = est_now()
                    time_elapsed = (now - cooldown_start_time).total_seconds()
                    total_cooldown_seconds = cooldown_minutes * 60
                    remaining_seconds = total_cooldown_seconds - time_elapsed  # Can be negative
                    
                    # Spike alert is only active when timer is positive (within cooldown period)
                    if remaining_seconds > 0:
                        spike_alert_active = True
                        remaining_minutes = remaining_seconds / 60
                    else:
                        # Timer has expired or gone negative - spike alert inactive, but keep tracking elapsed time
                        remaining_minutes = remaining_seconds / 60  # Negative value shows elapsed time
                    
                    # Always update cooldown_timer (even when negative) to show time since last spike
                    cursor.execute(
                        f"UPDATE {_aes_monitor_list_table()} SET cooldown_timer = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (int(remaining_seconds), ctx_mid())
                    )
                    
                    conn.commit()
                    
                    full_monitor_id = f"mon_{ctx_user()}_{ctx_mid()}"
                    _aes_preferences_notify(
                        "cooldown_timer_change",
                        {"monitor_id": full_monitor_id, "cooldown_timer": int(remaining_seconds)},
                    )
                
                state = {
                    "user_id": f"user_{ctx_user()}",
                    "monitor_id": "default",
                    "enabled": False,
                    "scanning_active": False,
                    "spike_alert_active": spike_alert_active,
                    "spike_alert_start_time": cooldown_start_time.isoformat() if cooldown_start_time else None,  # Always track, even when inactive
                    "spike_alert_momentum_value": None,  # Not stored in DB
                    "spike_alert_recovery_countdown": remaining_minutes,
                    "current_momentum": None,
                    "current_ttc": 0,
                    "min_time": min_time,
                    "max_time": max_time,
                    "last_updated": updated_at.isoformat() if updated_at else None
                }

                return state
        conn.close()
    except Exception as e:
        log(f"[AUTO ENTRY STATE DB] Error loading state from production database: {e}")
    
    return None


# LEGACY REMOVED: previous_auto_entry_status - now using auto_trade_status only

# SPIKE ALERT constants - NO DEFAULTS, must get from settings
# These will be loaded from auto_entry_settings.json

def log_heartbeat():
    """Detailed status at DEBUG; simple heartbeat at INFO is handled by _aes_heartbeat_loop."""
    try:
        auto_trade_enabled = is_auto_trade_enabled()
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        momentum_str = f"{current_momentum:.2f}" if current_momentum is not None else "N/A"
        cooldown_timer = 0
        try:
            import psycopg2
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT cooldown_timer FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
                result = cursor.fetchone()
                cooldown_timer = result[0] if result and result[0] is not None else 0
            conn.close()
        except Exception:
            cooldown_timer = 0
        cooldown_str = f"{cooldown_timer}s" if cooldown_timer is not None else "None"
        log_debug(f"HEARTBEAT | Auto Trade: {auto_trade_enabled} | Symbol: {current_symbol} | Momentum: {momentum_str} | Cooldown: {cooldown_str}")
    except Exception as e:
        log_debug(f"HEARTBEAT | Error getting status: {e}")

# Legacy auto_entry_state.json functionality removed - now using PostgreSQL for all state management

def get_current_momentum(symbol="BTC"):
    """Get current momentum_5s_avg from live price log for specified symbol"""
    try:
        import psycopg2
        
        # PostgreSQL connection parameters
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get momentum_5s_avg from live price log (symbol's live data stream)
        cursor.execute(f"""
            SELECT momentum_5s_avg FROM live_data.live_price_log_1s_{symbol.lower()} 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_5s_avg = float(result[0])
            return momentum_5s_avg
        else:
            return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum for {symbol}: {e}")
        return None

def get_momentum_30s_avg(symbol="BTC"):
    """Get current momentum_30s_avg from live price log for specified symbol"""
    try:
        import psycopg2
        
        # PostgreSQL connection parameters
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get momentum_30s_avg from live price log (symbol's live data stream)
        cursor.execute(f"""
            SELECT momentum_30s_avg FROM live_data.live_price_log_1s_{symbol.lower()} 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_30s_avg = float(result[0])
            return momentum_30s_avg
        else:
            return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum_30s_avg for {symbol}: {e}")
        return None

def get_momentum_percentile(symbol="BTC"):
    """Get current momentum_percentile from live price log for specified symbol"""
    try:
        import psycopg2
        
        # PostgreSQL connection parameters
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get momentum_percentile from live price log (symbol's live data stream)
        cursor.execute(f"""
            SELECT momentum_percentile FROM live_data.live_price_log_1s_{symbol.lower()} 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_percentile = float(result[0])
            return momentum_percentile
        else:
            return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum_percentile for {symbol}: {e}")
        return None

def check_spike_alert_conditions():
    """Check if spike alert conditions are met and update state accordingly"""
    try:
        # Get current momentum for this monitor's symbol
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        if current_momentum is None:
            return
        
        # Update current momentum in state
        _aes_indicator_bucket()["current_momentum"] = current_momentum
        
        # Load current state from database (PHASE 2: Replaced JSON with DB)
        state = load_auto_entry_state_from_db()
        if state is None:
            # Initialize state if file not found (should ideally not happen if load_auto_entry_state handles defaults)
            state = {
                "user_id": f"user_{ctx_user()}",
                "monitor_id": "default",
                "enabled": False,
                "scanning_active": False,
                "spike_alert_active": False,
                "spike_alert_start_time": None,
                "spike_alert_momentum_value": None,
                "spike_alert_recovery_countdown": None,
                "current_momentum": current_momentum,
                "current_ttc": 0,
                "min_time": 0,
                "max_time": 3600,
                "last_updated": None
            }
        
        # Get spike alert settings from auto entry settings - NO DEFAULTS
        settings = get_auto_entry_settings()
        
        # Check if all required spike alert settings exist
        required_settings = [
            "spike_alert_enabled",
            "spike_alert_momentum_threshold", 
            "spike_alert_cooldown_threshold",
            "spike_alert_cooldown_minutes"
        ]
        
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[SPIKE ALERT] ❌ Missing required settings: {missing_settings}")
            log(f"[SPIKE ALERT] Cannot proceed without complete settings configuration")
            return
        
        spike_alert_enabled = settings["spike_alert_enabled"]
        spike_threshold = settings["spike_alert_momentum_threshold"]  # Already in percentile (0-100)
        cooldown_threshold = settings["spike_alert_cooldown_threshold"]  # Already in percentile (0-100)
        cooldown_minutes = settings["spike_alert_cooldown_minutes"]
        
        # Skip spike alert if disabled
        if not spike_alert_enabled:
            # Reset any active spike alert
            if state["spike_alert_active"]:
                state["spike_alert_active"] = False
                state["spike_alert_start_time"] = None
                state["spike_alert_momentum_value"] = None
                state["spike_alert_recovery_countdown"] = None
                log_debug(f"[SPIKE ALERT] Disabled - clearing any active spike alert")
            
            # Update global state for frontend
            _aes_indicator_bucket().update({
                "spike_alert_active": False,
                "spike_alert_start_time": None,
                "spike_alert_momentum_value": None,
                "spike_alert_recovery_countdown": None,
                "current_momentum": state["current_momentum"]
            })
            
            # Save updated state to database (PHASE 2: Replaced JSON with DB)
            save_auto_entry_state_to_db(state)
            return
        
        # Check for spike detection using settings
        spike_detected = (current_momentum >= spike_threshold or 
                         current_momentum <= -spike_threshold)
        
        # Check for recovery conditions using settings
        recovery_conditions_met = (current_momentum < cooldown_threshold and 
                                  current_momentum > -cooldown_threshold)
        
        now = est_now()
        
        # CRITICAL: Use the spike_alert_active from loaded state (which is based on cooldown timer)
        # This ensures Reverse HTC only activates when cooldown timer is actually positive
        spike_alert_active_from_db = state["spike_alert_active"]
        
        if spike_detected and not spike_alert_active_from_db:
            # SPIKE DETECTED - Enter spike alert mode (only if cooldown timer is not already active)
            state["spike_alert_active"] = True
            state["spike_alert_start_time"] = now.isoformat()
            state["spike_alert_momentum_value"] = current_momentum
            state["spike_alert_recovery_countdown"] = cooldown_minutes
            
            # Start cooldown period in database (timestamp-based)
            start_cooldown_period_in_db()
            _aes_logger.info("spike started monitor_id=%s", ctx_mid())
            log(f"[SPIKE ALERT] 🚨 SPIKE DETECTED! Momentum: {current_momentum:.2f} (threshold: ±{spike_threshold})")
            log(f"[SPIKE ALERT] Cooldown started ({cooldown_minutes} min); Hourly HTC uses raised min_probability (prob_adj), not a hard pause")
        
        elif spike_alert_active_from_db:
            if recovery_conditions_met:
                # Check if recovery duration has passed
                if state["spike_alert_start_time"]:
                    spike_start = datetime.fromisoformat(state["spike_alert_start_time"])
                    time_in_recovery = (now - spike_start).total_seconds() / 60
                    
                    if time_in_recovery >= cooldown_minutes:
                        # RECOVERY COMPLETE - Exit spike alert mode (but keep cooldown_start_time for tracking)
                        state["spike_alert_active"] = False
                        state["spike_alert_momentum_value"] = None
                        state["spike_alert_recovery_countdown"] = None
                        # Note: spike_alert_start_time remains set in DB (cooldown_start_time) for tracking elapsed time
                        _aes_logger.info("spike ended monitor_id=%s", ctx_mid())
                        log(f"[SPIKE ALERT] ✅ RECOVERY COMPLETE! Auto entry RESUMED")
                        log(f"[SPIKE ALERT] Recovery time: {time_in_recovery:.1f} minutes")
                    else:
                        # Still in recovery period - calculate remaining time
                        remaining_minutes = cooldown_minutes - time_in_recovery
                        state["spike_alert_recovery_countdown"] = remaining_minutes
                        
                        log_debug(f"[SPIKE ALERT] Recovery in progress: {remaining_minutes:.1f} minutes remaining")
                else:
                    # Reset recovery countdown if start time is missing
                    state["spike_alert_recovery_countdown"] = cooldown_minutes
            else:
                # Still in spike conditions - reset recovery timer
                state["spike_alert_start_time"] = now.isoformat()
                state["spike_alert_recovery_countdown"] = cooldown_minutes
                
                # Reset cooldown period in database
                start_cooldown_period_in_db()
                
                log_debug(f"[SPIKE ALERT] Still in spike conditions: {current_momentum:.2f} - resetting timer to {cooldown_minutes} minutes")
        
        # Update current momentum in loaded state
        state["current_momentum"] = current_momentum
        
        # Update global state for frontend
        _aes_indicator_bucket().update({
            "spike_alert_active": state["spike_alert_active"],
            "spike_alert_start_time": state["spike_alert_start_time"],
            "spike_alert_momentum_value": state["spike_alert_momentum_value"],
            "spike_alert_recovery_countdown": state["spike_alert_recovery_countdown"],
            "current_momentum": state["current_momentum"]
        })
        
        # Save updated state to database (PHASE 2: Replaced JSON with DB)
        save_auto_entry_state_to_db(state)
        
    except Exception as e:
        log(f"[SPIKE ALERT] Error checking spike conditions: {e}")

def start_cooldown_period_in_db():
    """Start a new cooldown period in the database (uses existing spike_alert_cooldown_minutes setting)"""
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Update the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                f"UPDATE {_aes_monitor_list_table()} SET cooldown_start_time = NOW(), updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (ctx_mid(),)
            )
            
            conn.commit()
        conn.close()
        log_debug(f"Started cooldown period in production database")
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error starting cooldown period: {e}")

def reset_cooldown_period_in_db():
    """Reset/clear the cooldown period in the database"""
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Reset the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                f"UPDATE {_aes_monitor_list_table()} SET cooldown_start_time = NULL, cooldown_timer = 0, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (ctx_mid(),)
            )
            
            conn.commit()
        conn.close()
        log_debug(f"Reset cooldown period in production database")
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error resetting cooldown period: {e}")

# Legacy function for backward compatibility (will be removed)
def update_cooldown_timer_in_db(seconds):
    """Update cooldown_timer in the database (LEGACY - will be removed)"""
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Update the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                f"UPDATE {_aes_monitor_list_table()} SET cooldown_timer = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (seconds, ctx_mid())
            )
            
            conn.commit()
        conn.close()
        log_debug(f"Updated cooldown_timer to {seconds} seconds in production database (LEGACY)")
        
        full_monitor_id = f"mon_{ctx_user()}_{ctx_mid()}"
        _aes_preferences_notify(
            "cooldown_timer_change",
            {"monitor_id": full_monitor_id, "cooldown_timer": seconds},
        )
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error updating cooldown_timer: {e}")

def update_auto_entry_status_in_db(status):
    """Update auto trade status in the monitor_list table"""
    try:
        ident = ctx_ident()
        prev = _previous_auto_trade_status_by_monitor.get(ident)
        if prev != status:
            _previous_auto_trade_status_by_monitor[ident] = status
            msg = f"[AUTO ENTRY] 🔄 STATUS CHANGE | Monitor {ctx_mid()} | {prev} → {status}"
            import time as _t

            now = _t.time()
            last_info = _status_change_info_log_ts.get(ident, 0.0)
            # DISABLED is safety-relevant; always surface at INFO.
            force_info = status == "DISABLED" or prev == "DISABLED"
            if force_info or (now - last_info >= STATUS_CHANGE_INFO_MIN_INTERVAL_SEC):
                log(msg)
                _status_change_info_log_ts[ident] = now
            else:
                log_debug(msg)

        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Update the monitor's auto_trade_status field (this is what the frontend reads)
            cursor.execute(
                f"UPDATE {_aes_monitor_list_table()} SET auto_trade_status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (status, ctx_mid())
            )
            conn.commit()
        conn.close()
        # Only log actual status changes, not every update
        pass
        
        full_monitor_id = f"mon_{ctx_user()}_{ctx_mid()}"
        _aes_preferences_notify(
            "auto_trade_status_change",
            {"monitor_id": full_monitor_id, "auto_trade_status": status},
        )
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error updating auto_trade_status in database: {e}")

def determine_auto_entry_status():
    """Determine the current auto entry status based on conditions - routes to strategy-specific logic"""
    try:
        strategy = get_trade_strategy()
        
        if strategy == "Momentum Scalp":
            return determine_auto_entry_status_momentum_scalp()
        elif strategy == "Momentum Reversal":
            return determine_auto_entry_status_momentum_reversal()
        elif strategy == "Reverse HTC":
            return determine_auto_entry_status_reverse_htc()
        elif strategy == "Momentum Breakout":
            return determine_auto_entry_status_momentum_breakout()
        elif strategy == "Momentum Contain":
            return determine_auto_entry_status_momentum_contain()
        else:
            # Default to Hourly HTC (including fallback)
            return determine_auto_entry_status_hourly_htc()
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_hourly_htc():
    """Determine the current auto entry status for Hourly HTC strategy"""
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (no longer pauses - uses prob_adj instead)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        # Note: spike_alert_active no longer causes PAUSED status - monitor continues with adjusted probability
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time", "min_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if ttc_within_window:
            return "ACTIVE"
        else:
            return "INACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY HTC] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_scalp():
    """Determine the current auto entry status for Momentum Scalp strategy"""
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time", "min_probability", "momentum_scalp_entry_threshold"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # LAYER 1: Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if not ttc_within_window:
            return "INACTIVE"
        
        # LAYER 2: Check if momentum spike is detected
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        if momentum_threshold is None:
            return "DISABLED"  # Missing momentum threshold
        
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            return "INACTIVE"  # Cannot determine momentum
        
        # Check if momentum is above threshold (positive) or below -threshold (negative)
        momentum_spike_detected = (current_momentum >= momentum_threshold) or (current_momentum <= -momentum_threshold)
        
        if not momentum_spike_detected:
            return "INACTIVE"
        
        # Both layers pass - monitor is ACTIVE
        return "ACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY MS] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_reversal():
    """Determine the current auto entry status for Momentum Reversal strategy"""
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time", "min_probability", "momentum_scalp_entry_threshold"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # LAYER 1: Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if not ttc_within_window:
            return "INACTIVE"
        
        # LAYER 2: Check if momentum spike is detected
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        if momentum_threshold is None:
            return "DISABLED"  # Missing momentum threshold
        
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            return "INACTIVE"  # Cannot determine momentum
        
        # Check if momentum is above threshold (positive) or below -threshold (negative)
        momentum_spike_detected = (current_momentum >= momentum_threshold) or (current_momentum <= -momentum_threshold)
        
        if not momentum_spike_detected:
            return "INACTIVE"
        
        # Both layers pass - monitor is ACTIVE
        return "ACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY MR] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_reverse_htc():
    """Determine the current auto entry status for Reverse HTC strategy
    
    Reverse HTC activates when momentum spike is detected (opposite of Hourly HTC).
    It trades during the cooldown period when Hourly HTC would be paused.
    """
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (REQUIRED for Reverse HTC to activate)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        if not spike_alert_active:
            return "INACTIVE"  # Reverse HTC only activates during momentum spikes
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time", "min_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if ttc_within_window:
            return "ACTIVE"
        else:
            return "INACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY REVERSE HTC] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_breakout():
    """Determine the current auto entry status for Momentum Breakout strategy
    
    Momentum Breakout activates when momentum spike is detected (same as Reverse HTC).
    It uses the same activation logic but with simplified entry criteria.
    """
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (REQUIRED for Momentum Breakout to activate)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        if not spike_alert_active:
            return "INACTIVE"  # Momentum Breakout only activates during momentum spikes
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if ttc_within_window:
            return "ACTIVE"
        else:
            return "INACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_contain():
    """Determine the current auto entry status for Momentum Contain strategy
    
    Momentum Contain activates when momentum spike is detected (same as Momentum Breakout).
    It uses the same activation logic but with flipped trade sides (contrarian strategy).
    """
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (REQUIRED for Momentum Contain to activate)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        if not spike_alert_active:
            return "INACTIVE"  # Momentum Contain only activates during momentum spikes
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if not ttc_within_window:
            return "INACTIVE"
        
        # Check if cooldown timer is within activation window
        min_cooldown_timer = settings.get("min_cooldown_timer")
        max_cooldown_timer = settings.get("max_cooldown_timer")
        
        # If both min and max are NULL, skip the check (no restriction)
        if min_cooldown_timer is None and max_cooldown_timer is None:
            return "ACTIVE"
        
        # Get cooldown_timer from database
        cooldown_timer = None
        try:
            import psycopg2
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT cooldown_timer FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
                result = cursor.fetchone()
                cooldown_timer = result[0] if result and result[0] is not None else None
            conn.close()
        except Exception as e:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error getting cooldown timer: {e}")
        
        # If cooldown_timer is NULL, cannot determine - return INACTIVE
        if cooldown_timer is None:
            return "INACTIVE"
        
        # DB stores cooldown_timer as REMAINING seconds in spike cooldown (positive = in spike).
        # min/max_cooldown_timer are "seconds since spike started" window. So: time_since_spike = total_cooldown - remaining.
        cooldown_minutes = settings.get("spike_alert_cooldown_minutes") or 0
        total_cooldown_seconds = int(cooldown_minutes) * 60
        time_since_spike = total_cooldown_seconds - int(cooldown_timer) if cooldown_timer > 0 else 0
        
        # If min is set, time_since_spike must be >= min (not too close to spike start)
        if min_cooldown_timer is not None and time_since_spike < min_cooldown_timer:
            return "INACTIVE"  # Too close to momentum spike start
        
        # If max is set, time_since_spike must be <= max (not too far after spike started)
        if max_cooldown_timer is not None and time_since_spike > max_cooldown_timer:
            return "INACTIVE"  # Too far after spike regime started
        
        # All checks passed - cooldown window (time since spike) is within min/max
        return "ACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error determining status: {e}")
        return "DISABLED"

def broadcast_auto_entry_indicator_change():
    """Broadcast auto entry indicator state change via WebSocket to main app"""
    try:
        # Determine and update database status first
        new_status = determine_auto_entry_status()
        
        # Update the database with the new status
        update_auto_entry_status_in_db(new_status)
        
        # Get cooldown timer from database
        cooldown_timer = 0
        try:
            import psycopg2
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT cooldown_timer FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
                result = cursor.fetchone()
                cooldown_timer = result[0] if result and result[0] is not None else 0
            conn.close()
        except Exception as e:
            log(f"[AUTO ENTRY] ❌ Error getting cooldown timer: {e}")
        
        # Create broadcast data with database status
        broadcast_data = {
            "status": new_status,
            "cooldown_timer": cooldown_timer,
            "enabled": _aes_indicator_bucket()["enabled"],
            "ttc_within_window": _aes_indicator_bucket()["ttc_within_window"],
            "scanning_active": _aes_indicator_bucket()["scanning_active"],
            "service_healthy": _aes_indicator_bucket()["service_healthy"],
            "spike_alert_active": _aes_indicator_bucket()["spike_alert_active"],
            "spike_alert_start_time": _aes_indicator_bucket()["spike_alert_start_time"],
            "spike_alert_momentum_value": _aes_indicator_bucket()["spike_alert_momentum_value"],
            "spike_alert_recovery_countdown": _aes_indicator_bucket()["spike_alert_recovery_countdown"],
            "current_momentum": _aes_indicator_bucket()["current_momentum"]
        }
        
        # Check if state has actually changed (compare with previous)
        current_state_key = (new_status, cooldown_timer)
        _prev_key = ctx_ident()
        if _previous_indicator_by_monitor.get(_prev_key) == current_state_key:
            return  # No change, don't broadcast
        
        _previous_indicator_by_monitor[_prev_key] = current_state_key
        log_debug("State changed, broadcasting...")
        
        # COMMENTED OUT: Legacy auto_entry_indicator_change WebSocket notification - now using auto_trade_status_change only
        # try:
        #     port = get_port("main_app")
        #     url = f"http://localhost:{port}/api/broadcast_auto_entry_indicator"
        #     response = requests.post(url, json=broadcast_data, timeout=2)
        #     if response.ok:
        #         log(f"[AUTO ENTRY] ✅ Auto entry indicator change broadcasted: status={new_status}, cooldown={cooldown_timer}")
        #     else:
        #         log(f"[AUTO ENTRY] ⚠️ Failed to broadcast indicator change: {response.status_code}")
        # except Exception as e:
        #     log(f"[AUTO ENTRY] ❌ Error broadcasting indicator change: {e}")
        
        full_monitor_id = f"mon_{ctx_user()}_{ctx_mid()}"
        _aes_preferences_notify(
            "auto_trade_status_change",
            {"monitor_id": full_monitor_id, "auto_trade_status": new_status},
        )
            
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error in broadcast_auto_entry_indicator_change: {e}")


def periodic_status_sync():
    """
    Ensure auto_trade_status stays in sync with current conditions, even if
    strategy-specific paths do not trigger a broadcast on a given tick.

    This is intentionally light: it only runs when auto_trade is enabled and
    delegates to determine_auto_entry_status + update_auto_entry_status_in_db.
    """
    try:
        if AES_UNIFIED_POOL:
            if AES_UNIFIED_15M:
                from backend.core.unified_15m_monitors import iter_active_15m_monitor_bindings

                iter_bindings = iter_active_15m_monitor_bindings()
            elif AES_UNIFIED_HOURLY:
                from backend.core.unified_hourly_monitors import iter_active_hourly_monitor_bindings

                iter_bindings = iter_active_hourly_monitor_bindings()
            else:
                from backend.core.unified_all_monitors import iter_active_unified_monitor_bindings

                iter_bindings = iter_active_unified_monitor_bindings()
            for u, m in iter_bindings:
                with aes_monitor_bind(u, m):
                    if is_auto_trade_enabled():
                        status = determine_auto_entry_status()
                        update_auto_entry_status_in_db(status)
            return

        auto_trade_enabled = is_auto_trade_enabled()
        if not auto_trade_enabled:
            return

        status = determine_auto_entry_status()
        update_auto_entry_status_in_db(status)
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error during periodic_status_sync: {e}")

def is_auto_trade_enabled():
    """Check if AUTO ENTRY is enabled by checking auto_trade boolean in monitor_list"""
    if AES_UNIFIED_POOL and _aes_bind_m.get() is None:
        return False
    try:
        import psycopg2
        conn = get_db_connection()
        if not conn:
            log(f"[AUTO ENTRY] ❌ No database connection available when reading auto_trade for monitor {ctx_mid()}; shutting down supervisor")
            os._exit(0)

        with conn.cursor() as cursor:
            # Check auto_trade boolean from the specific monitor's row in monitor_list
            cursor.execute(f"SELECT auto_trade FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()

            if not result:
                log(
                    f"[AUTO ENTRY] ❌ Monitor {ctx_mid()} missing from {_aes_monitor_list_table()}; "
                    "shutting down supervisor to avoid ghost auto-entry"
                )
                os._exit(0)

            auto_trade_enabled = bool(result[0])
            return auto_trade_enabled
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error reading auto_trade from monitor_list for monitor {ctx_mid()}: {e}")
        os._exit(0)

def get_auto_entry_settings():
    """Get auto entry settings from monitor's assigned strategy"""
    global previous_settings
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Get monitor's strategy
            cursor.execute(f"""
                SELECT strategy FROM {_aes_monitor_list_table()} WHERE id = %s
            """, (ctx_mid(),))
            monitor_result = cursor.fetchone()
            
            if monitor_result:
                strategy_name = monitor_result[0]
                
                from backend.core.auto_entry_settings_store import monitor_list_flip_columns_available

                has_flip = monitor_list_flip_columns_available(cursor)
                sel_flip = """
                           , flip_sell_prob, flip_sell_prob_mult, flip_sell_floor, flip_sell_floor_mult
                """
                # Get monitor parameters
                cursor.execute(
                    """
                    SELECT min_probability, max_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
                           spike_alert_enabled, spike_alert_momentum_threshold,
                           spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                           min_volume, momentum_scalp_entry_threshold, min_ask, max_ask, max_price_spread, prob_adj,
                           min_cooldown_timer, max_cooldown_timer, min_ask_range
                    """
                    + (sel_flip if has_flip else "")
                    + f"""
                    FROM {_aes_monitor_list_table()} WHERE id = %s
                    """,
                    (ctx_mid(),),
                )
                strategy_result = cursor.fetchone()
                
                if strategy_result:
                    settings = {
                        "min_probability": float(strategy_result[0]) if strategy_result[0] is not None else 95.0,
                        "max_probability": float(strategy_result[1]) if strategy_result[1] is not None else 100.0,
                        "min_differential": float(strategy_result[2]),
                        "max_differential": float(strategy_result[3]) if strategy_result[3] is not None else None,
                        "min_time": strategy_result[4],
                        "max_time": strategy_result[5],
                        "allow_re_entry": strategy_result[6],
                        "spike_alert_enabled": strategy_result[7],
                        "spike_alert_momentum_threshold": strategy_result[8],
                        "spike_alert_cooldown_threshold": strategy_result[9],
                        "spike_alert_cooldown_minutes": strategy_result[10],
                        "min_volume": strategy_result[11],  # From monitor min_volume
                        "momentum_scalp_entry_threshold": float(strategy_result[12]) if strategy_result[12] is not None else None,
                        "min_ask": float(strategy_result[13]) if strategy_result[13] is not None else 0.0000,
                        "max_ask": float(strategy_result[14]) if strategy_result[14] is not None else 0.9800,
                        "max_price_spread": float(strategy_result[15]) if strategy_result[15] is not None else 0.0300,
                        "prob_adj": float(strategy_result[16]) if strategy_result[16] is not None else 5.00,
                        "min_cooldown_timer": strategy_result[17] if strategy_result[17] is not None else None,
                        "max_cooldown_timer": strategy_result[18] if strategy_result[18] is not None else None,
                        "min_ask_range": float(strategy_result[19]) if strategy_result[19] is not None else None,
                    }
                    if has_flip:
                        settings["flip_sell_prob"] = bool(strategy_result[20]) if strategy_result[20] is not None else False
                        settings["flip_sell_prob_mult"] = strategy_result[21] if strategy_result[21] is not None else None
                        settings["flip_sell_floor"] = bool(strategy_result[22]) if strategy_result[22] is not None else False
                        settings["flip_sell_floor_mult"] = strategy_result[23] if strategy_result[23] is not None else None
                    else:
                        settings["flip_sell_prob"] = False
                        settings["flip_sell_prob_mult"] = None
                        settings["flip_sell_floor"] = False
                        settings["flip_sell_floor_mult"] = None
                    
                    # Check for settings changes
                    if previous_settings is not None:
                        changed_settings = []
                        for key, value in settings.items():
                            if key not in previous_settings or previous_settings[key] != value:
                                changed_settings.append(f"{key}: {previous_settings.get(key, 'None')} → {value}")
                        
                        if changed_settings:
                            log_debug(f"SETTINGS CHANGED | Monitor {MONITOR_IDENTIFIER} | Changes: {'; '.join(changed_settings)}")
                    
                    previous_settings = settings.copy()
                    # Only log settings loading on first load or when settings change
                    if previous_settings is None:
                        log_debug(f"Loaded settings from monitor: {MONITOR_IDENTIFIER}")
                    return settings
                else:
                    log_debug(f"No monitor found with ID: {ctx_mid()}")
                    return {}
            else:
                log_debug(f"No monitor found with ID: {ctx_mid()}")
                return {}
    except Exception as e:
        log(f"[AUTO ENTRY] Error reading settings from strategy: {e}")
        return {}

def get_current_ttc():
    """Get current TTC from strike table (PostgreSQL). Uses ttc_hourly or ttc_15m per monitor market; no HTTP to main app."""
    try:
        current_symbol, current_market = get_current_monitor_symbol_and_market()
        if not current_market or current_market not in ("hourly", "15m"):
            return 0
        ctx = _aes_unified_tick_context.get()
        if ctx and ctx.get("data") is not None:
            if ctx.get("symbol") == current_symbol and ctx.get("market") == current_market:
                ttc_val = ctx["data"].get("ttc")
                if ttc_val is not None:
                    return int(ttc_val)
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            ttc_column = "ttc_15m" if current_market == "15m" else "ttc_hourly"
            ex = _strike_data_exchange_key()
            sym_u = current_symbol.upper()
            if current_market == "15m":
                table_15m = get_strike_table_name(current_symbol, "15m")
                cursor.execute(
                    f"""
                    SELECT {ttc_column} FROM live_data.{table_15m}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (ex, sym_u),
                )
            else:
                table_name = get_strike_table_name(current_symbol, current_market)
                cursor.execute(
                    f"""
                    SELECT {ttc_column} FROM live_data.{table_name}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (ex, sym_u),
                )
            result = cursor.fetchone()
        conn.close()
        if result and result[0] is not None:
            return int(result[0])
        # Fallback when strike table has no row (e.g. generator not yet run)
        now = est_now()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return max(1, int((next_hour - now).total_seconds()))
    except Exception as e:
        log(f"[AUTO ENTRY] get_current_ttc fallback after error: {e}")
        now = est_now()
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return max(1, int((next_hour - now).total_seconds()))

def get_strike_table_path():
    """Get the path to the master strike table JSON file"""
    current_symbol = get_current_monitor_symbol()
    return os.path.join(get_data_dir(), "live_data", "markets", "kalshi", "strike_tables", f"strike_table_{current_symbol.lower()}.json")

def get_master_strike_table_data():
    """Get current master strike table data from PostgreSQL (uses monitor symbol + market)."""
    sym, mkt = get_current_monitor_symbol_and_market()
    ctx = _aes_unified_tick_context.get()
    if ctx and ctx.get("data") is not None:
        if ctx.get("symbol") == sym and ctx.get("market") == mkt:
            if AES_UNIFIED_PROFILE and AES_UNIFIED_POOL:
                _unified_profile_state["master_cache_hits"] += 1
            return ctx["data"]
    t0 = time.perf_counter()
    try:
        return _fetch_master_strike_table_data(sym, mkt)
    finally:
        if AES_UNIFIED_PROFILE and AES_UNIFIED_POOL:
            _unified_profile_state["master_fetch_sec"] += time.perf_counter() - t0


def _fetch_master_strike_table_data(current_symbol: str, current_market: str):
    """Load ladder snapshot for explicit symbol and market (hourly or 15m).

    Prefers Redis snapshot from ``strike_snapshot_publisher`` when enabled so all AES
    processes see the same payload per wall second; falls back to PostgreSQL.
    """
    try:
        from backend.core.strike_ladder_fetch import fetch_strike_ladder_prefer_snapshot

        return fetch_strike_ladder_prefer_snapshot(
            current_symbol, current_market, _strike_data_exchange_key()
        )
    except Exception as e:
        log(f"[AUTO_ENTRY] Error reading master strike table data: {e}")
        return None


def _fetch_ttc_15m_latest_header(current_symbol: str) -> Optional[int]:
    """If ladder JSON omits ``ttc_15m`` (older Redis snapshots), read latest hourly row from ``live_data``."""
    try:
        from backend.core.config.database import get_system_postgresql_connection

        conn = get_system_postgresql_connection()
        if not conn:
            return None
        try:
            ex = _strike_data_exchange_key()
            sym_u = (current_symbol or "").upper().strip()
            if not sym_u:
                return None
            table_name = get_strike_table_name(current_symbol, "hourly")
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT ttc_15m FROM live_data.{table_name}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (ex, sym_u),
                )
                row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return None
    return None


def _fetch_ttc_native_15m_latest_header(current_symbol: str) -> Optional[int]:
    """If 15m ladder snapshot omits TTC, read latest ``ttc_15m`` from the native 15m strike table."""
    try:
        from backend.core.config.database import get_system_postgresql_connection

        conn = get_system_postgresql_connection()
        if not conn:
            return None
        try:
            ex = _strike_data_exchange_key()
            sym_u = (current_symbol or "").upper().strip()
            if not sym_u:
                return None
            table_name = get_strike_table_name(current_symbol, "15m")
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT ttc_15m FROM live_data.{table_name}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (ex, sym_u),
                )
                row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        return None
    return None


def get_master_strike_table_data_simulated_15m():
    """Ladder snapshot for the model-probe simulated path: side-aware 15m probability + quarter TTC.

    - **Hourly monitors:** same hourly ladder as live AES; TTC from ``ttc_15m`` on that snapshot
      (Kalshi quarter countdown within the hour).
    - **15m monitors:** native 15m ladder; TTC from the 15m contract countdown (``ttc`` / ``ttc_15m``).

    Uses ``DISTINCT ON (ticker)`` ladder rows and explicit yes/no 15m legs so the prob band matches
    the traded side. Simulated entries do not apply differential / volume / max_ask / Rising Devil range.
    """
    try:
        from backend.core.strike_ladder_fetch import probability_from_strike_row_side_aware

        sym, mkt = get_current_monitor_symbol_and_market()
        mkt_l = (mkt or "").strip().lower()
        if mkt_l not in ("hourly", "15m"):
            return None
        data = get_master_strike_table_data()
        if not data or "strikes" not in data:
            return None

        if mkt_l == "hourly":
            raw_ttc = data.get("ttc_15m")
            if raw_ttc is None:
                raw_ttc = _fetch_ttc_15m_latest_header(sym)
        else:
            raw_ttc = data.get("ttc")
            if raw_ttc is None:
                raw_ttc = data.get("ttc_15m")
            if raw_ttc is None:
                raw_ttc = _fetch_ttc_native_15m_latest_header(sym)
        if raw_ttc is None:
            return None

        out = {
            "symbol": data.get("symbol"),
            "current_price": data.get("current_price"),
            "ttc": int(raw_ttc),
            "event_ticker": data.get("event_ticker"),
            "market_title": data.get("market_title"),
            "strike_tier": data.get("strike_tier"),
            "market_status": data.get("market_status"),
            "strikes": [],
        }
        for strike in data["strikes"]:
            row = dict(strike)
            active_side = row.get("active_side")
            p15_side = probability_from_strike_row_side_aware(row, "15m", active_side)
            if p15_side is not None:
                row["probability"] = float(p15_side)
            elif row.get("probability_15m") is not None:
                row["probability"] = float(row["probability_15m"])
            elif row.get("probability") is not None:
                row["probability"] = float(row["probability"])
            else:
                row["probability"] = None
            out["strikes"].append(row)
        return out
    except Exception as e:
        log(f"[SIMULATED 15m] Error building simulated ladder: {e}")
        return None


def get_position_size():
    """Get total position size from monitor-specific configuration"""
    conn = None
    try:
        import psycopg2

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT total_position FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            if result:
                total_position = result[0]
                log_debug(f"Total position loaded from monitor {ctx_mid()}: {total_position}")
                return total_position
            else:
                log_debug(f"No monitor configuration found for monitor {ctx_mid()}")
                return None
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading total position from monitor {ctx_mid()}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_current_multiplier():
    """Get current multiplier value for this monitor."""
    conn = None
    try:
        import psycopg2

        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT multiplier FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            if result and result[0] is not None:
                multiplier_value = float(result[0])
                log(f"[AUTO ENTRY] Multiplier loaded from monitor {ctx_mid()}: {multiplier_value}")
                return multiplier_value
            else:
                log(f"[AUTO ENTRY] No multiplier found for monitor {ctx_mid()} - defaulting to 1.0")
                return 1.0
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading multiplier from monitor {ctx_mid()}: {e}")
        return 1.0
    finally:
        if conn:
            conn.close()

def get_loss_prevention_state():
    """Get effective loss_prevention state from monitor configuration and symbol-wide override."""
    conn = None
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            loss_prevention = resolve_effective_loss_prevention_state(
                cursor,
                _aes_monitor_list_table(),
                str(ctx_mid()),
            )
            log(f"[AUTO ENTRY] Effective loss prevention state for monitor {ctx_mid()}: {loss_prevention}")
            return loss_prevention
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading loss_prevention from monitor {ctx_mid()}: {e}")
        return "off"  # Default to off on error
    finally:
        if conn:
            conn.close()

def get_trade_strategy():
    """Get trade strategy from monitor-specific configuration"""
    if AES_UNIFIED_POOL and _aes_bind_m.get() is None:
        return "Hourly HTC"
    conn = None
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT strategy FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            if result:
                trade_strategy = result[0]
                return trade_strategy
            else:
                return "Hourly HTC"  # Default fallback
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading trade strategy from monitor {ctx_mid()}: {e}")
        return "Hourly HTC"  # Default fallback
    finally:
        if conn:
            conn.close()

def get_bankroll_allotment():
    """Get bankroll allotment total from monitor-specific configuration"""
    conn = None
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT bankroll_allotment_total FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            if result:
                bankroll_allotment = result[0]
                log(f"[AUTO ENTRY] Bankroll allotment loaded from monitor {ctx_mid()}: {bankroll_allotment}")
                return bankroll_allotment
            else:
                log_debug(f"No monitor configuration found for monitor {ctx_mid()}")
                return None
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading bankroll allotment from monitor {ctx_mid()}: {e}")
        return None
    finally:
        if conn:
            conn.close()


def _defer_unified_aes_trade_followup(ticket_id: str, log_message: str, notification_data: dict) -> None:
    """Best-effort trade_logger + preferences notify off the unified AES hot path."""

    def _run():
        import requests as _req

        try:
            from backend.util.trade_logger import log_trade_event

            log_trade_event(ticket_id, log_message, service="auto_entry_supervisor")
        except Exception:
            pass
        try:
            from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms

            if use_trading_redis_comms():
                publish_preferences_event(
                    "automated_trade_triggered",
                    notification_data,
                    tenant_user_no=ctx_user(),
                )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def _auto_entry_strike_vs_spot_gate(strike_data: dict, symbol_upper: str) -> tuple[bool, str]:
    """
    Failsafe: block auto-entry when the strike is wildly inconsistent with live spot.
    Uses the same drift limits as ``floor_strike_vs_spot_check`` (see
    ``FLOOR_STRIKE_VS_SPOT_CHECK`` and ``FLOOR_STRIKE_VS_SPOT_MAX_DRIFT_PCT``).
    """
    sym = (symbol_upper or "").strip().upper()
    if not sym:
        return True, "ok"
    raw = strike_data.get("strike")
    if raw is None:
        return True, "ok"
    try:
        strike_f = float(raw)
    except (TypeError, ValueError):
        return True, "ok"
    spot = None
    try:
        spot = get_current_price_from_db(sym)
    except Exception:
        pass
    ok, reason, _drift = floor_strike_vs_spot_check(strike_f, spot)
    return ok, reason


def trigger_auto_entry_trade(strike_data):
    """Trigger a buy trade by calling the trade_manager service directly"""
    import requests
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo

    t_trig = time.perf_counter()
    log(f"[AUTO ENTRY] 🟢 Triggered AUTO ENTRY for strike: {strike_data.get('strike')} {strike_data.get('side')}")
    
    try:
        current_symbol, current_market = get_current_monitor_symbol_and_market()
        cm = (current_market or "").strip().lower()
        if cm in ("15m", "hourly"):
            conn = None
            try:
                conn = get_db_connection()
                ok, reason = evaluate_pipeline_gate_conn(
                    conn,
                    exchange="kalshi",
                    market=cm,
                    symbol=current_symbol.upper(),
                )
                conn.close()
                conn = None
                if not ok:
                    log(
                        f"[AUTO ENTRY] 🚫 BLOCKED by pipeline gate symbol={current_symbol} "
                        f"market={cm} reason={reason}"
                    )
                    return False
            except Exception as gate_err:
                log(f"[AUTO ENTRY] 🚫 BLOCKED by pipeline gate check error: {gate_err}")
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                return False

        ok_spot, spot_reason = _auto_entry_strike_vs_spot_gate(
            strike_data, (current_symbol or "").strip().upper()
        )
        if not ok_spot:
            log(
                f"[AUTO ENTRY] BLOCKED by strike vs live spot gate symbol={current_symbol} "
                f"strike={strike_data.get('strike')} reason={spot_reason}"
            )
            return False

        port = scoped_trade_manager_http_port()
        url = f"http://localhost:{port}/trades"
        
        strike_table_data = get_master_strike_table_data() or {}
        current_symbol = get_current_monitor_symbol()
        contract_name = resolve_auto_entry_contract_name(
            current_symbol, strike_table_data, strike_data.get("ticker")
        )

        # Get position size from trade preferences
        position_size = get_position_size()
        if position_size is None:
            log(f"[AUTO ENTRY] ❌ Cannot trigger trade - no valid position size found")
            return False
        
        # Check loss prevention state and override position size if needed
        loss_prevention = get_loss_prevention_state()
        loss_prevention_base = normalize_loss_prevention_state_for_sizing(loss_prevention)
        if loss_prevention_base in (
            "one_contract",
            "win_streak_one_contract",
            "symbol_one_contract",
            "sim_loss_1c",
            "live_loss_1c",
        ):
            log(f"[AUTO ENTRY] 🛡️ Loss prevention active - overriding position size from {position_size} to 1 contract")
            position_size = 1
        elif loss_prevention_base == "sim_loss_25":
            new_sz = max(1, int(round(position_size * 0.25)))
            log(f"[AUTO ENTRY] 🛡️ Sim loss 25% tier — position size {position_size} -> {new_sz}")
            position_size = new_sz
        elif loss_prevention_base == "sim_loss_50":
            new_sz = max(1, int(round(position_size * 0.5)))
            log(f"[AUTO ENTRY] 🛡️ Sim loss 50% tier — position size {position_size} -> {new_sz}")
            position_size = new_sz
        else:
            log(f"[AUTO ENTRY] Loss prevention is '{loss_prevention}' - using configured position size: {position_size}")
        
        # Get bankroll allotment from monitor configuration
        bankroll_allotment = get_bankroll_allotment()
        if bankroll_allotment is None:
            log(f"[AUTO ENTRY] ❌ Cannot trigger trade - no valid bankroll allotment found")
            return False
        
        _log_aes_trigger_feed_snapshot(strike_data, strike_table_data)
        
        # Create the exact same payload that trade_initiator would create
        # Generate unique ticket ID (same format as trade_initiator)
        ticket_id = f"TICKET-{uuid.uuid4().hex[:9]}-{int(est_now().timestamp() * 1000)}"
        
        # Get current time in Eastern Time (same as trade_initiator)
        now = est_now()
        eastern_date = now.strftime('%Y-%m-%d')
        eastern_time = now.strftime('%H:%M:%S')
        
        # Convert side format (yes/no to Y/N) - same as trade_initiator
        side = strike_data.get("side")
        converted_side = side
        if side == "yes":
            converted_side = "Y"
        elif side == "no":
            converted_side = "N"

        from backend.core.trading_redis_comms import publish_trade_manager_command, use_trading_redis_comms

        use_redis = use_trading_redis_comms()
        unified_redis_fast = AES_UNIFIED_POOL and use_redis

        # trade_manager insert_trade loads symbol_open from live_price_log; skip main_app on unified+Redis hot path
        if not unified_redis_fast:
            try:
                main_port = get_port("main_app")
                price_url = f"http://localhost:{main_port}/api/{current_symbol.lower()}_price"
                price_response = requests.get(price_url, timeout=2)
                if price_response.ok:
                    price_response.json()
            except Exception as e:
                log(f"[AUTO ENTRY] ⚠️ Could not get {current_symbol} price: {e}")
        
        # Get trade strategy from PostgreSQL
        trade_strategy = get_trade_strategy()
        
        # Get paper_trade setting from monitor config
        paper_trade = False
        try:
            import psycopg2
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT paper_trade FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
                result = cursor.fetchone()
                if result and result[0] is not None:
                    paper_trade = bool(result[0])
            conn.close()
        except Exception as e:
            log(f"[AUTO ENTRY] ⚠️ Could not get paper_trade setting: {e}, defaulting to False")
        
        # Prepare the trade data exactly like trade_initiator does (count_fp for full-chain consistency)
        trade_payload = {
            "ticket_id": ticket_id,
            "status": "pending",
            "date": eastern_date,
            "time": eastern_time,
            "symbol": current_symbol,
            "exchange": "kalshi",
            "trade_strategy": trade_strategy,
            "contract": contract_name,
            "strike": strike_data.get("strike"),
            "side": converted_side,
            "ticker": strike_data.get("ticker"),
            "prob": strike_data.get("probability"),
            "diff": strike_data.get("diff"),
            "buy_price": strike_data.get("buy_price"),
            "position": position_size,
            "count_fp": f"{float(position_size):.2f}",
            "monitor": f"mon_{ctx_user()}_{ctx_mid()}",
            "bankroll_allotment_total": bankroll_allotment,
            "entry_method": "auto_entry",
            "loss_prevention": is_loss_prevention_sizing_state(loss_prevention),
            "loss_prevention_state": loss_prevention,
            "multiplier": get_current_multiplier(),
            "paper_trade": paper_trade
        }
        
        log(f"[AUTO ENTRY] 📤 Sending trade to trade_manager_{ctx_user()} :{port}/trades | {trade_payload}")

        log_message = (
            f"ENTRY | {contract_name} | {strike_data.get('strike')} | {strike_data.get('side')} | "
            f"{position_size} | {strike_data.get('buy_price')} | {strike_data.get('probability')}"
        )
        notification_data = {
            "strike": strike_data.get("strike"),
            "side": strike_data.get("side"),
            "ticker": strike_data.get("ticker"),
            "buy_price": strike_data.get("buy_price"),
            "probability": strike_data.get("probability"),
            "contract": contract_name,
            "position": position_size,
            "entry_method": "auto",
        }

        redis_published = bool(
            use_redis
            and publish_trade_manager_command(
                "add_trade",
                trade_payload,
                "auto_entry_supervisor",
                correlation_id=ticket_id,
                tenant_user_no=ctx_user(),
            )
        )

        if redis_published and AES_UNIFIED_POOL:
            _defer_unified_aes_trade_followup(ticket_id, log_message, notification_data)
            log(f"[AUTO ENTRY] ✅ Trade enqueued to trade_manager (Redis); follow-up logging/notify deferred")
            return True

        if redis_published:
            class _Ok201:
                status_code = 201

                def json(self):
                    return {}

            response = _Ok201()
        else:
            if AES_UNIFIED_POOL:
                log(
                    "[AUTO ENTRY] ⚠️ Unified pool: Redis add_trade unavailable; "
                    "falling back to synchronous HTTP POST trade_manager"
                )
            response = requests.post(url, json=trade_payload, timeout=10)

        if response.status_code == 201:
            result = response.json()
            log(f"[AUTO ENTRY] ✅ Trade initiated successfully via trade_manager: {result}")

            from backend.util.trade_logger import log_trade_event

            log_trade_event(ticket_id, log_message, service="auto_entry_supervisor")

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

            return True
        log(f"[AUTO ENTRY] ❌ Trade initiation failed: {response.status_code} - {getattr(response, 'text', '')}")
        return False
        
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error initiating trade via trade_manager: {e}")
        return False
    finally:
        if AES_UNIFIED_PROFILE and AES_UNIFIED_POOL:
            _unified_profile_state["trigger_trade_sec"] += time.perf_counter() - t_trig

def can_trade_strike(strike_key):
    """ATOMIC: Check if we can trade this strike (cooldown check)"""
    current_time = time.time()
    
    if strike_key in last_trade_times:
        time_since_last_trade = current_time - last_trade_times[strike_key]
        if time_since_last_trade < TRADE_COOLDOWN:
            # Skipping {strike_key} - traded {time_since_last_trade:.1f}s ago (cooldown: {TRADE_COOLDOWN}s)
            return False
    
    # ATOMIC: Add to cooldown immediately
    last_trade_times[strike_key] = current_time
            # {strike_key} passed cooldown check - added to cooldown
    return True

def has_bracket_for_cycle(contract: Optional[str] = None, strike_tier: Optional[int] = None) -> bool:
    """Check if a bracket exists for the current cycle (contract/date).
    
    A bracket is defined as: one Y trade and one N trade with strikes within 2 strike tiers of each other.
    This function queries the tenant ``users.trades_<slot>`` table for open/pending trades from this monitor with the same contract.
    
    Args:
        contract: The contract label (e.g., "BTC 12pm"). If None, uses _LAST_MONITOR_STATE["contract"].
        strike_tier: The strike tier spacing (e.g., 250 for BTC, 50 for ETH). If None, tries to get from strike table data.
    
    Returns:
        True if a bracket exists (Y and N trades within 2 strike tiers), False otherwise.
    """
    try:
        import psycopg2
        
        # Get contract from parameter or from state
        if contract is None:
            contract = _LAST_MONITOR_STATE.get("contract")
        
        if not contract:
            # No contract available, can't check bracket
            return False
        
        # Get strike_tier if not provided
        if strike_tier is None:
            # Try to get from strike table data
            strike_table_data = get_master_strike_table_data()
            if strike_table_data and strike_table_data.get("strike_tier"):
                try:
                    strike_tier = int(strike_table_data["strike_tier"])
                except (ValueError, TypeError):
                    strike_tier = None
        
        if strike_tier is None or strike_tier <= 0:
            # Can't determine bracket distance without strike tier
            log(f"[AUTO ENTRY REVERSE HTC] ⚠️ Cannot check bracket - strike_tier not available")
            return False
        
        # Calculate bracket distance: 2 strikes = 2 * strike_tier
        bracket_distance = 2 * strike_tier
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current monitor identifier
        current_monitor = f"mon_{ctx_user()}_{ctx_mid()}"
        
        # Query tenant trades table for open/pending trades from this monitor with the same contract
        cursor.execute(f"""
            SELECT id, strike, side, status, contract, date
            FROM {_aes_trades_table()}
            WHERE status IN ('open', 'pending')
              AND monitor = %s
              AND contract = %s
        """, (current_monitor, contract))
        
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            return False
        
        # Parse strikes and separate by side
        yes_trades = []
        no_trades = []
        
        # Helper function to parse strike value (e.g., "$50,000" -> 50000)
        def parse_strike(strike_str: str) -> Optional[float]:
            if not strike_str:
                return None
            # Remove $ and commas, then convert to float
            cleaned = strike_str.replace('$', '').replace(',', '').strip()
            try:
                return float(cleaned)
            except (ValueError, TypeError):
                return None
        
        for trade in trades:
            trade_id, strike_str, side, status, trade_contract, trade_date = trade
            
            # Normalize side
            normalized_side = str(side).upper()
            if normalized_side in ['Y', 'YES']:
                strike_value = parse_strike(strike_str)
                if strike_value is not None:
                    yes_trades.append(strike_value)
            elif normalized_side in ['N', 'NO']:
                strike_value = parse_strike(strike_str)
                if strike_value is not None:
                    no_trades.append(strike_value)
        
        # Check if we have at least one Y and one N trade
        if not yes_trades or not no_trades:
            return False
        
        # Check if any Y and N trades are within bracket_distance of each other
        for yes_strike in yes_trades:
            for no_strike in no_trades:
                strike_diff = abs(yes_strike - no_strike)
                if strike_diff <= bracket_distance:
                    # Bracket found
                    return True
        
        # No bracket found
        return False
        
    except Exception as e:
        log(f"[AUTO ENTRY REVERSE HTC] ⚠️ Error checking bracket: {e}")
        # On error, allow trading (fail open)
        return False

def is_strike_already_traded(strike_data):
    """Check if we already have an in-flight trade on this Kalshi market ticker (same monitor + side).

    Statuses counted as blocking: open, pending, closing (anything not yet terminal).
    Side comparison is canonicalized so DB ``Y`` matches strike_data ``yes`` (prior bug: never matched).
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        current_monitor = f"mon_{ctx_user()}_{ctx_mid()}"
        ticker = strike_data.get("ticker")
        want_side = _aes_side_bucket_for_dedupe(strike_data.get("side"))
        if not ticker or not want_side:
            return False

        cursor.execute(
            f"""
            SELECT id, ticker, side, status
            FROM {_aes_trades_table()}
            WHERE status IN ('open', 'pending', 'closing')
              AND monitor = %s
            """,
            (current_monitor,),
        )
        trades = cursor.fetchall()
        conn.close()

        for trade_id, trade_ticker, trade_side, trade_status in trades:
            if trade_ticker != ticker:
                continue
            if _aes_side_bucket_for_dedupe(trade_side) != want_side:
                continue
            log_debug(
                f"⚠️ Found {trade_status} trade (ID: {trade_id}) ticker={ticker} side_bucket={want_side} "
                f"monitor={current_monitor}"
            )
            return True
        return False
    except Exception as e:
        log(f"Error checking {_aes_trades_table()} for in-flight trades: {e}")
        return False


def _momentum_breakout_legs_in_db(strike_above_data, strike_below_data) -> Tuple[bool, bool]:
    """YES-above / NO-below: return (yes_leg_exists, no_leg_exists) for in-flight trades."""
    yes_e = False
    no_e = False
    if strike_above_data and strike_above_data.get("ticker"):
        yes_e = is_strike_already_traded(
            {
                "strike": strike_above_data.get("strike"),
                "side": "yes",
                "ticker": strike_above_data.get("ticker"),
            }
        )
    if strike_below_data and strike_below_data.get("ticker"):
        no_e = is_strike_already_traded(
            {
                "strike": strike_below_data.get("strike"),
                "side": "no",
                "ticker": strike_below_data.get("ticker"),
            }
        )
    return yes_e, no_e


def _momentum_contain_legs_in_db(strike_above_data, strike_below_data) -> Tuple[bool, bool]:
    """NO-above / YES-below: return (no_leg_exists, yes_leg_exists) for in-flight trades."""
    no_e = False
    yes_e = False
    if strike_above_data and strike_above_data.get("ticker"):
        no_e = is_strike_already_traded(
            {
                "strike": strike_above_data.get("strike"),
                "side": "no",
                "ticker": strike_above_data.get("ticker"),
            }
        )
    if strike_below_data and strike_below_data.get("ticker"):
        yes_e = is_strike_already_traded(
            {
                "strike": strike_below_data.get("strike"),
                "side": "yes",
                "ticker": strike_below_data.get("ticker"),
            }
        )
    return no_e, yes_e


def is_strike_already_simulated_traded(strike_data):
    """True if we already have any simulated trade (open, pending, or closed) for this monitor+date+contract+strike+side.
    Prevents re-insert after the 15m expiration job closes a trade. Uses same DB as trade_manager (DB_* / REC_DB_*)."""
    try:
        date_str = strike_data.get('date')
        contract_str = strike_data.get('contract')
        strike_str = strike_data.get('strike')
        if not date_str or not contract_str or strike_str is None:
            log(f"[SIMULATED 15m] duplicate check requires date, contract, strike in strike_data")
            return False
        side = (strike_data.get('side') or '').lower()
        db_side = 'Y' if side in ('yes', 'y') else 'N'
        conn = get_db_connection()
        if not conn:
            log(f"[SIMULATED 15m] No DB connection for duplicate check")
            return False
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT 1 FROM {_aes_trades_simulated_table()}
                    WHERE monitor = %s AND date = %s AND contract = %s AND strike = %s AND side = %s
                """, (f"mon_{ctx_user()}_{ctx_mid()}", date_str, contract_str, strike_str, db_side))
                return cursor.fetchone() is not None
        finally:
            conn.close()
    except Exception as e:
        log(f"[SIMULATED 15m] Error checking {_aes_trades_simulated_table()}: {e}")
        return False


def can_trade_strike_simulated(strike_key):
    """Cooldown check for simulated path only."""
    import time
    t = time.time()
    if strike_key in last_simulated_trade_times and (t - last_simulated_trade_times[strike_key]) < TRADE_COOLDOWN:
        return False
    last_simulated_trade_times[strike_key] = t
    return True


def trigger_simulated_trade(strike_data):
    """POST to trade_manager with simulated_trade=True; writes to tenant ``users.trades_simulated_<slot>``, no executor.
    Contract uses next 15m boundary (e.g. BTC 2:15pm) so weekly_cycle decimal reflects quarter (.0/.1/.2/.3)."""
    import requests
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        port = scoped_trade_manager_http_port()
        current_symbol = get_current_monitor_symbol()
        hour_24, minute = _next_15m_boundary_est()
        contract_name = _format_15m_contract_label(current_symbol, hour_24, minute)
        position_size = get_position_size() or 1
        bankroll_allotment = get_bankroll_allotment() or 0
        side = strike_data.get("side")
        conv_side = "Y" if side == "yes" else "N" if side == "no" else side
        payload = {
            "ticket_id": f"SIM-{uuid.uuid4().hex[:8]}-{int(est_now().timestamp() * 1000)}",
            "status": "pending", "date": today_est().strftime('%Y-%m-%d'),
            "time": est_now().strftime('%H:%M:%S'),
            "symbol": current_symbol, "exchange": "kalshi", "trade_strategy": get_trade_strategy(),
            "contract": contract_name, "strike": strike_data.get("strike"), "side": conv_side,
            "ticker": strike_data.get("ticker"), "prob": strike_data.get("probability"),
            "position": 1,
            "monitor": f"mon_{ctx_user()}_{ctx_mid()}", "bankroll_allotment_total": bankroll_allotment,
            "entry_method": "simulated_15m", "loss_prevention": False, "multiplier": get_current_multiplier(),
            "paper_trade": True, "simulated_trade": True,
        }
        from backend.core.trading_redis_comms import publish_trade_manager_command, use_trading_redis_comms

        r = None
        if use_trading_redis_comms() and publish_trade_manager_command(
            "add_trade",
            payload,
            "auto_entry_supervisor",
            tenant_user_no=ctx_user(),
        ):
            class _Ok:
                status_code = 201
                def json(self):
                    return {}

            r = _Ok()
        if r is None:
            r = requests.post(f"http://localhost:{port}/trades", json=payload, timeout=10)
        if r.status_code == 201:
            log_debug(f"[SIMULATED 15m] Recorded trade id={r.json().get('id')}")
            return True
        log_debug(f"[SIMULATED 15m] trade_manager returned {r.status_code}: {r.text}")
        return False
    except Exception as e:
        log(f"[SIMULATED 15m] Error: {e}")
        return False


def check_simulated_15m_entry_hourly_htc():
    """Model-probe simulated trades: quarter TTC + side-aware 15m probability band only (spike prob_adj on min).

    Runs for **hourly** and **15m** monitors with auto_trade. Does not apply differential, volume,
    max_ask, or Rising Devil ``min_ask_range`` so inserts reflect internal probability behavior even
    when live gates would block.
    """
    import time as _t
    _throttle = getattr(check_simulated_15m_entry_hourly_htc, "_log_ts", 0)
    _now = _t.time()
    _do_log = (_now - _throttle) >= 90
    try:
        settings = get_auto_entry_settings()
        for k in ("min_time", "max_time", "min_probability", "max_probability"):
            if k not in settings:
                if _do_log:
                    log_debug(f"[SIMULATED 15m] skip: missing setting {k}")
                    check_simulated_15m_entry_hourly_htc._log_ts = _now
                return
        min_t = int(float(settings["min_time"]))
        max_t = int(float(settings["max_time"]))
        base_min_p = float(settings["min_probability"])
        max_p = float(settings["max_probability"])
        prob_adj = float(settings.get("prob_adj", 5.00))
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        min_p = base_min_p + prob_adj if spike_alert_active else base_min_p
        data = get_master_strike_table_data_simulated_15m()
        if not data or "strikes" not in data:
            if _do_log:
                log_debug(f"[SIMULATED 15m] skip: no strike ladder for simulated path")
                check_simulated_15m_entry_hourly_htc._log_ts = _now
            return
        ttc = data.get("ttc")
        if ttc is None or not (min_t <= ttc <= max_t):
            if _do_log:
                log_debug(f"[SIMULATED 15m] skip: ttc_15m={ttc} outside window [{min_t},{max_t}]")
                check_simulated_15m_entry_hourly_htc._log_ts = _now
            return
        if _do_log:
            _prob_log = f"[{min_p},{max_p}]"
            if spike_alert_active:
                _prob_log = f"[{min_p},{max_p}] (spike base_min={base_min_p}+{prob_adj})"
            log_debug(
                f"[SIMULATED 15m] in window ttc_15m={ttc} [{min_t},{max_t}] "
                f"scanning {len(data['strikes'])} strikes prob={_prob_log}"
            )
            check_simulated_15m_entry_hourly_htc._log_ts = _now
        # Throttled success: one line per ~15 min so we get ~4/hour that cycle ran
        _ok_ts = getattr(check_simulated_15m_entry_hourly_htc, "_ok_log_ts", 0)
        if (_now - _ok_ts) >= 900:
            log(f"[SIMULATED 15m] cycle OK")
            check_simulated_15m_entry_hourly_htc._ok_log_ts = _now
        current_symbol = get_current_monitor_symbol()
        hour_24, minute = _next_15m_boundary_est()
        contract_name = _format_15m_contract_label(current_symbol, hour_24, minute)
        date_str = today_est().strftime("%Y-%m-%d")
        processed = set()
        for strike in data["strikes"]:
            try:
                active_side = strike.get("active_side")
                if not active_side:
                    continue
                strike_key = _strike_cooldown_key(strike.get("strike"), active_side)
                if strike_key in processed:
                    continue
                processed.add(strike_key)
                if not can_trade_strike_simulated(strike_key):
                    continue
                strike_formatted = format_trade_strike_label(strike.get("strike"), symbol=current_symbol, ticker=strike.get("ticker"))
                check_data = {"strike": strike_formatted, "side": active_side, "ticker": strike.get("ticker"), "date": date_str, "contract": contract_name}
                if is_strike_already_simulated_traded(check_data):
                    continue
                prob = strike.get("probability")
                if prob is None or prob < min_p or prob > max_p:
                    continue
                side = "yes" if active_side == "yes" else "no"
                buy_price = float(strike.get("yes_ask_dollars") or 0) if active_side == "yes" else float(strike.get("no_ask_dollars") or 0)
                diff = strike.get("yes_diff") if active_side == "yes" else strike.get("no_diff")
                sd = {"strike": format_trade_strike_label(strike.get("strike"), symbol=current_symbol, ticker=strike.get("ticker")), "side": side, "ticker": strike.get("ticker"),
                      "buy_price": buy_price, "probability": prob, "diff": diff}
                if trigger_simulated_trade(sd):
                    pass
                elif strike_key in last_simulated_trade_times:
                    del last_simulated_trade_times[strike_key]
            except Exception as e:
                log(f"[SIMULATED 15m] Strike {strike.get('strike')}: {e}")
    except Exception as e:
        log(f"[SIMULATED 15m] Error: {e}")


def check_auto_entry_conditions():
    """Check if auto entry conditions are met and trigger trades - routes to strategy-specific logic"""
    if AES_UNIFIED_POOL:
        try:
            t_pass0 = time.perf_counter()
            if AES_UNIFIED_PROFILE:
                _reset_unified_profile_state()
            if AES_UNIFIED_15M:
                from backend.core.unified_15m_monitors import list_active_15m_monitor_rows

                rows = list_active_15m_monitor_rows()
            elif AES_UNIFIED_HOURLY:
                from backend.core.unified_hourly_monitors import list_active_hourly_monitor_rows

                rows = list_active_hourly_monitor_rows()
            else:
                from backend.core.unified_all_monitors import list_active_unified_monitor_rows

                rows = list_active_unified_monitor_rows()
            by_ladder: Dict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
            for row in rows:
                sym = (row.get("symbol") or "BTC").strip().upper() or "BTC"
                mkt = (row.get("market") or "").strip().lower()
                if mkt not in ("hourly", "15m"):
                    if AES_UNIFIED_15M:
                        mkt = "15m"
                    elif AES_UNIFIED_HOURLY:
                        mkt = "hourly"
                    else:
                        mkt = "hourly"
                by_ladder[(sym, mkt)].append((row["user_number"], row["monitor_id"]))
            for (sym, mkt) in sorted(by_ladder.keys()):
                bindings = by_ladder[(sym, mkt)]
                tg0 = time.perf_counter()
                snap = _fetch_master_strike_table_data(sym, mkt)
                if AES_UNIFIED_PROFILE:
                    _unified_profile_state["group_prefetch_sec"] += time.perf_counter() - tg0
                if snap:
                    token = _aes_unified_tick_context.set({"symbol": sym, "market": mkt, "data": snap})
                    try:
                        for u, m in bindings:
                            tw0 = time.perf_counter()
                            with aes_monitor_bind(u, m):
                                ms, mm = get_current_monitor_symbol_and_market()
                                if ms != sym or mm != mkt:
                                    inner = _aes_unified_tick_context.set(None)
                                    try:
                                        _check_auto_entry_conditions_impl()
                                    finally:
                                        _aes_unified_tick_context.reset(inner)
                                else:
                                    _check_auto_entry_conditions_impl()
                            if AES_UNIFIED_PROFILE:
                                _unified_profile_state["monitor_wall_sec"].append((m, time.perf_counter() - tw0))
                    finally:
                        _aes_unified_tick_context.reset(token)
                else:
                    for u, m in bindings:
                        tw0 = time.perf_counter()
                        with aes_monitor_bind(u, m):
                            _check_auto_entry_conditions_impl()
                        if AES_UNIFIED_PROFILE:
                            _unified_profile_state["monitor_wall_sec"].append((m, time.perf_counter() - tw0))
            if AES_UNIFIED_PROFILE:
                elapsed = time.perf_counter() - t_pass0
                wall = _unified_profile_state["monitor_wall_sec"]
                wall_sum = sum(w for _, w in wall)
                log(
                    "[AES PROFILE] unified_pass=%.3fs groups=%s prefetch=%.3fs get_master_extra=%.3fs "
                    "master_hits=%s trigger_trade=%.3fs monitor_wall_sum=%.3fs detail=%s"
                    % (
                        elapsed,
                        len(by_ladder),
                        _unified_profile_state["group_prefetch_sec"],
                        _unified_profile_state["master_fetch_sec"],
                        _unified_profile_state["master_cache_hits"],
                        _unified_profile_state["trigger_trade_sec"],
                        wall_sum,
                        [(mid, round(sec, 3)) for mid, sec in wall],
                    )
                )
        except Exception as e:
            import traceback

            if AES_UNIFIED_ALL:
                pool_n = "unified"
            else:
                pool_n = "15m" if AES_UNIFIED_15M else "hourly"
            log(f"[AUTO ENTRY] ❌ Error checking entry conditions ({pool_n} pool): {e}")
            log(f"[AUTO ENTRY] ❌ Traceback: {traceback.format_exc()}")
        return
    _check_auto_entry_conditions_impl()


def _check_auto_entry_conditions_impl():
    """Single-monitor check (or one bound monitor inside the 15m pool)."""
    try:
        strategy = get_trade_strategy()
        # Simulated model-probe path: hourly and 15m monitors with auto_trade (Breakout/Contain excluded)
        try:
            import time as _t
            _, market = get_current_monitor_symbol_and_market()
            mkt_l = (market or "").strip().lower()
            is_hourly = mkt_l == "hourly"
            is_15m = mkt_l == "15m"
            auto_on = is_auto_trade_enabled()
            # Simulated 15m: exclude Momentum Breakout/Contain for testing; may re-include later
            skip_sim = strategy in ("Momentum Breakout", "Momentum Contain")
            if (is_hourly or is_15m) and auto_on and not skip_sim:
                if not hasattr(check_auto_entry_conditions, "_sim_log_ts"):
                    check_auto_entry_conditions._sim_log_ts = 0
                if (_t.time() - check_auto_entry_conditions._sim_log_ts) >= 90:
                    log_debug(
                        f"[SIMULATED 15m] running ({'hourly' if is_hourly else '15m'} monitor + auto_trade)"
                    )
                    check_auto_entry_conditions._sim_log_ts = _t.time()
                # Only one simulated scan at a time to avoid duplicate inserts (race on duplicate check)
                if _simulated_15m_lock.acquire(blocking=False):
                    try:
                        check_simulated_15m_entry_hourly_htc()
                    finally:
                        _simulated_15m_lock.release()
        except Exception as sim_e:
            log(f"[SIMULATED 15m] {sim_e}")

        # ALWAYS check spike alert conditions first (even during closed hours) to monitor momentum spikes
        check_spike_alert_conditions()
        
        # MARKET HOURS CHECK: Kalshi markets closed 00:00-08:00 EST
        # Skip trade entry during closed hours, but spike monitoring continues above
        # COMMENTED OUT: Time restriction disabled - auto_entry_supervisor can now find entries during these hours
        # now_est = est_now()
        # current_hour = now_est.hour
        # if 0 <= current_hour < 8:  # Between midnight and 8am EST
        #     return  # Skip trade entry checks during closed hours (spike monitoring already done)

        if strategy == "Momentum Scalp":
            check_auto_entry_conditions_momentum_scalp()
        elif strategy == "Momentum Reversal":
            check_auto_entry_conditions_momentum_reversal()
        elif strategy == "Reverse HTC":
            check_auto_entry_conditions_reverse_htc()
        elif strategy == "Momentum Breakout":
            check_auto_entry_conditions_momentum_breakout()
        elif strategy == "Momentum Contain":
            check_auto_entry_conditions_momentum_contain()
        elif strategy == "Rising Devil":
            check_auto_entry_conditions_rising_devil()
        else:
            # Default to Hourly HTC (including fallback)
            check_auto_entry_conditions_hourly_htc()
    except Exception as e:
        import traceback
        log(f"[AUTO ENTRY] ❌ Error checking entry conditions: {e}")
        log(f"[AUTO ENTRY] ❌ Traceback: {traceback.format_exc()}")

def check_auto_entry_conditions_hourly_htc():
    """Check if auto entry conditions are met and trigger trades for Hourly HTC strategy"""
    try:
        # Get strike table data directly
        
        # Check spike alert conditions first
        check_spike_alert_conditions()

        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)

        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (no longer blocks - uses prob_adj to adjust probability instead)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        if not auto_trade_enabled:
            _aes_indicator_bucket().update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": spike_alert_active,
                "current_ttc": 0,
                "last_updated": est_now().isoformat()
            })
            # Broadcast indicator state change
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings - NO DEFAULTS
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_probability", "max_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY] ❌ Missing required settings: {missing_settings}")
            log(f"[AUTO ENTRY] Cannot proceed without complete settings configuration")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        base_min_probability = settings["min_probability"]
        max_probability = settings["max_probability"]
        min_differential = settings["min_differential"]
        
        # Apply prob_adj adjustment during spike alert cooldown
        prob_adj = settings.get("prob_adj", 5.00)  # Default to 5.00 if not set
        if spike_alert_active:
            min_probability = base_min_probability + prob_adj
            log_debug(f"[AUTO ENTRY] 📊 Using adjusted probability: {base_min_probability:.2f} + {prob_adj:.2f} = {min_probability:.2f}% (spike cooldown active)")
        else:
            min_probability = base_min_probability
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window
        # Note: spike_alert_active no longer blocks scanning - it adjusts probability instead
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window)
        
        # Update indicator state for frontend
        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": spike_alert_active,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        if not ttc_within_window:
            # Log occasionally when TTC is outside window (INFO so operators see it without DEBUG)
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_ttc_log'):
                check_auto_entry_conditions_hourly_htc.last_ttc_log = 0
            if current_time - check_auto_entry_conditions_hourly_htc.last_ttc_log >= 300:  # Log every 5 minutes
                log(
                    f"[AUTO ENTRY] ⏸️ Hourly HTC: TTC outside window | ttc={current_ttc}s "
                    f"allowed={min_time}-{max_time}s (no scans until TTC is in range)"
                )
                check_auto_entry_conditions_hourly_htc.last_ttc_log = current_time
            return
        
        # Note: spike_alert_active no longer blocks trades - probability is adjusted instead (see min_probability calculation above)
        
        if not strike_table_data:
            # Log occasionally if strike table data is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_strike_table_log'):
                check_auto_entry_conditions_hourly_htc.last_strike_table_log = 0
            if current_time - check_auto_entry_conditions_hourly_htc.last_strike_table_log >= 60:  # Log every 60 seconds
                _sym, _mkt = get_current_monitor_symbol_and_market()
                _tn = get_strike_table_name(_sym, _mkt)
                _ex = _strike_data_exchange_key()
                if (_mkt or "").strip().lower() == "15m":
                    _mh = "live_data.market_kalshi_15m"
                    _wd = "market_watchdog_ws_kalshi_15m"
                    _sg = "strike_table_generator_ws_15m"
                else:
                    _mh = "live_data.market_kalshi_hourly"
                    _wd = "market_watchdog_ws_kalshi_hourly"
                    _sg = "strike_table_generator_ws_hourly"
                log(
                    f"[AUTO ENTRY] ⚠️ No strike ladder in live_data.{_tn} for exchange={_ex} symbol={_sym.upper()}. "
                    f"Upstream: {_mh} must have event_ticker ({_wd}); then {_sg} writes rows. "
                    f"Check those logs for 'No event_ticker' or rollover gaps."
                )
                check_auto_entry_conditions_hourly_htc.last_strike_table_log = current_time
            return
        
        if "strikes" not in strike_table_data:
            # Log occasionally if strikes array is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_strikes_missing_log'):
                check_auto_entry_conditions_hourly_htc.last_strikes_missing_log = 0
            if current_time - check_auto_entry_conditions_hourly_htc.last_strikes_missing_log >= 60:  # Log every 60 seconds
                log(f"[AUTO ENTRY] ⚠️ Strike table data missing 'strikes' array")
                check_auto_entry_conditions_hourly_htc.last_strikes_missing_log = current_time
            return
        
        # Log that we're scanning strikes (only log occasionally to avoid spam)
        import time
        current_time = time.time()
        if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_scan_log'):
            check_auto_entry_conditions_hourly_htc.last_scan_log = 0
        if current_time - check_auto_entry_conditions_hourly_htc.last_scan_log >= 60:  # Log every 60 seconds
            strike_count = len(strike_table_data.get("strikes", []))
            prob_display = f"{min_probability:.2f}-{max_probability}%"
            if spike_alert_active:
                prob_display += f" (adjusted: {base_min_probability:.2f}+{prob_adj:.2f})"
            log_debug(f"[AUTO ENTRY] 🔍 Scanning {strike_count} strikes | TTC: {current_ttc}s | Window: {min_time}-{max_time}s | Prob: {prob_display}")
            check_auto_entry_conditions_hourly_htc.last_scan_log = current_time
        
        # Process each strike ONCE
        processed_strikes = set()  # Prevent duplicate processing
        
        for i, strike in enumerate(strike_table_data["strikes"]):
            try:
                # Use active_side for strike_key generation
                active_side = strike.get('active_side')
                if not active_side:
                    continue
                    
                strike_key = _strike_cooldown_key(strike.get("strike"), active_side)
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                
                processed_strikes.add(strike_key)
                
                # STEP 1: ATOMIC cooldown check
                if not can_trade_strike(strike_key):
                    continue
                
                # STEP 2: Check if we already have an active trade on this strike
                strike_data_for_check = {
                    "strike": strike.get("strike"),
                    "side": active_side,
                    "ticker": strike.get("ticker"),
                }

                if is_strike_already_traded(strike_data_for_check):
                    continue

                # STEP 3: Check probability window (min_probability <= prob <= max_probability)
                prob = strike.get('probability')
                if prob is None or prob < min_probability or prob > max_probability:
                    continue
                
                # STEP 4: Check differential threshold (if applicable)
                if min_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff < (min_differential - 0.5):
                        continue
                
                # STEP 4.5: Check max differential threshold (if applicable)
                max_differential = settings.get("max_differential")
                if max_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff > max_differential:
                        continue
                
                # STEP 5: Check volume threshold
                min_volume = settings.get("min_volume", 1000)
                volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
                if volume < min_volume:
                    continue
                
                # STEP 6: Check max ask price threshold using _dollars values
                max_ask = settings.get("max_ask", 0.9800)
                yes_ask_dollars = strike.get('yes_ask_dollars')
                no_ask_dollars = strike.get('no_ask_dollars')
                if not yes_ask_dollars or not no_ask_dollars:
                    continue
                max_ask_price = max(float(yes_ask_dollars), float(no_ask_dollars))
                max_ask_limit = float(max_ask) if max_ask < 1 else float(max_ask) / 100.0
                if max_ask_price > max_ask_limit:
                    continue
                
                # STEP 5: Determine buy price based on active_side using subpenny precision
                if active_side == 'yes':
                    side = 'yes'
                    # Use yes_ask_dollars directly (no conversion needed)
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        log(f"⚠️ Missing yes_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(yes_ask_dollars)
                elif active_side == 'no':
                    side = 'no'
                    # Use no_ask_dollars directly (no conversion needed)
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        log(f"⚠️ Missing no_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(no_ask_dollars)
                else:
                    continue
                
                # STEP 6: Get diff value for the active side
                diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                
                # STEP 7: Prepare strike data for trade trigger
                strike_data = {
                    'strike': format_trade_strike_label(strike.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike.get("ticker")),
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob,
                    'diff': diff
                }
                
                # STEP 8: Check if strike is already traded
                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY] ⏸️ Skipping {strike_key} - already has open/pending trade")
                    continue
                
                # STEP 9: Trigger the trade
                log(f"[AUTO ENTRY] 🚀 TRIGGERING TRADE | {strike_key} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Ticker: {strike.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY] ✅ TRADE SUCCESSFUL | {strike_key} | Trade triggered and sent to trade_manager")
                else:
                    log(f"[AUTO ENTRY] ❌ TRADE FAILED | {strike_key} | Failed to trigger trade")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY HTC] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY HTC] Error checking auto entry conditions: {e}")


def check_auto_entry_conditions_rising_devil():
    """Rising Devil: same differential gates as Hourly HTC (min with -0.5 cushion, optional max), plus min_ask_range on the active side."""
    try:
        check_spike_alert_conditions()

        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)

        auto_trade_enabled = is_auto_trade_enabled()
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)

        if not auto_trade_enabled:
            _aes_indicator_bucket().update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": spike_alert_active,
                "current_ttc": 0,
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return

        settings = get_auto_entry_settings()
        required_settings = [
            "min_time",
            "max_time",
            "min_probability",
            "max_probability",
            "min_differential",
            "min_ask_range",
        ]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY RISING DEVIL] ❌ monitor={ctx_mid()} missing required settings: {missing_settings}")
            return

        min_differential = settings["min_differential"]
        max_differential = settings.get("max_differential")

        min_ask_range = settings.get("min_ask_range")
        if min_ask_range is None or (isinstance(min_ask_range, (int, float)) and float(min_ask_range) <= 0):
            import time as _t
            rl = _rising_devil_ratelimit()
            now = _t.time()
            if now - rl["thr"] >= 300:
                log(
                    f"[AUTO ENTRY RISING DEVIL] ⏸️ monitor={ctx_mid()} min_ask_range unset or <= 0; "
                    "configure monitor to enable entries"
                )
                rl["thr"] = now
            _aes_indicator_bucket().update({
                "enabled": True,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": spike_alert_active,
                "current_ttc": get_current_ttc(),
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return

        min_ask_range = float(min_ask_range)

        min_time = settings["min_time"]
        max_time = settings["max_time"]
        base_min_probability = settings["min_probability"]
        max_probability = settings["max_probability"]

        prob_adj = settings.get("prob_adj", 5.00)
        if spike_alert_active:
            min_probability = base_min_probability + prob_adj
            log_debug(f"[AUTO ENTRY RISING DEVIL] 📊 Adjusted probability floor: {base_min_probability:.2f} + {prob_adj:.2f} = {min_probability:.2f}%")
        else:
            min_probability = base_min_probability

        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        scanning_active = (auto_trade_enabled and service_healthy and ttc_within_window)

        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": spike_alert_active,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat()
        })
        broadcast_auto_entry_indicator_change()

        if not ttc_within_window:
            import time as _t
            rl = _rising_devil_ratelimit()
            now = _t.time()
            if now - rl["ttc_out"] >= 300:
                log(
                    f"[AUTO ENTRY RISING DEVIL] ⏸️ monitor={ctx_mid()} TTC outside window | "
                    f"ttc={current_ttc}s allowed={min_time}-{max_time}s"
                )
                rl["ttc_out"] = now
            return

        if not strike_table_data or "strikes" not in strike_table_data:
            import time as _t
            rl = _rising_devil_ratelimit()
            no = _t.time()
            if no - rl["no_ladder"] >= 120:
                log(
                    f"[AUTO ENTRY RISING DEVIL] ⚠️ monitor={ctx_mid()} no ladder snapshot "
                    "(strike_table_data missing or no strikes key)"
                )
                rl["no_ladder"] = no
            return

        processed_strikes = set()
        import time as _t
        strikes_list = strike_table_data.get("strikes", []) or []
        strike_count = len(strikes_list)
        rl_scan = _rising_devil_ratelimit()
        now_scan = _t.time()
        if now_scan - rl_scan["scan"] >= 60:
            sym = get_current_monitor_symbol() or "?"
            max_part = (
                f" max_diff<={max_differential:.2f}"
                if max_differential is not None
                else ""
            )
            log(
                f"[AUTO ENTRY RISING DEVIL] 🔍 monitor={ctx_mid()} scanning | symbol={sym} "
                f"strikes={strike_count} ttc={current_ttc}s window={min_time}-{max_time}s "
                f"min_ask_range>={min_ask_range:.4f} min_diff>={float(min_differential) - 0.5:.2f}{max_part}"
            )
            rl_scan["scan"] = now_scan

        with_active_side = 0
        active_side_null_range = 0

        for strike in strikes_list:
            try:
                active_side = strike.get('active_side')
                if not active_side:
                    continue

                with_active_side += 1
                _as = str(active_side).lower()
                if _as == "yes" and strike.get("yes_ask_range_15m") is None:
                    active_side_null_range += 1
                elif _as == "no" and strike.get("no_ask_range_15m") is None:
                    active_side_null_range += 1

                strike_key = _strike_cooldown_key(strike.get("strike"), active_side)

                if strike_key in processed_strikes:
                    continue
                processed_strikes.add(strike_key)

                if not can_trade_strike(strike_key):
                    continue

                strike_data_for_check = {
                    "strike": strike.get("strike"),
                    "side": active_side,
                    "ticker": strike.get("ticker"),
                }
                if is_strike_already_traded(strike_data_for_check):
                    continue

                prob = strike.get('probability')
                if prob is None or prob < min_probability or prob > max_probability:
                    continue

                diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                if min_differential is not None:
                    if diff is None or diff < (min_differential - 0.5):
                        continue
                if max_differential is not None:
                    if diff is None or diff > max_differential:
                        continue

                min_volume = settings.get("min_volume", 1000)
                volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
                if volume < min_volume:
                    continue

                max_ask = settings.get("max_ask", 0.9800)
                yes_ask_dollars = strike.get('yes_ask_dollars')
                no_ask_dollars = strike.get('no_ask_dollars')
                if not yes_ask_dollars or not no_ask_dollars:
                    continue
                max_ask_price = max(float(yes_ask_dollars), float(no_ask_dollars))
                max_ask_limit = float(max_ask) if max_ask < 1 else float(max_ask) / 100.0
                if max_ask_price > max_ask_limit:
                    continue

                side_lower = str(active_side).lower()
                if side_lower == 'yes':
                    rng = strike.get('yes_ask_range_15m')
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        continue
                    buy_price = float(yes_ask_dollars)
                    side = 'yes'
                elif side_lower == 'no':
                    rng = strike.get('no_ask_range_15m')
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        continue
                    buy_price = float(no_ask_dollars)
                    side = 'no'
                else:
                    continue

                if rng is None:
                    continue
                try:
                    rng_f = float(rng)
                except (TypeError, ValueError):
                    continue
                if rng_f < min_ask_range:
                    continue

                strike_data = {
                    'strike': format_trade_strike_label(strike.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike.get("ticker")),
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob,
                    'diff': diff
                }

                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY RISING DEVIL] ⏸️ monitor={ctx_mid()} Skipping {strike_key} - already traded")
                    continue

                log(
                    f"[AUTO ENTRY RISING DEVIL] 🚀 monitor={ctx_mid()} TRIGGERING | {strike_key} | range={rng_f:.4f} | "
                    f"Prob: {prob}% | Buy: ${buy_price:.2f} | Ticker: {strike.get('ticker')}"
                )
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY RISING DEVIL] ✅ monitor={ctx_mid()} TRADE SUCCESSFUL | {strike_key}")
                else:
                    log(f"[AUTO ENTRY RISING DEVIL] ❌ monitor={ctx_mid()} TRADE FAILED | {strike_key}")
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]

            except Exception as e:
                log(f"[AUTO ENTRY RISING DEVIL] monitor={ctx_mid()} Error processing strike {strike.get('strike')}: {e}")

        if (
            with_active_side > 0
            and active_side_null_range == with_active_side
        ):
            import time as _t_nr
            rl_nr = _rising_devil_ratelimit()
            tn = _t_nr.time()
            if tn - rl_nr["no_range"] >= 300:
                log(
                    f"[AUTO ENTRY RISING DEVIL] ⚠️ monitor={ctx_mid()} every active-side strike lacks "
                    f"yes/no_ask_range_15m ({with_active_side} rows); check ladder fetch / DB"
                )
                rl_nr["no_range"] = tn

    except Exception as e:
        log(f"[AUTO ENTRY RISING DEVIL] ❌ monitor={ctx_mid()} Error: {e}")


def check_auto_entry_conditions_reverse_htc():
    """Check if auto entry conditions are met and trigger trades for Reverse HTC strategy
    
    Reverse HTC activates when momentum spike is detected (opposite of Hourly HTC).
    It uses the same entry logic as Hourly HTC but enters with the OPPOSITE side.
    """
    try:
        # Get strike table data directly
        
        # Check spike alert conditions first
        check_spike_alert_conditions()

        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)

        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (REQUIRED for Reverse HTC to activate)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        if not auto_trade_enabled:
            _aes_indicator_bucket().update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": spike_alert_active,
                "current_ttc": 0,
                "last_updated": est_now().isoformat()
            })
            # Broadcast indicator state change
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings - NO DEFAULTS
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_probability", "max_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY REVERSE HTC] ❌ Missing required settings: {missing_settings}")
            log(f"[AUTO ENTRY REVERSE HTC] Cannot proceed without complete settings configuration")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_probability = settings["min_probability"]
        max_probability = settings["max_probability"]
        min_differential = settings["min_differential"]
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window + spike alert active (REQUIRED for Reverse HTC)
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          spike_alert_active)  # SPIKE ALERT REQUIRED for Reverse HTC
        
        # Update indicator state for frontend
        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": spike_alert_active,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        if not ttc_within_window:
            # Log occasionally when TTC is outside window
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_ttc_log'):
                check_auto_entry_conditions_reverse_htc.last_ttc_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_ttc_log >= 300:  # Log every 5 minutes
                log_debug(f"[AUTO ENTRY REVERSE HTC] ⏸️ TTC outside window: {current_ttc}s (window: {min_time}-{max_time}s)")
                check_auto_entry_conditions_reverse_htc.last_ttc_log = current_time
            return
        
        # SPIKE ALERT CHECK - Reverse HTC REQUIRES spike alert to be active
        if not spike_alert_active:
            log(f"[AUTO ENTRY REVERSE HTC] ⏸️ SPIKE ALERT NOT ACTIVE - Reverse HTC requires momentum spike to activate")
            return
        
        # BRACKET CHECK - Reverse HTC should only enter trades until a bracket is formed
        # A bracket is: one Y trade and one N trade with strikes within 2 strike tiers of each other
        # Use contract_label from _LAST_MONITOR_STATE (same format as what trade_manager stores after truncation)
        current_contract = _LAST_MONITOR_STATE.get("contract")
        strike_tier = strike_table_data.get("strike_tier") if strike_table_data else None
        if strike_tier:
            try:
                strike_tier = int(strike_tier)
            except (ValueError, TypeError):
                strike_tier = None
        
        if has_bracket_for_cycle(current_contract, strike_tier):
            # Log occasionally to avoid spam
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_bracket_log'):
                check_auto_entry_conditions_reverse_htc.last_bracket_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_bracket_log >= 300:  # Log every 5 minutes
                bracket_distance = 2 * strike_tier if strike_tier else "unknown"
                log(f"[AUTO ENTRY REVERSE HTC] ⏸️ BRACKET FORMED - No further entries for cycle {current_contract} (bracket distance: {bracket_distance})")
                check_auto_entry_conditions_reverse_htc.last_bracket_log = current_time
            return
        
        if not strike_table_data:
            # Log occasionally if strike table data is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_strike_table_log'):
                check_auto_entry_conditions_reverse_htc.last_strike_table_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_strike_table_log >= 60:  # Log every 60 seconds
                log(f"[AUTO ENTRY REVERSE HTC] ⚠️ No strike table data available")
                check_auto_entry_conditions_reverse_htc.last_strike_table_log = current_time
            return
        
        if "strikes" not in strike_table_data:
            # Log occasionally if strikes array is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_strikes_missing_log'):
                check_auto_entry_conditions_reverse_htc.last_strikes_missing_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_strikes_missing_log >= 60:  # Log every 60 seconds
                log(f"[AUTO ENTRY REVERSE HTC] ⚠️ Strike table data missing 'strikes' array")
                check_auto_entry_conditions_reverse_htc.last_strikes_missing_log = current_time
            return
        
        # Log that we're scanning strikes (only log occasionally to avoid spam)
        import time
        current_time = time.time()
        if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_scan_log'):
            check_auto_entry_conditions_reverse_htc.last_scan_log = 0
        if current_time - check_auto_entry_conditions_reverse_htc.last_scan_log >= 60:  # Log every 60 seconds
            strike_count = len(strike_table_data.get("strikes", []))
            log_debug(f"[AUTO ENTRY REVERSE HTC] 🔍 Scanning {strike_count} strikes | TTC: {current_ttc}s | Window: {min_time}-{max_time}s | Prob: {min_probability}-{max_probability}% | SPIKE ACTIVE")
            check_auto_entry_conditions_reverse_htc.last_scan_log = current_time
        
        # Process each strike ONCE
        processed_strikes = set()  # Prevent duplicate processing
        
        for i, strike in enumerate(strike_table_data["strikes"]):
            try:
                # Use active_side for strike_key generation (EXACT SAME AS HOURLY HTC)
                active_side = strike.get('active_side')
                if not active_side:
                    continue
                    
                strike_key = _strike_cooldown_key(strike.get("strike"), active_side)
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                
                processed_strikes.add(strike_key)
                
                # STEP 1: ATOMIC cooldown check (EXACT SAME AS HOURLY HTC)
                if not can_trade_strike(strike_key):
                    continue
                
                # STEP 1.5: BRACKET CHECK BEFORE EACH TRADE - Prevent entering if bracket already exists
                # Check bracket before triggering trade to prevent third entry
                # Use current_contract (set at function start) which matches database format
                if current_contract and has_bracket_for_cycle(current_contract, strike_tier):
                    bracket_distance = 2 * strike_tier if strike_tier else "unknown"
                    log(f"[AUTO ENTRY REVERSE HTC] ⏸️ BRACKET EXISTS - Skipping strike {strike_key} for cycle {current_contract} (bracket distance: {bracket_distance})")
                    continue  # Skip this strike if bracket already exists
                
                # STEP 2: Check if we already have an active trade on this strike
                # REVERSE HTC: Check opposite side (since we'll be trading opposite side)
                opposite_side = 'no' if active_side == 'yes' else 'yes'
                strike_data_for_check = {
                    'strike': strike.get('strike'),
                    'side': opposite_side,
                    'ticker': strike.get('ticker')
                }
                
                if is_strike_already_traded(strike_data_for_check):
                    continue
                
                # STEP 3: Check probability window (EXACT SAME AS HOURLY HTC)
                prob = strike.get('probability')
                if prob is None or prob < min_probability or prob > max_probability:
                    continue
                
                # STEP 4: Differential gates on the executed leg (opposite_side), not the signal side
                _diff_ok, _diff_reason = _auto_entry_differential_allowed(settings, opposite_side, strike)
                if not _diff_ok:
                    log_debug(
                        f"[AUTO ENTRY REVERSE HTC] skip {strike_key} executed={opposite_side} {_diff_reason}"
                    )
                    continue
                
                # STEP 5: Check volume threshold (EXACT SAME AS HOURLY HTC)
                min_volume = settings.get("min_volume", 1000)
                volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
                if volume < min_volume:
                    continue
                
                # STEP 6: Check max ask price threshold (EXACT SAME AS HOURLY HTC)
                max_ask = settings.get("max_ask", 0.9800)
                yes_ask_dollars = strike.get('yes_ask_dollars')
                no_ask_dollars = strike.get('no_ask_dollars')
                if not yes_ask_dollars or not no_ask_dollars:
                    continue
                max_ask_price = max(float(yes_ask_dollars), float(no_ask_dollars))
                max_ask_limit = float(max_ask) if max_ask < 1 else float(max_ask) / 100.0
                if max_ask_price > max_ask_limit:
                    continue
                
                # STEP 7: Determine buy price based on active_side (EXACT SAME AS HOURLY HTC)
                if active_side == 'yes':
                    side = 'yes'
                    # Use yes_ask_dollars directly (no conversion needed)
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        log(f"⚠️ Missing yes_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(yes_ask_dollars)
                elif active_side == 'no':
                    side = 'no'
                    # Use no_ask_dollars directly (no conversion needed)
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        log(f"⚠️ Missing no_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(no_ask_dollars)
                else:
                    continue
                
                # STEP 8: Get diff value for the active side (EXACT SAME AS HOURLY HTC)
                diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                
                # REVERSE HTC: ONLY DIFFERENCE - flip the side when submitting the order
                # (opposite_side was already calculated at Step 2)
                opposite_buy_price = float(strike.get('no_ask_dollars') if opposite_side == 'no' else strike.get('yes_ask_dollars'))
                opposite_diff = strike.get('no_diff') if opposite_side == 'no' else strike.get('yes_diff')
                
                # STEP 9: Prepare strike data for trade trigger (using OPPOSITE side - ONLY DIFFERENCE)
                strike_data = {
                    'strike': format_trade_strike_label(strike.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike.get("ticker")),
                    'side': opposite_side,
                    'ticker': strike.get('ticker'),
                    'buy_price': opposite_buy_price,
                    'probability': prob,
                    'diff': opposite_diff
                }
                
                # STEP 10: Trigger the trade (with opposite side - ONLY DIFFERENCE)
                log(f"[AUTO ENTRY REVERSE HTC] 🚀 TRIGGERING TRADE (OPPOSITE SIDE) | {strike_key} | Active Side: {active_side} → Trading: {opposite_side} | Prob: {prob}% | Buy Price: ${opposite_buy_price:.2f} | Ticker: {strike.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY REVERSE HTC] ✅ TRADE SUCCESSFUL | {strike_key} | Trade triggered and sent to trade_manager")
                else:
                    log(f"[AUTO ENTRY REVERSE HTC] ❌ TRADE FAILED | {strike_key} | Failed to trigger trade")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY REVERSE HTC] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY REVERSE HTC] Error checking auto entry conditions: {e}")

def check_auto_entry_conditions_momentum_breakout():
    """Check if auto entry conditions are met and trigger trades for Momentum Breakout strategy
    
    Momentum Breakout activates when momentum spike is detected (same as Reverse HTC).
    When activated, it immediately opens TWO trades:
    - YES trade at strike immediately above the money line
    - NO trade at strike immediately below the money line
    Uses strike_tier to find the correct strikes.
    After entering these two trades, it opens no more trades and holds until expiration.
    """
    try:
        monitor_key = ctx_ident()
        state = _momentum_breakout_cycle_state_by_monitor.setdefault(
            monitor_key, {"entered": False, "contract": None}
        )
        # Get strike table data
        check_spike_alert_conditions()
        
        strike_table_data = get_master_strike_table_data()
        
        # Failsafe: Skip 5pm cycles (daily 5pm cycles are excluded)
        # Check hour_24 directly (17 = 5pm) - most reliable method
        if strike_table_data:
            symbol = (strike_table_data or {}).get("symbol") or MONITOR_SYMBOL or "BTC"
            market_title = (strike_table_data or {}).get("market_title")
            event_ticker = (strike_table_data or {}).get("event_ticker")
            
            # Resolve the hour directly to check for 5pm (hour_24 == 17)
            _, hour_24 = _resolve_event_time(symbol, market_title, event_ticker)
            if hour_24 == 17:  # 5pm in 24-hour format
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ Skipping 5pm cycle (hour_24={hour_24})")
                return
            
            # Also check contract label and market_title as additional failsafe
            current_contract = _LAST_MONITOR_STATE.get("contract")
            contract_to_check = current_contract or market_title or ""
            if contract_to_check and "5pm" in contract_to_check.lower():
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ Skipping 5pm cycle (contract check): {contract_to_check}")
                return
            
            update_monitor_current_state(strike_table_data)
        
        # Get current contract from monitor state (after update)
        current_contract = _LAST_MONITOR_STATE.get("contract")
        
        # Reset trades_entered flag when a new cycle starts (contract changes)
        if current_contract and current_contract != state.get("contract"):
            prev_contract = state.get("contract")
            state["entered"] = False
            if prev_contract:
                log(
                    f"[AUTO ENTRY MOMENTUM BREAKOUT] 🔄 New cycle detected: "
                    f"{prev_contract} → {current_contract} - resetting entry flag"
                )
            state["contract"] = current_contract
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (REQUIRED for Momentum Breakout to activate)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        if not auto_trade_enabled:
            _aes_indicator_bucket().update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": spike_alert_active,
                "current_ttc": 0,
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window + spike alert active
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          spike_alert_active)
        
        # Update indicator state for frontend
        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": spike_alert_active,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        if not ttc_within_window:
            return
        
        # SPIKE ALERT CHECK - Momentum Breakout REQUIRES spike alert to be active
        if not spike_alert_active:
            return
        
        # If we've already entered trades for this spike activation, do nothing
        if state.get("entered"):
            return

        if not strike_table_data:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ No strike table data available")
            return
        
        current_price = strike_table_data.get("current_price")
        strike_tier = strike_table_data.get("strike_tier")
        
        if current_price is None or strike_tier is None:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Missing current_price or strike_tier")
            return
        
        try:
            strike_tier = int(strike_tier)
        except (ValueError, TypeError):
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Invalid strike_tier: {strike_tier}")
            return
        if strike_tier <= 0:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Invalid strike_tier (<=0): {strike_tier}")
            return

        if has_bracket_for_cycle(contract=current_contract, strike_tier=strike_tier):
            state["entered"] = True
            return
        
        # Find the actual available strikes from the strike table
        # We need the strike immediately above and immediately below the current price
        strikes = strike_table_data.get("strikes", [])
        strike_above_data = None
        strike_below_data = None
        
        # Find the closest strike above current price (>= current_price)
        closest_above = None
        closest_above_distance = float('inf')
        
        # Find the closest strike below current price (<= current_price)
        closest_below = None
        closest_below_distance = float('inf')
        
        for strike in strikes:
            strike_value = strike.get("strike")
            if strike_value is None:
                continue
            
            # Check if this strike is above the current price
            if strike_value >= current_price:
                distance = strike_value - current_price
                if distance < closest_above_distance:
                    closest_above_distance = distance
                    closest_above = strike
            
            # Check if this strike is below the current price
            if strike_value <= current_price:
                distance = current_price - strike_value
                if distance < closest_below_distance:
                    closest_below_distance = distance
                    closest_below = strike
        
        strike_above_data = closest_above
        strike_below_data = closest_below
        
        # Log the found strikes for debugging
        above_strike = strike_above_data.get('strike') if strike_above_data else None
        below_strike = strike_below_data.get('strike') if strike_below_data else None
        below_str = f"${below_strike:,.0f}" if below_strike else "N/A"
        above_str = f"${above_strike:,.0f}" if above_strike else "N/A"
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] 🎯 Current price: ${current_price:,.2f}, Strike tier: ${strike_tier:,}, Found below: {below_str}, Found above: {above_str}")
        
        yes_exists, no_exists = _momentum_breakout_legs_in_db(strike_above_data, strike_below_data)
        if yes_exists and no_exists:
            log(
                f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ Both legs already in flight (YES @ ${strike_above_data.get('strike') if strike_above_data else 0:,.0f}, "
                f"NO @ ${strike_below_data.get('strike') if strike_below_data else 0:,.0f}) — bracket complete"
            )
            state["entered"] = True
            return
        
        # Enter the two trades
        trades_entered = 0
        
        # Enter YES trade at strike above
        if strike_above_data and not yes_exists:
            yes_ask_dollars = strike_above_data.get('yes_ask_dollars')
            if yes_ask_dollars:
                _diff_ok, _diff_reason = _auto_entry_differential_allowed(settings, "yes", strike_above_data)
                if not _diff_ok:
                    log(
                        f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ YES leg blocked by differential gate ({_diff_reason}) "
                        f"strike=${strike_above_data.get('strike'):,.0f}"
                    )
                else:
                    strike_data = {
                        'strike': format_trade_strike_label(strike_above_data.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike_above_data.get("ticker")),
                        'side': 'yes',
                        'ticker': strike_above_data.get('ticker'),
                        'buy_price': float(yes_ask_dollars),
                        'probability': strike_above_data.get('probability'),
                        'diff': strike_above_data.get('yes_diff')
                    }
                    log(f"[AUTO ENTRY MOMENTUM BREAKOUT] 🚀 TRIGGERING YES TRADE | Strike: ${strike_above_data.get('strike'):,.0f} | Buy Price: ${float(yes_ask_dollars):.2f} | Ticker: {strike_above_data.get('ticker')}")
                    if trigger_auto_entry_trade(strike_data):
                        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ✅ YES TRADE SUCCESSFUL | Strike: ${strike_above_data.get('strike'):,.0f}")
                        trades_entered += 1
                    else:
                        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ YES TRADE FAILED | Strike: ${strike_above_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Missing yes_ask_dollars for strike above ${strike_above_data.get('strike'):,.0f}")
        elif strike_above_data and yes_exists:
            log(
                f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏭️ Skipping YES (already in flight) at ${strike_above_data.get('strike'):,.0f} — will try other leg if needed"
            )
        else:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Could not find strike above money line (current price: ${current_price:,.2f})")
        
        # Enter NO trade at strike below
        if strike_below_data and not no_exists:
            no_ask_dollars = strike_below_data.get('no_ask_dollars')
            if no_ask_dollars:
                _diff_ok, _diff_reason = _auto_entry_differential_allowed(settings, "no", strike_below_data)
                if not _diff_ok:
                    log(
                        f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ NO leg blocked by differential gate ({_diff_reason}) "
                        f"strike=${strike_below_data.get('strike'):,.0f}"
                    )
                else:
                    strike_data = {
                        'strike': format_trade_strike_label(strike_below_data.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike_below_data.get("ticker")),
                        'side': 'no',
                        'ticker': strike_below_data.get('ticker'),
                        'buy_price': float(no_ask_dollars),
                        'probability': strike_below_data.get('probability'),
                        'diff': strike_below_data.get('no_diff')
                    }
                    log(f"[AUTO ENTRY MOMENTUM BREAKOUT] 🚀 TRIGGERING NO TRADE | Strike: ${strike_below_data.get('strike'):,.0f} | Buy Price: ${float(no_ask_dollars):.2f} | Ticker: {strike_below_data.get('ticker')}")
                    if trigger_auto_entry_trade(strike_data):
                        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ✅ NO TRADE SUCCESSFUL | Strike: ${strike_below_data.get('strike'):,.0f}")
                        trades_entered += 1
                    else:
                        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ NO TRADE FAILED | Strike: ${strike_below_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Missing no_ask_dollars for strike below ${strike_below_data.get('strike'):,.0f}")
        elif strike_below_data and no_exists:
            log(
                f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏭️ Skipping NO (already in flight) at ${strike_below_data.get('strike'):,.0f} — will try other leg if needed"
            )
        else:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Could not find strike below money line (current price: ${current_price:,.2f})")
        
        yes_done, no_done = _momentum_breakout_legs_in_db(strike_above_data, strike_below_data)
        if yes_done and no_done:
            state["entered"] = True
            if current_contract:
                state["contract"] = current_contract
            log(
                f"[AUTO ENTRY MOMENTUM BREAKOUT] ✅ Two-leg bracket complete for cycle {current_contract} "
                f"(this_tick_new={trades_entered}) — will hold until expiration"
            )
        elif trades_entered > 0 or yes_done or no_done:
            log(
                f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Partial bracket (yes_in_db={yes_done} no_in_db={no_done} "
                f"new_this_tick={trades_entered}) cycle {current_contract} — will retry missing leg on next scan"
            )
        
    except Exception as e:
        import traceback
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Error checking auto entry conditions: {e}")
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Traceback: {traceback.format_exc()}")

def check_auto_entry_conditions_momentum_contain():
    """Check if auto entry conditions are met and trigger trades for Momentum Contain strategy
    
    Momentum Contain activates when momentum spike is detected (same as Momentum Breakout).
    When activated, it immediately opens TWO trades with FLIPPED SIDES compared to Momentum Breakout:
    - NO trade at strike immediately above the money line (contrarian to Breakout)
    - YES trade at strike immediately below the money line (contrarian to Breakout)
    Uses strike_tier to find the correct strikes.
    After entering these two trades, it opens no more trades and holds until expiration.
    """
    try:
        monitor_key = ctx_ident()
        state = _momentum_contain_cycle_state_by_monitor.setdefault(
            monitor_key, {"entered": False, "contract": None}
        )
        # Get strike table data
        check_spike_alert_conditions()
        
        strike_table_data = get_master_strike_table_data()
        
        # Failsafe: Skip 5pm cycles (daily 5pm cycles are excluded)
        # Check hour_24 directly (17 = 5pm) - most reliable method
        if strike_table_data:
            symbol = (strike_table_data or {}).get("symbol") or MONITOR_SYMBOL or "BTC"
            market_title = (strike_table_data or {}).get("market_title")
            event_ticker = (strike_table_data or {}).get("event_ticker")
            
            # Resolve the hour directly to check for 5pm (hour_24 == 17)
            _, hour_24 = _resolve_event_time(symbol, market_title, event_ticker)
            if hour_24 == 17:  # 5pm in 24-hour format
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Skipping 5pm cycle (hour_24={hour_24})")
                return
            
            # Also check contract label and market_title as additional failsafe
            current_contract = _LAST_MONITOR_STATE.get("contract")
            contract_to_check = current_contract or market_title or ""
            if contract_to_check and "5pm" in contract_to_check.lower():
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Skipping 5pm cycle (contract check): {contract_to_check}")
                return
            
            update_monitor_current_state(strike_table_data)
        
        # Get current contract from monitor state (after update)
        current_contract = _LAST_MONITOR_STATE.get("contract")
        
        # Reset trades_entered flag when a new cycle starts (contract changes)
        if current_contract and current_contract != state.get("contract"):
            prev_contract = state.get("contract")
            state["entered"] = False
            if prev_contract:
                log(
                    f"[AUTO ENTRY MOMENTUM CONTAIN] 🔄 New cycle detected: "
                    f"{prev_contract} → {current_contract} - resetting entry flag"
                )
            state["contract"] = current_contract
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (REQUIRED for Momentum Contain to activate)
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        
        if not auto_trade_enabled:
            _aes_indicator_bucket().update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": spike_alert_active,
                "current_ttc": 0,
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window + spike alert active
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          spike_alert_active)
        
        # Update indicator state for frontend
        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": spike_alert_active,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        if not ttc_within_window:
            return
        
        # SPIKE ALERT CHECK - Momentum Contain REQUIRES spike alert to be active
        if not spike_alert_active:
            return
        
        # COOLDOWN TIMER CHECK - Validate cooldown_timer is within activation window
        # This prevents entry when cooldown_timer is outside min/max parameters
        min_cooldown_timer = settings.get("min_cooldown_timer")
        max_cooldown_timer = settings.get("max_cooldown_timer")
        
        # If either min or max is set, check cooldown_timer is within window
        if min_cooldown_timer is not None or max_cooldown_timer is not None:
            # Get cooldown_timer from database
            cooldown_timer = None
            try:
                import psycopg2
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    cursor.execute(f"SELECT cooldown_timer FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
                    result = cursor.fetchone()
                    cooldown_timer = result[0] if result and result[0] is not None else None
                conn.close()
            except Exception as e:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error getting cooldown timer: {e}")
            
            # If cooldown_timer is NULL, cannot determine - skip entry
            if cooldown_timer is None:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ cooldown_timer is NULL - skipping entry")
                return
            
            # DB stores cooldown_timer as REMAINING seconds in spike cooldown. min/max are "seconds since spike started".
            cooldown_minutes = settings.get("spike_alert_cooldown_minutes") or 0
            total_cooldown_seconds = int(cooldown_minutes) * 60
            time_since_spike = total_cooldown_seconds - int(cooldown_timer) if cooldown_timer > 0 else 0
            
            if min_cooldown_timer is not None and time_since_spike < min_cooldown_timer:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ time_since_spike ({time_since_spike}s) < min_cooldown_timer ({min_cooldown_timer}s) - too close to spike start - skipping entry")
                return
            
            if max_cooldown_timer is not None and time_since_spike > max_cooldown_timer:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ time_since_spike ({time_since_spike}s) > max_cooldown_timer ({max_cooldown_timer}s) - too far after spike start - skipping entry")
                return
        
        # If we've already entered trades for this spike activation, do nothing
        if state.get("entered"):
            return

        if not strike_table_data:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ No strike table data available")
            return
        
        current_price = strike_table_data.get("current_price")
        strike_tier = strike_table_data.get("strike_tier")
        
        if current_price is None or strike_tier is None:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing current_price or strike_tier")
            return
        
        try:
            strike_tier = int(strike_tier)
        except (ValueError, TypeError):
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Invalid strike_tier: {strike_tier}")
            return
        if strike_tier <= 0:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Invalid strike_tier (<=0): {strike_tier}")
            return

        if has_bracket_for_cycle(contract=current_contract, strike_tier=strike_tier):
            state["entered"] = True
            return
        
        # Select strikes using the unified minimum-width + centering methodology:
        # 1) Compute minimum bracket width from 0.35% of current price.
        # 2) Find the valid YES/NO pair (YES < price < NO) whose bracket width is
        #    closest to that minimum without going below it.
        # 3) For ties on width excess, keep price as centered as possible.
        strikes = strike_table_data.get("strikes", [])
        strike_above_data = None  # NO leg (must be > current_price)
        strike_below_data = None  # YES leg (must be < current_price)

        # NOTE: hardcoded for now; we may later make this configurable per user/symbol.
        min_bracket_width_pct = 0.0035  # 0.35% total bracket width
        current_price_f = float(current_price)
        min_bracket_width = current_price_f * min_bracket_width_pct

        # Parse and partition available strikes once.
        below_candidates = []  # [(strike_value, strike_data)]
        above_candidates = []  # [(strike_value, strike_data)]
        for strike in strikes:
            strike_value_raw = strike.get("strike")
            if strike_value_raw is None:
                continue
            try:
                strike_value = float(strike_value_raw)
            except (ValueError, TypeError):
                continue

            if strike_value < current_price_f:
                below_candidates.append((strike_value, strike))
            elif strike_value > current_price_f:
                above_candidates.append((strike_value, strike))

        # Search for best valid pair:
        # priority 1: smallest non-negative width excess
        # priority 2: smallest midpoint distance from current price
        # priority 3: deterministic tie-break on lower strike (smaller first)
        best_pair = None
        best_pair_key = None
        for below_strike_val, below_strike_data in below_candidates:
            for above_strike_val, above_strike_data in above_candidates:
                bracket_width = above_strike_val - below_strike_val
                if bracket_width < min_bracket_width:
                    continue

                width_excess = bracket_width - min_bracket_width
                midpoint = (below_strike_val + above_strike_val) / 2.0
                center_offset = abs(current_price_f - midpoint)
                pair_key = (
                    round(width_excess, 12),
                    round(center_offset, 12),
                    below_strike_val
                )
                if best_pair_key is None or pair_key < best_pair_key:
                    best_pair_key = pair_key
                    best_pair = (
                        below_strike_data,
                        above_strike_data,
                        below_strike_val,
                        above_strike_val,
                        bracket_width,
                        midpoint,
                        center_offset,
                        width_excess
                    )

        if best_pair:
            strike_below_data = best_pair[0]
            strike_above_data = best_pair[1]

        # Log selection details for debugging
        below_strike_val = float(strike_below_data.get("strike")) if strike_below_data and strike_below_data.get("strike") is not None else None
        above_strike_val = float(strike_above_data.get("strike")) if strike_above_data and strike_above_data.get("strike") is not None else None

        below_str = f"${below_strike_val:,.0f}" if below_strike_val is not None else "N/A"
        above_str = f"${above_strike_val:,.0f}" if above_strike_val is not None else "N/A"
        min_width_str = f"${min_bracket_width:,.2f}"
        selected_width = None
        midpoint = None
        center_offset = None
        if below_strike_val is not None and above_strike_val is not None:
            selected_width = above_strike_val - below_strike_val
            midpoint = (below_strike_val + above_strike_val) / 2.0
            center_offset = abs(current_price_f - midpoint)

        selected_width_str = f"${selected_width:,.2f}" if selected_width is not None else "N/A"
        midpoint_str = f"${midpoint:,.2f}" if midpoint is not None else "N/A"
        center_offset_str = f"${center_offset:,.2f}" if center_offset is not None else "N/A"
        log(
            f"[AUTO ENTRY MOMENTUM CONTAIN] 🎯 Current price: ${current_price_f:,.2f}, Strike tier: ${strike_tier:,} | "
            f"Min width (0.35%): {min_width_str} | Selected below(YES): {below_str}, Selected above(NO): {above_str} | "
            f"Selected width: {selected_width_str} | Midpoint: {midpoint_str} | Center offset: {center_offset_str}"
        )
        
        no_exists, yes_exists = _momentum_contain_legs_in_db(strike_above_data, strike_below_data)
        if no_exists and yes_exists:
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Both legs already in flight (NO @ {above_str}, YES @ {below_str}) — bracket complete"
            )
            state["entered"] = True
            return
        
        # VALIDATION CHECKS: Volume, Momentum, and Ask Price checks before entering trades
        # Get required settings
        min_volume = settings.get("min_volume", 1000)
        min_ask = settings.get("min_ask", 0.0000)
        max_ask = settings.get("max_ask", 0.9800)
        cooldown_threshold = settings.get("spike_alert_cooldown_threshold")
        
        # VOLUME CHECK: Ensure both strikes meet minimum volume requirement
        if not strike_above_data or not strike_below_data:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Missing strike data - cannot perform volume check")
            return
        
        volume_above = _kalshi_fp_volume_number(strike_above_data.get("volume_fp")) or 0
        volume_below = _kalshi_fp_volume_number(strike_below_data.get("volume_fp")) or 0
        
        if volume_above < min_volume:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike above volume ({volume_above}) below minimum ({min_volume}) - skipping entry")
            return
        
        if volume_below < min_volume:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike below volume ({volume_below}) below minimum ({min_volume}) - skipping entry")
            return
        
        # MOMENTUM CHECK: Both 30s average and current momentum_percentile must be below cooldown threshold
        current_symbol = get_current_monitor_symbol()
        momentum_30s_avg = get_momentum_30s_avg(current_symbol)
        if momentum_30s_avg is None:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Cannot determine momentum_30s_avg - skipping entry")
            return
        
        momentum_percentile = get_momentum_percentile(current_symbol)
        if momentum_percentile is None:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Cannot determine momentum_percentile - skipping entry")
            return
        
        if cooldown_threshold is None:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing spike_alert_cooldown_threshold setting - skipping entry")
            return
        
        abs_momentum_30s = abs(momentum_30s_avg)
        abs_momentum_percentile = abs(momentum_percentile)
        
        # Both must be below threshold to allow entry
        if abs_momentum_30s >= cooldown_threshold:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ 30s average momentum ({momentum_30s_avg:.2f}, abs: {abs_momentum_30s:.2f}) still above cooldown threshold ({cooldown_threshold:.2f}) - skipping entry")
            return
        
        if abs_momentum_percentile >= cooldown_threshold:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Current momentum_percentile ({momentum_percentile:.2f}, abs: {abs_momentum_percentile:.2f}) still above cooldown threshold ({cooldown_threshold:.2f}) - skipping entry")
            return
        
        # ASK PRICE CHECK: Ensure both legs have ask prices within min_ask and max_ask range
        no_ask_dollars_above = strike_above_data.get('no_ask_dollars')
        yes_ask_dollars_below = strike_below_data.get('yes_ask_dollars')
        
        if not no_ask_dollars_above:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Missing no_ask_dollars for strike above - skipping entry")
            return
        
        if not yes_ask_dollars_below:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Missing yes_ask_dollars for strike below - skipping entry")
            return
        
        try:
            no_ask_price_above = float(no_ask_dollars_above)
            yes_ask_price_below = float(yes_ask_dollars_below)
        except (ValueError, TypeError):
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Invalid ask price data - skipping entry")
            return
        
        # Check NO ask price at strike above
        if no_ask_price_above < min_ask or no_ask_price_above > max_ask:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike above NO ask (${no_ask_price_above:.4f}) outside range [{min_ask:.4f}, {max_ask:.4f}] - skipping entry")
            return
        
        # Check YES ask price at strike below
        if yes_ask_price_below < min_ask or yes_ask_price_below > max_ask:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike below YES ask (${yes_ask_price_below:.4f}) outside range [{min_ask:.4f}, {max_ask:.4f}] - skipping entry")
            return
        
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ All checks passed | Above: vol={volume_above}>={min_volume}, NO ask=${no_ask_price_above:.4f} in [{min_ask:.4f}, {max_ask:.4f}] | Below: vol={volume_below}>={min_volume}, YES ask=${yes_ask_price_below:.4f} in [{min_ask:.4f}, {max_ask:.4f}] | Momentum 30s: {momentum_30s_avg:.2f} (abs: {abs_momentum_30s:.2f}) < {cooldown_threshold:.2f}, Momentum %ile: {momentum_percentile:.2f} (abs: {abs_momentum_percentile:.2f}) < {cooldown_threshold:.2f}")
        
        # Enter the two trades (FLIPPED SIDES from Momentum Breakout)
        trades_entered = 0
        
        # Enter NO trade at strike above (FLIPPED: Breakout enters YES here).
        # No differential gate for Momentum Contain (strategy is two fixed legs; differential is for Hourly HTC-style filters).
        if strike_above_data and not no_exists:
            no_ask_dollars = strike_above_data.get('no_ask_dollars')
            if no_ask_dollars:
                strike_data = {
                    'strike': format_trade_strike_label(strike_above_data.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike_above_data.get("ticker")),
                    'side': 'no',  # FLIPPED: Breakout uses 'yes' here
                    'ticker': strike_above_data.get('ticker'),
                    'buy_price': float(no_ask_dollars),
                    'probability': strike_above_data.get('probability'),
                    'diff': strike_above_data.get('no_diff')
                }
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] 🚀 TRIGGERING NO TRADE | Strike: ${strike_above_data.get('strike'):,.0f} | Buy Price: ${float(no_ask_dollars):.2f} | Ticker: {strike_above_data.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ NO TRADE SUCCESSFUL | Strike: ${strike_above_data.get('strike'):,.0f}")
                    trades_entered += 1
                else:
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ NO TRADE FAILED | Strike: ${strike_above_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing no_ask_dollars for strike above ${strike_above_data.get('strike'):,.0f}")
        elif strike_above_data and no_exists:
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ⏭️ Skipping NO (already in flight) at ${strike_above_data.get('strike'):,.0f} — will try YES leg if needed"
            )
        else:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Could not find strike above money line (current price: ${current_price:,.2f})")
        
        # Enter YES trade at strike below (FLIPPED: Breakout enters NO here). No differential gate (see NO leg above).
        if strike_below_data and not yes_exists:
            yes_ask_dollars = strike_below_data.get('yes_ask_dollars')
            if yes_ask_dollars:
                strike_data = {
                    'strike': format_trade_strike_label(strike_below_data.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike_below_data.get("ticker")),
                    'side': 'yes',  # FLIPPED: Breakout uses 'no' here
                    'ticker': strike_below_data.get('ticker'),
                    'buy_price': float(yes_ask_dollars),
                    'probability': strike_below_data.get('probability'),
                    'diff': strike_below_data.get('yes_diff')
                }
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] 🚀 TRIGGERING YES TRADE | Strike: ${strike_below_data.get('strike'):,.0f} | Buy Price: ${float(yes_ask_dollars):.2f} | Ticker: {strike_below_data.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ YES TRADE SUCCESSFUL | Strike: ${strike_below_data.get('strike'):,.0f}")
                    trades_entered += 1
                else:
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ YES TRADE FAILED | Strike: ${strike_below_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing yes_ask_dollars for strike below ${strike_below_data.get('strike'):,.0f}")
        elif strike_below_data and yes_exists:
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ⏭️ Skipping YES (already in flight) at ${strike_below_data.get('strike'):,.0f} — will try NO leg if needed"
            )
        else:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Could not find strike below money line (current price: ${current_price:,.2f})")
        
        no_done, yes_done = _momentum_contain_legs_in_db(strike_above_data, strike_below_data)
        if no_done and yes_done:
            state["entered"] = True
            if current_contract:
                state["contract"] = current_contract
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ Two-leg bracket complete for cycle {current_contract} "
                f"(this_tick_new={trades_entered}) — will hold until expiration"
            )
        elif trades_entered > 0 or no_done or yes_done:
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Partial bracket (no_in_db={no_done} yes_in_db={yes_done} "
                f"new_this_tick={trades_entered}) cycle {current_contract} — will retry missing leg on next scan"
            )
        
    except Exception as e:
        import traceback
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error checking auto entry conditions: {e}")
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Traceback: {traceback.format_exc()}")

def check_auto_entry_conditions_momentum_scalp():
    """Check if auto entry conditions are met and trigger trades for Momentum Scalp strategy"""
    try:
        # Get strike table data
        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not auto_trade_enabled:
            _aes_indicator_bucket().update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": 0,
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_volume", "momentum_scalp_entry_threshold", "min_ask", "max_ask"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MS] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_volume = settings.get("min_volume", 1000)
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        min_ask = settings.get("min_ask", 0.0000)
        max_ask = settings.get("max_ask", 0.9800)
        max_price_spread = settings.get("max_price_spread", 0.0300)
        
        if momentum_threshold is None:
            log(f"[AUTO ENTRY MS] ❌ Missing momentum_scalp_entry_threshold")
            return
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Get current momentum
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            # Update indicator state
            _aes_indicator_bucket().update({
                "enabled": True,
                "ttc_within_window": ttc_within_window,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": current_ttc,
                "min_time": min_time,
                "max_time": max_time,
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Determine momentum direction
        if current_momentum >= momentum_threshold:
            momentum_direction = "UP"
        elif current_momentum <= -momentum_threshold:
            momentum_direction = "DOWN"
        else:
            momentum_direction = None
        
        # Determine if scanning is active (TTC in window AND momentum spike detected)
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          momentum_direction is not None)
        
        # Update indicator state for frontend
        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": False,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        # Must be within time window AND have momentum spike to proceed
        if not ttc_within_window or momentum_direction is None:
            return
        
        if not strike_table_data or "strikes" not in strike_table_data:
            return
        
        # Filter strikes based on momentum direction
        # UP momentum -> look at active_side='yes'
        # DOWN momentum -> look at active_side='no'
        eligible_strikes = []
        for strike in strike_table_data["strikes"]:
            active_side = strike.get('active_side')
            if not active_side:
                continue
            
            # Filter by momentum direction
            if momentum_direction == "UP" and active_side != 'yes':
                continue
            if momentum_direction == "DOWN" and active_side != 'no':
                continue
            
            # Filter by volume
            volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
            if volume < min_volume:
                continue
            
            # Filter by ask price window (min_ask <= ask_dollars <= max_ask)
            # For YES side: check yes_ask_dollars
            # For NO side: check no_ask_dollars
            if active_side == 'yes':
                ask_dollars = strike.get('yes_ask_dollars')
            elif active_side == 'no':
                ask_dollars = strike.get('no_ask_dollars')
            else:
                continue
            
            if ask_dollars is None:
                continue
            
            # Convert to float and check against min/max ask window
            try:
                ask_price = float(ask_dollars)
                if ask_price < min_ask or ask_price > max_ask:
                    continue
            except (ValueError, TypeError):
                continue
            
            # Filter by price spread (must be <= max_price_spread)
            if active_side == 'yes':
                price_spread = strike.get('yes_price_spread')
            elif active_side == 'no':
                price_spread = strike.get('no_price_spread')
            else:
                continue
            
            if price_spread is None:
                continue
            
            try:
                spread_value = float(price_spread)
                if spread_value > max_price_spread:
                    continue
            except (ValueError, TypeError):
                continue
            
            eligible_strikes.append(strike)
        
        # Sort by probability (highest to lowest)
        eligible_strikes.sort(key=lambda x: x.get('probability', 0), reverse=True)
        
        # Process eligible strikes
        processed_strikes = set()
        for strike in eligible_strikes:
            try:
                active_side = strike.get('active_side')
                strike_key = _strike_cooldown_key(strike.get("strike"), active_side)
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                processed_strikes.add(strike_key)
                
                # Check cooldown
                if not can_trade_strike(strike_key):
                    continue
                
                # Check if already traded
                strike_data_for_check = {
                    "strike": strike.get("strike"),
                    "side": active_side,
                    "ticker": strike.get("ticker"),
                }
                if is_strike_already_traded(strike_data_for_check):
                    continue

                # Prepare strike data
                prob = strike.get('probability')
                if active_side == 'yes':
                    side = 'yes'
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        continue
                    buy_price = float(yes_ask_dollars)
                elif active_side == 'no':
                    side = 'no'
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        continue
                    buy_price = float(no_ask_dollars)
                else:
                    continue
                
                _diff_ok, _diff_reason = _auto_entry_differential_allowed(settings, side, strike)
                if not _diff_ok:
                    log(f"[AUTO ENTRY MS] ⏸️ Skipping {strike_key} differential gate ({_diff_reason})")
                    continue

                strike_data = {
                    'strike': format_trade_strike_label(strike.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike.get("ticker")),
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob,
                    'diff': strike.get('yes_diff') if side == 'yes' else strike.get('no_diff'),
                }
                
                # Check if strike is already traded
                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY MS] ⏸️ Skipping {strike_key} - already has open/pending trade")
                    continue
                
                # Trigger the trade
                log(f"[AUTO ENTRY MS] 🚀 TRIGGERING TRADE | {strike_key} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Momentum: {current_momentum:.2f} ({momentum_direction})")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MS] ✅ TRADE SUCCESSFUL | {strike_key}")
                else:
                    log(f"[AUTO ENTRY MS] ❌ TRADE FAILED | {strike_key}")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY MS] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY MS] Error checking auto entry conditions: {e}")

def check_auto_entry_conditions_momentum_reversal():
    """Check if auto entry conditions are met and trigger trades for Momentum Reversal strategy"""
    try:
        # Get strike table data
        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not auto_trade_enabled:
            _aes_indicator_bucket().update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": 0,
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_volume", "momentum_scalp_entry_threshold", "min_ask", "max_ask"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MR] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_volume = settings.get("min_volume", 1000)
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        min_ask = settings.get("min_ask", 0.0000)
        max_ask = settings.get("max_ask", 0.9800)
        max_price_spread = settings.get("max_price_spread", 0.0300)
        
        if momentum_threshold is None:
            log(f"[AUTO ENTRY MR] ❌ Missing momentum_scalp_entry_threshold")
            return
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Get current momentum
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            # Update indicator state
            _aes_indicator_bucket().update({
                "enabled": True,
                "ttc_within_window": ttc_within_window,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": current_ttc,
                "min_time": min_time,
                "max_time": max_time,
                "last_updated": est_now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Determine momentum direction
        if current_momentum >= momentum_threshold:
            momentum_direction = "UP"
        elif current_momentum <= -momentum_threshold:
            momentum_direction = "DOWN"
        else:
            momentum_direction = None
        
        # Determine if scanning is active (TTC in window AND momentum spike detected)
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          momentum_direction is not None)
        
        # Update indicator state for frontend
        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": False,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        # Must be within time window AND have momentum spike to proceed
        if not ttc_within_window or momentum_direction is None:
            return
        
        if not strike_table_data or "strikes" not in strike_table_data:
            return
        
        # Filter strikes based on momentum direction
        # UP momentum -> look at active_side='yes'
        # DOWN momentum -> look at active_side='no'
        eligible_strikes = []
        for strike in strike_table_data["strikes"]:
            active_side = strike.get('active_side')
            if not active_side:
                continue
            
            # Filter by momentum direction
            if momentum_direction == "UP" and active_side != 'yes':
                continue
            if momentum_direction == "DOWN" and active_side != 'no':
                continue
            
            # Filter by volume
            volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
            if volume < min_volume:
                continue
            
            # Filter by ask price window (min_ask <= ask_dollars <= max_ask)
            # For YES side: check yes_ask_dollars
            # For NO side: check no_ask_dollars
            if active_side == 'yes':
                ask_dollars = strike.get('yes_ask_dollars')
            elif active_side == 'no':
                ask_dollars = strike.get('no_ask_dollars')
            else:
                continue
            
            if ask_dollars is None:
                continue
            
            # Convert to float and check against min/max ask window
            try:
                ask_price = float(ask_dollars)
                if ask_price < min_ask or ask_price > max_ask:
                    continue
            except (ValueError, TypeError):
                continue
            
            # Filter by price spread (must be <= max_price_spread)
            if active_side == 'yes':
                price_spread = strike.get('yes_price_spread')
            elif active_side == 'no':
                price_spread = strike.get('no_price_spread')
            else:
                continue
            
            if price_spread is None:
                continue
            
            try:
                spread_value = float(price_spread)
                if spread_value > max_price_spread:
                    continue
            except (ValueError, TypeError):
                continue
            
            eligible_strikes.append(strike)
        
        # Sort by probability (highest to lowest)
        eligible_strikes.sort(key=lambda x: x.get('probability', 0), reverse=True)
        
        # Process eligible strikes
        processed_strikes = set()
        for strike in eligible_strikes:
            try:
                active_side = strike.get('active_side')
                strike_key = _strike_cooldown_key(strike.get("strike"), active_side)
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                processed_strikes.add(strike_key)
                
                # Check cooldown
                if not can_trade_strike(strike_key):
                    continue
                
                # Check if already traded
                strike_data_for_check = {
                    "strike": strike.get("strike"),
                    "side": active_side,
                    "ticker": strike.get("ticker"),
                }
                if is_strike_already_traded(strike_data_for_check):
                    continue

                # Prepare strike data - MOMENTUM REVERSAL: SWAP THE SIDE
                prob = strike.get('probability')
                if active_side == 'yes':
                    # Found YES ticker -> submit NO order (REVERSAL)
                    side = 'no'
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        continue
                    buy_price = float(no_ask_dollars)
                elif active_side == 'no':
                    # Found NO ticker -> submit YES order (REVERSAL)
                    side = 'yes'
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        continue
                    buy_price = float(yes_ask_dollars)
                else:
                    continue

                _diff_ok, _diff_reason = _auto_entry_differential_allowed(settings, side, strike)
                if not _diff_ok:
                    log(f"[AUTO ENTRY MR] ⏸️ Skipping {strike_key} -> {side.upper()} differential gate ({_diff_reason})")
                    continue
                
                strike_data = {
                    'strike': format_trade_strike_label(strike.get("strike"), symbol=get_current_monitor_symbol(), ticker=strike.get("ticker")),
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob,
                    'diff': strike.get('yes_diff') if side == 'yes' else strike.get('no_diff'),
                }
                
                # Check if strike is already traded (check with swapped side)
                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY MR] ⏸️ Skipping {strike_key} - already has open/pending trade")
                    continue
                
                # Trigger the trade
                log(f"[AUTO ENTRY MR] 🚀 TRIGGERING REVERSAL TRADE | {strike_key} -> {side.upper()} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Momentum: {current_momentum:.2f} ({momentum_direction})")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MR] ✅ TRADE SUCCESSFUL | {strike_key} -> {side.upper()}")
                else:
                    log(f"[AUTO ENTRY MR] ❌ TRADE FAILED | {strike_key} -> {side.upper()}")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY MR] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY MR] Error checking auto entry conditions: {e}")

def cleanup_old_cooldowns():
    """Clean up old cooldown entries"""
    current_time = time.time()
    keys_to_remove = []
    
    for strike_key, last_trade_time in last_trade_times.items():
        if current_time - last_trade_time >= TRADE_COOLDOWN:
            keys_to_remove.append(strike_key)
    
    for key in keys_to_remove:
        del last_trade_times[key]

    if keys_to_remove:
        log_debug(f"[AUTO ENTRY] Cleaned up {len(keys_to_remove)} expired cooldown(s)")


_symbol_wide_startup_done = False
_symbol_wide_startup_lock = threading.Lock()


def _aes_iter_unique_tenant_first_monitor():
    """First monitor binding per tenant (unified pool) for DB scoped to users.trades_<slot>."""
    if not AES_UNIFIED_POOL:
        yield USER_NUMBER, MONITOR_ID
        return
    if AES_UNIFIED_15M:
        from backend.core.unified_15m_monitors import iter_active_15m_monitor_bindings

        iter_bindings = iter_active_15m_monitor_bindings()
    elif AES_UNIFIED_HOURLY:
        from backend.core.unified_hourly_monitors import iter_active_hourly_monitor_bindings

        iter_bindings = iter_active_hourly_monitor_bindings()
    else:
        from backend.core.unified_all_monitors import iter_active_unified_monitor_bindings

        iter_bindings = iter_active_unified_monitor_bindings()
    seen = set()
    for u, m in iter_bindings:
        if u in seen:
            continue
        seen.add(u)
        yield u, m


def _aes_run_symbol_wide_startup_once() -> None:
    """Reconcile simulated-trade LP ledger + monitor columns from trades (once per process)."""
    global _symbol_wide_startup_done
    with _symbol_wide_startup_lock:
        if _symbol_wide_startup_done:
            return
        _symbol_wide_startup_done = True
    try:
        for u, m in _aes_iter_unique_tenant_first_monitor():
            with aes_monitor_bind(u, m):
                conn = get_db_connection()
                try:
                    with conn.cursor() as cur:
                        startup_reconcile_simulated_trade_for_tenant(
                            cur,
                            _aes_trades_table(),
                            _aes_trades_simulated_table(),
                            _aes_monitor_list_table(),
                            str(u),
                        )
                    conn.commit()
                finally:
                    conn.close()
        log("✅ [SIM TRADE LP] Startup reconcile completed")
    except Exception as e:
        log(f"⚠️ [SIM TRADE LP] Startup reconcile failed: {e}")


def _aes_tick_symbol_wide_recompute() -> None:
    """Expire simulated-trade cooldown windows (recompute loss_prevention) for tenants with active anchors."""
    try:
        for u, m in _aes_iter_unique_tenant_first_monitor():
            with aes_monitor_bind(u, m):
                conn = get_db_connection()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT id FROM {_aes_monitor_list_table()}
                            WHERE COALESCE(loss_prevention_toggle, FALSE) IS TRUE
                              AND COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak') = 'time'
                              AND (
                                live_loss_prevention_cooldown_start_time IS NOT NULL
                                OR (
                                  COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
                                  AND simulated_loss_prevention_cooldown_start_time IS NOT NULL
                                )
                              )
                            """
                        )
                        ids = [str(r[0]) for r in (cur.fetchall() or [])]
                        for mid in ids:
                            recompute_monitor_loss_prevention(
                                cur, _aes_monitor_list_table(), mid
                            )
                    conn.commit()
                finally:
                    conn.close()
    except Exception as e:
        log_debug(f"[SIM TRADE LP] tick recompute: {e}")


def start_monitoring_loop():
    """Start the monitoring loop for auto entry conditions"""
    global monitoring_thread
    
    def monitoring_worker():
        global monitoring_thread
        log("📊 MONITORING: Starting auto entry monitoring loop")
        
        # Broadcast initial state immediately on startup
        log("📊 MONITORING: Broadcasting initial auto entry state")
        _aes_run_symbol_wide_startup_once()
        check_auto_entry_conditions()
        
        check_count = 0
        last_heartbeat = time.time()
        while True:
            try:
                check_count += 1
                current_time = time.time()
                
                # Heartbeat every 5 minutes (300 seconds)
                if current_time - last_heartbeat >= 300:
                    log_heartbeat()
                    last_heartbeat = current_time
                
                # Only log every 1000 checks (reduces logging by 99.9%)
                if check_count % 1000 == 0:
                    log_debug(f"Check #{check_count} - continuing monitoring...")
                
                # Clean up old cooldowns first
                cleanup_old_cooldowns()

                _aes_tick_symbol_wide_recompute()
                
                # Check auto entry conditions
                check_auto_entry_conditions()
                
                # Sleep for 1 second
                time.sleep(1)
                
            except Exception as e:
                import traceback
                log(f"❌ Error in monitoring worker: {e}")
                log(f"❌ Traceback: {traceback.format_exc()}")
                time.sleep(5)  # Wait longer on error
        
        # Clear the global monitoring thread reference when done
        with monitoring_thread_lock:
            monitoring_thread = None
        log("📊 MONITORING: Auto entry monitoring thread finished")
    
    # Start monitoring in a separate thread
    with monitoring_thread_lock:
        monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
        monitoring_thread.start()
        log("📊 MONITORING: Auto entry monitoring thread started")

# Health check endpoint
@app.route("/health")
def health_check():
    """Health check endpoint."""
    try:
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        enabled = is_auto_trade_enabled()
        
        return {
            "status": "healthy" if service_healthy else "unhealthy",
            "service": f"auto_entry_supervisor_{MONITOR_IDENTIFIER}",
            "monitor_identifier": MONITOR_IDENTIFIER,
            "user_number": ctx_user(),
            "monitor_id": ctx_mid(),
            "port": AUTO_ENTRY_SUPERVISOR_PORT,
            "timestamp": est_now().isoformat(),
            "port_system": "centralized",
            "monitoring_thread_alive": service_healthy,
            "auto_entry_enabled": enabled,
            "scanning_active": _aes_indicator_bucket().get("scanning_active", False),
            "spike_alert_active": _aes_indicator_bucket().get("spike_alert_active", False),
            "current_momentum": _aes_indicator_bucket().get("current_momentum", None)
        }
    except Exception as e:
        return {
            "status": "error",
            "service": f"auto_entry_supervisor_{MONITOR_IDENTIFIER}",
            "monitor_identifier": MONITOR_IDENTIFIER,
            "error": str(e),
            "timestamp": est_now().isoformat()
        }

# LEGACY REMOVED: /api/auto_entry_status endpoint - now using auto_trade_status system

# Auto entry indicator endpoint (for frontend display)
@app.route("/api/auto_entry_indicator")
def get_auto_entry_indicator():
    """Get current auto entry indicator state (unified pool: pass ``monitor_id``; ``user_number`` or REC_USER_NO)."""
    if AES_UNIFIED_POOL:
        mid = request.args.get("monitor_id")
        user = (request.args.get("user_number") or "").strip()
        if not user:
            try:
                user = default_pool_user_number()
            except RuntimeError:
                return jsonify({"error": "user_number query parameter required (set REC_USER_NO for default)"}), 400
        if not mid:
            return jsonify({"error": "monitor_id query parameter required for unified pool AES"}), 400
        with aes_monitor_bind(user, str(mid)):
            return jsonify(_aes_indicator_bucket())
    return jsonify(_aes_indicator_bucket())

# Detailed scanning status endpoint (for debugging/monitoring)
@app.route("/api/auto_entry_scanning_status")
def get_auto_entry_scanning_status():
    """Get detailed scanning status information"""
    try:
        def _payload():
            enabled = is_auto_trade_enabled()
            settings = get_auto_entry_settings()
            current_ttc = get_current_ttc()
            service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
            
            ttc_within_window = settings["min_time"] <= current_ttc <= settings["max_time"]
            spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
            scanning_active = enabled and service_healthy and ttc_within_window and not spike_alert_active
            
            return {
                "enabled": enabled,
                "service_healthy": service_healthy,
                "ttc_within_window": ttc_within_window,
                "scanning_active": scanning_active,
                "spike_alert_active": spike_alert_active,
                "current_momentum": _aes_indicator_bucket().get("current_momentum", None),
                "spike_alert_recovery_countdown": _aes_indicator_bucket().get("spike_alert_recovery_countdown", None),
                "current_ttc": current_ttc,
                "settings": settings,
                "spike_alert_settings": {
                    "enabled": settings.get("spike_alert_enabled"),
                    "momentum_threshold": settings.get("spike_alert_momentum_threshold"),
                    "cooldown_threshold": settings.get("spike_alert_cooldown_threshold"),
                    "cooldown_minutes": settings.get("spike_alert_cooldown_minutes")
                },
                "cooldown_entries_count": len(last_trade_times),
                "monitoring_thread_alive": service_healthy,
                "timestamp": est_now().isoformat()
            }

        if AES_UNIFIED_POOL:
            mid = request.args.get("monitor_id")
            user = (request.args.get("user_number") or "").strip()
            if not user:
                try:
                    user = default_pool_user_number()
                except RuntimeError:
                    return jsonify({"error": "user_number query parameter required (set REC_USER_NO for default)"}), 400
            if not mid:
                return jsonify({"error": "monitor_id query parameter required for unified pool AES"}), 400
            with aes_monitor_bind(user, str(mid)):
                return jsonify(_payload())
        return jsonify(_payload())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Automated trade notification endpoint
@app.route("/api/notify_automated_trade", methods=['POST'])
def notify_automated_trade():
    """Notify the frontend that an automated trade was triggered"""
    try:
        data = request.json
        log(f"[AUTO ENTRY] 🔔 Notifying frontend of automated trade: {data}")
        
        try:
            _aes_preferences_notify(
                "automated_trade_triggered",
                data if isinstance(data, dict) else {},
            )
            log(f"[AUTO ENTRY] ✅ Frontend notification sent (Redis or HTTP)")
        except Exception as e:
            log(f"[AUTO ENTRY] ❌ Error sending frontend notification: {e}")
        
        return jsonify({"success": True, "message": "Automated trade notification sent"})
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error in notify_automated_trade: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# Port information endpoint
@app.route("/api/ports")
def get_ports():
    """Get all port assignments from centralized system."""
    from backend.core.port_config import get_port_info
    return get_port_info()

# Spike alert settings endpoint
@app.route("/api/spike_alert_settings", methods=['GET', 'POST'])
def spike_alert_settings():
    """Get or update spike alert settings"""
    try:
        if request.method == 'GET':
            settings = get_auto_entry_settings()
            return jsonify({
                "spike_alert_enabled": settings.get("spike_alert_enabled"),
                "spike_alert_momentum_threshold": settings.get("spike_alert_momentum_threshold"),
                "spike_alert_cooldown_threshold": settings.get("spike_alert_cooldown_threshold"),
                "spike_alert_cooldown_minutes": settings.get("spike_alert_cooldown_minutes")
            })
        else:
            # POST - Update settings
            data = request.json
            settings_path = os.path.join(
                get_data_dir(), "users", f"user_{ctx_user()}", "preferences", "auto_entry_settings.json"
            )
            
            # Load current settings
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            else:
                settings = {}
            
            # Update with new values
            if "spike_alert_enabled" in data:
                settings["spike_alert_enabled"] = data["spike_alert_enabled"]
            if "spike_alert_momentum_threshold" in data:
                settings["spike_alert_momentum_threshold"] = data["spike_alert_momentum_threshold"]
            if "spike_alert_cooldown_threshold" in data:
                settings["spike_alert_cooldown_threshold"] = data["spike_alert_cooldown_threshold"]
            if "spike_alert_cooldown_minutes" in data:
                settings["spike_alert_cooldown_minutes"] = data["spike_alert_cooldown_minutes"]
            
            # Save updated settings
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
            
            log(f"[SPIKE ALERT SETTINGS] Updated: {data}")
            return jsonify({"success": True, "message": "Spike alert settings updated"})
            
    except Exception as e:
        log(f"[SPIKE ALERT SETTINGS] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    log(f"🛑 Received signal {signum}, shutting down gracefully...")
    sys.exit(0)

def start_event_driven_supervisor():
    """Start the event-driven auto entry supervisor"""
    log(f"🚀 Starting Auto Entry Supervisor for Monitor {MONITOR_IDENTIFIER}")
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    
    # Start monitoring loop
    start_monitoring_loop()
    
    # Start HTTP server
    def start_http_server():
        try:
            host = "localhost"  # Use localhost for internal service communication
            port = AUTO_ENTRY_SUPERVISOR_PORT
            log(f"🌐 Starting HTTP server on {host}:{port}")
            
            # Broadcast initial state immediately when server starts
            log("🌐 Broadcasting initial auto entry state on server startup")
            check_auto_entry_conditions()
            
            app.run(host=host, port=port, debug=False, use_reloader=False)
        except Exception as e:
            log(f"❌ Error starting HTTP server: {e}")
    
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    # Keep the process alive and periodically sync status even if
    # no external HTTP triggers are hitting this process.
    try:
        while True:
            try:
                periodic_status_sync()
            except Exception as e:
                log(f"[AUTO ENTRY] ❌ Error in periodic status loop: {e}")
            time.sleep(30)
    except KeyboardInterrupt:
        log("🛑 Auto entry supervisor stopped by user")
    except Exception as e:
        log(f"❌ Error in supervisor: {e}")



if __name__ == "__main__":
    # Start the event-driven supervisor
    start_event_driven_supervisor() 