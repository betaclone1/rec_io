"""Latest Kalshi public prints stored by market_watchdog (lean tape + recent list)."""

from __future__ import annotations

import json
import re
from typing import Any


def load_public_trade_prints(ticker: str) -> list[dict[str, Any]]:
    """Recent public prints for ``ticker``. Empty when Redis has none."""
    mt = str(ticker or "").strip()
    if not mt:
        return []
    try:
        from backend.core.live_state_cache import redis_client_optional
        from backend.core.market_watchdog.config import load_config

        r = redis_client_optional()
        if not r:
            return []
        cfg = load_config(exchange="kalshi", market_interval="15m")
        prefix = str(cfg.settled_redis_key).rsplit(":", 1)[0] + ":"
        san = re.sub(r"[^A-Za-z0-9_]+", "_", mt).strip("_").lower()[:50] or "unknown"
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
