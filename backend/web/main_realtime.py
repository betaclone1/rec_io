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
live_path_monitor_by_ws: Dict[int, tuple] = {}  # id(websocket) -> (WebSocket, LivePathMonitorSpec)
_debug_last_trade_live: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = defaultdict(
    lambda: defaultdict(dict)
)
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


def live_path_monitor_ws_register(ws, spec) -> None:
    from backend.core.live_path_cache_monitor import LivePathMonitorSpec

    if not isinstance(spec, LivePathMonitorSpec):
        raise TypeError("spec must be LivePathMonitorSpec")
    live_path_monitor_by_ws[id(ws)] = (ws, spec)


def live_path_monitor_ws_unregister(ws) -> None:
    live_path_monitor_by_ws.pop(id(ws), None)


def _iter_live_path_monitor_clients():
    for ws, spec in list(live_path_monitor_by_ws.values()):
        yield ws, spec


def _slot_from_active_trades_redis_key(key: str) -> Optional[str]:
    m = _main_re.search(r":tenant:(\d{4}):active_trades$", str(key or ""))
    return m.group(1) if m else None


def _portfolio_source_from_redis_key(key: str) -> Optional[tuple[str, str]]:
    m = _main_re.search(
        r":tenant:(\d{4}):kalshi:(positions|orders|fills)$",
        str(key or ""),
    )
    if not m:
        return None
    suffix = m.group(2)
    from backend.core.live_path_cache_monitor import (
        SOURCE_KALSHI_FILLS,
        SOURCE_KALSHI_ORDERS,
        SOURCE_KALSHI_POSITIONS,
    )

    source_map = {
        "positions": SOURCE_KALSHI_POSITIONS,
        "orders": SOURCE_KALSHI_ORDERS,
        "fills": SOURCE_KALSHI_FILLS,
    }
    src = source_map.get(suffix)
    if not src:
        return None
    return m.group(1), src


async def _push_portfolio_rows_refresh(slot: str, source: str) -> None:
    """Full snapshot — WS connect init only."""
    from backend.core.live_path_cache_monitor import build_cache_init_payload

    for client, spec in _iter_live_path_monitor_clients():
        if spec.source != source or _norm_slot(spec.user_no) != slot:
            continue
        await _send_live_path_monitor_payload(client, build_cache_init_payload(spec))


async def _push_portfolio_delta_ws(
    slot: str,
    source: str,
    *,
    upserts: Optional[List[Dict[str, Any]]] = None,
    removes: Optional[List[str]] = None,
) -> None:
    upserts = upserts or []
    removes = removes or []
    if not upserts and not removes:
        return
    payload = {
        "type": "cache_delta",
        "source": source,
        "upserts": upserts,
        "removes": removes,
        "ts": time.time(),
    }
    for client, spec in _iter_live_path_monitor_clients():
        if spec.source != source or _norm_slot(spec.user_no) != slot:
            continue
        await _send_live_path_monitor_payload(client, payload)


async def _push_portfolio_row_change(slot: str, source: str, obj: dict) -> None:
    detail = str(obj.get("detail") or "row")
    removes = [str(x) for x in (obj.get("removes") or []) if x]
    upserts: List[Dict[str, Any]] = []

    if detail == "remove":
        field = obj.get("field")
        if field:
            removes.append(str(field))
    elif detail in ("delta", "baseline"):
        upserts = list(obj.get("rows") or [])
    elif obj.get("row"):
        upserts = [obj["row"]]
    elif detail == "row" and not obj.get("row"):
        # Legacy / defensive: no embedded row → skip (never full snapshot refresh).
        return

    await _push_portfolio_delta_ws(slot, source, upserts=upserts, removes=removes)


