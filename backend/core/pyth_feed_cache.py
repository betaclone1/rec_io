"""
Redis helpers + underlying→symbol map for Kalshi ``pyth_value`` commodity feed.

Settlement underlyings (from Kalshi series ``settlement_sources``):
  GOLD   → Metal.Index.1OZGOLD/USD
  SILVER → Metal.Index.SILVER/USD
  WTI    → Commodities.Index.PYTHOIL/USD
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

KEY_PREFIX = os.getenv("PYTH_REDIS_PREFIX", "rec_io:pyth:v1")
UPDATED_CHANNEL = os.getenv("PYTH_UPDATED_CHANNEL", "rec_io:pyth:updated")
RECENT_MAX = int(os.getenv("PYTH_RECENT_MAX", "200"))
TTL_SEC = int(os.getenv("PYTH_REDIS_TTL_SEC", "7200"))

# Kalshi settlement underlyings for our commodity 15m series
UNDERLYING_TO_SYMBOL: Dict[str, str] = {
    "Metal.Index.1OZGOLD/USD": "GOLD",
    "Metal.Index.SILVER/USD": "SILVER",
    "Commodities.Index.PYTHOIL/USD": "WTI",
}

DEFAULT_UNDERLYINGS: List[str] = list(UNDERLYING_TO_SYMBOL.keys())
DEFAULT_UNDERLYINGS_CSV = ",".join(DEFAULT_UNDERLYINGS)

SYMBOL_TO_UNDERLYING: Dict[str, str] = {
    sym: und for und, sym in UNDERLYING_TO_SYMBOL.items()
}

# Common aliases → canonical underlying
UNDERLYING_ALIASES: Dict[str, str] = {
    "GOLD": "Metal.Index.1OZGOLD/USD",
    "XAU": "Metal.Index.1OZGOLD/USD",
    "1OZGOLD": "Metal.Index.1OZGOLD/USD",
    "SILVER": "Metal.Index.SILVER/USD",
    "XAG": "Metal.Index.SILVER/USD",
    "WTI": "Commodities.Index.PYTHOIL/USD",
    "OIL": "Commodities.Index.PYTHOIL/USD",
    "PYTHOIL": "Commodities.Index.PYTHOIL/USD",
}


def resolve_underlying(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return s
    alias = UNDERLYING_ALIASES.get(s.upper())
    if alias:
        return alias
    return s


def symbol_for_underlying(underlying: str) -> str:
    und = resolve_underlying(underlying)
    return UNDERLYING_TO_SYMBOL.get(und, und)


def parse_underlyings(raw: Optional[str] = None) -> List[str]:
    text = (
        raw
        if raw is not None
        else os.getenv("PYTH_UNDERLYING_TICKERS", DEFAULT_UNDERLYINGS_CSV)
    ).strip()
    if text.upper() in ("ALL", "*"):
        return list(DEFAULT_UNDERLYINGS)
    out: List[str] = []
    for part in text.split(","):
        und = resolve_underlying(part)
        if und and und not in out:
            out.append(und)
    return out or list(DEFAULT_UNDERLYINGS)


def _redis():
    from backend.core.live_state_cache import redis_client_optional

    return redis_client_optional()


def underlying_key(underlying: str) -> str:
    return f"{KEY_PREFIX}:{resolve_underlying(underlying)}"


def recent_key(underlying: str) -> str:
    return f"{underlying_key(underlying)}:recent"


def meta_key(underlying: str) -> str:
    return f"{underlying_key(underlying)}:meta"


def publish_tick(underlying: str, envelope: Dict[str, Any]) -> bool:
    r = _redis()
    if not r:
        return False
    und = resolve_underlying(underlying)
    body = json.dumps(envelope, default=str)
    try:
        pipe = r.pipeline()
        pipe.setex(underlying_key(und), TTL_SEC, body)
        pipe.lpush(recent_key(und), body)
        pipe.ltrim(recent_key(und), 0, RECENT_MAX - 1)
        pipe.expire(recent_key(und), TTL_SEC)
        pipe.publish(UPDATED_CHANNEL, body)
        pipe.execute()
        return True
    except Exception:
        return False


def set_meta(underlying: str, meta: Dict[str, Any]) -> bool:
    r = _redis()
    if not r:
        return False
    und = resolve_underlying(underlying)
    try:
        r.setex(meta_key(und), TTL_SEC, json.dumps(meta, default=str))
        return True
    except Exception:
        return False


def get_latest(underlying: str) -> Optional[Dict[str, Any]]:
    r = _redis()
    if not r:
        return None
    raw = r.get(underlying_key(resolve_underlying(underlying)))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def build_status(underlying: str) -> Dict[str, Any]:
    und = resolve_underlying(underlying)
    latest = get_latest(und)
    return {
        "underlying_ticker": und,
        "symbol": symbol_for_underlying(und),
        "redis_ok": _redis() is not None,
        "latest": latest,
        "checked_at": time.time(),
    }
