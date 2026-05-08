"""Circuit breaker for read_api history routes (portfolio/bankroll/pnl bundles)."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict

_READ_API_HISTORY_BREAKER_LOCK = threading.Lock()
_READ_API_HISTORY_BREAKER: Dict[str, Dict[str, Any]] = {}
_READ_API_HISTORY_FAIL_THRESHOLD = int(os.getenv("READ_API_HISTORY_BREAKER_FAIL_THRESHOLD", "3"))
_READ_API_HISTORY_COOLDOWN_SEC = float(os.getenv("READ_API_HISTORY_BREAKER_COOLDOWN_SEC", "20"))


def history_breaker_is_open(key: str) -> bool:
    now_ts = time.time()
    with _READ_API_HISTORY_BREAKER_LOCK:
        st = _READ_API_HISTORY_BREAKER.get(key)
        return bool(st and float(st.get("open_until", 0.0)) > now_ts)


def history_breaker_mark_success(key: str) -> None:
    with _READ_API_HISTORY_BREAKER_LOCK:
        _READ_API_HISTORY_BREAKER[key] = {"fail_count": 0, "open_until": 0.0}


def history_breaker_mark_failure(key: str) -> None:
    now_ts = time.time()
    with _READ_API_HISTORY_BREAKER_LOCK:
        st = _READ_API_HISTORY_BREAKER.setdefault(key, {"fail_count": 0, "open_until": 0.0})
        st["fail_count"] = int(st.get("fail_count", 0)) + 1
        if st["fail_count"] >= _READ_API_HISTORY_FAIL_THRESHOLD:
            st["open_until"] = now_ts + _READ_API_HISTORY_COOLDOWN_SEC


def history_breaker_snapshot() -> Dict[str, Any]:
    now_ts = time.time()
    out: Dict[str, Any] = {}
    with _READ_API_HISTORY_BREAKER_LOCK:
        for key, st in _READ_API_HISTORY_BREAKER.items():
            open_until = float(st.get("open_until", 0.0))
            out[key] = {
                "fail_count": int(st.get("fail_count", 0)),
                "open": open_until > now_ts,
                "retry_in_sec": max(0.0, round(open_until - now_ts, 2)),
            }
    return out
