"""
Subscribe to hot orderbook cache updates (HF backend scripts).

Reads ``rec_io:live_state:updated`` hints (``kind=orderbook``) and optionally loads
the Redis levels blob at ``trade_monitor:orderbook_levels:v1:{ticker}``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from backend.core.live_state_cache import UPDATED_CHANNEL, redis_client_optional
from backend.core.trade_monitor_orderbook_keys import trade_monitor_orderbook_redis_key


@dataclass(frozen=True)
class OrderbookCacheSnapshot:
    market_ticker: str
    seq: Optional[int]
    ts_ms: Optional[int]
    redis_written_ms: Optional[int]
    yes: dict[str, str]
    no: dict[str, str]
    received_ms: int
    apply_to_hot_ms: Optional[int]
    apply_to_receive_ms: Optional[int]

    @property
    def age_ms(self) -> Optional[int]:
        if self.ts_ms is None:
            return None
        return max(0, self.received_ms - int(self.ts_ms))


def load_orderbook_cache_snapshot(
    market_ticker: str,
    *,
    received_ms: Optional[int] = None,
) -> Optional[OrderbookCacheSnapshot]:
    """Load current levels from Redis (call after hint or on bootstrap)."""
    mt = str(market_ticker or "").strip()
    if not mt:
        return None
    r = redis_client_optional()
    if not r:
        return None
    recv = int(received_ms if received_ms is not None else time.time() * 1000)
    try:
        raw = r.get(trade_monitor_orderbook_redis_key(mt))
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("valid") is False:
        return None
    ts_ms = data.get("ts_ms")
    rw_ms = data.get("redis_written_ms")
    try:
        ts_i = int(ts_ms) if ts_ms is not None else None
    except (TypeError, ValueError):
        ts_i = None
    try:
        rw_i = int(rw_ms) if rw_ms is not None else None
    except (TypeError, ValueError):
        rw_i = None
    seq = data.get("seq")
    try:
        seq_i = int(seq) if seq is not None else None
    except (TypeError, ValueError):
        seq_i = None
    yes = data.get("yes") if isinstance(data.get("yes"), dict) else {}
    no = data.get("no") if isinstance(data.get("no"), dict) else {}
    apply_hot = (rw_i - ts_i) if (rw_i is not None and ts_i is not None) else None
    apply_recv = (recv - ts_i) if ts_i is not None else None
    return OrderbookCacheSnapshot(
        market_ticker=mt,
        seq=seq_i,
        ts_ms=ts_i,
        redis_written_ms=rw_i,
        yes={str(k): str(v) for k, v in yes.items()},
        no={str(k): str(v) for k, v in no.items()},
        received_ms=recv,
        apply_to_hot_ms=apply_hot,
        apply_to_receive_ms=apply_recv,
    )


def start_orderbook_hot_subscriber(
    on_update: Callable[[OrderbookCacheSnapshot], None],
    *,
    ticker_filter: Optional[Callable[[str], bool]] = None,
    thread_name: str = "orderbook_hot_sub",
) -> bool:
    """
    Blocking Redis pub/sub loop in a daemon thread.

    ``on_update`` receives a snapshot loaded from Redis after each orderbook hint.
    Returns False if Redis unavailable.
    """
    r = redis_client_optional()
    if not r:
        return False

    def _worker() -> None:
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(UPDATED_CHANNEL)
        while True:
            try:
                msg = pubsub.get_message(timeout=1.0)
                if not msg or msg.get("type") != "message":
                    continue
                raw = msg.get("data")
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                payload = json.loads(raw)
                if payload.get("type") != "live_state_updated":
                    continue
                if str(payload.get("kind") or "") != "orderbook":
                    continue
                mt = str(payload.get("market_ticker") or "").strip()
                if not mt:
                    continue
                if ticker_filter and not ticker_filter(mt):
                    continue
                snap = load_orderbook_cache_snapshot(mt)
                if snap:
                    on_update(snap)
            except Exception:
                time.sleep(0.25)

    t = threading.Thread(target=_worker, name=thread_name, daemon=True)
    t.start()
    return True
