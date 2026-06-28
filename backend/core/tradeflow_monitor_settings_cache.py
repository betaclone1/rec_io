"""
Short-lived Redis cache for per-monitor tradeflow flags (``auto_trade``, ``reverse``, …).

Used by unified AES/ATS to avoid hammering ``monitor_list_*`` on every poll when
``LIVE_STATE_CACHE_ENABLED=1``. PG remains authoritative via ``load_fn`` on miss.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Callable

from backend.core.live_state_cache import redis_client_optional
from backend.core.live_state_config import live_state_cache_enabled

logger = logging.getLogger(__name__)

_KEY_PREFIX = os.getenv(
    "TRADEFLOW_MONITOR_SETTINGS_KEY_PREFIX",
    "rec_io:tradeflow:monitor_settings:v1",
)

# Fields cached per monitor; invalidate clears all of them.
_CACHED_FIELDS = ("auto_trade", "reverse")


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


def _cache_key(user_no: str, monitor_id: int, field: str) -> str:
    slot = _norm_slot(user_no)
    mid = int(monitor_id)
    return f"{_KEY_PREFIX}:{slot}:{mid}:{field}"


def invalidate_monitor_settings_cache(
    user_no: str,
    monitor_id: int,
    *,
    r=None,
) -> None:
    """Drop cached monitor flags after monitor_list writes (auto_trade toggle, etc.)."""
    client = r or redis_client_optional()
    if not client:
        return
    try:
        for field in _CACHED_FIELDS:
            client.delete(_cache_key(user_no, monitor_id, field))
    except Exception as e:
        logger.debug("invalidate_monitor_settings_cache: %s", e)


def get_cached_monitor_bool(
    user_no: str,
    monitor_id: int,
    field: str,
    load_fn: Callable[[], bool],
) -> bool:
    """
    Return a monitor boolean column via Redis when tradeflow cache is on.

    ``field`` names the cached flag (e.g. ``auto_trade``, ``reverse``). Each field
    has its own cache key so callers do not cross-contaminate values.
    """
    if not live_state_cache_enabled():
        return bool(load_fn())

    client = redis_client_optional()
    if not client:
        return bool(load_fn())

    key = _cache_key(user_no, monitor_id, field)
    try:
        raw = client.get(key)
        if raw:
            payload = json.loads(raw)
            if isinstance(payload, dict) and field in payload:
                return bool(payload[field])
    except Exception as e:
        logger.debug("get_cached_monitor_bool read: %s", e)

    value = bool(load_fn())
    try:
        client.setex(
            key,
            _cache_ttl_sec(),
            json.dumps({field: value}),
        )
    except Exception as e:
        logger.debug("get_cached_monitor_bool write: %s", e)
    return value


def get_cached_monitor_settings(
    user_no: str,
    monitor_id: int,
    load_fn: Callable[[], bool],
) -> bool:
    """Backward-compatible alias: cache ``auto_trade`` only."""
    return get_cached_monitor_bool(user_no, monitor_id, "auto_trade", load_fn)
