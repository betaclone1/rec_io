"""
Redis channel for trade_manager -> active_trade_supervisor open-trade enrollment with handoff ACK.

This is **not** the DB NOTIFY path (switchboard). It is a dedicated service-to-service channel on the
same Redis instance (`REDIS_URL` / `REDIS_HOST`+`REDIS_PORT`) so trade_manager can publish an open
event and wait for ATS to SET a short-lived result key (correlation id).

Env:
  REDIS_CHANNEL_ATS_ENROLL_REQUEST — default rec_io:ats_enroll_request
  REDIS_KEY_PREFIX_ATS_ENROLL_RESULT — default ats:enroll:result:
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from backend.core.exchange_ids import normalize_exchange

logger = logging.getLogger(__name__)

REDIS_CHANNEL_ATS_ENROLL_REQUEST = os.getenv(
    "REDIS_CHANNEL_ATS_ENROLL_REQUEST", "rec_io:ats_enroll_request"
)
REDIS_KEY_PREFIX_ATS_ENROLL_RESULT = os.getenv(
    "REDIS_KEY_PREFIX_ATS_ENROLL_RESULT", "ats:enroll:result:"
)


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
        logger.debug("Redis client unavailable: %s", e)
        return None


def redis_client_optional():
    """Return a Redis client or None if redis is not installed or connection fails."""
    r = _redis_client()
    if r is None:
        return None
    try:
        r.ping()
        return r
    except Exception as e:
        logger.warning("ATS enrollment Redis ping failed: %s", e)
        return None


def publish_trade_open_enroll_request(
    r,
    trade_id: int,
    ticket_id: str,
    monitor_suffix: str,
    correlation_id: str,
    exchange: Optional[str] = None,
) -> bool:
    """Fire-and-forget publish. Returns False only on hard errors."""
    try:
        payload = {
            "type": "ats_trade_open",
            "correlation_id": correlation_id,
            "trade_id": int(trade_id),
            "ticket_id": str(ticket_id) if ticket_id else "",
            "monitor_suffix": monitor_suffix,
            "exchange": normalize_exchange(exchange),
        }
        r.publish(REDIS_CHANNEL_ATS_ENROLL_REQUEST, json.dumps(payload))
        return True
    except Exception as e:
        logger.warning("ATS enrollment publish failed: %s", e)
        return False


def store_enroll_ack(r, correlation_id: str, payload: Dict[str, Any]) -> None:
    key = f"{REDIS_KEY_PREFIX_ATS_ENROLL_RESULT}{correlation_id}"
    r.setex(key, 120, json.dumps(payload))


def wait_trade_open_enroll_ack(
    r, correlation_id: str, timeout_sec: float = 12.0
) -> Optional[Dict[str, Any]]:
    key = f"{REDIS_KEY_PREFIX_ATS_ENROLL_RESULT}{correlation_id}"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.warning("ATS enrollment wait read error: %s", e)
        time.sleep(0.05)
    return None


def start_enroll_subscriber_loop(handler) -> None:
    """
    Blocking loop (run in a daemon thread). handler(msg: dict) -> None
    """
    r = redis_client_optional()
    if not r:
        logger.warning("ATS enrollment subscriber not started (no Redis)")
        return
    pubsub = r.pubsub()
    pubsub.subscribe(REDIS_CHANNEL_ATS_ENROLL_REQUEST)
    logger.info("ATS enrollment subscribed to %s", REDIS_CHANNEL_ATS_ENROLL_REQUEST)
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            data = json.loads(message["data"])
            handler(data)
        except Exception as e:
            logger.warning("ATS enrollment message error: %s", e)
