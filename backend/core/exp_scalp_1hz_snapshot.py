"""
BTC 15m Expiration Scalp: one strike-table snapshot per wall-clock second.

Feeds keep moving. This module only reads the 1 Hz Redis snapshot that
``strike_snapshot_publisher`` writes. No live_state / orderbook flicker substitute
when the snapshot is missing or older than one second.
"""

from __future__ import annotations

import copy
import os
import time
from typing import Any, Dict, Optional, Tuple

from backend.core.exchange_ids import DEFAULT_EXCHANGE, normalize_exchange
from backend.core.strike_snapshot_redis import (
    get_strike_snapshot_envelope,
    snapshot_envelope_age_sec,
)

CUTOUT_SYMBOL = "BTC"
CUTOUT_MARKET = "15m"


def exp_scalp_snapshot_max_age_sec() -> float:
    """Reject snapshots older than this. Default 1.25s (publisher + AES align)."""
    try:
        return max(0.5, min(float(os.getenv("EXP_SCALP_SNAPSHOT_MAX_AGE_SEC", "1.25")), 2.0))
    except (TypeError, ValueError):
        return 1.25


def sleep_until_next_second_boundary() -> None:
    t = time.time()
    frac = t % 1.0
    if frac < 0.001:
        return
    time.sleep(1.0 - frac)


def _stamp_decision_ladder(env: Dict[str, Any]) -> Dict[str, Any]:
    data = env.get("data")
    if not isinstance(data, dict):
        raise ValueError("snapshot envelope missing data")
    ladder = copy.deepcopy(data)
    try:
        wall = int(env.get("wall_second"))
    except (TypeError, ValueError):
        wall = int(time.time())
    ladder["wall_second"] = wall
    ladder["rec_snapshot_eval"] = True
    pub = env.get("published_at")
    if pub is not None:
        try:
            ladder["snapshot_published_at"] = float(pub)
        except (TypeError, ValueError):
            pass
    return ladder


def load_exp_scalp_decision_ladder(
    *,
    exchange: Optional[str] = None,
    now: Optional[float] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Latest BTC 15m 1 Hz snapshot if it is still inside the max-age window.

    Returns ``(ladder, None)`` or ``(None, reason)``.
    Reasons: ``disabled_or_missing``, ``stale``, ``bad_payload``.
    """
    ex = normalize_exchange(exchange or DEFAULT_EXCHANGE)
    env = get_strike_snapshot_envelope(ex, CUTOUT_MARKET, CUTOUT_SYMBOL)
    if env is None:
        return None, "disabled_or_missing"
    age = snapshot_envelope_age_sec(env, now=now)
    limit = exp_scalp_snapshot_max_age_sec()
    if age is not None and age > limit:
        return None, "stale"
    try:
        return _stamp_decision_ladder(env), None
    except (TypeError, ValueError, KeyError):
        return None, "bad_payload"


def wait_for_new_exp_scalp_snapshot(
    last_wall_second: Optional[int],
    *,
    exchange: Optional[str] = None,
    poll_deadline_sec: float = 0.40,
    poll_sleep_sec: float = 0.02,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Align to the next wall-clock second, then read the publisher snapshot.

    Skips a duplicate ``wall_second`` already evaluated. Does not substitute
    live_state if the snapshot never arrives.
    """
    sleep_until_next_second_boundary()
    target = int(time.time())
    deadline = time.time() + max(0.05, float(poll_deadline_sec))
    last_reason = "disabled_or_missing"
    while time.time() < deadline:
        ladder, reason = load_exp_scalp_decision_ladder(exchange=exchange)
        last_reason = reason or "ok"
        if ladder is not None:
            ws = int(ladder["wall_second"])
            if last_wall_second is not None and ws == int(last_wall_second):
                last_reason = "duplicate"
            elif ws < target - 1:
                last_reason = "stale"
            else:
                return ladder, None
        time.sleep(max(0.005, float(poll_sleep_sec)))
    return None, last_reason
