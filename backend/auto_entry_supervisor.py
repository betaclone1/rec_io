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
from typing import Any, Dict, List, Optional, Set, Tuple
from contextvars import ContextVar
from contextlib import contextmanager
from collections import defaultdict
from flask import Flask, request, jsonify
from flask_cors import CORS
_HIGH_PRECISION_STRIKE_SYMBOLS = frozenset({"SOL", "XRP", "DOGE"})


def _symbol_from_ticker_hint(ticker: Optional[str]) -> Optional[str]:
    if not ticker:
        return None
    t = str(ticker).upper()
    if "DOGE" in t:
        return "DOGE"
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
        if sys.argv[1] == "btc15m_exp_scalp":
            return "btc15m_exp_scalp"
        return sys.argv[1]  # Use first argument as monitor identifier
    
    # Default to first active monitor if no identifier provided
    raise ValueError("No monitor identifier found in script name")

# Get monitor identifier
MONITOR_IDENTIFIER = get_monitor_identifier()
AES_UNIFIED_15M = MONITOR_IDENTIFIER == "unified_15m"
AES_UNIFIED_HOURLY = MONITOR_IDENTIFIER == "unified_hourly"
AES_UNIFIED_ALL = MONITOR_IDENTIFIER == "unified"
AES_BTC15M_EXP_SCALP = MONITOR_IDENTIFIER == "btc15m_exp_scalp"
# Cutout is a specialized multi-monitor pool (same bind/context rules as unified).
AES_UNIFIED_POOL = (
    AES_UNIFIED_15M
    or AES_UNIFIED_HOURLY
    or AES_UNIFIED_ALL
    or AES_BTC15M_EXP_SCALP
)
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
# Latest-only fire guard: refuse submit when mailbox gen advanced during eval.
_aes_lane_fire_guard: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "_aes_lane_fire_guard", default=None
)
_aes_lane_hub = None
_aes_lane_hub_lock = threading.Lock()
# Short process caches for lane hot path (PG remains authoritative on miss / TTL).
_aes_settings_mem_lock = threading.Lock()
_aes_settings_mem_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_aes_strategy_mem_cache: Dict[str, Tuple[float, str]] = {}
_AES_MEM_CACHE_TTL_SEC = float(os.getenv("AES_MONITOR_MEM_CACHE_TTL_SEC", "2"))
_aes_monitor_state_touch: Dict[str, float] = {}
_AES_MONITOR_STATE_MIN_SEC = float(os.getenv("AES_MONITOR_STATE_UPDATE_MIN_SEC", "5"))
# Warm set of (ticker, side_bucket) for is_strike_already_traded within one bind eval.
_aes_open_ticker_sides: ContextVar[Optional[Set[Tuple[str, str]]]] = ContextVar(
    "_aes_open_ticker_sides", default=None
)

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
    """Structured INFO at auto-trigger: ladder snapshot + live_state symbol metrics."""
    try:
        strategy = get_effective_trade_strategy()
    except Exception:
        strategy = None
    try:
        sym, mkt = get_current_monitor_symbol_and_market()
    except Exception:
        sym, mkt = "BTC", "hourly"
    status_payload = None
    try:
        from backend.core.tradeflow_live_reads import symbol_metrics

        m = symbol_metrics(str(sym or "BTC").strip().upper())
        if m:
            status_payload = {
                "source": "live_state",
                "price": m.get("price"),
                "one_minute_avg": m.get("one_minute_avg"),
                "momentum_30s_avg": m.get("momentum_30s_avg"),
                "momentum_5s_avg": m.get("momentum_5s_avg"),
            }
    except Exception:
        status_payload = None
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
        "symbol_metrics": status_payload,
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


try:
    from backend.core.tradeflow_decision_trace import set_trace_logger as _aes_set_trace_logger

    _aes_set_trace_logger(log)
except Exception:
    pass

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
            clock = _kalshi_clock_from_event_suffix(parts[-1])
            if clock is None and len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) <= 2:
                clock = _kalshi_clock_from_event_suffix(parts[-2])
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
    if AES_UNIFIED_POOL:
        key = ctx_ident()
        now = time.monotonic()
        last = _aes_monitor_state_touch.get(key, 0.0)
        if now - last < _AES_MONITOR_STATE_MIN_SEC:
            return
        _aes_monitor_state_touch[key] = now
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

        if AES_BTC15M_EXP_SCALP:
            # Cutout may start with zero matching monitors; stay up for membership changes.
            return "BTC", "15m"
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
elif AES_BTC15M_EXP_SCALP:
    AUTO_ENTRY_SUPERVISOR_PORT = get_port(
        f"auto_entry_supervisor_{default_pool_user_number()}_btc15m_exp_scalp"
    )
    _aes_logger.info(
        "Using BTC 15m Expiration Scalp cutout AES port: %s", AUTO_ENTRY_SUPERVISOR_PORT
    )
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
_aes_live_state_wake = threading.Event()
_AES_FAILSAFE_POLL_SEC = float(os.getenv("AES_FAILSAFE_POLL_SEC", "1"))
# Redis failsafe_refresh_all while busy: slow cadence (quiet timeout still refreshes).
_AES_FAILSAFE_REDIS_SEC = float(os.getenv("AES_FAILSAFE_REDIS_SEC", "5"))
_AES_LP_RECONCILE_SEC = float(os.getenv("AES_LP_RECONCILE_SEC", "5"))
_aes_last_lp_recompute_mono: float = 0.0
_aes_last_failsafe_mono: float = 0.0
_aes_last_cheap_status_mono: float = 0.0
_aes_pool_ladder_keys: Set[Tuple[str, str]] = set()
_aes_pool_ladder_keys_at: float = 0.0
_aes_lane_monitor_rows_cache: Optional[List[dict]] = None
_aes_lane_monitor_rows_at: float = 0.0
_AES_LANE_MONITOR_ROWS_TTL_SEC = float(os.getenv("AES_LANE_MONITOR_ROWS_TTL_SEC", "2"))

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
    # Time window comes only from the monitor row — never invent 0/3600.
    "min_time": None,
    "max_time": None,
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
# Display-field write throttle for monitor_list.cooldown_timer (not gate authority).
_AES_COOLDOWN_TIMER_WRITE_MIN_SEC = float(
    os.getenv("AES_COOLDOWN_TIMER_WRITE_MIN_SEC", "1.0")
)
_aes_cooldown_timer_write_state: Dict[str, Tuple[float, int]] = {}
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

# Expiration Scalp entry verification dwell: ctx_ident -> (strike_key, side) -> {started_at}
_exp_scalp_entry_verify_by_monitor: Dict[str, Dict[Tuple[str, str], dict]] = {}


def _exp_scalp_verify_abort(
    verify_bucket: Dict[Tuple[str, str], dict],
    dedupe_key: Tuple[str, str],
    *,
    now_ts: float,
    need_s: int,
    reason: str,
    strike_key: str,
    side_key: str,
    log_tag: str,
    extra: str = "",
) -> None:
    """Clear in-progress entry dwell and INFO-log so aborts are countable."""
    prior = verify_bucket.pop(dedupe_key, None)
    if not prior:
        return
    try:
        started = float(prior.get("started_at"))
        dwell = max(0.0, float(now_ts) - started)
    except (TypeError, ValueError, AttributeError):
        dwell = 0.0
    msg = (
        f"{log_tag} VERIFY ABORT | {strike_key} {side_key.upper()} | "
        f"dwell={dwell:.1f}s need={need_s}s | reason={reason}"
    )
    if extra:
        msg = f"{msg} | {extra}"
    log(msg)


def _exp_scalp_live_side_ask(ticker: Any, side_key: str) -> Optional[float]:
    """Peek live_state ask for flicker veto only. None if missing/stale — no substitute."""
    want = str(ticker or "").strip()
    if not want:
        return None
    from backend.core.tradeflow_live_reads import strike_ladder

    ladder = strike_ladder("BTC", "15m", _strike_data_exchange_key())
    if not ladder:
        return None
    for row in ladder.get("strikes") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker") or "").strip() != want:
            continue
        raw = row.get("yes_ask_dollars") if side_key == "yes" else row.get("no_ask_dollars")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


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
                    
                    # Display field only — spike gates use cooldown_start_time.
                    # Throttle writes/NOTIFY to ≥1s to cut switchboard + PG load.
                    _aes_maybe_write_cooldown_timer_display(
                        cursor, int(remaining_seconds), commit_conn=conn
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
    """Get current momentum_5s_avg from live_state symbol cache (no PG on hot path)."""
    try:
        from backend.core.tradeflow_live_reads import symbol_metrics

        m = symbol_metrics(str(symbol or "BTC").strip().upper())
        if not m:
            return None
        v = m.get("momentum_5s_avg")
        if v is None:
            v = m.get("momentum")
        if v is not None:
            return float(v)
        return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum for {symbol}: {e}")
        return None


def get_momentum_30s_avg(symbol="BTC"):
    """Get current momentum_30s_avg from live_state symbol cache."""
    try:
        from backend.core.tradeflow_live_reads import symbol_metrics

        m = symbol_metrics(str(symbol or "BTC").strip().upper())
        if not m:
            return None
        v = m.get("momentum_30s_avg")
        if v is not None:
            return float(v)
        return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum_30s_avg for {symbol}: {e}")
        return None


def get_momentum_percentile(symbol="BTC"):
    """Get current momentum_percentile from live_state symbol cache."""
    try:
        from backend.core.tradeflow_live_reads import symbol_metrics

        m = symbol_metrics(str(symbol or "BTC").strip().upper())
        if not m:
            return None
        v = m.get("momentum_percentile")
        if v is not None:
            return float(v)
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
            # No DB state yet — do not invent monitor gate settings.
            return
        
        # Get spike alert settings from auto entry settings - NO DEFAULTS
        settings = get_auto_entry_settings()
        
        # Check if all required spike alert settings exist
        required_settings = [
            "spike_alert_enabled",
            "spike_alert_momentum_threshold", 
            "spike_alert_cooldown_threshold",
            "spike_alert_cooldown_minutes"
        ]
        
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
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

def _aes_maybe_write_cooldown_timer_display(
    cursor, remaining_seconds: int, *, commit_conn=None
) -> bool:
    """
    Persist monitor_list.cooldown_timer for UI display only.

    Spike / entry gates must use cooldown_start_time (see
    ``_aes_time_since_spike_seconds``), not this throttled column.
    Returns True when a write + preferences notify ran.
    """
    ident = ctx_ident()
    ri = int(remaining_seconds)
    now = time.monotonic()
    prev = _aes_cooldown_timer_write_state.get(ident)
    if prev is not None:
        pts, pval = prev
        if (now - pts) < _AES_COOLDOWN_TIMER_WRITE_MIN_SEC and pval == ri:
            return False
        if (now - pts) < _AES_COOLDOWN_TIMER_WRITE_MIN_SEC:
            return False
    cursor.execute(
        f"UPDATE {_aes_monitor_list_table()} SET cooldown_timer = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (ri, ctx_mid()),
    )
    if commit_conn is not None:
        commit_conn.commit()
    _aes_cooldown_timer_write_state[ident] = (now, ri)
    full_monitor_id = f"mon_{ctx_user()}_{ctx_mid()}"
    _aes_preferences_notify(
        "cooldown_timer_change",
        {"monitor_id": full_monitor_id, "cooldown_timer": ri},
    )
    return True


def _aes_time_since_spike_seconds() -> Optional[int]:
    """Seconds since cooldown_start_time (authoritative); None if no active spike start."""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT cooldown_start_time FROM {_aes_monitor_list_table()} WHERE id = %s",
                (ctx_mid(),),
            )
            row = cursor.fetchone()
        conn.close()
        if not row or row[0] is None:
            return None
        return int((est_now() - row[0]).total_seconds())
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error getting cooldown_start_time: {e}")
        return None


