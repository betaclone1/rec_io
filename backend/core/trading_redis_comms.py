"""
Trading-plane Redis helpers: streams (reliable commands) and pub/sub (UI fanout).

Env:
  USE_TRADING_REDIS_COMMS — when truthy, services prefer Redis over internal HTTP (per-path fallback remains in callers).

Streams (defaults):
  TRADING_REDIS_STREAM_EXECUTOR — trade_manager → trade_executor (trigger_trade payloads)
  TRADING_REDIS_STREAM_TM_STATUS — trade_executor → trade_manager (update_trade_status payloads)
  TRADING_REDIS_STREAM_TM_COMMANDS — AES / ATS → trade_manager (add_trade / close bodies)
  TRADING_REDIS_STREAM_MAXLEN — approximate max stream length per XADD (default 8000)

Consumer groups (fixed names):
  trade_executor: group executor, consumer hostname-based
  trade_manager status: group tm_status
  trade_manager commands: group tm_commands

Pub/sub:
  REDIS_CHANNEL_ATS_TM_NOTIFICATIONS — trade_manager → ATS (non-open notifications; open uses ats_enrollment_redis)
  REDIS_CHANNEL_TRADING_PREFERENCES — trading/UI events → main forwards to /ws/preferences (default rec_io:preferences)
  REDIS_CHANNEL_DB_CHANGES — same contract as main db_changes forwarder (default rec_io:db_changes)
  REDIS_CHANNEL_TM_POSITIONS_UPDATED — kalshi_account_sync_ws → trade_manager (same JSON as POST /api/positions_updated)

See docs/TRADING_REDIS_COMMS.md.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from backend.core.time_eastern import now_est

logger = logging.getLogger(__name__)


def use_trading_redis_comms() -> bool:
    v = (os.getenv("USE_TRADING_REDIS_COMMS") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def stream_executor() -> str:
    return os.getenv("TRADING_REDIS_STREAM_EXECUTOR", "trading:executor:trigger")


def stream_tm_status() -> str:
    return os.getenv("TRADING_REDIS_STREAM_TM_STATUS", "trading:tm:executor_status")


def stream_tm_commands() -> str:
    return os.getenv("TRADING_REDIS_STREAM_TM_COMMANDS", "trading:tm:commands")


def stream_maxlen() -> int:
    try:
        return max(500, int(os.getenv("TRADING_REDIS_STREAM_MAXLEN", "8000")))
    except ValueError:
        return 8000


def channel_ats_tm_notifications() -> str:
    return os.getenv("REDIS_CHANNEL_ATS_TM_NOTIFICATIONS", "rec_io:ats_tm_notifications")


def channel_trading_preferences() -> str:
    return os.getenv("REDIS_CHANNEL_TRADING_PREFERENCES", "rec_io:preferences")


def channel_db_changes() -> str:
    return os.getenv("REDIS_CHANNEL_DB_CHANGES", "rec_io:db_changes")


def channel_monitor_manager() -> str:
    return os.getenv("REDIS_CHANNEL_MONITOR_MANAGER", "rec_io:mm:trade_events")


def channel_tm_positions_updated() -> str:
    return os.getenv("REDIS_CHANNEL_TM_POSITIONS_UPDATED", "rec_io:tm:positions_updated")


def _redis_client():
    try:
        import redis

        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            return redis.from_url(
                redis_url,
                decode_responses=True,
                health_check_interval=25,
                socket_keepalive=True,
            )
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD") or None
        return redis.Redis(
            host=host,
            port=port,
            password=password,
            decode_responses=True,
            health_check_interval=25,
            socket_keepalive=True,
        )
    except Exception as e:
        logger.debug("trading redis client: %s", e)
        return None


_trading_redis_cached_lock = threading.Lock()
_trading_redis_cached = None


def _invalidate_trading_redis_cache() -> None:
    """Drop cached publisher client (e.g. after connection error)."""
    global _trading_redis_cached
    with _trading_redis_cached_lock:
        old = _trading_redis_cached
        _trading_redis_cached = None
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


def redis_client_optional():
    """
    Shared Redis connection for pub/sub and XADD from many call sites.
    Avoids a new TCP handshake + PING on every publish (previous behavior).
    """
    global _trading_redis_cached
    with _trading_redis_cached_lock:
        if _trading_redis_cached is not None:
            return _trading_redis_cached
        r = _redis_client()
        if r is None:
            return None
        try:
            r.ping()
        except Exception as e:
            logger.warning("Trading Redis ping failed: %s", e)
            try:
                r.close()
            except Exception:
                pass
            return None
        _trading_redis_cached = r
        return r


def redis_connect_uncached():
    """
    Dedicated connection for long-lived consumers that call close() in a finally block.
    Do not use redis_client_optional() there — it would tear down the shared cache.
    """
    r = _redis_client()
    if r is None:
        return None
    try:
        r.ping()
        return r
    except Exception as e:
        logger.warning("Trading Redis ping failed: %s", e)
        try:
            r.close()
        except Exception:
            pass
        return None


def ensure_consumer_group(r, stream: str, group: str) -> None:
    try:
        r.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as e:
        err = str(e).lower()
        if "busygroup" in err or "already exists" in err:
            return
        logger.warning("xgroup_create %s %s: %s", stream, group, e)


def xadd_trading_json(
    r,
    stream: str,
    *,
    msg_type: str,
    payload: Dict[str, Any],
    correlation_id: Optional[str] = None,
    source: str = "unknown",
) -> Optional[str]:
    """XADD one JSON payload. Returns stream id or None."""
    cid = correlation_id or str(uuid.uuid4())
    body = {
        "type": msg_type,
        "correlation_id": cid,
        "source": source,
        "ts": time.time(),
        "payload_json": json.dumps(payload, default=str),
    }
    try:
        maxlen = stream_maxlen()
        return r.xadd(stream, body, maxlen=maxlen, approximate=True)
    except Exception as e:
        logger.warning("xadd failed stream=%s type=%s: %s", stream, msg_type, e)
        return None


def decode_stream_fields(fields: Dict[str, str]) -> Dict[str, Any]:
    raw = fields.get("payload_json") or fields.get("data") or "{}"
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    return {
        "type": fields.get("type", ""),
        "correlation_id": fields.get("correlation_id", ""),
        "source": fields.get("source", ""),
        "payload": payload,
    }


def idempotency_begin(r, key: str, ttl_sec: int = 120) -> bool:
    """Return True if this is the first time for key (SET NX)."""
    try:
        return bool(r.set(key, "1", nx=True, ex=ttl_sec))
    except Exception:
        return True


def publish_ats_tm_notification(
    r,
    trade_id: int,
    ticket_id: str,
    status: str,
    monitor_identifier: str,
) -> bool:
    try:
        payload = {
            "type": "ats_tm_notification",
            "trade_id": int(trade_id),
            "ticket_id": str(ticket_id or ""),
            "status": str(status),
            "monitor_identifier": str(monitor_identifier),
        }
        r.publish(channel_ats_tm_notifications(), json.dumps(payload))
        return True
    except Exception as e:
        logger.warning("publish_ats_tm_notification failed: %s", e)
        return False


def publish_preferences_event(event_type: str, data: Dict[str, Any], r=None) -> bool:
    """Same JSON shape as main.py WS helpers: type + data (forwarded to /ws/preferences)."""
    channel = channel_trading_preferences()
    envelope = {"type": event_type, "data": data}
    payload = json.dumps(envelope, default=str)

    def _try_publish(client) -> bool:
        client.publish(channel, payload)
        return True

    if r is not None:
        try:
            return _try_publish(r)
        except Exception as e:
            logger.warning("publish_preferences_event failed: %s", e)
            return False

    for attempt in range(2):
        client = redis_client_optional()
        if not client:
            return False
        try:
            return _try_publish(client)
        except Exception as e:
            logger.warning(
                "publish_preferences_event failed (attempt %s): %s", attempt + 1, e
            )
            _invalidate_trading_redis_cache()
    return False


def publish_preferences_ws_message(message: Dict[str, Any], r=None) -> bool:
    """Publish a full WebSocket JSON object (monitor total position, monitor list, etc.)."""
    channel = channel_trading_preferences()
    payload = json.dumps(message, default=str)

    def _pub(c):
        c.publish(channel, payload)
        return True

    if r is not None:
        try:
            return _pub(r)
        except Exception as e:
            logger.warning("publish_preferences_ws_message failed: %s", e)
            return False

    for attempt in range(2):
        c = redis_client_optional()
        if not c:
            return False
        try:
            return _pub(c)
        except Exception as e:
            logger.warning(
                "publish_preferences_ws_message failed (attempt %s): %s",
                attempt + 1,
                e,
            )
            _invalidate_trading_redis_cache()
    return False


def publish_trade_manager_command(
    cmd_type: str,
    payload: Dict[str, Any],
    source: str,
    *,
    correlation_id: Optional[str] = None,
) -> bool:
    r = redis_client_optional()
    if not r:
        return False
    cid = correlation_id or (str(payload.get("ticket_id")) if payload.get("ticket_id") else None)
    return bool(
        xadd_trading_json(
            r,
            stream_tm_commands(),
            msg_type=cmd_type,
            payload=payload,
            source=source,
            correlation_id=cid,
        )
    )


def publish_monitor_manager_event(payload: Dict[str, Any], r=None) -> bool:
    if r is None:
        r = redis_client_optional()
        if not r:
            return False
    try:
        r.publish(channel_monitor_manager(), json.dumps(payload, default=str))
        return True
    except Exception as e:
        logger.warning("publish_monitor_manager_event failed: %s", e)
        return False


def publish_positions_updated_notification(payload: Dict[str, Any], r=None) -> bool:
    """Same body as POST trade_manager /api/positions_updated (e.g. database=positions)."""
    if r is None:
        r = redis_client_optional()
        if not r:
            return False
    try:
        r.publish(channel_tm_positions_updated(), json.dumps(payload, default=str))
        return True
    except Exception as e:
        logger.warning("publish_positions_updated_notification failed: %s", e)
        return False


def publish_db_change_json(db_name: str, change_data: Optional[Dict[str, Any]] = None, r=None) -> bool:
    """Same JSON shape as main.broadcast_db_change for /ws/db_changes subscribers."""
    close_client = False
    if r is None:
        r = redis_client_optional()
        if not r:
            return False
        close_client = False
    try:
        message = json.dumps(
            {
                "type": "db_change",
                "database": db_name,
                "data": change_data or {},
                "timestamp": now_est().isoformat(),
            },
            default=str,
        )
        r.publish(channel_db_changes(), message)
        return True
    except Exception as e:
        logger.warning("publish_db_change_json failed: %s", e)
        return False


def run_stream_consumer_loop(
    stream: str,
    group: str,
    consumer: str,
    handler: Callable[[Dict[str, Any], str, Dict[str, str]], bool],
    *,
    block_ms: int = 5000,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Blocking loop with reconnect. handler(fields_decoded, message_id, raw_fields) -> True if ACK.
    fields_decoded from decode_stream_fields.
    """
    import redis.exceptions as redis_exc

    backoff = 3.0
    while stop_event is None or not stop_event.is_set():
        r = None
        try:
            r = redis_connect_uncached()
            if not r:
                time.sleep(backoff)
                backoff = min(backoff * 1.3, 60.0)
                continue
            ensure_consumer_group(r, stream, group)
            backoff = 3.0
            while stop_event is None or not stop_event.is_set():
                try:
                    resp = r.xreadgroup(
                        group,
                        consumer,
                        {stream: ">"},
                        count=10,
                        block=block_ms,
                    )
                except redis_exc.ResponseError as e:
                    if "NOGROUP" in str(e):
                        ensure_consumer_group(r, stream, group)
                        continue
                    raise
                if not resp:
                    continue
                for _sname, messages in resp:
                    for msg_id, raw_fields in messages:
                        try:
                            decoded = decode_stream_fields(raw_fields)
                            if handler(decoded, msg_id, raw_fields):
                                r.xack(stream, group, msg_id)
                        except Exception as ex:
                            logger.warning(
                                "stream handler error stream=%s id=%s: %s",
                                stream,
                                msg_id,
                                ex,
                            )
                            try:
                                r.xack(stream, group, msg_id)
                            except Exception:
                                pass
        except (redis_exc.ConnectionError, redis_exc.TimeoutError, OSError) as e:
            logger.warning("stream consumer reconnect (%s): %s", stream, e)
            time.sleep(backoff)
            backoff = min(backoff * 1.3, 60.0)
        except Exception as e:
            logger.warning("stream consumer fatal (%s): %s", stream, e)
            time.sleep(backoff)
            backoff = min(backoff * 1.3, 60.0)
        finally:
            try:
                if r is not None:
                    r.close()
            except Exception:
                pass


def default_consumer_name(prefix: str) -> str:
    return f"{prefix}-{socket.gethostname()}-{os.getpid()}"


def start_consumer_daemon(
    stream: str,
    group: str,
    consumer: str,
    handler: Callable[[Dict[str, Any], str, Dict[str, str]], bool],
) -> threading.Thread:
    t = threading.Thread(
        target=run_stream_consumer_loop,
        kwargs={
            "stream": stream,
            "group": group,
            "consumer": consumer,
            "handler": handler,
        },
        daemon=True,
        name=f"trading-redis-{stream}",
    )
    t.start()
    return t
