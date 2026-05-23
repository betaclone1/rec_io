"""
In-process spool for deferred Kalshi fill/order PostgreSQL writes.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from backend.core.kalshi_portfolio_records import upsert_fill_row, upsert_order_row

logger = logging.getLogger(__name__)

_SpoolItem = Dict[str, Any]
_OnFlushCallback = Callable[[str, int], None]


class PortfolioPgSpool:
    def __init__(
        self,
        *,
        get_pg_connection: Callable[[], Any],
        fills_table: Callable[[], str],
        orders_table: Callable[[], str],
        on_flush: Optional[_OnFlushCallback] = None,
    ) -> None:
        self._get_pg_connection = get_pg_connection
        self._fills_table = fills_table
        self._orders_table = orders_table
        self._on_flush = on_flush
        self._queue: Deque[_SpoolItem] = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        try:
            self._flush_ms = max(50, int(os.getenv("PORTFOLIO_PG_SPOOL_FLUSH_MS", "250")))
        except ValueError:
            self._flush_ms = 250
        try:
            self._max_batch = max(1, int(os.getenv("PORTFOLIO_PG_SPOOL_MAX_BATCH", "50")))
        except ValueError:
            self._max_batch = 50

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="portfolio_pg_spool", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def append_fill(self, rec: Dict[str, Any]) -> None:
        with self._lock:
            self._queue.append({"entity": "fill", "payload": dict(rec)})

    def append_order(self, rec: Dict[str, Any]) -> None:
        with self._lock:
            self._queue.append({"entity": "order", "payload": dict(rec)})

    def _drain_batch(self) -> List[_SpoolItem]:
        out: List[_SpoolItem] = []
        with self._lock:
            while self._queue and len(out) < self._max_batch:
                out.append(self._queue.popleft())
        return out

    def _flush_batch(self, batch: List[_SpoolItem]) -> None:
        if not batch:
            return
        conn = self._get_pg_connection()
        if not conn:
            logger.warning("portfolio spool flush skipped: no PG connection")
            with self._lock:
                for item in reversed(batch):
                    self._queue.appendleft(item)
            return
        fills_tbl = self._fills_table()
        orders_tbl = self._orders_table()
        fill_n = 0
        order_n = 0
        try:
            with conn.cursor() as cur:
                for item in batch:
                    entity = item.get("entity")
                    payload = item.get("payload") or {}
                    if entity == "fill":
                        upsert_fill_row(cur, fills_tbl, payload)
                        fill_n += 1
                    elif entity == "order":
                        upsert_order_row(cur, orders_tbl, payload)
                        order_n += 1
            conn.commit()
        except Exception as exc:
            logger.error("portfolio spool flush failed: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
            with self._lock:
                for item in reversed(batch):
                    self._queue.appendleft(item)
            return
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if self._on_flush:
            if fill_n:
                try:
                    self._on_flush("fills", fill_n)
                except Exception as exc:
                    logger.debug("portfolio spool on_flush fills: %s", exc)
            if order_n:
                try:
                    self._on_flush("orders", order_n)
                except Exception as exc:
                    logger.debug("portfolio spool on_flush orders: %s", exc)

    def _worker(self) -> None:
        while not self._stop.is_set():
            batch = self._drain_batch()
            if batch:
                self._flush_batch(batch)
            else:
                time.sleep(self._flush_ms / 1000.0)


_global_spool: Optional[PortfolioPgSpool] = None
_global_spool_lock = threading.Lock()


def get_portfolio_pg_spool() -> Optional[PortfolioPgSpool]:
    return _global_spool


def init_portfolio_pg_spool(**kwargs: Any) -> PortfolioPgSpool:
    global _global_spool
    with _global_spool_lock:
        if _global_spool is None:
            _global_spool = PortfolioPgSpool(**kwargs)
            _global_spool.start()
        return _global_spool
