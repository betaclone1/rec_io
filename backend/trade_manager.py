import json
import logging
import math
import random
import threading
import time
import base64
import os
import sys
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from zoneinfo import ZoneInfo
import re
import uuid
import requests
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from typing import Optional, Tuple, Any, Dict, List
from pathlib import Path
from fastapi import HTTPException, status
from dotenv import dotenv_values
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# Import the universal centralized port system
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.core.port_config import get_port, get_port_info
from backend.core.time_eastern import merge_psycopg2_connect_kwargs
from backend.core.exchange_ids import normalize_exchange
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.util.paths import get_project_root, get_trade_history_dir, get_logs_dir, get_host, get_data_dir
from backend.util.trade_log_archivist import union_trades_with_archives_select
from backend.util.paths import get_accounts_data_dir
from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import effective_tenant_context_for_sql_rewrite
from backend.core.tenant_legacy_sql import (
    legacy_users_monitor_list,
    legacy_users_orders,
    legacy_users_trades,
    legacy_users_trades_simulated,
)
from backend.core.kalshi_execution_settings import (
    KALSHI_TIME_IN_FORCE_VALUES,
    EXECUTION_ORDER_TYPE_VALUES,
    validate_execution_fields,
    normalize_time_in_force_loose,
    limit_price_for_executor_payload,
)
from backend.core.time_based_loss_prevention import (
    apply_sim_trade_cycle_loss,
    cycle_loss_contribution_and_anchor,
    on_trade_closed_live_loss_throttle,
    recompute_monitor_loss_prevention,
    startup_reconcile_simulated_trade_for_tenant,
)
from backend.core.symbol_wide_loss_prevention import (
    is_loss_prevention_sizing_state,
    resolve_effective_loss_prevention_state,
)
from backend.core.tenant_legacy_sql import legacy_users_sim_trade_lp_cycle_ledger
from backend.core.strike_pipeline_health import evaluate_pipeline_gate_conn

_ORDERBOOK_SCHEMA = "live_data"
_ORDERBOOK_TABLE_PREFIX = "orderbook_kalshi_"
_ORDERBOOK_MAX_IDENT = 63
_ORDERBOOK_MAX_SUFFIX = _ORDERBOOK_MAX_IDENT - len(_ORDERBOOK_TABLE_PREFIX)


def _tm_trades_table() -> str:
    return legacy_users_trades(effective_tenant_context_for_sql_rewrite().user_no)


def _tm_monitor_list_table() -> str:
    return legacy_users_monitor_list(effective_tenant_context_for_sql_rewrite().user_no)


def _tm_trades_simulated_table() -> str:
    return legacy_users_trades_simulated(effective_tenant_context_for_sql_rewrite().user_no)

def _tm_orders_table() -> str:
    return legacy_users_orders(effective_tenant_context_for_sql_rewrite().user_no)

EST_ZONE = ZoneInfo("America/New_York")
# Hourly: "BTC 2pm" -> hour 2, pm
CONTRACT_HOUR_PATTERN = re.compile(r".*\s([0-9]{1,2})(am|pm)$", re.IGNORECASE)
# 15m: "BTC 2:15pm" or "BTC 12:45pm" -> capture hour, minutes, and am/pm
CONTRACT_15M_HOUR_PATTERN = re.compile(r".*\s([0-9]{1,2}):[0-9]{2}\s*(am|pm)", re.IGNORECASE)
CONTRACT_15M_FULL_PATTERN = re.compile(r".*\s([0-9]{1,2}):([0-9]{2})\s*(am|pm)", re.IGNORECASE)
MONITOR_KEY_PATTERN = re.compile(r"^mon_(\d+?)_(\d+)$", re.IGNORECASE)


def _monitor_slot_and_id(monitor_key):
    """Parse mon_<slot>_<id>; return (slot_str, id_str) or (None, None)."""
    if not monitor_key:
        return None, None
    m = MONITOR_KEY_PATTERN.match(str(monitor_key))
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _worker_tenant_user_no():
    try:
        from backend.core.tenant_context import get_worker_tenant_context

        return get_worker_tenant_context().user_no
    except Exception:
        return None


def _monitor_key_matches_worker(monitor_key) -> bool:
    """False if monitor key targets another tenant than this process (when tenant context exists)."""
    slot, _ = _monitor_slot_and_id(monitor_key)
    if not slot:
        return False
    w = _worker_tenant_user_no()
    if w is None:
        return True
    return slot == w


# trade_manager ↔ ATS: resilient delivery (Redis enroll + HTTP notify). Tune in prod under load.
_ATS_ENROLL_ACK_WAIT_SEC = float(os.getenv("ATS_ENROLL_ACK_WAIT_SEC", "18"))
_ATS_ENROLL_REDIS_ATTEMPTS = max(1, int(os.getenv("ATS_ENROLL_REDIS_ATTEMPTS", "3")))
_ATS_HTTP_NOTIFY_ATTEMPTS = max(1, int(os.getenv("ATS_HTTP_NOTIFY_ATTEMPTS", "6")))
_ATS_HTTP_CONNECT_TIMEOUT = float(os.getenv("ATS_HTTP_CONNECT_TIMEOUT", "4"))
_ATS_HTTP_READ_TIMEOUT = float(os.getenv("ATS_HTTP_READ_TIMEOUT", "25"))
ATS_HTTP_FALLBACK_ENABLED = (os.getenv("ATS_HTTP_FALLBACK_ENABLED") or "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_ATS_HTTP_FALLBACK_LAST_LOG_TS = 0.0
_ATS_HTTP_FALLBACK_LOG_INTERVAL_SEC = 60.0


def _log_ats_http_fallback_throttled(message: str) -> None:
    global _ATS_HTTP_FALLBACK_LAST_LOG_TS
    now = time.time()
    if now - _ATS_HTTP_FALLBACK_LAST_LOG_TS >= _ATS_HTTP_FALLBACK_LOG_INTERVAL_SEC:
        _ATS_HTTP_FALLBACK_LAST_LOG_TS = now
        log(message)


def _monitor_suffix_from_identifier(monitor_identifier: Optional[str]) -> Optional[str]:
    if not monitor_identifier:
        return None
    s = str(monitor_identifier).strip()
    if s.startswith("mon_"):
        return s[4:]
    return s if "_" in s else None


def _post_ats_trade_notification_http(
    monitor_suffix: str,
    payload: dict,
    *,
    attempts: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """
    POST /api/trade_manager_notification with retries and split timeouts.
    Returns (ok, last_error_message).
    """
    from backend.core.port_config import get_active_trade_supervisor_http_port_for_monitor_suffix

    attempts = attempts if attempts is not None else _ATS_HTTP_NOTIFY_ATTEMPTS
    port = get_active_trade_supervisor_http_port_for_monitor_suffix(monitor_suffix)
    url = f"http://localhost:{port}/api/trade_manager_notification"
    last_err: Optional[str] = None
    connect_t = _ATS_HTTP_CONNECT_TIMEOUT
    read_t = _ATS_HTTP_READ_TIMEOUT
    for i in range(attempts):
        try:
            response = requests.post(url, json=payload, timeout=(connect_t, read_t))
            if response.status_code == 200:
                try:
                    body = response.json()
                except Exception:
                    body = {}
                if body.get("success", False):
                    return True, None
                last_err = f"ATS success=false json={body!r}"
            else:
                last_err = f"HTTP {response.status_code}"
        except Exception as e:
            last_err = str(e)
        if i + 1 < attempts:
            delay = min(12.0, 0.35 * (2**i)) + random.uniform(0, 0.25)
            log(
                f"⚠️ ATS HTTP notify retry {i + 1}/{attempts} mon={monitor_suffix} trade_id={payload.get('trade_id')}: {last_err} (sleep {delay:.2f}s)"
            )
            time.sleep(delay)
    return False, last_err


def _derive_kalshi_event_ticker(market_ticker: str) -> str:
    parts = market_ticker.strip().split("-")
    if len(parts) < 2:
        return market_ticker.strip()
    while len(parts) > 2:
        last = parts[-1]
        if last and last[0] == "T" and any(ch.isdigit() for ch in last[1:]):
            parts = parts[:-1]
        else:
            break
    return "-".join(parts) if parts else market_ticker.strip()


def _derive_clock_from_kalshi_suffix(dt_part: str) -> Optional[tuple]:
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


def _derive_clock_from_kalshi_event_parts(parts: list) -> Optional[tuple]:
    """Parse clock from event segments; 15m tickers use HHMM in penultimate segment (e.g. 26MAY211815-15)."""
    if not parts:
        return None
    clock = _derive_clock_from_kalshi_suffix(parts[-1])
    if clock is not None:
        return clock
    if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) <= 2:
        return _derive_clock_from_kalshi_suffix(parts[-2])
    return None


def _derive_format_time_label(hour_24: int) -> str:
    if hour_24 == 0:
        return "12am"
    if hour_24 == 12:
        return "12pm"
    if hour_24 > 12:
        return f"{hour_24 - 12}pm"
    return f"{hour_24}am"


def _derive_format_15m_contract(symbol: str, hour_24: int, minute: int) -> str:
    s = symbol.upper()
    if hour_24 == 0:
        return f"{s} 12:{minute:02d}am"
    if hour_24 == 12:
        return f"{s} 12:{minute:02d}pm"
    if hour_24 > 12:
        return f"{s} {hour_24 - 12}:{minute:02d}pm"
    return f"{s} {hour_24}:{minute:02d}am"


def derive_contract_label_from_kalshi_ticker(symbol: Optional[str], ticker: Optional[str]) -> Optional[str]:
    """Human-readable contract from Kalshi market ticker (e.g. KXETHD-…-T… -> 'ETH 7pm')."""
    if not ticker or not str(ticker).strip():
        return None
    sym = _trade_symbol_norm(symbol) or "BTC"
    ev = _derive_kalshi_event_ticker(str(ticker).strip())
    parts = ev.split("-")
    if len(parts) < 2:
        return None
    clock = _derive_clock_from_kalshi_event_parts(parts)
    if not clock:
        return None
    h24, min_opt = clock
    if min_opt is not None:
        return _derive_format_15m_contract(sym, h24, min_opt)
    return f"{sym} {_derive_format_time_label(h24)}"


def _coalesce_trade_contract(symbol: str, contract: Optional[str], ticker: Optional[str]) -> str:
    """Prefer explicit contract; else derive from ticker; else legacy segment label."""
    sym = _trade_symbol_norm(symbol) or "BTC"
    legacy = f"{sym} Market"
    c = str(contract).strip() if contract is not None else ""
    d = derive_contract_label_from_kalshi_ticker(symbol, ticker)
    if c and c != legacy:
        return c
    if d:
        return d
    if c:
        return c
    return legacy


# Spot/strike precision: BTC/ETH stay at 2dp for backward compatibility; SOL/XRP align with
# 15m strike tables (NUMERIC scale 5) so settlement compares and UI match Kalshi granularity.
_HIGH_PRECISION_TRADE_SPOT_SYMBOLS = frozenset({"SOL", "XRP"})


def _trade_symbol_norm(symbol: Optional[str]) -> str:
    if not symbol:
        return ""
    return str(symbol).strip().upper()


def trade_uses_high_precision_spot(symbol: Optional[str]) -> bool:
    return _trade_symbol_norm(symbol) in _HIGH_PRECISION_TRADE_SPOT_SYMBOLS


def normalize_trade_spot_price(symbol: Optional[str], value):
    """
    Quantize spot price for DB writes. Returns Decimal for clean NUMERIC persistence, or None.
    """
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        try:
            d = Decimal(str(float(value)))
        except Exception:
            return None
    step = Decimal("0.00001") if trade_uses_high_precision_spot(symbol) else Decimal("0.01")
    return d.quantize(step, rounding=ROUND_HALF_UP)


def _symbol_close_from_close_request(symbol: Optional[str], raw) -> Optional[float]:
    """Coerce ATS/close-request symbol_close into a DB-safe spot price, or None."""
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    out = normalize_trade_spot_price(symbol, v)
    if out is None:
        return None
    return float(out)


def _resolve_symbol_close_for_finalize(
    trade_id: int,
    symbol: Optional[str],
    *,
    ticket_id: Optional[str] = None,
    as_of_est: Optional[datetime] = None,
) -> Optional[float]:
    """Prefer symbol_close on the trade row (set at close start), else 1m avg, else live spot."""
    existing = None
    pg_conn = get_postgresql_connection()
    if pg_conn:
        try:
            with pg_conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT symbol_close FROM {_tm_trades_table()} WHERE id = %s",
                    (trade_id,),
                )
                row = cursor.fetchone()
            if row and row[0] is not None:
                existing = _symbol_close_from_close_request(symbol, row[0])
        except Exception as e:
            log(f"⚠️ symbol_close read for trade {trade_id}: {e}")
        finally:
            try:
                pg_conn.close()
            except Exception:
                pass
    if existing is not None:
        return existing

    when = as_of_est or datetime.now(ZoneInfo("America/New_York"))
    symbol_close = _fetch_one_minute_avg_at_or_before(
        symbol, when, max_gap_seconds=120,
    )
    if symbol_close is not None:
        try:
            return float(symbol_close)
        except (TypeError, ValueError):
            pass

    try:
        from backend.core.tradeflow_live_reads import symbol_spot_price

        spot = symbol_spot_price(str(symbol or "").strip().upper())
        if spot is not None:
            out = normalize_trade_spot_price(symbol, spot)
            return float(out) if out is not None else None
    except Exception:
        pass

    if ticket_id:
        log_event(ticket_id, f"MANAGER: symbol_close unresolved for {symbol}")
    return None


def canonical_trade_strike_display(symbol: Optional[str], strike_raw):
    """
    Persist strike text without losing precision for low-priced underlyings.
    BTC/ETH: unchanged. SOL/XRP: normalize to $ with up to 5 decimal places (trim trailing zeros).
    """
    if strike_raw is None:
        return None
    s = str(strike_raw).strip()
    if not trade_uses_high_precision_spot(symbol):
        return s
    clean = s.replace("$", "").replace(",", "").strip()
    if not clean:
        return s
    try:
        d = Decimal(clean).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return s
    plain = format(d, "f")
    if "." in plain:
        plain = plain.rstrip("0").rstrip(".")
    return f"${plain}"


def _tm_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _TmFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_tm_logging():
    logr = logging.getLogger("trade_manager")
    if logr.handlers:
        return logr
    h = _TmFlushHandler(sys.stdout)
    h.setFormatter(_tm_est_formatter())
    logr.addHandler(h)
    logr.setLevel(logging.INFO)
    return logr


_tm_logger = _configure_tm_logging()


def log(msg):
    """Log messages at INFO; use log_debug for routine/verbose output."""
    _tm_logger.info("%s", msg)


def log_debug(msg):
    """Log at DEBUG (not shown at default INFO level)."""
    _tm_logger.debug("%s", msg)


# Set during FastAPI lifespan teardown. Do not register signal.signal(SIGTERM) here:
# uvicorn installs its own SIGTERM handler; replacing it prevents graceful shutdown and
# can stall MASTER_RESTART until stopwaitsecs/SIGKILL.
_trade_manager_scheduler_shutdown = threading.Event()


def _fetch_monitor_state(cursor, monitor_key):
    """
    Fetch loss_prevention_state, multiplier, test_filter, loss_prevention_toggle from monitor_list.
    Use the caller's cursor (no nested cursor). SQL uses users.monitor_list_<slot> as a legacy template;
    TenantConnection rewrites to the bound schema/table.
    """
    if not monitor_key or not cursor:
        return None
    if not _monitor_key_matches_worker(monitor_key):
        return None
    _, monitor_id = _monitor_slot_and_id(monitor_key)
    if not monitor_id:
        return None
    try:
        cursor.execute(
            f"""
            SELECT loss_prevention_state, multiplier, test_filter, loss_prevention_toggle,
                   time_in_force, order_type
            FROM {_tm_monitor_list_table()}
            WHERE id = %s
            """,
            (monitor_id,),
        )
        row = cursor.fetchone()
        if row:
            loss_prevention = resolve_effective_loss_prevention_state(
                cursor,
                _tm_monitor_list_table(),
                monitor_id,
            )
            return {
                "loss_prevention": loss_prevention,
                "loss_prevention_state": loss_prevention,
                "multiplier": row[1],
                "test_filter": row[2],
                "loss_prevention_toggle": row[3],
                "time_in_force": row[4] if len(row) > 4 else None,
                "order_type": row[5] if len(row) > 5 else None,
            }
        return None
    except Exception as e:
        log(f"⚠️ Error fetching monitor state for {monitor_key}: {e}")
        return None


def _enrich_open_trade_execution_from_monitor(data: dict) -> None:
    """Set ``time_in_force`` and ``order_type`` (limit|market) from monitor_list; validate."""
    mk = data.get("monitor")
    if not mk:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="monitor_required_for_kalshi_execution_fields",
        )
    if not _monitor_key_matches_worker(mk):
        return
    _, mid = _monitor_slot_and_id(mk)
    if not mid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_monitor_key_for_execution_fields",
        )
    pg = get_postgresql_connection()
    if not pg:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database_unavailable",
        )
    try:
        with pg.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT time_in_force, order_type
                FROM {_tm_monitor_list_table()}
                WHERE id = %s
                """,
                (mid,),
            )
            row = cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="monitor_not_found_for_execution_fields",
            )
        tif, ot = row[0], row[1]
        ok, err = validate_execution_fields(str(tif), str(ot))
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err or "invalid_execution_fields")
        data["time_in_force"] = str(tif).strip().lower()
        data["order_type"] = str(ot).strip().lower()
    finally:
        try:
            pg.close()
        except Exception:
            pass


def _live_partial_row_if_residual(
    tid: Any,
    pos: Any,
    init_c: Any,
    tkt: Any,
    st_side: Any,
    want_side: str,
) -> Optional[tuple]:
    """If side matches and initial_count - position > 0, return (trade_id, p, ic, ticket_id)."""
    if _normalize_trade_side(st_side) != want_side:
        return None
    try:
        ic = int(init_c) if init_c is not None else int(pos)
    except (TypeError, ValueError):
        ic = int(pos) if pos is not None else 0
    try:
        p = int(pos) if pos is not None else 0
    except (TypeError, ValueError):
        p = 0
    residual = ic - p
    if residual <= 0:
        return None
    return (int(tid), p, ic, tkt)


def _find_live_partial_topup_by_instrument_keys(
    cursor, data: dict
) -> Optional[tuple]:
    """Match partial IOC rows by monitor + session + strike when ticker-based lookup is insufficient."""
    monitor_key = data.get("monitor")
    trade_date = data.get("date")
    symbol = str(data.get("symbol") or "").strip()
    if not monitor_key or not trade_date or not symbol:
        return None
    want = _normalize_trade_side(data.get("side"))
    if not want:
        return None
    contract_original = _coalesce_trade_contract(
        symbol, data.get("contract"), data.get("ticker")
    )
    contract_name = truncate_contract_name(contract_original, symbol)
    strike_for_db = canonical_trade_strike_display(symbol, data.get("strike"))
    if not contract_name or strike_for_db is None or str(strike_for_db).strip() == "":
        return None
    cursor.execute(
        f"""
        SELECT id, position, initial_count, ticket_id, side
        FROM {_tm_trades_table()}
        WHERE status = 'partial'
          AND paper_trade IS NOT TRUE
          AND monitor = %s
          AND date = %s
          AND contract = %s
          AND strike = %s
        """,
        (monitor_key, trade_date, contract_name, strike_for_db),
    )
    for row in cursor.fetchall() or []:
        tid, pos, init_c, tkt, st_side = row[0], row[1], row[2], row[3], row[4]
        got = _live_partial_row_if_residual(tid, pos, init_c, tkt, st_side, want)
        if got:
            return got
    return None


def _find_live_partial_topup(
    cursor,
    monitor_key: Optional[str],
    ticker: Optional[str],
    side_raw: Any,
    instrument_data: Optional[dict] = None,
) -> Optional[tuple]:
    """Return (trade_id, current_position, initial_count, ticket_id) or None."""
    if not monitor_key:
        return None
    want = _normalize_trade_side(side_raw)
    if not want:
        return None
    if ticker:
        cursor.execute(
            f"""
            SELECT id, position, initial_count, ticket_id, side
            FROM {_tm_trades_table()}
            WHERE status = 'partial'
              AND paper_trade IS NOT TRUE
              AND monitor = %s
              AND ticker = %s
            """,
            (monitor_key, ticker),
        )
        for row in cursor.fetchall() or []:
            tid, pos, init_c, tkt, st_side = row[0], row[1], row[2], row[3], row[4]
            got = _live_partial_row_if_residual(tid, pos, init_c, tkt, st_side, want)
            if got:
                return got
    if instrument_data:
        return _find_live_partial_topup_by_instrument_keys(cursor, instrument_data)
    return None


def _find_live_blocking_duplicate_trade_id(data: dict) -> Optional[int]:
    """Return existing live trade id if monitor+session+strike+side already has pending or open row.

    Prevents duplicate executor submissions and duplicate rows when the same signal retriggers
    before partial top-up applies (e.g. row still pending) or after a fill (open).
    """
    monitor_key = data.get("monitor")
    trade_date = data.get("date")
    side = data.get("side")
    symbol = str(data.get("symbol") or "").strip()
    if not monitor_key or not trade_date or not side or not symbol:
        return None
    contract_original = _coalesce_trade_contract(
        symbol, data.get("contract"), data.get("ticker")
    )
    contract_name = truncate_contract_name(contract_original, symbol)
    strike_for_db = canonical_trade_strike_display(symbol, data.get("strike"))
    if not contract_name or strike_for_db is None or str(strike_for_db).strip() == "":
        return None
    try:
        pg = get_postgresql_connection()
        if not pg:
            return None
        with pg.cursor() as c:
            c.execute(
                f"""
                SELECT id FROM {_tm_trades_table()}
                WHERE monitor = %s AND date = %s AND contract = %s AND strike = %s AND side = %s
                  AND status IN ('pending', 'open')
                  AND (paper_trade IS NULL OR paper_trade = FALSE)
                ORDER BY id DESC
                LIMIT 1
                """,
                (monitor_key, trade_date, contract_name, strike_for_db, side),
            )
            row = c.fetchone()
        pg.close()
        if row and row[0] is not None:
            return int(row[0])
    except Exception as e:
        log(f"⚠️ _find_live_blocking_duplicate_trade_id: {e}")
    return None


def _find_paper_partial_topup_by_instrument_keys(
    cursor, data: dict
) -> Optional[tuple]:
    """Same as live instrument-key partial lookup but for paper (test_filter) rows."""
    monitor_key = data.get("monitor")
    trade_date = data.get("date")
    symbol = str(data.get("symbol") or "").strip()
    if not monitor_key or not trade_date or not symbol:
        return None
    want = _normalize_trade_side(data.get("side"))
    if not want:
        return None
    contract_original = _coalesce_trade_contract(
        symbol, data.get("contract"), data.get("ticker")
    )
    contract_name = truncate_contract_name(contract_original, symbol)
    strike_for_db = canonical_trade_strike_display(symbol, data.get("strike"))
    if not contract_name or strike_for_db is None or str(strike_for_db).strip() == "":
        return None
    cursor.execute(
        f"""
        SELECT id, position, initial_count, ticket_id, side
        FROM {_tm_trades_table()}
        WHERE status = 'partial'
          AND paper_trade IS TRUE
          AND monitor = %s
          AND date = %s
          AND contract = %s
          AND strike = %s
        """,
        (monitor_key, trade_date, contract_name, strike_for_db),
    )
    for row in cursor.fetchall() or []:
        tid, pos, init_c, tkt, st_side = row[0], row[1], row[2], row[3], row[4]
        got = _live_partial_row_if_residual(tid, pos, init_c, tkt, st_side, want)
        if got:
            return got
    return None


def _find_paper_partial_topup(
    cursor,
    monitor_key: Optional[str],
    ticker: Optional[str],
    side_raw: Any,
    instrument_data: Optional[dict] = None,
) -> Optional[tuple]:
    """Return (trade_id, position, initial_count, ticket_id) for paper partial IOC top-up."""
    if not monitor_key:
        return None
    want = _normalize_trade_side(side_raw)
    if not want:
        return None
    if ticker:
        cursor.execute(
            f"""
            SELECT id, position, initial_count, ticket_id, side
            FROM {_tm_trades_table()}
            WHERE status = 'partial'
              AND paper_trade IS TRUE
              AND monitor = %s
              AND ticker = %s
            """,
            (monitor_key, ticker),
        )
        for row in cursor.fetchall() or []:
            tid, pos, init_c, tkt, st_side = row[0], row[1], row[2], row[3], row[4]
            got = _live_partial_row_if_residual(tid, pos, init_c, tkt, st_side, want)
            if got:
                return got
    if instrument_data:
        return _find_paper_partial_topup_by_instrument_keys(cursor, instrument_data)
    return None


def _find_paper_blocking_duplicate_trade_id(data: dict) -> Optional[int]:
    """Pending/open paper row for same monitor session + strike (AES retrigger while row active)."""
    monitor_key = data.get("monitor")
    trade_date = data.get("date")
    side = data.get("side")
    symbol = str(data.get("symbol") or "").strip()
    if not monitor_key or not trade_date or not side or not symbol:
        return None
    contract_original = _coalesce_trade_contract(
        symbol, data.get("contract"), data.get("ticker")
    )
    contract_name = truncate_contract_name(contract_original, symbol)
    strike_for_db = canonical_trade_strike_display(symbol, data.get("strike"))
    if not contract_name or strike_for_db is None or str(strike_for_db).strip() == "":
        return None
    try:
        pg = get_postgresql_connection()
        if not pg:
            return None
        with pg.cursor() as c:
            c.execute(
                f"""
                SELECT id FROM {_tm_trades_table()}
                WHERE monitor = %s AND date = %s AND contract = %s AND strike = %s AND side = %s
                  AND status IN ('pending', 'open')
                  AND paper_trade IS TRUE
                ORDER BY id DESC
                LIMIT 1
                """,
                (monitor_key, trade_date, contract_name, strike_for_db, side),
            )
            row = c.fetchone()
        pg.close()
        if row and row[0] is not None:
            return int(row[0])
    except Exception as e:
        log(f"⚠️ _find_paper_blocking_duplicate_trade_id: {e}")
    return None


def _apply_paper_ioc_partial_topup(
    trade_id: int,
    pos_existing,
    ic_existing: int,
    data: dict,
    proj_side: Optional[str],
    ticker: str,
) -> dict:
    """Simulate IOC for remaining contracts and merge into existing paper partial row."""
    if not proj_side or not ticker:
        return {"id": trade_id}
    try:
        lim_ioc = float(data.get("buy_price"))
    except (TypeError, ValueError):
        log_event(
            data.get("ticket_id", "UNKNOWN"),
            "MANAGER: PAPER IOC TOP-UP bad limit — skipped",
        )
        return {"id": trade_id}
    residual = int(ic_existing) - int(pos_existing or 0)
    if residual <= 0:
        return {"id": trade_id}
    ioc_proj = _project_paper_ioc_at_limit(ticker, proj_side, residual, lim_ioc)
    fill = int(ioc_proj.get("filled") or 0)
    if fill > residual:
        fill = residual
    if fill <= 0:
        log_event(
            data.get("ticket_id", "UNKNOWN"),
            f"MANAGER: PAPER IOC TOP-UP zero fill trade_id={trade_id} residual={residual}",
        )
        return {"id": trade_id}
    proj_buy = ioc_proj.get("initial_proj_price")
    proj_fee = ioc_proj.get("initial_proj_fees")
    try:
        pb = float(proj_buy) if proj_buy is not None else float(lim_ioc)
    except (TypeError, ValueError):
        pb = float(lim_ioc)
    try:
        inc_fee = float(proj_fee) if proj_fee is not None else 0.0
    except (TypeError, ValueError):
        inc_fee = 0.0

    pg_conn = get_postgresql_connection()
    if not pg_conn:
        return {"id": trade_id}
    prob_for_diff = data.get("prob")
    old_buy = pb
    old_fees = 0.0
    try:
        with pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT prob, buy_price, fees FROM {_tm_trades_table()}
                WHERE id = %s
                """,
                (trade_id,),
            )
            row0 = cursor.fetchone()
            if row0:
                if prob_for_diff is None and row0[0] is not None:
                    prob_for_diff = row0[0]
                if row0[1] is not None:
                    try:
                        old_buy = float(row0[1])
                    except (TypeError, ValueError):
                        pass
                if row0[2] is not None:
                    try:
                        old_fees = float(row0[2])
                    except (TypeError, ValueError):
                        pass
        pg_conn.close()
    except Exception as e:
        log(f"⚠️ paper IOC top-up read row: {e}")
        try:
            pg_conn.close()
        except Exception:
            pass
        return {"id": trade_id}

    old_pos = _trade_position_for_db(pos_existing)
    new_pos = _trade_position_for_db(old_pos + fill)
    if new_pos > ic_existing:
        new_pos = _trade_position_for_db(ic_existing)
    if old_pos > 0 and fill > 0:
        avg_buy = (old_buy * old_pos + pb * fill) / new_pos if new_pos > 0 else pb
    elif fill > 0:
        avg_buy = pb
    else:
        avg_buy = old_buy
    new_fees = old_fees + inc_fee
    next_st = "open" if new_pos >= int(ic_existing) else "partial"
    buy_px_float = float(avg_buy)
    diff_for_buy = _format_diff_from_prob_and_buy(prob_for_diff, buy_px_float)

    try:
        pg_u = get_postgresql_connection()
        if pg_u:
            with pg_u.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {_tm_trades_table()}
                    SET status = %s,
                        position = %s,
                        buy_price = %s,
                        fees = %s,
                        diff = %s,
                        order_id_open = NULL,
                        {_sql_slippage_from_buy_price_params()}
                    WHERE id = %s
                    """,
                    (
                        next_st,
                        new_pos,
                        buy_px_float,
                        new_fees,
                        diff_for_buy,
                        buy_px_float,
                        buy_px_float,
                        trade_id,
                    ),
                )
                pg_u.commit()
            pg_u.close()
    except Exception as e:
        log(f"⚠️ paper IOC top-up UPDATE failed: {e}")

    log_event(
        data.get("ticket_id", "UNKNOWN"),
        f"MANAGER: PAPER IOC TOP-UP trade_id={trade_id} +{fill} -> pos={new_pos} "
        f"status={next_st} avg_buy={buy_px_float:.4f}",
    )

    skip_ledger = False
    try:
        pg_chk = get_postgresql_connection()
        if pg_chk:
            with pg_chk.cursor() as cur_chk:
                cur_chk.execute(
                    f"SELECT COALESCE(test_filter, FALSE) FROM {_tm_trades_table()} WHERE id = %s",
                    (trade_id,),
                )
                rchk = cur_chk.fetchone()
                skip_ledger = bool(rchk and rchk[0] is True)
            pg_chk.close()
    except Exception as e:
        log_debug(f"paper top-up ledger skip check trade_id={trade_id}: {e}")
    if not skip_ledger:
        try:
            _paper_ledger_on_open(pb, int(fill), float(inc_fee or 0.0))
        except Exception as e:
            log(f"⚠️ paper ledger top-up: {e}")

    ticket_id_val = data.get("ticket_id", "PAPER")

    def _notify():
        try:
            notify_active_trade_supervisor_direct(trade_id, ticket_id_val, "pending")
            notify_ats_trade_open_with_ack(trade_id)
        except Exception as e:
            log(f"ERROR in paper IOC top-up notify: {e}")

    threading.Thread(target=_notify, daemon=True).start()
    return {"id": trade_id}


def _resolve_monitor_for_trade_insert(cursor, raw_monitor):
    """
    When monitor is set, require mon_<user>_<id> format and a row in users.monitor_list_<user>.
    Rejects orphan labels so deleted or fictitious monitors cannot open trades.
    Returns (value_for_db, error_detail). error_detail is None if OK.
    f"""
    if raw_monitor is None:
        return (None, None)
    mk = str(raw_monitor).strip()
    if not mk:
        return (None, None)
    match = MONITOR_KEY_PATTERN.match(mk)
    if not match:
        return (None, f"invalid_monitor_format:{mk!r}")
    if not _monitor_key_matches_worker(mk):
        return (None, f"monitor_wrong_tenant:{mk!r}")
    _, monitor_id = _monitor_slot_and_id(mk)
    if not monitor_id:
        return (None, f"invalid_monitor_format:{mk!r}")
    cursor.execute(
        f"SELECT 1 FROM {_tm_monitor_list_table()} WHERE id = %s",
        (monitor_id,),
    )
    if not cursor.fetchone():
        return (None, f"monitor_not_found:{mk}")
    return (mk, None)


def _get_market_for_monitor_key_cursor(cursor, monitor_key):
    """Return market ('hourly' or '15m') from monitor_list using the caller's cursor (same transaction)."""
    if not monitor_key or not cursor:
        return "hourly"
    if not _monitor_key_matches_worker(monitor_key):
        return "hourly"
    _, monitor_id = _monitor_slot_and_id(monitor_key)
    if not monitor_id:
        return "hourly"
    try:
        cursor.execute(
            f"""
            SELECT COALESCE(market, 'hourly') FROM {_tm_monitor_list_table()}
            WHERE id = %s
            """,
            (monitor_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            m = str(row[0]).strip().lower()
            return m if m in ("hourly", "15m") else "hourly"
        return "hourly"
    except Exception:
        return "hourly"


def _resolve_trade_market_for_insert(cursor, monitor_key, trade_strategy, ticker):
    """
    Trade cadence stored on each row: 'hourly' or '15m' (Kalshi cycle), not the venue slug.
    Prefer users.monitor_list.market when monitor_key resolves; else infer from strategy/ticker.
    """
    if monitor_key and cursor is not None:
        return _get_market_for_monitor_key_cursor(cursor, monitor_key)
    ts = (trade_strategy or "").lower()
    tk = (ticker or "").upper()
    if "15m" in ts or "15M" in tk:
        return "15m"
    return "hourly"


def _normalize_trade_date(value):
    """Best-effort conversion of stored trade date into an aware datetime in EST."""
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        value_str = str(value).strip()
        if not value_str:
            return None

        if value_str.endswith("Z"):
            value_str = value_str[:-1] + "+00:00"

        dt = None
        parse_attempts = (
            lambda v: datetime.fromisoformat(v),
            lambda v: datetime.strptime(v, "%Y-%m-%d"),
            lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M:%S"),
            lambda v: datetime.strptime(v, "%m/%d/%Y"),
        )
        for attempt in parse_attempts:
            try:
                dt = attempt(value_str)
                break
            except ValueError:
                continue
        if dt is None:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EST_ZONE)
    else:
        dt = dt.astimezone(EST_ZONE)

    return dt


def _contract_session_date_variants(trade_date) -> list:
    """Strings that may appear in ``users.trades_<slot>.date`` for the same session day."""
    out: list = []
    if trade_date is None:
        return out
    dt = _normalize_trade_date(trade_date)
    if dt:
        iso = dt.date().isoformat()
        out.append(iso)
        try:
            mdy = dt.strftime("%m/%d/%Y")
            if mdy not in out:
                out.append(mdy)
            mdshort = dt.strftime("%m/%d/%y")
            if mdshort not in out:
                out.append(mdshort)
        except Exception:
            pass
    raw = str(trade_date).strip()
    if raw and raw not in out:
        out.append(raw)
    return out


def _extract_hour_idx(contract):
    """Parse contract string into hour_idx following EST rules.
    Hourly: 'BTC 2pm' -> 14. 15m: 'BTC 2:15pm' -> 14 (hour of the cycle; all 4 cycles in that hour share same hour_idx)."""
    if not contract:
        return None

    s = contract.strip()

    # 15m: "BTC 12:45pm" or "BTC 2:30pm" -> use hour so all 4 cycles in that hour get same hour_idx/weekly_cycle
    match_15m = CONTRACT_15M_HOUR_PATTERN.search(s)
    if match_15m:
        hour_raw = int(match_15m.group(1))
        mer = match_15m.group(2).lower()
        if mer == "am":
            return 24 if hour_raw == 12 else hour_raw
        if hour_raw == 12:
            return 12
        return hour_raw + 12

    # Hourly: "BTC 2pm"
    match = CONTRACT_HOUR_PATTERN.match(s)
    if not match:
        return None

    hour_raw = int(match.group(1))
    mer = match.group(2).lower()

    if mer == "am":
        return 24 if hour_raw == 12 else hour_raw

    if hour_raw == 12:
        return 12

    return hour_raw + 12


def _normalize_boolean_flag(value):
    """Normalize various boolean-like values to a proper boolean."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in (
            'true',
            '1',
            'yes',
            'on',
            'one_contract',
            'win_streak_one_contract',
        )
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _extract_quarter_from_contract(contract):
    """Extract 15m quarter from contract for weekly_cycle decimal.
    Hourly contracts (no :MM) -> 4 (fourth quarter of hour; stored as .4).
    15m contracts: :00->0 (.0), :15->1 (.1), :30->2 (.2), :45->3 (.3)."""
    if not contract:
        return 4  # default hourly
    s = contract.strip()
    match = CONTRACT_15M_FULL_PATTERN.search(s)
    if match:
        minutes = int(match.group(2))
        return min(3, minutes // 15)  # 0, 15, 30, 45 -> 0, 1, 2, 3
    return 4  # hourly: fourth quarter of the hour


def _compute_weekly_cycle(trade_date, hour_idx):
    """Compute 1-168 weekly cycle bucket (integer); returns None when inputs unavailable."""
    if hour_idx is None:
        return None

    normalized_date = _normalize_trade_date(trade_date)
    if normalized_date is None:
        return None

    postgres_dow = (normalized_date.weekday() + 1) % 7  # Sunday=0 … Saturday=6
    return (postgres_dow * 24) + hour_idx


def _contract_expiration_est(trade_date, contract, fallback_now_est):
    """Resolve contract expiration timestamp (EST) from trade date + contract label."""
    base_date = _normalize_trade_date(trade_date) or fallback_now_est
    if not contract:
        return fallback_now_est

    s = str(contract).strip()
    m15 = CONTRACT_15M_FULL_PATTERN.search(s)
    if m15:
        hour_raw = int(m15.group(1))
        minutes = int(m15.group(2))
        mer = m15.group(3).lower()
    else:
        mh = CONTRACT_HOUR_PATTERN.match(s)
        if not mh:
            return fallback_now_est
        hour_raw = int(mh.group(1))
        minutes = 0
        mer = mh.group(2).lower()

    day_shift = 0
    if mer == "am":
        if hour_raw == 12:
            hour24 = 0
            # Hourly ``12am`` (00:00) maps to cycle hour 24 (end-of-day). Do not apply
            # day_shift to 15m labels like ``12:15am`` (00:15 same calendar day).
            if minutes == 0:
                day_shift = 1
        else:
            hour24 = hour_raw
    else:
        hour24 = 12 if hour_raw == 12 else hour_raw + 12

    expiration_est = datetime(
        base_date.year,
        base_date.month,
        base_date.day,
        hour24,
        minutes,
        0,
        tzinfo=EST_ZONE,
    )
    if day_shift:
        expiration_est += timedelta(days=day_shift)
    return expiration_est


def _trade_eligible_for_quarter_hour_expiry(trade_market: Optional[str]) -> bool:
    """True if this row is processed at :15/:30/:45 (not only at :00).

    Cadence is **only** ``users.trades_<slot>.market`` (same meaning as monitor market):
    ``15m`` → quarter-hour sweeps; ``hourly`` or NULL → top-of-hour only.
    Applies to every strategy.
    """
    return bool(trade_market and str(trade_market).strip().lower() == "15m")


def _filter_trades_past_contract_expiration(trades, now_est):
    """Keep only rows whose contract wall-clock expiration instant has passed (EST).

    Matches ``check_expired_simulated_trades`` — without this, :00 sweeps mark every
    open trade expired while ``one_minute_avg`` at/before expiry is just the latest tick.
    """
    past = []
    for row in trades:
        _trade_id, _ticker, _symbol, _strategy, contract, trade_date, _mkt = row
        expiration_est = _contract_expiration_est(trade_date, contract, now_est)
        if now_est >= expiration_est:
            past.append(row)
    return past


def _live_price_log_timestamp_cutoff_str(expiration_est: datetime) -> str:
    """ISO wall time string matching symbol_price_watchdog rows (America/New_York, no TZ suffix)."""
    if expiration_est.tzinfo is None:
        exp = expiration_est.replace(tzinfo=EST_ZONE)
    else:
        exp = expiration_est.astimezone(EST_ZONE)
    return exp.strftime("%Y-%m-%dT%H:%M:%S")


def _fetch_one_minute_avg_from_live_state_near_cutoff(
    symbol: str,
    expiration_est: datetime,
    *,
    max_gap_seconds: Optional[int] = None,
) -> Optional[float]:
    """Fallback when PG ``live_price_log_1s_*`` is stale (crypto hot path skips per-tick inserts).

    Expiry sweeps and closes run at/just after contract end; live_state spot is authoritative then.
    """
    if not symbol or expiration_est is None:
        return None
    try:
        from backend.core.live_state_config import live_state_cache_enabled
        from backend.core.tradeflow_live_reads import symbol_spot_price_for_monitoring

        if not live_state_cache_enabled():
            return None
        if expiration_est.tzinfo is None:
            cutoff_dt = expiration_est.replace(tzinfo=EST_ZONE)
        else:
            cutoff_dt = expiration_est.astimezone(EST_ZONE)
        now_est = datetime.now(EST_ZONE)
        delta_s = (now_est - cutoff_dt).total_seconds()
        window = float(max_gap_seconds) if max_gap_seconds is not None else 120.0
        # Sweep runs on the boundary; allow slightly early scheduler skew.
        if delta_s < -45.0 or delta_s > max(window, 300.0):
            return None
        sym_u = str(symbol).strip().upper()
        spot = symbol_spot_price_for_monitoring(
            sym_u,
            prefer_max_age_sec=min(120.0, max(window, 30.0)),
            allow_stale_max_age_sec=max(window, 180.0),
        )
        if spot is None:
            return None
        out = normalize_trade_spot_price(symbol, spot)
        if out is not None:
            log(
                f"ℹ️ one_minute_avg for {sym_u} from live_state near cutoff "
                f"(cutoff={_live_price_log_timestamp_cutoff_str(expiration_est)}, delta_s={delta_s:.1f})"
            )
        return out
    except Exception as e:
        log(f"⚠️ live_state one_minute_avg near cutoff for {symbol}: {e}")
        return None


def _fetch_one_minute_avg_at_or_before(
    symbol,
    expiration_est,
    *,
    max_gap_seconds: Optional[int] = None,
):
    """Read one_minute_avg from the latest row at/before expiration_est.

    ``live_price_log_1s_*`` stores ``timestamp`` as TEXT in ``%%Y-%%m-%%dT%%H:%%M:%%S`` EST.
    A Python datetime bound param makes PostgreSQL compare ``text <= timestamp``, which errors.
    """
    if not symbol or expiration_est is None:
        return None
    cutoff_str = _live_price_log_timestamp_cutoff_str(expiration_est)
    pg_conn = None
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return None
        with pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT one_minute_avg, timestamp
                FROM live_data.live_price_log_1s_{symbol.lower()}
                WHERE one_minute_avg IS NOT NULL
                  AND timestamp <= %s
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (cutoff_str,),
            )
            row = cursor.fetchone()
        pg_conn.close()
        if not row or row[0] is None:
            return _fetch_one_minute_avg_from_live_state_near_cutoff(
                symbol, expiration_est, max_gap_seconds=max_gap_seconds
            )
        if max_gap_seconds is not None and row[1]:
            try:
                row_ts = datetime.strptime(str(row[1]), "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=EST_ZONE
                )
                if expiration_est.tzinfo is None:
                    cutoff_dt = expiration_est.replace(tzinfo=EST_ZONE)
                else:
                    cutoff_dt = expiration_est.astimezone(EST_ZONE)
                gap_s = (cutoff_dt - row_ts).total_seconds()
                if gap_s < 0 or gap_s > float(max_gap_seconds):
                    log(
                        f"⚠️ one_minute_avg stale/misaligned for {symbol}: "
                        f"row_ts={row[1]} cutoff={cutoff_str} gap_s={gap_s:.1f} "
                        f"(max={max_gap_seconds})"
                    )
                    return _fetch_one_minute_avg_from_live_state_near_cutoff(
                        symbol, expiration_est, max_gap_seconds=max_gap_seconds
                    )
            except Exception as gap_err:
                log(f"⚠️ one_minute_avg gap check failed for {symbol}: {gap_err}")
                return _fetch_one_minute_avg_from_live_state_near_cutoff(
                    symbol, expiration_est, max_gap_seconds=max_gap_seconds
                )
        return normalize_trade_spot_price(symbol, row[0])
    except Exception as e:
        log(f"⚠️ one_minute_avg lookup at/before {cutoff_str} for {symbol}: {e}")
        if pg_conn:
            try:
                pg_conn.close()
            except Exception:
                pass
        return _fetch_one_minute_avg_from_live_state_near_cutoff(
            symbol, expiration_est, max_gap_seconds=max_gap_seconds
        )


def _apply_symbol_expiration_for_contract_session(cursor, symbol: str, trade_date, contract: str) -> int:
    """Same ``symbol_expiration`` for every trade with this session ``date`` + human ``contract`` (same cycle/event).

    Different Kalshi market tickers (YES/NO legs, strikes) still share one contract label per cycle.
    """
    if not symbol or not contract or trade_date is None:
        return 0
    now_est = datetime.now(EST_ZONE)
    exp_est = _contract_expiration_est(trade_date, contract, now_est)
    if now_est < exp_est:
        return 0
    px = _fetch_one_minute_avg_at_or_before(symbol, exp_est, max_gap_seconds=90)
    if px is None:
        return 0
    contract_key = str(contract).strip()
    variants = _contract_session_date_variants(trade_date)
    if not variants:
        return 0
    sym_key = str(symbol).strip().upper()
    ph = ",".join(["%s"] * len(variants))
    cursor.execute(
        f"""
        UPDATE {_tm_trades_table()}
        SET symbol_expiration = %s
        WHERE upper(trim(both from coalesce(symbol, ''))) = %s
          AND trim(both from coalesce(contract, '')) = %s
          AND date::text IN ({ph})
        """,
        (px, sym_key, contract_key, *variants),
    )
    return cursor.rowcount


def _trade_ids_pending_wlc_for_contract_session(cursor, symbol: str, contract: str, trade_date) -> list:
    c = str(contract).strip()
    variants = _contract_session_date_variants(trade_date)
    if not c or not variants or not symbol:
        return []
    sym_key = str(symbol).strip().upper()
    ph = ",".join(["%s"] * len(variants))
    cursor.execute(
        f"""
        SELECT id FROM {_tm_trades_table()}
        WHERE upper(trim(both from coalesce(symbol, ''))) = %s
          AND trim(both from coalesce(contract, '')) = %s
          AND date::text IN ({ph})
          AND status = 'closed'
          AND win_loss IS NOT NULL
          AND win_loss_confirmed IS NULL
        """,
        (sym_key, c, *variants),
    )
    return [r[0] for r in cursor.fetchall()]


def _backfill_symbol_expiration_past_due_closed(now_est: datetime) -> None:
    """For each distinct ``date`` + ``contract`` in the window (past expiry), align symbol_expiration across all rows."""
    pg = get_postgresql_connection()
    if not pg:
        return
    try:
        window_start = (now_est - timedelta(days=7)).date()
        window_end = now_est.date()
        with pg.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT symbol, date, contract
                FROM {_tm_trades_table()}
                WHERE symbol IS NOT NULL
                  AND contract IS NOT NULL
                  AND date IS NOT NULL
                  AND trim(both from date::text) <> ''
                  AND (trim(both from date::text))::date >= %s::date
                  AND (trim(both from date::text))::date <= %s::date
                """,
                (window_start, window_end),
            )
            markets = cur.fetchall()
        sessions_touched: list = []
        total_rows = 0
        for symbol, trade_date, contract in markets:
            exp_est = _contract_expiration_est(trade_date, contract, now_est)
            if now_est < exp_est:
                continue
            with pg.cursor() as cur:
                n = _apply_symbol_expiration_for_contract_session(cur, symbol, trade_date, contract)
            if n:
                total_rows += n
                sessions_touched.append((str(symbol).strip(), str(contract).strip(), trade_date))
        with pg.cursor() as cur:
            ids = []
            seen_sess = set()
            for sym_k, ckey, td in sessions_touched:
                sk = (sym_k.upper(), ckey, str(td))
                if sk in seen_sess:
                    continue
                seen_sess.add(sk)
                ids.extend(_trade_ids_pending_wlc_for_contract_session(cur, sym_k, ckey, td))
            _apply_win_loss_confirmed_for_trade_ids(cur, ids)
        pg.commit()
        if total_rows:
            log_debug(
                f"[15-MIN CHECK] symbol_expiration contract-session alignment: {total_rows} row(s), "
                f"{len(seen_sess)} session(s)"
            )
    except Exception as e:
        log(f"⚠️ symbol_expiration past-due backfill failed: {e}")
        try:
            pg.rollback()
        except Exception:
            pass
    finally:
        pg.close()


