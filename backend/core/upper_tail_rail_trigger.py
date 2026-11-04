"""Active Upper Tail rail-cross trigger — emit on OB publish, not agent polling.

Watchdog (or any flush path) evaluates armed tickers once when levels are published.
On rising edge (not-at-rail → at-rail), publishes ``rec_io:upper_tail:rail_trigger:v1``.
Upper Tail agents subscribe to that channel and place; they do not chew every OB delta.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

CHANNEL = os.getenv(
    "UPPER_TAIL_RAIL_TRIGGER_CHANNEL",
    "rec_io:upper_tail:rail_trigger:v1",
)

_edge_lock = threading.Lock()
# ticker → last emitted side (None = not currently at rail for emit purposes)
_last_emitted_side: Dict[str, Optional[str]] = {}


def _redis():
    try:
        from backend.core.live_state_cache import redis_client_optional

        return redis_client_optional()
    except Exception:
        return None


def _parse_px(raw: Any) -> Optional[float]:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def clear_rail_edge(market_ticker: Optional[str] = None) -> None:
    """Reset edge state (tests / when arms clear)."""
    with _edge_lock:
        if market_ticker is None:
            _last_emitted_side.clear()
            return
        mt = str(market_ticker or "").strip()
        if mt:
            _last_emitted_side.pop(mt, None)


def maybe_emit_rail_from_orderbook_payload(
    market_ticker: str,
    payload: Dict[str, Any],
) -> bool:
    """
    Cheap rising-edge check after OB Redis publish.

    Returns True if a rail_trigger message was published.
    """
    mt = str(market_ticker or "").strip()
    if not mt or not isinstance(payload, dict):
        return False
    try:
        from backend.core.upper_tail_orderbook_watch import get_upper_tail_arm_limit
    except Exception:
        return False
    limit = get_upper_tail_arm_limit(mt)
    if limit is None:
        return False

    from backend.core.orderbook_strike_prices import touch_dollars_from_orderbook_snapshot
    from backend.core.upper_tail import upper_tail_side_from_orderbook

    touch = touch_dollars_from_orderbook_snapshot(
        {
            "valid": True,
            "yes": payload.get("yes") or {},
            "no": payload.get("no") or {},
            "ts_ms": payload.get("ts_ms"),
            "venue_ts_ms": payload.get("venue_ts_ms"),
            "redis_written_ms": payload.get("redis_written_ms"),
        }
    )
    if not touch:
        with _edge_lock:
            _last_emitted_side[mt] = None
        return False

    side = upper_tail_side_from_orderbook(
        yes_ask=_parse_px(touch.get("yes_ask_dollars")),
        no_ask=_parse_px(touch.get("no_ask_dollars")),
        yes_bid=_parse_px(touch.get("yes_bid_dollars")),
        no_bid=_parse_px(touch.get("no_bid_dollars")),
        limit_px=float(limit),
    )
    with _edge_lock:
        prev = _last_emitted_side.get(mt)
        if not side:
            _last_emitted_side[mt] = None
            return False
        if prev == side:
            return False
        _last_emitted_side[mt] = side

    body = {
        "type": "upper_tail_rail_trigger",
        "market_ticker": mt,
        "side": side,
        "limit_px": float(limit),
        "touch": touch,
        "ts_ms": payload.get("ts_ms"),
        "venue_ts_ms": payload.get("venue_ts_ms"),
        "sending_ts_ms": payload.get("sending_ts_ms"),
        "redis_written_ms": payload.get("redis_written_ms"),
        "t_ws_recv_ms": payload.get("t_ws_recv_ms"),
        "t_apply_ms": payload.get("t_apply_ms"),
        "emitted_ms": int(time.time() * 1000),
    }
    r = _redis()
    if not r:
        # Edge already marked; allow retry next delta if publish skipped.
        with _edge_lock:
            if _last_emitted_side.get(mt) == side:
                _last_emitted_side[mt] = None
        return False
    try:
        r.publish(CHANNEL, json.dumps(body, default=str))
        return True
    except Exception:
        with _edge_lock:
            if _last_emitted_side.get(mt) == side:
                _last_emitted_side[mt] = None
        log.debug("upper_tail rail_trigger publish failed for %s", mt, exc_info=True)
        return False


def start_rail_trigger_listener(
    on_trigger: Callable[[Dict[str, Any]], None],
    *,
    thread_name: str = "upper_tail_rail_trigger",
) -> bool:
    """Daemon pub/sub on the rail-trigger channel. Returns False if Redis down."""
    r = _redis()
    if not r:
        return False

    def _worker() -> None:
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(CHANNEL)
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
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("type") or "") != "upper_tail_rail_trigger":
                    continue
                on_trigger(payload)
            except Exception:
                time.sleep(0.25)

    threading.Thread(target=_worker, name=thread_name, daemon=True).start()
    return True