# Legacy function for backward compatibility (will be removed)
def update_cooldown_timer_in_db(seconds):
    """Update cooldown_timer in the database (LEGACY - will be removed)"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            wrote = _aes_maybe_write_cooldown_timer_display(
                cursor, int(seconds), commit_conn=conn
            )
        conn.close()
        if wrote:
            log_debug(
                f"Updated cooldown_timer to {seconds} seconds in production database (LEGACY)"
            )
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error updating cooldown_timer: {e}")

def update_auto_entry_status_in_db(status):
    """Update auto trade status in the monitor_list table (no-op when unchanged)."""
    try:
        ident = ctx_ident()
        prev = _previous_auto_trade_status_by_monitor.get(ident)
        if prev == status:
            return
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

        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Update the monitor's auto_trade_status field (this is what the frontend reads)
            cursor.execute(
                f"UPDATE {_aes_monitor_list_table()} SET auto_trade_status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (status, ctx_mid())
            )
            conn.commit()
        conn.close()

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
        from backend.core.high_water_scalp import is_expiration_scalp_entry_strategy

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
        elif is_expiration_scalp_entry_strategy(strategy):
            return determine_auto_entry_status_expiration_scalp()
        else:
            # Default to Hourly HTC (including fallback)
            return determine_auto_entry_status_hourly_htc()
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_hourly_htc(*, expiration_scalp: bool = False):
    """Determine the current auto entry status for Hourly HTC (or Expiration Scalp when flagged)."""
    log_tag = "[AUTO ENTRY EXPIRATION SCALP]" if expiration_scalp else "[AUTO ENTRY HTC]"
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
        required_settings = ["min_time", "max_time", "min_probability", "max_probability"]
        if not expiration_scalp:
            required_settings.append("min_differential")
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        
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
        log(f"{log_tag} ❌ Error determining status: {e}")
        return "DISABLED"


def determine_auto_entry_status_expiration_scalp():
    """Expiration Scalp: same ACTIVE/INACTIVE rules as Hourly HTC (TTC window only)."""
    return determine_auto_entry_status_hourly_htc(expiration_scalp=True)

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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        
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
        
        # Authoritative elapsed from cooldown_start_time (not throttled cooldown_timer display).
        time_since_spike = _aes_time_since_spike_seconds()
        if time_since_spike is None:
            return "INACTIVE"
        
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

    Pool membership matches the fire path (``_aes_list_lane_monitor_rows``):
    cutout AES only BTC 15m Expiration Scalp; unified excludes those rows.
    """
    try:
        if AES_UNIFIED_POOL:
            for r in _aes_list_lane_monitor_rows():
                u = r["user_number"]
                m = r["monitor_id"]
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
        from backend.core.tradeflow_monitor_settings_cache import get_cached_monitor_settings

        def _load():
            import psycopg2

            conn = get_db_connection()
            if not conn:
                log(
                    f"[AUTO ENTRY] ❌ No database connection available when reading auto_trade for monitor {ctx_mid()}; shutting down supervisor"
                )
                os._exit(0)
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT auto_trade FROM {_aes_monitor_list_table()} WHERE id = %s",
                    (ctx_mid(),),
                )
                result = cursor.fetchone()
            if not result:
                log(
                    f"[AUTO ENTRY] ❌ Monitor {ctx_mid()} missing from {_aes_monitor_list_table()}; "
                    "shutting down supervisor to avoid ghost auto-entry"
                )
                os._exit(0)
            return bool(result[0])

        return bool(get_cached_monitor_settings(ctx_user(), ctx_mid(), _load))
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error reading auto_trade from monitor_list for monitor {ctx_mid()}: {e}")
        os._exit(0)

def is_reverse_monitor():
    """True when monitor_list.reverse is enabled for this monitor."""
    if AES_UNIFIED_POOL and _aes_bind_m.get() is None:
        return False
    try:
        from backend.core.tradeflow_monitor_settings_cache import get_cached_monitor_bool

        def _load():
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT reverse FROM {_aes_monitor_list_table()} WHERE id = %s",
                    (ctx_mid(),),
                )
                result = cursor.fetchone()
            conn.close()
            return bool(result[0]) if result and result[0] is not None else False

        return bool(get_cached_monitor_bool(ctx_user(), ctx_mid(), "reverse", _load))
    except Exception as e:
        log(f"[AUTO ENTRY] Error reading reverse from monitor_list for monitor {ctx_mid()}: {e}")
        return False


def get_effective_trade_strategy():
    """Strategy name for logs/trades; prefixes Reverse when monitor reverse mode is on."""
    from backend.core.monitor_reverse_mode import effective_trade_strategy

    return effective_trade_strategy(get_trade_strategy(), is_reverse_monitor())


