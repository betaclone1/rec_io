"""
Versioned live_state envelopes in Redis (market, symbol, strike ladder).

Keys: ``rec_io:live_state:v1:{kind}:{exchange}:{market}:{symbol}`` (symbol omits market).
Pub/sub: ``rec_io:live_state:updated`` for strike gen and switchboard fanout.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend.core.exchange_ids import normalize_exchange

logger = logging.getLogger(__name__)

UPDATED_CHANNEL = os.getenv("LIVE_STATE_UPDATED_CHANNEL", "rec_io:live_state:updated")
KEY_PREFIX = os.getenv("LIVE_STATE_KEY_PREFIX", "rec_io:live_state:v1")
TTL_SEC = int(os.getenv("LIVE_STATE_TTL_SEC", "7200"))


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def _redis_client():
    try:
        import redis

        url = os.getenv("REDIS_URL", "").strip()
        if url:
            return redis.from_url(url, decode_responses=True)
        return redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
    except Exception as e:
        logger.debug("live_state_cache: no redis client: %s", e)
        return None


def redis_client_optional():
    r = _redis_client()
    if r is None:
        return None
    try:
        r.ping()
        return r
    except Exception as e:
        logger.debug("live_state_cache ping failed: %s", e)
        return None


def market_key(exchange: str, market: str, symbol: str) -> str:
    ex = normalize_exchange(exchange)
    m = (market or "hourly").strip().lower()
    sym = (symbol or "").upper().strip()
    return f"{KEY_PREFIX}:market:{ex}:{m}:{sym}"


def symbol_key(symbol: str) -> str:
    sym = (symbol or "").upper().strip()
    return f"{KEY_PREFIX}:symbol:{sym}"


def strike_ladder_key(exchange: str, market: str, symbol: str) -> str:
    ex = normalize_exchange(exchange)
    m = (market or "hourly").strip().lower()
    sym = (symbol or "").upper().strip()
    return f"{KEY_PREFIX}:strike_ladder:{ex}:{m}:{sym}"


def _envelope(
    data: Dict[str, Any],
    *,
    source_event_at: Optional[str] = None,
    ingest_mono: Optional[float] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    env: Dict[str, Any] = {
        "data": data,
        "updated_at": now,
    }
    if source_event_at:
        env["source_event_at"] = source_event_at
    if ingest_mono is not None:
        env["ingest_mono"] = ingest_mono
    return env


def _publish_updated(r, kind: str, key: str, *, extra: Optional[dict] = None) -> None:
    msg: Dict[str, Any] = {"type": "live_state_updated", "kind": kind, "key": key}
    if extra:
        msg.update(extra)
    try:
        r.publish(UPDATED_CHANNEL, json.dumps(msg, default=_json_default))
    except Exception as e:
        logger.debug("live_state publish failed: %s", e)


def cache_age_sec(envelope: Optional[Dict[str, Any]]) -> float:
    if not envelope or not envelope.get("updated_at"):
        return float("inf")
    try:
        updated = datetime.fromisoformat(
            str(envelope["updated_at"]).replace("Z", "+00:00")
        )
        return max(0.0, time.time() - updated.timestamp())
    except Exception:
        return float("inf")


def set_market(
    exchange: str,
    market: str,
    symbol: str,
    payload: Dict[str, Any],
    *,
    source_event_at: Optional[str] = None,
) -> bool:
    r = redis_client_optional()
    if not r:
        return False
    key = market_key(exchange, market, symbol)
    body = json.dumps(_envelope(payload, source_event_at=source_event_at), default=_json_default)
    r.setex(key, TTL_SEC, body)
    _publish_updated(r, "market", key)
    return True


def get_market(exchange: str, market: str, symbol: str) -> Optional[Dict[str, Any]]:
    r = redis_client_optional()
    if not r:
        return None
    raw = r.get(market_key(exchange, market, symbol))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_market_data(exchange: str, market: str, symbol: str) -> Optional[Dict[str, Any]]:
    env = get_market(exchange, market, symbol)
    if not env:
        return None
    data = env.get("data")
    return data if isinstance(data, dict) else None


def set_symbol(
    symbol: str,
    tick_row: Dict[str, Any],
    *,
    source_event_at: Optional[str] = None,
    publish_detail: str = "full",
    ingest_mono: Optional[float] = None,
) -> bool:
    r = redis_client_optional()
    if not r:
        return False
    key = symbol_key(symbol)
    mono = ingest_mono if ingest_mono is not None else time.monotonic()
    body = json.dumps(
        _envelope(tick_row, source_event_at=source_event_at, ingest_mono=mono),
        default=_json_default,
    )
    r.setex(key, TTL_SEC, body)
    _publish_updated(r, "symbol", key, extra={"publish_detail": publish_detail})
    return True


def get_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    r = redis_client_optional()
    if not r:
        return None
    raw = r.get(symbol_key(symbol))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_symbol_data(symbol: str) -> Optional[Dict[str, Any]]:
    env = get_symbol(symbol)
    if not env:
        return None
    data = env.get("data")
    return data if isinstance(data, dict) else None


def set_strike_ladder(
    exchange: str,
    market: str,
    symbol: str,
    *,
    generation_id: str,
    rows: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> bool:
    r = redis_client_optional()
    if not r:
        return False
    key = strike_ladder_key(exchange, market, symbol)
    payload = {
        "generation_id": generation_id,
        "rows": rows,
        "meta": meta or {},
    }
    body = json.dumps(_envelope(payload), default=_json_default)
    r.setex(key, TTL_SEC, body)
    _publish_updated(r, "strike_ladder", key)
    return True


def get_strike_ladder(exchange: str, market: str, symbol: str) -> Optional[Dict[str, Any]]:
    r = redis_client_optional()
    if not r:
        return None
    raw = r.get(strike_ladder_key(exchange, market, symbol))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_strike_ladder_rows(
    exchange: str, market: str, symbol: str
) -> List[Dict[str, Any]]:
    env = get_strike_ladder(exchange, market, symbol)
    if not env:
        return []
    data = env.get("data") or {}
    rows = data.get("rows")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict)]
    meta = data.get("meta") or {}
    strikes = meta.get("strikes")
    if isinstance(strikes, list):
        return [r for r in strikes if isinstance(r, dict)]
    return []
