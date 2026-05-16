"""
Kalshi orderbook sidecar for market_watchdog_ws.

When MARKET_WATCHDOG_WS_ORDERBOOK_TABLES is enabled and
MARKET_WATCHDOG_WS_ORDERBOOK_DISABLE is not set, subscribes and applies
orderbook_snapshot / orderbook_delta updates.

**Primary path (default):** in-memory books plus a Redis projection keyed by
``trade_monitor_orderbook_redis_key()`` so ``read_api`` / trade-monitor can read
depth without touching PostgreSQL.

**Optional PostgreSQL:** set MARKET_WATCHDOG_WS_ORDERBOOK_PG=1 to also maintain
``live_data.orderbook_kalshi_*`` (legacy NOTIFY / DB readers).

Does not import market_watchdog_ws (avoid cycles); callers pass DB borrow/return hooks.

Supervisor: generate_unified_supervisor_config sets MARKET_WATCHDOG_WS_ORDERBOOK_TABLES=1 by default.
Set MARKET_WATCHDOG_WS_ORDERBOOK_DISABLE=1 to turn the sidecar off.
"""

from __future__ import annotations

import json
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

_ORDERBOOK_LEVELS_REDIS_PREFIX = os.getenv(
    "TRADE_MONITOR_ORDERBOOK_REDIS_PREFIX",
    "trade_monitor:orderbook_levels:v1:",
).strip() or "trade_monitor:orderbook_levels:v1:"

# PostgreSQL identifier length (NAMEDATALEN 64 -> 63 chars)
_MAX_IDENT = 63
_PREFIX_LEN = len(_TABLE_PREFIX)
_MAX_SUFFIX = _MAX_IDENT - _PREFIX_LEN

_PRICE_Q = Decimal("0.000001")
_SIZE_Q = Decimal("0.01")

_ORDERBOOK_SIDE_LOCK = threading.Lock()

# market_ticker -> {"yes": {price_str: size_str}, "no": {...}, "seq": Optional[int]}
_MEMORY_BOOKS: dict[str, dict[str, Any]] = {}