async def _push_active_trades_patches_from_redis(slot: str) -> None:
    """After Redis hot-path write: diff per-client patch scope and push."""
    from backend.core import live_state_active_trades as ls_at
    from backend.core.live_path_cache_monitor import (
        SOURCE_ACTIVE_TRADES,
        live_patch_fields_for_scope,
    )

    scopes: set = set()
    for _, spec in live_path_monitor_by_ws.values():
        if spec.source == SOURCE_ACTIVE_TRADES and _norm_slot(spec.user_no) == slot:
            scopes.add(str(spec.patch_scope or "active_trades_ui"))
    if not scopes:
        return

    records = ls_at.list_trades(slot, statuses=("active", "pending", "closing"))
    for scope in scopes:
        last = _debug_last_trade_live[slot][scope]
        patches: List[Dict[str, Any]] = []
        seen = set()
        for rec in records:
            tid = rec.get("trade_id")
            if tid is None:
                continue
            tid_s = str(int(tid))
            seen.add(tid_s)
            live = live_patch_fields_for_scope(scope, rec)
            prev = last.get(tid_s) or {}
            changed: Dict[str, Any] = {}
            for k, v in live.items():
                if v is None:
                    continue
                if prev.get(k) != v:
                    changed[k] = v
            if changed:
                patches.append({"trade_id": int(tid), **changed})
            last[tid_s] = live
        for tid_s in list(last.keys()):
            if tid_s not in seen:
                del last[tid_s]
        if not patches:
            continue
        text = json.dumps(
            {
                "type": "cache_patch",
                "patch_scope": scope,
                "patches": patches,
                "ts": time.time(),
            },
            default=str,
        )
        await _send_live_path_monitor_text_to_slot(slot, scope, text)


async def _send_live_path_monitor_text_to_slot(slot: str, patch_scope: str, text: str) -> None:
    """Send to active_trades WS clients for tenant slot + patch scope."""
    from backend.core.live_path_cache_monitor import SOURCE_ACTIVE_TRADES

    to_remove: set = set()
    for client, spec in _iter_live_path_monitor_clients():
        if spec.source != SOURCE_ACTIVE_TRADES or _norm_slot(spec.user_no) != slot:
            continue
        if str(spec.patch_scope or "") != str(patch_scope or ""):
            continue
        try:
            await client.send_text(text)
        except Exception:
            to_remove.add(client)
    for c in to_remove:
        live_path_monitor_ws_unregister(c)


async def _send_live_path_monitor_payload(ws, payload: Dict[str, Any]) -> None:
    try:
        await ws.send_text(json.dumps(payload, default=str))
    except Exception:
        live_path_monitor_ws_unregister(ws)


async def _broadcast_live_state_debug(obj: dict) -> None:
    if not live_path_monitor_by_ws:
        return
    from backend.core.live_path_cache_monitor import (
        SOURCE_ACTIVE_TRADES,
        SOURCE_KALSHI_FILLS,
        SOURCE_KALSHI_ORDERS,
        SOURCE_KALSHI_POSITIONS,
        build_cache_event_payload,
    )
    from backend.core import live_state_kalshi_portfolio as lskp

    kind = str(obj.get("kind") or "")
    if kind == "active_trades":
        slot = _slot_from_active_trades_redis_key(str(obj.get("key") or ""))
        if slot:
            await _push_active_trades_patches_from_redis(slot)
    elif kind in (lskp.KIND_POSITIONS, lskp.KIND_ORDERS, lskp.KIND_FILLS):
        parsed = _portfolio_source_from_redis_key(str(obj.get("key") or ""))
        if parsed:
            await _push_portfolio_row_change(parsed[0], parsed[1], obj)

    portfolio_sources = {
        SOURCE_KALSHI_POSITIONS,
        SOURCE_KALSHI_ORDERS,
        SOURCE_KALSHI_FILLS,
    }
    for client, spec in _iter_live_path_monitor_clients():
        if not spec.matches_live_state_message(obj):
            continue
        if spec.source == SOURCE_ACTIVE_TRADES or spec.source in portfolio_sources:
            continue
        await _send_live_path_monitor_payload(
            client, build_cache_event_payload(spec, obj)
        )