def get_auto_entry_settings():
    """Get auto entry settings from monitor's assigned strategy"""
    global previous_settings
    cache_key = f"{ctx_user()}:{ctx_mid()}"
    now = time.monotonic()
    with _aes_settings_mem_lock:
        hit = _aes_settings_mem_cache.get(cache_key)
        if hit and (now - hit[0]) <= _AES_MEM_CACHE_TTL_SEC:
            return dict(hit[1])
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
                           min_cooldown_timer, max_cooldown_timer, min_ask_range,
                           min_movement, max_movement,
                           entry_verification_period_enabled, entry_verification_period_seconds,
                           min_buffer_pct
                    """
                    + (sel_flip if has_flip else "")
                    + f"""
                    FROM {_aes_monitor_list_table()} WHERE id = %s
                    """,
                    (ctx_mid(),),
                )
                strategy_result = cursor.fetchone()
                
                if strategy_result:
                    def _f(v):
                        return float(v) if v is not None else None

                    def _i(v):
                        return int(v) if v is not None else None

                    def _b(v):
                        return bool(v) if v is not None else None

                    # Pass-through from monitor_list only — never invent strategy/UI defaults.
                    settings = {
                        "min_probability": _f(strategy_result[0]),
                        "max_probability": _f(strategy_result[1]),
                        "min_differential": _f(strategy_result[2]),
                        "max_differential": _f(strategy_result[3]),
                        "min_time": _i(strategy_result[4]),
                        "max_time": _i(strategy_result[5]),
                        "allow_re_entry": _b(strategy_result[6]),
                        "spike_alert_enabled": _b(strategy_result[7]),
                        "spike_alert_momentum_threshold": strategy_result[8],
                        "spike_alert_cooldown_threshold": strategy_result[9],
                        "spike_alert_cooldown_minutes": strategy_result[10],
                        "min_volume": strategy_result[11],
                        "momentum_scalp_entry_threshold": _f(strategy_result[12]),
                        "min_ask": _f(strategy_result[13]),
                        "max_ask": _f(strategy_result[14]),
                        "max_price_spread": _f(strategy_result[15]),
                        "prob_adj": _f(strategy_result[16]),
                        "min_cooldown_timer": strategy_result[17],
                        "max_cooldown_timer": strategy_result[18],
                        "min_ask_range": _f(strategy_result[19]),
                        "min_movement": _f(strategy_result[20]),
                        "max_movement": _f(strategy_result[21]),
                        "entry_verification_period_enabled": _b(strategy_result[22]),
                        "entry_verification_period_seconds": _i(strategy_result[23]),
                        "min_buffer_pct": _f(strategy_result[24]),
                    }
                    flip_base = 25
                    if has_flip:
                        settings["flip_sell_prob"] = _b(strategy_result[flip_base])
                        settings["flip_sell_prob_mult"] = strategy_result[flip_base + 1]
                        settings["flip_sell_floor"] = _b(strategy_result[flip_base + 2])
                        settings["flip_sell_floor_mult"] = strategy_result[flip_base + 3]
                    else:
                        settings["flip_sell_prob"] = None
                        settings["flip_sell_prob_mult"] = None
                        settings["flip_sell_floor"] = None
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
                    with _aes_settings_mem_lock:
                        _aes_settings_mem_cache[cache_key] = (time.monotonic(), dict(settings))
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

def _ttc_fallback_seconds(market: str) -> int:
    """Wall-clock seconds to next contract boundary when ladder TTC is unavailable."""
    now = est_now()
    mkt = (market or "hourly").strip().lower()
    if mkt == "15m":
        minute = now.minute
        next_15 = (minute // 15 + 1) * 15
        if next_15 >= 60:
            next_boundary = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_boundary = now.replace(minute=next_15, second=0, microsecond=0)
        return max(1, int((next_boundary - now).total_seconds()))
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(1, int((next_hour - now).total_seconds()))

def get_current_ttc():
    """Get current TTC from live_state strike ladder (no PostgreSQL on hot path)."""
    try:
        current_symbol, current_market = get_current_monitor_symbol_and_market()
        if not current_market or current_market not in ("hourly", "15m"):
            return 0
        ctx = _aes_unified_tick_context.get()
        snap_age = None
        if ctx and ctx.get("captured_mono") is not None:
            try:
                snap_age = max(0.0, time.monotonic() - float(ctx["captured_mono"]))
            except (TypeError, ValueError):
                snap_age = None
        if ctx and ctx.get("data") is not None:
            if ctx.get("symbol") == current_symbol and ctx.get("market") == current_market:
                from backend.core.tradeflow_live_reads import ttc_seconds_from_ladder

                ttc_val = ttc_seconds_from_ladder(
                    ctx["data"],
                    current_market,
                    snap_age_sec=snap_age,
                )
                if ttc_val is not None:
                    return int(ttc_val)
        from backend.core.tradeflow_live_reads import strike_ladder, ttc_seconds_from_ladder

        ladder = strike_ladder(
            current_symbol,
            current_market,
            _strike_data_exchange_key(),
        )
        ttc_val = ttc_seconds_from_ladder(ladder, current_market)
        if ttc_val is not None:
            return int(ttc_val)
        return _ttc_fallback_seconds(current_market)
    except Exception as e:
        log(f"[AUTO ENTRY] get_current_ttc fallback after error: {e}")
        return _ttc_fallback_seconds(current_market if "current_market" in locals() else "hourly")

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
    """Load ladder from live_state when enabled (no PostgreSQL fallback on hot path)."""
    try:
        from backend.core.tradeflow_live_reads import strike_ladder

        return strike_ladder(
            current_symbol,
            current_market,
            _strike_data_exchange_key(),
        )
    except Exception as e:
        log(f"[AUTO_ENTRY] Error reading master strike table data: {e}")
        return None


def _fetch_ttc_15m_latest_header(current_symbol: str) -> Optional[int]:
    """TTC from hourly live_state ladder when header omits ``ttc_15m``."""
    try:
        from backend.core.tradeflow_live_reads import strike_ladder, ttc_seconds_from_ladder

        ladder = strike_ladder(
            current_symbol, "hourly", _strike_data_exchange_key()
        )
        return ttc_seconds_from_ladder(ladder, "hourly")
    except Exception:
        return None


def _fetch_ttc_native_15m_latest_header(current_symbol: str) -> Optional[int]:
    """TTC from 15m live_state ladder when snapshot omits ``ttc``."""
    try:
        from backend.core.tradeflow_live_reads import strike_ladder, ttc_seconds_from_ladder

        ladder = strike_ladder(current_symbol, "15m", _strike_data_exchange_key())
        return ttc_seconds_from_ladder(ladder, "15m")
    except Exception:
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
    cache_key = f"{ctx_user()}:{ctx_mid()}"
    now = time.monotonic()
    with _aes_settings_mem_lock:
        hit = _aes_strategy_mem_cache.get(cache_key)
        if hit and (now - hit[0]) <= _AES_MEM_CACHE_TTL_SEC:
            return hit[1]
    conn = None
    try:
        import psycopg2
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT strategy FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
            result = cursor.fetchone()
            if result:
                trade_strategy = result[0]
                with _aes_settings_mem_lock:
                    _aes_strategy_mem_cache[cache_key] = (time.monotonic(), trade_strategy)
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
        from backend.core.tradeflow_live_reads import symbol_spot_price, tradeflow_requires_live_state

        spot = symbol_spot_price(sym)
        if spot is None and not tradeflow_requires_live_state():
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

    if _aes_refuse_stale_fire("pre_pipeline"):
        return False
    
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
                    try:
                        from backend.core.tradeflow_decision_trace import trace as _dtrace

                        _dtrace(
                            "aes_fire_blocked",
                            monitor=ctx_mid(),
                            reason="pipeline_gate",
                            detail=reason,
                            strike=strike_data.get("strike"),
                            side=strike_data.get("side"),
                        )
                    except Exception:
                        pass
                    return False
            except Exception as gate_err:
                log(f"[AUTO ENTRY] 🚫 BLOCKED by pipeline gate check error: {gate_err}")
                try:
                    if conn:
                        conn.close()
                except Exception:
                    pass
                try:
                    from backend.core.tradeflow_decision_trace import trace as _dtrace

                    _dtrace(
                        "aes_fire_blocked",
                        monitor=ctx_mid(),
                        reason="pipeline_gate_error",
                        detail=str(gate_err)[:120],
                    )
                except Exception:
                    pass
                return False

        if _aes_refuse_stale_fire("post_pipeline"):
            return False

        ok_spot, spot_reason = _auto_entry_strike_vs_spot_gate(
            strike_data, (current_symbol or "").strip().upper()
        )
        if not ok_spot:
            log(
                f"[AUTO ENTRY] BLOCKED by strike vs live spot gate symbol={current_symbol} "
                f"strike={strike_data.get('strike')} reason={spot_reason}"
            )
            try:
                from backend.core.tradeflow_decision_trace import trace as _dtrace

                _dtrace(
                    "aes_fire_blocked",
                    monitor=ctx_mid(),
                    reason="strike_vs_spot",
                    detail=spot_reason,
                    strike=strike_data.get("strike"),
                    side=strike_data.get("side"),
                )
            except Exception:
                pass
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
            "live_loss_market_wide_1c",
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

        if strike_data.get("half_size") or strike_data.get("size_mode") == "half":
            half_sz = max(1, int(round(float(position_size) * 0.5)))
            log(
                f"[AUTO ENTRY] Expiration Scalp half-size (out-of-prob, in-movement): "
                f"{position_size} -> {half_sz}"
            )
            position_size = half_sz
        
        # Get bankroll allotment from monitor configuration
        bankroll_allotment = get_bankroll_allotment()
        if bankroll_allotment is None:
            log(f"[AUTO ENTRY] ❌ Cannot trigger trade - no valid bankroll allotment found")
            return False

        from backend.core.monitor_reverse_mode import apply_reverse_to_strike_data

        reverse = is_reverse_monitor()
        if reverse:
            orig_side = strike_data.get("side")
            strike_data = apply_reverse_to_strike_data(
                strike_data, strike_table_data, reverse=True
            )
            elp = strike_data.get("entry_limit_price")
            if elp is not None:
                try:
                    strike_data["buy_price"] = float(elp)
                except (TypeError, ValueError):
                    pass
            log(
                f"[AUTO ENTRY] REVERSE mode — dispatch opposite side "
                f"{orig_side} → {strike_data.get('side')} @ {strike_data.get('buy_price')}"
            )

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
        trade_strategy = get_effective_trade_strategy()
        
        # Get paper_trade + min_slippage gate settings from monitor config
        paper_trade = False
        min_slippage = 0.0000
        try:
            import psycopg2
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT paper_trade, min_slippage FROM {_aes_monitor_list_table()} WHERE id = %s", (ctx_mid(),))
                result = cursor.fetchone()
                if result and result[0] is not None:
                    paper_trade = bool(result[0])
                if result and result[1] is not None:
                    try:
                        ms = float(result[1])
                        min_slippage = round(ms, 4) if ms < 0 else 0.0000
                    except (TypeError, ValueError):
                        min_slippage = 0.0000
            conn.close()
        except Exception as e:
            log(f"[AUTO ENTRY] ⚠️ Could not get paper_trade/min_slippage setting: {e}, defaulting to False/0.0000")
        from backend.trading_mode import effective_paper_trade

        paper_trade = effective_paper_trade(paper_trade)
        
        # Market interval must travel with the ticket so TM pipeline gate keys the
        # matching strike_pipeline_health row (15m must never consult hourly).
        market_for_ticket = (current_market or "").strip().lower()
        if market_for_ticket not in ("15m", "hourly"):
            market_for_ticket = None

        # Prepare the trade data exactly like trade_initiator does (count_fp for full-chain consistency)
        trade_payload = {
            "ticket_id": ticket_id,
            "status": "pending",
            "date": eastern_date,
            "time": eastern_time,
            "symbol": current_symbol,
            "market": market_for_ticket,
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
            "paper_trade": paper_trade,
            "min_slippage": min_slippage
        }
        
        if _aes_refuse_stale_fire("pre_submit"):
            return False

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

            try:
                from backend.core.tradeflow_decision_trace import trace as _dtrace

                _dtrace(
                    "aes_fire",
                    monitor=ctx_mid(),
                    ticket_id=ticket_id,
                    strike=strike_data.get("strike"),
                    side=strike_data.get("side"),
                    ticker=strike_data.get("ticker"),
                    via="redis" if redis_published else "http",
                    ok=True,
                )
            except Exception:
                pass

            return True
        log(f"[AUTO ENTRY] ❌ Trade initiation failed: {response.status_code} - {getattr(response, 'text', '')}")
        try:
            from backend.core.tradeflow_decision_trace import trace as _dtrace

            _dtrace(
                "aes_fire",
                monitor=ctx_mid(),
                strike=strike_data.get("strike"),
                side=strike_data.get("side"),
                ticker=strike_data.get("ticker"),
                ok=False,
                http_status=response.status_code,
            )
        except Exception:
            pass
        return False
        
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error initiating trade via trade_manager: {e}")
        try:
            from backend.core.tradeflow_decision_trace import trace as _dtrace

            _dtrace(
                "aes_fire",
                monitor=ctx_mid(),
                strike=strike_data.get("strike"),
                side=strike_data.get("side"),
                ok=False,
                error=str(e)[:120],
            )
        except Exception:
            pass
        return False
    finally:
        if AES_UNIFIED_PROFILE and AES_UNIFIED_POOL:
            _unified_profile_state["trigger_trade_sec"] += time.perf_counter() - t_trig

def strike_on_trade_cooldown(strike_key, now=None):
    """True if this strike/side is inside TRADE_COOLDOWN. Does not claim."""
    current_time = time.time() if now is None else float(now)
    last = last_trade_times.get(strike_key)
    if last is None:
        return False
    return (current_time - last) < TRADE_COOLDOWN


def can_trade_strike(strike_key):
    """ATOMIC: Claim TRADE_COOLDOWN if the strike is free.

    Expiration Scalp claims at fire only. Other strategies still claim on look.
    """
    current_time = time.time()

    if strike_on_trade_cooldown(strike_key, now=current_time):
        try:
            from backend.core.tradeflow_decision_trace import trace as _dtrace

            last = last_trade_times.get(strike_key)
            _dtrace(
                "aes_cooldown_skip",
                monitor=ctx_mid(),
                strike_key=strike_key,
                age_s=round(current_time - last, 3) if last is not None else None,
                cooldown_s=TRADE_COOLDOWN,
            )
        except Exception:
            pass
        return False

    last_trade_times[strike_key] = current_time
    return True


def _exp_scalp_retain_verify_during_cooldown(strike_key, seen_verify_keys, dedupe_key) -> bool:
    """If cooling down, keep verify dwell and skip the rest of this pass.

    TRADE_COOLDOWN is anti-double-fire, not a product gate. A look-skip that
    omits the key from seen_verify_keys used to abort as not_eligible_this_pass
    and zero contiguous dwell whenever evals landed <1s apart.
    """
    if not strike_on_trade_cooldown(strike_key):
        return False
    seen_verify_keys.add(dedupe_key)
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

    Statuses counted as blocking: open, pending, partial, closing (anything not yet terminal).
    Side comparison is canonicalized so DB ``Y`` matches strike_data ``yes`` (prior bug: never matched).
    """
    try:
        current_monitor = f"mon_{ctx_user()}_{ctx_mid()}"
        ticker = strike_data.get("ticker")
        reverse = is_reverse_monitor()
        from backend.core.monitor_reverse_mode import executed_side_for_dedupe

        want_side = _aes_side_bucket_for_dedupe(
            executed_side_for_dedupe(strike_data.get("side"), reverse=reverse)
        )
        if not ticker or not want_side:
            return False

        warm = _aes_open_ticker_sides.get()
        if warm is not None:
            return (str(ticker), want_side) in warm

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            f"""
            SELECT id, ticker, side, status
            FROM {_aes_trades_table()}
            WHERE status IN ('open', 'pending', 'partial', 'closing')
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


def _aes_prime_open_ticker_sides_cache() -> None:
    """One PG read of in-flight (ticker, side) pairs for the current monitor bind."""
    try:
        current_monitor = f"mon_{ctx_user()}_{ctx_mid()}"
        conn = get_db_connection()
        if not conn:
            _aes_open_ticker_sides.set(set())
            return
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT ticker, side
                    FROM {_aes_trades_table()}
                    WHERE status IN ('open', 'pending', 'partial', 'closing')
                      AND monitor = %s
                    """,
                    (current_monitor,),
                )
                warm: Set[Tuple[str, str]] = set()
                for trade_ticker, trade_side in cursor.fetchall():
                    if not trade_ticker:
                        continue
                    bucket = _aes_side_bucket_for_dedupe(trade_side)
                    if bucket:
                        warm.add((str(trade_ticker), bucket))
                _aes_open_ticker_sides.set(warm)
        finally:
            conn.close()
    except Exception as e:
        log_debug(f"[AES] open ticker cache prime failed: {e}")
        _aes_open_ticker_sides.set(set())


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


