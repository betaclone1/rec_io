"""Kalshi market_watchdog Redis: public tape + ticker BBO (lean market feed)."""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def _settled_prefix_and_sanitize(ticker: str) -> tuple[str, str] | tuple[None, None]:
    mt = str(ticker or "").strip()
    if not mt:
        return None, None
    try:
        from backend.core.live_state_cache import redis_client_optional
        from backend.core.market_watchdog.config import load_config

        r = redis_client_optional()
        if not r:
            return None, None
        cfg = load_config(exchange="kalshi", market_interval="15m")
        prefix = str(cfg.settled_redis_key).rsplit(":", 1)[0] + ":"
        san = re.sub(r"[^A-Za-z0-9_]+", "_", mt).strip("_").lower()[:50] or "unknown"
        return prefix, san
    except Exception:
        return None, None


def load_ticker_bbo(ticker: str) -> Optional[dict[str, Any]]:
    """Latest ticker BBO for ``ticker`` (``yes_ask_dollars`` / ``no_ask_dollars``, …)."""
    mt = str(ticker or "").strip()
    if not mt:
        return None
    try:
        from backend.core.live_state_cache import redis_client_optional

        r = redis_client_optional()
        if not r:
            return None
        prefix, san = _settled_prefix_and_sanitize(mt)
        if not prefix or not san:
            return None
        raw = r.get(f"{prefix}ticker:v1:{san}")
        if raw is None:
            return None
        rec = json.loads(raw)
        return rec if isinstance(rec, dict) else None
    except Exception:
        return None


def load_public_trade_prints(ticker: str) -> list[dict[str, Any]]:
    """Recent public prints for ``ticker``. Empty when Redis has none."""
    mt = str(ticker or "").strip()
    if not mt:
        return []
    try:
        from backend.core.live_state_cache import redis_client_optional

        r = redis_client_optional()
        if not r:
            return []
        prefix, san = _settled_prefix_and_sanitize(mt)
        if not prefix or not san:
            return []
        recent_key = f"{prefix}public_trade_recent:v1:{san}"
        latest_key = f"{prefix}public_trade:v1:{san}"
        raws = r.lrange(recent_key, 0, 49) or []
        if not raws:
            one = r.get(latest_key)
            raws = [one] if one else []
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for raw in raws:
        if raw is None:
            continue
        try:
            rec = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out
