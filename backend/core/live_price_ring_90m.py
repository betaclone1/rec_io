"""
Rolling 90-minute PG price ring for CFB watchdog startup hydration.

Writes are handed to ``live_ring_pg_writer`` (single background thread, batched)
and must never touch PG on the WS / live_state hot path.
Reads run once at process startup to populate symbol_tick_buffer (+ CFB momentum replay).

Ring ``timestamp`` values are ISO-8601 UTC with a ``Z`` suffix
(``YYYY-MM-DDTHH:MM:SS.mmmZ``), derived from CFB ``data.time`` (unix ms).
Hot-path / in-memory buffers remain EST.

``trade_manager`` reads ``avg_60s`` from here for ``symbol_close``: the exact
quarter-hour tick at expiration (``avg_60s_at_quarter_close``) and the tick as of
the close instant for early closes (``avg_60s_as_of``).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

from backend.core.live_ring_pg_writer import submit_upsert

logger = logging.getLogger("cfbenchmarks_price_watchdog")

_EST = ZoneInfo("America/New_York")
_UTC = timezone.utc
_TRACKED = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})
_TABLE_BY_SYMBOL: Dict[str, str] = {
    "BTC": "live_price_ring_90m_btc",
    "ETH": "live_price_ring_90m_eth",
    "SOL": "live_price_ring_90m_sol",
    "XRP": "live_price_ring_90m_xrp",
    "DOGE": "live_price_ring_90m_doge",
}


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


def _utc_wall_str(dt: datetime) -> str:
    """ISO-8601 UTC with millisecond precision and ``Z`` suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    else:
        dt = dt.astimezone(_UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _cutoff_timestamp_utc(minutes: int) -> str:
    return _utc_wall_str(datetime.now(_UTC) - timedelta(minutes=minutes))


def ring_timestamp_utc_from_source_ms(source_ts_ms: Any) -> Optional[str]:
    """Format CFB ``data.time`` (unix ms) as ISO-8601 UTC for ring PG."""
    if source_ts_ms is None:
        return None
    try:
        ms = int(source_ts_ms)
    except (TypeError, ValueError):
        return None
    return _utc_wall_str(datetime.fromtimestamp(ms / 1000.0, tz=_UTC))


def is_quarter_close_ring_timestamp(timestamp: str) -> bool:
    """True for exact ``:00`` / ``:15`` / ``:30`` / ``:45`` UTC seconds (settlement ticks)."""
    dt = _parse_ring_timestamp_utc(timestamp)
    if dt is None:
        return False
    return dt.second == 0 and dt.microsecond == 0 and (dt.minute % 15) == 0


def _parse_ring_timestamp_utc(ts: str) -> Optional[datetime]:
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_UTC)
        return dt.astimezone(_UTC)
    except (TypeError, ValueError):
        return None


def utc_wall_to_est_wall(ts_utc: str) -> str:
    """Convert a ring ISO UTC string to EST wall for in-memory buffer hydrate."""
    dt = _parse_ring_timestamp_utc(ts_utc)
    if dt is None:
        return str(ts_utc or "")
    est = dt.astimezone(_EST)
    ms = est.microsecond // 1000
    base = est.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ms:03d}" if ms else base