async def _live_path_monitor_send_init(websocket: WebSocket, spec) -> None:
    from backend.core.live_path_cache_monitor import (
        SOURCE_ACTIVE_TRADES,
        build_cache_init_payload,
    )

    if spec.source == SOURCE_ACTIVE_TRADES:
        slot = _norm_slot(spec.user_no)
        scope = str(spec.patch_scope or "")
        if scope in _debug_last_trade_live[slot]:
            _debug_last_trade_live[slot][scope].clear()
    await _send_live_path_monitor_payload(websocket, build_cache_init_payload(spec))
    if spec.source == SOURCE_ACTIVE_TRADES:
        await _push_active_trades_patches_from_redis(_norm_slot(spec.user_no))


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
live_market_clients: set = set()
cfbenchmarks_feed_clients: set = set()

# Global live_data fanout (strike ladder, orderbook, spot) — not tenant-scoped.
LIVE_MARKET_WS_TYPES = frozenset(
    {
        "live_strike_ladder",
        "live_orderbook",
        "live_symbol_spot",
    }
)


def _is_live_market_ws_message(text: str) -> bool:
    if not text or not text.lstrip().startswith("{"):
        return False
    # Fast path: avoid full JSON parse on every db_changes fanout frame.
    if '"type":"live_orderbook"' in text or '"type": "live_orderbook"' in text:
        return True
    if '"type":"live_strike_ladder"' in text or '"type": "live_strike_ladder"' in text:
        return True
    if '"type":"live_symbol_spot"' in text or '"type": "live_symbol_spot"' in text:
        return True
    return False


async def _broadcast_live_market_message_text(message: str) -> None:
    if not live_market_clients or not _is_live_market_ws_message(message):
        return
    to_remove = set()
    for client in list(live_market_clients):
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    live_market_clients.difference_update(to_remove)


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
    await _broadcast_live_market_message_text(message)
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