# Momentum Contain only: hourly contract aliases (e.g. BTC 11:00am vs BTC 11am) must not
# reset cycle state or miss in-flight bracket checks on unified AES.
_MC_HOURLY_CONTRACT_COLON_ZERO = re.compile(
    r"^(\S+)\s+(\d{1,2}):00\s*(am|pm)$", re.IGNORECASE
)


def _mc_normalize_hourly_contract(contract: Optional[str]) -> Optional[str]:
    """Collapse erroneous 15m-style :00 labels to hourly form for MC cycle keys."""
    if not contract:
        return contract
    text = contract.strip()
    m = _MC_HOURLY_CONTRACT_COLON_ZERO.match(text)
    if m:
        return f"{m.group(1).upper()} {m.group(2)}{m.group(3).lower()}"
    return text


def _mc_strike_row_for_ticker(strikes: List[Dict[str, Any]], ticker: Optional[str]) -> Optional[Dict[str, Any]]:
    if not ticker:
        return None
    want = str(ticker).strip()
    for row in strikes:
        if str(row.get("ticker") or "").strip() == want:
            return row
    return None


def _momentum_contain_open_auto_entry_legs(
    contract: Optional[str],
) -> Tuple[int, int, int]:
    """In-flight auto_entry legs for this monitor on the normalized hourly contract.

    Returns (total, yes_count, no_count).
    """
    norm = _mc_normalize_hourly_contract(contract)
    if not norm:
        return 0, 0, 0
    try:
        conn = get_db_connection()
        if not conn:
            return 0, 0, 0
        current_monitor = f"mon_{ctx_user()}_{ctx_mid()}"
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT side
                FROM {_aes_trades_table()}
                WHERE status IN ('open', 'pending', 'partial', 'closing')
                  AND monitor = %s
                  AND contract = %s
                  AND entry_method = 'auto_entry'
                """,
                (current_monitor, norm),
            )
            rows = cursor.fetchall()
        conn.close()
        yes_c = 0
        no_c = 0
        for (side_val,) in rows:
            bucket = _aes_side_bucket_for_dedupe(side_val)
            if bucket == "yes":
                yes_c += 1
            elif bucket == "no":
                no_c += 1
        return len(rows), yes_c, no_c
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Error counting open auto_entry legs: {e}")
        return 0, 0, 0


def _momentum_contain_cycle_bracket_satisfied(
    contract: Optional[str], strike_tier: Optional[int] = None
) -> bool:
    """MC-only: bracket complete if two in-flight legs exist or legacy bracket distance matches."""
    total, yes_c, no_c = _momentum_contain_open_auto_entry_legs(contract)
    if total >= 2 and yes_c >= 1 and no_c >= 1:
        return True
    norm = _mc_normalize_hourly_contract(contract)
    if norm and strike_tier:
        return has_bracket_for_cycle(contract=norm, strike_tier=strike_tier)
    return False


def _momentum_contain_reset_cycle_state(state: Dict[str, Any], norm_contract: Optional[str]) -> None:
    state["entered"] = False
    state["contract"] = norm_contract
    state["locked_above_ticker"] = None
    state["locked_below_ticker"] = None


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
            "symbol": current_symbol, "market": "15m", "exchange": "kalshi",
            "trade_strategy": get_effective_trade_strategy(),
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
        prob_adj = float(settings["prob_adj"]) if settings.get("prob_adj") is not None else None
        spike_alert_active = _aes_indicator_bucket().get("spike_alert_active", False)
        min_p = base_min_p + prob_adj if spike_alert_active and prob_adj is not None else base_min_p
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


def _aes_list_lane_monitor_rows() -> List[dict]:
    """Active monitors owned by this AES process (cutout membership or general excl. cutout).

    Short TTL cache: ladder wakes still evaluate every tick; only the membership
    query is coalesced so we do not hit PG twice (15m+hourly) on every wake.

    Lane bind fanout only includes ``auto_trade=true`` rows (disabled monitors
    get status via toggle / periodic_status_sync, not every ladder tick).
    """
    global _aes_lane_monitor_rows_cache, _aes_lane_monitor_rows_at
    now = time.monotonic()
    ttl = _AES_LANE_MONITOR_ROWS_TTL_SEC
    if _aes_lane_monitor_rows_cache is not None and (now - _aes_lane_monitor_rows_at) < ttl:
        return _aes_lane_monitor_rows_cache

    from backend.core.aes_btc15m_exp_scalp_cutout import (
        filter_out_cutout_rows,
        list_active_btc15m_exp_scalp_cutout_rows,
    )

    if AES_BTC15M_EXP_SCALP:
        rows = list_active_btc15m_exp_scalp_cutout_rows()
    elif AES_UNIFIED_15M:
        from backend.core.unified_15m_monitors import list_active_15m_monitor_rows

        rows = filter_out_cutout_rows(list_active_15m_monitor_rows())
    elif AES_UNIFIED_HOURLY:
        from backend.core.unified_hourly_monitors import list_active_hourly_monitor_rows

        rows = list_active_hourly_monitor_rows()
    elif AES_UNIFIED_ALL:
        from backend.core.unified_all_monitors import list_active_unified_monitor_rows

        rows = filter_out_cutout_rows(list_active_unified_monitor_rows())
    else:
        rows = []
    rows = [r for r in rows if r.get("auto_trade") is True]
    _aes_lane_monitor_rows_cache = rows
    _aes_lane_monitor_rows_at = now
    return rows


def _aes_lane_parallelism() -> int:
    raw = os.getenv("AES_LANE_PARALLELISM", "12").strip()
    try:
        return max(1, min(int(raw), 64))
    except (TypeError, ValueError):
        return 12


def _aes_refuse_stale_fire(stage: str) -> bool:
    """
    Observe whether the lane gen advanced during a fire path.

    Default: do **not** abort — once AES decided to enter on the snap it
    evaluated, hand the ticket to TM. Latest-only applies to which snap gets
    *evaluated*, not to killing a fire mid-handoff.

    Set ``AES_REFUSE_STALE_FIRE=1`` (or ``TRADEFLOW_REFUSE_STALE_FIRE=1``) to
    restore hard refuse when the mailbox gen has advanced.
    """
    guard = _aes_lane_fire_guard.get()
    if not guard:
        return False
    lane = guard.get("lane")
    epoch = guard.get("epoch")
    gid = guard.get("generation_id")
    if lane is None or epoch is None or not gid:
        return False
    if lane.is_current(int(epoch), str(gid)):
        return False
    refuse = os.getenv("AES_REFUSE_STALE_FIRE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ) or os.getenv("TRADEFLOW_REFUSE_STALE_FIRE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    try:
        from backend.core.tradeflow_decision_trace import trace as _dtrace

        _dtrace(
            "aes_fire_blocked" if refuse else "aes_fire_stale_notice",
            monitor=ctx_mid(),
            reason="stale_generation",
            stage=stage,
            generation_id=gid,
            epoch=epoch,
            refuse=1 if refuse else 0,
        )
    except Exception:
        pass
    if refuse:
        log(
            f"[AUTO ENTRY] 🚫 BLOCKED stale fire stage={stage} monitor={ctx_mid()} "
            f"gen={gid} epoch={epoch}"
        )
        return True
    log(
        f"[AUTO ENTRY] ⚠️ stale gen during fire (continuing handoff) stage={stage} "
        f"monitor={ctx_mid()} gen={gid} epoch={epoch}"
    )
    return False


def _aes_lane_bind_worker(u: str, m: str, slot, lane) -> None:
    if not lane.is_current(slot.epoch, slot.generation_id):
        return
    guard_tok = _aes_lane_fire_guard.set(
        {
            "lane": lane,
            "epoch": slot.epoch,
            "generation_id": slot.generation_id,
        }
    )
    tick_tok = _aes_unified_tick_context.set(
        {
            "symbol": slot.symbol,
            "market": slot.market,
            "data": slot.snap,
            "captured_mono": getattr(slot, "captured_mono", None),
        }
    )
    tw0 = time.perf_counter()
    strat = ""
    auto_on = False
    open_tok = _aes_open_ticker_sides.set(None)
    try:
        with aes_monitor_bind(u, m):
            if not lane.is_current(slot.epoch, slot.generation_id):
                return
            strat = get_trade_strategy()
            auto_on = is_auto_trade_enabled()
            if not auto_on:
                update_auto_entry_status_in_db("DISABLED")
                return
            # Out-of-window: status only (no open-ticker PG prime / strike scan).
            if _aes_ttc_outside_entry_window():
                update_auto_entry_status_in_db(determine_auto_entry_status())
                return
            _aes_prime_open_ticker_sides_cache()
            ms, mm = get_current_monitor_symbol_and_market()
            if ms != slot.symbol or mm != slot.market:
                inner = _aes_unified_tick_context.set(None)
                try:
                    _check_auto_entry_conditions_impl()
                finally:
                    _aes_unified_tick_context.reset(inner)
            else:
                _check_auto_entry_conditions_impl()
    finally:
        _aes_open_ticker_sides.reset(open_tok)
        _aes_unified_tick_context.reset(tick_tok)
        _aes_lane_fire_guard.reset(guard_tok)
        try:
            from backend.core.tradeflow_decision_trace import (
                decision_trace_enabled as _dtrace_on,
                trace as _dtrace,
            )

            if _dtrace_on():
                _dtrace(
                    "aes_monitor_done",
                    user=u,
                    monitor=m,
                    strategy=strat,
                    auto_trade=auto_on,
                    wall_s=round(time.perf_counter() - tw0, 4),
                    symbol=slot.symbol,
                    market=slot.market,
                    generation_id=slot.generation_id,
                    cutout=1 if AES_BTC15M_EXP_SCALP else 0,
                )
        except Exception:
            pass


def _aes_ttc_outside_entry_window() -> bool:
    """True when settings exist and current TTC is outside min_time..max_time."""
    try:
        settings = get_auto_entry_settings()
        if not settings:
            return False
        if settings.get("min_time") is None or settings.get("max_time") is None:
            return False
        min_time = int(settings["min_time"])
        max_time = int(settings["max_time"])
        ttc = int(get_current_ttc())
        return not (min_time <= ttc <= max_time)
    except Exception:
        return False


def _aes_cheap_status_pass() -> None:
    """
    Update ACTIVE/INACTIVE from cached lane snaps (aged TTC) without Redis fetch
    or strike scans. Keeps Exp Scalp window opens on time without failsafe_all.
    """
    if not AES_UNIFIED_POOL:
        return
    try:
        hub = _aes_ensure_lane_hub()
    except Exception:
        return
    rows_by_ladder: Dict[Tuple[str, str], List[dict]] = {}
    try:
        for r in _aes_list_lane_monitor_rows():
            key = (
                (r.get("symbol") or "BTC").strip().upper() or "BTC",
                (r.get("market") or "").strip().lower(),
            )
            if key[1] not in ("hourly", "15m"):
                continue
            rows_by_ladder.setdefault(key, []).append(r)
    except Exception:
        return
    for (sym, mkt), rows in rows_by_ladder.items():
        try:
            lane = hub.lane(sym, mkt)
            cur = lane.current()
            if cur is None or not cur.snap:
                continue
            for r in rows:
                u = r["user_number"]
                mid = r["monitor_id"]
                tick_tok = _aes_unified_tick_context.set(
                    {
                        "symbol": sym,
                        "market": mkt,
                        "data": cur.snap,
                        "captured_mono": getattr(cur, "captured_mono", None),
                    }
                )
                try:
                    with aes_monitor_bind(u, mid):
                        update_auto_entry_status_in_db(determine_auto_entry_status())
                except Exception:
                    pass
                finally:
                    _aes_unified_tick_context.reset(tick_tok)
        except Exception:
            continue


def _aes_evaluate_lane(slot, lane) -> None:
    hub = _aes_ensure_lane_hub()
    rows = [
        r
        for r in _aes_list_lane_monitor_rows()
        if (r.get("symbol") or "").strip().upper() == slot.symbol
        and (r.get("market") or "").strip().lower() == slot.market
    ]
    bindings = [(r["user_number"], r["monitor_id"]) for r in rows]
    try:
        from backend.core.tradeflow_decision_trace import (
            decision_trace_enabled as _dtrace_on,
            ladder_identity_with_envelope as _dtrace_ladder_id,
            trace as _dtrace,
        )

        if _dtrace_on():
            ident = _dtrace_ladder_id(
                exchange=_strike_data_exchange_key(),
                symbol=slot.symbol,
                market=slot.market,
                snap=slot.snap,
            )
            _dtrace(
                "aes_ladder",
                symbol=slot.symbol,
                market=slot.market,
                monitors=len(bindings),
                generation_id=slot.generation_id,
                epoch=slot.epoch,
                cutout=1 if AES_BTC15M_EXP_SCALP else 0,
                monitors_csv=",".join(sorted({b[1] for b in bindings})),
                **ident,
            )
    except Exception:
        pass
    hub.run_bindings_parallel(
        lane=lane,
        slot=slot,
        bindings=bindings,
        worker=_aes_lane_bind_worker,
    )


def _aes_ensure_lane_hub():
    global _aes_lane_hub
    with _aes_lane_hub_lock:
        if _aes_lane_hub is not None:
            return _aes_lane_hub
        from backend.core.tradeflow_latest_only_lane import LatestOnlyLaneHub

        def _keys():
            return _aes_active_pool_ladder_keys()

        _aes_lane_hub = LatestOnlyLaneHub(
            service=f"aes_{MONITOR_IDENTIFIER}",
            fetch_snap=_fetch_master_strike_table_data,
            evaluate_lane=_aes_evaluate_lane,
            ladder_keys=_keys,
            parallelism=_aes_lane_parallelism(),
        )
        return _aes_lane_hub


def check_auto_entry_conditions():
    """Check if auto entry conditions are met and trigger trades - routes to strategy-specific logic"""
    if AES_UNIFIED_POOL:
        try:
            hub = _aes_ensure_lane_hub()
            hub.failsafe_refresh_all()
        except Exception as e:
            import traceback

            if AES_BTC15M_EXP_SCALP:
                pool_n = "btc15m_exp_scalp"
            elif AES_UNIFIED_ALL:
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
        from backend.core.high_water_scalp import is_expiration_scalp_entry_strategy

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
            skip_sim = strategy in (
                "Momentum Breakout",
                "Momentum Contain",
            ) or is_expiration_scalp_entry_strategy(strategy)
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
        elif is_expiration_scalp_entry_strategy(strategy):
            check_auto_entry_conditions_expiration_scalp()
        else:
            # Default to Hourly HTC (including fallback)
            check_auto_entry_conditions_hourly_htc()
    except Exception as e:
        import traceback
        log(f"[AUTO ENTRY] ❌ Error checking entry conditions: {e}")
        log(f"[AUTO ENTRY] ❌ Traceback: {traceback.format_exc()}")

def check_auto_entry_conditions_hourly_htc():
    """Check if auto entry conditions are met and trigger trades for Hourly HTC strategy"""
    log_tag = "[AUTO ENTRY]"
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
            try:
                from backend.core.tradeflow_decision_trace import trace as _dtrace

                _dtrace("aes_gate", monitor=ctx_mid(), strategy="Hourly HTC", reason="auto_trade_off")
            except Exception:
                pass
            return
        
        # Get auto entry settings - NO DEFAULTS
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_probability", "max_probability", "min_differential"]
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        if missing_settings:
            log(f"{log_tag} ❌ Missing required settings: {missing_settings}")
            log(f"{log_tag} Cannot proceed without complete settings configuration")
            try:
                from backend.core.tradeflow_decision_trace import trace as _dtrace

                _dtrace(
                    "aes_gate",
                    monitor=ctx_mid(),
                    strategy="Hourly HTC",
                    reason="missing_settings",
                    missing=",".join(missing_settings),
                )
            except Exception:
                pass
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        base_min_probability = settings["min_probability"]
        max_probability = settings["max_probability"]
        min_differential = settings["min_differential"]
        
        # Apply prob_adj adjustment during spike alert cooldown
        prob_adj = settings.get("prob_adj")
        if spike_alert_active and prob_adj is not None:
            min_probability = base_min_probability + prob_adj
            log_debug(f"{log_tag} 📊 Using adjusted probability: {base_min_probability:.2f} + {prob_adj:.2f} = {min_probability:.2f}% (spike cooldown active)")
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
                label = "Hourly HTC"
                log(
                    f"{log_tag} ⏸️ {label}: TTC outside window | ttc={current_ttc}s "
                    f"allowed={min_time}-{max_time}s (no scans until TTC is in range)"
                )
                check_auto_entry_conditions_hourly_htc.last_ttc_log = current_time
            try:
                from backend.core.tradeflow_decision_trace import trace as _dtrace

                _dtrace(
                    "aes_gate",
                    monitor=ctx_mid(),
                    strategy="Hourly HTC",
                    reason="ttc_outside_window",
                    ttc=current_ttc,
                    min_time=min_time,
                    max_time=max_time,
                )
            except Exception:
                pass
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
                    _sg = "strike_table_generator_ws_15m"
                else:
                    _mh = "live_data.market_kalshi_hourly"
                    _sg = "strike_table_generator_ws_hourly"
                log(
                    f"[AUTO ENTRY] ⚠️ No strike ladder in live_data.{_tn} for exchange={_ex} symbol={_sym.upper()}. "
                    f"Upstream: {_mh} must have event_ticker; then {_sg} writes rows. "
                    f"Check those logs for rollover gaps."
                )
                check_auto_entry_conditions_hourly_htc.last_strike_table_log = current_time
            try:
                from backend.core.tradeflow_decision_trace import trace as _dtrace

                _dtrace(
                    "aes_gate",
                    monitor=ctx_mid(),
                    strategy="Hourly HTC",
                    reason="no_strike_ladder",
                )
            except Exception:
                pass
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
            try:
                from backend.core.tradeflow_decision_trace import trace as _dtrace

                _dtrace(
                    "aes_gate",
                    monitor=ctx_mid(),
                    strategy="Hourly HTC",
                    reason="strikes_missing",
                )
            except Exception:
                pass
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
            log_debug(f"{log_tag} 🔍 Scanning {strike_count} strikes | TTC: {current_ttc}s | Window: {min_time}-{max_time}s | Prob: {prob_display}")
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
                    try:
                        from backend.core.tradeflow_decision_trace import trace_verbose as _dtv

                        _dtv(
                            "aes_strike_skip",
                            monitor=ctx_mid(),
                            strike_key=strike_key,
                            reason="already_traded",
                        )
                    except Exception:
                        pass
                    continue

                # STEP 3: Check probability window (min_probability <= prob <= max_probability)
                prob = strike.get('probability')
                if prob is None or prob < min_probability or prob > max_probability:
                    try:
                        from backend.core.tradeflow_decision_trace import trace_verbose as _dtv

                        _dtv(
                            "aes_strike_skip",
                            monitor=ctx_mid(),
                            strike_key=strike_key,
                            reason="prob_band",
                            prob=prob,
                            min_p=min_probability,
                            max_p=max_probability,
                        )
                    except Exception:
                        pass
                    continue
                
                # STEP 4: Check differential threshold (if applicable)
                if min_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff < (min_differential - 0.5):
                        try:
                            from backend.core.tradeflow_decision_trace import trace_verbose as _dtv

                            _dtv(
                                "aes_strike_skip",
                                monitor=ctx_mid(),
                                strike_key=strike_key,
                                reason="min_differential",
                                diff=diff,
                                floor=float(min_differential) - 0.5,
                            )
                        except Exception:
                            pass
                        continue
                
                # STEP 4.5: Check max differential threshold (if applicable)
                max_differential = settings.get("max_differential")
                if max_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff > max_differential:
                        try:
                            from backend.core.tradeflow_decision_trace import trace_verbose as _dtv

                            _dtv(
                                "aes_strike_skip",
                                monitor=ctx_mid(),
                                strike_key=strike_key,
                                reason="max_differential",
                                diff=diff,
                                cap=max_differential,
                            )
                        except Exception:
                            pass
                        continue
                
                # STEP 5: Check volume threshold
                min_volume = settings.get("min_volume")
                if min_volume is None:
                    continue
                volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
                if volume < min_volume:
                    try:
                        from backend.core.tradeflow_decision_trace import trace_verbose as _dtv

                        _dtv(
                            "aes_strike_skip",
                            monitor=ctx_mid(),
                            strike_key=strike_key,
                            reason="min_volume",
                            volume=volume,
                            min_volume=min_volume,
                        )
                    except Exception:
                        pass
                    continue
                
                # STEP 6: Check max ask price threshold using _dollars values
                max_ask = settings.get("max_ask")
                if max_ask is None:
                    continue
                yes_ask_dollars = strike.get('yes_ask_dollars')
                no_ask_dollars = strike.get('no_ask_dollars')
                if not yes_ask_dollars or not no_ask_dollars:
                    try:
                        from backend.core.tradeflow_decision_trace import trace_verbose as _dtv

                        _dtv(
                            "aes_strike_skip",
                            monitor=ctx_mid(),
                            strike_key=strike_key,
                            reason="missing_asks",
                        )
                    except Exception:
                        pass
                    continue
                max_ask_price = max(float(yes_ask_dollars), float(no_ask_dollars))
                max_ask_limit = float(max_ask) if max_ask < 1 else float(max_ask) / 100.0
                if max_ask_price > max_ask_limit:
                    try:
                        from backend.core.tradeflow_decision_trace import trace_verbose as _dtv

                        _dtv(
                            "aes_strike_skip",
                            monitor=ctx_mid(),
                            strike_key=strike_key,
                            reason="max_ask",
                            max_ask_price=max_ask_price,
                            limit=max_ask_limit,
                        )
                    except Exception:
                        pass
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
                log(f"{log_tag} 🚀 TRIGGERING TRADE | {strike_key} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Ticker: {strike.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"{log_tag} ✅ TRADE SUCCESSFUL | {strike_key} | Trade triggered and sent to trade_manager")
                else:
                    log(f"{log_tag} ❌ TRADE FAILED | {strike_key} | Failed to trigger trade")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"{log_tag} Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"{log_tag} Error checking auto entry conditions: {e}")


def check_auto_entry_conditions_expiration_scalp():
    """Near-expiration: buy the side whose ask and side-aware probability both pass (not active_side/HTC)."""
    log_tag = "[AUTO ENTRY EXPIRATION SCALP]"
    try:
        # Spike-alert path is not gate-binding for Exp Scalp; skip on unified/cutout lanes.
        if not AES_UNIFIED_POOL:
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
                "last_updated": est_now().isoformat(),
            })
            broadcast_auto_entry_indicator_change()
            return

        settings = get_auto_entry_settings()
        required_settings = [
            "min_time",
            "max_time",
            "min_probability",
            "max_probability",
            "min_ask",
            "max_ask",
            "min_movement",
            "max_movement",
            "entry_verification_period_enabled",
            "entry_verification_period_seconds",
        ]
        missing_settings = [
            s for s in required_settings if s not in settings or settings.get(s) is None
        ]
        if missing_settings:
            log(f"{log_tag} ❌ Missing required settings: {missing_settings}")
            return

        from backend.core.high_water_scalp import (
            ask_hits_price_target,
            is_high_water_family,
            parse_limit_close_price,
        )
        from backend.util.auto_entry_expiration_scalp_gates import parse_min_buffer_pct

        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_probability = float(settings["min_probability"])
        max_probability = float(settings["max_probability"])
        min_ask = float(settings["min_ask"])
        max_ask = float(settings["max_ask"])
        min_movement = float(settings["min_movement"])
        max_movement = float(settings["max_movement"])
        min_buffer_pct = parse_min_buffer_pct(settings)
        hws_family = is_high_water_family(get_trade_strategy())
        hws_target = parse_limit_close_price(min_ask) if hws_family else None
        if hws_family and hws_target is None:
            log(f"{log_tag} ❌ High Water missing active-side price target (min_ask)")
            return
        verify_enabled = bool(settings["entry_verification_period_enabled"])
        try:
            verify_seconds = int(settings["entry_verification_period_seconds"])
        except (TypeError, ValueError):
            log(f"{log_tag} ❌ Invalid entry_verification_period_seconds on monitor row")
            return
        verify_seconds = max(0, min(15, verify_seconds))

        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        scanning_active = auto_trade_enabled and service_healthy and ttc_within_window

        _aes_indicator_bucket().update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": spike_alert_active,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": est_now().isoformat(),
        })
        broadcast_auto_entry_indicator_change()

        mon_key = ctx_ident()
        if not ttc_within_window:
            leftover = _exp_scalp_entry_verify_by_monitor.pop(mon_key, None) or {}
            if leftover and verify_enabled:
                now_leave = time.time()
                for (sk, side), prior in leftover.items():
                    try:
                        started = float(prior.get("started_at"))
                        dwell = max(0.0, now_leave - started)
                    except (TypeError, ValueError, AttributeError):
                        dwell = 0.0
                    log(
                        f"{log_tag} VERIFY ABORT | {sk} {str(side).upper()} | "
                        f"dwell={dwell:.1f}s need={verify_seconds}s | reason=ttc_outside_window"
                    )
            return

        if not strike_table_data or "strikes" not in strike_table_data:
            return

        if _aes_refuse_stale_fire("exp_scalp_pre_strikes"):
            return

        movement_pct = strike_table_data.get("movement_percentile")
        try:
            movement_pct_f = float(movement_pct) if movement_pct is not None else None
        except (TypeError, ValueError):
            movement_pct_f = None

        from backend.core.strike_ladder_fetch import probability_from_strike_row_side_aware
        from backend.util.auto_entry_expiration_scalp_gates import (
            ask_dollars_to_cent,
            classify_expiration_scalp_prob_movement,
            exp_scalp_busy_book_enabled,
            exp_scalp_flicker_gate_enabled,
            exp_scalp_flicker_live_band_enabled,
            exp_scalp_flicker_step_cents,
            expiration_scalp_busy_book_gate,
            expiration_scalp_flicker_gate,
            expiration_scalp_min_buffer_pct_gate,
            update_expiration_scalp_entry_verification,
        )

        sym = get_current_monitor_symbol()
        mkt = get_current_monitor_symbol_and_market()[1]
        processed_strikes = set()
        strike_i = 0
        verify_bucket = _exp_scalp_entry_verify_by_monitor.setdefault(mon_key, {})
        seen_verify_keys: set = set()
        now_ts = time.time()

        for strike in strike_table_data["strikes"]:
            strike_i += 1
            if strike_i % 8 == 0 and _aes_refuse_stale_fire("exp_scalp_strike_loop"):
                return
            for side_key in ("yes", "no"):
                try:
                    strike_key = _strike_cooldown_key(strike.get("strike"), side_key)
                    dedupe_key = (strike_key, side_key)
                    if dedupe_key in processed_strikes:
                        continue
                    processed_strikes.add(dedupe_key)

                    if _exp_scalp_retain_verify_during_cooldown(
                        strike_key, seen_verify_keys, dedupe_key
                    ):
                        continue

                    strike_data_for_check = {
                        "strike": strike.get("strike"),
                        "side": side_key,
                        "ticker": strike.get("ticker"),
                    }
                    if is_strike_already_traded(strike_data_for_check):
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason="already_traded",
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                        )
                        continue

                    ask_dollars = strike.get("yes_ask_dollars") if side_key == "yes" else strike.get("no_ask_dollars")
                    if ask_dollars is None:
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason="missing_ask",
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                        )
                        continue
                    ask_price = float(ask_dollars)
                    if hws_family:
                        if not ask_hits_price_target(ask_price, hws_target):
                            _exp_scalp_verify_abort(
                                verify_bucket,
                                dedupe_key,
                                now_ts=now_ts,
                                need_s=verify_seconds,
                                reason="ask_misses_price_target",
                                strike_key=strike_key,
                                side_key=side_key,
                                log_tag=log_tag,
                                extra=f"ask=${ask_price:.4f} target=${hws_target:.4f}",
                            )
                            continue
                    elif ask_price < min_ask or ask_price > max_ask:
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason="ask_outside_band",
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                            extra=f"ask=${ask_price:.4f}",
                        )
                        continue

                    prob = probability_from_strike_row_side_aware(strike, mkt, side_key)
                    if prob is None:
                        prob = strike.get("probability")
                    if prob is None:
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason="missing_probability",
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                        )
                        continue
                    try:
                        prob_f = float(prob)
                    except (TypeError, ValueError):
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason="bad_probability",
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                        )
                        continue

                    size_mode, size_reason = classify_expiration_scalp_prob_movement(
                        probability=prob_f,
                        movement_percentile=movement_pct_f,
                        min_probability=min_probability,
                        max_probability=max_probability,
                        min_movement=min_movement,
                        max_movement=max_movement,
                    )
                    if size_mode == "block":
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason="prob_movement_block",
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                            extra=(
                                f"prob={prob_f}% move={movement_pct_f} "
                                f"({size_reason})"
                            ),
                        )
                        continue

                    raw_buf = strike.get("buffer_pct")
                    try:
                        buffer_pct_f = float(raw_buf) if raw_buf is not None else None
                    except (TypeError, ValueError):
                        buffer_pct_f = None
                    raw_avg_buf = strike.get("60s_avg_buffer_pct")
                    try:
                        avg_60s_buffer_pct_f = (
                            float(raw_avg_buf) if raw_avg_buf is not None else None
                        )
                    except (TypeError, ValueError):
                        avg_60s_buffer_pct_f = None
                    buf_reject = expiration_scalp_min_buffer_pct_gate(
                        buffer_pct=buffer_pct_f,
                        avg_60s_buffer_pct=avg_60s_buffer_pct_f,
                        min_buffer_pct=min_buffer_pct,
                    )
                    if buf_reject:
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason=buf_reject,
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                            extra=(
                                f"buffer_pct={buffer_pct_f} "
                                f"60s_avg_buffer_pct={avg_60s_buffer_pct_f} "
                                f"min_buffer_pct={min_buffer_pct}"
                            ),
                        )
                        continue

                    if exp_scalp_flicker_gate_enabled(cutout=AES_BTC15M_EXP_SCALP):
                        prior_state = verify_bucket.get(dedupe_key)
                        live_ask = None
                        if exp_scalp_flicker_live_band_enabled():
                            live_ask = _exp_scalp_live_side_ask(
                                strike.get("ticker"), side_key
                            )
                        flicker_action, flicker_reason = expiration_scalp_flicker_gate(
                            prior_ask_cent=(prior_state or {}).get("ask_cent")
                            if prior_state
                            else None,
                            snapshot_ask=ask_price,
                            min_ask=hws_target if hws_family else min_ask,
                            max_ask=hws_target if hws_family else max_ask,
                            live_ask=live_ask,
                            step_cents=exp_scalp_flicker_step_cents(),
                        )
                        if flicker_action == "abort":
                            extra = f"ask=${ask_price:.4f}"
                            if live_ask is not None:
                                extra = f"{extra} live_ask=${float(live_ask):.4f}"
                            _exp_scalp_verify_abort(
                                verify_bucket,
                                dedupe_key,
                                now_ts=now_ts,
                                need_s=verify_seconds,
                                reason=flicker_reason or "flicker_live_outside_band",
                                strike_key=strike_key,
                                side_key=side_key,
                                log_tag=log_tag,
                                extra=extra,
                            )
                            continue
                        if flicker_action == "reset":
                            seen_verify_keys.add(dedupe_key)
                            try:
                                started = float((prior_state or {}).get("started_at"))
                                prior_dwell = max(0.0, now_ts - started)
                            except (TypeError, ValueError, AttributeError):
                                prior_dwell = 0.0
                            verify_bucket[dedupe_key] = {
                                "started_at": now_ts,
                                "ask_cent": ask_dollars_to_cent(ask_price),
                            }
                            log(
                                f"{log_tag} VERIFY RESET | {strike_key} {side_key.upper()} | "
                                f"dwell={prior_dwell:.1f}s need={verify_seconds}s | "
                                f"reason={flicker_reason} | "
                                f"from={((prior_state or {}).get('ask_cent'))} "
                                f"to={ask_dollars_to_cent(ask_price)}"
                            )
                            continue

                    if exp_scalp_busy_book_enabled(cutout=AES_BTC15M_EXP_SCALP):
                        prior_state = verify_bucket.get(dedupe_key)
                        busy_reason, new_dir = expiration_scalp_busy_book_gate(
                            prior_ask_cent=(prior_state or {}).get("ask_cent")
                            if prior_state
                            else None,
                            prior_dir=(prior_state or {}).get("last_dir")
                            if prior_state
                            else None,
                            ask=ask_price,
                        )
                        if busy_reason:
                            seen_verify_keys.add(dedupe_key)
                            try:
                                started = float((prior_state or {}).get("started_at"))
                                prior_dwell = max(0.0, now_ts - started)
                            except (TypeError, ValueError, AttributeError):
                                prior_dwell = 0.0
                            verify_bucket[dedupe_key] = {
                                "started_at": now_ts,
                                "ask_cent": ask_dollars_to_cent(ask_price),
                                "last_dir": new_dir,
                            }
                            log(
                                f"{log_tag} VERIFY RESET | {strike_key} {side_key.upper()} | "
                                f"dwell={prior_dwell:.1f}s need={verify_seconds}s | "
                                f"reason={busy_reason} | "
                                f"from={((prior_state or {}).get('ask_cent'))} "
                                f"to={ask_dollars_to_cent(ask_price)}"
                            )
                            continue
                    else:
                        new_dir = None

                    seen_verify_keys.add(dedupe_key)
                    new_state, may_enter, dwell_s = update_expiration_scalp_entry_verification(
                        verify_bucket.get(dedupe_key),
                        eligible=True,
                        now_ts=now_ts,
                        enabled=verify_enabled,
                        period_seconds=verify_seconds,
                    )
                    if new_state is None:
                        verify_bucket.pop(dedupe_key, None)
                    else:
                        new_state["ask_cent"] = ask_dollars_to_cent(ask_price)
                        if exp_scalp_busy_book_enabled(cutout=AES_BTC15M_EXP_SCALP):
                            new_state["last_dir"] = new_dir
                        verify_bucket[dedupe_key] = new_state
                    if not may_enter:
                        log_debug(
                            f"{log_tag} VERIFY WAIT | {strike_key} {side_key.upper()} | "
                            f"dwell={dwell_s:.1f}s need={verify_seconds}s | "
                            f"Prob: {prob_f}% | Ask: ${ask_price:.4f} | TTC: {current_ttc}s"
                        )
                        continue

                    diff = strike.get("yes_diff") if side_key == "yes" else strike.get("no_diff")
                    entry_limit = hws_target if hws_family else ask_price
                    strike_data = {
                        "strike": format_trade_strike_label(
                            strike.get("strike"),
                            symbol=sym,
                            ticker=strike.get("ticker"),
                        ),
                        "side": side_key,
                        "ticker": strike.get("ticker"),
                        "buy_price": entry_limit,
                        "entry_limit_price": entry_limit if hws_family else None,
                        "probability": prob_f,
                        "diff": diff,
                        "half_size": size_mode == "half",
                        "size_mode": size_mode,
                        "size_reason": size_reason,
                        "movement_percentile": movement_pct_f,
                    }

                    if is_strike_already_traded(strike_data):
                        _exp_scalp_verify_abort(
                            verify_bucket,
                            dedupe_key,
                            now_ts=now_ts,
                            need_s=verify_seconds,
                            reason="already_traded",
                            strike_key=strike_key,
                            side_key=side_key,
                            log_tag=log_tag,
                        )
                        continue

                    size_note = "½ size" if size_mode == "half" else "full size"
                    verify_note = (
                        f"verified {dwell_s:.1f}s"
                        if verify_enabled
                        else "verify off"
                    )
                    if not can_trade_strike(strike_key):
                        continue

                    log(
                        f"{log_tag} 🚀 TRIGGERING TRADE | {strike_key} {side_key.upper()} | "
                        f"Prob: {prob_f}% | Move: {movement_pct_f} | Ask: ${ask_price:.4f} | "
                        f"TTC: {current_ttc}s | {size_note} ({size_reason}) | {verify_note}"
                    )
                    if trigger_auto_entry_trade(strike_data):
                        log(f"{log_tag} ✅ TRADE SUCCESSFUL | {strike_key} {side_key.upper()}")
                        verify_bucket.pop(dedupe_key, None)
                    else:
                        log(f"{log_tag} ❌ TRADE FAILED | {strike_key} {side_key.upper()}")
                        if strike_key in last_trade_times:
                            del last_trade_times[strike_key]
                except Exception as strike_err:
                    log(f"{log_tag} Error processing strike {strike.get('strike')} {side_key}: {strike_err}")

        stale = [k for k in list(verify_bucket.keys()) if k not in seen_verify_keys]
        for k in stale:
            sk, side = k[0], k[1]
            _exp_scalp_verify_abort(
                verify_bucket,
                k,
                now_ts=now_ts,
                need_s=verify_seconds,
                reason="not_eligible_this_pass",
                strike_key=str(sk),
                side_key=str(side),
                log_tag=log_tag,
            )
    except Exception as e:
        log(f"{log_tag} Error checking auto entry conditions: {e}")


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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
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

        prob_adj = settings.get("prob_adj")
        if spike_alert_active and prob_adj is not None:
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

                min_volume = settings.get("min_volume")
                if min_volume is None:
                    continue
                volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
                if volume < min_volume:
                    continue

                max_ask = settings.get("max_ask")
                if max_ask is None:
                    continue
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
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
                min_volume = settings.get("min_volume")
                if min_volume is None:
                    continue
                volume = _kalshi_fp_volume_number(strike.get("volume_fp")) or 0
                if volume < min_volume:
                    continue
                
                # STEP 6: Check max ask price threshold (EXACT SAME AS HOURLY HTC)
                max_ask = settings.get("max_ask")
                if max_ask is None:
                    continue
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
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
            monitor_key,
            {
                "entered": False,
                "contract": None,
                "locked_above_ticker": None,
                "locked_below_ticker": None,
            },
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
        norm_contract = _mc_normalize_hourly_contract(current_contract)

        # Reset entry state only on a true hourly cycle change (ignore 11am vs 11:00am aliases).
        prev_norm = _mc_normalize_hourly_contract(state.get("contract"))
        if norm_contract and prev_norm != norm_contract:
            if prev_norm:
                log(
                    f"[AUTO ENTRY MOMENTUM CONTAIN] 🔄 New cycle detected: "
                    f"{prev_norm} → {norm_contract} - resetting entry flag"
                )
            _momentum_contain_reset_cycle_state(state, norm_contract)
        elif norm_contract:
            state["contract"] = norm_contract
        
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
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
        
        # COOLDOWN WINDOW CHECK — seconds since spike start (cooldown_start_time).
        min_cooldown_timer = settings.get("min_cooldown_timer")
        max_cooldown_timer = settings.get("max_cooldown_timer")
        
        # If either min or max is set, check time_since_spike is within window
        if min_cooldown_timer is not None or max_cooldown_timer is not None:
            time_since_spike = _aes_time_since_spike_seconds()
            if time_since_spike is None:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ cooldown_start_time is NULL - skipping entry")
                return
            
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

        open_total, _, _ = _momentum_contain_open_auto_entry_legs(norm_contract)
        if open_total >= 2:
            state["entered"] = True
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Cycle {norm_contract} already has "
                f"{open_total} in-flight auto_entry legs — holding until expiration"
            )
            return

        if _momentum_contain_cycle_bracket_satisfied(norm_contract, strike_tier):
            state["entered"] = True
            return
        
        # Select strikes using the unified minimum-width + centering methodology,
        # or reuse the locked bracket for this cycle (partial-fill retries).
        strikes = strike_table_data.get("strikes", [])
        strike_above_data = None  # NO leg (must be > current_price)
        strike_below_data = None  # YES leg (must be < current_price)

        locked_above = state.get("locked_above_ticker")
        locked_below = state.get("locked_below_ticker")
        if locked_above or locked_below:
            strike_above_data = _mc_strike_row_for_ticker(strikes, locked_above)
            strike_below_data = _mc_strike_row_for_ticker(strikes, locked_below)
            if not strike_above_data or not strike_below_data:
                log(
                    f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Locked bracket tickers not on ladder "
                    f"(above={locked_above} below={locked_below}) — waiting"
                )
                return
        else:
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

        if strike_above_data and strike_below_data:
            if not state.get("locked_above_ticker"):
                state["locked_above_ticker"] = strike_above_data.get("ticker")
                state["locked_below_ticker"] = strike_below_data.get("ticker")

        # Log selection details for debugging
        current_price_f = float(current_price)
        min_bracket_width = current_price_f * 0.0035
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
        min_volume = settings.get("min_volume")
        if min_volume is None:
            return
        min_ask = settings.get("min_ask")
        if min_ask is None:
            return
        max_ask = settings.get("max_ask")
        if max_ask is None:
            return
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
        no_triggered_ok = False
        yes_triggered_ok = False
        
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
                    no_triggered_ok = True
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
                    yes_triggered_ok = True
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
        open_total, yes_open, no_open = _momentum_contain_open_auto_entry_legs(norm_contract)
        bracket_confirmed = (no_done and yes_done) or (
            open_total >= 2 and yes_open >= 1 and no_open >= 1
        )
        if bracket_confirmed:
            state["entered"] = True
            if norm_contract:
                state["contract"] = norm_contract
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ Two-leg bracket complete for cycle {norm_contract} "
                f"(this_tick_new={trades_entered}, no_db={no_done}, yes_db={yes_done}, "
                f"open_legs={open_total}) — will hold until expiration"
            )
        elif no_triggered_ok and yes_triggered_ok:
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ⏳ Both legs enqueued for cycle {norm_contract} "
                f"(no_db={no_done}, yes_db={yes_done}) — awaiting trade_manager before locking cycle"
            )
        elif trades_entered > 0 or no_done or yes_done:
            log(
                f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Partial bracket (no_in_db={no_done} yes_in_db={yes_done} "
                f"new_this_tick={trades_entered}) cycle {norm_contract} — will retry missing leg on next scan"
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        if missing_settings:
            log(f"[AUTO ENTRY MS] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_volume = settings.get("min_volume")
        if min_volume is None:
            return
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        min_ask = settings.get("min_ask")
        if min_ask is None:
            return
        max_ask = settings.get("max_ask")
        if max_ask is None:
            return
        max_price_spread = settings.get("max_price_spread")
        
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
        missing_settings = [
            setting
            for setting in required_settings
            if setting not in settings or settings.get(setting) is None
        ]
        if missing_settings:
            log(f"[AUTO ENTRY MR] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_volume = settings.get("min_volume")
        if min_volume is None:
            return
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        min_ask = settings.get("min_ask")
        if min_ask is None:
            return
        max_ask = settings.get("max_ask")
        if max_ask is None:
            return
        max_price_spread = settings.get("max_price_spread")
        
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


def _aes_active_pool_ladder_keys() -> Set[Tuple[str, str]]:
    """(symbol, market) pairs for all active monitors in this unified AES process."""
    global _aes_pool_ladder_keys, _aes_pool_ladder_keys_at
    if not AES_UNIFIED_POOL:
        sym, mkt = get_current_monitor_symbol_and_market()
        return {((sym or "BTC").upper(), (mkt or "hourly").lower())}
    if AES_BTC15M_EXP_SCALP:
        return {("BTC", "15m")}
    now = time.monotonic()
    if _aes_pool_ladder_keys and (now - _aes_pool_ladder_keys_at) < 5.0:
        return _aes_pool_ladder_keys
    keys: Set[Tuple[str, str]] = set()
    try:
        rows = _aes_list_lane_monitor_rows()
        for row in rows:
            sym = (row.get("symbol") or "BTC").strip().upper() or "BTC"
            mkt = (row.get("market") or "").strip().lower()
            if mkt not in ("hourly", "15m"):
                mkt = "15m" if AES_UNIFIED_15M else "hourly"
            keys.add((sym, mkt))
    except Exception as e:
        log_debug(f"[AES] pool ladder keys: {e}")
    _aes_pool_ladder_keys = keys
    _aes_pool_ladder_keys_at = now
    return keys


def _aes_maybe_lp_recompute() -> None:
    global _aes_last_lp_recompute_mono
    now = time.monotonic()
    if now - _aes_last_lp_recompute_mono < _AES_LP_RECONCILE_SEC:
        return
    _aes_last_lp_recompute_mono = now
    _aes_tick_symbol_wide_recompute()


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
        if AES_UNIFIED_POOL:
            if AES_BTC15M_EXP_SCALP:
                log(
                    "📊 MONITORING: AES mode=btc15m_exp_scalp_cutout "
                    "(live_state ladder-notify; same eval trigger as prod)"
                )
            else:
                log("📊 MONITORING: AES mode=latest_only_lanes (mailbox per ladder; cancel in-flight eval only)")
        
        # Broadcast initial state immediately on startup
        log("📊 MONITORING: Broadcasting initial auto entry state")
        _aes_run_symbol_wide_startup_once()
        if AES_UNIFIED_POOL:
            _aes_ensure_lane_hub().failsafe_refresh_all()
        else:
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

                _aes_maybe_lp_recompute()

                if AES_UNIFIED_POOL:
                    global _aes_last_failsafe_mono, _aes_last_cheap_status_mono
                    # Cheap status (~1s): ACTIVE/INACTIVE from cached snaps + aged
                    # TTC (no Redis fetch / strike scan). Redis failsafe_refresh_all
                    # only on quiet timeout or slow busy cadence (AES_FAILSAFE_REDIS_SEC).
                    # Full strategy evals stay on live_state on_ladder_notify + that
                    # Redis refresh — not 1s all-ladder fanout.
                    woke = _aes_live_state_wake.wait(timeout=_AES_FAILSAFE_POLL_SEC)
                    _aes_live_state_wake.clear()
                    now_mono = time.monotonic()
                    if now_mono - _aes_last_cheap_status_mono >= _AES_FAILSAFE_POLL_SEC:
                        try:
                            _aes_cheap_status_pass()
                        except Exception as _cheap_e:
                            log_debug(f"AES cheap status: {_cheap_e}")
                        _aes_last_cheap_status_mono = now_mono
                    need_redis = (not woke) or (
                        now_mono - _aes_last_failsafe_mono >= _AES_FAILSAFE_REDIS_SEC
                    )
                    if need_redis:
                        _aes_ensure_lane_hub().failsafe_refresh_all()
                        _aes_last_failsafe_mono = now_mono
                else:
                    check_auto_entry_conditions()
                    _aes_live_state_wake.wait(timeout=_AES_FAILSAFE_POLL_SEC)
                    _aes_live_state_wake.clear()
                
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

    try:
        from backend.core.tradeflow_live_state_trigger import (
            start_tradeflow_live_state_listener,
        )

        sym, mkt = get_current_monitor_symbol_and_market()

        def _aes_symbol_market_filter(s: str, m: str) -> bool:
            try:
                if AES_BTC15M_EXP_SCALP:
                    return s.strip().upper() == "BTC" and m.strip().lower() == "15m"
                if AES_UNIFIED_POOL:
                    return (s.strip().upper(), m.strip().lower()) in _aes_active_pool_ladder_keys()
                cs, cm = get_current_monitor_symbol_and_market()
                return s == (cs or "").strip().upper() and m == (cm or "hourly").strip().lower()
            except Exception:
                return True

        def _aes_on_live_state() -> None:
            _aes_live_state_wake.set()

        def _aes_on_ladder(s: str, m: str) -> None:
            if AES_UNIFIED_POOL:
                _aes_ensure_lane_hub().on_ladder_notify(s, m)
            else:
                _aes_live_state_wake.set()

        listener_kwargs = {
            "service": f"aes_{MONITOR_IDENTIFIER}",
            "symbol_market_filter": _aes_symbol_market_filter,
            "on_ladder_update": _aes_on_ladder,
        }
        if AES_UNIFIED_POOL:
            # active_trades kind still wakes failsafe path
            listener_kwargs["on_evaluate"] = _aes_on_live_state
        else:
            listener_kwargs["on_evaluate"] = _aes_on_live_state

        if start_tradeflow_live_state_listener(**listener_kwargs):
            log(
                "📊 MONITORING: live_state trigger enabled for %s/%s",
                sym,
                mkt,
            )
    except Exception as e:
        log_debug(f"live_state trigger not started: {e}")

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