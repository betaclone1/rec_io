"""
Rolling 90-minute PG price ring for CFB watchdog startup hydration.

Writes are async (ThreadPoolExecutor) and must not block WS / live_state hot path.
Reads run once at process startup to populate symbol_tick_buffer (+ CFB momentum replay).
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger("cfbenchmarks_price_watchdog")

_EST = ZoneInfo("America/New_York")
_TRACKED = frozenset({"BTC", "ETH", "SOL", "XRP"})
_TABLE_BY_SYMBOL: Dict[str, str] = {
    "BTC": "live_price_ring_90m_btc",
    "ETH": "live_price_ring_90m_eth",
    "SOL": "live_price_ring_90m_sol",
    "XRP": "live_price_ring_90m_xrp",
}

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def ring_pg_enabled() -> bool:
    raw = os.getenv("CFBENCHMARKS_RING_PG", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def retention_minutes() -> int:
    raw = os.getenv("CFBENCHMARKS_RING_PG_RETENTION_MIN", "90").strip()
    try:
        return max(30, int(raw))
    except (TypeError, ValueError):
        return 90


def _table_for_symbol(symbol: str) -> Optional[str]:
    return _TABLE_BY_SYMBOL.get(str(symbol or "").strip().upper())


def _cutoff_timestamp_est(minutes: int) -> str:
    dt = datetime.now(_EST) - timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _est_wall_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_EST)
    else:
        dt = dt.astimezone(_EST)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def expiration_symbol_close_window_sec() -> int:
    """Seconds of CFB ring ticks before expiry to average for ``symbol_close``."""
    raw = os.getenv("CFB_EXPIRATION_SYMBOL_CLOSE_WINDOW_SEC", "60").strip()
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 60


def avg_cfb_spot_in_est_window(
    symbol: str,
    window_start_est: datetime,
    window_end_est: datetime,
) -> Optional[float]:
    """
    Mean CFB spot (``price`` column) for ticks with ``start < timestamp <= end`` (EST wall strings).
    """
    table = _table_for_symbol(symbol)
    if not table or window_end_est is None or window_start_est is None:
        return None
    if not ring_pg_enabled():
        return None
    start_s = _est_wall_str(window_start_est)
    end_s = _est_wall_str(window_end_est)
    if start_s > end_s:
        return None
    try:
        from backend.core.config.database import get_system_postgresql_connection
    except Exception:
        return None

    conn = None
    try:
        conn = get_system_postgresql_connection()
        if conn is None:
            return None
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT AVG(price::numeric), COUNT(*)::bigint
                FROM live_data.{table}
                WHERE timestamp > %s
                  AND timestamp <= %s
                """,
                (start_s, end_s),
            )
            row = cur.fetchone()
        if not row or int(row[1] or 0) < 1 or row[0] is None:
            return None
        return float(row[0])
    except Exception as e:
        logger.debug("ring avg in window failed %s [%s,%s]: %s", symbol, start_s, end_s, e)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def avg_cfb_spot_60s_before_expiration(
    symbol: str,
    expiration_est: datetime,
    *,
    window_sec: Optional[int] = None,
) -> Optional[float]:
    """Average CFB spot ticks in (expiry - window_sec, expiry] (default 60s)."""
    if expiration_est is None:
        return None
    if expiration_est.tzinfo is None:
        exp = expiration_est.replace(tzinfo=_EST)
    else:
        exp = expiration_est.astimezone(_EST)
    sec = int(window_sec if window_sec is not None else expiration_symbol_close_window_sec())
    start = exp - timedelta(seconds=sec)
    return avg_cfb_spot_in_est_window(symbol, start, exp)


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            workers = max(1, min(4, int(os.getenv("CFBENCHMARKS_RING_PG_WORKERS", "2"))))
            _executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="cfb_ring_pg",
            )
    return _executor


def shutdown_ring_executor() -> None:
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None


atexit.register(shutdown_ring_executor)


def enqueue_ring_tick(symbol: str, timestamp: str, price: float) -> None:
    """Fire-and-forget PG write; never raises to caller."""
    if not ring_pg_enabled():
        return
    sym = str(symbol or "").strip().upper()
    if sym not in _TRACKED or not timestamp or price is None:
        return
    try:
        px = float(price)
    except (TypeError, ValueError):
        return
    try:
        _get_executor().submit(_write_ring_tick_sync, sym, timestamp, px)
    except Exception as e:
        logger.debug("ring PG enqueue failed %s: %s", sym, e)


def _write_ring_tick_sync(symbol: str, timestamp: str, price: float) -> None:
    table = _table_for_symbol(symbol)
    if not table:
        return
    try:
        from backend.core.config.database import get_system_postgresql_connection
    except Exception as e:
        logger.debug("ring PG import failed: %s", e)
        return

    conn = None
    try:
        conn = get_system_postgresql_connection()
        if conn is None:
            return
        cutoff = _cutoff_timestamp_est(retention_minutes())
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO live_data.{table} (timestamp, price)
                VALUES (%s, %s)
                ON CONFLICT (timestamp) DO UPDATE SET price = EXCLUDED.price
                """,
                (timestamp, price),
            )
            cur.execute(
                f"DELETE FROM live_data.{table} WHERE timestamp < %s",
                (cutoff,),
            )
        conn.commit()
    except Exception as e:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.debug("ring PG write failed %s: %s", symbol, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _load_ring_rows(symbol: str) -> List[Tuple[str, float]]:
    table = _table_for_symbol(symbol)
    if not table:
        return []
    try:
        from backend.core.config.database import get_system_postgresql_connection
    except Exception:
        return []

    conn = None
    try:
        conn = get_system_postgresql_connection()
        if conn is None:
            return []
        cutoff = _cutoff_timestamp_est(retention_minutes())
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT timestamp, price
                FROM live_data.{table}
                WHERE timestamp >= %s
                ORDER BY timestamp ASC
                """,
                (cutoff,),
            )
            rows = cur.fetchall()
        return [(str(r[0]), float(r[1])) for r in rows if r and r[0] is not None]
    except Exception as e:
        logger.warning("ring PG load failed %s: %s", symbol, e)
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def hydrate_startup_buffers(symbols: List[str]) -> None:
    """
    Populate symbol_tick_buffer and replay CFB momentum deque from ring tables.
    Called once before the WebSocket loop.
    """
    from backend.core.cfbenchmarks_tick_metrics import replay_cfb_momentum_from_price_rows
    from backend.core.symbol_tick_buffer import append_tick

    for sym in symbols:
        s = str(sym or "").strip().upper()
        if s not in _TRACKED:
            continue
        rows = _load_ring_rows(s)
        if not rows:
            logger.info("ring hydrate %s: no rows in PG", s)
            continue
        for ts, px in rows:
            append_tick(s, ts, px)
        replay_cfb_momentum_from_price_rows(s, rows)
        logger.info("ring hydrate %s: %s ticks from PG", s, len(rows))