def redis_live_state_debug_subscriber_thread(
    queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
) -> None:
    import redis.exceptions as redis_exc

    from backend.core.live_state_cache import UPDATED_CHANNEL

    channel = UPDATED_CHANNEL
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
                "Main app: subscribed to Redis channel %s for live-path debug WS",
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
                            "Redis live_state debug forwarder: ping failed (%s); reconnecting",
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
                "Redis live_state debug forwarder: connection issue (%s); retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        except Exception as e:
            _log = _LOG.debug if is_probably_startup_connect_refused(e) else _LOG.warning
            _log(
                "Redis live_state debug forwarder: %s; retry in %ss",
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


async def redis_live_state_debug_consume_loop(queue: asyncio.Queue) -> None:
    while True:
        try:
            text = await queue.get()
            try:
                obj = json.loads(text)
            except Exception:
                continue
            if isinstance(obj, dict) and obj.get("type") == "live_state_updated":
                await _broadcast_live_state_debug(obj)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Redis live_state debug consumer: %s", e)


async def redis_db_changes_consume_loop(queue: asyncio.Queue) -> None:
    while True:
        try:
            text = await queue.get()
            await _broadcast_db_change_message_text(text)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Redis db_changes consumer: %s", e)


async def _broadcast_cfbenchmarks_feed_text(message: str) -> None:
    if not cfbenchmarks_feed_clients:
        return
    to_remove = set()
    for client in list(cfbenchmarks_feed_clients):
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    cfbenchmarks_feed_clients.difference_update(to_remove)


async def redis_cfbenchmarks_feed_consume_loop(queue: asyncio.Queue) -> None:
    while True:
        try:
            text = await queue.get()
            await _broadcast_cfbenchmarks_feed_text(text)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _LOG.warning("Redis cfbenchmarks feed consumer: %s", e)


def redis_cfbenchmarks_feed_subscriber_thread(
    queue: asyncio.Queue, loop: asyncio.AbstractEventLoop
) -> None:
    import redis.exceptions as redis_exc

    from backend.core.cfbenchmarks_feed_cache import UPDATED_CHANNEL

    channel = os.getenv("CFBENCHMARKS_UPDATED_CHANNEL", UPDATED_CHANNEL)
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
                "Main app: subscribed to Redis channel %s for /ws/cfbenchmarks_feed",
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
                            "Redis cfbenchmarks forwarder: ping failed (%s); reconnecting",
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
                "Redis cfbenchmarks forwarder: connection issue (%s); retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        except Exception as e:
            _log = _LOG.debug if is_probably_startup_connect_refused(e) else _LOG.warning
            _log(
                "Redis cfbenchmarks forwarder: %s; retry in %ss",
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


async def _serve_live_path_cache_monitor_ws(websocket: WebSocket, spec) -> None:
    from backend.core.live_path_cache_monitor import validate_spec

    err = validate_spec(spec)
    if err:
        await websocket.close(code=4400, reason=err)
        return
    await websocket.accept()
    live_path_monitor_ws_register(websocket, spec)
    try:
        await _live_path_monitor_send_init(websocket, spec)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        live_path_monitor_ws_unregister(websocket)


@realtime_ws_router.websocket("/ws/active-trades-hot-path")
async def websocket_active_trades_hot_path(websocket: WebSocket):
    """Session-scoped: trade-log marks only (sell/pnl) for trade history."""
    from backend.core.live_path_cache_monitor import (
        PATCH_SCOPE_TRADE_LOG,
        parse_spec_from_query,
    )

    user_no = resolve_session_user_no_from_asgi_scope(websocket.scope)
    if not user_no:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    spec = parse_spec_from_query(
        source="active_trades", user_no=user_no, patch_scope=PATCH_SCOPE_TRADE_LOG
    )
    await _serve_live_path_cache_monitor_ws(websocket, spec)


@realtime_ws_router.websocket("/ws/active-trades-panel-live")
async def websocket_active_trades_panel_live(websocket: WebSocket):
    """Session-scoped: live prob + pnl patches for trade monitor active-trades table."""
    from backend.core.live_path_cache_monitor import (
        PATCH_SCOPE_ACTIVE_TRADES_UI,
        parse_spec_from_query,
    )

    user_no = resolve_session_user_no_from_asgi_scope(websocket.scope)
    if not user_no:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    spec = parse_spec_from_query(
        source="active_trades", user_no=user_no, patch_scope=PATCH_SCOPE_ACTIVE_TRADES_UI
    )
    await _serve_live_path_cache_monitor_ws(websocket, spec)


@realtime_ws_router.websocket("/ws/debug/live-path-cache")
async def websocket_debug_live_path_cache(
    websocket: WebSocket,
    source: str = "active_trades",
    user_no: str = "0001",
    exchange: str = "kalshi",
    market: str = "15m",
    symbol: str = "BTC",
    redis_key: str = "",
    ticker: str = "",
):
    """No auth — query params select cache source (local monitor UI)."""
    from backend.core.live_path_cache_monitor import parse_spec_from_query

    spec = parse_spec_from_query(
        source=source,
        user_no=user_no,
        exchange=exchange,
        market=market,
        symbol=symbol,
        redis_key=redis_key,
        ticker=ticker,
    )
    await _serve_live_path_cache_monitor_ws(websocket, spec)


@realtime_ws_router.websocket("/ws/debug/active-trades-hot-path/{user_no}")
async def websocket_debug_active_trades_hot_path(websocket: WebSocket, user_no: str):
    """Legacy alias — active_trades UI patches (includes prob) for tenant slot."""
    from backend.core.live_path_cache_monitor import parse_spec_from_query

    slot = str(user_no).strip()
    if not slot.isdigit() or len(slot) > 4:
        await websocket.close(code=4400, reason="user_no must be numeric slot e.g. 0001")
        return
    spec = parse_spec_from_query(source="active_trades", user_no=slot)
    await _serve_live_path_cache_monitor_ws(websocket, spec)


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


def _ws_query_param(scope: dict, key: str, default: str = "") -> str:
    raw = scope.get("query_string") or b""
    try:
        qs = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    except Exception:
        return default
    if not qs:
        return default
    from urllib.parse import parse_qs

    vals = parse_qs(qs, keep_blank_values=True).get(key) or []
    return str(vals[0]).strip() if vals else default


async def _hydrate_live_market_ws(websocket: WebSocket, symbol: str, market: str) -> None:
    """First frames on connect: spot + strike ladder for requested symbol/market (no HTTP)."""
    try:
        from backend.redis_switchboard import build_live_symbol_spot_payload
        from backend.core.live_state_read_helpers import strike_ladder_ws_payload

        spot = await asyncio.to_thread(build_live_symbol_spot_payload)
        if spot:
            await websocket.send_text(json.dumps(spot))
        sym = (symbol or "BTC").strip().upper() or "BTC"
        mk = (market or "15m").strip().lower()
        if mk not in ("hourly", "15m"):
            mk = "15m"
        ladder = await asyncio.to_thread(strike_ladder_ws_payload, "kalshi", mk, sym)
        if ladder:
            await websocket.send_text(json.dumps(ladder))
        from backend.core.trade_monitor_orderbook_watch import get_trade_monitor_orderbook_watch
        from backend.core.trade_monitor_live_orderbook_payload import build_live_orderbook_ws_payload

        watch_mt = await asyncio.to_thread(get_trade_monitor_orderbook_watch)
        if watch_mt:
            ob = await asyncio.to_thread(build_live_orderbook_ws_payload, watch_mt)
            if ob:
                await websocket.send_text(json.dumps(ob))
    except Exception as e:
        _LOG.debug("live_market WS hydrate failed: %s", e)


@realtime_ws_router.websocket("/ws/live_market")
async def websocket_live_market(websocket: WebSocket):
    """Global Kalshi live_data (strike ladder, orderbook, spot). No tenant session required."""
    sym = _ws_query_param(websocket.scope, "symbol", "BTC")
    mkt = _ws_query_param(websocket.scope, "market", "15m")
    await websocket.accept()
    live_market_clients.add(websocket)
    await _hydrate_live_market_ws(websocket, sym, mkt)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        live_market_clients.discard(websocket)


async def _hydrate_cfbenchmarks_feed_ws(websocket: WebSocket, index_id: str) -> None:
    import asyncio as _asyncio

    from backend.core.cfbenchmarks_feed_cache import (
        DEFAULT_INDEX_IDS_CSV,
        get_latest,
        get_meta,
        get_recent,
        parse_index_ids,
    )

    for iid in parse_index_ids(index_id or DEFAULT_INDEX_IDS_CSV):
        try:
            latest = await _asyncio.to_thread(get_latest, iid)
            if latest:
                await websocket.send_text(json.dumps(latest))
            meta = await _asyncio.to_thread(get_meta, iid)
            if meta:
                await websocket.send_text(
                    json.dumps({"type": "cfbenchmarks_meta", "index_id": iid, "meta": meta})
                )
            recent = await _asyncio.to_thread(get_recent, iid, 30)
            if recent:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "cfbenchmarks_recent",
                            "index_id": iid,
                            "ticks": recent,
                        }
                    )
                )
        except Exception as e:
            _LOG.debug("cfbenchmarks WS hydrate failed %s: %s", iid, e)


@realtime_ws_router.websocket("/ws/cfbenchmarks_feed")
async def websocket_cfbenchmarks_feed(websocket: WebSocket):
    """Experiment: Kalshi cfbenchmarks_value ticks from Redis (BRTI,ERTI default)."""
    from backend.core.cfbenchmarks_feed_cache import DEFAULT_INDEX_IDS_CSV as _cfb_default_csv

    index_id = _ws_query_param(websocket.scope, "index_id", _cfb_default_csv)
    await websocket.accept()
    cfbenchmarks_feed_clients.add(websocket)
    await _hydrate_cfbenchmarks_feed_ws(websocket, index_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        cfbenchmarks_feed_clients.discard(websocket)


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
