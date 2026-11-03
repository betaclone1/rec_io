"""Multi-ticker hot OB watch set for Upper Tail armed crypto markets.

Watchdog ``is_hot_orderbook_ticker`` unions this set so armed UT books flush
Redis + pub/sub immediately (no coalesce delay).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Iterable, Optional, Set

_lock = threading.Lock()
_local: Set[str] = set()

_REDIS_KEY = os.getenv(
    "UPPER_TAIL_ORDERBOOK_WATCH_KEY",
    "rec_io:upper_tail:orderbook_watch:v1",
)


def _redis():
    try:
        from backend.core.live_state_cache import redis_client_optional

        return redis_client_optional()
    except Exception:
        return None


def set_upper_tail_orderbook_watch(tickers: Iterable[str]) -> None:
    """Replace the armed UT hot-flush ticker set (local + Redis)."""
    cleaned = {str(t).strip() for t in tickers if str(t or "").strip()}
    with _lock:
        global _local
        _local = set(cleaned)
    r = _redis()
    if not r:
        return
    try:
        if cleaned:
            r.set(_REDIS_KEY, json.dumps(sorted(cleaned)), ex=7200)
        else:
            r.delete(_REDIS_KEY)
    except Exception:
        pass


def get_upper_tail_orderbook_watch() -> Set[str]:
    """Armed UT tickers (process-local first, else Redis)."""
    with _lock:
        if _local:
            return set(_local)
    r = _redis()
    if not r:
        return set()
    try:
        raw = r.get(_REDIS_KEY)
        if not raw:
            return set()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        if isinstance(data, list):
            return {str(t).strip() for t in data if str(t or "").strip()}
        if isinstance(data, str) and data.strip():
            return {data.strip()}
    except Exception:
        return set()
    return set()


def is_upper_tail_watched_ticker(market_ticker: str) -> bool:
    mt = str(market_ticker or "").strip()
    if not mt:
        return False
    return mt in get_upper_tail_orderbook_watch()
