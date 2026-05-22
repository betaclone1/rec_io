"""
Short-lived Redis cache for per-monitor tradeflow flags (e.g. ``auto_trade``).

Used by unified AES/ATS to avoid hammering ``monitor_list_*`` on every poll when
``LIVE_STATE_CACHE_ENABLED=1``. PG remains authoritative via ``load_fn`` on miss.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Callable, Optional

from backend.core.live_state_cache import redis_client_optional
from backend.core.live_state_config import live_state_cache_enabled

logger = logging.getLogger(__name__)

_KEY_PREFIX = os.getenv(
    "TRADEFLOW_MONITOR_SETTINGS_KEY_PREFIX",
    "rec_io:tradeflow:monitor_settings:v1",
)


def _cache_ttl_sec() -> int:
    raw = os.getenv("TRADEFLOW_MONITOR_SETTINGS_CACHE_TTL_SEC", "3").strip()
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


def _norm_slot(user_no: str) -> str:
    u = str(user_no or "").strip()
    if u.isdigit() and len(u) <= 4:
        return u.zfill(4)
    return u


def _cache_key(user_no: str, monitor_id: int) -> str:
    slot = _norm_slot(user_no)
    mid = int(monitor_id)
    return f"{_KEY_PREFIX}:{slot}:{mid}"


def invalidate_monitor_settings_cache(
    user_no: str,
    monitor_id: int,
    *,
    r=None,
) -> None:
    """Drop cached row after monitor_list writes (auto_trade toggle, etc.)."""
    client = r or redis_client_optional()
    if not client:
        return
    try:
        client.delete(_cache_key(user_no, monitor_id))
    except Exception as e:
        logger.debug("invalidate_monitor_settings_cache: %s", e)


def get_cached_monitor_settings(
    user_no: str,
    monitor_id: int,
    load_fn: Callable[[], bool],
) -> bool:
    """
    Return monitor settings flag via Redis when tradeflow cache is on.

    ``load_fn`` must read PostgreSQL (or exit) and return the boolean needed by the
    caller (today: ``auto_trade`` enabled).
    """
    if not live_state_cache_enabled():
        return bool(load_fn())

    client = redis_client_optional()
    if not client:
        return bool(load_fn())

    key = _cache_key(user_no, monitor_id)
    try:
        raw = client.get(key)
        if raw:
            payload = json.loads(raw)
            if isinstance(payload, dict) and "auto_trade" in payload:
                return bool(payload["auto_trade"])
    except Exception as e:
        logger.debug("get_cached_monitor_settings read: %s", e)

    value = bool(load_fn())
    try:
        client.setex(
            key,
            _cache_ttl_sec(),
            json.dumps({"auto_trade": value}),
        )
    except Exception as e:
        logger.debug("get_cached_monitor_settings write: %s", e)
    return value
