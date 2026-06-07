"""
Feed-health checks for cfbenchmarks_price_watchdog (~1 tick/min per index).

Unlike legacy Coinbase stale-price reconnect (unchanged quote for N seconds), CFB uses
**tick drought**: no cfbenchmarks_value tick for a subscribed index within the window.

Set CFB_FEED_STALE_TICK_SEC=0 to disable.
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple


def feed_stale_tick_sec() -> int:
    """Per-index max seconds without a tick before forcing WS reconnect. 0 = disabled."""
    raw = os.getenv("CFB_FEED_STALE_TICK_SEC", "180").strip()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 180


def feed_health_check_interval_sec() -> float:
    """How often the background loop evaluates drought while connected."""
    raw = os.getenv("CFB_FEED_HEALTH_CHECK_INTERVAL_SEC", "30").strip()
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def feed_stale_grace_after_connect_sec() -> float:
    """After subscribe, wait this long before drought checks (first ticks may be slow)."""
    raw = os.getenv("CFB_FEED_STALE_GRACE_SEC", "120").strip()
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 120.0


def feed_health_enabled() -> bool:
    return feed_stale_tick_sec() > 0


class CfBenchmarksFeedHealth:
    """Tracks last tick time per index for one WS session."""

    def __init__(self, index_ids: List[str]) -> None:
        self.index_ids = [i.strip().upper() for i in index_ids if i.strip()]
        self._last_tick_mono: Dict[str, float] = {}
        self._session_start_mono: float = 0.0

    def begin_session(self) -> None:
        self._last_tick_mono.clear()
        self._session_start_mono = time.monotonic()

    def record_tick(self, index_id: str) -> None:
        iid = (index_id or "").strip().upper()
        if not iid:
            return
        self._last_tick_mono[iid] = time.monotonic()

    def evaluate(self) -> Tuple[bool, str, Optional[str]]:
        """
        Return (feed_healthy, summary, reconnect_reason).

        reconnect_reason is set when the watchdog should drop the socket and reconnect.
        """
        if not feed_health_enabled():
            return True, "disabled", None

        stale_sec = feed_stale_tick_sec()
        grace = feed_stale_grace_after_connect_sec()
        now = time.monotonic()
        elapsed = now - self._session_start_mono
        if elapsed < grace:
            return True, f"grace:{elapsed:.0f}s<{grace:.0f}s", None

        worst_iid: Optional[str] = None
        worst_age = 0.0
        for iid in self.index_ids:
            last = self._last_tick_mono.get(iid)
            if last is None:
                age = elapsed
                reason_kind = "no_tick_since_connect"
            else:
                age = now - last
                reason_kind = "tick_stale"
            if age > worst_age:
                worst_age = age
                worst_iid = iid
            if age >= float(stale_sec):
                return (
                    False,
                    f"unhealthy:{iid}:{reason_kind}:{age:.0f}s>={stale_sec}s",
                    f"feed_{reason_kind}:{iid}:{age:.0f}s>={stale_sec}s",
                )

        return True, f"ok:max_age={worst_age:.0f}s@{worst_iid}", None

    def meta_snapshot(self) -> Dict[str, object]:
        """Fields for experiment meta / logging."""
        healthy, summary, reconnect = self.evaluate()
        now = time.monotonic()
        per_index: Dict[str, object] = {}
        for iid in self.index_ids:
            last = self._last_tick_mono.get(iid)
            if last is None:
                age = now - self._session_start_mono
            else:
                age = now - last
            per_index[iid] = round(age, 1)
        return {
            "feed_health_enabled": feed_health_enabled(),
            "feed_healthy": healthy,
            "feed_health_summary": summary,
            "feed_reconnect_pending": reconnect,
            "feed_stale_tick_sec": feed_stale_tick_sec(),
            "feed_age_sec_by_index": per_index,
        }
