"""Armed Upper Tail crypto tickers + min limit for book-trigger evaluation.

Watchdog uses this only to decide whether a published book at the rail should
emit ``upper_tail_rail_trigger``. Redis OB flush itself is universal; this set
does **not** gate freshness or tradeflow wake.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict, Iterable, Mapping, Optional, Set, Union

_lock = threading.Lock()
# ticker → minimum armed limit_px (most sensitive rail among monitors)
_local_arms: Dict[str, float] = {}

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


def _normalize_arms(
    arms: Union[Mapping[str, float], Iterable[str]],
) -> Dict[str, float]:
    if isinstance(arms, Mapping):
        out: Dict[str, float] = {}
        for k, v in arms.items():
            mt = str(k or "").strip()
            if not mt:
                continue
            try:
                px = float(v)
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            out[mt] = px
        return out
    # Iterable of tickers → default rail 0.99
    return {str(t).strip(): 0.99 for t in arms if str(t or "").strip()}


def set_upper_tail_orderbook_arm(arms: Mapping[str, float]) -> None:
    """Replace armed UT tickers with per-ticker min limit_px (local + Redis)."""
    cleaned = _normalize_arms(arms)
    with _lock:
        global _local_arms
        _local_arms = dict(cleaned)
    r = _redis()
    if r:
        try:
            if cleaned:
                r.set(_REDIS_KEY, json.dumps(cleaned, sort_keys=True), ex=7200)
            else:
                r.delete(_REDIS_KEY)
        except Exception:
            pass
    if not cleaned:
        try:
            from backend.core.upper_tail_rail_trigger import clear_rail_edge

            clear_rail_edge()
        except Exception:
            pass


def set_upper_tail_orderbook_watch(tickers: Iterable[str]) -> None:
    """Back-compat: arm tickers at default $0.99 rail."""
    set_upper_tail_orderbook_arm(_normalize_arms(tickers))


def get_upper_tail_orderbook_arm() -> Dict[str, float]:
    """Armed UT ticker → min limit_px (process-local first, else Redis)."""
    with _lock:
        if _local_arms:
            return dict(_local_arms)
    r = _redis()
    if not r:
        return {}
    try:
        raw = r.get(_REDIS_KEY)
        if not raw:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        if isinstance(data, dict):
            return _normalize_arms(data)
        if isinstance(data, list):
            return _normalize_arms(data)
        if isinstance(data, str) and data.strip():
            return {data.strip(): 0.99}
    except Exception:
        return {}
    return {}


def get_upper_tail_arm_limit(market_ticker: str) -> Optional[float]:
    mt = str(market_ticker or "").strip()
    if not mt:
        return None
    return get_upper_tail_orderbook_arm().get(mt)


def get_upper_tail_orderbook_watch() -> Set[str]:
    """Armed UT tickers (keys only)."""
    return set(get_upper_tail_orderbook_arm().keys())


def is_upper_tail_watched_ticker(market_ticker: str) -> bool:
    mt = str(market_ticker or "").strip()
    if not mt:
        return False
    return mt in get_upper_tail_orderbook_arm()
