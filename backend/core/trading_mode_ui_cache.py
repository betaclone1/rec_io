"""
Redis-backed cache for per-tenant ``/api/trading_mode`` JSON.

Invalidation: increment ``rec_io:trading_mode:rev`` when global trading mode changes so all
tenant-scoped cache keys (which include the rev) miss without scanning keys.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

_LOG = logging.getLogger(__name__)

_REV_KEY = "rec_io:trading_mode:rev"
_TTL_SEC = 45


def _redis_client_optional():
    try:
        import redis as redis_mod
    except ImportError:
        return None
    kwargs = dict(
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        url = os.getenv("REDIS_URL")
        if url:
            return redis_mod.from_url(url, **kwargs)
        return redis_mod.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            **kwargs,
        )
    except Exception as e:
        _LOG.debug("trading_mode_ui_cache: redis unavailable: %s", e)
        return None


def _current_rev(r) -> str:
    try:
        v = r.get(_REV_KEY)
        return str(int(v)) if v is not None and str(v).isdigit() else "0"
    except Exception:
        return "0"


def trading_mode_ui_cache_get(user_no: str) -> Optional[Dict[str, Any]]:
    r = _redis_client_optional()
    if not r:
        return None
    slot = (user_no or "").strip().zfill(4)
    if len(slot) != 4 or not slot.isdigit():
        return None
    try:
        rev = _current_rev(r)
        key = f"rec_io:trading_mode:ui:{slot}:{rev}"
        raw = r.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:
        _LOG.debug("trading_mode_ui_cache get: %s", e)
        return None


def trading_mode_ui_cache_set(user_no: str, payload: Dict[str, Any]) -> None:
    r = _redis_client_optional()
    if not r:
        return
    slot = (user_no or "").strip().zfill(4)
    if len(slot) != 4 or not slot.isdigit():
        return
    try:
        rev = _current_rev(r)
        key = f"rec_io:trading_mode:ui:{slot}:{rev}"
        r.setex(key, _TTL_SEC, json.dumps(payload, separators=(",", ":")))
    except Exception as e:
        _LOG.debug("trading_mode_ui_cache set: %s", e)


def trading_mode_ui_cache_bump_revision() -> None:
    r = _redis_client_optional()
    if not r:
        return
    try:
        r.incr(_REV_KEY)
    except Exception as e:
        _LOG.debug("trading_mode_ui_cache bump: %s", e)
