"""
Subscribe to hot orderbook cache updates (HF backend scripts).

Reads ``rec_io:live_state:updated`` hints (``kind=orderbook``) and optionally loads
the Redis levels blob at ``trade_monitor:orderbook_levels:v1:{ticker}``.

Hot flushes may embed ``yes``/``no`` levels in the hint so consumers can skip GET.
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
    venue_ts_ms: Optional[int] = None
    sending_ts_ms: Optional[int] = None
    t_ws_recv_ms: Optional[int] = None
    t_apply_ms: Optional[int] = None
    clock: Optional[Any] = None
    from_hint: bool = False

    @property
    def age_ms(self) -> Optional[int]:
        """Age from venue/event ts_ms to consumer receive (prefer venue)."""
        src = self.venue_ts_ms if self.venue_ts_ms is not None else self.ts_ms
        if src is None:
            return None
        return max(0, self.received_ms - int(src))

    @property
    def venue_to_send_ms(self) -> Optional[int]:
        if self.venue_ts_ms is None or self.sending_ts_ms is None:
            return None
        return max(0, int(self.sending_ts_ms) - int(self.venue_ts_ms))


def _opt_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _levels_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _snapshot_from_fields(
    *,
    market_ticker: str,
    seq: Any,
    ts_ms: Any,
    redis_written_ms: Any,
    yes: Any,
    no: Any,
    received_ms: int,
    venue_ts_ms: Any = None,
    sending_ts_ms: Any = None,
    t_ws_recv_ms: Any = None,
    t_apply_ms: Any = None,
    clock: Any = None,
    from_hint: bool = False,
) -> OrderbookCacheSnapshot:
    ts_i = _opt_int(ts_ms)
    venue_i = _opt_int(venue_ts_ms)
    if ts_i is None and venue_i is not None:
        ts_i = venue_i
    rw_i = _opt_int(redis_written_ms)
    apply_i = _opt_int(t_apply_ms)
    # Prefer local apply→hot when available; else venue/event ts → redis write.
    apply_ref = apply_i if apply_i is not None else ts_i
    apply_hot = (rw_i - apply_ref) if (rw_i is not None and apply_ref is not None) else None
    event_ref = venue_i if venue_i is not None else ts_i
    apply_recv = (received_ms - event_ref) if event_ref is not None else None
    return OrderbookCacheSnapshot(
        market_ticker=market_ticker,
        seq=_opt_int(seq),
        ts_ms=ts_i,
        redis_written_ms=rw_i,
        yes=_levels_map(yes),
        no=_levels_map(no),
        received_ms=received_ms,
        apply_to_hot_ms=apply_hot,
        apply_to_receive_ms=apply_recv,
        venue_ts_ms=venue_i,
        sending_ts_ms=_opt_int(sending_ts_ms),
        t_ws_recv_ms=_opt_int(t_ws_recv_ms),
        t_apply_ms=apply_i,
        clock=clock,
        from_hint=from_hint,
    )


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
    return _snapshot_from_fields(
        market_ticker=mt,
        seq=data.get("seq"),
        ts_ms=data.get("ts_ms"),
        redis_written_ms=data.get("redis_written_ms"),
        yes=data.get("yes"),
        no=data.get("no"),
        received_ms=recv,
        venue_ts_ms=data.get("venue_ts_ms"),
        sending_ts_ms=data.get("sending_ts_ms"),
        t_ws_recv_ms=data.get("t_ws_recv_ms"),
        t_apply_ms=data.get("t_apply_ms"),
        clock=data.get("clock"),
        from_hint=False,
    )


def snapshot_from_orderbook_hint(
    payload: dict[str, Any],
    *,
    received_ms: Optional[int] = None,
) -> Optional[OrderbookCacheSnapshot]:
    """Build a snapshot from an embedded hot pub/sub hint (no Redis GET)."""
    if not isinstance(payload, dict):
        return None
    if str(payload.get("kind") or "") != "orderbook":
        return None
    mt = str(payload.get("market_ticker") or "").strip()
    if not mt:
        return None
    if payload.get("yes") is None or payload.get("no") is None:
        return None
    if payload.get("valid") is False:
        return None
    recv = int(received_ms if received_ms is not None else time.time() * 1000)
    return _snapshot_from_fields(
        market_ticker=mt,
        seq=payload.get("book_seq", payload.get("seq")),
        ts_ms=payload.get("ts_ms"),
        redis_written_ms=payload.get("redis_written_ms"),
        yes=payload.get("yes"),
        no=payload.get("no"),
        received_ms=recv,
        venue_ts_ms=payload.get("venue_ts_ms"),
        sending_ts_ms=payload.get("sending_ts_ms"),
        t_ws_recv_ms=payload.get("t_ws_recv_ms"),
        t_apply_ms=payload.get("t_apply_ms"),
        clock=payload.get("clock"),
        from_hint=True,
    )


def start_orderbook_hot_subscriber(
    on_update: Callable[[OrderbookCacheSnapshot], None],
    *,
    ticker_filter: Optional[Callable[[str], bool]] = None,
    thread_name: str = "orderbook_hot_sub",
) -> bool:
    """
    Blocking Redis pub/sub loop in a daemon thread.

    Prefers levels embedded in the hot hint; falls back to Redis GET.
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
                recv_ms = int(time.time() * 1000)
                snap = snapshot_from_orderbook_hint(payload, received_ms=recv_ms)
                if snap is None:
                    snap = load_orderbook_cache_snapshot(mt, received_ms=recv_ms)
                if snap:
                    on_update(snap)
            except Exception:
                time.sleep(0.25)

    t = threading.Thread(target=_worker, name=thread_name, daemon=True)
    t.start()
    return True
