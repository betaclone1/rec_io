"""
Kalshi orderbook sidecar for market_watchdog_ws.

When MARKET_WATCHDOG_WS_ORDERBOOK_TABLES is enabled and
MARKET_WATCHDOG_WS_ORDERBOOK_DISABLE is not set, maintains per-market_ticker
orderbook tables under live_data (same row shape as the experimental testing tables).
Does not import market_watchdog_ws (avoid cycles); callers pass DB borrow/return hooks.

Real-time orderbook collection is off by default in generated supervisor config
(DISABLE=1). Remove DISABLE and set MARKET_WATCHDOG_WS_ORDERBOOK_TABLES to re-enable.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger("kalshi_live_orderbook_sidecar")

_SCHEMA = "live_data"
_TABLE_PREFIX = "orderbook_kalshi_"
_REGISTRY = f'{_SCHEMA}.kalshi_orderbook_sidecar_registry'
# PostgreSQL identifier length (NAMEDATALEN 64 -> 63 chars)
_MAX_IDENT = 63
_PREFIX_LEN = len(_TABLE_PREFIX)
_MAX_SUFFIX = _MAX_IDENT - _PREFIX_LEN

_ORDERBOOK_DB_LOCK = threading.Lock()


def orderbook_sidecar_enabled() -> bool:
    off = os.getenv("MARKET_WATCHDOG_WS_ORDERBOOK_DISABLE", "").strip().lower()
    if off in ("1", "true", "yes", "on"):
        return False
    v = os.getenv("MARKET_WATCHDOG_WS_ORDERBOOK_TABLES", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _sanitize_suffix(market_ticker: str) -> str:
    t = re.sub(r"[^A-Za-z0-9_]+", "_", str(market_ticker).strip())
    t = re.sub(r"_+", "_", t).strip("_").lower()
    if not t:
        t = "unknown"
    if len(t) > _MAX_SUFFIX:
        t = t[:_MAX_SUFFIX]
    if not re.fullmatch(r"[a-z0-9_]+", t):
        t = "invalid_ticker"
    return t


def physical_table_name(market_ticker: str) -> str:
    return f"{_TABLE_PREFIX}{_sanitize_suffix(market_ticker)}"


def quoted_table(market_ticker: str) -> str:
    name = physical_table_name(market_ticker)
    return f'{_SCHEMA}."{name}"'


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        raise InvalidOperation("None")
    return Decimal(str(value).strip())


def _ensure_table_sql(table_sql: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table_sql} (
            side TEXT NOT NULL,
            price_dollars NUMERIC(18,6) NOT NULL,
            size_fp NUMERIC(18,2) NOT NULL,
            seq BIGINT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (side, price_dollars)
        )
        """


def ensure_table(cur, market_ticker: str, market_interval: str) -> None:
    tsql = quoted_table(market_ticker)
    cur.execute(_ensure_table_sql(tsql))
    phys = physical_table_name(market_ticker)
    cur.execute(
        f"""
        INSERT INTO {_REGISTRY} (market_ticker, table_name, market_interval)
        VALUES (%s, %s, %s)
        ON CONFLICT (market_ticker) DO UPDATE SET
            table_name = EXCLUDED.table_name,
            market_interval = EXCLUDED.market_interval
        """,
        (str(market_ticker).strip(), phys, str(market_interval).strip().lower()),
    )


