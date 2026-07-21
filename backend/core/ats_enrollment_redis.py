"""
Redis channel for trade_manager -> active_trade_supervisor open-trade enrollment with handoff ACK.

This is **not** the DB NOTIFY path (switchboard). It is a dedicated service-to-service channel on the
same Redis instance (`REDIS_URL` / `REDIS_HOST`+`REDIS_PORT`) so trade_manager can publish an open
event and wait for ATS to SET a short-lived result key (correlation id).

Env:
  REDIS_CHANNEL_ATS_ENROLL_REQUEST — default rec_io:ats_enroll_request
  REDIS_KEY_PREFIX_ATS_ENROLL_RESULT — default ats:enroll:result:

trade_manager additionally reads (open-trade enrollment only):
  ATS_ENROLL_REDIS_ATTEMPTS — publish+wait rounds when waiting for ACK (default 3)
  ATS_ENROLL_ACK_WAIT_SEC — seconds to wait per round for the result key (default 18)
"""

from __future__ import annotations

import json
import logging
import os
import threading
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
REDIS_CHANNEL_ATS_TM_NOTIFICATIONS = os.getenv(
    "REDIS_CHANNEL_ATS_TM_NOTIFICATIONS", "rec_io:ats_tm_notifications"
)

# Pubsub loop progress (monotonic seconds). Updated every get_message wake so idle
# markets still look healthy; stalls only when the listen thread is dead or blocked
# inside a handler.
_subscriber_progress_mono: float = 0.0
_subscriber_progress_lock = threading.Lock()
_SUBSCRIBER_GET_MESSAGE_TIMEOUT_SEC = float(
    os.getenv("ATS_ENROLL_SUBSCRIBER_GET_MESSAGE_TIMEOUT_SEC", "1.0")
)


def mark_subscriber_progress() -> None:
    global _subscriber_progress_mono
    with _subscriber_progress_lock:
        _subscriber_progress_mono = time.monotonic()


def subscriber_progress_age_sec() -> float:
    """Seconds since last pubsub-loop progress. inf if never started."""
    with _subscriber_progress_lock:
        if _subscriber_progress_mono <= 0.0:
            return float("inf")
        return max(0.0, time.monotonic() - _subscriber_progress_mono)


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


def start_enroll_subscriber_loop(handler, tm_notify_handler=None, stop_event=None) -> None:
    """
    Blocking loop (run in a daemon thread).
    handler(msg: dict) -> None for REDIS_CHANNEL_ATS_ENROLL_REQUEST (open enroll).
    tm_notify_handler(msg: dict) -> None optional for REDIS_CHANNEL_ATS_TM_NOTIFICATIONS.

    Uses timed get_message so mark_subscriber_progress advances even when quiet
    (listen() alone only wakes on traffic and cannot detect a hung handler).
    Optional stop_event (threading.Event) ends the loop for supervised restart.
    """
    r = redis_client_optional()
    if not r:
        logger.warning("ATS enrollment subscriber not started (no Redis)")
        return
    pubsub = r.pubsub()
    channels = [REDIS_CHANNEL_ATS_ENROLL_REQUEST]
    if tm_notify_handler:
        channels.append(REDIS_CHANNEL_ATS_TM_NOTIFICATIONS)
    pubsub.subscribe(*channels)
    logger.info("ATS Redis subscribed to %s", channels)
    mark_subscriber_progress()
    timeout = max(0.2, float(_SUBSCRIBER_GET_MESSAGE_TIMEOUT_SEC))
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("ATS enrollment subscriber stop requested")
                break
            mark_subscriber_progress()
            try:
                message = pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=timeout
                )
            except Exception as e:
                logger.warning("ATS enrollment get_message error: %s", e)
                time.sleep(min(2.0, timeout))
                continue
            if not message:
                continue
            if message.get("type") != "message":
                continue
            try:
                ch = message.get("channel")
                data = json.loads(message["data"])
                if ch == REDIS_CHANNEL_ATS_TM_NOTIFICATIONS and tm_notify_handler:
                    tm_notify_handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.warning("ATS enrollment message error: %s", e)
            finally:
                mark_subscriber_progress()
    finally:
        try:
            pubsub.unsubscribe(*channels)
            pubsub.close()
        except Exception:
            pass