def _apply_win_loss_confirmed_for_trade_ids(cursor, trade_ids) -> None:
    """Recompute win_loss_confirmed where symbol_expiration and win_loss are set."""
    if not trade_ids:
        return
    for tid in trade_ids:
        cursor.execute(
            f"""
            SELECT strike, side, symbol_expiration, win_loss
            FROM {_tm_trades_table()}
            WHERE id = %s
              AND symbol_expiration IS NOT NULL
              AND win_loss IS NOT NULL
              AND win_loss_confirmed IS NULL
            """,
            (tid,),
        )
        row = cursor.fetchone()
        if not row:
            continue
        strike, side, sym_exp, win_loss = row
        wlc = _compute_win_loss_confirmed(strike, side, sym_exp, win_loss)
        if wlc is None:
            continue
        cursor.execute(
            f"UPDATE {_tm_trades_table()} SET win_loss_confirmed = %s WHERE id = %s",
            (wlc, tid),
        )


def _settle_one_expired_paper_trade(now_est: datetime, trade_id: int, ticker: str, symbol: str) -> None:
    """Repair missing ``symbol_close`` for an expired paper row; close when ``market_result`` exists."""
    pg_conn_paper = None
    try:
        pg_conn_paper = get_postgresql_connection()
        if not pg_conn_paper:
            log(f"⚠️ Cannot connect to PostgreSQL for paper trade {trade_id} settlement")
            return

        with pg_conn_paper.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT symbol_close, contract, date, market_result
                FROM {_tm_trades_table()}
                WHERE id = %s AND status = 'expired'
                  AND paper_trade IS TRUE
                """,
                (trade_id,),
            )
            trade_data = cursor.fetchone()

        if not trade_data:
            return

        symbol_close, contract, trade_date, market_result = trade_data

        if symbol_close is None and contract and trade_date and symbol:
            exp_est = _contract_expiration_est(trade_date, contract, now_est)
            symbol_close = _fetch_one_minute_avg_at_or_before(symbol, exp_est)
            if symbol_close is not None:
                log_debug(
                    f"📝 Repaired symbol_close for expired paper {trade_id} from expiration-tick 1m avg"
                )
                with pg_conn_paper.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {_tm_trades_table()} SET symbol_close = %s WHERE id = %s AND status = 'expired'",
                        (symbol_close, trade_id),
                    )
                    pg_conn_paper.commit()

        if market_result is None:
            # Paper trades need the same immediate per-ticker backfill path as live
            # so they do not wait for the periodic 5-minute sweep when WS apply is missed.
            mt = str(ticker or "").strip()
            if mt:
                applied_now = _backfill_market_result_for_ticker_now(mt)
                if applied_now > 0:
                    log(
                        f"[EXPIRY] immediate market_result apply rows={applied_now} "
                        f"ticker={mt} (paper trade path)"
                    )
                    with pg_conn_paper.cursor() as cursor:
                        cursor.execute(
                            f"SELECT market_result FROM {_tm_trades_table()} WHERE id = %s",
                            (trade_id,),
                        )
                        mr_row = cursor.fetchone()
                    market_result = mr_row[0] if mr_row else None
            if market_result is None:
                return

        finalize_expired_trade_from_market_result(trade_id)

    except Exception as e:
        log(f"❌ Error processing paper trade {trade_id} settlement: {e}")
    finally:
        if pg_conn_paper:
            try:
                pg_conn_paper.close()
            except Exception:
                pass


def _settle_stuck_expired_paper_trades(now_est: datetime) -> None:
    """Finalize paper rows left ``expired`` with NULL ``symbol_close`` (e.g. after a failed price lookup)."""
    pg = get_postgresql_connection()
    if not pg:
        return
    try:
        with pg.cursor() as c:
            c.execute(
                f"""
                SELECT id, ticker, symbol FROM {_tm_trades_table()}
                WHERE paper_trade IS TRUE
                  AND status = 'expired'
                  AND symbol_close IS NULL
                LIMIT 100
                """
            )
            rows = c.fetchall()
        pg.close()
    except Exception as e:
        log(f"⚠️ stuck expired paper scan: {e}")
        try:
            pg.close()
        except Exception:
            pass
        return
    if not rows:
        return
    log(f"📝 Settling {len(rows)} stuck expired paper trade(s) missing symbol_close")
    for tid, tkr, sym in rows:
        _settle_one_expired_paper_trade(now_est, tid, tkr, sym)


def _repair_missing_symbol_close_recent(now_est: datetime) -> None:
    """Backfill ``symbol_close`` on recent closed/expired rows (hot-path PG gap failures)."""
    pg = get_postgresql_connection()
    if not pg:
        return
    try:
        window_start = (now_est - timedelta(hours=6)).date()
        with pg.cursor() as c:
            c.execute(
                f"""
                SELECT id, symbol, contract, date, status
                FROM {_tm_trades_table()}
                WHERE symbol_close IS NULL
                  AND symbol IS NOT NULL
                  AND status IN ('closed', 'expired')
                  AND date IS NOT NULL
                  AND (trim(both from date::text))::date >= %s::date
                ORDER BY id DESC
                LIMIT 50
                """,
                (window_start,),
            )
            rows = c.fetchall()
        if not rows:
            pg.close()
            return
        repaired = 0
        with pg.cursor() as c:
            for trade_id, symbol, contract, trade_date, _status in rows:
                exp_est = _contract_expiration_est(trade_date, contract, now_est)
                px = _fetch_one_minute_avg_at_or_before(
                    symbol, exp_est, max_gap_seconds=300
                )
                if px is None:
                    px = _resolve_symbol_close_for_finalize(
                        int(trade_id), symbol, as_of_est=exp_est
                    )
                if px is None:
                    continue
                c.execute(
                    f"""
                    UPDATE {_tm_trades_table()}
                    SET symbol_close = %s
                    WHERE id = %s AND symbol_close IS NULL
                    """,
                    (px, trade_id),
                )
                if c.rowcount:
                    repaired += 1
            pg.commit()
        pg.close()
        if repaired:
            log(f"ℹ️ Repaired symbol_close on {repaired} recent closed/expired trade(s)")
    except Exception as e:
        log(f"⚠️ symbol_close recent repair failed: {e}")
        try:
            pg.close()
        except Exception:
            pass


def _tm_symbol_open_from_live_state(symbol: str):
    """Spot for trade record-keeping from live_state (None if stale/miss)."""
    try:
        from backend.core.tradeflow_live_reads import symbol_spot_price

        sym_u = str(symbol or "").strip().upper()
        spot = symbol_spot_price(sym_u)
        if spot is not None:
            return normalize_trade_spot_price(symbol, spot)
    except Exception:
        pass
    return None


def _get_price_spread_from_strike_table(symbol, ticker, side, market=None):
    """Price spread for ticker/side from live_state ladder (PG when cache off)."""
    if not symbol or not ticker or not side:
        return None
    mkt = (market or 'hourly').strip().lower()
    if mkt not in ('hourly', '15m'):
        mkt = 'hourly'

    normalized_side = side.upper()
    if normalized_side == 'Y':
        side_column = 'yes_price_spread'
    elif normalized_side == 'N':
        side_column = 'no_price_spread'
    else:
        normalized_side = side.lower()
        if normalized_side == 'yes':
            side_column = 'yes_price_spread'
        elif normalized_side == 'no':
            side_column = 'no_price_spread'
        else:
            return None

    try:
        from backend.core.tradeflow_live_reads import (
            find_ladder_strike_row,
            strike_ladder,
            tradeflow_requires_live_state,
        )

        ladder = strike_ladder(symbol, mkt, "kalshi")
        row = find_ladder_strike_row(ladder, ticker)
        if row is not None:
            v = row.get(side_column)
            if v is not None:
                return float(v)
        if tradeflow_requires_live_state():
            return None
    except Exception:
        try:
            from backend.core.tradeflow_live_reads import tradeflow_requires_live_state

            if tradeflow_requires_live_state():
                return None
        except Exception:
            return None

    table_name = f'strike_table_{mkt}_{symbol.lower()}'
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return None
        
        with pg_conn.cursor() as cursor:
            query = sql.SQL("""
                SELECT {}
                FROM live_data.{}
                WHERE ticker = %s
                ORDER BY created_at DESC
                LIMIT 1
            """).format(
                sql.Identifier(side_column),
                sql.Identifier(table_name)
            )
            cursor.execute(query, (ticker,))
            
            result = cursor.fetchone()
            pg_conn.close()
            
            if result and result[0] is not None:
                return float(result[0])
            else:
                return None
    except Exception as e:
        if pg_conn:
            pg_conn.close()
        return None


def _row_to_float6(row):
    if not row:
        return (None,) * 6
    out = []
    for x in row:
        if x is None:
            out.append(None)
        else:
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                out.append(None)
    return tuple(out)


def _get_final_quarter_ask_snapshot_from_strike_table(symbol, ticker, market=None, exchange=None):
    """
    Latest strike row for this Kalshi market_ticker: final-window YES/NO ask min, max, range (dollars, 4 dp).
    Tries live_data.strike_table_15m (unified) for 15m, then legacy strike_table_15m_{symbol}; hourly uses
    unified strike_table_hourly with exchange + symbol filter. Mirrors cadence used for price_spread.
    """
    if not symbol or not ticker:
        return (None,) * 6
    mkt = (market or "hourly").strip().lower()
    if mkt not in ("hourly", "15m"):
        mkt = "hourly"
    ex = normalize_exchange(exchange or "kalshi")
    sym_lower = str(symbol).strip().lower()
    sym_upper = str(symbol).strip().upper()
    try:
        from backend.core.tradeflow_live_reads import (
            find_ladder_strike_row,
            strike_ladder,
            tradeflow_requires_live_state,
        )

        ladder = strike_ladder(symbol, mkt, ex)
        row = find_ladder_strike_row(ladder, ticker)
        if row is not None:
            vals = (
                row.get("yes_ask_min_15m"),
                row.get("yes_ask_max_15m"),
                row.get("no_ask_min_15m"),
                row.get("no_ask_max_15m"),
                row.get("yes_ask_range_15m"),
                row.get("no_ask_range_15m"),
            )
            if any(v is not None for v in vals):
                return _row_to_float6(vals)
        if tradeflow_requires_live_state():
            return (None,) * 6
    except Exception:
        try:
            from backend.core.tradeflow_live_reads import tradeflow_requires_live_state

            if tradeflow_requires_live_state():
                return (None,) * 6
        except Exception:
            return (None,) * 6

    pg_conn = None
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return (None,) * 6
        with pg_conn.cursor() as cursor:
            if mkt == "15m":
                cursor.execute(
                    """
                    SELECT yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                           yes_ask_range_15m, no_ask_range_15m
                    FROM live_data.strike_table_15m
                    WHERE LOWER(TRIM(exchange)) = %s
                      AND UPPER(TRIM(symbol)) = %s
                      AND ticker = %s
                    ORDER BY timestamp DESC NULLS LAST
                    LIMIT 1
                    """,
                    (ex, sym_upper, ticker),
                )
                row = cursor.fetchone()
                if row and any(v is not None for v in row):
                    return _row_to_float6(row)
                leg = f"strike_table_15m_{sym_lower}"
                q = sql.SQL(
                    """
                    SELECT yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                           yes_ask_range_15m, no_ask_range_15m
                    FROM live_data.{tbl}
                    WHERE ticker = %s
                    ORDER BY timestamp DESC NULLS LAST
                    LIMIT 1
                    """
                ).format(tbl=sql.Identifier(leg))
                cursor.execute(q, (ticker,))
                row = cursor.fetchone()
                if row and any(v is not None for v in row):
                    return _row_to_float6(row)
            else:
                cursor.execute(
                    """
                    SELECT yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                           yes_ask_range_15m, no_ask_range_15m
                    FROM live_data.strike_table_hourly
                    WHERE LOWER(TRIM(exchange::text)) = %s
                      AND UPPER(TRIM(symbol::text)) = %s
                      AND ticker = %s
                    ORDER BY "timestamp" DESC NULLS LAST
                    LIMIT 1
                    """,
                    (ex, sym_upper, ticker),
                )
                row = cursor.fetchone()
                if row and any(v is not None for v in row):
                    return _row_to_float6(row)
        return (None,) * 6
    except Exception:
        return (None,) * 6
    finally:
        if pg_conn:
            try:
                pg_conn.close()
            except Exception:
                pass


# Function to get momentum data from PostgreSQL (replacement for archived unified_production_coordinator)
def get_momentum_data_from_postgresql(symbol):
    """Get current momentum data directly from PostgreSQL for the specified symbol."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            **merge_psycopg2_connect_kwargs(
                {
                    "host": "localhost",
                    "database": "rec_io_db",
                    "user": "rec_io_user",
                    "password": "rec_io_password",
                }
            )
        )
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_score = float(result[0])
            return {
                "weighted_momentum_score": momentum_score
            }
        else:
            return {
                "weighted_momentum_score": 0
            }
    except Exception as e:
        log(f"Error getting momentum from PostgreSQL: {e}")
        return {
            "weighted_momentum_score": 0
        }

# Get port from centralized system
TRADE_MANAGER_PORT = get_port("trade_manager")

# Thread-safe set to track trades being processed
processing_trades = set()
processing_lock = threading.Lock()

_trade_confirm_locks: dict[int, threading.Lock] = {}
_trade_confirm_locks_guard = threading.Lock()


def _trade_confirm_lock(trade_id: int) -> threading.Lock:
    """Serialize confirm_open_trade / confirm_close_trade per trade id (overlapping notifications)."""
    with _trade_confirm_locks_guard:
        lock = _trade_confirm_locks.get(trade_id)
        if lock is None:
            lock = threading.Lock()
            _trade_confirm_locks[trade_id] = lock
        return lock


def _order_count_val(legacy, fp):
    """Prefer _fp (NUMERIC) for order counts; fall back to legacy integer. Returns float for math."""
    if fp is not None:
        return float(fp)
    if legacy is not None:
        return float(legacy)
    return 0.0


def _trade_position_for_db(value) -> float:
    """Normalize stored contract count on trades.position to 2dp (Kalshi fractional fills)."""
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_dollars(value):
    """Convert fixed-point dollar strings/numbers to float dollars; None/invalid -> None."""
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _entry_slippage_value(buy_price: object, initial_price: object):
    """Entry slippage = fill buy_price minus intended initial_price (0 if initial is missing). Matches DB: buy_price - COALESCE(initial_price, buy_price)."""
    if buy_price is None:
        return None
    try:
        bp = float(buy_price)
    except (TypeError, ValueError):
        return None
    if initial_price is None:
        return 0.0
    try:
        ip = float(initial_price)
    except (TypeError, ValueError):
        return 0.0
    return bp - ip


def _format_diff_from_prob_and_buy(prob_value: object, buy_price: object) -> Optional[str]:
    """Return diff text (+/- integer cents) from prob(percent) and buy_price(decimal)."""
    try:
        if prob_value is None or buy_price is None:
            return None
        prob_decimal = float(prob_value) / 100.0
        buy_decimal = float(buy_price)
        diff_value = int(round((prob_decimal - buy_decimal) * 100))
        return f"+{diff_value}" if diff_value >= 0 else f"{diff_value}"
    except (TypeError, ValueError):
        return None


def _sql_slippage_from_buy_price_params():
    """SQL assignment when writing a new entry buy_price: two %s placeholders (same value twice)."""
    return "slippage = %s - COALESCE(initial_price, %s)"


def estimate_kalshi_taker_fee(position, price: float) -> float:
    """Estimate taker fee for one leg: 0.07 * C * P * (1 - P), rounded up to next cent. Taker only."""
    try:
        pos = float(position)
    except (TypeError, ValueError):
        return 0.0
    if pos <= 0 or price is None or price <= 0 or price >= 1:
        return 0.0
    raw = 0.07 * pos * float(price) * (1.0 - float(price))
    return math.ceil(raw * 100) / 100


def _load_kalshi_rest_credentials() -> tuple[Optional[str], Optional[Path]]:
    """Return Kalshi key id + private key path for current account mode."""
    try:
        from backend.account_mode import get_account_mode
        from backend.util.paths import get_kalshi_credentials_dir

        mode = get_account_mode()
        cred_dir = Path(get_kalshi_credentials_dir()) / mode
        env_vars = dotenv_values(cred_dir / ".env")
        key_id = env_vars.get("KALSHI_API_KEY_ID")
        key_path = cred_dir / "kalshi.pem"
        if not key_id or not key_path.is_file():
            return None, None
        return key_id, key_path
    except Exception:
        return None, None


def _generate_kalshi_rest_signature(timestamp_ms: str, full_path: str, key_path: Path) -> Optional[str]:
    try:
        with open(key_path, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend(),
            )
        message = f"{timestamp_ms}GET{full_path}".encode("utf-8")
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")
    except Exception:
        return None


def _quoted_sidecar_table(market_ticker: str) -> Optional[str]:
    """Build live_data sidecar table identifier without importing sidecar module."""
    t = re.sub(r"[^A-Za-z0-9_]+", "_", str(market_ticker or "").strip())
    t = re.sub(r"_+", "_", t).strip("_").lower()
    if not t:
        return None
    if len(t) > _ORDERBOOK_MAX_SUFFIX:
        t = t[:_ORDERBOOK_MAX_SUFFIX]
    if not re.fullmatch(r"[a-z0-9_]+", t):
        return None
    return f'{_ORDERBOOK_SCHEMA}."{_ORDERBOOK_TABLE_PREFIX}{t}"'


