"""
Preferences and db_changes WebSocket registries, Redis pub/sub fan-in, and broadcasts.

Owns tenant-scoped /ws/preferences and /ws/db_changes plus helpers used by trading_mode
hooks and monitor mutation routes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re as _main_re
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.core.time_eastern import now_est
from backend.core.trading_redis_comms import is_probably_startup_connect_refused
from backend.trading_mode import _norm_slot
from backend.web.tenant_asgi import resolve_session_user_no_from_asgi_scope

_LOG = logging.getLogger("main_app")

preferences_ws_by_user: Dict[str, set] = defaultdict(set)
realtime_ws_router = APIRouter()


def prefs_ws_all_clients():
    for sset in preferences_ws_by_user.values():
        for ws in sset:
            yield ws


def prefs_ws_register(ws, user_no: str) -> None:
    preferences_ws_by_user[str(user_no).strip().zfill(4)].add(ws)


def prefs_ws_unregister(ws) -> None:
    for un, sset in list(preferences_ws_by_user.items()):
        if ws in sset:
            sset.discard(ws)
            if not sset:
                del preferences_ws_by_user[un]
            return


def prefs_recipient_slots_for_redis_message(obj: dict) -> Optional[set]:
    """
    None → deliver to all preference WebSocket clients.
    Non-empty set of 4-digit slots → only those tenants.
    """
    raw = obj.get("tenant_user_no")
    if raw is not None:
        u = str(raw).strip()
        if u.isdigit() and len(u) <= 4:
            return {u.zfill(4)}
    mon_re = _main_re.compile(r"^(?:mon|MON)_(\d{4})_")
    slots: set = set()
    for key in ("monitor_id", "monitor_identifier"):
        v = obj.get(key)
        if isinstance(v, str):
            m = mon_re.match(v.strip())
            if m:
                slots.add(m.group(1))
    if slots:
        return slots
    data = obj.get("data")
    slots = set()
    if isinstance(data, dict):
        for key in ("monitor_id", "monitor_identifier"):
            v = data.get(key)
            if isinstance(v, str):
                m = mon_re.match(v.strip())
                if m:
                    slots.add(m.group(1))
        at = data.get("active_trades")
        if isinstance(at, list):
            for row in at:
                if not isinstance(row, dict):
                    continue
                mon = row.get("monitor") or row.get("monitor_identifier")
                if isinstance(mon, str):
                    m = mon_re.match(mon.strip())
                    if m:
                        slots.add(m.group(1))
    if slots:
        return slots
    return None


def prefs_ws_clients_for_slots(targets: Optional[set]) -> List:
    if not targets:
        return list(prefs_ws_all_clients())
    out: List = []
    for slot in targets:
        out.extend(list(preferences_ws_by_user.get(slot, ())))
    return out


def prefs_ws_client_count() -> int:
    return sum(len(s) for s in preferences_ws_by_user.values())


async def prefs_ws_send_json_to_slot(message: dict, tenant_slot: str) -> None:
    """Deliver a JSON message only to /ws/preferences clients for the given four-digit slot."""
    slot = _norm_slot(tenant_slot)
    text = json.dumps(message)
    to_remove = set()
    for websocket in list(preferences_ws_by_user.get(slot, ())):
        try:
            await websocket.send_text(text)
        except Exception:
            to_remove.add(websocket)
    for c in to_remove:
        prefs_ws_unregister(c)


db_change_clients: set = set()


async def broadcast_account_mode(mode: str):
    message = json.dumps({"account_mode": mode})
    to_remove = set()
    for client in prefs_ws_all_clients():
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    for c in to_remove:
        prefs_ws_unregister(c)


async def broadcast_trading_mode(mode: str):
    """Notify preferences WebSocket clients of live vs paper (global paper trading)."""
    message = json.dumps(
        {
            "trading_mode": mode,
            "global_paper_mode": mode == "paper",
        }
    )
    to_remove = set()
    for client in prefs_ws_all_clients():
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    for c in to_remove:
        prefs_ws_unregister(c)


async def _broadcast_db_change_message_text(message: str) -> None:
    """Send a pre-built db_change JSON string to all /ws/db_changes subscribers."""
    if not db_change_clients:
        return
    to_remove = set()
    for client in list(db_change_clients):
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    db_change_clients.difference_update(to_remove)


async def broadcast_db_change(db_name: str, change_data: dict):
    message = json.dumps(
        {
            "type": "db_change",
            "database": db_name,
            "data": change_data,
            "timestamp": now_est().isoformat(),
        }
    )
    await _broadcast_db_change_message_text(message)


def _redis_client_for_db_changes_forwarder():
    """Same env contract as redis_switchboard (REDIS_URL or REDIS_HOST/PORT/PASSWORD)."""
    import redis as _redis_mod

    _kwargs = dict(
        decode_responses=True,
        health_check_interval=25,
        socket_keepalive=True,
    )
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return _redis_mod.from_url(redis_url, **_kwargs)
    return _redis_mod.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        **_kwargs,
    )


def redis_db_changes_subscriber_thread(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    """
    Blocking Redis pubsub → asyncio queue. Uses timed get_message + ping instead of listen()
    so dead connections recover; matches long-lived UI sessions behind proxies.
    """
    import redis.exceptions as redis_exc

    channel = os.getenv("REDIS_CHANNEL_DB_CHANGES", "rec_io:db_changes")
    get_timeout_s = float(os.getenv("REDIS_DB_FORWARDER_GET_TIMEOUT", "30"))
    backoff = 5.0
    while True:
        r = None
        pubsub = None
        try:
            r = _redis_client_for_db_changes_forwarder()
            pubsub = r.pubsub()
            pubsub.subscribe(channel)
            _LOG.info(
                "Main app: subscribed to Redis channel %s for /ws/db_changes forward (same-origin WS for prod)",
                channel,
            )
            backoff = 5.0
            while True:
                message = pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=get_timeout_s,
                )
                if message is None:
                    try:
                        r.ping()
                    except (redis_exc.ConnectionError, redis_exc.TimeoutError, OSError) as ping_e:
                        _log = _LOG.debug if is_probably_startup_connect_refused(ping_e) else _LOG.warning
                        _log(
                            "Redis db_changes forwarder: ping failed (%s); reconnecting pubsub",
                            ping_e,
                        )
                        break
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if data is None:
                    continue
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                asyncio.run_coroutine_threadsafe(queue.put(data), loop)
        except (redis_exc.ConnectionError, redis_exc.TimeoutError, OSError) as e:
            _log = _LOG.debug if is_probably_startup_connect_refused(e) else _LOG.warning
            _log(
                "Redis db_changes forwarder: connection issue (%s); retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        except Exception as e:
            _log = _LOG.debug if is_probably_startup_connect_refused(e) else _LOG.warning
            _log(
                "Redis db_changes forwarder: %s; retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        finally:
            try:
                if pubsub is not None:
                    pubsub.close()
            except Exception:
                pass
            try:
                if r is not None:
                    r.close()
            except Exception:
                pass


async def redis_db_changes_consume_loop(queue: asyncio.Queue) -> None:
    while True:
        try:
            text = await queue.get()
            await _broadcast_db_change_message_text(text)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Redis db_changes consumer: %s", e)


def redis_trading_preferences_subscriber_thread(
    queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
) -> None:
    import redis.exceptions as redis_exc

    channel = os.getenv("REDIS_CHANNEL_TRADING_PREFERENCES", "rec_io:preferences")
    get_timeout_s = float(os.getenv("REDIS_DB_FORWARDER_GET_TIMEOUT", "30"))
    backoff = 5.0
    while True:
        r = None
        pubsub = None
        try:
            r = _redis_client_for_db_changes_forwarder()
            pubsub = r.pubsub()
            pubsub.subscribe(channel)
            _LOG.info(
                "Main app: subscribed to Redis channel %s for /ws/preferences forward",
                channel,
            )
            backoff = 5.0
            while True:
                message = pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=get_timeout_s,
                )
                if message is None:
                    try:
                        r.ping()
                    except (redis_exc.ConnectionError, redis_exc.TimeoutError, OSError) as ping_e:
                        _log = _LOG.debug if is_probably_startup_connect_refused(ping_e) else _LOG.warning
                        _log(
                            "Redis preferences forwarder: ping failed (%s); reconnecting",
                            ping_e,
                        )
                        break
                    continue
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if data is None:
                    continue
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                asyncio.run_coroutine_threadsafe(queue.put(data), loop)
        except (redis_exc.ConnectionError, redis_exc.TimeoutError, OSError) as e:
            _log = _LOG.debug if is_probably_startup_connect_refused(e) else _LOG.warning
            _log(
                "Redis preferences forwarder: connection issue (%s); retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        except Exception as e:
            _log = _LOG.debug if is_probably_startup_connect_refused(e) else _LOG.warning
            _log(
                "Redis preferences forwarder: %s; retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        finally:
            try:
                if pubsub is not None:
                    pubsub.close()
            except Exception:
                pass
            try:
                if r is not None:
                    r.close()
            except Exception:
                pass


async def redis_trading_preferences_consume_loop(queue: asyncio.Queue) -> None:
    while True:
        try:
            text = await queue.get()
            try:
                obj = json.loads(text)
            except Exception:
                obj = None
            targets = prefs_recipient_slots_for_redis_message(obj) if isinstance(obj, dict) else None
            clients = prefs_ws_clients_for_slots(targets)
            seen = set()
            to_remove = set()
            for client in clients:
                wid = id(client)
                if wid in seen:
                    continue
                seen.add(wid)
                try:
                    await client.send_text(text)
                except Exception:
                    to_remove.add(client)
            for c in to_remove:
                prefs_ws_unregister(c)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Redis preferences consumer: %s", e)


@realtime_ws_router.websocket("/ws/preferences")
async def websocket_preferences(websocket: WebSocket):
    user_no = resolve_session_user_no_from_asgi_scope(websocket.scope)
    if not user_no:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    # Omit Sec-WebSocket-Protocol on accept even if the client sent the token there:
    # echoing a long token_urlsafe value breaks some browsers (abnormal close 1006).
    await websocket.accept()
    prefs_ws_register(websocket, user_no)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        prefs_ws_unregister(websocket)


@realtime_ws_router.websocket("/ws/db_changes")
async def websocket_db_changes(websocket: WebSocket):
    if not resolve_session_user_no_from_asgi_scope(websocket.scope):
        await websocket.close(code=4401, reason="Not authenticated")
        return
    await websocket.accept()
    db_change_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        db_change_clients.discard(websocket)
