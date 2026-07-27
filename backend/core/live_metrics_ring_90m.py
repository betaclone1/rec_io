"""
Rolling 90-minute PG metrics ring — profile-tied hot-path percentiles for backtesting.

Companion to live_price_ring_90m_* (same ISO-8601 UTC ``timestamp`` join key).
Stores only fields that cannot be reconstructed from the price series alone because
they depend on the analytics profile tables that change over time:

  momentum_percentile, volatility_percentile, movement_percentile,
  momentum_5s_avg, momentum_10s_avg, momentum_30s_avg, momentum_1m_avg,
  momentum_acceleration

Writes are fire-and-forget (ThreadPoolExecutor). Must never block WS / live_state.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("cfbenchmarks_price_watchdog")

_UTC = timezone.utc
_TRACKED = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})
_TABLE_BY_SYMBOL: Dict[str, str] = {
    "BTC": "live_metrics_ring_90m_btc",
    "ETH": "live_metrics_ring_90m_eth",
    "SOL": "live_metrics_ring_90m_sol",
    "XRP": "live_metrics_ring_90m_xrp",
    "DOGE": "live_metrics_ring_90m_doge",
}

_METRIC_KEYS: Tuple[str, ...] = (
    "momentum_percentile",
    "volatility_percentile",
    "movement_percentile",
    "momentum_5s_avg",
    "momentum_10s_avg",
    "momentum_30s_avg",
    "momentum_1m_avg",
    "momentum_acceleration",
)

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def metrics_ring_pg_enabled() -> bool:
    raw = os.getenv("CFBENCHMARKS_METRICS_RING_PG", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def retention_minutes() -> int:
    raw = os.getenv("CFBENCHMARKS_RING_PG_RETENTION_MIN", "90").strip()
    try:
        return max(30, int(raw))
    except (TypeError, ValueError):
        return 90


def _table_for_symbol(symbol: str) -> Optional[str]:
    return _TABLE_BY_SYMBOL.get(str(symbol or "").strip().upper())


def _utc_wall_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    else:
        dt = dt.astimezone(_UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _cutoff_timestamp_utc(minutes: int) -> str:
    return _utc_wall_str(datetime.now(_UTC) - timedelta(minutes=minutes))


def _optional_numeric(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _snapshot_metrics(tick_row: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Copy metric fields off the hot-path row before async handoff."""
    return {k: _optional_numeric(tick_row.get(k)) for k in _METRIC_KEYS}


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            workers = max(1, min(4, int(os.getenv("CFBENCHMARKS_METRICS_RING_PG_WORKERS", "2"))))
            _executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="cfb_metrics_ring_pg",
            )
    return _executor


def shutdown_metrics_ring_executor() -> None:
    global _executor
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None


atexit.register(shutdown_metrics_ring_executor)


def enqueue_metrics_ring_tick(
    symbol: str,
    timestamp: str,
    tick_row: Dict[str, Any],
) -> None:
    """
    Fire-and-forget PG write of profile-tied metrics.

    ``timestamp`` must be the same ISO-8601 UTC string used for the price ring row.
    Never raises; never blocks the caller beyond a thread-pool submit.
    """
    if not metrics_ring_pg_enabled():
        return
    sym = str(symbol or "").strip().upper()
    if sym not in _TRACKED or not timestamp or not isinstance(tick_row, dict):
        return
    snap = _snapshot_metrics(tick_row)
    try:
        _get_executor().submit(_write_metrics_ring_tick_sync, sym, timestamp, snap)
    except Exception as e:
        logger.debug("metrics ring PG enqueue failed %s: %s", sym, e)


def _write_metrics_ring_tick_sync(
    symbol: str,
    timestamp: str,
    metrics: Dict[str, Optional[float]],
) -> None:
    table = _table_for_symbol(symbol)
    if not table:
        return
    try:
        from backend.core.config.database import get_system_postgresql_connection
    except Exception as e:
        logger.debug("metrics ring PG import failed: %s", e)
        return

    conn = None
    try:
        conn = get_system_postgresql_connection()
        if conn is None:
            return
        cutoff = _cutoff_timestamp_utc(retention_minutes())
        cols = ", ".join(["timestamp"] + list(_METRIC_KEYS))
        placeholders = ", ".join(["%s"] * (1 + len(_METRIC_KEYS)))
        updates = ", ".join(f"{k} = EXCLUDED.{k}" for k in _METRIC_KEYS)
        values = [timestamp] + [metrics.get(k) for k in _METRIC_KEYS]
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO live_data.{table} ({cols})
                VALUES ({placeholders})
                ON CONFLICT (timestamp) DO UPDATE SET {updates}
                """,
                values,
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
        logger.debug("metrics ring PG write failed %s: %s", symbol, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