def _load_orderbook_from_sidecar(ticker: str) -> Optional[dict]:
    """Read latest per-ticker orderbook levels from live_data sidecar table."""
    if not ticker:
        return None
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        qtbl = _quoted_sidecar_table(ticker)
        if not qtbl:
            return None
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT side, price_dollars, size_fp
                FROM {qtbl}
                WHERE size_fp > 0
                """
            )
            rows = cur.fetchall() or ()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    yes_bids: list[list[float]] = []
    no_bids: list[list[float]] = []
    for side, price, size_fp in rows:
        s = str(side or "").strip().lower()
        try:
            p = float(price)
            sz = float(size_fp)
        except (TypeError, ValueError):
            continue
        if sz <= 0 or p <= 0 or p >= 1:
            continue
        if s == "yes":
            yes_bids.append([p, sz])
        elif s == "no":
            no_bids.append([p, sz])

    if not yes_bids and not no_bids:
        return None
    return {"yes_dollars": yes_bids, "no_dollars": no_bids}


def _fetch_orderbook_for_projection(ticker: str) -> tuple[Optional[dict], str]:
    """Return orderbook bids map for projection, preferring local sidecar over Kalshi REST."""
    ob = _load_orderbook_from_sidecar(ticker)
    if ob is not None:
        return ob, "sidecar"

    url = f"https://external-api.kalshi.com/trade-api/v2/markets/{ticker}/orderbook"
    try:
        resp = requests.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "TradeManagerOrderbookProjection/1.0",
            },
            timeout=10,
        )
        if not resp.ok:
            return None, f"orderbook_http_{resp.status_code}"
        payload = resp.json()
    except Exception as e:
        return None, f"orderbook_request_failed:{e}"

    ob = payload.get("orderbook_fp") or payload.get("orderbook") or {}
    return ob, "ok"


def _normalize_trade_side(side_val: object) -> Optional[str]:
    side = str(side_val or "").strip().lower()
    if side in ("yes", "y"):
        return "yes"
    if side in ("no", "n"):
        return "no"
    return None


def _project_orderbook_entry(ticker: str, side: str, position: int) -> dict:
    """
    Build taker projection from current orderbook (REST bids flipped to asks).
    Returns keys: ok, reason, initial_proj_price, initial_proj_fees, available_contracts.
    """
    result = {
        "ok": False,
        "reason": "projection_failed",
        "initial_proj_price": None,
        "initial_proj_fees": None,
        "available_contracts": None,
    }
    if not ticker or not side or not position or position <= 0:
        result["reason"] = "missing_projection_inputs"
        return result

    ob, ob_reason = _fetch_orderbook_for_projection(ticker)
    if ob is None:
        result["reason"] = ob_reason
        return result
    yes_bids = ob.get("yes_dollars") or []
    no_bids = ob.get("no_dollars") or []
    src_bids = no_bids if side == "yes" else yes_bids

    asks: list[tuple[float, float]] = []
    for lvl in src_bids:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        try:
            bid_px = float(lvl[0])
            qty = float(lvl[1])
        except (TypeError, ValueError):
            continue
        ask_px = 1.0 - bid_px
        if qty <= 0 or ask_px <= 0 or ask_px >= 1:
            continue
        asks.append((ask_px, qty))
    asks.sort(key=lambda x: x[0])  # best ask first

    available = sum(q for _, q in asks)
    remaining = float(position)
    filled = 0.0
    notional = 0.0
    for px, qty in asks:
        if remaining <= 0:
            break
        take = min(remaining, qty)
        if take <= 0:
            continue
        notional += px * take
        filled += take
        remaining -= take

    result["available_contracts"] = round(available, 2)
    if filled <= 0:
        result["reason"] = "no_resting_volume"
        return result

    avg_price = notional / filled
    proj_fees = estimate_kalshi_taker_fee(int(round(filled)), avg_price)
    result["initial_proj_price"] = round(avg_price, 8)
    result["initial_proj_fees"] = round(proj_fees, 2)
    result["ok"] = filled >= float(position)
    result["reason"] = "ok" if result["ok"] else "insufficient_resting_volume"
    return result


def _project_paper_ioc_at_limit(
    ticker: str, side: str, requested_position: int, limit_price: float
) -> dict:
    """Simulate IOC: walk asks up to ``limit_price``; may fill less than requested."""
    result = {
        "ok": False,
        "reason": "projection_failed",
        "filled": 0,
        "initial_proj_price": None,
        "initial_proj_fees": None,
        "available_contracts": None,
    }
    if not ticker or not side or not requested_position or requested_position <= 0:
        result["reason"] = "missing_projection_inputs"
        return result
    try:
        lim = float(limit_price)
    except (TypeError, ValueError):
        result["reason"] = "bad_limit_price"
        return result
    if lim <= 0 or lim >= 1:
        result["reason"] = "bad_limit_price"
        return result

    ob, ob_reason = _fetch_orderbook_for_projection(ticker)
    if ob is None:
        result["reason"] = ob_reason
        return result
    yes_bids = ob.get("yes_dollars") or []
    no_bids = ob.get("no_dollars") or []
    src_bids = no_bids if side == "yes" else yes_bids

    asks: list = []
    for lvl in src_bids:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        try:
            bid_px = float(lvl[0])
            qty = float(lvl[1])
        except (TypeError, ValueError):
            continue
        ask_px = 1.0 - bid_px
        if qty <= 0 or ask_px <= 0 or ask_px >= 1:
            continue
        asks.append((ask_px, qty))
    asks.sort(key=lambda x: x[0])

    available = sum(q for px, q in asks if px <= lim + 1e-12)
    remaining = float(requested_position)
    filled = 0.0
    notional = 0.0
    for px, qty in asks:
        if remaining <= 0:
            break
        if px > lim + 1e-12:
            continue
        take = min(remaining, qty)
        if take <= 0:
            continue
        notional += px * take
        filled += take
        remaining -= take

    result["available_contracts"] = round(available, 2)
    result["filled"] = int(round(filled))
    if filled <= 0:
        result["reason"] = "no_fill_at_limit"
        return result

    avg_price = notional / filled
    proj_fees = estimate_kalshi_taker_fee(int(round(filled)), avg_price)
    result["initial_proj_price"] = round(avg_price, 8)
    result["initial_proj_fees"] = round(proj_fees, 2)
    result["ok"] = True
    result["reason"] = "ok"
    return result


def _project_orderbook_close(ticker: str, side: str, position: float) -> dict:
    """
    Build close projection from current orderbook bids on the same side.
    Returns keys: ok, reason, projected_sell_price, projected_close_fee, available_contracts.
    """
    result = {
        "ok": False,
        "reason": "projection_failed",
        "projected_sell_price": None,
        "projected_close_fee": None,
        "available_contracts": None,
    }
    if not ticker or not side or not position or position <= 0:
        result["reason"] = "missing_projection_inputs"
        return result

    ob, ob_reason = _fetch_orderbook_for_projection(ticker)
    if ob is None:
        result["reason"] = ob_reason
        return result
    side_bids = (ob.get("yes_dollars") or []) if side == "yes" else (ob.get("no_dollars") or [])

    bids: list[tuple[float, float]] = []
    for lvl in side_bids:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        try:
            bid_px = float(lvl[0])
            qty = float(lvl[1])
        except (TypeError, ValueError):
            continue
        if qty <= 0 or bid_px <= 0 or bid_px >= 1:
            continue
        bids.append((bid_px, qty))
    bids.sort(key=lambda x: x[0], reverse=True)  # best bid first for sells

    available = sum(q for _, q in bids)
    remaining = float(position)
    filled = 0.0
    proceeds = 0.0
    for px, qty in bids:
        if remaining <= 0:
            break
        take = min(remaining, qty)
        if take <= 0:
            continue
        proceeds += px * take
        filled += take
        remaining -= take

    result["available_contracts"] = round(available, 2)
    if filled <= 0:
        result["reason"] = "no_resting_volume"
        return result

    avg_sell_price = proceeds / filled
    close_fee_price = 1.0 - avg_sell_price
    close_fee = (
        estimate_kalshi_taker_fee(int(round(filled)), close_fee_price)
        if 0 < close_fee_price < 1
        else 0.0
    )
    result["projected_sell_price"] = round(avg_sell_price, 8)
    result["projected_close_fee"] = round(close_fee, 2)
    result["ok"] = filled >= float(position)
    result["reason"] = "ok" if result["ok"] else "insufficient_resting_volume"
    return result


def _paper_ledger_on_open(buy_price: float, position, open_fee_dollars: float) -> None:
    """
    Mimic live Kalshi balance feed: ``portfolio_value`` from OPEN paper trades in DB;
    cash = total equity minus that; total equity decreases by open fees only (premium is neutral).
    """
    try:
        from backend.balance_snapshot import paper_open_cost_and_fee_cents, sync_paper_balance_feed_after_open

        _cost_cents, fee_cents = paper_open_cost_and_fee_cents(
            float(buy_price), float(position), float(open_fee_dollars or 0.0)
        )
        sync_paper_balance_feed_after_open(fee_cents)
    except Exception as e:
        log(f"⚠️ paper ledger open: {e}")


def _paper_ledger_on_close(buy_price: float, position, pnl_dollars: float) -> None:
    try:
        from backend.balance_snapshot import sync_paper_balance_feed_after_close

        pnl_cents = int(round(float(pnl_dollars) * 100.0))
        sync_paper_balance_feed_after_close(pnl_cents, float(buy_price), float(position))
    except Exception as e:
        log(f"⚠️ paper ledger close: {e}")


def _format_count_fp(payload: dict, for_close: bool = False) -> str:
    """Format contract count as Kalshi fixed-point string (e.g. '100.00'). For open use position/count; for close use count/position."""
    fp = payload.get("count_fp")
    if fp is not None and str(fp).strip() != "":
        try:
            return f"{float(fp):.2f}"
        except (TypeError, ValueError):
            pass
    raw = payload.get("count", payload.get("position", 1)) if for_close else payload.get("position", payload.get("count", 1))
    return f"{float(raw):.2f}"


def _get_system_mode() -> str:
    """
    Read the global system mode from core.system_state.

    Returns:
        'normal' or 'maintenance'. On any error, defaults to 'maintenance'
        so we fail closed and avoid opening new trades when state is unknown.
    """
    conn = None
    try:
        conn = get_postgresql_connection()
        if not conn:
            # If we cannot talk to the DB at all, treat as maintenance for safety.
            log("⚠️ SYSTEM_STATE: No DB connection; treating mode as 'maintenance'")
            return "maintenance"

        with conn.cursor() as cursor:
            # Ensure schema/table exist and there is always a row with id=1.
            cursor.execute("CREATE SCHEMA IF NOT EXISTS core")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS core.system_state (
                    id INTEGER PRIMARY KEY,
                    mode TEXT NOT NULL CHECK (mode IN ('normal', 'maintenance')),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO core.system_state (id, mode)
                VALUES (1, 'normal')
                ON CONFLICT (id) DO NOTHING
                """
            )
            cursor.execute("SELECT mode FROM core.system_state WHERE id = 1")
            row = cursor.fetchone()

        if row and row[0] in ("normal", "maintenance"):
            return row[0]

        # If row missing or invalid, default to normal so healthy systems keep trading.
        return "normal"
    except Exception as e:
        # On any unexpected error, fail closed.
        log(f"⚠️ SYSTEM_STATE error: {e}")
        return "maintenance"
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _is_trading_enabled() -> bool:
    """
    Global gate for opening new trades.

    Returns:
        True if system_state.mode == 'normal', False otherwise.
    """
    mode = _get_system_mode()
    if mode != "normal":
        log(f"[TRADE_MANAGER] Trading disabled (system_mode={mode}); rejecting new trade request")
    return mode == "normal"


def get_executor_port():
    return get_port("trade_executor")


def send_trigger_to_executor(payload: dict) -> None:
    """Redis stream to trade_executor when enabled, else HTTP /trigger_trade."""
    try:
        from backend.core.trading_redis_comms import (
            redis_client_optional,
            resolve_tm_command_stream_slot,
            stream_executor_resolved,
            use_trading_redis_comms,
            xadd_trading_json,
        )

        if use_trading_redis_comms():
            r = redis_client_optional()
            slot = resolve_tm_command_stream_slot(payload if isinstance(payload, dict) else {}, None)
            if not slot:
                try:
                    from backend.core.tenant_context import get_worker_tenant_context

                    slot = get_worker_tenant_context().user_no
                except Exception:
                    slot = None
            ex_stream = stream_executor_resolved(slot)
            if r and xadd_trading_json(
                r,
                ex_stream,
                msg_type="trigger_trade",
                payload=payload,
                source="trade_manager",
            ):
                return
    except Exception as e:
        log(f"⚠️ Executor trigger via Redis failed, using HTTP: {e}")
    try:
        executor_port = get_executor_port()
        requests.post(
            f"http://localhost:{executor_port}/trigger_trade",
            json=payload,
            timeout=5,
        )
    except Exception as e:
        log(f"EXECUTOR HTTP ERROR: {e}")


def _fanout_active_trades_change_via_redis_or_http(broadcast_payload: dict) -> None:
    try:
        from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms
        from backend.core.tenant_context import get_worker_tenant_context

        slot = None
        try:
            slot = get_worker_tenant_context().user_no
        except Exception:
            pass
        if use_trading_redis_comms() and publish_preferences_event(
            "active_trades_change", broadcast_payload, tenant_user_no=slot
        ):
            log("NOTIFIED FRONTEND - ACTIVE TRADES CHANGE (Redis)")
            return
    except Exception:
        pass
    log("ACTIVE TRADES BROADCAST SKIPPED: Redis unavailable and HTTP fallback removed")


def notify_frontend_trade_change_redis_or_http() -> None:
    try:
        from backend.core.trading_redis_comms import publish_db_change_json, use_trading_redis_comms

        inner = {"timestamp": time.time(), "change_data": {"trades": 1}}
        if use_trading_redis_comms() and publish_db_change_json("trades", inner):
            log("NOTIFIED FRONTEND (Redis db_changes)")
            return
    except Exception:
        pass
    log("FRONTEND DB CHANGE NOTIFY SKIPPED: Redis unavailable and HTTP fallback removed")


def notify_strike_table_trade_change_redis_or_http(trade_id: int, status: str) -> None:
    cd = {"trade_id": trade_id, "status": status}
    try:
        from backend.core.trading_redis_comms import publish_db_change_json, use_trading_redis_comms

        inner = {"timestamp": time.time(), "change_data": cd}
        if use_trading_redis_comms() and publish_db_change_json("trades", inner):
            log("NOTIFIED STRIKE TABLE (Redis)")
            return
    except Exception:
        pass
    log("STRIKE TABLE DB CHANGE NOTIFY SKIPPED: Redis unavailable and HTTP fallback removed")

# ---------- CORE TRADE FUNCTIONS ----------------------------------------------------

