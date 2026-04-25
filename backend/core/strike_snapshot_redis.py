"""
Versioned strike ladder snapshots in Redis for aligned AES/ATS reads.

Key: ``rec_io:strike_snapshot:v1:{exchange}:{market}:{symbol}``
Value: JSON envelope with ``generation_seq``, ``wall_second``, ``published_at``, ``data`` (ladder dict).

Env:
  REC_STRIKE_SNAPSHOT_READ — when truthy, supervisors prefer Redis before DB (default supervised: see supervisord generator).
  REC_STRIKE_SNAPSHOT_MAX_AGE_SEC — drop snapshot and fall back to DB if older than this (default 3).
  STRIKE_SNAPSHOT_REDIS_TTL_SEC — SET TTL (default 120).
"""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, Optional

from backend.core.exchange_ids import normalize_exchange

logger = logging.getLogger(__name__)


def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return float(o)
    return str(o)

KEY_PREFIX = os.getenv("STRIKE_SNAPSHOT_REDIS_KEY_PREFIX", "rec_io:strike_snapshot:v1")


def snapshot_redis_key(exchange: str, market: str, symbol: str) -> str:
    ex = normalize_exchange(exchange)
    m = (market or "hourly").strip().lower()
    sym = (symbol or "").upper().strip()
    return f"{KEY_PREFIX}:{ex}:{m}:{sym}"


def _redis_client():
    try:
        import redis

        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            return redis.from_url(redis_url, decode_responses=True)
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD") or None
        return redis.Redis(host=host, port=port, password=password, decode_responses=True)
    except Exception as e:
        logger.debug("strike_snapshot_redis: no client: %s", e)
        return None


def redis_client_optional():
    r = _redis_client()
    if r is None:
        return None
    try:
        r.ping()
        return r
    except Exception as e:
        logger.debug("strike_snapshot_redis ping failed: %s", e)
        return None


def strike_snapshot_read_enabled() -> bool:
    v = os.getenv("REC_STRIKE_SNAPSHOT_READ", "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def strike_snapshot_max_age_sec() -> float:
    try:
        return float(os.getenv("REC_STRIKE_SNAPSHOT_MAX_AGE_SEC", "3"))
    except ValueError:
        return 3.0


def strike_snapshot_ttl_sec() -> int:
    try:
        return max(30, int(os.getenv("STRIKE_SNAPSHOT_REDIS_TTL_SEC", "120")))
    except ValueError:
        return 120


def publish_strike_snapshot(
    r,
    *,
    exchange: str,
    market: str,
    symbol: str,
    generation_seq: int,
    wall_second: int,
    db_header_timestamp: Any,
    data: Dict[str, Any],
) -> bool:
    """Write snapshot JSON to Redis with TTL."""
    key = snapshot_redis_key(exchange, market, symbol)
    envelope = {
        "generation_seq": generation_seq,
        "wall_second": wall_second,
        "published_at": time.time(),
        "db_header_timestamp": str(db_header_timestamp) if db_header_timestamp is not None else None,
        "exchange": normalize_exchange(exchange),
        "market": (market or "hourly").strip().lower(),
        "symbol": (symbol or "").upper().strip(),
        "data": data,
    }
    try:
        r.set(
            key,
            json.dumps(envelope, default=_json_default),
            ex=strike_snapshot_ttl_sec(),
        )
        return True
    except Exception as e:
        logger.warning("publish_strike_snapshot failed %s: %s", key, e)
        return False


def get_strike_ladder_from_snapshot(
    exchange: str,
    market: str,
    symbol: str,
) -> Optional[Dict[str, Any]]:
    """
    Return ladder dict (same shape as fetch_strike_ladder_payload_from_db) or None.
    None if disabled, Redis down, parse error, or snapshot too stale.
    """
    if not strike_snapshot_read_enabled():
        return None
    r = redis_client_optional()
    if not r:
        return None
    key = snapshot_redis_key(exchange, market, symbol)
    try:
        raw = r.get(key)
        if not raw:
            return None
        env = json.loads(raw)
        data = env.get("data")
        if not isinstance(data, dict) or "strikes" not in data:
            return None
        pub = env.get("published_at")
        if pub is not None:
            age = time.time() - float(pub)
            if age > strike_snapshot_max_age_sec():
                logger.debug("strike snapshot stale key=%s age=%.2fs", key, age)
                return None
        return data
    except Exception as e:
        logger.debug("get_strike_ladder_from_snapshot %s: %s", key, e)
        return None