def avg_60s_at_quarter_close(
    symbol: str,
    expiration: datetime,
    *,
    wait_seconds: float = 0.0,
    poll_interval: float = 0.25,
) -> Optional[float]:
    """
    CFB ``avg_60s`` on the exact contract close second (``:00`` / ``:15`` / ``:30`` / ``:45``).

    That tick is always written into the ring; the expiry cron often fires at the
    same second, so callers may pass ``wait_seconds`` to poll until it appears.
    No substitute tick — only the exact close second.
    """
    import time

    table = _table_for_symbol(symbol)
    if not table or expiration is None:
        return None
    if not ring_pg_enabled():
        return None

    if expiration.tzinfo is None:
        exp = expiration.replace(tzinfo=_EST)
    else:
        exp = expiration
    exp_utc = exp.astimezone(_UTC).replace(microsecond=0)
    prefix = exp_utc.strftime("%Y-%m-%dT%H:%M:%S")

    try:
        from backend.core.config.database import get_system_postgresql_connection
    except Exception:
        return None

    deadline = time.monotonic() + max(0.0, float(wait_seconds or 0.0))
    interval = max(0.05, float(poll_interval or 0.25))

    while True:
        conn = None
        try:
            conn = get_system_postgresql_connection()
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT avg_60s::numeric
                    FROM live_data.{table}
                    WHERE timestamp LIKE %s
                      AND avg_60s IS NOT NULL
                    ORDER BY timestamp ASC
                    LIMIT 1
                    """,
                    (prefix + "%",),
                )
                row = cur.fetchone()
            if row and row[0] is not None:
                return float(row[0])
        except Exception as e:
            logger.debug(
                "ring avg_60s at quarter close failed %s prefix=%s: %s",
                symbol,
                prefix,
                e,
            )
            return None
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def avg_60s_as_of(
    symbol: str,
    when: datetime,
    *,
    max_lookback_seconds: float = 15.0,
) -> Optional[float]:
    """
    CFB ``avg_60s`` sampled as of ``when``: newest ring tick at or before that
    instant, no older than ``max_lookback_seconds``.

    Early (pre-expiration) closes land on arbitrary seconds, so there is no exact
    settlement tick to demand as there is at ``:00`` / ``:15`` / ``:30`` / ``:45``.
    An empty window returns None so callers leave ``symbol_close`` NULL for the
    repair pass — never a spot substitute.
    """
    table = _table_for_symbol(symbol)
    if not table or when is None:
        return None
    if not ring_pg_enabled():
        return None

    at = when.replace(tzinfo=_EST) if when.tzinfo is None else when
    newest = _utc_wall_str(at)
    oldest = _utc_wall_str(at - timedelta(seconds=max(0.0, float(max_lookback_seconds))))

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
                SELECT avg_60s::numeric
                FROM live_data.{table}
                WHERE timestamp <= %s
                  AND timestamp >= %s
                  AND avg_60s IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (newest, oldest),
            )
            row = cur.fetchone()
        if row and row[0] is not None:
            return float(row[0])
    except Exception as e:
        logger.debug("ring avg_60s as-of failed %s at=%s: %s", symbol, newest, e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return None


def decimal_from_cfb_value(raw: Any) -> Optional[Decimal]:
    """
    Preserve CFB API decimal specificity (string → Decimal).

    Avoids ``float()`` so Postgres NUMERIC receives the exact digit string.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, float):
        # Last resort if a caller already floated; prefer string inputs.
        return Decimal(str(raw))
    s = str(raw).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def avg_value_from_cfb_obj(obj: Any) -> Optional[Decimal]:
    """Extract ``.value`` from Kalshi windowed-average metadata as Decimal."""
    if not isinstance(obj, dict):
        return None
    return decimal_from_cfb_value(obj.get("value"))


def enqueue_ring_tick(
    symbol: str,
    timestamp: str,
    price: Union[Decimal, str, int, float],
    *,
    avg_60s: Optional[Union[Decimal, str, int, float]] = None,
    last_60s_windowed_average_15min: Optional[Union[Decimal, str, int, float]] = None,
) -> None:
    """
    Hand one ring row to the off-loop writer. ``timestamp`` must be ISO-8601 UTC
    (``…Z``). Touches no database and never blocks the caller.
    """
    if not ring_pg_enabled():
        return
    sym = str(symbol or "").strip().upper()
    table = _table_for_symbol(sym)
    if not table or not timestamp or price is None:
        return
    px = decimal_from_cfb_value(price)
    if px is None:
        return
    submit_upsert(
        table,
        ("timestamp", "price", "avg_60s", "last_60s_windowed_average_15min"),
        (
            timestamp,
            px,
            decimal_from_cfb_value(avg_60s),
            decimal_from_cfb_value(last_60s_windowed_average_15min),
        ),
    )


def _load_ring_rows(symbol: str) -> List[Tuple[str, float]]:
    """Load ring rows as (EST wall timestamp, price) for in-memory buffer hydrate."""
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
        cutoff = _cutoff_timestamp_utc(retention_minutes())
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
        out: List[Tuple[str, float]] = []
        for r in rows:
            if not r or r[0] is None or r[1] is None:
                continue
            out.append((utc_wall_to_est_wall(str(r[0])), float(r[1])))
        return out
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
    Called once before the WebSocket loop. Ring UTC timestamps are converted to EST.
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