def insert_trade(trade):
    """Insert a new trade with symbol-specific price from unified endpoint.

    Returns (trade_id, inserted_new). ``inserted_new`` is False when an existing row
    is reused (ticket_id idempotency, or active pending/open dedupe). On failure,
    returns (None, False).
    """

    # Get the symbol from trade data - NO FALLBACKS, symbol must be provided
    symbol = trade.get('symbol')
    if not symbol:
        raise ValueError("Trade symbol must be provided - no fallbacks allowed")
    symbol_lower = symbol.lower()

    ticket_id = trade.get("ticket_id")
    if ticket_id:
        tid = str(ticket_id).strip()
        if tid:
            try:
                pg_idem = get_postgresql_connection()
                if pg_idem:
                    with pg_idem.cursor() as cur_i:
                        cur_i.execute(
                            "SELECT id FROM "
                            + _tm_trades_table()
                            + " WHERE ticket_id = %s LIMIT 1",
                            (tid,),
                        )
                        existing = cur_i.fetchone()
                    pg_idem.close()
                    if existing and existing[0] is not None:
                        log_debug(f"insert_trade: idempotent reuse ticket_id={tid} id={existing[0]}")
                        return int(existing[0]), False
            except Exception as e:
                log(f"⚠️ insert_trade ticket_id idempotency lookup failed: {e}")
    
    symbol_open = None
    momentum_for_db = 0
    momentum_percentile_for_db = None
    momentum_5s_avg_for_db = None
    volatility_for_db = None
    volatility_percentile_for_db = None
    movement_for_db = None
    movement_percentile_for_db = None
    try:
        from backend.core.tradeflow_live_reads import (
            symbol_metrics,
            symbol_spot_price,
            tradeflow_requires_live_state,
        )

        sym_u = str(symbol or "").strip().upper()
        metrics = symbol_metrics(sym_u)
        if metrics:
            spot = symbol_spot_price(sym_u)
            if spot is not None:
                symbol_open = normalize_trade_spot_price(symbol, spot)
            momentum_val = metrics.get("momentum")
            if momentum_val is not None:
                momentum_for_db = round(float(momentum_val) * 100)
            mp = metrics.get("momentum_percentile")
            momentum_percentile_for_db = float(mp) if mp is not None else None
            m5 = metrics.get("momentum_5s_avg")
            momentum_5s_avg_for_db = float(m5) if m5 is not None else None
            vol = metrics.get("volatility")
            volatility_for_db = float(vol) if vol is not None else None
            vp = metrics.get("volatility_percentile")
            volatility_percentile_for_db = float(vp) if vp is not None else None
            mov = metrics.get("movement")
            movement_for_db = float(mov) if mov is not None else None
            mvp = metrics.get("movement_percentile")
            movement_percentile_for_db = float(mvp) if mvp is not None else None
        elif not tradeflow_requires_live_state():
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT price, momentum, momentum_percentile, momentum_5s_avg,
                               volatility, volatility_percentile, movement, movement_percentile
                        FROM live_data.live_price_log_1s_{symbol_lower}
                        ORDER BY timestamp DESC LIMIT 1
                        """
                    )
                    result = cursor.fetchone()
                pg_conn.close()
                if result:
                    if result[0] is not None:
                        symbol_open = normalize_trade_spot_price(symbol, result[0])
                    momentum_val = result[1]
                    if momentum_val is not None:
                        momentum_for_db = round(float(momentum_val) * 100)
                    momentum_percentile_for_db = (
                        float(result[2]) if result[2] is not None else None
                    )
                    momentum_5s_avg_for_db = (
                        float(result[3]) if result[3] is not None else None
                    )
                    volatility_for_db = (
                        float(result[4]) if result[4] is not None else None
                    )
                    volatility_percentile_for_db = (
                        float(result[5]) if result[5] is not None else None
                    )
                    movement_for_db = (
                        float(result[6]) if result[6] is not None else None
                    )
                    movement_percentile_for_db = (
                        float(result[7]) if result[7] is not None else None
                    )
    except Exception as e:
        log(f"⚠️ insert_trade: symbol metrics failed for symbol_open: {e}")

    if symbol_open is None:
        try:
            main_port = get_port("main_app")
            response = requests.get(f"http://localhost:{main_port}/api/{symbol_lower}_price", timeout=5)
            if response.ok:
                symbol_data = response.json()
                price = symbol_data.get("price")
                if price is not None:
                    symbol_open = normalize_trade_spot_price(symbol, price)
        except Exception as e:
            log(f"⚠️ insert_trade: API fallback for symbol_open failed: {e}")

    contract_original = _coalesce_trade_contract(symbol, trade.get("contract"), trade.get("ticker"))
    trade["contract"] = contract_original
    contract_name = truncate_contract_name(contract_original, symbol)

    hour_idx_for_db = _extract_hour_idx(contract_original)
    base_weekly_cycle = _compute_weekly_cycle(trade.get('date'), hour_idx_for_db)
    quarter = _extract_quarter_from_contract(contract_original)
    weekly_cycle_for_db = round(base_weekly_cycle + (quarter / 10.0), 1) if base_weekly_cycle is not None else None
    
    # Write to PostgreSQL only
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                _trades_tbl = _tm_trades_table()
                _monitor_list_tbl = _tm_monitor_list_table()
                monitor_key = trade.get('monitor')
                
                # Fetch monitor state once if monitor_key is provided
                monitor_state = None
                cooldown_timer = None
                if monitor_key:
                    monitor_state = _fetch_monitor_state(cursor, monitor_key)

                    # Fetch cooldown_timer from monitor_list
                    try:
                        if _monitor_key_matches_worker(monitor_key):
                            _, monitor_id_cd = _monitor_slot_and_id(monitor_key)
                            if monitor_id_cd:
                                cursor.execute(
                                    "SELECT cooldown_timer FROM "
                                    + _monitor_list_tbl
                                    + " WHERE id = %s",
                                    (monitor_id_cd,),
                                )
                                cooldown_result = cursor.fetchone()
                                if cooldown_result and cooldown_result[0] is not None:
                                    cooldown_timer = int(cooldown_result[0])
                    except Exception as e:
                        log(f"⚠️ Error fetching cooldown_timer for {monitor_key}: {e}")
                
                # Handle loss_prevention (boolean) + loss_prevention_state (monitor string snapshot)
                trade_loss_prevention = trade.get('loss_prevention')
                loss_prevention_state_for_db = None
                _payload_lp_state = trade.get("loss_prevention_state")
                if isinstance(_payload_lp_state, str) and _payload_lp_state.strip():
                    loss_prevention_state_for_db = _payload_lp_state.strip()
                elif _payload_lp_state is not None:
                    _s = str(_payload_lp_state).strip()
                    loss_prevention_state_for_db = _s if _s else None
                if loss_prevention_state_for_db is None and monitor_state and monitor_state.get("loss_prevention") is not None:
                    _raw_lp = monitor_state.get("loss_prevention")
                    if isinstance(_raw_lp, str) and _raw_lp.strip():
                        loss_prevention_state_for_db = _raw_lp.strip()
                    elif _raw_lp is not None:
                        _s = str(_raw_lp).strip()
                        loss_prevention_state_for_db = _s if _s else None
                if trade_loss_prevention is not None:
                    # Trade explicitly provided loss_prevention (boolean: True = sizing LP active)
                    loss_prevention_flag = _normalize_boolean_flag(trade_loss_prevention)
                else:
                    # Trade didn't provide loss_prevention, fetch from monitor state
                    if monitor_state and monitor_state.get('loss_prevention') is not None:
                        lp_toggle = monitor_state.get('loss_prevention_toggle')
                        toggle_on = bool(lp_toggle) if lp_toggle is not None else True
                        if not toggle_on:
                            loss_prevention_flag = False
                        else:
                            # Monitor stores loss_prevention as string (win_streak_one_contract, sim_loss_*, off, new, …)
                            monitor_loss_prevention = monitor_state.get('loss_prevention')
                            if isinstance(monitor_loss_prevention, str):
                                loss_prevention_flag = is_loss_prevention_sizing_state(
                                    monitor_loss_prevention
                                )
                            else:
                                loss_prevention_flag = _normalize_boolean_flag(monitor_loss_prevention)
                    else:
                        loss_prevention_flag = False
                
                # Handle multiplier
                multiplier_for_db = trade.get('multiplier')
                if multiplier_for_db is not None:
                    try:
                        multiplier_for_db = float(multiplier_for_db)
                    except (TypeError, ValueError):
                        multiplier_for_db = None
                
                # If multiplier not provided in trade, try to get from monitor state
                if multiplier_for_db is None and monitor_state and monitor_state.get('multiplier') is not None:
                    try:
                        multiplier_for_db = float(monitor_state['multiplier'])
                    except (TypeError, ValueError):
                        multiplier_for_db = None
                
                # Default multiplier to 1.0 if still None
                if multiplier_for_db is None:
                    multiplier_for_db = 1.0
                
                # Get price spread from strike table (same cadence as trades.market)
                ticker = trade.get('ticker')
                side = trade.get('side')
                trade_market_for_db = _resolve_trade_market_for_insert(
                    cursor, monitor_key, trade.get("trade_strategy"), ticker
                )
                price_spread = None
                if ticker and side:
                    price_spread = _get_price_spread_from_strike_table(
                        symbol, ticker, side, trade_market_for_db
                    )

                # Get paper_trade value from trade payload, default to False
                paper_trade = trade.get('paper_trade', False)
                if isinstance(paper_trade, str):
                    paper_trade = paper_trade.lower() in ('true', '1', 'yes')
                elif paper_trade is None:
                    paper_trade = False

                tf_raw = trade.get("test_filter")
                if tf_raw is not None:
                    test_filter_for_db = _normalize_boolean_flag(tf_raw)
                elif monitor_state and monitor_state.get("test_filter") is not None:
                    test_filter_for_db = _normalize_boolean_flag(monitor_state.get("test_filter"))
                else:
                    test_filter_for_db = False

                if test_filter_for_db:
                    paper_trade = True

                # Snapshot MTB from account_balance at insert time (single source of truth)
                master_trading_bankroll_for_db = None
                mtb_base_value_for_db = None
                try:
                    from backend.core.tenant_context import resolved_tenant_user_no_for_app
                    from backend.trading_mode import account_balance_table_for_user

                    _ab = account_balance_table_for_user(resolved_tenant_user_no_for_app())
                    cursor.execute(
                        "SELECT master_trading_bankroll, mtb_base_value FROM "
                        + _ab
                        + " ORDER BY id DESC LIMIT 1"
                    )
                    mtb_row = cursor.fetchone()
                    if mtb_row:
                        master_trading_bankroll_for_db = mtb_row[0]
                        mtb_base_value_for_db = mtb_row[1]
                except Exception as e:
                    log_debug(f"insert_trade: could not read MTB from account_balance: {e}")

                # Format diff value (add + prefix for positive values, keep negative as-is)
                diff_value = trade.get('diff')
                if diff_value is not None:
                    try:
                        diff_float = float(diff_value)
                        diff_formatted = f"+{int(diff_float)}" if diff_float >= 0 else f"{int(diff_float)}"
                    except (ValueError, TypeError):
                        diff_formatted = str(diff_value) if diff_value is not None else None
                else:
                    diff_formatted = None
                
                strike_for_db = canonical_trade_strike_display(symbol, trade.get("strike"))

                venue_exchange = normalize_exchange(
                    trade.get("exchange", trade.get("market"))
                )
                (
                    yes_ask_min_15m_for_db,
                    yes_ask_max_15m_for_db,
                    no_ask_min_15m_for_db,
                    no_ask_max_15m_for_db,
                    yes_ask_range_15m_for_db,
                    no_ask_range_15m_for_db,
                ) = _get_final_quarter_ask_snapshot_from_strike_table(
                    symbol, ticker, trade_market_for_db, venue_exchange
                )
                initial_price_for_db = trade.get('buy_price')
                initial_count_for_db = trade.get('position')
                try:
                    initial_price_for_db = float(initial_price_for_db) if initial_price_for_db is not None else None
                except (TypeError, ValueError):
                    initial_price_for_db = None
                try:
                    initial_count_for_db = int(initial_count_for_db) if initial_count_for_db is not None else None
                except (TypeError, ValueError):
                    initial_count_for_db = None

                slippage_for_db = _entry_slippage_value(trade.get("buy_price"), initial_price_for_db)

                # Live active-row dedupe (same keys as simulated duplicate guard): second INSERT path
                # returns the existing row when pending/open already exists for this monitor/strike.
                if (
                    not paper_trade
                    and monitor_key
                    and trade.get("date")
                    and contract_name
                    and strike_for_db is not None
                    and str(strike_for_db).strip() != ""
                    and trade.get("side")
                ):
                    cursor.execute(
                        f"""
                        SELECT id FROM {_trades_tbl}
                        WHERE monitor = %s AND date = %s AND contract = %s AND strike = %s AND side = %s
                          AND status IN ('pending', 'open')
                          AND (paper_trade IS NULL OR paper_trade = FALSE)
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (
                            monitor_key,
                            trade["date"],
                            contract_name,
                            strike_for_db,
                            trade["side"],
                        ),
                    )
                    dup_live = cursor.fetchone()
                    if dup_live and dup_live[0] is not None:
                        dup_id = int(dup_live[0])
                        log_debug(
                            f"insert_trade: active-row dedupe reuse id={dup_id} "
                            f"monitor={monitor_key!r} date={trade['date']!r} contract={contract_name!r} "
                            f"strike={strike_for_db!r} side={trade['side']!r}"
                        )
                        pg_conn.commit()
                        pg_conn.close()
                        return dup_id, False

                # Paper active-row dedupe (test_filter / paper_trade rows)
                if (
                    paper_trade
                    and monitor_key
                    and trade.get("date")
                    and contract_name
                    and strike_for_db is not None
                    and str(strike_for_db).strip() != ""
                    and trade.get("side")
                ):
                    cursor.execute(
                        f"""
                        SELECT id FROM {_trades_tbl}
                        WHERE monitor = %s AND date = %s AND contract = %s AND strike = %s AND side = %s
                          AND status IN ('pending', 'open')
                          AND paper_trade IS TRUE
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (
                            monitor_key,
                            trade["date"],
                            contract_name,
                            strike_for_db,
                            trade["side"],
                        ),
                    )
                    dup_paper_ins = cursor.fetchone()
                    if dup_paper_ins and dup_paper_ins[0] is not None:
                        dup_id = int(dup_paper_ins[0])
                        log_debug(
                            f"insert_trade: paper active-row dedupe reuse id={dup_id} "
                            f"monitor={monitor_key!r} date={trade['date']!r}"
                        )
                        pg_conn.commit()
                        pg_conn.close()
                        return dup_id, False

                cursor.execute(
                    "INSERT INTO "
                    + _trades_tbl
                    + """ (
                        status, date, time, symbol, exchange, trade_strategy, market,
                        contract, strike, side, prob, diff, buy_price, position, initial_price, initial_count, slippage, initial_proj_price, initial_proj_fees,
                        sell_price, closed_at, fees, pnl, symbol_open, symbol_close,
                        momentum, volatility, volatility_percentile, movement, movement_percentile,
                        win_loss, ticker, ticket_id, market_id,
                        momentum_percentile, momentum_5s_avg, entry_method, close_method, monitor, bankroll,
                        master_trading_bankroll, mtb_base_value,
                        hour_idx, weekly_cycle, loss_prevention, loss_prevention_state, multiplier, price_spread,
                        yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                        yes_ask_range_15m, no_ask_range_15m,
                        paper_trade, cooldown_timer, test_filter,
                        time_in_force, order_type,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    RETURNING id
                    """,
                    (
                    trade.get('status', 'pending'), trade['date'], trade['time'],
                    symbol, venue_exchange, trade.get('trade_strategy', 'Hourly HTC'), trade_market_for_db,
                    contract_name, strike_for_db, trade['side'], trade.get('prob'),
                    diff_formatted, trade['buy_price'], _trade_position_for_db(trade.get('position')), initial_price_for_db, initial_count_for_db, slippage_for_db,
                    trade.get('initial_proj_price'), trade.get('initial_proj_fees'),
                    None, None,
                    None, None, symbol_open, None, momentum_for_db,
                    volatility_for_db, volatility_percentile_for_db, movement_for_db, movement_percentile_for_db,
                    None, trade.get('ticker'), trade.get('ticket_id'), trade.get('market_id', f'{symbol}-USD'),
                    momentum_percentile_for_db, momentum_5s_avg_for_db, trade.get('entry_method', 'manual'), trade.get('close_method'),
                    monitor_key,
                    trade.get('bankroll_allotment_total'),
                    master_trading_bankroll_for_db, mtb_base_value_for_db,
                    hour_idx_for_db, weekly_cycle_for_db,
                    loss_prevention_flag,
                    loss_prevention_state_for_db,
                    multiplier_for_db,
                    price_spread,
                    yes_ask_min_15m_for_db,
                    yes_ask_max_15m_for_db,
                    no_ask_min_15m_for_db,
                    no_ask_max_15m_for_db,
                    yes_ask_range_15m_for_db,
                    no_ask_range_15m_for_db,
                    paper_trade,
                    cooldown_timer,
                    test_filter_for_db,
                    trade.get("time_in_force"),
                    trade.get("order_type"),
                ))
                last_id = cursor.fetchone()[0]
                pg_conn.commit()
                log_debug(f"💾 Trade written to PostgreSQL tenant trades with ID {last_id}")
                log_event(
                    trade.get("ticket_id") or str(last_id),
                    f"INSERT trade id={last_id} test_filter={test_filter_for_db}",
                )
            pg_conn.close()
        else:
            log(f"⚠️ Skipping PostgreSQL write - no connection available")
            return None, False
    except Exception as pg_err:
        log(f"❌ Failed to write trade to PostgreSQL: {pg_err}")
        return None, False
    
    notify_frontend_trade_change()
    return last_id, True


def _ensure_trades_simulated_id_sequence():
    """One-time: ensure tenant trades_simulated.id has a sequence default so INSERT ... RETURNING id works."""
    if getattr(_ensure_trades_simulated_id_sequence, "_done", False):
        return
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return
        with pg_conn.cursor() as cur:
            sim = _tm_trades_simulated_table()
            base = sim.split(".", 1)[-1] if "." in sim else sim
            cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'users' AND table_name = %s",
                (base,),
            )
            if not cur.fetchone():
                pg_conn.close()
                return
            cur.execute(f"CREATE SEQUENCE IF NOT EXISTS {sim}_id_seq")
            cur.execute(
                f"ALTER TABLE {sim} ALTER COLUMN id SET DEFAULT nextval('{sim}_id_seq'::regclass)"
            )
            cur.execute(
                f"SELECT setval('{sim}_id_seq', GREATEST(1, (SELECT COALESCE(MAX(id), 0) + 1 FROM {sim})))"
            )
        pg_conn.commit()
        pg_conn.close()
        _ensure_trades_simulated_id_sequence._done = True
    except Exception:
        pass


def insert_simulated_trade(trade):
    """Insert a simulated (virtual 15m) trade into the tenant ``trades_simulated_*`` table. paper_trade=True, test_filter=False."""
    _ensure_trades_simulated_id_sequence()
    symbol = trade.get('symbol')
    if not symbol:
        raise ValueError("Trade symbol must be provided")
    symbol_lower = symbol.lower()
    contract_original = _coalesce_trade_contract(symbol, trade.get("contract"), trade.get("ticker"))
    trade["contract"] = contract_original
    contract_name = truncate_contract_name(contract_original, symbol)
    hour_idx_for_db = _extract_hour_idx(contract_original)
    base_weekly_cycle = _compute_weekly_cycle(trade.get('date'), hour_idx_for_db)
    quarter = _extract_quarter_from_contract(contract_original)
    weekly_cycle_for_db = round(base_weekly_cycle + (quarter / 10.0), 1) if base_weekly_cycle is not None else None

    symbol_open = None
    momentum_for_db = 0
    momentum_percentile_for_db = None
    momentum_5s_avg_for_db = None
    volatility_for_db = None
    volatility_percentile_for_db = None
    movement_for_db = None
    movement_percentile_for_db = None
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT price, momentum, momentum_percentile, momentum_5s_avg,
                           volatility, volatility_percentile, movement, movement_percentile
                    FROM live_data.live_price_log_1s_{symbol_lower} ORDER BY timestamp DESC LIMIT 1
                """)
                result = cursor.fetchone()
            pg_conn.close()
            if result and len(result) >= 8 and result[0] is not None:
                symbol_open = normalize_trade_spot_price(symbol, result[0])
                if result[1] is not None:
                    momentum_for_db = round(float(result[1]) * 100)
                momentum_percentile_for_db = float(result[2]) if result[2] is not None else None
                momentum_5s_avg_for_db = float(result[3]) if result[3] is not None else None
                volatility_for_db = float(result[4]) if result[4] is not None else None
                volatility_percentile_for_db = float(result[5]) if result[5] is not None else None
                movement_for_db = float(result[6]) if result[6] is not None else None
                movement_percentile_for_db = float(result[7]) if result[7] is not None else None
    except Exception as e:
        log(f"⚠️ insert_simulated_trade: live_price_log_1s_{symbol_lower} failed for symbol_open: {e}")

    # Fallback: if we still have no price, get it from the main app API
    if symbol_open is None:
        try:
            main_port = get_port("main_app")
            response = requests.get(f"http://localhost:{main_port}/api/{symbol_lower}_price", timeout=5)
            if response.ok:
                symbol_data = response.json()
                price = symbol_data.get("price")
                if price is not None:
                    symbol_open = normalize_trade_spot_price(symbol, price)
        except Exception as e:
            log(f"⚠️ insert_simulated_trade: API fallback for symbol_open failed: {e}")

    # Simulated trades: do not record diff, buy_price, position, fees, or bankroll
    diff_formatted = None
    buy_price_for_db = None
    position_for_db = None
    bankroll_for_db = None
    fees_for_db = None

    last_id = None
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return None
        with pg_conn.cursor() as cursor:
            # Build qualified table name once (avoid brace placeholders ever reaching Postgres).
            _sim_trades_tbl = _tm_trades_simulated_table()
            monitor_key = trade.get('monitor')
            cooldown_timer = None
            if monitor_key:
                try:
                    if _monitor_key_matches_worker(monitor_key):
                        _, mid_cd = _monitor_slot_and_id(monitor_key)
                        if mid_cd:
                            cursor.execute(
                                f"""
                                SELECT cooldown_timer FROM {_tm_monitor_list_table()}
                                WHERE id = %s
                                """,
                                (mid_cd,),
                            )
                            row = cursor.fetchone()
                            if row and len(row) > 0 and row[0] is not None:
                                cooldown_timer = int(row[0])
                except Exception:
                    pass
            loss_prevention_flag = _normalize_boolean_flag(trade.get('loss_prevention', False))
            multiplier_for_db = trade.get('multiplier')
            if multiplier_for_db is None:
                multiplier_for_db = 1.0
            try:
                multiplier_for_db = float(multiplier_for_db)
            except (TypeError, ValueError):
                multiplier_for_db = 1.0
            # Simulated: do not record price_spread
            price_spread = None
            ticker, side = trade.get('ticker'), trade.get('side')
            trade_market_for_db = _resolve_trade_market_for_insert(
                cursor, monitor_key, trade.get("trade_strategy"), ticker
            )
            strike_for_db = canonical_trade_strike_display(symbol, trade.get("strike"))
            venue_exchange = normalize_exchange(
                trade.get("exchange", trade.get("market"))
            )
            (
                yes_ask_min_15m_for_db,
                yes_ask_max_15m_for_db,
                no_ask_min_15m_for_db,
                no_ask_max_15m_for_db,
                yes_ask_range_15m_for_db,
                no_ask_range_15m_for_db,
            ) = _get_final_quarter_ask_snapshot_from_strike_table(
                symbol, ticker, trade_market_for_db, venue_exchange
            )

            # Server-side duplicate guard: one row per (monitor, date, contract, strike, side)
            if monitor_key and trade.get('date') and contract_name and strike_for_db and side:
                cursor.execute(
                    "SELECT id FROM "
                    + _sim_trades_tbl
                    + " WHERE monitor = %s AND date = %s AND contract = %s AND strike = %s AND side = %s "
                    "LIMIT 1",
                    (monitor_key, trade['date'], contract_name, strike_for_db, side),
                )
                existing = cursor.fetchone()
                if existing:
                    log(f"[SIMULATED] Duplicate skipped (monitor={monitor_key} date={trade['date']} contract={contract_name} strike={strike_for_db} side={side}); existing id={existing[0]}")
                    pg_conn.close()
                    return existing[0]

            cursor.execute(
                "INSERT INTO "
                + _sim_trades_tbl
                + """ (
                    status, date, time, symbol, exchange, trade_strategy, market,
                    contract, strike, side, prob, diff, buy_price, position,
                    sell_price, closed_at, fees, pnl, symbol_open, symbol_close,
                    momentum, volatility, volatility_percentile, movement, movement_percentile,
                    win_loss, ticker, ticket_id, market_id,
                    momentum_percentile, momentum_5s_avg, entry_method, close_method, monitor, bankroll,
                    hour_idx, weekly_cycle, loss_prevention, multiplier, price_spread,
                    yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                    yes_ask_range_15m, no_ask_range_15m,
                    paper_trade, cooldown_timer, test_filter,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                RETURNING id
                """,
                (
                trade.get('status', 'pending'), trade['date'], trade['time'],
                symbol, venue_exchange, trade.get('trade_strategy', 'Hourly HTC'), trade_market_for_db,
                contract_name, strike_for_db, trade['side'], trade.get('prob'),
                diff_formatted, buy_price_for_db, position_for_db, None, None,
                fees_for_db, None, symbol_open, None, momentum_for_db,
                volatility_for_db, volatility_percentile_for_db, movement_for_db, movement_percentile_for_db,
                None, ticker, trade.get('ticket_id'), trade.get('market_id', f'{symbol}-USD'),
                momentum_percentile_for_db, momentum_5s_avg_for_db, trade.get('entry_method', 'simulated_15m'), trade.get('close_method'),
                monitor_key, bankroll_for_db,
                hour_idx_for_db, weekly_cycle_for_db,
                loss_prevention_flag, multiplier_for_db, price_spread,
                yes_ask_min_15m_for_db,
                yes_ask_max_15m_for_db,
                no_ask_min_15m_for_db,
                no_ask_max_15m_for_db,
                yes_ask_range_15m_for_db,
                no_ask_range_15m_for_db,
                True, cooldown_timer, False
            ))
            row = cursor.fetchone()
            try:
                last_id = row[0] if row and len(row) > 0 else None
            except (TypeError, IndexError):
                last_id = None
            if last_id is None:
                try:
                    cursor.execute("SELECT lastval()")
                    r = cursor.fetchone()
                    if r and len(r) > 0 and r[0] is not None:
                        last_id = int(r[0])
                except Exception:
                    pass
        pg_conn.commit()
        pg_conn.close()
        if last_id is None:
            log("❌ Simulated trade INSERT returned no id (RETURNING id gave no row)")
            return None
    except Exception as e:
        import traceback
        log(f"❌ Failed to write simulated trade: {e}")
        traceback.print_exc()
        return None
    return last_id


def confirm_open_trade(id: int, ticket_id: str) -> None:
    """Confirms a PENDING trade has been opened by checking ORDERS table for complete fill.

    Cumulative open fees on the trade row are: fees already stored from prior IOC legs plus
    (taker_fees_dollars + maker_fees_dollars) from the tenant orders row for the current
    order_id_open (synced Kalshi API). A per-trade lock prevents     overlapping confirms from
    double-counting the same order fee. Uses the same per-id lock as close confirmation.
    """
    # Get initial trade info including the order_id_open we stored
    pg_conn = get_postgresql_connection()
    if pg_conn:
        with pg_conn.cursor() as cursor:
            cursor.execute(f"SELECT ticker, symbol, order_id_open FROM {_tm_trades_table()} WHERE id = %s", (id,))
            row = cursor.fetchone()
        pg_conn.close()
    else:
        row = None
    
    if not row:
        log_event(ticket_id, f"MANAGER: No trade found for ID {id}")
        return
    
    symbol = row[1]
    stored_order_id_open = row[2]
    
    if not stored_order_id_open:
        log_event(ticket_id, f"MANAGER: No order_id_open stored for trade ID {id} - cannot confirm via ORDERS table")
        return
    
    with _trade_confirm_lock(id):
        deadline = time.time() + 30  # 30 second timeout
        
        while time.time() < deadline:
            try:
                pg_conn = get_postgresql_connection()
                if not pg_conn:
                    log_event(ticket_id, f"MANAGER: Cannot connect to PostgreSQL orders table")
                    time.sleep(1)
                    continue
            
                # Check ORDERS table for our specific order_id (prefer _fp columns for counts and *_dollars for prices/fees)
                with pg_conn.cursor() as cursor:
                    cursor.execute(f"""
                        SELECT remaining_count_fp, fill_count_fp, initial_count_fp, status, outcome_side,
                               taker_fees_dollars, maker_fees_dollars,
                               taker_fill_cost_dollars, maker_fill_cost_dollars
                        FROM {_tm_orders_table()} 
                        WHERE order_id = %s
                    """, (stored_order_id_open,))
                    order_row = cursor.fetchone()
            
                if order_row:
                    (remaining_count_fp, fill_count_fp, initial_count_fp, order_status, outcome_side,
                     taker_fees_dollars, maker_fees_dollars,
                     taker_fill_cost_dollars, maker_fill_cost_dollars) = order_row
                    # Legacy integer counts were removed; use *_fp only.
                    remaining_val = _order_count_val(None, remaining_count_fp)
                    fill_val = _order_count_val(None, fill_count_fp)
                    initial_val = _order_count_val(None, initial_count_fp)
                    log_event(ticket_id, f"MANAGER: Opening order {stored_order_id_open} status: {order_status}, remaining: {remaining_val}, filled: {fill_val}/{initial_val}")

                    pg_snap = get_postgresql_connection()
                    tr_snap = None
                    if pg_snap:
                        try:
                            with pg_snap.cursor() as cur:
                                cur.execute(
                                    f"""
                                    SELECT status, time_in_force, initial_count, position, buy_price, fees, prob
                                    FROM {_tm_trades_table()}
                                    WHERE id = %s
                                    """,
                                    (id,),
                                )
                                tr_snap = cur.fetchone()
                        finally:
                            try:
                                pg_snap.close()
                            except Exception:
                                pass
                    if not tr_snap:
                        log_event(ticket_id, "MANAGER: trade row missing during confirm_open")
                        pg_conn.close()
                        break
                    row_status = tr_snap[0]
                    tr_tif = str(tr_snap[1] or "").strip().lower()
                    tr_ic = tr_snap[2]
                    tr_pos = tr_snap[3]
                    tr_bp = tr_snap[4]
                    tr_fees = tr_snap[5]
                    prob_value_seed = tr_snap[6]

                    is_ioc = tr_tif == "immediate_or_cancel"
                    terminal_ioc = is_ioc and order_status in ("canceled", "executed")

                    if terminal_ioc and fill_val <= 0 and row_status == "pending":
                        # Live IOC top-up resets the row to pending + NULL order_id_open before the
                        # replacement Kalshi order is stored. A zero-fill terminal leg on that new
                        # order_id must not delete the trade if a prior leg already reduced position
                        # below initial_count (exchange holds contracts not reflected in this leg's
                        # fill_count). A brand-new pending row still has position == initial_count
                        # until the first IOC confirm; those true zero-fills must keep IOC_ZERO_FILL.
                        tr_pos_f_pending = _trade_position_for_db(tr_pos)
                        try:
                            tr_ic_chk = int(tr_ic) if tr_ic is not None else 0
                        except (TypeError, ValueError):
                            tr_ic_chk = 0
                        prior_leg_filled_some = (
                            tr_ic_chk > 0 and tr_pos_f_pending + 1e-9 < float(tr_ic_chk)
                        )
                        if prior_leg_filled_some:
                            pg_conn.close()
                            try:
                                pg_conn_rev = get_postgresql_connection()
                                if pg_conn_rev:
                                    with pg_conn_rev.cursor() as cur_rev:
                                        cur_rev.execute(
                                            f"""
                                            UPDATE {_tm_trades_table()}
                                            SET order_id_open = NULL
                                            WHERE id = %s
                                            """,
                                            (id,),
                                        )
                                    pg_conn_rev.commit()
                                    pg_conn_rev.close()
                            except Exception as e_rev:
                                log_event(
                                    ticket_id,
                                    f"MANAGER: IOC top-up zero-fill clear order_id_open failed: {e_rev}",
                                )
                            update_trade_status(id, "partial")
                            log_event(
                                ticket_id,
                                f"MANAGER: IOC top-up leg zero fill — keeping trade partial "
                                f"(pos={tr_pos_f_pending}); prior leg already on exchange",
                            )
                            notify_strike_table_trade_change(id, "partial")
                            break
                        pg_conn.close()
                        _delete_pending_trade_for_rejection(id, ticket_id, "IOC_ZERO_FILL")
                        break

                    ioc_handled = False
                    if terminal_ioc and fill_val > 0 and row_status in ("pending", "partial"):
                        taker_fees_usd = _parse_dollars(taker_fees_dollars)
                        maker_fees_usd = _parse_dollars(maker_fees_dollars)
                        order_fees_cumulative = (taker_fees_usd or 0.0) + (maker_fees_usd or 0.0)
                        order_cost_cumulative = _parse_dollars(taker_fill_cost_dollars) or 0.0
                        order_fill_cumulative = float(fill_val)
                        old_buy = float(tr_bp) if tr_bp is not None else 0.0
                        old_fees = float(tr_fees) if tr_fees is not None else 0.0
                        try:
                            tr_ic_int = int(tr_ic) if tr_ic is not None else int(round(initial_val))
                        except (TypeError, ValueError):
                            tr_ic_int = int(round(initial_val))
                        tr_pos_f = _trade_position_for_db(tr_pos)
                        ic_f = float(tr_ic_int)
                        # `orders_*`.fill_count_fp and fees are cumulative for this order_id. Pending INSERT
                        # stores `position` = requested size (= initial_count) until first IOC confirm; partial
                        # / top-up pending rows store cumulative filled contracts. Never add full fill twice
                        # when a second confirm runs after status is already partial (see prod 17679).
                        if row_status == "pending":
                            if tr_pos_f + 1e-6 >= ic_f:
                                fill_increment = order_fill_cumulative
                                pos_basis_for_avg = 0.0
                            else:
                                fill_increment = order_fill_cumulative
                                pos_basis_for_avg = tr_pos_f
                        else:
                            fill_increment = max(0.0, order_fill_cumulative - tr_pos_f)
                            pos_basis_for_avg = tr_pos_f
                        if fill_increment <= 0:
                            log_event(
                                ticket_id,
                                f"MANAGER: IOC terminal order already applied (fill={order_fill_cumulative} trade_pos={tr_pos_f}) — skipping duplicate confirm",
                            )
                            pg_conn.close()
                            ioc_handled = True
                            break
                        ratio = (
                            (fill_increment / order_fill_cumulative)
                            if order_fill_cumulative > 0
                            else 1.0
                        )
                        fee_increment = order_fees_cumulative * ratio
                        cost_increment = order_cost_cumulative * ratio
                        new_pos = _trade_position_for_db(pos_basis_for_avg + fill_increment)
                        if pos_basis_for_avg > 0 and old_buy > 0 and fill_increment > 0:
                            avg_buy = (
                                (old_buy * pos_basis_for_avg + cost_increment) / new_pos
                                if new_pos > 0
                                else old_buy
                            )
                        elif fill_increment > 0:
                            avg_buy = cost_increment / fill_increment
                        else:
                            avg_buy = old_buy
                        total_fees_dollars = old_fees + fee_increment
                        position_for_db = new_pos
                        buy_price = avg_buy
                        next_st = "open" if new_pos >= tr_ic_int else "partial"
                        prob_value = prob_value_seed
                        diff_formatted = _format_diff_from_prob_and_buy(prob_value, buy_price)

                        symbol_open = None
                        try:
                            main_port = get_port("main_app")
                            response = requests.get(f"http://localhost:{main_port}/api/{symbol.lower()}_price", timeout=5)
                            if response.ok:
                                symbol_data = response.json()
                                raw_price = symbol_data.get("price")
                                if raw_price is not None:
                                    symbol_open = normalize_trade_spot_price(symbol, raw_price)
                        except Exception as e:
                            log_event(ticket_id, f"MANAGER: symbol_open fetch failed: {e}")
                        if symbol_open is None:
                            symbol_open = _tm_symbol_open_from_live_state(symbol)
                        if symbol_open is None:
                            try:
                                from backend.core.tradeflow_live_reads import tradeflow_requires_live_state

                                if not tradeflow_requires_live_state():
                                    pg_conn_price = get_postgresql_connection()
                                    if pg_conn_price:
                                        with pg_conn_price.cursor() as cur:
                                            cur.execute(
                                                f"""
                                                SELECT price FROM live_data.live_price_log_1s_{symbol.lower()}
                                                ORDER BY timestamp DESC LIMIT 1
                                                """
                                            )
                                            row_sp = cur.fetchone()
                                            if row_sp and row_sp[0] is not None:
                                                symbol_open = normalize_trade_spot_price(
                                                    symbol, row_sp[0]
                                                )
                                        pg_conn_price.close()
                            except Exception as e:
                                log_event(ticket_id, f"MANAGER: live_price_log symbol_open failed: {e}")
                        if symbol_open is None:
                            try:
                                pg_conn_exist = get_postgresql_connection()
                                if pg_conn_exist:
                                    with pg_conn_exist.cursor() as cur:
                                        cur.execute(f"SELECT symbol_open FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                        row_e = cur.fetchone()
                                        if row_e and row_e[0] is not None:
                                            symbol_open = normalize_trade_spot_price(symbol, row_e[0])
                                    pg_conn_exist.close()
                            except Exception as e:
                                log_event(ticket_id, f"MANAGER: existing symbol_open read failed: {e}")

                        try:
                            pg_conn_update = get_postgresql_connection()
                            if pg_conn_update:
                                with pg_conn_update.cursor() as cursor:
                                    cursor.execute(
                                        f"""
                                        UPDATE {_tm_trades_table()}
                                        SET position = %s,
                                            buy_price = %s,
                                            {_sql_slippage_from_buy_price_params()},
                                            fees = %s,
                                            diff = %s,
                                            symbol_open = COALESCE(%s, symbol_open)
                                        WHERE id = %s
                                        """,
                                        (
                                            position_for_db,
                                            buy_price,
                                            buy_price,
                                            buy_price,
                                            total_fees_dollars,
                                            diff_formatted,
                                            symbol_open,
                                            id,
                                        ),
                                    )
                                    pg_conn_update.commit()
                                pg_conn_update.close()
                        except Exception as pg_err:
                            log(f"❌ IOC confirm update failed: {pg_err}")

                        update_trade_status(id, next_st)
                        log_event(
                            ticket_id,
                            f"MANAGER: IOC fill — status={next_st} pos={position_for_db} price={buy_price:.4f} fees=${total_fees_dollars:.4f}",
                        )
                        notify_strike_table_trade_change(id, next_st)
                        pg_conn.close()
                        ioc_handled = True
                        break

                    # Non-IOC (and IOC that did not match above): full fill only
                    if (not ioc_handled) and order_status == "executed" and remaining_val == 0 and fill_val > 0:
                        # Calculate fees from orders table, using *_dollars fixed-point fields
                        taker_fees_usd = _parse_dollars(taker_fees_dollars)
                        maker_fees_usd = _parse_dollars(maker_fees_dollars)
                        total_fees_dollars = (taker_fees_usd or 0.0) + (maker_fees_usd or 0.0)
                    
                        # Calculate position size and buy price from order data (use _fp and *_dollars for precision)
                        position_size = fill_val

                        # taker_fill_cost_dollars is the fixed-point total cost for the filled taker quantity.
                        buy_price = 0.0
                        total_cost_usd = _parse_dollars(taker_fill_cost_dollars)

                        if total_cost_usd is not None and position_size > 0:
                            buy_price = total_cost_usd / position_size
                        elif position_size > 0:
                            # Fallback: orders table had no dollar cost (e.g. API gap); keep existing buy_price from trade row
                            try:
                                pg_conn_bp = get_postgresql_connection()
                                if pg_conn_bp:
                                    with pg_conn_bp.cursor() as cur:
                                        cur.execute(f"SELECT buy_price FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                        bp_row = cur.fetchone()
                                        if bp_row and bp_row[0] is not None:
                                            buy_price = float(bp_row[0])
                                    pg_conn_bp.close()
                            except Exception as e:
                                log_event(ticket_id, f"MANAGER: Could not read existing buy_price for open: {e}")

                        position_for_db = _trade_position_for_db(position_size)
                        log_event(ticket_id, f"MANAGER: Order completely filled - pos={position_for_db}, price={buy_price:.4f}, fees=${total_fees_dollars:.4f}")
                
                        # Get current trade status
                        pg_conn_status = get_postgresql_connection()
                        if pg_conn_status:
                            with pg_conn_status.cursor() as cursor:
                                cursor.execute(f"SELECT status FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                status_row = cursor.fetchone()
                                current_status = status_row[0] if status_row else None
                            pg_conn_status.close()
                        else:
                            current_status = None
                    
                        if current_status == "pending":
                            # Get probability for diff calculation
                            pg_conn_prob = get_postgresql_connection()
                            if pg_conn_prob:
                                with pg_conn_prob.cursor() as cursor:
                                    cursor.execute(f"SELECT prob FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                    prob_row = cursor.fetchone()
                                pg_conn_prob.close()
                            else:
                                prob_row = None
                        
                            prob_value = prob_row[0] if prob_row and prob_row[0] is not None else None
                            diff_value = None
                        
                            diff_formatted = _format_diff_from_prob_and_buy(prob_value, buy_price)
                    
                            symbol_open = _tm_symbol_open_from_live_state(symbol)
                            if symbol_open is not None:
                                log_event(
                                    ticket_id,
                                    f"MANAGER: symbol_open from live_state: {symbol_open}",
                                )
                            if symbol_open is None:
                                try:
                                    main_port = get_port("main_app")
                                    response = requests.get(
                                        f"http://localhost:{main_port}/api/{symbol.lower()}_price",
                                        timeout=5,
                                    )
                                    if response.ok:
                                        symbol_data = response.json()
                                        raw_price = symbol_data.get("price")
                                        if raw_price is not None:
                                            symbol_open = normalize_trade_spot_price(
                                                symbol, raw_price
                                            )
                                            log_event(
                                                ticket_id,
                                                f"MANAGER: Retrieved symbol price for open: {symbol_open}",
                                            )
                                    else:
                                        log_event(
                                            ticket_id,
                                            f"MANAGER: price API status {response.status_code}",
                                        )
                                except Exception as e:
                                    log_event(
                                        ticket_id,
                                        f"MANAGER: Failed to get symbol price from API: {e}",
                                    )

                            if symbol_open is None:
                                try:
                                    from backend.core.tradeflow_live_reads import (
                                        tradeflow_requires_live_state,
                                    )

                                    if not tradeflow_requires_live_state():
                                        pg_conn_price = get_postgresql_connection()
                                        if pg_conn_price:
                                            with pg_conn_price.cursor() as cur:
                                                cur.execute(
                                                    f"""
                                                    SELECT price FROM live_data.live_price_log_1s_{symbol.lower()}
                                                    ORDER BY timestamp DESC LIMIT 1
                                                    """
                                                )
                                                row = cur.fetchone()
                                                if row and row[0] is not None:
                                                    symbol_open = normalize_trade_spot_price(
                                                        symbol, row[0]
                                                    )
                                            pg_conn_price.close()
                                except Exception as e:
                                    log_event(
                                        ticket_id,
                                        f"MANAGER: live_price_log fallback failed: {e}",
                                    )

                            # If we still have no price, keep existing symbol_open from DB (do not overwrite with NULL)
                            if symbol_open is None:
                                try:
                                    pg_conn_exist = get_postgresql_connection()
                                    if pg_conn_exist:
                                        with pg_conn_exist.cursor() as cur:
                                            cur.execute(f"SELECT symbol_open FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                            row = cur.fetchone()
                                            if row and row[0] is not None:
                                                symbol_open = normalize_trade_spot_price(symbol, row[0])
                                                log_event(ticket_id, f"MANAGER: Keeping existing symbol_open: {symbol_open}")
                                        pg_conn_exist.close()
                                except Exception as e:
                                    log_event(ticket_id, f"MANAGER: Could not read existing symbol_open: {e}")

                            # Update additional fields in PostgreSQL BEFORE status change
                            try:
                                pg_conn_update = get_postgresql_connection()
                                if pg_conn_update:
                                    with pg_conn_update.cursor() as cursor:
                                        cursor.execute(f"""
                                            UPDATE {_tm_trades_table()}
                                            SET position = %s,
                                                buy_price = %s,
                                                {_sql_slippage_from_buy_price_params()},
                                                fees = %s,
                                                diff = %s,
                                                symbol_open = %s
                                            WHERE id = %s
                                        """, (position_for_db, buy_price, buy_price, buy_price, total_fees_dollars, diff_formatted, symbol_open, id))
                                    
                                        if cursor.rowcount > 0:
                                            log_debug(f"💾 Trade additional fields updated in PostgreSQL tenant trades from ORDERS data")
                                        else:
                                            log(f"⚠️ No matching trade found in PostgreSQL for ID {id}")
                                    
                                        pg_conn_update.commit()
                                    pg_conn_update.close()
                                else:
                                    log(f"⚠️ Skipping PostgreSQL additional fields update - no connection available")
                            except Exception as pg_err:
                                log(f"❌ Failed to update trade additional fields in PostgreSQL: {pg_err}")
                        
                            # Update trade status to open (this will also update PostgreSQL and notify ATS)
                            update_trade_status(id, 'open')
                        
                            log_event(ticket_id, f"MANAGER: OPEN TRADE CONFIRMED via ORDERS table — pos={position_for_db}, price={buy_price:.4f}, fees=${total_fees_dollars:.4f}, diff={diff_formatted}")
                            # Notify strike table for display update (lowest priority)
                            notify_strike_table_trade_change(id, "open")
                            pg_conn.close()
                            break
                        else:
                            log_event(ticket_id, f"MANAGER: Trade status is not pending (current: {current_status}) - skipping confirmation")
                            pg_conn.close()
                            break
                    else:
                        log_event(ticket_id, f"MANAGER: Order not yet completely filled - status: {order_status}, remaining: {remaining_val}")
                else:
                    log_event(ticket_id, f"MANAGER: Opening order {stored_order_id_open} not found in ORDERS table yet")
            
                pg_conn.close()
                    
            except Exception as e:
                log_event(ticket_id, f"MANAGER: OPEN TRADE WATCH DB read error: {e}")
        
            time.sleep(1)
    
        log_event(ticket_id, f"MANAGER: OPEN TRADE polling complete for order_id_open: {stored_order_id_open}")
    
        # Final status check with fresh connection
        pg_conn_final = get_postgresql_connection()
        if pg_conn_final:
            with pg_conn_final.cursor() as cursor:
                cursor.execute(f"SELECT status FROM {_tm_trades_table()} WHERE id = %s", (id,))
                status_row = cursor.fetchone()
                current_status = status_row[0] if status_row else None
            pg_conn_final.close()
        else:
            current_status = None
    
        if current_status == "pending":
            log_event(ticket_id, f"MANAGER: PENDING TRADE FAILED TO FILL - TIMEOUT (order_id_open: {stored_order_id_open})")
            notify_active_trade_supervisor_direct(id, ticket_id, "error")

def confirm_close_trade(id: int, ticket_id: str) -> None:
    """Confirms a CLOSING trade has been closed by checking ORDERS table for complete close fill.

    Total fees on the trade row are existing fees (open + prior legs) plus close-order taker+maker
    from the synced orders row for order_id_close. Serialized with confirm_open_trade per trade id.
    """
    log(f"CONFIRMING CLOSE TRADE: {id}")
    
    try:
        # Get trade info including the order_id_close we stored
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT ticker, symbol, order_id_close FROM {_tm_trades_table()} WHERE id = %s", (id,))
                row = cursor.fetchone()
            pg_conn.close()
        else:
            row = None
        
        if not row:
            log_event(ticket_id, f"MANAGER: No trade found for ID {id}")
            log(f"NO TRADE FOUND FOR ID: {id}")
            return
        
        expected_ticker = row[0]
        symbol = row[1]
        stored_order_id_close = row[2]
        
        if not stored_order_id_close:
            log_event(ticket_id, f"MANAGER: No order_id_close stored for trade ID {id} - cannot confirm via ORDERS table")
            log(f"NO CLOSE ORDER_ID FOR TRADE: {id}")
            return
        
        with _trade_confirm_lock(id):
            # Check ORDERS table for our specific close order_id
            pg_conn = get_postgresql_connection()
            if not pg_conn:
                log_event(ticket_id, f"MANAGER: Cannot connect to PostgreSQL orders table")
                return
        
            # Check close order once - orders change notification should handle timing
            try:
                with pg_conn.cursor() as cursor:
                    cursor.execute(f"""
                        SELECT remaining_count_fp, fill_count_fp, status,
                               taker_fees_dollars, maker_fees_dollars
                        FROM {_tm_orders_table()} 
                        WHERE order_id = %s
                    """, (stored_order_id_close,))
                    order_row = cursor.fetchone()
            
                if order_row:
                    remaining_count_fp, fill_count_fp, order_status, taker_fees_dollars, maker_fees_dollars = order_row
                    # Legacy integer counts were removed; use *_fp only.
                    remaining_val = _order_count_val(None, remaining_count_fp)
                    fill_val = _order_count_val(None, fill_count_fp)
                    log_event(ticket_id, f"MANAGER: Close order {stored_order_id_close} status: {order_status}, remaining: {remaining_val}, filled: {fill_val}")
                
                    # Check if close order is completely filled (remaining = 0) and executed
                    if order_status == "executed" and remaining_val == 0 and fill_val > 0:
                        log_event(ticket_id, f"MANAGER: CLOSE ORDER COMPLETELY FILLED - Trade {id} confirmed closed")
                        log(f"CLOSE ORDER COMPLETELY FILLED: {expected_ticker}")
                    
                        now_est = datetime.now(ZoneInfo("America/New_York"))
                        closed_at = now_est.strftime("%H:%M:%S")
                    
                        # SIMPLE: Get opening fees already recorded + add closing fees from this order
                        pg_conn_trade = get_postgresql_connection()
                        if pg_conn_trade:
                            with pg_conn_trade.cursor() as cursor:
                                cursor.execute(f"SELECT fees FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                existing_fees_row = cursor.fetchone()
                                existing_fees = existing_fees_row[0] if existing_fees_row else 0.0
                            pg_conn_trade.close()
                        else:
                            existing_fees = 0.0
                    
                        # Add closing order fees to existing opening fees (prefer *_dollars fixed-point fields)
                        taker_fees_usd = _parse_dollars(taker_fees_dollars)
                        maker_fees_usd = _parse_dollars(maker_fees_dollars)
                        close_order_fees_dollars = (taker_fees_usd or 0.0) + (maker_fees_usd or 0.0)
                        total_fees_paid = existing_fees + close_order_fees_dollars
                    
                        log_event(ticket_id, f"MANAGER: SIMPLE fee calc - existing: ${existing_fees}, close order: ${close_order_fees_dollars}, total: ${total_fees_paid}")
                    
                        # Get sell price from the close order data
                        pg_conn_close_order = get_postgresql_connection()
                        if pg_conn_close_order:
                            with pg_conn_close_order.cursor() as cursor:
                                cursor.execute(f"""
                                    SELECT outcome_side, taker_fill_cost_dollars, fill_count_fp
                                    FROM {_tm_orders_table()} 
                                    WHERE order_id = %s
                                """, (stored_order_id_close,))
                                close_order_data = cursor.fetchone()
                            pg_conn_close_order.close()
                        else:
                            close_order_data = None
                    
                        if close_order_data:
                            _close_outcome_side, close_fill_cost_dollars, close_fill_count_fp = close_order_data
                            close_fill_val = _order_count_val(None, close_fill_count_fp)
                            # Calculate sell price from close order (cost per share) using fixed-point dollars
                            total_close_cost_usd = _parse_dollars(close_fill_cost_dollars)
                            sell_price = (total_close_cost_usd / close_fill_val) if (total_close_cost_usd is not None and close_fill_val > 0) else 0.0
                            # For close orders, sell_price should be 1 - the price we paid to close
                            sell_price = 1 - sell_price
                            log_event(ticket_id, f"MANAGER: Calculated sell_price from close order: {sell_price}")
                        else:
                            sell_price = None
                            log_event(ticket_id, f"MANAGER: Could not get close order data for sell price calculation")
                    
                        symbol_close = _resolve_symbol_close_for_finalize(
                            id,
                            symbol,
                            ticket_id=ticket_id,
                            as_of_est=now_est,
                        )
                        if symbol_close is not None:
                            log_event(ticket_id, f"MANAGER: symbol_close for finalize: {symbol_close}")
                        else:
                            log_event(
                                ticket_id,
                                f"MANAGER: symbol_close left unset for {symbol}",
                            )
                    
                        # Get trade data for PnL calculation including existing fees
                        pg_conn_trade = get_postgresql_connection()
                        if pg_conn_trade:
                            with pg_conn_trade.cursor() as cursor:
                                cursor.execute(f"SELECT buy_price, position, close_method, fees FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                trade_data = cursor.fetchone()
                            pg_conn_trade.close()
                        else:
                            trade_data = None
                    
                        if trade_data and sell_price is not None:
                            buy_price, position, close_method, existing_fees = trade_data
                            close_method = close_method or "manual"
                            existing_fees = existing_fees or 0.0
                            try:
                                buy_price = float(buy_price or 0.0)
                            except (TypeError, ValueError):
                                buy_price = 0.0
                            try:
                                position = float(position or 0.0)
                            except (TypeError, ValueError):
                                position = 0.0
                        
                            # Use the total fees we calculated (existing + close order fees)
                            total_fees = float(total_fees_paid) if total_fees_paid is not None else 0.0
                        
                            log_event(ticket_id, f"MANAGER: Final total fees for PnL: ${total_fees}")
                        
                            # Calculate PnL with total fees
                            buy_value = buy_price * position
                            sell_value = sell_price * position
                            pnl = round(sell_value - buy_value - total_fees, 6)
                            roi_pct = None
                            if buy_value is not None and buy_value > 0:
                                roi_pct = round((pnl / buy_value) * 100.0, 5)
                            win_loss = "W" if pnl > 0 else "L" if pnl < 0 else "D"
                        
                            log_event(ticket_id, f"MANAGER: PnL calculation - buy: ${buy_price}, sell: ${sell_price}, total_fees: ${total_fees}, pnl: ${pnl}")
                        
                            # Calculate ret_pct and ret_pct_base (return % vs bankroll and vs mtb_base_value)
                            ret_pct = None
                            ret_pct_base = None
                            pg_conn_bankroll = get_postgresql_connection()
                            if pg_conn_bankroll:
                                with pg_conn_bankroll.cursor() as cursor_bankroll:
                                    cursor_bankroll.execute(f"SELECT bankroll, mtb_base_value FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                    bankroll_row = cursor_bankroll.fetchone()
                                    bankroll = bankroll_row[0] if bankroll_row else None
                                    mtb_base = bankroll_row[1] if bankroll_row and len(bankroll_row) > 1 else None
                                pg_conn_bankroll.close()
                            else:
                                bankroll = None
                                mtb_base = None
                        
                            if bankroll is not None and bankroll > 0:  # Prevent division by zero
                                ret_pct = round((pnl / (bankroll / 100.0)) * 100, 5)
                                log_event(ticket_id, f"MANAGER: Calculated ret_pct: {ret_pct}% (PnL: ${pnl}, Bankroll: {bankroll} cents)")
                            else:
                                log_event(ticket_id, f"MANAGER: Bankroll is zero or None for trade {id}, cannot calculate ret_pct")
                            if mtb_base is not None and mtb_base > 0:
                                ret_pct_base = round((pnl / (mtb_base / 100.0)) * 100, 5)
                        
                            # Get high_price and low_price from active_trades before it's removed
                            high_price, low_price = get_high_low_prices_from_active_trades(id)
                        
                            # SECOND FAILSAFE CHECK: Validate that ATS was monitoring correctly
                            # If high_price == low_price, it means ATS was NOT monitoring (values never changed from initial buy_price)
                            if high_price is not None and low_price is not None and high_price == low_price:
                                log_event(ticket_id, f"MANAGER: ⚠️ FAILSAFE DETECTED - high_price == low_price ({high_price}) - ATS monitoring failure!")
                                log(f"⚠️ FAILSAFE: Trade {id} has high_price == low_price - ATS was not monitoring correctly")
                            
                                # Get monitor identifier to notify the specific ATS instance
                                pg_conn_monitor = get_postgresql_connection()
                                monitor_identifier = None
                                if pg_conn_monitor:
                                    with pg_conn_monitor.cursor() as cursor:
                                        cursor.execute(f"SELECT monitor FROM {_tm_trades_table()} WHERE id = %s", (id,))
                                        monitor_row = cursor.fetchone()
                                        if monitor_row and monitor_row[0]:
                                            monitor_identifier = monitor_row[0]
                                    pg_conn_monitor.close()
                            
                                # Alert the specific ATS instance to restart via monitoring_failure notification
                                if monitor_identifier:
                                    notify_active_trade_supervisor_direct_with_monitor(id, ticket_id, "monitoring_failure", monitor_identifier)
                                    log_event(ticket_id, f"MANAGER: ⚠️ FAILSAFE: Notified ATS instance {monitor_identifier} of monitoring failure")
                                    log(f"⚠️ FAILSAFE: Triggered ATS restart for monitor {monitor_identifier}")
                        
                            # Update trade status to closed with all calculated values including ret_pct, ret_pct_base, roi_pct, and high/low prices
                            update_trade_status_with_ret_pct(id, "closed", closed_at, sell_price, symbol_close, win_loss, pnl, close_method, total_fees, roi_pct, ret_pct, ret_pct_base, high_price, low_price)
                        
                            log_event(ticket_id, f"MANAGER: CLOSE TRADE CONFIRMED - PnL: ${pnl}, W/L: {win_loss}, Fees: ${total_fees}")
                            log(f"CLOSE TRADE CONFIRMED: {expected_ticker}, PnL=${pnl}, W/L={win_loss}")
                        else:
                            # Fallback - just mark as closed without detailed calculations
                            update_trade_status(id, "closed")
                            log_event(ticket_id, f"MANAGER: CLOSE TRADE CONFIRMED (minimal data)")
                    
                        # Notify active trade supervisor
                        notify_active_trade_supervisor_direct(id, ticket_id, "closed")
                    
                        # Notify strike table for display update
                        notify_strike_table_trade_change(id, "closed")
                    
                        pg_conn.close()
                        return
                    else:
                        log_event(ticket_id, f"MANAGER: Close order not yet completely filled - status: {order_status}, remaining: {remaining_val}")
                else:
                    log_event(ticket_id, f"MANAGER: Close order {stored_order_id_close} not found in ORDERS table yet")
            
                pg_conn.close()
                    
            except Exception as e:
                log_event(ticket_id, f"MANAGER: CLOSE TRADE WATCH DB read error: {e}")
                log(f"ERROR CHECKING CLOSE ORDER: {e}")
                return
    except Exception as e:
        log_event(ticket_id, f"MANAGER: Error in confirm_close_trade: {e}")
        log(f"ERROR IN CONFIRM_CLOSE_TRADE: {e}")
        return

# ---------- UTILITY FUNCTIONS ----------------------------------------------------

def get_high_low_prices_from_active_trades(trade_id: int) -> tuple:
    """
    Get high_price and low_price from active_trades table before trade is removed.
    
    Args:
        trade_id: The trade ID
        
    Returns:
        tuple: (high_price, low_price) or (None, None) if not found
    f"""
    try:
        # Get monitor identifier from trades table
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return (None, None)
        
        with pg_conn.cursor() as cursor:
            cursor.execute(f"SELECT monitor FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
            monitor_row = cursor.fetchone()
        pg_conn.close()
        
        if not monitor_row or not monitor_row[0]:
            log(f"⚠️ No monitor found for trade {trade_id}, cannot get high/low prices")
            return (None, None)
        
        monitor_identifier = monitor_row[0]
        
        # Extract user number and monitor ID from monitor identifier (e.g., "mon_0001_10002" -> "0001", "10002")
        if monitor_identifier.startswith('mon_'):
            monitor_suffix = monitor_identifier[4:]  # Remove "mon_" prefix
            parts = monitor_suffix.split('_')
            if len(parts) == 2:
                user_number = parts[0]
                monitor_id = parts[1]
            else:
                log(f"⚠️ Invalid monitor identifier format: {monitor_identifier}")
                return (None, None)
        else:
            log(f"⚠️ Monitor identifier doesn't start with 'mon_': {monitor_identifier}")
            return (None, None)
        
        try:
            from backend.core.live_state_active_trades import (
                get_high_low_prices,
                live_state_active_trades_enabled,
            )

            if live_state_active_trades_enabled():
                hp, lp = get_high_low_prices(user_number, trade_id)
                if hp is not None or lp is not None:
                    log(
                        f"📊 Retrieved high_price={hp}, low_price={lp} for trade {trade_id} (Redis)"
                    )
                    return (hp, lp)
        except Exception as redis_e:
            log_debug(f"Redis high/low lookup failed for trade {trade_id}: {redis_e}")

        from backend.core.live_state_active_trades import active_trades_pg_dual_write

        if not active_trades_pg_dual_write():
            log(f"⚠️ Trade {trade_id} not found in Redis active_trades pool")
            return (None, None)

        from backend.core.port_config import (
            monitor_suffix_uses_unified_15m_pool,
            monitor_suffix_uses_unified_hourly_pool,
        )

        suffix = f"{user_number}_{monitor_id}"
        if monitor_suffix_uses_unified_15m_pool(suffix):
            active_trades_table = f"active_trades_15m_{user_number}"
        elif monitor_suffix_uses_unified_hourly_pool(suffix):
            active_trades_table = f"active_trades_hourly_{user_number}"
        else:
            active_trades_table = f"active_trades_{user_number}_{monitor_id}"

        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return (None, None)

        with pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT high_price, low_price
                FROM users.{active_trades_table}
                WHERE trade_id = %s
                """,
                (trade_id,),
            )
            price_row = cursor.fetchone()
        pg_conn.close()

        if price_row:
            high_price, low_price = price_row
            log(f"📊 Retrieved high_price={high_price}, low_price={low_price} for trade {trade_id}")
            return (high_price, low_price)
        log(f"⚠️ Trade {trade_id} not found in active_trades table {active_trades_table}")
        return (None, None)
            
    except Exception as e:
        log(f"❌ Error getting high/low prices from active_trades for trade {trade_id}: {e}")
        return (None, None)


def _split_monitor_identifier(monitor_key: str):
    """Return (user_id, monitor_id) tuple parsed from monitor key like mon_0001_10002."""
    if not monitor_key:
        return None

    match = MONITOR_KEY_PATTERN.match(monitor_key)
    if match:
        return match.group(1), match.group(2)

    parts = monitor_key.split("_")
    if len(parts) >= 3 and parts[0].lower() == "mon":
        return parts[1], parts[2]

    return None


def _lookup_monitor_symbol(conn, user_id: str, monitor_key: str) -> str:
    """Best-effort lookup of the symbol tied to a monitor."""
    symbol = None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT symbol FROM {}.{} WHERE name = %s LIMIT 1").format(
                    sql.Identifier("users"),
                    sql.Identifier(f"monitor_list_{user_id}")
                ),
                (monitor_key,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                symbol = row[0]
    except Exception:
        # Table might not exist for every user; fall back silently.
        symbol = None

    if not symbol:
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT symbol
                    FROM {_tm_trades_table()}
                    WHERE monitor = %s AND symbol IS NOT NULL
                    ORDER BY created_at DESC NULLS LAST, id DESC
                    LIMIT 1
                    """,
                    (monitor_key,)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    symbol = row[0]
        except Exception:
            symbol = None

    return symbol if symbol else "UNKNOWN"


def refresh_monitor_cycle_performance_for_monitor(
    monitor_key: str,
    *,
    window_days: int = 84,
    weekly_cycle: Optional[int] = None
) -> None:
    """Recompute the monitor_cycle_performance table for a monitor."""
    monitor_parts = _split_monitor_identifier(monitor_key)
    if not monitor_parts:
        log(f"⚠️ Cannot refresh performance table for unknown monitor format: {monitor_key}")
        return

    user_id, monitor_id = monitor_parts
    table_name = f"monitor_cycle_performance_{user_id}_{monitor_id}"
    index_name = f"{table_name}_winrate_idx"
    table_ref = f"users.{table_name}"
    interval_literal = f"{window_days} days"

    conn = get_postgresql_connection()
    if not conn:
        log(f"⚠️ Skipping performance refresh for {monitor_key} - no database connection")
        return

    try:
        is_archived = False
        with conn.cursor() as cursor:
            try:
                cursor.execute(
                    f"SELECT status FROM users.monitor_list_{user_id} WHERE name = %s LIMIT 1",
                    (monitor_key,)
                )
                status_row = cursor.fetchone()
                if status_row and status_row[0] and str(status_row[0]).upper() == "ARCHIVED":
                    is_archived = True
            except Exception:
                pass

        if is_archived:
            log(f"ℹ️ Skipping performance refresh for archived monitor {monitor_key}")
            return

        symbol_label = _lookup_monitor_symbol(conn, user_id, monitor_key) or "UNKNOWN"

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_ref} (
                    weekly_cycle            SMALLINT PRIMARY KEY,
                    day_name                TEXT,
                    contract_hour           TEXT,
                    trade_count             INT      NOT NULL DEFAULT 0,
                    win_count               INT      NOT NULL DEFAULT 0,
                    win_rate_pct            NUMERIC(5,2),
                    avg_collateral_exposure INT,
                    median_exposure         INT,
                    max_exposure            INT,
                    max_pct_exposure        NUMERIC(10,2) NOT NULL DEFAULT 0,
                    performance_modifier    NUMERIC(10,2) NOT NULL DEFAULT 0,
                    window_start            TIMESTAMPTZ,
                    window_end              TIMESTAMPTZ,
                    last_updated            TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {table_ref} (win_rate_pct DESC NULLS LAST)
                """
            )
            cursor.execute(
                f"""
                INSERT INTO {table_ref} (weekly_cycle)
                SELECT gs
                FROM generate_series(1, 168) AS gs
                ON CONFLICT (weekly_cycle) DO NOTHING
                """
            )
        conn.commit()

        weekly_cycle_filter = weekly_cycle
        if weekly_cycle_filter is not None:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table_ref}")
                row = cursor.fetchone()
                if not row or row[0] < 168:
                    weekly_cycle_filter = None

        update_query = f"""
            WITH params AS (
                SELECT
                    NOW()::timestamptz AS now_ts,
                    (NOW()::date - %s::interval)::timestamptz AS win_start
            ),
            trades_norm AS (
                SELECT
                    t.side,
                    t.win_loss,
                    t.status,
                    t.hour_idx,
                    FLOOR(t.weekly_cycle)::int AS weekly_cycle,
                    (t.date || ' ' || COALESCE(NULLIF(t.time, ''), '00:00:00'))::timestamptz AS trade_ts
                FROM {_tm_trades_table()} t
                CROSS JOIN params p
                WHERE t.monitor = %s
                  AND (t.date || ' ' || COALESCE(NULLIF(t.time, ''), '00:00:00'))::timestamptz BETWEEN p.win_start AND p.now_ts
                  AND t.weekly_cycle >= 1 AND t.weekly_cycle < 169
            ),
            cycle_counts AS (
                SELECT
                    tn.trade_ts::date AS trade_date,
                    tn.hour_idx,
                    tn.weekly_cycle,
                    SUM(CASE WHEN LOWER(COALESCE(tn.side::text, '')) IN ('y','yes') THEN 1 ELSE 0 END) AS yes_cnt,
                    SUM(CASE WHEN LOWER(COALESCE(tn.side::text, '')) IN ('n','no') THEN 1 ELSE 0 END) AS no_cnt,
                    SUM(CASE WHEN LOWER(COALESCE(tn.win_loss::text, tn.status::text)) IN ('w','win','1','true','yes','won') THEN 1 ELSE 0 END) AS wins,
                    COUNT(*) AS trades
                FROM trades_norm tn
                GROUP BY tn.trade_ts::date, tn.hour_idx, tn.weekly_cycle
            ),
            cycle_exposure AS (
                SELECT
                    weekly_cycle,
                    GREATEST(yes_cnt, no_cnt) AS exposure,
                    wins,
                    trades
                FROM cycle_counts
            ),
            hour_agg AS (
                SELECT
                    weekly_cycle,
                    SUM(trades) AS trade_count,
                    SUM(wins)   AS win_count,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY exposure) AS median_exposure,
                    MAX(exposure) AS max_exposure,
                    AVG(exposure) AS avg_exposure_float
                FROM cycle_exposure
                GROUP BY weekly_cycle
            ),
            all_cycles AS (
                SELECT
                    gs AS weekly_cycle,
                    CASE ((gs - 1) / 24)
                        WHEN 0 THEN 'Sunday'
                        WHEN 1 THEN 'Monday'
                        WHEN 2 THEN 'Tuesday'
                        WHEN 3 THEN 'Wednesday'
                        WHEN 4 THEN 'Thursday'
                        WHEN 5 THEN 'Friday'
                        WHEN 6 THEN 'Saturday'
                    END AS day_name,
            CASE (MOD(gs - 1, 24) + 1)
                        WHEN 24 THEN '12am'
                        WHEN 12 THEN '12pm'
                        WHEN 13 THEN '1pm'
                        WHEN 14 THEN '2pm'
                        WHEN 15 THEN '3pm'
                        WHEN 16 THEN '4pm'
                        WHEN 17 THEN '5pm'
                        WHEN 18 THEN '6pm'
                        WHEN 19 THEN '7pm'
                        WHEN 20 THEN '8pm'
                        WHEN 21 THEN '9pm'
                        WHEN 22 THEN '10pm'
                        WHEN 23 THEN '11pm'
                ELSE (MOD(gs - 1, 24) + 1)::text || 'am'
                    END AS hour_label,
                    COALESCE(ha.trade_count, 0) AS trade_count,
                    COALESCE(ha.win_count, 0) AS win_count,
                    CASE WHEN COALESCE(ha.trade_count, 0) > 0
                        THEN ROUND(100.0 * ha.win_count::numeric / ha.trade_count::numeric, 2)
                        ELSE 0
                    END AS win_rate_pct,
                    COALESCE(ROUND(ha.avg_exposure_float)::int, 0) AS avg_collateral_exposure,
                    COALESCE(ROUND(ha.median_exposure)::int, 0) AS median_exposure,
                    COALESCE(ha.max_exposure::int, 0) AS max_exposure
                FROM generate_series(1, 168) AS gs
                LEFT JOIN hour_agg ha ON ha.weekly_cycle = gs
                WHERE (%s) IS NULL OR gs = %s
            ),
            metrics AS (
                SELECT
                    ac.weekly_cycle,
                    ac.day_name,
                    %s || ' ' || ac.hour_label AS contract_hour,
                    ac.trade_count,
                    ac.win_count,
                    ac.win_rate_pct,
                    ac.avg_collateral_exposure,
                    ac.median_exposure,
                    ac.max_exposure,
                    CASE
                        WHEN ac.avg_collateral_exposure IS NULL OR ac.avg_collateral_exposure = 0 THEN 0.25
                        WHEN ac.avg_collateral_exposure = 1 THEN 0.50
                        ELSE ROUND(1.0 / NULLIF(ac.avg_collateral_exposure::numeric, 0), 2)
                    END AS max_pct_exposure,
                    CASE
                        WHEN ac.trade_count = 0 THEN 1.00
                        WHEN ac.win_rate_pct < 90 THEN 0.25
                        WHEN ac.win_rate_pct >= 90 AND ac.win_rate_pct < 95 THEN 0.50
                        WHEN ac.trade_count >= 20 AND ac.win_rate_pct = 100 THEN 1.50
                        ELSE 1.00
                    END AS performance_modifier,
                    p.win_start AS window_start,
                    p.now_ts AS window_end
                FROM all_cycles ac
                CROSS JOIN params p
            )
            UPDATE {table_ref} dst
            SET
                day_name = m.day_name,
                contract_hour = m.contract_hour,
                trade_count = m.trade_count,
                win_count = m.win_count,
                win_rate_pct = m.win_rate_pct,
                avg_collateral_exposure = m.avg_collateral_exposure,
                median_exposure = m.median_exposure,
                max_exposure = m.max_exposure,
                max_pct_exposure = m.max_pct_exposure,
                performance_modifier = m.performance_modifier,
                window_start = m.window_start,
                window_end = m.window_end,
                last_updated = NOW()
            FROM metrics m
            WHERE dst.weekly_cycle = m.weekly_cycle
        """

        params = (
            interval_literal,
            monitor_key,
            weekly_cycle_filter,
            weekly_cycle_filter,
            symbol_label
        )

        with conn.cursor() as cursor:
            cursor.execute(update_query, params)

        conn.commit()
    except Exception as exc:
        conn.rollback()
        log(f"⚠️ Failed to refresh performance table for {monitor_key}: {exc}")
    finally:
        conn.close()


def refresh_monitor_cycle_performance_for_trade(trade_id: int, *, window_days: int = 84) -> None:
    """Update the monitor-cycle table row associated with a newly closed trade."""
    conn = get_postgresql_connection()
    if not conn:
        log(f"⚠️ Skipping performance refresh for trade {trade_id} - no database connection")
        return

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT monitor, weekly_cycle FROM {_tm_trades_table()} WHERE id = %s",
                (trade_id,)
            )
            row = cursor.fetchone()
        conn.close()

        if not row:
            log(f"⚠️ Trade {trade_id} not found when refreshing performance table")
            return

        monitor_key, weekly_cycle_raw = row
        if not monitor_key or weekly_cycle_raw is None:
            log(f"⚠️ Trade {trade_id} missing monitor or weekly_cycle for performance update")
            return
        weekly_cycle = int(float(weekly_cycle_raw))  # use integer part for performance lookup

        refresh_monitor_cycle_performance_for_monitor(
            monitor_key,
            window_days=window_days,
            weekly_cycle=weekly_cycle
        )
    except Exception as exc:
        log(f"⚠️ Failed to refresh performance for trade {trade_id}: {exc}")
        try:
            conn.close()
        except Exception:
            pass


def refresh_all_monitor_cycle_performance(window_days: int = 84) -> None:
    """Refresh all monitor performance tables for the rolling window."""
    conn = get_postgresql_connection()
    if not conn:
        log("⚠️ Skipping daily performance refresh - no database connection")
        return

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT DISTINCT monitor FROM {_tm_trades_table()} WHERE monitor IS NOT NULL"
            )
            monitors = [row[0] for row in cursor.fetchall()]
        conn.close()

        if not monitors:
            log("ℹ️ No monitors found for performance refresh")
            return

        for monitor_key in monitors:
            refresh_monitor_cycle_performance_for_monitor(
                monitor_key,
                window_days=window_days
            )
    except Exception as exc:
        log(f"⚠️ Failed to refresh all monitor performance tables: {exc}")
        try:
            conn.close()
        except Exception:
            pass

from backend.util.trade_logger import log_trade_event

def log_event(ticket_id, message, trade_id=None):
    """Log trade events to PostgreSQL instead of text files.

    ``trade_id`` is optional metadata for searchability (same shape as ``trade_executor.log_event``).
    """
    try:
        if trade_id is not None:
            message = f"{message} trade_id={trade_id}"
        log_trade_event(ticket_id, message, service="trade_manager")
    except Exception as e:
        log(f"[LOG ERROR] Failed to write log: {message} — {e}")

def notify_active_trade_supervisor_direct_with_monitor(trade_id: int, ticket_id: str, status: str, monitor_identifier: str) -> bool:
    """Send direct notification to ATS via Redis (non-open) or HTTP with retries (system-critical path)."""
    monitor_suffix = _monitor_suffix_from_identifier(monitor_identifier)
    if not monitor_suffix:
        log(f"ERROR: No valid monitor identifier found for trade {trade_id}")
        return False
    payload = {
        "trade_id": trade_id,
        "ticket_id": ticket_id,
        "status": status,
        "monitor_identifier": monitor_suffix,
    }
    try:
        from backend.core.trading_redis_comms import publish_ats_tm_notification, redis_client_optional, use_trading_redis_comms

        if use_trading_redis_comms() and status != "open":
            r = redis_client_optional()
            if r and publish_ats_tm_notification(
                r, trade_id, ticket_id or "", status, monitor_suffix
            ):
                log(
                    f"NOTIFIED ATS (Redis) for monitor {monitor_suffix} trade_id={trade_id} status={status}"
                )
                return True
            if not ATS_HTTP_FALLBACK_ENABLED:
                _log_ats_http_fallback_throttled(
                    f"ATS notify dropped (Redis unavailable, HTTP fallback disabled) "
                    f"mon={monitor_suffix} trade_id={trade_id} status={status}"
                )
                return False
    except Exception as e:
        if not ATS_HTTP_FALLBACK_ENABLED:
            _log_ats_http_fallback_throttled(
                f"ATS Redis notify failed and HTTP fallback disabled mon={monitor_suffix} "
                f"trade_id={trade_id} status={status}: {e}"
            )
            return False
        log(f"⚠️ ATS Redis notify failed, using HTTP: {e}")
    if not ATS_HTTP_FALLBACK_ENABLED:
        _log_ats_http_fallback_throttled(
            f"ATS notify dropped (Redis not selected, HTTP fallback disabled) "
            f"mon={monitor_suffix} trade_id={trade_id} status={status}"
        )
        return False
    ok, err = _post_ats_trade_notification_http(monitor_suffix, payload)
    if ok:
        log(f"NOTIFIED ACTIVE TRADE SUPERVISOR for monitor {monitor_suffix} trade_id={trade_id} status={status}")
        return True
    log(f"ACTIVE TRADE SUPERVISOR ERROR for monitor {monitor_suffix} trade_id={trade_id}: {err}")
    return False

def notify_active_trade_supervisor_direct(trade_id: int, ticket_id: str, status: str) -> bool:
    """Send direct notification to ATS via HTTP (loads monitor from DB, then resilient POST)."""
    monitor_identifier = None
    pg_conn = get_postgresql_connection()
    if pg_conn:
        try:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT monitor FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    monitor_identifier = row[0]
        finally:
            pg_conn.close()
    if not monitor_identifier:
        log(f"ERROR: No monitor on trade row for trade {trade_id}")
        return False
    return notify_active_trade_supervisor_direct_with_monitor(
        trade_id, ticket_id, status, str(monitor_identifier)
    )


def notify_ats_trade_open_with_ack(trade_id: int) -> None:
    """
    When a trade becomes open: publish to Redis (rec_io:ats_enroll_request) and wait for ATS ACK.
    Retries Redis publish/wait (slow subscriber / load). On failure: HTTP fallback with retries.
    Logs CRITICAL only if all attempts fail.
    """
    from backend.core.ats_enrollment_redis import (
        publish_trade_open_enroll_request,
        redis_client_optional,
        wait_trade_open_enroll_ack,
    )

    pg_conn = get_postgresql_connection()
    if not pg_conn:
        log(f"❌ notify_ats_trade_open_with_ack: no DB for trade {trade_id}")
        return
    with pg_conn.cursor() as cursor:
        cursor.execute(
            f"SELECT ticket_id, monitor, exchange FROM {_tm_trades_table()} WHERE id = %s",
            (trade_id,),
        )
        row = cursor.fetchone()
    pg_conn.close()
    if not row:
        log(f"❌ notify_ats_trade_open_with_ack: trade {trade_id} not found")
        return
    ticket_id, monitor = row[0], row[1]
    venue_exchange = normalize_exchange(row[2] if len(row) > 2 else None)
    if not monitor or not str(monitor).startswith("mon_"):
        log(f"❌ notify_ats_trade_open_with_ack: invalid monitor for trade {trade_id}")
        return
    monitor_suffix = str(monitor)[4:]
    tid = ticket_id if ticket_id else ""
    wait_sec = _ATS_ENROLL_ACK_WAIT_SEC
    redis_rounds = _ATS_ENROLL_REDIS_ATTEMPTS

    r = redis_client_optional()
    if r:
        explicit_fail = False
        for round_i in range(redis_rounds):
            cid = str(uuid.uuid4())
            if not publish_trade_open_enroll_request(
                r, trade_id, tid, monitor_suffix, cid, venue_exchange
            ):
                log(
                    f"⚠️ ATS Redis publish failed trade_id={trade_id} round={round_i + 1}/{redis_rounds}"
                )
                time.sleep(min(2.0, 0.4 * (2**round_i)))
                continue
            ack = wait_trade_open_enroll_ack(r, cid, wait_sec)
            if ack and ack.get("ok"):
                if ack.get("degraded"):
                    log(
                        f"⚠️ ATS enrollment confirmed (degraded / no live Kalshi quote) trade_id={trade_id}"
                    )
                else:
                    log(f"✅ ATS enrollment confirmed via Redis trade_id={trade_id}")
                return
            if ack and ack.get("ok") is False:
                explicit_fail = True
                log(
                    f"⚠️ ATS Redis ACK ok=false trade_id={trade_id} round={round_i + 1}; falling back to HTTP"
                )
                break
            log(
                f"⚠️ ATS Redis enroll no ACK in {wait_sec}s trade_id={trade_id} round={round_i + 1}/{redis_rounds}"
            )
            if round_i + 1 < redis_rounds:
                time.sleep(min(3.0, 0.5 * (2**round_i)) + random.uniform(0, 0.2))
        if not explicit_fail:
            log(
                f"🚨 CRITICAL: ATS Redis enrollment exhausted after {redis_rounds} round(s) — trade_id={trade_id} monitor={monitor_suffix}"
            )
            log_event(
                tid or str(trade_id),
                f"CRITICAL: ATS Redis enrollment failed for OPEN trade_id={trade_id}",
            )
    else:
        log(f"⚠️ Redis unavailable; ATS open notify via HTTP only trade_id={trade_id}")

    ok_http = notify_active_trade_supervisor_direct_with_monitor(
        trade_id, tid, "open", monitor
    )
    if not ok_http:
        log(
            f"🚨 CRITICAL: ATS HTTP fallback failed — OPEN trade_id={trade_id} may be UNTRACKED (no stop-loss path)"
        )
        log_event(
            tid or str(trade_id),
            f"CRITICAL: ATS HTTP notify failed; UNTRACKED open trade_id={trade_id}",
        )


def _fanout_trade_log_lifecycle(trade_id: int, status: str) -> None:
    """Trade history: invalidate insights cache + targeted refetch (not mark ticks)."""
    try:
        from backend.core.trades_history_insights_cache import bump_insights_cache_version
        from backend.core.trading_redis_comms import publish_preferences_event, use_trading_redis_comms
        from backend.core.tenant_context import effective_tenant_context_for_sql_rewrite

        slot = effective_tenant_context_for_sql_rewrite().user_no
        bump_insights_cache_version(slot)
        if use_trading_redis_comms():
            publish_preferences_event(
                "trade_log_changed",
                {"trade_id": int(trade_id), "status": str(status)},
                tenant_user_no=slot,
            )
    except Exception:
        pass


def _fanout_trade_marks_closed(
    trade_id: int,
    *,
    sell_price: Optional[float] = None,
    pnl: Optional[float] = None,
    ret_pct: Optional[float] = None,
) -> None:
    """Push final sell/pnl to trade history via WebSocket (no full /trades refetch)."""
    mark: Dict[str, Any] = {"trade_id": int(trade_id)}
    if sell_price is not None:
        mark["sell_price"] = float(sell_price)
    if pnl is not None:
        mark["pnl"] = float(pnl)
    if ret_pct is not None:
        mark["ret_pct"] = float(ret_pct)
    if len(mark) < 2:
        return
    try:
        from backend.core.trading_redis_comms import publish_trade_marks_ws_message
        from backend.core.tenant_context import effective_tenant_context_for_sql_rewrite

        slot = effective_tenant_context_for_sql_rewrite().user_no
        publish_trade_marks_ws_message([mark], tenant_user_no=slot)
    except Exception:
        pass


def notify_frontend_trade_change() -> None:
    """Send notification to frontend when trades are updated"""
    notify_frontend_trade_change_redis_or_http()

def notify_strike_table_trade_change(trade_id: int, status: str) -> None:
    """Notify strike table about trade status changes for display updates"""
    notify_strike_table_trade_change_redis_or_http(trade_id, status)

def truncate_contract_name(contract_name, symbol=None):
    """Truncate contract name to short form like 'SYMBOL 5pm'"""
    if not contract_name:
        return contract_name
    
    # If already short and contains symbol, return as-is
    if symbol and contract_name.startswith(f"{symbol} ") and len(contract_name) < 20:
        return contract_name
    
    import re
    time_match = re.search(r'at (\d+)(am|pm)', contract_name, re.IGNORECASE)
    if time_match and symbol:
        hour = time_match.group(1)
        ampm = time_match.group(2).lower()
        return f"{symbol} {hour}{ampm}"
    
    return contract_name

# ---------- DATABASE FUNCTIONS ----------------------------------------------------

def init_trades_db():
    """Initialize PostgreSQL database structure for fresh installs"""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log("⚠️ Cannot connect to PostgreSQL - skipping database initialization")
            return
        
        with pg_conn.cursor() as cursor:
            # Create users schema if it doesn't exist
            cursor.execute("CREATE SCHEMA IF NOT EXISTS users")
            
            # Create trades table
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {_tm_trades_table()} (
                    id INTEGER PRIMARY KEY,
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    exchange TEXT DEFAULT 'kalshi',
                    trade_strategy TEXT DEFAULT 'Hourly HTC',
                    contract TEXT,
                    strike TEXT NOT NULL,
                    side TEXT NOT NULL,
                    prob REAL,
                    diff TEXT,
                    buy_price NUMERIC(12,6) NOT NULL,
                    position NUMERIC(12,2) NOT NULL,
                    sell_price NUMERIC(12,6),
                    closed_at TEXT,
                    fees REAL,
                    pnl REAL,
                    symbol_open NUMERIC(18,5),
                    symbol_close NUMERIC(18,5),
                    momentum REAL,
                    volatility_percentile REAL,
                    win_loss TEXT,
                    ticker TEXT,
                    ticket_id TEXT,
                    market_id TEXT,
                    momentum_percentile REAL,
                    entry_method TEXT DEFAULT 'manual',
                    close_method TEXT,
                    order_id_open TEXT,
                    order_id_close TEXT,
                    high_price DECIMAL(10,4),
                    low_price DECIMAL(10,4),
                    loss_prevention BOOLEAN DEFAULT FALSE,
                    multiplier DECIMAL(10,2),
                    paper_trade BOOLEAN DEFAULT FALSE,
                    cooldown_timer INTEGER
                )
            """)
            
            # Create sequence for auto-incrementing ID
            cursor.execute(f"""
                CREATE SEQUENCE IF NOT EXISTS {_tm_trades_table()}_id_seq1
                INCREMENT 1
                START 1
                OWNED BY {_tm_trades_table()}.id
            """)
            
            # Create fills table (fixed-point: count_fp and *_dollars only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users.fills_0001 (
                    id SERIAL PRIMARY KEY,
                    trade_id TEXT UNIQUE,
                    ticker TEXT,
                    order_id TEXT,
                    outcome_side TEXT,
                    orderbook_side TEXT,
                    action TEXT,
                    count_fp NUMERIC(12,2),
                    yes_price_dollars TEXT,
                    no_price_dollars TEXT,
                    is_taker BOOLEAN,
                    created_time TEXT,
                    raw_json TEXT
                )
            """)
            
            # Create settlements table (fixed-point counts and *_total_cost_dollars)
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
                    raw_json TEXT,
                    UNIQUE(ticker, settled_time)
                )
            """)
            
            # Create positions table (fixed-point / dollars only)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users.positions_0001 (
                    id SERIAL PRIMARY KEY,
                    ticker TEXT,
                    last_updated_ts TEXT,
                    raw_json TEXT,
                    total_traded_dollars TEXT,
                    market_exposure_dollars TEXT,
                    realized_pnl_dollars TEXT,
                    fees_paid_dollars TEXT,
                    total_traded_fp NUMERIC(12,2),
                    position_fp NUMERIC(12,2)
                )
            """)
            
            # Create live_data schema if it doesn't exist
            cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data")
            

            
            # Add order_id columns if they don't exist (for existing databases).
            # Use savepoints so a failing ALTER/UPDATE doesn't leave the transaction aborted.
            # IMPORTANT: keep a short lock timeout so startup never hangs behind an open txn.
            try:
                cursor.execute("SAVEPOINT sp_order_id_open")
                cursor.execute("SET LOCAL lock_timeout = '1500ms'")
                cursor.execute(f"ALTER TABLE {_tm_trades_table()} ADD COLUMN order_id_open TEXT")
                log_debug("✅ Added order_id_open column to existing trades table")
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT sp_order_id_open")
                emsg = str(e).lower()
                if "already exists" in emsg or "duplicate column" in emsg:
                    log_debug("✅ order_id_open column already exists in trades table")
                elif "lock timeout" in emsg or "canceling statement due to lock timeout" in emsg:
                    log("⚠️ Skipping order_id_open DDL at startup (table busy; will retry on next boot)")
                else:
                    log(f"⚠️ Note: Could not add order_id_open column: {e}")
            
            try:
                cursor.execute("SAVEPOINT sp_order_id_close")
                cursor.execute("SET LOCAL lock_timeout = '1500ms'")
                cursor.execute(f"ALTER TABLE {_tm_trades_table()} ADD COLUMN order_id_close TEXT")
                log_debug("✅ Added order_id_close column to existing trades table")
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT sp_order_id_close")
                emsg = str(e).lower()
                if "already exists" in emsg or "duplicate column" in emsg:
                    log_debug("✅ order_id_close column already exists in trades table")
                elif "lock timeout" in emsg or "canceling statement due to lock timeout" in emsg:
                    log("⚠️ Skipping order_id_close DDL at startup (table busy; will retry on next boot)")
                else:
                    log(f"⚠️ Note: Could not add order_id_close column: {e}")
            
            # Migrate existing order_id data to order_id_open
            try:
                cursor.execute("SAVEPOINT sp_migrate_order_id")
                cursor.execute("SET LOCAL lock_timeout = '1500ms'")
                cursor.execute(f"UPDATE {_tm_trades_table()} SET order_id_open = order_id WHERE order_id IS NOT NULL AND order_id_open IS NULL")
                migrated_count = cursor.rowcount
                if migrated_count > 0:
                    log_debug(f"✅ Migrated {migrated_count} existing order_id values to order_id_open")
            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT sp_migrate_order_id")
                emsg = str(e).lower()
                if "lock timeout" in emsg or "canceling statement due to lock timeout" in emsg:
                    log("⚠️ Skipping order_id migration at startup (table busy; will retry on next boot)")
                else:
                    log(f"⚠️ Could not migrate existing order_id data: {e}")
            
            # Create indexes for better performance
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_trades_0001_status ON {_tm_trades_table()}(status)")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_trades_0001_ticker ON {_tm_trades_table()}(ticker)")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_trades_0001_order_id_open ON {_tm_trades_table()}(order_id_open)")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_trades_0001_order_id_close ON {_tm_trades_table()}(order_id_close)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_fills_0001_ticker ON users.fills_0001(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_settlements_0001_ticker ON users.settlements_0001(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_0001_ticker ON users.positions_0001(ticker)")

            
            pg_conn.commit()
            log_debug("✅ PostgreSQL database structure initialized successfully")
            
        pg_conn.close()
        
    except Exception as e:
        log(f"❌ Error initializing PostgreSQL database structure: {e}")
        try:
            pg_conn.close()
        except:
            pass

init_trades_db()



def update_trade_status_with_ret_pct(trade_id, status, closed_at=None, sell_price=None, symbol_close=None, win_loss=None, pnl=None, close_method=None, fees=None, roi_pct=None, ret_pct=None, ret_pct_base=None, high_price=None, low_price=None):
    """Update trade status in PostgreSQL database with ret_pct and ret_pct_base (return % vs mtb_base_value)."""
    if status == 'closed':
        if closed_at is None:
            utc_now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
            est_now = utc_now.astimezone(ZoneInfo("America/New_York"))
            closed_at = est_now.isoformat()

        if pnl is not None:
            calculated_pnl = pnl
        else:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor_pg:
                    cursor_pg.execute(f"SELECT buy_price, position FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                    row = cursor_pg.fetchone()
                    buy_price = row[0] if row else None
                    position = row[1] if row else None
                    fees_paid = fees if fees is not None else 0.0
            else:
                buy_price = None
                position = None
                fees_paid = fees if fees is not None else 0.0

            if buy_price is not None and sell_price is not None:
                win_loss = 'W' if sell_price > buy_price else 'L'
            else:
                win_loss = None

            calculated_pnl = None
            buy_value = None
            if buy_price is not None and sell_price is not None and position is not None:
                buy_value = buy_price * position
                sell_value = sell_price * position
                fees = fees_paid if fees_paid is not None else 0.0
                calculated_pnl = round(sell_value - buy_value - fees, 6)

        # Calculate roi_pct if not provided and we have enough data
        roi_value = roi_pct
        if roi_value is None:
            try:
                if calculated_pnl is not None:
                    if 'buy_value' not in locals() or buy_value is None:
                        # Fetch buy_price/position if we didn't compute buy_value above
                        pg_conn_roi = get_postgresql_connection()
                        if pg_conn_roi:
                            with pg_conn_roi.cursor() as cur_roi:
                                cur_roi.execute(f"SELECT buy_price, position FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                                row = cur_roi.fetchone()
                                if row and row[0] is not None and row[1] is not None:
                                    buy_value = row[0] * row[1]
                            pg_conn_roi.close()
                    if buy_value is not None and buy_value > 0:
                        roi_value = round((calculated_pnl / buy_value) * 100.0, 5)
            except Exception:
                roi_value = roi_pct

    # Update PostgreSQL only
    close_ledger_paper: Optional[tuple] = None
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                wrote_trade_row = False
                # First try to update by ID
                if status == 'closed':
                    # IMMUTABILITY RULE: Preserve existing high_price/low_price if trade is already closed
                    # Check if trade is already closed and has existing values
                    cursor.execute(
                        f"""
                        SELECT status, high_price, low_price, strike, side, date, contract, symbol
                        FROM {_tm_trades_table()} WHERE id = %s
                        """,
                        (trade_id,),
                    )
                    existing_row = cursor.fetchone()
                    existing_status = None
                    
                    # Preserve existing values if trade is already closed and provided values are None
                    final_high_price = high_price
                    final_low_price = low_price
                    trade_date = trade_contract = trade_symbol = None
                    if existing_row:
                        (
                            existing_status,
                            existing_high_price,
                            existing_low_price,
                            _strike_c,
                            _side_c,
                            trade_date,
                            trade_contract,
                            trade_symbol,
                        ) = existing_row
                        if existing_status == 'closed':
                            # Trade is already closed - preserve existing values
                            if high_price is None and existing_high_price is not None:
                                final_high_price = existing_high_price
                            if low_price is None and existing_low_price is not None:
                                final_low_price = existing_low_price
                    
                    # Set monitor_confirmed = TRUE if high_price != low_price (meaning ATS was monitoring correctly)
                    monitor_confirmed = False
                    if final_high_price is not None and final_low_price is not None:
                        if final_high_price != final_low_price:
                            monitor_confirmed = True
                            log(f"✅ Trade {trade_id}: monitor_confirmed = TRUE (high_price={final_high_price} != low_price={final_low_price})")
                        else:
                            log(f"⚠️ Trade {trade_id}: monitor_confirmed = FALSE (high_price == low_price = {final_high_price})")
                    
                    cursor.execute(f"""
                        UPDATE {_tm_trades_table()} 
                        SET status = %s, closed_at = %s, sell_price = %s, symbol_close = %s, win_loss = %s, pnl = %s, close_method = %s, fees = %s, roi_pct = %s, ret_pct = %s, ret_pct_base = %s, high_price = %s, low_price = %s, monitor_confirmed = %s,
                            slippage = buy_price - COALESCE(initial_price, buy_price)
                        WHERE id = %s
                    """, (status, closed_at, sell_price, symbol_close, win_loss, calculated_pnl, close_method, fees, roi_value, ret_pct, ret_pct_base, final_high_price, final_low_price, monitor_confirmed, trade_id))
                    if cursor.rowcount > 0:
                        wrote_trade_row = True
                        if trade_symbol and trade_contract and trade_date:
                            _apply_symbol_expiration_for_contract_session(
                                cursor, trade_symbol, trade_date, trade_contract
                            )
                        _finalize_closed_trade_win_loss_confirmed(cursor, trade_id)
                        if existing_status != 'closed' and calculated_pnl is not None:
                            cursor.execute(
                                f"""
                                SELECT paper_trade, COALESCE(test_filter, FALSE), buy_price, position
                                FROM {_tm_trades_table()} WHERE id = %s
                                """,
                                (trade_id,),
                            )
                            pr = cursor.fetchone()
                            if (
                                pr
                                and pr[0] is True
                                and pr[1] is not True
                                and pr[2] is not None
                                and pr[3] is not None
                            ):
                                close_ledger_paper = (
                                    float(pr[2]),
                                    int(pr[3]),
                                    float(calculated_pnl),
                                )
                else:
                    cursor.execute(f"""
                        UPDATE {_tm_trades_table()} 
                        SET status = %s 
                        WHERE id = %s
                    """, (status, trade_id))
                    wrote_trade_row = cursor.rowcount > 0
                
                if wrote_trade_row:
                    log_debug(f"💾 Trade status update written to PostgreSQL tenant trades")
                else:
                    log(f"⚠️ No matching trade found in PostgreSQL for ID {trade_id}")
                
                pg_conn.commit()
                pg_conn.close()
                
                # Broadcast active trades change to frontend
                _fanout_active_trades_change_via_redis_or_http(
                    {
                        "count": 1,
                        "trade_id": trade_id,
                        "status": status,
                        "timestamp": time.time(),
                    }
                )
        else:
            log(f"⚠️ Skipping PostgreSQL update - no connection available")
    except Exception as e:
        log(f"❌ Failed to update PostgreSQL: {e}")
        if pg_conn:
            pg_conn.close()
    
    notify_frontend_trade_change()
    if status in ("open", "closed", "pending", "partial", "closing"):
        _fanout_trade_log_lifecycle(trade_id, status)
    if status == "closed":
        _final_pnl = pnl
        if _final_pnl is None and "calculated_pnl" in locals():
            _final_pnl = calculated_pnl
        _fanout_trade_marks_closed(
            trade_id,
            sell_price=sell_price,
            pnl=_final_pnl,
            ret_pct=ret_pct,
        )
    
    # Notify Active Trade Supervisor when status changes to open (Redis ACK + HTTP fallback)
    if status in ('open', 'partial'):
        notify_ats_trade_open_with_ack(trade_id)
    
    # Notify monitor_manager when trade is closed
    if status == 'closed':
        refresh_monitor_cycle_performance_for_trade(trade_id)
        notify_monitor_manager_trade_closed(trade_id, status)
        # Update win_streak for the monitor
        update_monitor_win_streak(trade_id)
        _symbol_wide_loss_after_close(trade_id)
        # Check and update cycle metrics if all trades in cycle are closed
        check_and_update_cycle_metrics(trade_id)

    if close_ledger_paper is not None:
        bp, pos, pnl_v = close_ledger_paper
        try:
            _paper_ledger_on_close(bp, pos, pnl_v)
        except Exception as e:
            log(f"⚠️ paper ledger after close (update_trade_status_with_ret_pct): {e}")

def update_trade_status(trade_id, status, closed_at=None, sell_price=None, symbol_close=None, win_loss=None, pnl=None, close_method=None, fees=None):
    """Update trade status in PostgreSQL database only."""
    if status == 'closed':
        if closed_at is None:
            utc_now = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
            est_now = utc_now.astimezone(ZoneInfo("America/New_York"))
            closed_at = est_now.isoformat()

        if pnl is not None:
            calculated_pnl = pnl
        else:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor_pg:
                    cursor_pg.execute(f"SELECT buy_price, position FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                    row = cursor_pg.fetchone()
                    buy_price = row[0] if row else None
                    position = row[1] if row else None
                    fees_paid = fees if fees is not None else 0.0
            else:
                buy_price = None
                position = None
                fees_paid = fees if fees is not None else 0.0

            if buy_price is not None and sell_price is not None:
                win_loss = 'W' if sell_price > buy_price else 'L'
            else:
                win_loss = None

            calculated_pnl = None
            if buy_price is not None and sell_price is not None and position is not None:
                buy_value = buy_price * position
                sell_value = sell_price * position
                fees = fees_paid if fees_paid is not None else 0.0
                calculated_pnl = round(sell_value - buy_value - fees, 6)

    # Update PostgreSQL only
    try:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                wrote_trade_row = False
                # First try to update by ID
                if status == 'closed':
                    # Calculate ret_pct and ret_pct_base if we have pnl and bankroll/mtb_base_value
                    ret_pct = None
                    ret_pct_base = None
                    if calculated_pnl is not None:
                        pg_conn_ret = get_postgresql_connection()
                        if pg_conn_ret:
                            with pg_conn_ret.cursor() as cursor_ret:
                                cursor_ret.execute(f"SELECT bankroll, mtb_base_value FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                                row_ret = cursor_ret.fetchone()
                                bankroll = row_ret[0] if row_ret else None
                                mtb_base = row_ret[1] if row_ret and len(row_ret) > 1 else None
                            pg_conn_ret.close()
                            if bankroll is not None and bankroll > 0:
                                ret_pct = round((calculated_pnl / (bankroll / 100.0)) * 100, 5)
                            if mtb_base is not None and mtb_base > 0:
                                ret_pct_base = round((calculated_pnl / (mtb_base / 100.0)) * 100, 5)
                    
                    cursor.execute(
                        f"SELECT date, contract, symbol FROM {_tm_trades_table()} WHERE id = %s",
                        (trade_id,),
                    )
                    meta_row = cursor.fetchone()
                    meta_sym = meta_contract = meta_date = None
                    if meta_row:
                        meta_date, meta_contract, meta_sym = meta_row[0], meta_row[1], meta_row[2]

                    cursor.execute(f"""
                        UPDATE {_tm_trades_table()} 
                        SET status = %s, closed_at = %s, sell_price = %s, symbol_close = %s, win_loss = %s, pnl = %s, close_method = %s, fees = %s, ret_pct = %s, ret_pct_base = %s,
                            slippage = buy_price - COALESCE(initial_price, buy_price)
                        WHERE id = %s
                    """, (status, closed_at, sell_price, symbol_close, win_loss, calculated_pnl, close_method, fees, ret_pct, ret_pct_base, trade_id))
                    if cursor.rowcount > 0:
                        wrote_trade_row = True
                        if meta_sym and meta_contract and meta_date:
                            _apply_symbol_expiration_for_contract_session(
                                cursor, meta_sym, meta_date, meta_contract
                            )
                        _finalize_closed_trade_win_loss_confirmed(cursor, trade_id)
                else:
                    cursor.execute(f"""
                        UPDATE {_tm_trades_table()} 
                        SET status = %s 
                        WHERE id = %s
                    """, (status, trade_id))
                    wrote_trade_row = cursor.rowcount > 0
                
                if wrote_trade_row:
                    log_debug(f"💾 Trade status update written to PostgreSQL tenant trades")
                else:
                    log(f"⚠️ No matching trade found in PostgreSQL for ID {trade_id}")
                
                pg_conn.commit()
                pg_conn.close()
                
                # Broadcast active trades change to frontend
                _fanout_active_trades_change_via_redis_or_http(
                    {
                        "count": 1,
                        "trade_id": trade_id,
                        "status": status,
                        "timestamp": time.time(),
                    }
                )
        else:
            log(f"⚠️ Skipping PostgreSQL update - no connection available")
    except Exception as e:
        log(f"❌ Failed to update PostgreSQL: {e}")
        if pg_conn:
            pg_conn.close()
    
    notify_frontend_trade_change()
    if status in ("open", "closed", "pending", "partial", "closing"):
        _fanout_trade_log_lifecycle(trade_id, status)
    
    # Notify Active Trade Supervisor when status changes to open (Redis ACK + HTTP fallback)
    if status in ('open', 'partial'):
        notify_ats_trade_open_with_ack(trade_id)

    # Notify monitor_manager when a trade is closed
    if status == 'closed':
        refresh_monitor_cycle_performance_for_trade(trade_id)
        notify_monitor_manager_trade_closed(trade_id, status)
        # Update win_streak for the monitor
        update_monitor_win_streak(trade_id)
        _symbol_wide_loss_after_close(trade_id)
        # Check and update cycle metrics if all trades in cycle are closed
        check_and_update_cycle_metrics(trade_id)

def _symbol_wide_loss_after_close(trade_id: int) -> None:
    """Event-driven time LP: real closed L triggers live_loss_1c cooldown."""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return
        try:
            tenant_slot = effective_tenant_context_for_sql_rewrite().user_no
            with pg_conn.cursor() as cursor:
                ran_live = on_trade_closed_live_loss_throttle(
                    cursor,
                    _tm_trades_table(),
                    _tm_monitor_list_table(),
                    tenant_slot,
                    trade_id,
                )
            if ran_live:
                pg_conn.commit()
        finally:
            pg_conn.close()
    except Exception as e:
        log(f"⚠️ simulated_trade_loss_after_close trade {trade_id}: {e}")


def update_monitor_win_streak(trade_id: int) -> None:
    """Update the win_streak for a monitor based on the trade result.
    
    CYCLE LOGIC: Any cycle (settlement hour) with a loss results in win_streak=0.
    Wins only count if the entire cycle has no losses.
    f"""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log(f"⚠️ Cannot connect to database to update win_streak")
            return
        
        # Get the monitor, contract, and win_loss for this trade
        with pg_conn.cursor() as cursor:
            cursor.execute(f"SELECT monitor, win_loss, contract, ticker FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
            trade_row = cursor.fetchone()
        
        if not trade_row or not trade_row[0]:
            pg_conn.close()
            return
        
        monitor = trade_row[0]
        win_loss = trade_row[1]
        contract = trade_row[2]
        ticker = trade_row[3]
        
        # Extract monitor ID from monitor identifier (e.g., "mon_0001_10002" -> "10002")
        if monitor and monitor.startswith('mon_'):
            parts = monitor.split('_')
            if len(parts) >= 3:
                monitor_id = parts[2]  # e.g. mon_0001_10002 -> 10002
            else:
                pg_conn.close()
                return
        else:
            pg_conn.close()
            return

        if not _monitor_key_matches_worker(monitor):
            log_debug(f"win_streak: skip monitor {monitor!r} (wrong tenant for this worker)")
            pg_conn.close()
            return

        # CYCLE-BASED WIN STREAK LOGIC:
        # A cycle is defined by the contract (settlement hour).
        # If ANY trade in a cycle is a loss, the entire cycle doesn't count toward win_streak.
        # We need to check if we've already processed this cycle to avoid double-counting.
        
        # First, check if we've already processed this cycle (using ticker as cycle identifier)
        # Extract the settlement hour from ticker (e.g., KXBTCD-25OCT1314 means Oct 13, 14:00)
        cycle_id = None
        if ticker and '-' in ticker:
            # Extract the date-hour portion (everything before the last hyphen)
            parts = ticker.rsplit('-', 1)
            if len(parts) >= 1:
                cycle_id = parts[0]  # e.g., "KXBTCD-25OCT1314"
        
        if not cycle_id:
            # Fallback to contract if ticker parsing fails
            cycle_id = contract
        
        # Check if we've already processed this cycle for this monitor
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT last_processed_cycle FROM {_tm_monitor_list_table()}
                WHERE id = %s
            """, (monitor_id,))
            result = cursor.fetchone()
            last_processed_cycle = result[0] if result and result[0] else None
        
        if last_processed_cycle == cycle_id:
            # Already processed this cycle, skip to avoid double-counting
            log(f"⏭️  Skipping win_streak update for {monitor} - cycle {cycle_id} already processed")
            pg_conn.close()
            return
        
        # Check if there are ANY pending trades in this cycle (expired but not yet settled)
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT COUNT(*) 
                FROM {_tm_trades_table()} 
                WHERE monitor = %s 
                AND ticker LIKE %s
                AND status = 'expired'
            """, (monitor, f"{cycle_id}%"))
            pending_count = cursor.fetchone()[0]
        
        if pending_count > 0:
            # There are still unsettled trades in this cycle - skip for now
            # They will trigger this function again when they settle
            log(f"⏭️  Waiting for {pending_count} pending trades in cycle {cycle_id} for {monitor} to settle")
            pg_conn.close()
            return
        
        # Get all trades from this cycle for this monitor
        with pg_conn.cursor() as cursor:
            # Use ticker pattern to find all trades from the same cycle
            # Note: We use ONLY ticker (not contract) because contract is too generic
            # (e.g., "BTC 4pm" matches multiple days, but "KXBTCD-25OCT1316" is unique to one hour)
            cursor.execute(f"""
                SELECT id, win_loss, contract, ticker 
                FROM {_tm_trades_table()} 
                WHERE monitor = %s 
                AND status = 'closed'
                AND ticker LIKE %s
                ORDER BY id ASC
            """, (monitor, f"{cycle_id}%"))
            cycle_trades = cursor.fetchall()
        
        if not cycle_trades:
            pg_conn.close()
            return
        
        # Check if ANY trade in this cycle is a loss
        has_loss = any(trade[1] == 'L' for trade in cycle_trades)
        win_count = sum(1 for trade in cycle_trades if trade[1] == 'W')
        
        # Get the strategy, win_streak_threshold and loss_prevention_toggle from the database for this monitor
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT strategy, win_streak_threshold, loss_prevention_toggle FROM {_tm_monitor_list_table()}
                WHERE id = %s
            """, (monitor_id,))
            config_row = cursor.fetchone()
            strategy = config_row[0] if config_row and config_row[0] else "Hourly HTC"
            win_streak_threshold = config_row[1] if config_row and config_row[1] is not None else 22
            loss_prevention_toggle = config_row[2] if config_row and config_row[2] is not None else True
        
        # Determine if this is Momentum Contain or Momentum Breakout
        is_momentum_contain = strategy and "Momentum Contain" in strategy
        is_momentum_breakout = strategy and "Momentum Breakout" in strategy
        is_cycle_based_streak = is_momentum_contain or is_momentum_breakout
        
        # For Momentum Contain/Breakout: count by cycle wins (1 per cycle), not individual trade wins
        # For other strategies: count by individual trade wins
        streak_increment = 1 if is_cycle_based_streak else win_count
        
        # Update win_streak based on cycle result (loss_prevention via recompute_monitor_loss_prevention)
        with pg_conn.cursor() as cursor:
            if has_loss:
                cursor.execute(f"""
                    UPDATE {_tm_monitor_list_table()}
                    SET win_streak = 0,
                        last_processed_cycle = %s
                    WHERE id = %s
                """, (cycle_id, monitor_id))
                log(f"🔄 Cycle {cycle_id} for {monitor} had a loss - win_streak reset to 0 (trades: {len(cycle_trades)})")
            else:
                if loss_prevention_toggle:
                    cursor.execute(f"""
                        UPDATE {_tm_monitor_list_table()}
                        SET win_streak = win_streak + %s,
                            last_processed_cycle = %s
                        WHERE id = %s
                    """, (streak_increment, cycle_id, monitor_id))
                else:
                    cursor.execute(f"""
                        UPDATE {_tm_monitor_list_table()}
                        SET win_streak = win_streak + %s,
                            last_processed_cycle = %s
                        WHERE id = %s
                    """, (streak_increment, cycle_id, monitor_id))
                if is_cycle_based_streak:
                    log(f"📈 Cycle {cycle_id} for {monitor} all wins - win_streak +1 (cycle win, {win_count} trades in cycle, threshold: {win_streak_threshold})")
                else:
                    log(f"📈 Cycle {cycle_id} for {monitor} all wins - win_streak +{win_count} (trades: {len(cycle_trades)}, threshold: {win_streak_threshold})")

            recompute_monitor_loss_prevention(
                cursor,
                _tm_monitor_list_table(),
                str(monitor_id),
                cycle_had_loss=has_loss,
            )
            pg_conn.commit()
        
        pg_conn.close()
        
    except Exception as e:
        log(f"⚠️ Error updating win_streak for trade {trade_id}: {e}")
        try:
            pg_conn.close()
        except:
            pass

def check_and_update_cycle_metrics(trade_id: int) -> None:
    """
    Check if all trades for a cycle are closed, and if so, update cycle-level metrics.
    
    A cycle is defined by monitor + contract + date.
    Only updates when ALL trades in the cycle have status = 'closed'.
    Updates cycle_pnl, cycle_ret_pct, and cycle_win_loss for all trades in the cycle.
    """
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log(f"⚠️ Cannot connect to database to check cycle metrics for trade {trade_id}")
            return
        
        # Step 1: Get cycle info for this trade (monitor, contract, date)
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT monitor, contract, date 
                FROM {_tm_trades_table()} 
                WHERE id = %s
            """, (trade_id,))
            trade_row = cursor.fetchone()
        
        if not trade_row:
            pg_conn.close()
            return
        
        monitor, contract, trade_date = trade_row
        
        # Skip if any required fields are NULL
        if not monitor or not contract or not trade_date:
            log(f"⏭️  Skipping cycle metrics for trade {trade_id} - missing monitor, contract, or date")
            pg_conn.close()
            return
        
        # Step 2: Check if all trades in cycle are closed
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total_trades,
                    COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed_trades
                FROM {_tm_trades_table()}
                WHERE monitor = %s 
                  AND contract = %s 
                  AND date = %s
                  AND monitor IS NOT NULL
                  AND contract IS NOT NULL
                  AND date IS NOT NULL
            """, (monitor, contract, trade_date))
            cycle_check = cursor.fetchone()
        
        if not cycle_check:
            pg_conn.close()
            return
        
        total_trades, closed_trades = cycle_check
        
        # If not all trades are closed, skip (wait for more trades to close)
        if total_trades != closed_trades:
            log(f"⏭️  Cycle metrics: {closed_trades}/{total_trades} trades closed for cycle {monitor}/{contract}/{trade_date} - waiting for completion")
            pg_conn.close()
            return
        
        # Step 3: All trades are closed - calculate and update cycle metrics
        with pg_conn.cursor() as cursor:
            # Calculate cycle totals
            cursor.execute(f"""
                SELECT 
                    SUM(pnl) as total_pnl,
                    SUM(ret_pct) as total_ret_pct
                FROM {_tm_trades_table()}
                WHERE monitor = %s 
                  AND contract = %s 
                  AND date = %s
                  AND status = 'closed'
            """, (monitor, contract, trade_date))
            cycle_stats = cursor.fetchone()
        
        if not cycle_stats:
            pg_conn.close()
            return
        
        total_pnl, total_ret_pct = cycle_stats
        
        # Skip if we don't have valid pnl/ret_pct data
        if total_pnl is None or total_ret_pct is None:
            log(f"⏭️  Cycle metrics: No valid pnl/ret_pct data for cycle {monitor}/{contract}/{trade_date}")
            pg_conn.close()
            return
        
        # Calculate cycle_win_loss
        cycle_win_loss = 'W' if total_pnl > 0 else 'L'
        
        # Step 4: Update all trades in the cycle with cycle metrics
        with pg_conn.cursor() as cursor:
            cursor.execute(f"""
                UPDATE {_tm_trades_table()}
                SET 
                    cycle_pnl = %s,
                    cycle_ret_pct = %s,
                    cycle_win_loss = %s
                WHERE monitor = %s 
                  AND contract = %s 
                  AND date = %s
                  AND status = 'closed'
            """, (total_pnl, total_ret_pct, cycle_win_loss, monitor, contract, trade_date))
            
            updated_count = cursor.rowcount
            pg_conn.commit()
        
        log(f"✅ Cycle metrics updated for cycle {monitor}/{contract}/{trade_date}: {updated_count} trades, cycle_pnl=${total_pnl:.2f}, cycle_ret_pct={total_ret_pct:.5f}, cycle_win_loss={cycle_win_loss}")
        
        pg_conn.close()
        
    except Exception as e:
        log(f"⚠️ Error updating cycle metrics for trade {trade_id}: {e}")
        try:
            pg_conn.close()
        except:
            pass

# ---------- API ENDPOINTS ----------------------------------------------------

from fastapi import APIRouter, FastAPI, Request
router = APIRouter()

@router.get("/api/ports")
async def get_ports():
    """Get all port assignments from centralized system"""
    return get_port_info()

@router.get("/trades")
def get_trades(status: str = None, recent_hours: int = None):
    """Get trades with optional filtering by status"""
    pg_conn = get_postgresql_connection()
    if not pg_conn:
        return []
    
    try:
        with pg_conn.cursor() as cursor:
            from backend.core.tenant_context import get_worker_tenant_context

            slot = get_worker_tenant_context().user_no
            union_sql, _ = union_trades_with_archives_select(cursor, slot)
            if status == "open":
                cursor.execute(
                    f"""
                    SELECT id, date, time, strike, side, buy_price, position, status, contract
                    FROM ({union_sql}) AS all_trades
                    WHERE status = 'open'
                    """
                )
                rows = cursor.fetchall()
                result = [dict(zip(["id","date","time","strike","side","buy_price","position","status","contract"], row)) for row in rows]
            elif status == "closed" and recent_hours:
                cutoff = datetime.utcnow() - timedelta(hours=recent_hours)
                cutoff_iso = cutoff.isoformat()
                cursor.execute(
                    f"""
                    SELECT id, date, time, strike, side, buy_price, position, status, closed_at, contract, sell_price, pnl, win_loss
                    FROM ({union_sql}) AS all_trades
                    WHERE status = 'closed' AND closed_at >= %s
                    ORDER BY closed_at DESC
                    """,
                    (cutoff_iso,),
                )
                rows = cursor.fetchall()
                result = [dict(zip(["id","date","time","strike","side","buy_price","position","status","closed_at","contract","sell_price","pnl","win_loss"], row)) for row in rows]
            elif status == "closed":
                cursor.execute(
                    f"""
                    SELECT * FROM ({union_sql}) AS all_trades
                    WHERE status = 'closed' ORDER BY id DESC
                    """
                )
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                result = [dict(zip(columns, row)) for row in rows]
            else:
                cursor.execute(
                    f"""
                    SELECT * FROM ({union_sql}) AS all_trades
                    ORDER BY id DESC
                    """
                )
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                result = [dict(zip(columns, row)) for row in rows]
        
        return result
    except Exception as e:
        log(f"❌ Error reading trades from PostgreSQL: {e}")
        return []
    finally:
        pg_conn.close()


@router.get("/trades/{trade_id}")
def get_trade_by_id(trade_id: int):
    """Single trade row from master log or archive (after monitor archival)."""
    pg_conn = get_postgresql_connection()
    if not pg_conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        # NOTE: `union_trades_with_archives_select()` calls
        # `fetch_trades_0001_column_names()`, which expects tuple rows from
        # `cursor.fetchall()`. A `RealDictCursor` returns dict rows, which
        # breaks column-name extraction and causes HTTP 500.
        with pg_conn.cursor() as cursor:
            from backend.core.tenant_context import get_worker_tenant_context

            slot = get_worker_tenant_context().user_no
            union_sql, _ = union_trades_with_archives_select(cursor, slot)
            cursor.execute(
                f"SELECT * FROM ({union_sql}) AS all_trades WHERE id = %s LIMIT 1",
                (trade_id,),
            )
            row = cursor.fetchone()
            columns = [desc[0] for desc in cursor.description]
        if not row:
            raise HTTPException(status_code=404, detail="Trade not found")
        return dict(zip(columns, row))
    except HTTPException:
        raise
    except Exception as e:
        log(f"❌ Error reading trade {trade_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        pg_conn.close()

@router.post("/trades", status_code=status.HTTP_201_CREATED)
async def add_trade(request: Request):
    """Create a new trade - handles both open and close intents"""
    data = await request.json()
    intent = data.get("intent", "open").lower()
    
    if intent == "close":
        log(f"CLOSE TICKET RECEIVED")
        trade_id = data.get("id")  # Get trade_id directly from request
        ticker = data.get("ticker")  # Still need ticker for executor payload
        
        if trade_id:
            log(f"CLOSING SPECIFIC TRADE ID: {trade_id}")
            
            # Verify this trade exists and is open, and get close-relevant fields
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute(
                        f"SELECT ticker, status, paper_trade, side, position, symbol FROM {_tm_trades_table()} WHERE id = %s",
                        (trade_id,),
                    )
                    row = cursor.fetchone()
            else:
                row = None
            
            if row and row[1] == "open":
                verified_ticker = row[0]
                paper_trade = row[2] if len(row) > 2 else False
                trade_side = _normalize_trade_side(row[3]) if len(row) > 3 else None
                trade_position = float(row[4]) if len(row) > 4 and row[4] is not None else 0.0
                trade_symbol = row[5] if len(row) > 5 else None
                if isinstance(paper_trade, str):
                    paper_trade = paper_trade.lower() in ('true', '1', 'yes')
                elif paper_trade is None:
                    paper_trade = False
                
                log(f"VERIFIED OPEN TRADE: ID={trade_id}, TICKER={verified_ticker}, PAPER_TRADE={paper_trade}")

                tif_close = normalize_time_in_force_loose(
                    data.get("time_in_force", "immediate_or_cancel")
                ) or "immediate_or_cancel"
                requested_close_count = None
                count_fp_in = data.get("count_fp")
                if count_fp_in is not None and str(count_fp_in).strip() != "":
                    try:
                        requested_close_count = round(float(count_fp_in), 2)
                    except (TypeError, ValueError):
                        requested_close_count = None
                if requested_close_count is None:
                    for key in ("count", "position"):
                        value = data.get(key)
                        if value is None:
                            continue
                        try:
                            requested_close_count = round(float(value), 2)
                            break
                        except (TypeError, ValueError):
                            continue
                if requested_close_count is None:
                    requested_close_count = _trade_position_for_db(trade_position)
                if requested_close_count <= 0:
                    requested_close_count = _trade_position_for_db(trade_position)

                close_projection = {
                    "ok": None,
                    "reason": None,
                    "projected_sell_price": None,
                    "projected_close_fee": None,
                    "available_contracts": None,
                }
                if paper_trade:
                    close_projection = _project_orderbook_close(
                        verified_ticker,
                        trade_side,
                        requested_close_count,
                    )
                    log_event(
                        data.get("ticket_id"),
                        "MANAGER CLOSE PROJECTION "
                        f"ticker={verified_ticker} side={trade_side} qty={requested_close_count} "
                        f"ok={close_projection.get('ok')} reason={close_projection.get('reason')} "
                        f"proj_sell={close_projection.get('projected_sell_price')} "
                        f"proj_close_fee={close_projection.get('projected_close_fee')} "
                        f"available={close_projection.get('available_contracts')}",
                        trade_id=trade_id,
                    )

                    if tif_close == "fill_or_kill" and close_projection.get("ok") is False:
                        if close_projection.get("reason") == "insufficient_resting_volume":
                            return _mark_close_trade_failed(
                                trade_id,
                                data.get("ticket_id"),
                                "insufficient_resting_volume (precheck)",
                            )
                
                if paper_trade:
                    # PAPER TRADE: Skip executor, mark as closing, then immediately finalize
                    log(f"📝 PAPER TRADE CLOSE: Skipping executor, processing immediately")
                    
                    # Prefer projected close sell price so paper closes reflect live depth.
                    sell_price = close_projection.get("projected_sell_price")
                    if sell_price is None:
                        sell_price = data.get("buy_price")
                    close_method = data.get("close_method", "manual")
                    ticket_id = data.get("ticket_id")
                    
                    symbol = trade_symbol
                    if not symbol:
                        try:
                            pg_conn_symbol = get_postgresql_connection()
                            if pg_conn_symbol:
                                with pg_conn_symbol.cursor() as cursor:
                                    cursor.execute(
                                        f"SELECT symbol FROM {_tm_trades_table()} WHERE id = %s",
                                        (trade_id,),
                                    )
                                    result = cursor.fetchone()
                                    if result and result[0]:
                                        symbol = result[0]
                                pg_conn_symbol.close()
                        except Exception as e:
                            log(f"⚠️ Failed to get symbol for paper trade close: {e}")

                    symbol_close = _symbol_close_from_close_request(
                        symbol, data.get("symbol_close"),
                    )
                    if symbol_close is None and symbol:
                        now_est_close = datetime.now(ZoneInfo("America/New_York"))
                        symbol_close = _fetch_one_minute_avg_at_or_before(
                            symbol,
                            now_est_close,
                            max_gap_seconds=120,
                        )
                        if symbol_close is not None:
                            log(f"📝 PAPER TRADE: Retrieved one_minute_avg for close: {symbol_close}")
                        else:
                            log(f"📝 PAPER TRADE: No fresh one_minute_avg for {symbol}; symbol_close left unset")
                    
                    # Mark as closing first
                    try:
                        pg_conn_closing = get_postgresql_connection()
                        if pg_conn_closing:
                            with pg_conn_closing.cursor() as cursor:
                                cursor.execute(f"UPDATE {_tm_trades_table()} SET status = 'closing', symbol_close = %s, close_method = %s WHERE id = %s", (symbol_close, close_method, trade_id))
                                pg_conn_closing.commit()
                            pg_conn_closing.close()
                    except Exception as pg_err:
                        log(f"❌ Failed to update paper trade to closing: {pg_err}")
                    
                    # Notify active trade supervisor that it's closing
                    notify_active_trade_supervisor_direct(trade_id, ticket_id, "closing")
                    
                    # Immediately finalize the trade
                    try:
                        now_est = datetime.now(ZoneInfo("America/New_York"))
                        closed_at = now_est.strftime("%H:%M:%S")
                        
                        # Get trade data for calculations (include existing open fee)
                        pg_conn_trade = get_postgresql_connection()
                        if pg_conn_trade:
                            with pg_conn_trade.cursor() as cursor:
                                cursor.execute(f"SELECT buy_price, position, bankroll, mtb_base_value, fees FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                                trade_data = cursor.fetchone()
                            pg_conn_trade.close()
                        else:
                            trade_data = None
                        
                        if trade_data and sell_price is not None:
                            buy_price, position, bankroll, mtb_base, existing_fees = trade_data
                            existing_fees = float(existing_fees) if existing_fees is not None else 0.0
                            buy_pf = float(buy_price) if buy_price is not None else 0.0
                            sell_pf = float(sell_price) if sell_price is not None else 0.0
                            pos_f = float(position) if position is not None else 0.0
                            bankroll_f = float(bankroll) if bankroll is not None else 0.0
                            mtb_base_f = float(mtb_base) if mtb_base is not None else 0.0
                            # Close leg fee comes from orderbook projection when available.
                            projected_close_fee = close_projection.get("projected_close_fee")
                            if projected_close_fee is not None:
                                close_fee = float(projected_close_fee)
                            else:
                                price_to_close = 1.0 - sell_pf
                                close_fee = (
                                    estimate_kalshi_taker_fee(pos_f, price_to_close)
                                    if 0 < price_to_close < 1
                                    else 0.0
                                )
                            total_fees = existing_fees + close_fee
                            buy_value = buy_pf * pos_f
                            sell_value = sell_pf * pos_f
                            pnl = round(sell_value - buy_value - total_fees, 6)
                            win_loss = "W" if pnl > 0 else "L" if pnl < 0 else "D"
                            
                            # Calculate ret_pct, ret_pct_base, and roi_pct
                            ret_pct = None
                            ret_pct_base = None
                            roi_pct = None
                            if bankroll_f > 0:
                                ret_pct = round((pnl / (bankroll_f / 100.0)) * 100, 5)
                            if mtb_base_f > 0:
                                ret_pct_base = round((pnl / (mtb_base_f / 100.0)) * 100, 5)
                            if buy_pf > 0 and pos_f:
                                buy_value_roi = buy_pf * pos_f
                                if buy_value_roi > 0:
                                    roi_pct = round((pnl / buy_value_roi) * 100.0, 5)
                            
                            # Get high_price and low_price from active_trades
                            high_price, low_price = get_high_low_prices_from_active_trades(trade_id)
                            
                            # Update trade to closed with all calculated values (total_fees = open + close)
                            update_trade_status_with_ret_pct(
                                trade_id,
                                "closed",
                                closed_at,
                                sell_pf,
                                symbol_close,
                                win_loss,
                                pnl,
                                close_method,
                                total_fees,
                                roi_pct,
                                ret_pct,
                                ret_pct_base,
                                high_price,
                                low_price,
                            )
                            
                            # Set order_id_close to NULL for paper trades
                            pg_conn_update = get_postgresql_connection()
                            if pg_conn_update:
                                with pg_conn_update.cursor() as cursor:
                                    cursor.execute(f"UPDATE {_tm_trades_table()} SET order_id_close = NULL WHERE id = %s", (trade_id,))
                                    pg_conn_update.commit()
                                pg_conn_update.close()
                            
                            log(f"📝 PAPER TRADE CLOSED: Trade {trade_id}, PnL=${pnl}, W/L={win_loss}, Fees=${total_fees}")
                            log_event(ticket_id, f"MANAGER: PAPER TRADE CLOSED - PnL: ${pnl}, W/L: {win_loss}, Fees: ${total_fees}")
                            
                            # Notify active trade supervisor that it's closed
                            notify_active_trade_supervisor_direct(trade_id, ticket_id, "closed")
                            
                            # Notify strike table for display update
                            notify_strike_table_trade_change(trade_id, "closed")
                        else:
                            log(f"❌ Failed to finalize paper trade {trade_id}: missing trade data or sell_price")
                            log_event(ticket_id, f"MANAGER: PAPER TRADE CLOSE FAILED - missing data")
                    except Exception as e:
                        log(f"❌ Error finalizing paper trade {trade_id}: {e}")
                        log_event(ticket_id, f"MANAGER: PAPER TRADE CLOSE ERROR: {e}")
                else:
                    # LIVE TRADE: Send to executor as normal
                    # IMMEDIATELY send to executor with trade_id
                    try:
                        log(f"SENDING CLOSE TO EXECUTOR")
                        close_payload = {
                            "id": trade_id,  # Include trade_id for close orders
                            "ticker": verified_ticker,  # Use verified ticker from database
                            # Always use canonical position leg from DB; trade_executor flips on intent=close.
                            "side": trade_side,
                            "count_fp": _format_count_fp(data, for_close=True),
                            "action": "close",
                            "order_type": "market",
                            "time_in_force": "immediate_or_cancel",
                            "buy_price": data.get("buy_price"),
                            "symbol_close": _symbol_close_from_close_request(
                                trade_symbol, data.get("symbol_close"),
                            ),
                            "intent": "close",
                            "ticket_id": data.get("ticket_id")  # Include ticket_id for close orders
                        }
                        send_trigger_to_executor(close_payload)
                    except Exception as e:
                        log(f"CLOSE EXECUTOR ERROR: {e}")
                
                    # Update database status
                    symbol_close = _symbol_close_from_close_request(
                        trade_symbol, data.get("symbol_close"),
                    )
                    sell_price = data.get("buy_price")
                    close_method = data.get("close_method", "manual")
                    
                    # Update PostgreSQL
                    try:
                        pg_conn_update = get_postgresql_connection()
                        if pg_conn_update:
                            with pg_conn_update.cursor() as cursor:
                                cursor.execute(f"UPDATE {_tm_trades_table()} SET status = 'closing', symbol_close = %s, close_method = %s WHERE id = %s", (symbol_close, close_method, trade_id))
                                pg_conn_update.commit()
                                log_debug(f"💾 Manual close trade also marked as 'closing' in PostgreSQL tenant trades")
                            pg_conn_update.close()
                        else:
                            log(f"⚠️ Skipping PostgreSQL manual close update - no connection available")
                    except Exception as pg_err:
                        log(f"❌ Failed to update manual close trade in PostgreSQL: {pg_err}")
                    
                    # Notify active trade supervisor
                    notify_active_trade_supervisor_direct(trade_id, data.get('ticket_id'), "closing")
                    
                    log(f"CLOSE TICKET SENT FOR TRADE {trade_id} - WAITING FOR CONFIRMATION")
            else:
                if row:
                    log(
                        f"TRADE {trade_id} EXISTS BUT STATUS IS: {row[1]} (expected: open)"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Trade {trade_id} is not open (status: {row[1]})",
                    )
                else:
                    log(f"TRADE {trade_id} NOT FOUND")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Trade {trade_id} not found",
                    )
        else:
            log(f"NO TRADE_ID PROVIDED IN CLOSE REQUEST")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="trade_id (id) is required for close requests",
            )

        return {"message": "Close ticket received and processed"}
    
    # OPEN TRADE
    log("OPEN TICKET RECEIVED")

    simulated = data.get("simulated_trade", False)
    if isinstance(simulated, str):
        simulated = simulated.lower() in ("true", "1", "yes")
    if simulated:
        required = {"date", "time", "strike", "side", "symbol"}
        if not required.issubset(data.keys()):
            raise HTTPException(status_code=400, detail="Missing required fields for simulated trade")
        sym0 = str(data.get("symbol") or "").strip()
        if sym0:
            data["contract"] = _coalesce_trade_contract(sym0, data.get("contract"), data.get("ticker"))
        trade_id = insert_simulated_trade(data)
        if trade_id is None:
            raise HTTPException(status_code=500, detail="Failed to insert simulated trade")
        # Paper trade rule: confirm as open immediately (no executor)
        try:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute(f"""
                        UPDATE {_tm_trades_simulated_table()}
                        SET status = 'open', fees = NULL, order_id_open = NULL
                        WHERE id = %s
                    """, (trade_id,))
                    pg_conn.commit()
                pg_conn.close()
        except Exception as e:
            log(f"⚠️ Failed to confirm simulated trade {trade_id} as open: {e}")
        return {"id": trade_id}

    # Global maintenance guard: never open new trades while the system is in maintenance mode.
    try:
        if not _is_trading_enabled():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="trading_disabled")
    except HTTPException:
        raise
    except Exception as e:
        log(f"⚠️ Error checking system trading mode: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="trading_disabled")

    # Hard fail-closed data gate for live opens: require healthy + non-flatlined spot pipeline.
    # Paper/simulated paths are allowed to continue for diagnostics/backtesting.
    try:
        _paper_raw = data.get("paper_trade", False)
        if isinstance(_paper_raw, str):
            _paper_for_gate = _paper_raw.strip().lower() in ("true", "1", "yes", "on")
        else:
            _paper_for_gate = bool(_paper_raw)
        if not simulated and not _paper_for_gate:
            symbol_for_gate = str(data.get("symbol") or "").strip().upper()
            market_for_gate = str(data.get("market") or "hourly").strip().lower() or "hourly"
            if symbol_for_gate:
                pg_gate = get_postgresql_connection()
                if not pg_gate:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="pipeline_gate_db_unavailable",
                    )
                try:
                    ok_gate, reason_gate = evaluate_pipeline_gate_conn(
                        pg_gate,
                        exchange="kalshi",
                        market=market_for_gate,
                        symbol=symbol_for_gate,
                    )
                finally:
                    try:
                        pg_gate.close()
                    except Exception:
                        pass
                if not ok_gate:
                    log(
                        f"🚫 OPEN BLOCKED by pipeline gate symbol={symbol_for_gate} "
                        f"market={market_for_gate} reason={reason_gate}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=f"pipeline_gate_blocked:{reason_gate}",
                    )
    except HTTPException:
        raise
    except Exception as e:
        log(f"⚠️ pipeline gate check error in add_trade open path: {e}")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="pipeline_gate_check_failed")

    required_fields = {"date", "time", "strike", "side", "buy_price", "position"}
    if not required_fields.issubset(data.keys()):
        raise HTTPException(status_code=400, detail="Missing required trade fields")

    sym0 = str(data.get("symbol") or "").strip()
    if sym0:
        data["contract"] = _coalesce_trade_contract(sym0, data.get("contract"), data.get("ticker"))

    now_est = datetime.now(ZoneInfo("America/New_York"))
    data["time"] = now_est.strftime("%H:%M:%S")

    # Check if this is a paper trade
    paper_trade = data.get('paper_trade', False)
    if isinstance(paper_trade, str):
        paper_trade = paper_trade.lower() in ('true', '1', 'yes')
    elif paper_trade is None:
        paper_trade = False

    proj_side = _normalize_trade_side(data.get("side"))
    proj_position = None
    try:
        proj_position = int(float(data.get("position")))
    except (TypeError, ValueError):
        proj_position = None
    ticker_for_projection = str(data.get("ticker") or "").strip()
    projection = None
    if ticker_for_projection and proj_side and proj_position and proj_position > 0:
        projection = _project_orderbook_entry(ticker_for_projection, proj_side, proj_position)
        if projection.get("initial_proj_price") is not None:
            data["initial_proj_price"] = projection.get("initial_proj_price")
        if projection.get("initial_proj_fees") is not None:
            data["initial_proj_fees"] = projection.get("initial_proj_fees")
        log_event(
            data.get("ticket_id", "UNKNOWN"),
            "MANAGER: ORDERBOOK PROJECTION "
            f"ticker={ticker_for_projection} side={proj_side} position={proj_position} "
            f"initial_proj_price={projection.get('initial_proj_price')} "
            f"initial_proj_fees={projection.get('initial_proj_fees')} "
            f"available_contracts={projection.get('available_contracts')} "
            f"reason={projection.get('reason')}",
        )

    monitor_key_open = data.get("monitor")
    if monitor_key_open:
        pg_mon = None
        try:
            pg_mon = get_postgresql_connection()
            if pg_mon:
                with pg_mon.cursor() as _c_mon:
                    mst = _fetch_monitor_state(_c_mon, monitor_key_open)
                if mst and _normalize_boolean_flag(mst.get("test_filter")):
                    paper_trade = True
                    data["paper_trade"] = True
        except Exception as e:
            log_debug(f"add_trade test_filter monitor check: {e}")
        finally:
            if pg_mon:
                try:
                    pg_mon.close()
                except Exception:
                    pass

    if monitor_key_open:
        _enrich_open_trade_execution_from_monitor(data)

    tif_for_precheck = str(data.get("time_in_force") or "").strip().lower()
    if (
        paper_trade
        and tif_for_precheck == "fill_or_kill"
        and projection is not None
        and projection.get("ok") is False
        and projection.get("reason") == "insufficient_resting_volume"
    ):
        data["status"] = "pending"
        trade_id, inserted_new = insert_trade(data)
        if trade_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to insert trade to database",
            )
        if not inserted_new:
            log_event(
                data.get("ticket_id", "UNKNOWN"),
                "MANAGER: PRECHECK CANCEL — idempotent ticket reuse, skip volume rejection delete",
            )
            return {"id": trade_id}
        log_event(
            data.get("ticket_id", "UNKNOWN"),
            "MANAGER: PRECHECK CANCEL — insufficient_resting_volume "
            f"requested_position={proj_position} available_contracts={projection.get('available_contracts')}",
        )
        return _delete_pending_trade_for_rejection(
            trade_id,
            data.get("ticket_id"),
            "INSUFFICIENT VOLUME",
        )

    if paper_trade:
        # PAPER TRADE: Skip executor, create pending trade, then immediately mark as open.
        # Return HTTP response as soon as DB work is done so the client (e.g. auto_entry_supervisor)
        # does not timeout when main_app or active_trade_supervisor are slow; notifications run in background.
        log(f"📝 PAPER TRADE: Skipping executor, processing immediately")

        projected_buy_price = None
        projected_open_fee = None
        try:
            if projection is not None and projection.get("initial_proj_price") is not None:
                projected_buy_price = float(projection.get("initial_proj_price"))
            if projection is not None and projection.get("initial_proj_fees") is not None:
                projected_open_fee = float(projection.get("initial_proj_fees"))
        except (TypeError, ValueError):
            projected_buy_price = None
            projected_open_fee = None

        try:
            from backend.paper_collateral import paper_open_passes_collateral_cap

            _bp_g = float(projected_buy_price if projected_buy_price is not None else data["buy_price"])
            _pos_g = int(data["position"])
            _fee_g = (
                float(projected_open_fee)
                if projected_open_fee is not None
                else estimate_kalshi_taker_fee(_pos_g, _bp_g)
            )
            _ok_cap, _cap_reason = paper_open_passes_collateral_cap(
                ticker=data.get("ticker"),
                side=data.get("side"),
                buy_price=_bp_g,
                position=_pos_g,
                open_fee_dollars=_fee_g,
            )
            if not _ok_cap:
                log(f"PAPER TRADE SKIPPED (buying power / collateral): {_cap_reason}")
                log_event(
                    data.get("ticket_id", "UNKNOWN"),
                    f"MANAGER: PAPER — SKIPPED insufficient buying power: {_cap_reason}",
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "insufficient_paper_buying_power",
                        "message": _cap_reason,
                    },
                )
        except HTTPException:
            raise
        except Exception as e:
            log(f"paper collateral precheck failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="paper_collateral_precheck_failed",
            ) from e

        # Paper IOC: reuse partial row (same monitor/session/strike); live path already does this for non-paper.
        tif_early_paper = str(data.get("time_in_force") or "").strip().lower()
        if tif_early_paper == "immediate_or_cancel":
            pg_pe = get_postgresql_connection()
            ptop = None
            if pg_pe:
                try:
                    with pg_pe.cursor() as cpe:
                        ptop = _find_paper_partial_topup(
                            cpe,
                            data.get("monitor"),
                            data.get("ticker"),
                            data.get("side"),
                            data,
                        )
                finally:
                    try:
                        pg_pe.close()
                    except Exception:
                        pass
            if ptop:
                tid_p, pos_p, ic_p, _tkt_p = ptop
                try:
                    res_p = int(ic_p) - int(pos_p or 0)
                except (TypeError, ValueError):
                    res_p = 0
                if res_p > 0:
                    log(
                        f"PAPER IOC TOP-UP reuse trade_id={tid_p} residual={res_p} "
                        f"monitor={data.get('monitor')!r}"
                    )
                    log_event(
                        data.get("ticket_id", "UNKNOWN"),
                        f"MANAGER: PAPER IOC TOP-UP reuse trade_id={tid_p} residual={res_p}",
                    )
                    tk_top = ticker_for_projection or str(data.get("ticker") or "").strip()
                    return _apply_paper_ioc_partial_topup(
                        int(tid_p),
                        int(pos_p or 0),
                        int(ic_p),
                        data,
                        proj_side,
                        tk_top,
                    )

        dup_paper_id = _find_paper_blocking_duplicate_trade_id(data)
        if dup_paper_id is not None:
            log(
                f"PAPER OPEN DEDUP: existing pending/open trade id={dup_paper_id} "
                f"monitor={data.get('monitor')!r} date={data.get('date')!r} — skipping insert"
            )
            log_event(
                data.get("ticket_id", "UNKNOWN"),
                f"MANAGER: PAPER OPEN DEDUP reuse trade_id={dup_paper_id}",
            )
            return {"id": dup_paper_id}

        # Insert trade with 'pending' status first
        data['status'] = 'pending'
        trade_id, inserted_new = insert_trade(data)

        if trade_id is None:
            log(f"❌ Failed to insert paper trade to database")
            log_event(data.get("ticket_id", "UNKNOWN"), "MANAGER: PAPER TRADE — DATABASE INSERT FAILED")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to insert paper trade to database",
            )
        if not inserted_new:
            log_event(
                data.get("ticket_id", "UNKNOWN"),
                f"MANAGER: PAPER insert_trade dedupe reuse trade_id={trade_id}",
            )
            return {"id": trade_id}

        tif_paper = str(data.get("time_in_force") or "").strip().lower()
        if tif_paper == "immediate_or_cancel":
            tk_ioc = ticker_for_projection or str(data.get("ticker") or "").strip()
            if not tk_ioc or not proj_side or not proj_position or proj_position <= 0:
                return _delete_pending_trade_for_rejection(
                    trade_id,
                    data.get("ticket_id"),
                    "IOC_PAPER_BAD_INPUT",
                )
            try:
                lim_ioc = float(
                    limit_price_for_executor_payload(
                        order_type_policy=str(data.get("order_type") or "market"),
                        ticket_buy_price=data.get("buy_price"),
                    )
                )
            except (TypeError, ValueError):
                return _delete_pending_trade_for_rejection(
                    trade_id,
                    data.get("ticket_id"),
                    "IOC_PAPER_BAD_LIMIT",
                )
            ioc_proj = _project_paper_ioc_at_limit(tk_ioc, proj_side, int(proj_position), lim_ioc)
            filled_ioc = int(ioc_proj.get("filled") or 0)
            if filled_ioc <= 0:
                return _delete_pending_trade_for_rejection(
                    trade_id,
                    data.get("ticket_id"),
                    "IOC_ZERO_FILL",
                )
            projected_buy_price = ioc_proj.get("initial_proj_price")
            projected_open_fee = ioc_proj.get("initial_proj_fees")
            is_partial_ioc = filled_ioc < int(proj_position)
            eff_pos = filled_ioc
            next_paper_status = "partial" if is_partial_ioc else "open"
        else:
            next_paper_status = "open"
            eff_pos = None

        # Mark paper row filled (IOC partial|full or classic instant open)
        try:
            buy_price = projected_buy_price if projected_buy_price is not None else data.get('buy_price')
            position = eff_pos if eff_pos is not None else data.get('position')
            open_fee = 0.0
            buy_px_float = None
            if buy_price is not None:
                try:
                    buy_px_float = float(buy_price)
                except (TypeError, ValueError):
                    buy_px_float = None
            if projected_open_fee is not None:
                open_fee = float(projected_open_fee)
            elif buy_price is not None and position is not None:
                try:
                    open_fee = estimate_kalshi_taker_fee(float(position), float(buy_price))
                except (TypeError, ValueError):
                    pass
            pos_for_db = _trade_position_for_db(position) if position is not None else None
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    # Keep slippage in sync with entry buy_price whenever it is written (paper = instant fill at posted price).
                    if buy_px_float is not None:
                        prob_for_diff = data.get("prob")
                        if prob_for_diff is None:
                            cursor.execute(
                                f"SELECT prob FROM {_tm_trades_table()} WHERE id = %s",
                                (trade_id,),
                            )
                            row_prob = cursor.fetchone()
                            prob_for_diff = row_prob[0] if row_prob else None
                        diff_for_buy = _format_diff_from_prob_and_buy(prob_for_diff, buy_px_float)
                        cursor.execute(
                            f"""
                            UPDATE {_tm_trades_table()}
                            SET status = %s,
                                position = %s,
                                buy_price = %s,
                                fees = %s,
                                diff = %s,
                                order_id_open = NULL,
                                {_sql_slippage_from_buy_price_params()}
                            WHERE id = %s
                            """,
                            (
                                next_paper_status,
                                pos_for_db,
                                buy_px_float,
                                open_fee,
                                diff_for_buy,
                                buy_px_float,
                                buy_px_float,
                                trade_id,
                            ),
                        )
                    else:
                        cursor.execute(
                            f"""
                            UPDATE {_tm_trades_table()}
                            SET status = %s,
                                position = %s,
                                fees = %s,
                                order_id_open = NULL
                            WHERE id = %s
                            """,
                            (next_paper_status, pos_for_db, open_fee, trade_id),
                        )
                    pg_conn.commit()
                pg_conn.close()
            if projected_buy_price is not None or projected_open_fee is not None:
                log_event(
                    data.get("ticket_id", "UNKNOWN"),
                    "MANAGER: PAPER PROJECTION APPLIED "
                    f"buy_price={buy_px_float} fees={open_fee} status={next_paper_status}",
                )
        except Exception as e:
            log(f"⚠️ Failed to update paper trade to open: {e}")

        try:
            skip_paper_ledger = False
            try:
                pg_chk = get_postgresql_connection()
                if pg_chk:
                    with pg_chk.cursor() as cur_chk:
                        cur_chk.execute(
                            f"SELECT COALESCE(test_filter, FALSE) FROM {_tm_trades_table()} WHERE id = %s",
                            (trade_id,),
                        )
                        rchk = cur_chk.fetchone()
                        skip_paper_ledger = bool(rchk and rchk[0] is True)
                    pg_chk.close()
            except Exception as e:
                log_debug(f"paper ledger skip check trade_id={trade_id}: {e}")
            if (
                buy_price is not None
                and position is not None
                and not skip_paper_ledger
            ):
                _paper_ledger_on_open(float(buy_price), float(position), float(open_fee or 0.0))
        except Exception as e:
            log(f"⚠️ paper ledger after open: {e}")

        log_event(
            data.get("ticket_id", "UNKNOWN"),
            f"MANAGER: PAPER TRADE — {next_paper_status.upper()} (IMMEDIATE)",
        )

        # Notify active trade supervisor in background so slow ATS does not block response and cause client timeout
        ticket_id_val = data.get("ticket_id", "PAPER")
        def _paper_notify_background():
            try:
                notify_active_trade_supervisor_direct(trade_id, ticket_id_val, "pending")
                notify_ats_trade_open_with_ack(trade_id)
            except Exception as e:
                log(f"ERROR in paper-trade background notify: {e}")
        t = threading.Thread(target=_paper_notify_background, daemon=True)
        t.start()

        return {"id": trade_id}
    else:
        # LIVE TRADE: partial top-up reuses existing row; otherwise insert pending (same as paper) then executor.
        live_top = None
        pg_top = get_postgresql_connection()
        if pg_top:
            try:
                with pg_top.cursor() as c_top:
                    live_top = _find_live_partial_topup(
                        c_top,
                        data.get("monitor"),
                        data.get("ticker"),
                        data.get("side"),
                        data,
                    )
            finally:
                try:
                    pg_top.close()
                except Exception:
                    pass
        if live_top:
            tid_top, pos_top, ic_top, tkt_top = live_top
            try:
                residual_top = int(ic_top) - int(pos_top or 0)
            except (TypeError, ValueError):
                residual_top = 0
            if residual_top > 0:
                data["id"] = int(tid_top)
                if tkt_top:
                    data["ticket_id"] = str(tkt_top)
                data["count_fp"] = f"{float(residual_top):.2f}"
                pg_u = get_postgresql_connection()
                if pg_u:
                    try:
                        with pg_u.cursor() as cu:
                            cu.execute(
                                f"""
                                UPDATE {_tm_trades_table()}
                                SET status = %s, order_id_open = NULL
                                WHERE id = %s AND status = %s
                                """,
                                ("pending", int(tid_top), "partial"),
                            )
                            pg_u.commit()
                    finally:
                        try:
                            pg_u.close()
                        except Exception:
                            pass
                try:
                    log(f"SENDING PARTIAL TOP-UP TO EXECUTOR trade_id={tid_top} count_fp={data['count_fp']}")
                    send_trigger_to_executor(data)
                except Exception as e:
                    log(f"EXECUTOR ERROR (partial top-up): {e}")
                    log_event(data.get("ticket_id", "UNKNOWN"), f"EXECUTOR ERROR (partial top-up): {e}")
                return {"id": int(tid_top)}
        dup_live_id = _find_live_blocking_duplicate_trade_id(data)
        if dup_live_id is not None:
            log(
                f"LIVE OPEN DEDUP: existing pending/open trade id={dup_live_id} "
                f"monitor={data.get('monitor')!r} date={data.get('date')!r} — skipping executor and insert"
            )
            log_event(
                data.get("ticket_id", "UNKNOWN"),
                f"MANAGER: LIVE OPEN DEDUP reuse trade_id={dup_live_id}",
            )
            return {"id": dup_live_id}

        data["status"] = "pending"
        trade_id, inserted_new = insert_trade(data)
        if trade_id is None:
            log(f"❌ Failed to insert live trade to database - cannot notify active trade supervisor")
            log_event(
                data.get("ticket_id", "UNKNOWN"),
                "MANAGER: LIVE TRADE — DATABASE INSERT FAILED",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to insert trade to database",
            )
        if not inserted_new:
            log_event(
                data.get("ticket_id", "UNKNOWN"),
                f"MANAGER: LIVE insert_trade dedupe reuse trade_id={trade_id}",
            )
            return {"id": trade_id}

        data["id"] = trade_id
        try:
            if "count_fp" not in data or (
                data.get("count_fp") is None or str(data.get("count_fp", "")).strip() == ""
            ):
                data["count_fp"] = _format_count_fp(data, for_close=False)
            log(f"SENDING TO EXECUTOR trade_id={trade_id}")
            send_trigger_to_executor(data)
        except Exception as e:
            log(f"EXECUTOR ERROR: {e}")
            log_event(data.get("ticket_id", "UNKNOWN"), f"EXECUTOR ERROR: {e}")

        log(f"TRADE SENT TO EXECUTOR - PENDING ROW id={trade_id}")
        log_event(
            data.get("ticket_id", "UNKNOWN"),
            "MANAGER: LIVE PENDING ROW + EXECUTOR — CONFIRMED",
        )
        notify_active_trade_supervisor_direct(
            trade_id, str(data.get("ticket_id") or "UNKNOWN"), "pending"
        )
        return {"id": trade_id}


