"""
Off-loop Postgres writer for the 90m backtesting rings.

The CFB WebSocket loop is system critical: it must never open a Postgres
connection, never wait on a commit, and never spawn a thread. Producers hand
rows to :func:`submit_upsert`, which only touches an in-memory queue. One
background thread owns a single long-lived connection, batches upserts per
table, and prunes on a timer instead of once per tick.

Ring rows are backtesting input and are allowed to lag. If the queue is full or
the database is unreachable the rows are dropped and logged — nothing is
substituted, and the live feed is never slowed down to save them.

Row contract: ``columns[0]`` must be ``timestamp`` and must be the ``ON
CONFLICT`` key for the target table.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("cfbenchmarks_price_watchdog")

_UTC = timezone.utc

# (table, columns) -> {timestamp: values}
_BatchKey = Tuple[str, Tuple[str, ...]]
_Item = Tuple[str, Tuple[str, ...], Tuple[Any, ...]]

_q: Optional["queue.Queue[Optional[_Item]]"] = None
_thread: Optional[threading.Thread] = None
_lock = threading.Lock()
_drain_done = threading.Event()

_dropped = 0
_last_drop_log_mono = 0.0


def _int_env(name: str, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)).strip()))
    except (TypeError, ValueError):
        return default


def queue_max() -> int:
    return _int_env("CFBENCHMARKS_RING_PG_QUEUE_MAX", 100_000, minimum=1_000)


def batch_max() -> int:
    return _int_env("CFBENCHMARKS_RING_PG_BATCH_MAX", 500, minimum=1)


def prune_interval_sec() -> int:
    return _int_env("CFBENCHMARKS_RING_PG_PRUNE_SEC", 60, minimum=5)


def retention_minutes() -> int:
    return _int_env("CFBENCHMARKS_RING_PG_RETENTION_MIN", 90, minimum=30)


def _cutoff_timestamp_utc() -> str:
    dt = datetime.now(_UTC) - timedelta(minutes=retention_minutes())
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _get_queue() -> "queue.Queue[Optional[_Item]]":
    global _q, _thread
    with _lock:
        if _q is None:
            _q = queue.Queue(maxsize=queue_max())
        if _thread is None or not _thread.is_alive():
            _drain_done.clear()
            _thread = threading.Thread(
                target=_writer_loop,
                name="live_ring_pg",
                daemon=True,
            )
            _thread.start()
        return _q


def submit_upsert(
    table: str,
    columns: Sequence[str],
    values: Sequence[Any],
) -> None:
    """
    Queue one ring row for the background writer. Never blocks, never raises.

    ``table`` is the unqualified ``live_data`` table name. ``columns[0]`` must be
    ``timestamp``; rows sharing a timestamp collapse to the last one in a batch.
    """
    if not table or not columns or len(columns) != len(values):
        return
    try:
        _get_queue().put_nowait((str(table), tuple(columns), tuple(values)))
    except queue.Full:
        _note_drop(1)
    except Exception as e:
        logger.debug("ring PG submit failed %s: %s", table, e)


def _note_drop(count: int) -> None:
    global _dropped, _last_drop_log_mono
    _dropped += count
    now = time.monotonic()
    if now - _last_drop_log_mono < 10.0:
        return
    _last_drop_log_mono = now
    logger.warning(
        "ring PG writer dropped %s rows (queue full, depth=%s); "
        "backtesting rings will have gaps",
        _dropped,
        _q.qsize() if _q is not None else 0,
    )


def queue_depth() -> int:
    return _q.qsize() if _q is not None else 0


def dropped_rows() -> int:
    return _dropped


def _system_conn():
    try:
        from backend.core.config.database import get_system_postgresql_connection
    except Exception as e:
        logger.debug("ring PG import failed: %s", e)
        return None
    try:
        return get_system_postgresql_connection()
    except Exception as e:
        logger.warning("ring PG connect failed: %s", e)
        return None


def _close(conn) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass


def _collect() -> Tuple[List[_Item], bool]:
    """Block for the next row, then take everything already queued."""
    q = _q
    if q is None:
        return [], False
    items: List[_Item] = []
    stop = False
    try:
        first = q.get(timeout=1.0)
    except queue.Empty:
        return [], False
    if first is None:
        return [], True
    items.append(first)
    limit = batch_max()
    while len(items) < limit:
        try:
            nxt = q.get_nowait()
        except queue.Empty:
            break
        if nxt is None:
            stop = True
            break
        items.append(nxt)
    return items, stop


def _group(items: List[_Item]) -> Dict[_BatchKey, Dict[Any, Tuple[Any, ...]]]:
    grouped: Dict[_BatchKey, Dict[Any, Tuple[Any, ...]]] = {}
    for table, columns, values in items:
        grouped.setdefault((table, columns), {})[values[0]] = values
    return grouped


def _flush(conn, items: List[_Item]):
    try:
        from psycopg2.extras import execute_values
    except Exception as e:
        logger.warning("ring PG psycopg2 unavailable (%s rows dropped): %s", len(items), e)
        return conn

    grouped = _group(items)
    if conn is None or getattr(conn, "closed", 1):
        conn = _system_conn()
    if conn is None:
        _note_drop(len(items))
        return None
    try:
        with conn.cursor() as cur:
            for (table, columns), rows in grouped.items():
                updates = ", ".join(
                    f"{c} = EXCLUDED.{c}" for c in columns if c != "timestamp"
                )
                sql = (
                    f"INSERT INTO live_data.{table} ({', '.join(columns)}) "
                    f"VALUES %s ON CONFLICT (timestamp) DO UPDATE SET {updates}"
                )
                execute_values(cur, sql, list(rows.values()))
        conn.commit()
        return conn
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _close(conn)
        logger.warning("ring PG batch failed (%s rows dropped): %s", len(items), e)
        return None


def _prune(conn, tables: Sequence[str]):
    if conn is None or getattr(conn, "closed", 1) or not tables:
        return conn
    cutoff = _cutoff_timestamp_utc()
    try:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(
                    f"DELETE FROM live_data.{table} WHERE timestamp < %s",
                    (cutoff,),
                )
        conn.commit()
        return conn
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _close(conn)
        logger.warning("ring PG prune failed: %s", e)
        return None


def _writer_loop() -> None:
    conn = None
    seen_tables: List[str] = []
    next_prune = time.monotonic() + prune_interval_sec()
    while True:
        try:
            items, stop = _collect()
            if items:
                for table, _cols, _vals in items:
                    if table not in seen_tables:
                        seen_tables.append(table)
                conn = _flush(conn, items)
            now = time.monotonic()
            if now >= next_prune:
                next_prune = now + prune_interval_sec()
                conn = _prune(conn, seen_tables)
            if stop:
                _close(conn)
                _drain_done.set()
                return
        except Exception as e:
            # Stay alive: a dead writer would silently stop all ring capture.
            logger.warning("ring PG writer iteration failed: %s", e)
            _close(conn)
            conn = None
            time.sleep(1.0)


def drain(*, timeout_sec: float = 5.0) -> bool:
    """Flush queued rows and stop the writer (process shutdown only)."""
    global _thread, _q
    with _lock:
        t, q = _thread, _q
    if t is None or not t.is_alive() or q is None:
        return True
    logger.info("ring PG writer drain start depth=%s", q.qsize())
    _drain_done.clear()
    try:
        q.put_nowait(None)
    except queue.Full:
        return False
    ok = _drain_done.wait(timeout=timeout_sec)
    t.join(timeout=1.0)
    with _lock:
        if _thread is t:
            _thread = None
            _q = None
    return ok


atexit.register(drain)
