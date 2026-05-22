"""Which Kalshi market_ticker should receive live_orderbook WS fanout."""

from __future__ import annotations

import os
import threading
from typing import Optional

_lock = threading.Lock()
_watch_ticker: Optional[str] = None

_REDIS_KEY = os.getenv(
    "TRADE_MONITOR_ORDERBOOK_WATCH_KEY",
    "rec_io:trade_monitor:orderbook_watch:v1",
)


def _redis_get() -> Optional[str]:
    try:
        from backend.core import live_state_cache

        r = live_state_cache.redis_client_optional()
        if not r:
            return None
        raw = r.get(_REDIS_KEY)
        if not raw:
            return None
        s = str(raw).strip()
        return s or None
    except Exception:
        return None


def _redis_set(mt: Optional[str]) -> None:
    try:
        from backend.core import live_state_cache

        r = live_state_cache.redis_client_optional()
        if not r:
            return
        if mt:
            r.set(_REDIS_KEY, mt, ex=7200)
        else:
            r.delete(_REDIS_KEY)
    except Exception:
        pass


def set_trade_monitor_orderbook_watch(market_ticker: str) -> None:
    global _watch_ticker
    mt = str(market_ticker or "").strip() or None
    with _lock:
        _watch_ticker = mt
    _redis_set(mt)


def get_trade_monitor_orderbook_watch() -> Optional[str]:
    with _lock:
        if _watch_ticker:
            return _watch_ticker
    return _redis_get()


def should_fanout_orderbook_live_ws(
    market_ticker: str,
    *,
    market: str = "15m",
) -> bool:
    del market  # reserved for interval-specific rules
    watched = get_trade_monitor_orderbook_watch()
    if not watched:
        return False
    return str(market_ticker or "").strip() == watched
