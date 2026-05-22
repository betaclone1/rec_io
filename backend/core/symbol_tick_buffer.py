"""
In-process tick ring buffer for crypto symbol watchdog hot path.

Avoids per-tick PostgreSQL reads when LIVE_STATE_USE_TICK_BUFFER=1.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

_EST = ZoneInfo("America/New_York")
_MAX_TICKS = 50_000
_MAX_MOMENTUM = 120

_lock = threading.Lock()
_ticks: Dict[str, Deque[Tuple[float, float]]] = defaultdict(
    lambda: deque(maxlen=_MAX_TICKS)
)
_momentum: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=_MAX_MOMENTUM))


def _parse_ts(ts: str) -> float:
    s = (ts or "").strip()
    if not s:
        return datetime.now(_EST).timestamp()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        if "." in s and "+" not in s and s.count("-") <= 2:
            dt = datetime.strptime(s[:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=_EST)
        elif "+" in s or s.endswith("+00:00"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_EST)
        else:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_EST)
        return dt.timestamp()
    except Exception:
        return datetime.now(_EST).timestamp()


def append_tick(symbol: str, timestamp: str, price: float) -> None:
    sym = symbol.upper()
    epoch = _parse_ts(timestamp)
    with _lock:
        _ticks[sym].append((epoch, float(price)))


def record_momentum(symbol: str, momentum: Optional[float]) -> None:
    if momentum is None:
        return
    sym = symbol.upper()
    with _lock:
        _momentum[sym].append(float(momentum))


def latest_price(symbol: str) -> Optional[float]:
    sym = symbol.upper()
    with _lock:
        q = _ticks.get(sym)
        if not q:
            return None
        return q[-1][1]


def _ticks_in_window(sym: str, seconds: float) -> List[Tuple[float, float]]:
    cutoff = datetime.now(_EST).timestamp() - seconds
    with _lock:
        return [(e, p) for e, p in _ticks.get(sym, ()) if e >= cutoff]


def avg_price_last_minute(symbol: str, fallback: float) -> float:
    rows = _ticks_in_window(symbol.upper(), 60.0)
    if not rows:
        return float(fallback)
    return sum(p for _, p in rows) / len(rows)


def price_at_offset_minutes(symbol: str, minutes_ago: int) -> Optional[float]:
    sym = symbol.upper()
    target = datetime.now(_EST).timestamp() - minutes_ago * 60
    with _lock:
        q = _ticks.get(sym)
        if not q:
            return None
        best: Optional[Tuple[float, float]] = None
        best_dist = float("inf")
        for epoch, price in q:
            dist = abs(epoch - target)
            if dist < best_dist:
                best_dist = dist
                best = (epoch, price)
        return best[1] if best else None


def high_low_open_window(symbol: str, minutes_ago: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    rows = _ticks_in_window(symbol.upper(), minutes_ago * 60.0)
    if not rows:
        return (None, None, None)
    prices = [p for _, p in rows]
    return (max(prices), min(prices), rows[0][1])


def momentum_tail(symbol: str, count: int) -> List[float]:
    sym = symbol.upper()
    with _lock:
        q = _momentum.get(sym)
        if not q:
            return []
        return list(q)[-count:]


def minute_candles(symbol: str, lookback_minutes: int) -> List[dict]:
    sym = symbol.upper()
    cutoff = datetime.now(_EST) - timedelta(minutes=lookback_minutes)
    cutoff_epoch = cutoff.timestamp()
    buckets: Dict[str, List[float]] = {}
    with _lock:
        for epoch, price in _ticks.get(sym, ()):
            if epoch < cutoff_epoch:
                continue
            minute_key = datetime.fromtimestamp(epoch, _EST).strftime("%Y-%m-%dT%H:%M")
            buckets.setdefault(minute_key, []).append(price)
    candles: List[dict] = []
    for key in sorted(buckets.keys()):
        prices = buckets[key]
        if not prices:
            continue
        candles.append(
            {
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
            }
        )
    return candles