def _delete_pending_trade_for_rejection(trade_id: int, ticket_id: Optional[str], error_type: str) -> dict:
    """Delete pending trade (same behavior as insufficient_resting_volume handling)."""
    log(f"{error_type} ERROR - DELETING PENDING TRADE")
    if ticket_id:
        log_event(ticket_id, f"MANAGER: {error_type} - DELETING PENDING TRADE")

    monitor_identifier = None
    pg_conn = get_postgresql_connection()
    if pg_conn:
        with pg_conn.cursor() as cursor:
            cursor.execute(f"SELECT monitor FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
            row = cursor.fetchone()
            if row and row[0]:
                monitor_identifier = row[0]
        pg_conn.close()

    pg_conn = get_postgresql_connection()
    if pg_conn:
        with pg_conn.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {_tm_trades_table()} WHERE id = %s AND status = 'pending'",
                (trade_id,),
            )
            deleted_count = cursor.rowcount
            pg_conn.commit()
            pg_conn.close()

            if deleted_count > 0:
                log(f"DELETED PENDING TRADE {trade_id} DUE TO {error_type}")
                if monitor_identifier:
                    notify_active_trade_supervisor_direct_with_monitor(
                        trade_id, ticket_id, "deleted", monitor_identifier
                    )
                else:
                    notify_active_trade_supervisor_direct(trade_id, ticket_id, "deleted")
                return {"message": f"Pending trade deleted due to {error_type.lower()}", "id": trade_id}

            log("NO PENDING TRADE FOUND TO DELETE")
            return {"message": "No pending trade found to delete", "id": trade_id}

    log("CANNOT CONNECT TO DATABASE TO DELETE TRADE")
    return {"message": "Database connection error", "id": trade_id}