def orderbook_sidecar_enabled() -> bool:
    off = os.getenv("MARKET_WATCHDOG_WS_ORDERBOOK_DISABLE", "").strip().lower()
    if off in ("1", "true", "yes", "on"):
        return False
    v = os.getenv("MARKET_WATCHDOG_WS_ORDERBOOK_TABLES", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def orderbook_pg_writes_enabled() -> bool:
    """When True, mirror orderbook state into ``live_data.orderbook_kalshi_*``."""
    if not orderbook_sidecar_enabled():
        return False
    v = os.getenv("MARKET_WATCHDOG_WS_ORDERBOOK_PG", "").strip().lower()
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


def trade_monitor_orderbook_redis_key(market_ticker: str) -> str:
    """Redis key for JSON orderbook levels (YES/NO price ladders)."""
    return f"{_ORDERBOOK_LEVELS_REDIS_PREFIX}{_sanitize_suffix(market_ticker)}"


def physical_table_name(market_ticker: str) -> str:
    return f"{_TABLE_PREFIX}{_sanitize_suffix(market_ticker)}"


def quoted_table(market_ticker: str) -> str:
    name = physical_table_name(market_ticker)
    return f'{_SCHEMA}."{name}"'


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        raise InvalidOperation("None")
    return Decimal(str(value).strip())


def _fmt_price_key(p: Decimal) -> str:
    return str(p.quantize(_PRICE_Q))


def _fmt_size_val(sz: Decimal) -> str:
    return str(sz.quantize(_SIZE_Q))


def _redis_ttl_sec() -> int:
    raw = os.getenv("TRADE_MONITOR_ORDERBOOK_REDIS_TTL_SEC", "21600").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 21600


def _parse_snapshot_levels(snapshot_msg: dict[str, Any]) -> list[tuple[str, Decimal, Decimal]]:
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
    return levels


def _apply_snapshot_to_memory(market_ticker: str, snapshot_msg: dict[str, Any], seq: Optional[int]) -> int:
    mt = str(market_ticker).strip()
    levels = _parse_snapshot_levels(snapshot_msg)
    yes: dict[str, str] = {}
    no: dict[str, str] = {}
    for side_name, price, size in levels:
        pk = _fmt_price_key(price)
        sv = _fmt_size_val(size)
        if side_name == "yes":
            yes[pk] = sv
        else:
            no[pk] = sv
    _MEMORY_BOOKS[mt] = {"yes": yes, "no": no, "seq": seq}
    return len(levels)


def _apply_delta_to_memory(market_ticker: str, delta_msg: dict[str, Any], seq: Optional[int]) -> None:
    mt = str(market_ticker).strip()
    side = str(delta_msg.get("side") or "").strip().lower()
    if side not in ("yes", "no"):
        return
    try:
        price = _to_decimal(delta_msg.get("price_dollars"))
        delta = _to_decimal(delta_msg.get("delta_fp"))
    except Exception:
        return
    pk = _fmt_price_key(price)
    book = _MEMORY_BOOKS.setdefault(mt, {"yes": {}, "no": {}, "seq": None})
    side_book: dict[str, str] = book[side]
    cur = Decimal("0")
    if pk in side_book:
        try:
            cur = Decimal(side_book[pk])
        except Exception:
            cur = Decimal("0")
    new_sz = cur + delta
    if new_sz <= 0:
        side_book.pop(pk, None)
    else:
        side_book[pk] = _fmt_size_val(new_sz)
    book["seq"] = seq


def _publish_memory_book_to_redis(market_ticker: str) -> None:
    mt = str(market_ticker).strip()
    book = _MEMORY_BOOKS.get(mt)
    if not book:
        return
    try:
        from backend.core.trading_redis_comms import redis_client_optional
    except Exception:
        return
    r = redis_client_optional()
    if not r:
        return
    payload = {
        "v": 1,
        "market_ticker": mt,
        "yes": dict(book.get("yes") or {}),
        "no": dict(book.get("no") or {}),
        "seq": book.get("seq"),
    }
    key = trade_monitor_orderbook_redis_key(mt)
    try:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        r.setex(key, _redis_ttl_sec(), raw)
    except Exception:
        logger.exception("orderbook redis publish failed market_ticker=%s", mt)


def _delete_redis_levels(market_ticker: str) -> None:
    mt = str(market_ticker).strip()
    if not mt:
        return
    try:
        from backend.core.trading_redis_comms import redis_client_optional
    except Exception:
        return
    r = redis_client_optional()
    if not r:
        return
    try:
        r.delete(trade_monitor_orderbook_redis_key(mt))
    except Exception:
        logger.exception("orderbook redis delete failed market_ticker=%s", mt)


def clear_orderbook_memory_and_redis(market_ticker: str) -> None:
    """Drop in-memory ladder and Redis projection for one ticker (lifecycle / prune)."""
    mt = str(market_ticker).strip()
    if not mt:
        return
    _MEMORY_BOOKS.pop(mt, None)
    _delete_redis_levels(mt)


def clear_orderbook_memory_for_tests() -> None:
    """Test helper: empty all in-memory books (does not touch Redis)."""
    _MEMORY_BOOKS.clear()


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
    levels = _parse_snapshot_levels(snapshot_msg)
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

    with _ORDERBOOK_SIDE_LOCK:
        if dtype == "orderbook_snapshot":
            n = _apply_snapshot_to_memory(mt, msg, seq)
            logger.info(
                "orderbook sidecar snapshot market_ticker=%s levels=%s seq=%s",
                mt,
                n,
                seq,
            )
        else:
            _apply_delta_to_memory(mt, msg, seq)

        _publish_memory_book_to_redis(mt)

        if not orderbook_pg_writes_enabled():
            return

        conn = borrow_conn("orderbook_sidecar_pg", 25.0)
        if not conn:
            return
        try:
            cur = conn.cursor()
            ensure_table(cur, mt, market_interval)
            if dtype == "orderbook_snapshot":
                apply_snapshot(cur, mt, msg, seq)
            else:
                apply_delta(cur, mt, msg, seq)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("orderbook sidecar PG ingest failed market_ticker=%s type=%s", mt, dtype)
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

    with _ORDERBOOK_SIDE_LOCK:
        clear_orderbook_memory_and_redis(mt)
        if not orderbook_pg_writes_enabled():
            logger.info(
                "orderbook sidecar cleared cache after lifecycle market_ticker=%s event_type=%s",
                mt,
                et,
            )
            return
        conn = borrow_conn("orderbook_sidecar_lifecycle", 25.0)
        if not conn:
            return
        try:
            cur = conn.cursor()
            drop_table_for_ticker(cur, mt)
            conn.commit()
            logger.info(
                "orderbook sidecar dropped PG table after lifecycle market_ticker=%s event_type=%s",
                mt,
                et,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("orderbook sidecar lifecycle PG drop failed market_ticker=%s", mt)
        finally:
            return_conn(conn)


def prune_orderbook_sidecar_keep_only_sync(
    keep_tickers: Iterable[str],
    market_interval: str,
    *,
    borrow_conn: BorrowConn,
    return_conn: ReturnConn,
) -> None:
    """Evict stale tickers from memory/Redis; optionally drop PG tables via registry."""
    if not orderbook_sidecar_enabled():
        return
    keep = {str(x).strip() for x in keep_tickers if str(x).strip()}
    mi = str(market_interval or "").strip().lower()
    if not mi:
        return

    with _ORDERBOOK_SIDE_LOCK:
        dropped_memory = 0
        for mt in list(_MEMORY_BOOKS.keys()):
            mts = str(mt).strip()
            if mts and mts not in keep:
                clear_orderbook_memory_and_redis(mts)
                dropped_memory += 1
        if dropped_memory:
            logger.info(
                "orderbook sidecar memory/redis pruned %s ticker(s) (interval=%s keep_n=%s)",
                dropped_memory,
                mi,
                len(keep),
            )

        if not orderbook_pg_writes_enabled():
            return

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
                    "orderbook sidecar PG pruned %s stale table(s) (interval=%s keep_n=%s)",
                    dropped,
                    mi,
                    len(keep),
                )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.exception("orderbook sidecar PG keep-only prune failed interval=%s", mi)
        finally:
            return_conn(conn)
