"""Stale-tick reconnect gate for pyth_price_watchdog (~1 Hz underlyings)."""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple


def feed_health_enabled() -> bool:
    return os.getenv("PYTH_FEED_HEALTH", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def feed_stale_tick_sec() -> float:
    raw = os.getenv("PYTH_FEED_STALE_TICK_SEC", "30").strip()
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def feed_health_check_interval_sec() -> float:
    raw = os.getenv("PYTH_FEED_HEALTH_CHECK_INTERVAL_SEC", "5").strip()
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return 5.0


class PythFeedHealth:
    def __init__(self, underlyings: List[str]) -> None:
        self.underlyings = [u.strip() for u in underlyings if u.strip()]
        self._last_tick_mono: Dict[str, float] = {}
        self._session_start_mono: float = time.monotonic()
        self._reconnect_pending: Optional[str] = None

    def begin_session(self) -> None:
        self._session_start_mono = time.monotonic()
        self._reconnect_pending = None
        # Do not clear last ticks — allow grace across reconnect for healthy feeds.

    def record_tick(self, underlying: str) -> None:
        self._last_tick_mono[underlying.strip()] = time.monotonic()

    def meta_snapshot(self) -> Dict[str, object]:
        stale = feed_stale_tick_sec()
        now = time.monotonic()
        ages = {
            u: (now - self._last_tick_mono[u]) if u in self._last_tick_mono else None
            for u in self.underlyings
        }
        return {
            "feed_stale_tick_sec": stale,
            "tick_ages_sec": ages,
            "feed_reconnect_pending": self._reconnect_pending,
        }

    def evaluate(self) -> Tuple[bool, str, Optional[str]]:
        stale = feed_stale_tick_sec()
        if stale <= 0:
            return True, "ok", None
        now = time.monotonic()
        # Grace after connect before declaring stale.
        if now - self._session_start_mono < stale:
            return True, "warmup", None
        bad: List[str] = []
        for u in self.underlyings:
            last = self._last_tick_mono.get(u)
            if last is None or (now - last) > stale:
                bad.append(u)
        if not bad:
            return True, "ok", None
        summary = f"stale:{','.join(bad)}"
        reason = f"pyth_feed_stale:{bad[0]}"
        self._reconnect_pending = reason
        return False, summary, reason