def _mark_close_trade_failed(trade_id: int, ticket_id: Optional[str], error_message: str) -> dict:
    """Close did not complete: position is still open. Revert tenant row to ``open`` so retries work.

    Paper FOK precheck failures mirror live executor insufficient-volume on close. Live executor
    errors use the same path. ATS receives ``close_attempt_failed`` so the pool can sync and retry;
    the failure is also logged as an operator alert (no persisted ``close_failed`` status).
    """
    log(
        f"ALERT CLOSE_ATTEMPT_FAILED trade_id={trade_id} detail={error_message!r} — "
        "reverting row to open (position unchanged; close may be retried)"
    )
    if ticket_id:
        log_event(
            ticket_id,
            "MANAGER: CLOSE ORDER FAILED - reverting status to open",
            trade_id=trade_id,
        )

    note_text = f"Auto Stop Fail - {error_message}"
    pg_conn = get_postgresql_connection()
    if pg_conn:
        try:
            with pg_conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE {_tm_trades_table()}
                    SET status = 'open',
                        order_id_close = NULL,
                        symbol_close = NULL,
                        close_method = NULL,
                        notes = %s
                    WHERE id = %s
                    """,
                    (note_text, trade_id),
                )
                if cursor.rowcount > 0:
                    log(f"UPDATED NOTES: {note_text}")
                else:
                    log(f"⚠️ close-failure revert: no row updated for trade_id={trade_id}")
                pg_conn.commit()
            pg_conn.close()
        except Exception as e:
            log(f"ERROR reverting trade to open after close failure: {e}")
            if pg_conn:
                pg_conn.close()

    _fanout_active_trades_change_via_redis_or_http(
        {
            "count": 1,
            "trade_id": trade_id,
            "status": "open",
            "timestamp": time.time(),
        }
    )
    notify_frontend_trade_change()
    notify_active_trade_supervisor_direct(trade_id, ticket_id, "close_attempt_failed")
    return {
        "message": "Close order failed - trade remains open for retry",
        "id": trade_id,
    }


def apply_update_trade_status_payload(data: dict):
    """
    Core handler for executor status updates (HTTP + Redis stream).
    Returns (response_dict, None) on success or (None, (status_code, detail)) on error.
    f"""
    log(f"STATUS UPDATE RECEIVED")
    id = data.get("id")
    ticket_id = data.get("ticket_id")
    new_status = data.get("status", "").strip().lower()
    order_id = data.get("order_id")
    intent = data.get("intent", "open")

    if not new_status or (not id and not ticket_id):
        return None, (400, "Missing id or ticket_id or status")

    if not id and ticket_id:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT id FROM {_tm_trades_table()} WHERE ticket_id = %s", (ticket_id,))
                row = cursor.fetchone()
        else:
            row = None
        if not row:
            return None, (404, "Trade with provided ticket_id not found")
        id = row[0]

    if not ticket_id:
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT ticket_id FROM {_tm_trades_table()} WHERE id = %s", (id,))
                row = cursor.fetchone()
        else:
            row = None
        ticket_id = row[0] if row else None

    if new_status == "accepted":
        log(f"TRADE ACCEPTED BY EXECUTOR")
        
        # Store the order_id in the database if provided
        if order_id:
            # Determine which order_id field to update based on intent
            if intent == "close":
                order_id_field = "order_id_close"
                log_type = "CLOSING"
            else:
                order_id_field = "order_id_open"
                log_type = "OPENING"
            
            log(f"STORING {log_type} ORDER_ID: {order_id}")
            if ticket_id:
                log_event(ticket_id, f"MANAGER: STORING KALSHI {log_type} ORDER_ID: {order_id}")
            
            try:
                pg_conn = get_postgresql_connection()
                if pg_conn:
                    with pg_conn.cursor() as cursor:
                        cursor.execute(f"UPDATE {_tm_trades_table()} SET {order_id_field} = %s WHERE id = %s", (order_id, id))
                        pg_conn.commit()
                        log(f"{log_type} ORDER_ID STORED SUCCESSFULLY")
                        if ticket_id:
                            log_event(ticket_id, f"MANAGER: {log_type} ORDER_ID STORED IN DATABASE: {order_id}")
                    pg_conn.close()
                    
                    # FAILSAFE: For opening trades, immediately trigger confirm_open_trade after storing order_id
                    # This catches the edge case where positions_updated arrives before executor callback
                    # In normal cases (99.9%), trade is already 'open' so confirm_open_trade will skip (no-op)
                    if intent == "open" and order_id:
                        log(f"🛡️ FAILSAFE: Triggering immediate confirmation for trade {id} after storing order_id")
                        threading.Thread(target=confirm_open_trade, args=(id, ticket_id), daemon=True).start()
                else:
                    log(f"FAILED TO STORE {log_type} ORDER_ID - NO DATABASE CONNECTION")
                    if ticket_id:
                        log_event(ticket_id, f"MANAGER: FAILED TO STORE {log_type} ORDER_ID - NO DATABASE CONNECTION")
            except Exception as e:
                log(f"ERROR STORING {log_type} ORDER_ID: {e}")
                if ticket_id:
                    log_event(ticket_id, f"MANAGER: ERROR STORING {log_type} ORDER_ID: {e}")
        
        log(f"WAITING FOR POSITION CONFIRMATION")
        return ({"message": "Trade accepted – waiting for position confirmation", "id": id}, None)

    elif new_status == "error":
        error_message = data.get("error_message", "")
        intent = data.get("intent", "open")  # Get the original intent
        
        # Check if it's a close order failure
        if intent == "close":
            return (_mark_close_trade_failed(id, ticket_id, error_message), None)
        
        # Check if it's an insufficient volume or insufficient balance error for OPEN orders
        elif "insufficient_resting_volume" in error_message.lower() or "insufficient balance" in error_message.lower():
            error_type = "INSUFFICIENT VOLUME" if "insufficient_resting_volume" in error_message.lower() else "INSUFFICIENT BALANCE"
            return (_delete_pending_trade_for_rejection(id, ticket_id, error_type), None)
        else:
            # Handle other errors normally
            update_trade_status(id, "error")
            if ticket_id:
                log_event(ticket_id, f"MANAGER: STATUS UPDATED — SET TO 'ERROR' - {error_message}")
            
            notify_active_trade_supervisor_direct(id, ticket_id, "error")
            
            return ({"message": "Trade marked error", "id": id}, None)

    else:
        return None, (400, f"Unrecognized status value: '{new_status}'")


@router.post("/api/update_trade_status")
async def update_trade_status_api(request: Request):
    """Handle status updates from executor"""
    data = await request.json()
    body, err = apply_update_trade_status_payload(data)
    if err:
        raise HTTPException(status_code=err[0], detail=err[1])
    return body


def apply_positions_updated_payload(data: dict) -> dict:
    """kalshi_account_sync_ws: same logic as POST /api/positions_updated (HTTP or Redis pub/sub)."""
    try:
        db_name = data.get("database", "positions")

        if db_name == "positions":
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute(f"SELECT id, ticket_id FROM {_tm_trades_table()} WHERE status = 'pending'")
                    pending_trades = cursor.fetchall()
            else:
                pending_trades = []

            if pending_trades:
                log(f"[🔔 POSITIONS UPDATED] Found {len(pending_trades)} pending trades to confirm")
                for id, ticket_id in pending_trades:
                    threading.Thread(target=confirm_open_trade, args=(id, ticket_id), daemon=True).start()

        if db_name == "orders":
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    cursor.execute(f"SELECT id, ticket_id FROM {_tm_trades_table()} WHERE status = 'closing'")
                    closing_trades = cursor.fetchall()
            else:
                closing_trades = []

            if closing_trades:
                log(f"[🔔 ORDERS UPDATED] Found {len(closing_trades)} closing trades to confirm")
                for id, ticket_id in closing_trades:
                    pg_conn = get_postgresql_connection()
                    if pg_conn:
                        with pg_conn.cursor() as cursor:
                            cursor.execute(f"SELECT status FROM {_tm_trades_table()} WHERE id = %s", (id,))
                            current_status = cursor.fetchone()
                    else:
                        current_status = None

                    if current_status and current_status[0] == "closing":
                        log(f"[🔔 ORDERS UPDATED] Confirming close for trade {id}")
                        confirm_close_trade(id, ticket_id)

        return {"message": f"{db_name}_updated received"}
    except Exception as e:
        log(f"[ERROR /api/positions_updated] {e}")
        return {"error": str(e)}


@router.post("/api/positions_updated")
async def positions_updated_api(request: Request):
    """Endpoint for kalshi_account_sync to notify about database updates"""
    data = await request.json()
    return apply_positions_updated_payload(data)

@router.post("/api/manual_expiration_check")
async def manual_expiration_check():
    """Manually trigger the expiration check - marks all open trades as expired"""
    try:
        log("[MANUAL] Manual expiration check triggered")
        
        # Run the expiration check in a separate thread to avoid blocking
        threading.Thread(target=check_expired_trades, daemon=True).start()
        
        return {"message": "Manual expiration check triggered"}
    except Exception as e:
        log(f"[ERROR /api/manual_expiration_check] {e}")
        return {"error": str(e)}

@router.post("/api/manual_settlement_poll")
async def manual_settlement_poll():
    """Manually sweep ``expired`` trades that already have ``market_result`` (finalize to ``closed``)."""
    try:
        log("[MANUAL] Manual finalize sweep for expired trades with market_result triggered")

        def _run_sweep():
            sweep_finalize_expired_trades_with_market_result()

        threading.Thread(target=_run_sweep, daemon=True).start()
        return {"message": "Manual finalize sweep started (expired rows with market_result)"}
    except Exception as e:
        log(f"[ERROR /api/manual_settlement_poll] {e}")
        return {"error": str(e)}

# ---------- EXPIRATION FUNCTIONS ----------------------------------------------------

def finalize_expired_trade_from_market_result(trade_id: int) -> bool:
    """Promote ``expired`` → ``closed`` using venue ``market_result`` + ``side`` (held to expiration). Idempotent."""
    from backend.core.kalshi_lifecycle_trade_outcome import expiry_win_loss_from_market_result

    if _trade_manager_scheduler_shutdown.is_set():
        return False

    pg_conn = get_postgresql_connection()
    if not pg_conn:
        log(f"⚠️ finalize_expired_trade_from_market_result: no DB trade_id={trade_id}")
        return False
    try:
        with pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT status, market_result, side, buy_price, position, fees, bankroll, mtb_base_value,
                       symbol_close, high_price, low_price, closed_at, ticker, paper_trade
                FROM {_tm_trades_table()}
                WHERE id = %s
                """,
                (trade_id,),
            )
            row = cursor.fetchone()
        pg_conn.close()
    except Exception as e:
        log(f"❌ finalize_expired_trade_from_market_result load failed trade_id={trade_id}: {e}")
        try:
            pg_conn.close()
        except Exception:
            pass
        return False

    if not row:
        return False
    (
        status,
        market_result,
        side,
        buy_price,
        position,
        existing_fees,
        bankroll,
        mtb_base,
        symbol_close,
        high_price,
        low_price,
        closed_at,
        ticker,
        paper_trade,
    ) = row

    if status != "expired":
        return False
    if market_result is None:
        return False

    win_loss = expiry_win_loss_from_market_result(side, market_result)
    if win_loss is None:
        log(
            f"⚠️ finalize_expired_trade_from_market_result: cannot derive W/L trade_id={trade_id} "
            f"side={side} market_result={market_result}"
        )
        return False

    sell_price = 1.0 if win_loss == "W" else 0.0
    existing_fees_f = float(existing_fees) if existing_fees is not None else 0.0

    pnl = None
    ret_pct = None
    ret_pct_base = None
    roi_pct = None
    if buy_price is not None and position is not None:
        # psycopg2 returns NUMERIC columns as Decimal; normalize before float math.
        bp_f = float(buy_price)
        pos_f = float(position)
        buy_value = bp_f * pos_f
        sell_value = float(sell_price) * pos_f
        pnl = round(sell_value - buy_value - existing_fees_f, 6)
        if bankroll is not None and float(bankroll) > 0 and pnl is not None:
            ret_pct = round((pnl / (float(bankroll) / 100.0)) * 100, 5)
        if mtb_base is not None and float(mtb_base) > 0 and pnl is not None:
            ret_pct_base = round((pnl / (float(mtb_base) / 100.0)) * 100, 5)
        if buy_value > 0 and pnl is not None:
            roi_pct = round((pnl / buy_value) * 100.0, 5)

    now_est = datetime.now(ZoneInfo("America/New_York"))
    use_closed_at = closed_at if closed_at else now_est.strftime("%H:%M:%S")

    update_trade_status_with_ret_pct(
        trade_id=trade_id,
        status="closed",
        closed_at=use_closed_at,
        sell_price=sell_price,
        symbol_close=symbol_close,
        win_loss=win_loss,
        pnl=pnl,
        close_method="expired",
        fees=existing_fees_f,
        roi_pct=roi_pct,
        ret_pct=ret_pct,
        ret_pct_base=ret_pct_base,
        high_price=high_price,
        low_price=low_price,
    )

    if paper_trade is True:
        pg2 = get_postgresql_connection()
        if pg2:
            try:
                with pg2.cursor() as c:
                    c.execute(
                        f"UPDATE {_tm_trades_table()} SET order_id_close = NULL WHERE id = %s",
                        (trade_id,),
                    )
                pg2.commit()
            except Exception:
                pass
            try:
                pg2.close()
            except Exception:
                pass

    log(
        f"📝 EXPIRED FINALIZED (market_result): trade {trade_id}, {ticker}, "
        f"W/L={win_loss}, PnL={pnl}, sell={sell_price}"
    )
    notify_active_trade_supervisor_direct(trade_id, str(ticker or ""), "closed")
    notify_strike_table_trade_change(trade_id, "closed")
    return True