def apply_snapshot(cur, market_ticker: str, snapshot_msg: dict[str, Any], seq: Optional[int]) -> int:
    levels: list[tuple[str, Decimal, Decimal]] = []
    for side_key, side_name in (("yes_dollars_fp", "yes"), ("no_dollars_fp", "no")):
        arr = snapshot_msg.get(side_key) or []
        if not isinstance(arr, list):
            continue
        for level in arr:
            if not isinstance(level, list) or len(level) < 2:
                continue
            try:
                price = _to_decimal(level[0])
                size = _to_decimal(level[1])
            except Exception:
                continue
            levels.append((side_name, price, size))

    tsql = quoted_table(market_ticker)
    cur.execute(f"DELETE FROM {tsql}")
    if levels:
        cur.executemany(
            f"""
            INSERT INTO {tsql}
            (side, price_dollars, size_fp, seq, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            [(s, p, sz, seq) for (s, p, sz) in levels],
        )
    return len(levels)


def apply_delta(cur, market_ticker: str, delta_msg: dict[str, Any], seq: Optional[int]) -> None:
    side = str(delta_msg.get("side") or "").strip().lower()
    if side not in ("yes", "no"):
        return
    try:
        price = _to_decimal(delta_msg.get("price_dollars"))
        delta = _to_decimal(delta_msg.get("delta_fp"))
    except Exception:
        return

    tsql = quoted_table(market_ticker)
    cur.execute(
        f"""
        INSERT INTO {tsql} AS ob
        (side, price_dollars, size_fp, seq, updated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (side, price_dollars)
        DO UPDATE SET
            size_fp = ob.size_fp + EXCLUDED.size_fp,
            seq = EXCLUDED.seq,
            updated_at = NOW()
        """,
        (side, price, delta, seq),
    )
    cur.execute(
        f"""
        DELETE FROM {tsql}
        WHERE side = %s AND price_dollars = %s AND size_fp <= 0
        """,
        (side, price),
    )


def drop_table_for_ticker(cur, market_ticker: str) -> None:
    mt = str(market_ticker).strip()
    if not mt:
        return
    phys = physical_table_name(mt)
    cur.execute(f'DROP TABLE IF EXISTS {_SCHEMA}."{phys}" CASCADE')
    cur.execute(f"DELETE FROM {_REGISTRY} WHERE market_ticker = %s", (mt,))


BorrowConn = Callable[[str, float], Any]
ReturnConn = Callable[[Any], None]


def handle_ws_orderbook_message_sync(
    data: dict[str, Any],
    *,
    market_interval: str,
    rolling: threading.Event,
    borrow_conn: BorrowConn,
    return_conn: ReturnConn,
) -> None:
    if not orderbook_sidecar_enabled():
        return
    if rolling.is_set():
        return
    dtype = data.get("type")
    if dtype not in ("orderbook_snapshot", "orderbook_delta"):
        return
    msg = data.get("msg") or {}
    if not isinstance(msg, dict):
        return
    mt = str(msg.get("market_ticker") or "").strip()
    if not mt:
        return
    seq = data.get("seq")

    with _ORDERBOOK_DB_LOCK:
        conn = borrow_conn("orderbook_sidecar", 25.0)
        if not conn:
            return
        try:
            cur = conn.cursor()
            ensure_table(cur, mt, market_interval)
            if dtype == "orderbook_snapshot":
                n = apply_snapshot(cur, mt, msg, seq)
                logger.info(
                    "orderbook sidecar snapshot market_ticker=%s levels=%s seq=%s",
                    mt,
                    n,
                    seq,
                )
            else:
                apply_delta(cur, mt, msg, seq)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("orderbook sidecar ingest failed market_ticker=%s type=%s", mt, dtype)
        finally:
            return_conn(conn)


def drop_on_lifecycle_final_sync(
    lc_msg: dict[str, Any],
    *,
    borrow_conn: BorrowConn,
    return_conn: ReturnConn,
) -> None:
    if not orderbook_sidecar_enabled():
        return
    mt = str(lc_msg.get("market_ticker") or "").strip()
    if not mt:
        return
    et = lc_msg.get("event_type")
    if et not in ("determined", "settled"):
        return
    result = lc_msg.get("result")
    if result is None or str(result).strip() == "":
        return
    with _ORDERBOOK_DB_LOCK:
        conn = borrow_conn("orderbook_sidecar_lifecycle", 25.0)
        if not conn:
            return
        try:
            cur = conn.cursor()
            drop_table_for_ticker(cur, mt)
            conn.commit()
            logger.info(
                "orderbook sidecar dropped table after lifecycle market_ticker=%s event_type=%s",
                mt,
                et,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("orderbook sidecar lifecycle drop failed market_ticker=%s", mt)
        finally:
            return_conn(conn)


def prune_orderbook_sidecar_keep_only_sync(
    keep_tickers: Iterable[str],
    market_interval: str,
    *,
    borrow_conn: BorrowConn,
    return_conn: ReturnConn,
) -> None:
    """Drop per-ticker orderbook tables for this ``market_interval`` that are not in ``keep_tickers``.

    ``keep_tickers`` should match ``_orderbook_subscription_tickers`` (current-event cycle only).
    """
    if not orderbook_sidecar_enabled():
        return
    keep = {str(x).strip() for x in keep_tickers if str(x).strip()}
    mi = str(market_interval or "").strip().lower()
    if not mi:
        return
    with _ORDERBOOK_DB_LOCK:
        conn = borrow_conn("orderbook_sidecar_prune_keep", 30.0)
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT market_ticker FROM {_REGISTRY}
                WHERE LOWER(TRIM(market_interval::text)) = %s
                """,
                (mi,),
            )
            dropped = 0
            for (mt,) in cur.fetchall() or ():
                mts = str(mt).strip()
                if mts and mts not in keep:
                    drop_table_for_ticker(cur, mts)
                    dropped += 1
            conn.commit()
            if dropped:
                logger.info(
                    "orderbook sidecar pruned %s stale table(s) (interval=%s keep_n=%s)",
                    dropped,
                    mi,
                    len(keep),
                )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("orderbook sidecar keep-only prune failed interval=%s", mi)
        finally:
            return_conn(conn)
