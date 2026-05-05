"""
Trading-plane Redis helpers: streams (reliable commands) and pub/sub (UI fanout).

Env:
  USE_TRADING_REDIS_COMMS — when truthy, services prefer Redis over internal HTTP (per-path fallback remains in callers).

  TRADING_REDIS_STARTUP_WAIT_SEC — seconds to retry PING when establishing the shared client (default 45).
  TRADING_REDIS_STARTUP_RETRY_INTERVAL_SEC — sleep between PING attempts (default 0.25).
  TRADING_REDIS_BACKOFF_AFTER_FAIL_SEC — after a failed wait, skip new attempts for this many seconds (default 15).
  TRADING_REDIS_WARN_COOLDOWN_SEC — at most one WARNING about unreachable Redis per this many seconds (default 120).
  TRADING_REDIS_UNCACHED_WAIT_SEC — shorter PING wait for :func:`redis_connect_uncached` reconnect loops (default 8).

Streams (defaults):
  TRADING_REDIS_STREAM_EXECUTOR — trade_manager → trade_executor (trigger_trade payloads); per-slot ``…:NNNN`` unless TRADING_REDIS_EXECUTOR_LEGACY_SINGLE_STREAM
  TRADING_REDIS_STREAM_TM_STATUS — trade_executor → trade_manager (update_trade_status payloads); per-slot ``…:NNNN`` unless TRADING_REDIS_TM_STATUS_LEGACY_SINGLE_STREAM
  TRADING_REDIS_STREAM_TM_COMMANDS — AES / ATS → trade_manager (add_trade / close bodies); per-slot stream ``…:NNNN`` unless legacy flag is set
  TRADING_REDIS_TM_COMMANDS_LEGACY_SINGLE_STREAM — if truthy, one shared command stream (multi-tenant unsafe with multiple trade_managers)
  TRADING_REDIS_STREAM_MM_MONITOR_SETTINGS — main_app → monitor_manager (set_auto_entry_settings JSON body)
  TRADING_REDIS_STREAM_MAXLEN — approximate max stream length per XADD (default 8000)

Consumer groups (fixed names; command stream may be per-slot):
  trade_executor: group executor, consumer hostname-based
  trade_manager status: group tm_status
  trade_manager commands: group tm_commands on ``trading:tm:commands:<NNNN>`` (one stream per tenant slot)

Pub/sub:
  REDIS_CHANNEL_ATS_TM_NOTIFICATIONS — trade_manager → ATS (non-open notifications; open uses ats_enrollment_redis)
  REDIS_CHANNEL_TRADING_PREFERENCES — trading/UI events → main forwards to /ws/preferences (default rec_io:preferences)
  REDIS_CHANNEL_DB_CHANGES — same contract as main db_changes forwarder (default rec_io:db_changes)
  REDIS_CHANNEL_TM_POSITIONS_UPDATED — kalshi_account_sync_ws → trade_manager (same JSON as POST /api/positions_updated)
  REDIS_CHANNEL_KALSHI_LIFECYCLE_TRADES — market_watchdog_ws → per-tenant kalshi_lifecycle_trade_consumer (``users_NNNN.trades_NNNN``)

See docs/TRADING_REDIS_COMMS.md.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional, Tuple

_MONITOR_SLOT_IN_KEY = re.compile(r"^mon_(\d{4})_\d+$", re.IGNORECASE)
_USER_NO_4 = re.compile(r"^\d{4}$")

from backend.core.time_eastern import now_est

logger = logging.getLogger(__name__)

# Shared client: wait for Redis during supervisor restart (ordering) before logging errors.
_trading_redis_cached_lock = threading.Lock()
_trading_redis_cached: Any = None
_trading_redis_skip_until_mono: float = 0.0
_trading_redis_warn_last_mono: float = 0.0


def _trading_redis_startup_wait_sec() -> float:
    try:
        return max(1.0, float(os.getenv("TRADING_REDIS_STARTUP_WAIT_SEC", "45")))
    except ValueError:
        return 45.0


def _trading_redis_startup_retry_interval_sec() -> float:
    try:
        return max(0.05, float(os.getenv("TRADING_REDIS_STARTUP_RETRY_INTERVAL_SEC", "0.25")))
    except ValueError:
        return 0.25


def _trading_redis_backoff_after_fail_sec() -> float:
    try:
        return max(1.0, float(os.getenv("TRADING_REDIS_BACKOFF_AFTER_FAIL_SEC", "15")))
    except ValueError:
        return 15.0


def _trading_redis_warn_cooldown_sec() -> float:
    try:
        return max(5.0, float(os.getenv("TRADING_REDIS_WARN_COOLDOWN_SEC", "120")))
    except ValueError:
        return 120.0


def _trading_redis_uncached_wait_sec() -> float:
    """Shorter wait for per-call connections (e.g. stream consumer reconnect loop)."""
    try:
        return max(0.5, float(os.getenv("TRADING_REDIS_UNCACHED_WAIT_SEC", "8")))
    except ValueError:
        return 8.0


def _should_emit_trading_redis_warning() -> bool:
    global _trading_redis_warn_last_mono
    now = time.monotonic()
    if now - _trading_redis_warn_last_mono >= _trading_redis_warn_cooldown_sec():
        _trading_redis_warn_last_mono = now
        return True
    return False


def is_probably_startup_connect_refused(exc: Optional[BaseException]) -> bool:
    """
    True when failure is typical supervisor ordering (peer not listening yet).

    Log these at DEBUG so restarts do not look like incidents; still WARN on
    timeouts, auth, etc.
    """
    if exc is None:
        return False
    msg = str(exc).lower()
    if "connection refused" in msg:
        return True
    if "error 111" in msg or "errno 111" in msg:
        return True
    if "errno 61" in msg or "error 61" in msg:
        return True
    if "10061" in msg:
        return True
    return False


def _ping_redis_with_backoff(r: Any, *, max_wait_sec: float) -> Tuple[bool, Optional[BaseException]]:
    """
    Retry PING until success or ``max_wait_sec`` elapses. No logging (callers decide).
    """
    if r is None:
        return False, None
    deadline = time.monotonic() + max_wait_sec
    interval = _trading_redis_startup_retry_interval_sec()
    last_err: Optional[BaseException] = None
    while time.monotonic() < deadline:
        try:
            r.ping()
            return True, None
        except Exception as e:
            last_err = e
            time.sleep(interval)
    return False, last_err


def use_trading_redis_comms() -> bool:
    v = (os.getenv("USE_TRADING_REDIS_COMMS") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def stream_executor() -> str:
    return os.getenv("TRADING_REDIS_STREAM_EXECUTOR", "trading:executor:trigger")


def stream_tm_status() -> str:
    return os.getenv("TRADING_REDIS_STREAM_TM_STATUS", "trading:tm:executor_status")


def stream_tm_commands() -> str:
    """Base stream name only. Prefer :func:`stream_tm_commands_for_worker` / :func:`stream_tm_commands_resolved`."""
    return os.getenv("TRADING_REDIS_STREAM_TM_COMMANDS", "trading:tm:commands")


def _legacy_single_tm_command_stream() -> bool:
    """If true, use one global stream (breaks multi-tenant when multiple trade_managers run)."""
    v = (os.getenv("TRADING_REDIS_TM_COMMANDS_LEGACY_SINGLE_STREAM") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def tenant_slot_from_monitor_key(monitor: Optional[str]) -> Optional[str]:
    """Parse ``mon_<slot>_<id>`` → four-digit slot."""
    if not monitor:
        return None
    m = _MONITOR_SLOT_IN_KEY.match(str(monitor).strip())
    return m.group(1) if m else None


def resolve_tm_command_stream_slot(
    payload: Dict[str, Any],
    tenant_user_no: Optional[str],
) -> Optional[str]:
    """Pick Redis stream slot: explicit arg, then ``payload['monitor']``, then worker tenant."""
    if tenant_user_no and _USER_NO_4.match(str(tenant_user_no).strip()):
        return str(tenant_user_no).strip()
    slot = tenant_slot_from_monitor_key(payload.get("monitor") if isinstance(payload, dict) else None)
    if slot:
        return slot
    try:
        from backend.core.tenant_context import get_worker_tenant_context

        w = get_worker_tenant_context().user_no
        if w and _USER_NO_4.match(str(w).strip()):
            return str(w).strip()
    except Exception:
        pass
    return None


def stream_tm_commands_resolved(slot: Optional[str]) -> str:
    """
    Stream key for AES/ATS → trade_manager commands.

    Default: ``{base}:<slot>`` for four-digit slots so each ``trade_manager_NNNN`` consumes only its queue.
    Set ``TRADING_REDIS_TM_COMMANDS_LEGACY_SINGLE_STREAM=1`` to force a single shared stream (legacy).
    """
    base = stream_tm_commands()
    if _legacy_single_tm_command_stream():
        return base
    if slot and _USER_NO_4.match(str(slot).strip()):
        return f"{base}:{str(slot).strip()}"
    return base


def stream_tm_commands_for_worker() -> str:
    """Stream this ``trade_manager`` process should XREADGROUP (from ``REC_USER_SCHEMA`` / worker tenant)."""
    try:
        from backend.core.tenant_context import get_worker_tenant_context

        return stream_tm_commands_resolved(get_worker_tenant_context().user_no)
    except Exception:
        return stream_tm_commands_resolved(None)


def _legacy_single_executor_stream() -> bool:
    """If true, use one global executor stream (unsafe with multiple trade_executors)."""
    v = (os.getenv("TRADING_REDIS_EXECUTOR_LEGACY_SINGLE_STREAM") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def stream_executor_resolved(slot: Optional[str]) -> str:
    """
    Stream for trade_manager → trade_executor ``trigger_trade``.

    Default: ``{base}:<slot>`` for four-digit slots so each ``trade_executor_NNNN`` consumes only its queue.
    """
    base = stream_executor()
    if _legacy_single_executor_stream():
        return base
    if slot and _USER_NO_4.match(str(slot).strip()):
        return f"{base}:{str(slot).strip()}"
    return base


def stream_executor_for_worker() -> str:
    """Stream this ``trade_executor`` process should XREADGROUP."""
    try:
        from backend.core.tenant_context import get_worker_tenant_context

        return stream_executor_resolved(get_worker_tenant_context().user_no)
    except Exception:
        return stream_executor_resolved(None)


def _legacy_single_tm_status_stream() -> bool:
    """If true, use one global tm_status stream (unsafe with multiple trade_managers)."""
    v = (os.getenv("TRADING_REDIS_TM_STATUS_LEGACY_SINGLE_STREAM") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def stream_tm_status_resolved(slot: Optional[str]) -> str:
    """
    Stream for trade_executor → trade_manager ``update_trade_status``.

    Default: ``{base}:<slot>`` per tenant so status updates reach the correct ``trade_manager_NNNN``.
    """
    base = stream_tm_status()
    if _legacy_single_tm_status_stream():
        return base
    if slot and _USER_NO_4.match(str(slot).strip()):
        return f"{base}:{str(slot).strip()}"
    return base


def stream_tm_status_for_worker() -> str:
    """Stream this ``trade_manager`` process should XREADGROUP for executor status."""
    try:
        from backend.core.tenant_context import get_worker_tenant_context

        return stream_tm_status_resolved(get_worker_tenant_context().user_no)
    except Exception:
        return stream_tm_status_resolved(None)


def stream_mm_monitor_settings() -> str:
    return os.getenv(
        "TRADING_REDIS_STREAM_MM_MONITOR_SETTINGS",
        "trading:mm:monitor_settings",
    )


def stream_kalshi_lifecycle_trades() -> str:
    """Durable stream for Kalshi lifecycle outcomes."""
    return os.getenv(
        "TRADING_REDIS_STREAM_KALSHI_LIFECYCLE_TRADES",
        "trading:kalshi:lifecycle:trades",
    )


def mm_monitor_settings_ack_key(correlation_id: str) -> str:
    return f"trading:mm:monitor_settings:ack:{correlation_id}"


def stream_maxlen() -> int:
    try:
        return max(500, int(os.getenv("TRADING_REDIS_STREAM_MAXLEN", "8000")))
    except ValueError:
        return 8000


def channel_ats_tm_notifications() -> str:
    return os.getenv("REDIS_CHANNEL_ATS_TM_NOTIFICATIONS", "rec_io:ats_tm_notifications")


def channel_trading_preferences() -> str:
    return os.getenv("REDIS_CHANNEL_TRADING_PREFERENCES", "rec_io:preferences")


def redis_key_system_release_version() -> str:
    """String value: current app release (e.g. 3.0.2). Set by system_monitor from system.version_control."""
    return os.getenv("REDIS_KEY_SYSTEM_RELEASE_VERSION", "rec_io:system_release_version")


def redis_key_dashboard_performance_snapshot(slot: str) -> str:
    """
    JSON blob: same object as ``performance_rollups_snapshot`` on ``REDIS_CHANNEL_DB_CHANGES``.
    Written by :func:`backend.core.performance_rollups.publish_performance_rollups_ws_snapshot` (and the same
    helper used there). ``GET /api/dashboard/performance-snapshot`` reads this key only (no DB cold-fill).
    """
    from backend.trading_mode import _norm_slot

    u = _norm_slot(slot or "")
    tpl = os.getenv(
        "REDIS_KEY_DASHBOARD_PERFORMANCE_SNAPSHOT",
        "rec_io:dashboard:performance_snapshot:{slot}",
    )
    return tpl.format(slot=u)


def channel_db_changes() -> str:
    return os.getenv("REDIS_CHANNEL_DB_CHANGES", "rec_io:db_changes")


def channel_monitor_manager() -> str:
    return os.getenv("REDIS_CHANNEL_MONITOR_MANAGER", "rec_io:mm:trade_events")


def channel_tm_positions_updated() -> str:
    return os.getenv("REDIS_CHANNEL_TM_POSITIONS_UPDATED", "rec_io:tm:positions_updated")


def channel_kalshi_lifecycle_trades() -> str:
    return os.getenv("REDIS_CHANNEL_KALSHI_LIFECYCLE_TRADES", "rec_io:kalshi_lifecycle_trades")


def publish_kalshi_lifecycle_trades_event(
    *,
    market_ticker: str,
    result_raw: object,
    event_type: str,
    source: str = "market_watchdog_ws",
) -> bool:
    """
    Publish a Kalshi ``market_lifecycle_v2`` outcome for fan-out to tenant-bound consumers.

    Each :mod:`backend.kalshi_lifecycle_trade_consumer` applies :func:`backend.core.kalshi_lifecycle_trade_outcome.apply_lifecycle_market_result_for_ticker`
    only within its ``REC_USER_SCHEMA``.
    """
    body = {
        "type": "kalshi_lifecycle_trades",
        "market_ticker": str(market_ticker).strip(),
        "result": result_raw,
        "event_type": str(event_type),
        "source": source,
    }
    r = redis_client_optional()
    if r is None:
        return False
    stream_ok = False
    pubsub_ok = False
    try:
        # Durable path (primary): stream + consumer groups.
        stream_ok = (
            xadd_trading_json(
                r,
                stream_kalshi_lifecycle_trades(),
                msg_type="kalshi_lifecycle_trades",
                payload=body,
                source=source,
            )
            is not None
        )
        # Best-effort compatibility fanout while consumers migrate.
        payload = json.dumps(body, default=str)
        pubsub_ok = bool(r.publish(channel_kalshi_lifecycle_trades(), payload))
        return stream_ok
    except Exception as e:
        logger.warning("publish kalshi_lifecycle_trades failed: %s", e)
        _invalidate_trading_redis_cache()
        return stream_ok or pubsub_ok


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


def _invalidate_trading_redis_cache() -> None:
    """Drop cached publisher client (e.g. after connection error)."""
    global _trading_redis_cached, _trading_redis_skip_until_mono
    with _trading_redis_cached_lock:
        old = _trading_redis_cached
        _trading_redis_cached = None
        _trading_redis_skip_until_mono = 0.0
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


def redis_client_optional():
    """
    Shared Redis connection for pub/sub and XADD from many call sites.
    Avoids a new TCP handshake + PING on every publish (previous behavior).

    On cold start (supervisor restart), Redis may not accept connections for a few seconds.
    This path retries PING for ``TRADING_REDIS_STARTUP_WAIT_SEC`` (default 45) before emitting
    a rate-limited warning, and backs off ``TRADING_REDIS_BACKOFF_AFTER_FAIL_SEC`` before retrying
    a full wait again — so logs are not flooded with benign restart noise.
    """
    global _trading_redis_cached, _trading_redis_skip_until_mono
    with _trading_redis_cached_lock:
        if _trading_redis_cached is not None:
            return _trading_redis_cached
        now = time.monotonic()
        if now < _trading_redis_skip_until_mono:
            return None
        r = _redis_client()
        if r is None:
            return None
        ok, last_err = _ping_redis_with_backoff(r, max_wait_sec=_trading_redis_startup_wait_sec())
        if ok:
            _trading_redis_cached = r
            _trading_redis_skip_until_mono = 0.0
            return r
        try:
            r.close()
        except Exception:
            pass
        _trading_redis_skip_until_mono = time.monotonic() + _trading_redis_backoff_after_fail_sec()
        if _should_emit_trading_redis_warning():
            _msg = (
                "Trading Redis unreachable after %.0fs of startup retries (backing off %.0fs; "
                "set TRADING_REDIS_STARTUP_WAIT_SEC to tune): %s"
            )
            _args = (
                _trading_redis_startup_wait_sec(),
                _trading_redis_backoff_after_fail_sec(),
                last_err,
            )
            if is_probably_startup_connect_refused(last_err):
                logger.debug(_msg, *_args)
            else:
                logger.warning(_msg, *_args)
        return None


def redis_connect_uncached():
    """
    Dedicated connection for long-lived consumers that call close() in a finally block.
    Do not use redis_client_optional() there — it would tear down the shared cache.

    Uses a shorter default wait than :func:`redis_client_optional` so reconnect loops do not stall.
    """
    r = _redis_client()
    if r is None:
        return None
    ok, last_err = _ping_redis_with_backoff(r, max_wait_sec=_trading_redis_uncached_wait_sec())
    if ok:
        return r
    try:
        r.close()
    except Exception:
        pass
    if _should_emit_trading_redis_warning():
        _msg = "Trading Redis unreachable (uncached, waited %.0fs): %s"
        _args = (_trading_redis_uncached_wait_sec(), last_err)
        if is_probably_startup_connect_refused(last_err):
            logger.debug(_msg, *_args)
        else:
            logger.warning(_msg, *_args)
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


def publish_preferences_event(
    event_type: str,
    data: Dict[str, Any],
    r=None,
    *,
    tenant_user_no: Optional[str] = None,
) -> bool:
    """Same JSON shape as main.py WS helpers: type + data (forwarded to /ws/preferences).

    When ``tenant_user_no`` is set (four-digit slot), main_app delivers only to WebSockets
    for that tenant instead of broadcasting every AES/ATS event to all browsers.
    """
    channel = channel_trading_preferences()
    envelope: Dict[str, Any] = {"type": event_type, "data": data}
    if tenant_user_no:
        u = str(tenant_user_no).strip()
        if u.isdigit() and len(u) <= 4:
            envelope["tenant_user_no"] = u.zfill(4)
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
            if is_probably_startup_connect_refused(e):
                logger.debug("publish_preferences_ws_message failed: %s", e)
            else:
                logger.warning("publish_preferences_ws_message failed: %s", e)
            return False

    for attempt in range(2):
        c = redis_client_optional()
        if not c:
            return False
        try:
            return _pub(c)
        except Exception as e:
            if is_probably_startup_connect_refused(e):
                logger.debug(
                    "publish_preferences_ws_message failed (attempt %s): %s",
                    attempt + 1,
                    e,
                )
            else:
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
    tenant_user_no: Optional[str] = None,
) -> bool:
    r = redis_client_optional()
    if not r:
        return False
    cid = correlation_id or (str(payload.get("ticket_id")) if payload.get("ticket_id") else None)
    slot = resolve_tm_command_stream_slot(payload, tenant_user_no)
    stream = stream_tm_commands_resolved(slot)
    if not _legacy_single_tm_command_stream() and slot is None:
        logger.warning(
            "publish_trade_manager_command: could not resolve tenant slot for stream "
            "(set monitor on payload or pass tenant_user_no); using base stream=%s source=%s type=%s",
            stream,
            source,
            cmd_type,
        )
    return bool(
        xadd_trading_json(
            r,
            stream,
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


def publish_auto_entry_settings_job(
    monitor_id: str,
    body: Dict[str, Any],
    correlation_id: str,
    *,
    user_number: Optional[str] = None,
    source: str = "main_app",
    r=None,
) -> bool:
    """
    Queue monitor_list auto-entry/auto-stop field updates for monitor_manager.
    consumer writes JSON result to mm_monitor_settings_ack_key(cor_uuid).

    ``user_number`` (four-digit slot) is required for multi-tenant: any monitor_manager
    process may consume the stream; apply uses this tenant, not the worker's REC_USER_SCHEMA.
    """
    client = r if r is not None else redis_client_optional()
    if not client:
        return False
    payload = {
        "correlation_id": correlation_id,
        "monitor_id": str(monitor_id),
        "body": body,
    }
    if user_number is not None and str(user_number).strip():
        payload["user_number"] = str(user_number).strip()
    return bool(
        xadd_trading_json(
            client,
            stream_mm_monitor_settings(),
            msg_type="set_auto_entry_settings",
            payload=payload,
            source=source,
            correlation_id=correlation_id,
        )
    )


def wait_auto_entry_settings_ack(
    correlation_id: str,
    *,
    timeout_sec: float = 12.0,
    poll_sec: float = 0.05,
) -> Optional[Dict[str, Any]]:
    """Poll Redis for monitor_manager result JSON. Returns None on timeout."""
    deadline = time.time() + timeout_sec
    key = mm_monitor_settings_ack_key(correlation_id)
    while time.time() < deadline:
        client = redis_client_optional()
        if not client:
            return None
        try:
            raw = client.get(key)
            if raw:
                try:
                    return json.loads(raw)
                except Exception:
                    return {"status": "error", "message": "invalid ack payload"}
        except Exception:
            pass
        time.sleep(poll_sec)
    return None


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
        if is_probably_startup_connect_refused(e):
            logger.debug("publish_db_change_json failed: %s", e)
        else:
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
    *,
    stop_event: Optional[threading.Event] = None,
) -> threading.Thread:
    t = threading.Thread(
        target=run_stream_consumer_loop,
        kwargs={
            "stream": stream,
            "group": group,
            "consumer": consumer,
            "handler": handler,
            "stop_event": stop_event,
        },
        daemon=True,
        name=f"trading-redis-{stream}",
    )
    t.start()
    return t