def _hypothetical_win_loss_at_expiration(strike, side, symbol_expiration) -> Optional[str]:
    """W/L if the trade were held to expiration given spot at cycle end (same rules as paper settlement)."""
    if symbol_expiration is None or strike is None or side is None:
        return None
    try:
        strike_clean = str(strike).replace("$", "").replace(",", "")
        strike_float = float(strike_clean)
        sym_exp = float(symbol_expiration)
    except (ValueError, TypeError):
        return None
    side_u = str(side).strip().upper()
    if side_u in ("Y", "YES"):
        return "W" if sym_exp >= strike_float else "L"
    if side_u in ("N", "NO"):
        return "W" if sym_exp <= strike_float else "L"
    return None


def _normalize_win_loss_for_confirm(actual) -> Optional[str]:
    if actual is None:
        return None
    a = str(actual).strip().upper()
    if not a:
        return None
    if a in ("D", "DRAW", "TIE", "PUSH"):
        return None
    if a[0] == "W":
        return "W"
    if a[0] == "L":
        return "L"
    if a in ("1", "TRUE", "YES"):
        return "W"
    if a in ("0", "FALSE", "NO"):
        return "L"
    return None


def _compute_win_loss_confirmed(strike, side, symbol_expiration, win_loss_actual) -> Optional[bool]:
    hypo = _hypothetical_win_loss_at_expiration(strike, side, symbol_expiration)
    act = _normalize_win_loss_for_confirm(win_loss_actual)
    if hypo is None or act is None:
        return None
    return hypo == act


def _finalize_closed_trade_win_loss_confirmed(cursor, trade_id: int) -> None:
    """Last persistence step for a closed live/paper trade: set ``win_loss_confirmed`` from venue or spot-at-expiry."""
    cursor.execute(
        f"""
        SELECT strike, side, symbol_expiration, symbol_close, win_loss, status, close_method, market_result
        FROM {_tm_trades_table()} WHERE id = %s
        """,
        (trade_id,),
    )
    row = cursor.fetchone()
    if not row:
        return
    strike, side, sym_exp, sym_close, win_loss, row_status, close_method, market_result = row
    if row_status != "closed":
        return
    wlc = None
    try:
        cm = str(close_method or "").strip().lower()
    except Exception:
        cm = ""
    if cm == "expired" and market_result:
        from backend.core.kalshi_lifecycle_trade_outcome import compute_win_loss_confirmed_from_venue

        mr = str(market_result).strip().lower()
        if mr in ("yes", "no"):
            wlc = compute_win_loss_confirmed_from_venue(side, mr, win_loss)
    if wlc is None:
        eff_sym_exp = sym_exp
        if eff_sym_exp is None and sym_close is not None:
            try:
                eff_sym_exp = float(sym_close)
            except (TypeError, ValueError):
                eff_sym_exp = None
        if eff_sym_exp is not None:
            try:
                eff_sym_exp = float(eff_sym_exp)
            except (TypeError, ValueError):
                eff_sym_exp = None
        wlc = _compute_win_loss_confirmed(strike, side, eff_sym_exp, win_loss)
    if wlc is None:
        return
    cursor.execute(
        f"""
        UPDATE {_tm_trades_table()}
        SET win_loss_confirmed = %s
        WHERE id = %s AND status = 'closed'
        """,
        (wlc, trade_id),
    )


def check_expired_simulated_trades():
    """Expire and settle open simulated trades on the 15m schedule. All simulated trades are treated as 15m.
    Records sell_price as NULL; sets cycle_win_loss per 15m window (L if any loss in that monitor/cycle, else W)."""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return
        with pg_conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, ticker, symbol, strike, side, monitor, date, weekly_cycle, contract "
                f"FROM {_tm_trades_simulated_table()} "
                "WHERE status IN ('open', 'closing', 'partial')"
            )
            active = cursor.fetchall()
        pg_conn.close()
        if not active:
            return
        now_est = datetime.now(ZoneInfo("America/New_York"))
        closed_at = now_est.strftime("%H:%M:%S")
        symbol_prices = {}
        cycles_closed = set()  # (monitor, date, weekly_cycle) for cycle_win_loss update
        for row in active:
            trade_id, ticker, symbol, strike, side = row[0], row[1], row[2], row[3], row[4]
            monitor, trade_date, weekly_cycle, contract = row[5], row[6], row[7], row[8]
            expiration_est = _contract_expiration_est(trade_date, contract, now_est)
            # Do not settle before the contract's expiration instant (wall clock). Otherwise each
            # 15m sweep would still pick one_minute_avg with timestamp <= expiry, which is often
            # "latest tick so far" — e.g. closing 8:00pm hourly-sim rows at the 7:45 sweep.
            if now_est < expiration_est:
                continue
            cache_key = (symbol, expiration_est.replace(tzinfo=None))
            if cache_key not in symbol_prices:
                symbol_prices[cache_key] = _fetch_one_minute_avg_at_or_before(
                    symbol, expiration_est, max_gap_seconds=90
                )
            symbol_close = symbol_prices.get(cache_key)
            if symbol_close is None:
                continue
            strike_clean = str(strike).replace("$", "").replace(",", "")
            strike_float = float(strike_clean)
            symbol_close_float = float(symbol_close)
            is_winner = False
            if side and str(side).upper() in ("Y", "YES"):
                is_winner = symbol_close_float >= strike_float
            elif side and str(side).upper() in ("N", "NO"):
                is_winner = symbol_close_float <= strike_float
            win_loss = "W" if is_winner else "L"
            conn = get_postgresql_connection()
            if not conn:
                continue
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        UPDATE {_tm_trades_simulated_table()}
                        SET status = 'closed',
                            closed_at = %s,
                            symbol_close = %s,
                            sell_price = NULL,
                            win_loss = %s,
                            close_method = 'expired',
                            fees = NULL
                        WHERE id = %s AND status IN ('open', 'closing', 'partial')
                        """,
                        (closed_at, symbol_close, win_loss, trade_id),
                    )
                conn.commit()
                if monitor is not None and trade_date is not None and weekly_cycle is not None:
                    cycles_closed.add((monitor, trade_date, weekly_cycle))
                log(f"📝 SIMULATED TRADE EXPIRED/SETTLED: id={trade_id}, {ticker}, W/L={win_loss}")
            except Exception as e:
                log(f"⚠️ Failed to settle simulated trade {trade_id}: {e}")
            finally:
                conn.close()
        # Set cycle_win_loss per 15m window: L if any loss in that monitor/cycle, else W;
        # then bump per-monitor simulated-trade LP ledger when the cycle has losses.
        loss_cycles_for_lp: List[Tuple[Any, Any, Any]] = []
        for monitor, trade_date, weekly_cycle in cycles_closed:
            try:
                conn = get_postgresql_connection()
                if not conn:
                    continue
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"""
                        SELECT 1 FROM {_tm_trades_simulated_table()}
                        WHERE monitor = %s AND date = %s AND weekly_cycle = %s AND status = 'closed' AND win_loss = 'L'
                        LIMIT 1
                        """,
                        (monitor, trade_date, weekly_cycle),
                    )
                    has_loss = cursor.fetchone() is not None
                    cycle_win_loss = "L" if has_loss else "W"
                    cursor.execute(
                        f"""
                        UPDATE {_tm_trades_simulated_table()}
                        SET cycle_win_loss = %s
                        WHERE monitor = %s AND date = %s AND weekly_cycle = %s
                        """,
                        (cycle_win_loss, monitor, trade_date, weekly_cycle),
                    )
                    if has_loss:
                        loss_cycles_for_lp.append((monitor, trade_date, weekly_cycle))
                conn.commit()
                conn.close()
            except Exception as e:
                log(f"⚠️ Failed to set cycle_win_loss for simulated cycle {monitor}/{trade_date}/{weekly_cycle}: {e}")

        if loss_cycles_for_lp:
            try:
                pg_lp = get_postgresql_connection()
                if not pg_lp:
                    log("⚠️ simulated_trade LP batch: no DB connection")
                else:
                    tenant_slot = effective_tenant_context_for_sql_rewrite().user_no
                    ml_tbl = _tm_monitor_list_table()
                    tr_tbl = _tm_trades_table()
                    tsim_tbl = _tm_trades_simulated_table()
                    led_tbl = legacy_users_sim_trade_lp_cycle_ledger(tenant_slot)
                    with pg_lp.cursor() as lp_cur:
                        for monitor, trade_date, weekly_cycle in loss_cycles_for_lp:
                            try:
                                contrib, anch = cycle_loss_contribution_and_anchor(
                                    lp_cur,
                                    tsim_tbl,
                                    tr_tbl,
                                    str(monitor).strip(),
                                    trade_date,
                                    weekly_cycle,
                                )
                                if contrib <= 0 or anch is None:
                                    continue
                                apply_sim_trade_cycle_loss(
                                    lp_cur,
                                    monitor_list_qualified=ml_tbl,
                                    trades_qualified=tr_tbl,
                                    trades_simulated_qualified=tsim_tbl,
                                    ledger_qualified=led_tbl,
                                    tenant_slot=str(tenant_slot),
                                    monitor_key=str(monitor).strip(),
                                    cycle_date=trade_date,
                                    weekly_cycle=weekly_cycle,
                                    loss_anchor_ts=anch,
                                )
                            except Exception as le:
                                log(
                                    f"⚠️ simulated_trade LP after sim settle {monitor}/{trade_date}/{weekly_cycle}: {le}"
                                )
                    pg_lp.commit()
                    pg_lp.close()
            except Exception as e:
                log(f"⚠️ simulated_trade LP batch after simulated settle: {e}")
    except Exception as e:
        log(f"⚠️ check_expired_simulated_trades: {e}")


def check_expired_trades():
    """Check for expired trades.

    Runs on a 15-minute schedule. At minute 0 it processes all active trades.
    At minutes 15, 30, and 45 it processes only rows whose ``market`` column is
    ``15m`` (aligned with the monitor's market). Hourly or NULL ``market`` is
    expired only at :00, for every strategy.
    """
    if _trade_manager_scheduler_shutdown.is_set():
        return
    try:
        now_est = datetime.now(ZoneInfo("America/New_York"))
        log(f"[15-MIN CHECK] Starting expiry sweep at {now_est.strftime('%Y-%m-%d %H:%M:%S %Z')}")

        # Step 1: Delete trades with status ERROR
        delete_error_trades()

        # Early-closed trades: fill symbol_expiration once contract end has passed (same 1m avg @ expiration tick).
        _backfill_symbol_expiration_past_due_closed(now_est)

        # Paper trades can be stuck ``expired`` if symbol_close failed during sweep (e.g. text vs timestamp bug).
        _settle_stuck_expired_paper_trades(now_est)
        _repair_missing_symbol_close_recent(now_est)

        closed_at = now_est.strftime("%H:%M:%S")
        current_minute = now_est.minute

        if current_minute % 15 != 0:
            # Safety guard: scheduler should only call us at multiples of 15.
            log(f"[15-MIN CHECK] Skipping run at minute={current_minute} (not on 15-minute boundary)")
            return

        # Simulated trades: run every 15m regardless of live trade count; close and set W/L from symbol_close
        check_expired_simulated_trades()

        # Step 2: Check for open, partial, and closing trades (live) to mark as expired
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, ticker, symbol, trade_strategy, contract, date, market "
                    f"FROM {_tm_trades_table()} "
                    "WHERE status IN ('open', 'closing', 'partial')"
                )
                active_trades = cursor.fetchall()
        else:
            active_trades = []

        if not active_trades:
            return

        # Decide which trades to process on this run.
        # - At minute 0: process all active trades (original hourly behavior).
        # - At minutes 15/30/45: process trades with market = 15m only.
        if current_minute == 0:
            trades_to_process = active_trades
        else:
            trades_to_process = [
                row for row in active_trades if _trade_eligible_for_quarter_hour_expiry(row[6])
            ]

        log(
            f"[15-MIN CHECK] Active trades={len(active_trades)}, "
            f"eligible_for_this_run={len(trades_to_process)}, minute={current_minute}"
        )

        if not trades_to_process:
            log("[15-MIN CHECK] No eligible trades found for expiration")
            return

        before_expiry_filter = len(trades_to_process)
        trades_to_process = _filter_trades_past_contract_expiration(trades_to_process, now_est)
        skipped_early = before_expiry_filter - len(trades_to_process)
        if skipped_early:
            log(
                f"[15-MIN CHECK] Skipped {skipped_early} trade(s) not yet past contract expiry"
            )

        if not trades_to_process:
            log("[15-MIN CHECK] No trades past contract expiry for this run")
            return

        # Closing prices: one_minute_avg at or before each trade's contract expiration tick.
        expiration_price_cache = {}
        for trade_id, ticker, symbol, trade_strategy, contract, trade_date, _trade_mkt in trades_to_process:
            expiration_est = _contract_expiration_est(trade_date, contract, now_est)
            cache_key = (symbol, expiration_est.replace(tzinfo=None))
            if cache_key not in expiration_price_cache:
                expiration_price_cache[cache_key] = _fetch_one_minute_avg_at_or_before(
                    symbol, expiration_est, max_gap_seconds=90
                )
            if expiration_price_cache.get(cache_key) is None:
                log(
                    f"[15-MIN CHECK] No one_minute_avg at/before expiration for {symbol} "
                    f"(ticker={ticker}, exp={expiration_est.strftime('%Y-%m-%d %H:%M:%S %Z')})"
                )
        
        # Update PostgreSQL - handle each trade individually with its symbol-specific closing price
        try:
            pg_conn = get_postgresql_connection()
            if pg_conn:
                with pg_conn.cursor() as cursor:
                    for trade_id, ticker, symbol, trade_strategy, contract, trade_date, _trade_mkt in trades_to_process:
                        expiration_est = _contract_expiration_est(trade_date, contract, now_est)
                        if now_est < expiration_est:
                            continue
                        cache_key = (symbol, expiration_est.replace(tzinfo=None))
                        symbol_close = expiration_price_cache.get(cache_key)
                        
                        # CRITICAL: Re-check trade status before UPDATE to prevent race condition
                        # If trade was already closed between SELECT and UPDATE, skip it entirely
                        cursor.execute(f"SELECT status, high_price, low_price FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                        status_check = cursor.fetchone()
                        
                        if not status_check:
                            continue  # Trade doesn't exist, skip
                        
                        current_status, existing_high_price, existing_low_price = status_check
                        
                        # IMMUTABILITY RULE: Never touch already-closed trades
                        if current_status == 'closed':
                            log(f"⚠️ EXPIRATION: Skipping trade {trade_id} - already closed (immutability rule)")
                            continue
                        
                        # Only process trades that are still open, partial, or closing
                        if current_status not in ('open', 'closing', 'partial'):
                            continue
                        
                        # Get high_price and low_price from active_trades before it's removed
                        high_price, low_price = get_high_low_prices_from_active_trades(trade_id)
                        
                        # PRESERVE EXISTING VALUES: If get_high_low_prices_from_active_trades() returns (None, None),
                        # but trade already has values, preserve them instead of overwriting with NULL
                        if high_price is None and existing_high_price is not None:
                            high_price = existing_high_price
                            log(f"⚠️ EXPIRATION: Preserving existing high_price={high_price} for trade {trade_id}")
                        
                        if low_price is None and existing_low_price is not None:
                            low_price = existing_low_price
                            log(f"⚠️ EXPIRATION: Preserving existing low_price={low_price} for trade {trade_id}")
                        
                        # Set monitor_confirmed = TRUE if high_price != low_price (meaning ATS was monitoring correctly)
                        monitor_confirmed = False
                        if high_price is not None and low_price is not None:
                            if high_price != low_price:
                                monitor_confirmed = True
                                log(f"✅ EXPIRATION: Trade {trade_id}: monitor_confirmed = TRUE (high_price={high_price} != low_price={low_price})")
                            else:
                                log(f"⚠️ EXPIRATION: Trade {trade_id}: monitor_confirmed = FALSE (high_price == low_price = {high_price})")
                        
                        cursor.execute(f"""
                            UPDATE {_tm_trades_table()} 
                            SET status = 'expired', 
                                closed_at = %s, 
                                symbol_close = %s,
                                close_method = 'expired',
                                high_price = %s,
                                low_price = %s,
                                monitor_confirmed = %s
                            WHERE id = %s AND status IN ('open', 'closing', 'partial')
                        """, (closed_at, symbol_close, high_price, low_price, monitor_confirmed, trade_id))
                    markets_applied = set()
                    for _tid, _ticker, _symbol, _strategy, _contract, _trade_date, _m in trades_to_process:
                        k = (str(_symbol).strip(), str(_contract).strip(), str(_trade_date))
                        if k in markets_applied:
                            continue
                        markets_applied.add(k)
                        _apply_symbol_expiration_for_contract_session(cursor, _symbol, _trade_date, _contract)
                    pg_conn.commit()
                    with pg_conn.cursor() as bf_cursor:
                        _apply_win_loss_confirmed_for_trade_ids(
                            bf_cursor, [row[0] for row in trades_to_process]
                        )
                    pg_conn.commit()
                    log_debug(
                        f"💾 Expired trades update written to PostgreSQL tenant trades for "
                        f"{len(trades_to_process)} trades (open, partial, and closing)"
                    )
                pg_conn.close()
            else:
                log(f"⚠️ Skipping PostgreSQL expired trades update - no connection available")
        except Exception as pg_err:
            log(f"❌ Failed to update expired trades in PostgreSQL: {pg_err}")
        
        notify_frontend_trade_change()
        
        # Separate paper trades from live trades (only for trades we just expired)
        paper_trade_ids = []
        live_trade_tickers = []
        
        try:
            pg_conn_check = get_postgresql_connection()
            if pg_conn_check:
                with pg_conn_check.cursor() as cursor:
                    for trade_id, ticker, symbol, trade_strategy, contract, trade_date, _trade_mkt in trades_to_process:
                        cursor.execute(f"SELECT paper_trade FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                        result = cursor.fetchone()
                        if result and result[0] is True:
                            paper_trade_ids.append((trade_id, ticker, symbol))
                        else:
                            live_trade_tickers.append(ticker)
                pg_conn_check.close()
            else:
                # If we can't check, treat all as live trades
                for trade_id, ticker, symbol, trade_strategy, contract, trade_date, _trade_mkt in trades_to_process:
                    live_trade_tickers.append(ticker)
        except Exception as e:
            log(f"⚠️ Error separating paper/live trades: {e}, treating all as live")
            for trade_id, ticker, symbol, trade_strategy, contract, trade_date, _trade_mkt in trades_to_process:
                live_trade_tickers.append(ticker)
        
        # Notify active_trade_supervisor for all expired trades (both paper and live)
        for trade_id, ticker, symbol, trade_strategy, contract, trade_date, _trade_mkt in trades_to_process:
            notify_active_trade_supervisor_direct(trade_id, str(ticker), "expired")
        
        # Paper: repair symbol_close; finalize when ``market_result`` exists (same as live).
        if paper_trade_ids:
            log(f"📝 Processing {len(paper_trade_ids)} expired paper trades")
            for trade_id, ticker, symbol in paper_trade_ids:
                _settle_one_expired_paper_trade(now_est, trade_id, ticker, symbol)

        paper_ids_set = {pid for pid, _, _ in paper_trade_ids}
        attempted_ticker_backfill = set()
        for trade_id, ticker, symbol, trade_strategy, contract, trade_date, _trade_mkt in trades_to_process:
            if trade_id not in paper_ids_set:
                finalized = finalize_expired_trade_from_market_result(trade_id)
                if finalized:
                    continue
                mt = str(ticker or "").strip()
                if not mt:
                    continue
                if mt not in attempted_ticker_backfill:
                    attempted_ticker_backfill.add(mt)
                    applied_now = _backfill_market_result_for_ticker_now(mt)
                    if applied_now > 0:
                        log(
                            f"[EXPIRY] immediate market_result apply rows={applied_now} "
                            f"ticker={mt}"
                        )
                finalize_expired_trade_from_market_result(trade_id)

        log(
            f"[15-MIN CHECK] Completed expiry sweep; "
            f"processed={len(trades_to_process)}, paper={len(paper_trade_ids)}, live={len(live_trade_tickers)}"
        )
        
    except Exception as e:
        log(f"[15-MIN CHECK] Error during expiry sweep: {e}")

def delete_error_trades():
    """Delete trades with status ERROR from PostgreSQL database"""
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            log(f"❌ Cannot connect to PostgreSQL for error cleanup")
            return
        
        with pg_conn.cursor() as cursor:
            # Count ERROR trades before deletion
            cursor.execute(f"SELECT COUNT(*) FROM {_tm_trades_table()} WHERE status = 'error'")
            error_count = cursor.fetchone()[0]
            
            if error_count > 0:
                # Delete trades with status ERROR
                cursor.execute(f"DELETE FROM {_tm_trades_table()} WHERE status = 'error'")
                deleted_count = cursor.rowcount
                pg_conn.commit()
                
                log(f"🧹 DELETED {deleted_count} ERROR trades from PostgreSQL database")
            else:
                log(f"🧹 No ERROR trades found to delete")
        
        pg_conn.close()
        
    except Exception as e:
        log(f"❌ Error deleting ERROR trades: {e}")
        try:
            pg_conn.close()
        except:
            pass

def sweep_finalize_expired_trades_with_market_result() -> None:
    """Finalize ``expired`` rows that already have ``market_result`` (idempotent; repairs delayed finalize)."""
    if _trade_manager_scheduler_shutdown.is_set():
        return
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return
        with pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id FROM {_tm_trades_table()}
                WHERE status = 'expired' AND market_result IS NOT NULL
                ORDER BY id
                LIMIT 500
                """
            )
            rows = cursor.fetchall() or []
        pg_conn.close()
        if not rows:
            return
        log(
            f"[5-MIN CHECK] Finalize sweep: {len(rows)} expired trade(s) with market_result"
        )
        for (tid,) in rows:
            if _trade_manager_scheduler_shutdown.is_set():
                break
            finalize_expired_trade_from_market_result(int(tid))
    except Exception as e:
        log(f"[5-MIN CHECK] Finalize sweep error: {e}")


def _backfill_market_result_for_ticker_now(ticker: str) -> int:
    """
    Immediate one-ticker outcome backfill used during expiry processing.
    Returns number of trade rows updated by lifecycle apply.
    """
    mt = str(ticker or "").strip()
    if not mt:
        return 0
    try:
        from backend.core.kalshi_event_market_fetch import (
            event_ticker_from_market_ticker,
            fetch_event_payload,
            normalized_result_for_market_in_payload,
        )
        from backend.core.kalshi_lifecycle_trade_outcome import (
            apply_lifecycle_market_result_for_ticker,
        )

        et = event_ticker_from_market_ticker(mt)
        if not et:
            return 0
        payload = fetch_event_payload(et)
        result = normalized_result_for_market_in_payload(payload, mt)
        if result not in ("yes", "no"):
            return 0
        return int(apply_lifecycle_market_result_for_ticker(mt, result) or 0)
    except Exception as e:
        log(f"[EXPIRY] immediate market_result backfill failed ticker={mt}: {e}")
        return 0


def backfill_expired_market_results_from_kalshi(limit: int = 250) -> None:
    """
    Repair missed lifecycle outcomes by polling Kalshi /events for expired rows still missing
    ``market_result``. This is a safety net when WS/Redis fanout drops a ``determined`` event.
    """
    if _trade_manager_scheduler_shutdown.is_set():
        return
    try:
        pg_conn = get_postgresql_connection()
        if not pg_conn:
            return
        with pg_conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT DISTINCT ticker
                FROM {_tm_trades_table()}
                WHERE status = 'expired'
                  AND market_result IS NULL
                  AND ticker IS NOT NULL
                  AND TRIM(ticker::text) <> ''
                ORDER BY ticker
                LIMIT %s
                """,
                (int(limit),),
            )
            tickers = [str(r[0]).strip() for r in (cursor.fetchall() or []) if r and r[0]]
        pg_conn.close()
        if not tickers:
            return

        from backend.core.kalshi_event_market_fetch import (
            event_ticker_from_market_ticker,
            fetch_event_payload,
            normalized_result_for_market_in_payload,
        )
        from backend.core.kalshi_lifecycle_trade_outcome import (
            apply_lifecycle_market_result_for_ticker,
        )

        payload_by_event: Dict[str, Optional[Dict[str, Any]]] = {}
        checked = 0
        applied = 0
        for mt in tickers:
            et = event_ticker_from_market_ticker(mt)
            if not et:
                continue
            if et not in payload_by_event:
                payload_by_event[et] = fetch_event_payload(et)
            payload = payload_by_event.get(et)
            checked += 1
            result = normalized_result_for_market_in_payload(payload, mt)
            if result in ("yes", "no"):
                try:
                    n = apply_lifecycle_market_result_for_ticker(mt, result)
                    if n:
                        applied += int(n)
                except Exception as e:
                    log(f"[5-MIN CHECK] backfill apply failed ticker={mt}: {e}")
        if applied > 0:
            log(
                f"[5-MIN CHECK] Kalshi outcome backfill applied rows={applied} "
                f"tickers_checked={checked} candidates={len(tickers)}"
            )
    except Exception as e:
        log(f"[5-MIN CHECK] Kalshi outcome backfill error: {e}")


def check_expired_trades_for_settlements():
    """Periodic sweep: finalize ``expired`` trades once ``market_result`` is present."""
    if _trade_manager_scheduler_shutdown.is_set():
        return
    backfill_expired_market_results_from_kalshi()
    sweep_finalize_expired_trades_with_market_result()


def notify_monitor_manager_trade_closed(trade_id: int, status: str) -> None:
    """Notify monitor_manager when a trade is closed to update monitor statistics"""
    try:
        # Get the monitor identifier for this trade
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT monitor FROM {_tm_trades_table()} WHERE id = %s", (trade_id,))
                monitor_row = cursor.fetchone()
                monitor = monitor_row[0] if monitor_row else None
            pg_conn.close()
        else:
            monitor = None
        
        if monitor:
            payload = {"trade_id": trade_id, "status": status, "monitor": monitor}
            _notify_monitor_manager_trade_payload(payload)
            log(f"✅ Notified monitor_manager (Redis or HTTP) about closed trade {trade_id} for monitor {monitor}")
        else:
            log(f"⚠️ No monitor found for trade {trade_id}, skipping monitor_manager notification")
            
    except Exception as e:
        # Don't fail the trade close if monitor notification fails
        log(f"⚠️ Error notifying monitor_manager about trade {trade_id}: {e}")

def notify_monitor_manager_trades_closed_by_ticker(ticker: str, status: str) -> None:
    """Notify monitor_manager about trades closed by ticker (for settlements/expired trades)"""
    try:
        # Get all trades for this ticker and their monitor identifiers
        pg_conn = get_postgresql_connection()
        if pg_conn:
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SELECT id, monitor FROM {_tm_trades_table()} WHERE ticker = %s AND status = 'closed'", (ticker,))
                trades = cursor.fetchall()
            pg_conn.close()
        else:
            trades = []
        
        if trades:
            # Group trades by monitor to send one notification per monitor
            monitors = set()
            for trade_id, monitor in trades:
                if monitor:
                    monitors.add(monitor)
            
            # Send notification to monitor_manager for each affected monitor
            for monitor in monitors:
                try:
                    payload = {
                        "trade_id": None,
                        "status": status,
                        "monitor": monitor,
                        "bulk_update": True,
                        "ticker": ticker,
                    }
                    _notify_monitor_manager_trade_payload(payload)
                    log(
                        f"✅ Notified monitor_manager (Redis or HTTP) bulk closure ticker {ticker} monitor {monitor}"
                    )
                    refresh_monitor_cycle_performance_for_monitor(monitor)
                except Exception as e:
                    log(f"⚠️ Error notifying monitor_manager about bulk trade closure for ticker {ticker}, monitor {monitor}: {e}")
        else:
            log(f"⚠️ No closed trades found for ticker {ticker}, skipping monitor_manager notification")
            
    except Exception as e:
        # Don't fail the settlement if monitor notification fails
        log(f"⚠️ Error notifying monitor_manager about bulk trade closure for ticker {ticker}: {e}")

def _trade_manager_executor_status_handler(decoded: dict, msg_id: str, raw_fields: dict) -> bool:
    if decoded.get("type") != "update_trade_status":
        return True
    payload = decoded.get("payload") if isinstance(decoded.get("payload"), dict) else {}
    try:
        from backend.core.trading_redis_comms import idempotency_begin, redis_client_optional, use_trading_redis_comms

        if use_trading_redis_comms():
            r = redis_client_optional()
            if r:
                cid = str(decoded.get("correlation_id") or msg_id)
                if not idempotency_begin(r, f"trading:dedupe:tmst:{cid}", ttl_sec=600):
                    return True
        body, err = apply_update_trade_status_payload(payload)
        if err:
            log(f"⚠️ Redis executor status: {err}")
        elif body:
            pass
    except Exception as e:
        log(f"❌ trade_manager executor status stream: {e}")
    return True


def _trade_manager_command_handler(decoded: dict, msg_id: str, raw_fields: dict) -> bool:
    if decoded.get("type") != "add_trade":
        return True
    payload = decoded.get("payload") if isinstance(decoded.get("payload"), dict) else {}
    try:
        from backend.core.trading_redis_comms import idempotency_begin, redis_client_optional, use_trading_redis_comms

        if use_trading_redis_comms():
            r = redis_client_optional()
            if r:
                cid = str(decoded.get("correlation_id") or msg_id)
                if not idempotency_begin(r, f"trading:dedupe:tm_cmd:{cid}", ttl_sec=600):
                    return True
        port = get_port("trade_manager")
        host = get_host()
        resp = requests.post(f"http://{host}:{port}/trades", json=payload, timeout=120)
        if resp.status_code not in (200, 201):
            log(
                f"❌ tm_commands consumer: local POST /trades returned {resp.status_code} "
                f"(Redis delivery OK; fix trade_manager handler). "
                f"body={getattr(resp, 'text', '')[:900]!r}"
            )
        else:
            try:
                j = resp.json()
                if isinstance(j, dict) and j.get("error") is not None:
                    log(
                        f"❌ tm_commands consumer: POST /trades 2xx but JSON error field: {j!r}"
                    )
            except Exception:
                pass
    except Exception as e:
        log(f"❌ trade_manager command stream: {e}")
    return True


def start_trading_redis_trade_manager_consumers(
    stop_event: Optional[threading.Event] = None,
) -> None:
    from backend.core.trading_redis_comms import (
        default_consumer_name,
        start_consumer_daemon,
        stream_tm_commands_for_worker,
        stream_tm_status_for_worker,
        use_trading_redis_comms,
    )

    if not use_trading_redis_comms():
        return
    start_consumer_daemon(
        stream_tm_status_for_worker(),
        "tm_status",
        default_consumer_name("tm-status"),
        _trade_manager_executor_status_handler,
        stop_event=stop_event,
    )
    start_consumer_daemon(
        stream_tm_commands_for_worker(),
        "tm_commands",
        default_consumer_name("tm-cmd"),
        _trade_manager_command_handler,
        stop_event=stop_event,
    )


def start_trade_manager_positions_updated_subscriber() -> None:
    """kalshi_account_sync_ws → trade_manager via Redis (rec_io:tm:positions_updated)."""
    from backend.core.trading_redis_comms import channel_tm_positions_updated, redis_client_optional, use_trading_redis_comms

    if not use_trading_redis_comms():
        return

    def loop():
        backoff = 3.0
        while True:
            try:
                r = redis_client_optional()
                if not r:
                    time.sleep(backoff)
                    continue
                pubsub = r.pubsub()
                ch = channel_tm_positions_updated()
                pubsub.subscribe(ch)
                log(f"trade_manager subscribed to Redis {ch}")
                backoff = 3.0
                for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    raw = msg.get("data")
                    if raw is None:
                        continue
                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue
                    try:
                        apply_positions_updated_payload(data)
                    except Exception as e:
                        log(f"Redis positions_updated handling: {e}")
            except Exception as e:
                log(f"trade_manager positions_updated Redis subscriber reconnect: {e}")
                time.sleep(backoff)
                backoff = min(backoff * 1.3, 60.0)

    threading.Thread(target=loop, daemon=True, name="tm-positions-updated-redis").start()


def _notify_monitor_manager_trade_payload(payload: dict) -> None:
    try:
        from backend.core.trading_redis_comms import publish_monitor_manager_event, use_trading_redis_comms

        if use_trading_redis_comms() and publish_monitor_manager_event(payload):
            return
    except Exception:
        pass
    try:
        monitor_manager_port = get_port("monitor_manager")
        requests.post(
            f"http://localhost:{monitor_manager_port}/api/trade_status_update",
            json=payload,
            timeout=5,
        )
    except Exception:
        pass


# ---------- APScheduler Setup ----------------------------------------------------

_scheduler = BackgroundScheduler(timezone=ZoneInfo("America/New_York"))
_scheduler.add_job(check_expired_trades, CronTrigger(minute="*/15", second=0), max_instances=1, coalesce=True)
_scheduler.add_job(check_expired_trades_for_settlements, CronTrigger(minute="*/5", second=0), max_instances=1, coalesce=True)
_scheduler.add_job(
    refresh_all_monitor_cycle_performance,
    CronTrigger(hour=3, minute=15, second=0),
    max_instances=1,
    coalesce=True
)

from contextlib import asynccontextmanager


def _tm_startup_sim_trade_lp_reconcile() -> None:
    """Rebuild sim-trade LP ledger + cooldown anchors from trades (Eastern-safe); runs once per TM process."""
    try:
        pg = get_postgresql_connection()
        if not pg:
            log("⚠️ [SIM TRADE LP] trade_manager startup reconcile skipped (no DB)")
            return
        try:
            with pg.cursor() as cur:
                startup_reconcile_simulated_trade_for_tenant(
                    cur,
                    _tm_trades_table(),
                    _tm_trades_simulated_table(),
                    _tm_monitor_list_table(),
                    str(effective_tenant_context_for_sql_rewrite().user_no),
                )
            pg.commit()
            log("✅ [SIM TRADE LP] trade_manager startup reconcile completed")
        finally:
            pg.close()
    except Exception as e:
        log(f"⚠️ [SIM TRADE LP] trade_manager startup reconcile failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start APScheduler when FastAPI app starts"""
    _trade_manager_scheduler_shutdown.clear()
    try:
        _scheduler.start()
        threading.Thread(
            target=refresh_all_monitor_cycle_performance,
            kwargs={"window_days": 84},
            daemon=True
        ).start()
        _tm_startup_sim_trade_lp_reconcile()
        start_trading_redis_trade_manager_consumers(_trade_manager_scheduler_shutdown)
        start_trade_manager_positions_updated_subscriber()
    except Exception as e:
        pass
    yield
    try:
        _trade_manager_scheduler_shutdown.set()
    except Exception:
        pass
    try:
        _scheduler.shutdown(wait=False)
    except Exception as e:
        log(f"trade_manager APScheduler shutdown: {e}")

app = FastAPI(lifespan=lifespan)

app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    import os

    port = get_port("trade_manager")
    uvicorn.run(app, host="0.0.0.0", port=port)


