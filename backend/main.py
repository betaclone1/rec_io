"""
MAIN APPLICATION - UNIVERSAL CENTRALIZED PORT SYSTEM
Uses the single centralized port configuration system.
"""

import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import json
import asyncio
import threading
from contextlib import asynccontextmanager
from collections import defaultdict
import time
import re as _main_re
from datetime import datetime, timedelta
import pytz
import requests
import sqlite3
import psycopg2
from psycopg2 import sql
from typing import List, Optional, Dict, Tuple
import fcntl
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Import the universal centralized port system
import sys
import os

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from backend.util.paths import get_project_root

# Use relative imports to avoid ModuleNotFoundError
from backend.core.port_config import (
    get_port,
    get_port_info,
    unified_active_trade_supervisor_service_name,
    user_scoped_service_name,
)

# Import unified configuration system for database connections
from backend.core.unified_config import UnifiedConfigManager
from backend.core.config.database import (
    get_database_config,
    get_postgresql_connection,
    get_system_postgresql_connection,
)
from backend.core.tenant_context import effective_tenant_context_for_sql_rewrite
from backend.core.tenant_legacy_sql import legacy_users_monitor_list
from backend.core.exchange_ids import normalize_exchange
from backend.core.time_eastern import EST, now_est
from backend.core.trading_redis_comms import is_probably_startup_connect_refused
from backend.util.trade_log_archivist import (
    archive_trades_for_monitor,
    fetch_master_trades_column_names,
    union_trades_with_archives_select,
)

unified_config = UnifiedConfigManager()


# Get port from centralized system
MAIN_APP_PORT = get_port("main_app")
READ_API_BASE_URL = f"http://127.0.0.1:{get_port('read_api')}"
# Aggregate /api/active_trades is served by pool ATS (8034), not legacy key active_trade_supervisor (6000).
ACTIVE_TRADE_SUPERVISOR_PORT = get_port(unified_active_trade_supervisor_service_name())

# Logging: EST, flush, single handler to stdout (supervisor captures)
from zoneinfo import ZoneInfo as _main_tz

def _main_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            from datetime import datetime
            dt = datetime.fromtimestamp(record.created, tz=_main_tz("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")

class _MainFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

def _configure_main_logging():
    logr = logging.getLogger("main_app")
    if logr.handlers:
        return logr
    import sys
    h = _MainFlushHandler(sys.stdout)
    h.setFormatter(_main_est_formatter())
    logr.addHandler(h)
    logr.setLevel(logging.INFO)
    return logr

_main_logger = _configure_main_logging()
_main_logger.info("Using centralized port %s (ATS port %s)", MAIN_APP_PORT, ACTIVE_TRADE_SUPERVISOR_PORT)

# Import centralized path utilities
from backend.util.paths import get_data_dir, get_trade_history_dir, get_accounts_data_dir
from backend.account_mode import get_account_mode
from backend.trading_mode import (
    _norm_slot,
    account_balance_table_for_user,
    is_paper_trading,
    migrate_legacy_state_file,
    monitor_list_fqn,
    sql_ident_qualified_table,
    subaccounts_table_for_user,
    transfers_table_for_user,
)

# /ws/preferences: tenant-scoped subscribers (Redis fan-out targets by tenant_user_no)
preferences_ws_by_user: Dict[str, set] = defaultdict(set)


def _prefs_ws_all_clients():
    for sset in preferences_ws_by_user.values():
        for ws in sset:
            yield ws


def _prefs_ws_register(ws, user_no: str) -> None:
    preferences_ws_by_user[str(user_no).strip().zfill(4)].add(ws)


def _prefs_ws_unregister(ws) -> None:
    for un, sset in list(preferences_ws_by_user.items()):
        if ws in sset:
            sset.discard(ws)
            if not sset:
                del preferences_ws_by_user[un]
            return


def _prefs_recipient_slots_for_redis_message(obj: dict) -> Optional[set]:
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


def _prefs_ws_clients_for_slots(targets: Optional[set]) -> List:
    if not targets:
        return list(_prefs_ws_all_clients())
    out: List = []
    for slot in targets:
        out.extend(list(preferences_ws_by_user.get(slot, ())))
    return out


def _prefs_ws_client_count() -> int:
    return sum(len(s) for s in preferences_ws_by_user.values())


async def _prefs_ws_send_json_to_slot(message: dict, tenant_slot: str) -> None:
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
        _prefs_ws_unregister(c)

# Global set of connected websocket clients for database changes
db_change_clients = set()

# Legacy preference path removed - all data now in PostgreSQL

# Global preferences cache
_preferences_cache = None
_cache_timestamp = 0
CACHE_TTL = 1.0  # 1 second cache TTL

# LEGACY REMOVED: update_auto_trade_settings_postgresql function - now using strategy_list table directly

# LEGACY REMOVED: get_auto_trade_settings_postgresql function - now using strategy_list table directly

# LEGACY REMOVED: get_auto_stop_settings_postgresql function - now using strategy_list table directly

# Legacy trade_preferences functions removed - all position sizing and strategy now handled by monitor_list table

# Legacy calculate_total_position function removed - position sizing now handled by monitor_list table

# Legacy update_total_position function removed - position sizing now handled by monitor_list table

# Legacy get_trade_preferences_postgresql function removed - all position sizing and strategy now handled by monitor_list table

# LEGACY REMOVED: get_all_preferences_postgresql function - now using strategy-specific endpoints

# Authentication: sessions and password checks live on read_api; main proxies /api/auth and /api/user.
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.web.session_store import find_valid_token


def _session_user_number_from_optional_user_id(user_id: Optional[str]) -> str:
    """Authenticated tenant slot; optional ``user_id`` must match session (cross-tenant guard)."""
    slot = resolved_tenant_user_no_for_app()
    if user_id is None or not str(user_id).strip():
        return slot
    s = str(user_id).strip()
    low = s.lower()
    if low.startswith("user_"):
        s = s.split("_", 1)[-1]
    s = s.strip().zfill(4)
    if len(s) != 4 or not s.isdigit():
        raise HTTPException(status_code=400, detail="invalid user_id")
    if s != slot:
        raise HTTPException(status_code=403, detail="user_id does not match session")
    return s


def _monitor_slot_and_db_id_from_monitor_id(
    monitor_id: str, body_user_id: Optional[str]
) -> tuple[str, str]:
    """
    Parse MON_/mon_ / numeric monitor id. Numeric id uses session slot.
    Embedded tenant in prefixed ids must match session.
    """
    slot = _session_user_number_from_optional_user_id(body_user_id)
    mid = str(monitor_id).strip()
    if (mid.startswith("MON_") or mid.startswith("mon_")) and "_" in mid:
        parts = mid.split("_")
        if len(parts) >= 3:
            un = parts[1].strip().zfill(4)
            db_id = parts[2].strip()
            if len(un) != 4 or not un.isdigit() or not db_id.isdigit():
                raise HTTPException(status_code=400, detail="Invalid monitor ID format")
            if un != slot:
                raise HTTPException(
                    status_code=403, detail="monitor_id tenant does not match session"
                )
            return un, db_id
        raise HTTPException(status_code=400, detail="Invalid monitor ID format")
    if mid.isdigit():
        return slot, mid
    raise HTTPException(status_code=400, detail="Invalid monitor ID format")


AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
if os.environ.get("REC_ENVIRONMENT") == "production":
    AUTH_ENABLED = True


def _query_token_auth_ok(request: Request) -> bool:
    if not AUTH_ENABLED:
        return True
    token = (request.query_params.get("token") or "").strip()
    if not token:
        ck = request.cookies.get("rec_auth_token")
        token = (ck or "").strip()
    if not token:
        return False
    return find_valid_token(token) is not None


def _read_api_forward_headers(request: Request) -> Dict[str, str]:
    h: Dict[str, str] = {}
    auth = request.headers.get("authorization")
    if auth:
        h["Authorization"] = auth
    # read_api resolves tenant from session; browser fetch uses Cookie, not Bearer.
    cookie = request.headers.get("cookie")
    if cookie:
        h["Cookie"] = cookie
    return h


def _read_api_query_with_session(request: Request, base: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for k in ("token", "user_id", "trading_mode"):
        v = request.query_params.get(k)
        if v is not None and str(v).strip() != "":
            out[k] = v
    return out


def _synthetic_read_api_503() -> requests.Response:
    """Return a JSON 503 without raising (read_api still starting after supervisor restart)."""
    r = requests.Response()
    r.status_code = 503
    r.headers["Content-Type"] = "application/json"
    r._content = json.dumps({"detail": "read_api_temporarily_unavailable"}).encode("utf-8")
    r.encoding = "utf-8"
    return r


async def _proxy_read_api_raw(
    request: Request, method: str, path: str, body: Optional[bytes] = None
):
    url = f"{READ_API_BASE_URL}{path}"
    hdrs = _read_api_forward_headers(request)
    if body is not None:
        hdrs["Content-Type"] = request.headers.get("content-type") or "application/json"

    def _do():
        if method.upper() == "GET":
            return requests.get(url, headers=hdrs, timeout=60)
        if method.upper() == "POST":
            return requests.post(url, data=body if body is not None else b"", headers=hdrs, timeout=60)
        if method.upper() == "PATCH":
            return requests.patch(url, data=body if body is not None else b"", headers=hdrs, timeout=60)
        raise ValueError(method)

    try:
        return await asyncio.to_thread(_do)
    except requests.RequestException as exc:
        _main_logger.debug(
            "read_api proxy transport error %s %s: %s",
            method,
            path,
            exc,
        )
        return _synthetic_read_api_503()


async def _as_starlette_response(r: requests.Response) -> Response:
    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if r.status_code == 204 or not r.content:
        return Response(status_code=r.status_code)
    if "application/json" in ct:
        try:
            return JSONResponse(content=r.json(), status_code=r.status_code)
        except Exception:
            pass
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type"),
    )


def load_preferences():
    global _preferences_cache, _cache_timestamp
    current_time = time.time()
    
    # Return cached version if still valid
    if _preferences_cache is not None and (current_time - _cache_timestamp) < CACHE_TTL:
        return _preferences_cache.copy()
    
    # Load from PostgreSQL - now using strategy-specific endpoints
    try:
        # Default preferences - auto settings now handled by strategy-specific endpoints
        default_prefs = {"diff_mode": False, "position_size": 1, "multiplier": 1}
        
        # Update cache
        _preferences_cache = default_prefs
        _cache_timestamp = current_time
        return default_prefs
    except Exception as e:
        _main_logger.warning(f"[Preferences Load Error] {e}")
        # Default preferences
        default_prefs = {"diff_mode": False, "position_size": 1, "multiplier": 1}
        _preferences_cache = default_prefs
        _cache_timestamp = current_time
        return default_prefs

async def save_preferences(prefs):
    global _preferences_cache, _cache_timestamp
    try:
        # Auto settings now handled by strategy-specific endpoints
        # Only handle non-auto settings here
        
        # Update cache
        _preferences_cache = prefs.copy()
        _cache_timestamp = time.time()
        _main_logger.debug(f"[Preferences] ✅ Updated cache: {list(prefs.keys())}")
    except Exception as e:
        _main_logger.warning(f"[Preferences Save Error] {e}")

# Broadcast helper function for preferences updates
async def broadcast_preferences_update():
    try:
        data = json.dumps(load_preferences())
        to_remove = set()
        
        # Send to all connected clients concurrently
        tasks = []
        for client in _prefs_ws_all_clients():
            task = asyncio.create_task(send_to_client(client, data))
            tasks.append(task)
        
        # Wait for all sends to complete with timeout
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1.0)
        
        # Clean up disconnected clients
        for c in to_remove:
            _prefs_ws_unregister(c)
    except Exception as e:
        _main_logger.warning(f"[Broadcast Preferences Error] {e}")

async def send_to_client(client, data):
    try:
        await client.send_text(data)
    except Exception:
        # Client will be removed in the main function
        pass

# Broadcast helper function for account mode updates
async def broadcast_account_mode(mode: str):
    message = json.dumps({"account_mode": mode})
    to_remove = set()
    for client in _prefs_ws_all_clients():
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    for c in to_remove:
        _prefs_ws_unregister(c)


async def broadcast_trading_mode(mode: str):
    """Notify preferences WebSocket clients of live vs paper (global paper trading)."""
    message = json.dumps(
        {
            "trading_mode": mode,
            "global_paper_mode": mode == "paper",
        }
    )
    to_remove = set()
    for client in _prefs_ws_all_clients():
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    for c in to_remove:
        _prefs_ws_unregister(c)


async def ripple_bankroll_to_monitors():
    """
    After balance source changes (e.g. live vs paper), recompute monitor allotments from
    the active account_balance table via monitor_manager (same path as Kalshi sync_balance).
    """
    def _run():
        try:
            from backend.kalshi_account_sync_ws import notify_monitor_manager

            notify_monitor_manager(False)
        except Exception as e:
            _main_logger.warning("ripple_bankroll_to_monitors: %s", e)

    await asyncio.to_thread(_run)


from backend.web.trading_mode_routes import configure_trading_mode_hooks, trading_mode_router

configure_trading_mode_hooks(
    broadcast_trading_mode=broadcast_trading_mode,
    ripple_bankroll_to_monitors=ripple_bankroll_to_monitors,
)


# Broadcast helper function for database changes
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
    message = json.dumps({
        "type": "db_change",
        "database": db_name,
        "data": change_data,
        "timestamp": now_est().isoformat()
    })
    await _broadcast_db_change_message_text(message)


def _redis_client_for_db_changes_forwarder():
    """Same env contract as redis_switchboard (REDIS_URL or REDIS_HOST/PORT/PASSWORD)."""
    import redis as _redis_mod

    # health_check_interval + periodic get_message timeouts avoid silent pubsub stalls.
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


def _redis_db_changes_subscriber_thread(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
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
            _main_logger.info(
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
                        _log = (
                            _main_logger.debug
                            if is_probably_startup_connect_refused(ping_e)
                            else _main_logger.warning
                        )
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
            _log = (
                _main_logger.debug
                if is_probably_startup_connect_refused(e)
                else _main_logger.warning
            )
            _log(
                "Redis db_changes forwarder: connection issue (%s); retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        except Exception as e:
            _log = (
                _main_logger.debug
                if is_probably_startup_connect_refused(e)
                else _main_logger.warning
            )
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


async def _redis_db_changes_consume_loop(queue: asyncio.Queue) -> None:
    while True:
        try:
            text = await queue.get()
            await _broadcast_db_change_message_text(text)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _main_logger.warning("Redis db_changes consumer: %s", e)


def _redis_trading_preferences_subscriber_thread(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
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
            _main_logger.info(
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
                        _log = (
                            _main_logger.debug
                            if is_probably_startup_connect_refused(ping_e)
                            else _main_logger.warning
                        )
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
            _log = (
                _main_logger.debug
                if is_probably_startup_connect_refused(e)
                else _main_logger.warning
            )
            _log(
                "Redis preferences forwarder: connection issue (%s); retry in %ss",
                e,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 60.0)
        except Exception as e:
            _log = (
                _main_logger.debug
                if is_probably_startup_connect_refused(e)
                else _main_logger.warning
            )
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


async def _redis_trading_preferences_consume_loop(queue: asyncio.Queue) -> None:
    while True:
        try:
            text = await queue.get()
            try:
                obj = json.loads(text)
            except Exception:
                obj = None
            targets = (
                _prefs_recipient_slots_for_redis_message(obj)
                if isinstance(obj, dict)
                else None
            )
            clients = _prefs_ws_clients_for_slots(targets)
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
                _prefs_ws_unregister(c)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _main_logger.warning("Redis preferences consumer: %s", e)


# Lifespan: startup/shutdown (replaces deprecated on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown; use instead of on_event for FastAPI compatibility."""
    try:
        migrate_legacy_state_file()
    except Exception as e:
        _main_logger.warning("migrate_legacy_state_file: %s", e)
    _main_logger.info("Main app started on port %s", MAIN_APP_PORT)
    redis_queue: asyncio.Queue = asyncio.Queue()
    pref_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    consumer = asyncio.create_task(_redis_db_changes_consume_loop(redis_queue))
    pref_consumer = asyncio.create_task(_redis_trading_preferences_consume_loop(pref_queue))
    forwarder_thread = threading.Thread(
        target=_redis_db_changes_subscriber_thread,
        args=(redis_queue, loop),
        daemon=True,
        name="redis_db_changes_forwarder",
    )
    forwarder_thread.start()
    pref_forwarder = threading.Thread(
        target=_redis_trading_preferences_subscriber_thread,
        args=(pref_queue, loop),
        daemon=True,
        name="redis_trading_preferences_forwarder",
    )
    pref_forwarder.start()
    try:
        yield
    finally:
        consumer.cancel()
        pref_consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass
        try:
            await pref_consumer
        except asyncio.CancelledError:
            pass
        _main_logger.info("Main app shutting down")

# Create FastAPI app
app = FastAPI(title="Trading System Main App", lifespan=lifespan)

# Import universal host system
from backend.util.paths import get_host

# Configure CORS with universal host origins
host = get_host()
_explicit_origins = [
    f"http://{host}:{MAIN_APP_PORT}",
    f"http://localhost:{MAIN_APP_PORT}",
    f"http://127.0.0.1:{MAIN_APP_PORT}",
    f"https://{host}:{MAIN_APP_PORT}",
    f"https://localhost:{MAIN_APP_PORT}",
    f"https://127.0.0.1:{MAIN_APP_PORT}",
    "https://rec-io.com",
    "https://www.rec-io.com",
    "http://rec-io.com",
    "http://www.rec-io.com",
]
# Static orderbook UI (e.g. orderbook_ui_redis_server) calls main /api/* with Bearer from another port.
if os.getenv("REC_ENVIRONMENT") != "production":
    _explicit_origins.extend(
        [
            "http://127.0.0.1:8091",
            "http://localhost:8091",
        ]
    )
origins = _explicit_origins if os.getenv("REC_ENVIRONMENT") == "production" else _explicit_origins + ["*"]

from backend.web.tenant_asgi import WebTenantMiddleware

app.add_middleware(WebTenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trading_mode_router, prefix="/api")

from backend.bookkeeper.intuit_oauth_routes import router as intuit_oauth_router

app.include_router(intuit_oauth_router)

# Mount static files with cache busting
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Custom static file handler with cache busting
class CacheBustingStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    async def __call__(self, scope, receive, send):
        # Add cache-busting headers to all static files
        async def send_with_cache_busting(message):
            if message["type"] == "http.response.start":
                message["headers"].extend([
                    (b"cache-control", b"no-cache, no-store, must-revalidate"),
                    (b"pragma", b"no-cache"),
                    (b"expires", b"0")
                ])
            await send(message)
        
        await super().__call__(scope, receive, send_with_cache_busting)

# Mount static files
from backend.util.paths import get_frontend_dir
frontend_dir = get_frontend_dir()

app.mount("/tabs", CacheBustingStaticFiles(directory=f"{frontend_dir}/tabs"), name="tabs")
app.mount("/audio", CacheBustingStaticFiles(directory=f"{frontend_dir}/audio"), name="audio")
app.mount("/js", CacheBustingStaticFiles(directory=f"{frontend_dir}/js"), name="js")
app.mount("/images", CacheBustingStaticFiles(directory=f"{frontend_dir}/images"), name="images")
app.mount("/styles", CacheBustingStaticFiles(directory=f"{frontend_dir}/styles"), name="styles")
app.mount("/data", CacheBustingStaticFiles(directory=f"{frontend_dir}/data"), name="data")
_legal_static = os.path.join(frontend_dir, "legal")
if os.path.isdir(_legal_static):
    app.mount("/legal", CacheBustingStaticFiles(directory=_legal_static), name="legal")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "main_app",
        "port": MAIN_APP_PORT,
        "timestamp": now_est().isoformat(),
        "port_system": "centralized"
    }


@app.get("/api/system/release_version")
async def get_release_version_main() -> Dict[str, Any]:
    """Global deploy label from Redis (same contract as read_api; same-origin for System UI)."""
    ver: Optional[str] = None
    try:
        from backend.core.trading_redis_comms import (
            redis_client_optional,
            redis_key_system_release_version,
        )

        r = redis_client_optional()
        if r:
            raw = r.get(redis_key_system_release_version())
            if raw is not None:
                ver = raw.decode() if isinstance(raw, bytes) else str(raw)
                ver = ver.strip() or None
    except Exception:
        ver = None
    return {"version": ver}


# Port information endpoint
@app.get("/api/ports")
async def get_ports(request: Request):
    """Get all port assignments from centralized system."""
    port_info = get_port_info()
    
    # Get the current request's protocol
    protocol = request.headers.get("x-forwarded-proto", "http")
    if protocol == "https":
        # Update service URLs to use HTTPS
        host = port_info["host"]
        ports = port_info["ports"]
        port_info["service_urls"] = {name: f"https://{host}:{port}" for name, port in ports.items()}
    
    return port_info

# Test endpoint
@app.get("/api/test-health")
async def test_health():
    """Test endpoint to verify routing works."""
    return {"message": "Test health endpoint working"}

# System health endpoint
@app.get("/api/system-health")
async def get_system_health():
    """Get comprehensive system health status."""
    try:
        # Import system monitor
        from backend.system_monitor import SystemMonitor
        
        # Create system monitor instance and generate health report
        monitor = SystemMonitor()
        health_report = monitor.generate_health_report()
        
        # Determine overall system status
        overall_status = "healthy"
        issues = []
        
        # Check supervisor status
        if health_report.get("supervisor_status", {}).get("status") != "running":
            overall_status = "offline"
            issues.append("Supervisor not running")
        
        # Check critical services
        critical_services = [
            "main_app",
            user_scoped_service_name("trade_manager"),
            user_scoped_service_name("trade_executor"),
            unified_active_trade_supervisor_service_name(),
        ]
        unhealthy_services = []
        
        for service in critical_services:
            service_status = health_report.get("services", {}).get(service, {})
            if service_status.get("status") != "healthy":
                unhealthy_services.append(service)
        
        if unhealthy_services:
            if len(unhealthy_services) >= len(critical_services) // 2:
                overall_status = "offline"
            else:
                overall_status = "degraded"
            issues.append(f"Unhealthy services: {', '.join(unhealthy_services)}")
        
        # Check database health
        db_health = health_report.get("database_health", {})
        if db_health.get("status") != "healthy":
            overall_status = "degraded"
            issues.append("Database issues detected")
        
        return {
            "status": overall_status,
            "issues": issues,
            "timestamp": now_est().isoformat(),
            "health_report": health_report
        }
        
    except Exception as e:
        return {
            "status": "offline",
            "issues": [f"System monitor error: {str(e)}"],
            "timestamp": now_est().isoformat(),
            "error": str(e)
        }

# WebSocket endpoint for preferences updates
@app.websocket("/ws/preferences")
async def websocket_preferences(websocket: WebSocket):
    from backend.web.tenant_asgi import resolve_session_user_no_from_asgi_scope

    user_no = resolve_session_user_no_from_asgi_scope(websocket.scope)
    if not user_no:
        await websocket.close(code=4401, reason="Not authenticated")
        return
    # Omit Sec-WebSocket-Protocol on accept even if the client sent the token there:
    # echoing a long token_urlsafe value breaks some browsers (abnormal close 1006).
    await websocket.accept()
    _prefs_ws_register(websocket, user_no)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        pass
    finally:
        _prefs_ws_unregister(websocket)

@app.websocket("/ws/db_changes")
async def websocket_db_changes(websocket: WebSocket):
    from backend.web.tenant_asgi import resolve_session_user_no_from_asgi_scope

    if not resolve_session_user_no_from_asgi_scope(websocket.scope):
        await websocket.close(code=4401, reason="Not authenticated")
        return
    await websocket.accept()
    db_change_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        db_change_clients.discard(websocket)


# Serve main index.html
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the main application or login page based on authentication."""
    _main_logger.debug(f"[AUTH] AUTH_ENABLED = {AUTH_ENABLED}")
    if AUTH_ENABLED:
        # Always redirect to login - no direct access to main app
        _main_logger.debug(f"[AUTH] Redirecting to login page")
        return RedirectResponse(url="/login")
    else:
        # Local development mode - serve main app directly
        _main_logger.debug(f"[AUTH] Serving main app directly (local development)")
        with open(f"{frontend_dir}/index.html", "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )

@app.get("/app", response_class=HTMLResponse)
async def serve_main_app(request: Request):
    """Serve the main application (protected route)."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    # Serve the main app
    with open(f"{frontend_dir}/index.html", "r") as f:
        content = f.read()
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    """Serve the login page."""
    try:
        with open(f"{frontend_dir}/login.html", "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Login</h1><p>Login page not found.</p>", status_code=404)


def _html_no_cache_headers() -> dict:
    return {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }


@app.get("/register", response_class=HTMLResponse)
async def serve_register():
    """Serve master-user self-registration form (frontend/register.html)."""
    try:
        with open(os.path.join(frontend_dir, "register.html"), "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content, headers=_html_no_cache_headers())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Register</h1><p>register.html not found.</p>",
            status_code=404,
        )


@app.get("/register/verify", response_class=HTMLResponse)
async def serve_register_verify():
    """Email verification code entry (frontend/register-verify.html)."""
    try:
        with open(os.path.join(frontend_dir, "register-verify.html"), "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content, headers=_html_no_cache_headers())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Verify</h1><p>register-verify.html not found.</p>",
            status_code=404,
        )


@app.get("/register/application-submitted", response_class=HTMLResponse)
async def serve_register_application_submitted():
    """Post-verification holding page (frontend/register-application-submitted.html)."""
    try:
        with open(
            os.path.join(frontend_dir, "register-application-submitted.html"),
            "r",
            encoding="utf-8",
        ) as f:
            content = f.read()
        return HTMLResponse(content=content, headers=_html_no_cache_headers())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Application submitted</h1><p>register-application-submitted.html not found.</p>",
            status_code=404,
        )


# Serve favicon
@app.get("/favicon.ico")
async def serve_favicon():
    """Serve favicon."""
    from fastapi.responses import FileResponse
    import os
    file_path = os.path.join("frontend", "images", "icons", "fave.ico")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    else:
        return {"error": "Favicon not found"}, 404

# Serve terminal control page
@app.get("/terminal-control.html", response_class=HTMLResponse)
async def serve_terminal_control():
    """Serve terminal control page."""
    import os
    file_path = f"{frontend_dir}/terminal-control.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(content="<h1>Terminal Control not found</h1>", status_code=404)

# Serve log viewer page
@app.get("/log-viewer.html", response_class=HTMLResponse)
async def serve_log_viewer():
    """Serve log viewer page."""
    import os
    file_path = f"{frontend_dir}/log-viewer.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(content="<h1>Log Viewer not found</h1>", status_code=404)

# Serve CSS files with cache busting
@app.get("/styles/{filename:path}")
async def serve_css(filename: str):
    """Serve CSS files with cache busting headers."""
    file_path = f"{frontend_dir}/styles/{filename}"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Type": "text/css",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="CSS file not found", status_code=404)

# Serve JS files with cache busting
@app.get("/js/{filename:path}")
async def serve_js(filename: str):
    """Serve JS files with cache busting headers."""
    file_path = f"{frontend_dir}/js/{filename}"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Type": "application/javascript",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="JS file not found", status_code=404)

# Serve mobile trade monitor with cache busting
@app.get("/mobile/trade_monitor", response_class=HTMLResponse)
async def serve_mobile_trade_monitor(request: Request):
    """Serve mobile trade monitor with cache busting headers."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/trade_monitor_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
            return HTMLResponse(content="Mobile trade monitor not found", status_code=404)

# Serve mobile dashboard with cache busting
@app.get("/mobile/dashboard", response_class=HTMLResponse)
async def serve_mobile_dashboard(request: Request):
    """Serve mobile dashboard with cache busting headers."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/dashboard_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile dashboard not found", status_code=404)


@app.get("/mobile/dashboard_new", response_class=HTMLResponse)
async def serve_mobile_dashboard_new(request: Request):
    """Serve Phase C dashboard shell (rollup strip + TD/PREV); cache-busted like /mobile/dashboard."""
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")

    file_path = f"{frontend_dir}/mobile/dashboard_mobile_NEW.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse(content="Mobile dashboard NEW not found", status_code=404)


# Serve mobile account manager with cache busting
@app.get("/mobile/account_manager", response_class=HTMLResponse)
async def serve_mobile_account_manager(request: Request):
    """Serve mobile account manager with cache busting headers."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/account_manager_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile account manager not found", status_code=404)

# Serve mobile index with cache busting
@app.get("/mobile", response_class=HTMLResponse)
async def serve_mobile_index(request: Request):
    """Serve mobile index with cache busting headers."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/index.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile index not found", status_code=404)

# Serve mobile index.html directly (for direct access)
@app.get("/mobile/index.html", response_class=HTMLResponse)
async def serve_mobile_index_html(request: Request):
    """Serve mobile index.html directly with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/index.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile index not found", status_code=404)

# Test route for debugging
@app.get("/test-mobile")
async def test_mobile():
    """Test route for debugging mobile routes."""
    return {"message": "Mobile test route works!"}

# Test route for monitor history display
@app.get("/test_monitor_history_display.html", response_class=HTMLResponse)
async def serve_test_monitor_history_display():
    """Serve the test page for monitor history display."""
    file_path = f"{frontend_dir}/test_monitor_history_display.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Test page not found", status_code=404)

# Test route for debugging mobile path
@app.get("/mobile/test")
async def test_mobile_path():
    """Test route for debugging mobile path."""
    return {"message": "Mobile path test route works!"}

# Serve mobile user settings with authentication
@app.get("/mobile/user", response_class=HTMLResponse)
async def serve_mobile_user(request: Request):
    """Serve mobile user settings with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/user_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile user settings not found", status_code=404)

# Serve mobile system with authentication
@app.get("/mobile/system", response_class=HTMLResponse)
async def serve_mobile_system(request: Request):
    """Serve mobile system page with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/system_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile system page not found", status_code=404)

# Serve mobile trade history with authentication
@app.get("/mobile/trade_history", response_class=HTMLResponse)
async def serve_mobile_trade_history(request: Request):
    """Serve mobile trade history with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        if not _query_token_auth_ok(request):
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/trade_history_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile trade history not found", status_code=404)

def get_ttc_data_from_postgresql() -> Dict[str, Any]:
    """Get TTC data directly from PostgreSQL"""
    try:
        from datetime import timedelta

        # Calculate TTC (time to next hour)
        ne = now_est()
        next_hour = ne.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        ttc_seconds = int((next_hour - ne).total_seconds())
        
        return {
            'ttc_seconds': ttc_seconds,
            'timestamp': ne.isoformat(),
            'current_time_est': ne.strftime("%I:%M:%S %p %Z"),
            'next_hour_est': next_hour.strftime("%I:%M:%S %p %Z")
        }
    except Exception as e:
        _main_logger.warning(f"Error calculating TTC: {e}")
        return {"error": str(e)}

@app.get("/api/ttc")
async def get_ttc_data():
    """Get time to close data directly from PostgreSQL."""
    return get_ttc_data_from_postgresql()

# Core data endpoint
@app.get("/core")
async def get_core_data(symbol: str = "BTC"):
    """Get core trading data for specified symbol."""
    try:
        # Get current time
        now = now_est()
        date_str = now.strftime("%A, %B %d, %Y")
        time_str = now.strftime("%I:%M:%S %p %Z")
        
        # Get TTC directly from PostgreSQL
        ttc_seconds = 0
        try:
            ttc_data = get_ttc_data_from_postgresql()
            ttc_seconds = ttc_data.get('ttc_seconds', 0)
        except Exception as e:
            _main_logger.warning(f"Error getting TTC from PostgreSQL: {e}")
            # Fallback calculation
            close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
            if now.time() >= close_time.time():
                close_time += timedelta(days=1)
            ttc_seconds = int((close_time - now).total_seconds())
        
        # Get BTC price from PostgreSQL live_data
        btc_price = 0
        try:
            # Get the latest price from PostgreSQL live_data.live_price_log_1s_btc
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
            result = cursor.fetchone()
            conn.close()
            
            if result:
                btc_price = float(result[0])
                _main_logger.debug(f"[MAIN] Using PostgreSQL BTC price: ${btc_price:,.2f}")
            else:
                # Fallback to direct API call if no PostgreSQL data
                response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    btc_price = float(data['result']['XXBTZUSD']['c'][0])
                    _main_logger.debug(f"[MAIN] Using fallback API BTC price: ${btc_price:,.2f}")
        except Exception as e:
            _main_logger.warning(f"Error fetching BTC price from PostgreSQL: {e}")
            # Final fallback to direct API call
            try:
                response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    btc_price = float(data['result']['XXBTZUSD']['c'][0])
                    _main_logger.debug(f"[MAIN] Using emergency fallback API BTC price: ${btc_price:,.2f}")
            except Exception as e2:
                _main_logger.warning(f"Emergency fallback also failed: {e2}")
        
        # Get momentum data directly from PostgreSQL
        momentum_data = {}
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg,
                       move_1m, move_2m, move_3m, move_4m, movement, movement_percentile
                FROM live_data.live_price_log_1s_{symbol.lower()}
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result:
                (momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg,
                 move_1m, move_2m, move_3m, move_4m, movement, movement_percentile) = result
                momentum_data = {
                    'weighted_momentum_score': float(momentum) if momentum is not None else 0.0,
                    'delta_1m': float(delta_1m) if delta_1m is not None else None,
                    'delta_2m': float(delta_2m) if delta_2m is not None else None,
                    'delta_3m': float(delta_3m) if delta_3m is not None else None,
                    'delta_4m': float(delta_4m) if delta_4m is not None else None,
                    'delta_15m': float(delta_15m) if delta_15m is not None else None,
                    'delta_30m': float(delta_30m) if delta_30m is not None else None,
                    'momentum_percentile': float(momentum_percentile) if momentum_percentile is not None else None,
                    'momentum_5s_avg': float(momentum_5s_avg) if momentum_5s_avg is not None else None,
                    'move_1m': float(move_1m) if move_1m is not None else None,
                    'move_2m': float(move_2m) if move_2m is not None else None,
                    'move_3m': float(move_3m) if move_3m is not None else None,
                    'move_4m': float(move_4m) if move_4m is not None else None,
                    'movement': float(movement) if movement is not None else None,
                    'movement_percentile': float(movement_percentile) if movement_percentile is not None else None,
                }
                _main_logger.debug(f"[MAIN] Momentum analysis: {momentum_data.get('weighted_momentum_score', 'N/A'):.4f}%")
            else:
                momentum_data = {
                    'delta_1m': None,
                    'delta_2m': None,
                    'delta_3m': None,
                    'delta_4m': None,
                    'delta_15m': None,
                    'delta_30m': None,
                    'weighted_momentum_score': None,
                    'move_1m': None, 'move_2m': None, 'move_3m': None, 'move_4m': None,
                    'movement': None, 'movement_percentile': None,
                }
        except Exception as e:
            _main_logger.warning(f"Error getting momentum data from PostgreSQL: {e}")
            momentum_data = {
                'delta_1m': None,
                'delta_2m': None,
                'delta_3m': None,
                'delta_4m': None,
                'delta_15m': None,
                'delta_30m': None,
                'weighted_momentum_score': None,
                'move_1m': None, 'move_2m': None, 'move_3m': None, 'move_4m': None,
                'movement': None, 'movement_percentile': None,
            }
        
        # Get latest database price from PostgreSQL
        latest_db_price = 0
        try:
            conn = get_postgresql_connection()
            slot_price = resolved_tenant_user_no_for_app()
            with conn.cursor() as cursor:
                if fetch_master_trades_column_names(cursor, slot_price):
                    union_sql, _ = union_trades_with_archives_select(cursor, slot_price)
                    cursor.execute(
                        f"""
                        SELECT buy_price FROM ({union_sql}) AS all_trades
                        WHERE test_filter IS NULL OR test_filter = FALSE
                        ORDER BY date DESC, time DESC LIMIT 1
                        """
                    )
                    result = cursor.fetchone()
                    if result:
                        latest_db_price = result[0]
            conn.close()
        except Exception as e:
            _main_logger.warning(f"Error getting latest DB price: {e}")
        
        # Get Kraken changes
        kraken_changes = {}
        try:
            response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
            if response.status_code == 200:
                data = response.json()
                ticker = data['result']['XXBTZUSD']
                
                # Calculate changes
                current_price = float(ticker['c'][0])
                for period in ['1h', '3h', '1d']:
                    if period == '1h':
                        old_price = float(ticker['p'][0])  # 24h low as proxy
                    elif period == '3h':
                        old_price = float(ticker['p'][0])  # 24h low as proxy
                    else:  # 1d
                        old_price = float(ticker['p'][0])  # 24h low as proxy
                    
                    change = (current_price - old_price) / old_price
                    kraken_changes[f"change{period}"] = change
        except Exception as e:
            _main_logger.warning(f"Error getting Kraken changes: {e}")
        
        # Get Kalshi markets (placeholder)
        kalshi_markets = []
        
        return {
            "date": date_str,
            "time": time_str,
            "ttc_seconds": ttc_seconds,
            "btc_price": btc_price,
            "latest_db_price": latest_db_price,
            "timestamp": now_est().isoformat(),
            **momentum_data,  # Include all momentum deltas and weighted score
            "status": "online",
            "volScore": 0,
            "volSpike": 0,
            **kraken_changes,
            "kalshi_markets": kalshi_markets
        }
    except Exception as e:
        _main_logger.warning(f"Error in core data: {e}")
        return {"error": str(e)}

# Account mode endpoints
@app.get("/api/get_account_mode")
async def get_account_mode_endpoint():
    """Get current account mode."""
    return {"mode": get_account_mode()}


@app.get("/api/system_settings")
async def get_system_settings_endpoint(response: Response):
    """Global system settings (drawdown halt, threshold) for dashboard gear menu."""
    _api_no_store_headers(response)
    from backend.core.system_settings_store import fetch_system_settings_row

    num = resolved_tenant_user_no_for_app()
    row = fetch_system_settings_row(num)
    if not row:
        return {"status": "error", "message": "system_settings not available for user"}
    return {"status": "ok", "user_number": num, **row}


@app.post("/api/system_settings")
async def post_system_settings_endpoint(payload: dict):
    """Update system settings. Optional action: clear_trading_halt_alert | restore_trade_operations."""
    from backend.core.system_settings_store import (
        clear_trading_halt_alert,
        fetch_system_settings_row,
        restore_trade_operations_from_snapshot,
        update_system_settings_drawdown,
    )

    body = payload or {}
    num = resolved_tenant_user_no_for_app()
    action = str(body.get("action") or "").strip().lower()

    if action == "clear_trading_halt_alert":
        ok, msg = clear_trading_halt_alert(num)
        if not ok:
            return {"status": "error", "message": msg}
        row = fetch_system_settings_row(num)
        return {"status": "ok", "user_number": num, **(row or {}), "message": "trading_halt_active cleared"}

    if action == "restore_trade_operations":
        ok, msg, restored = restore_trade_operations_from_snapshot(num)
        if not ok:
            return {"status": "error", "message": msg}
        row = fetch_system_settings_row(num)
        return {
            "status": "ok",
            "user_number": num,
            **(row or {}),
            "monitors_restore_updates": restored,
            "message": "monitors restored from saved snapshot; trading_halt_active cleared (snapshot retained)",
        }

    if action:
        return {"status": "error", "message": f"unknown action: {action}"}

    halt = body.get("drawdown_trading_halt")
    pct = body.get("drawdown_reset_threshold_pct")
    if halt is not None and not isinstance(halt, bool):
        if str(halt).lower() in ("true", "1", "yes"):
            halt = True
        elif str(halt).lower() in ("false", "0", "no"):
            halt = False
        else:
            return {"status": "error", "message": "drawdown_trading_halt must be boolean"}
    if pct is not None:
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            return {"status": "error", "message": "drawdown_reset_threshold_pct must be a number"}
    ok, msg = update_system_settings_drawdown(
        num,
        drawdown_trading_halt=halt,
        drawdown_reset_threshold_pct=pct,
    )
    if not ok:
        return {"status": "error", "message": msg}
    row = fetch_system_settings_row(num)
    return {"status": "ok", "user_number": num, **(row or {})}


@app.post("/api/paper/bankroll/seed")
async def seed_paper_bankroll_endpoint(payload: dict):
    """Set initial paper bankroll (cents). User-configured only."""
    try:
        cents = (payload or {}).get("bankroll_cents")
        if cents is None:
            return {"status": "error", "message": "bankroll_cents required"}
        try:
            c = int(cents)
        except (TypeError, ValueError):
            return {"status": "error", "message": "bankroll_cents must be an integer"}
        if c < 0:
            return {"status": "error", "message": "bankroll_cents must be non-negative"}
        from backend.paper_bankroll import seed_paper_bankroll_cents

        try:
            if not seed_paper_bankroll_cents(c):
                return {"status": "error", "message": "database unavailable"}
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        await broadcast_db_change("account_balance_paper", {"source": "seed"})
        await broadcast_db_change("subaccounts", {"source": "paper_seed"})
        return {"status": "ok", "bankroll_cents": c}
    except Exception as e:
        _main_logger.warning("paper bankroll seed: %s", e)
        return {"status": "error", "message": str(e)}


@app.post("/api/set_account_mode")
async def set_account_mode(mode_data: dict):
    """Legacy: Kalshi env is prod only; demo requests are coerced to prod."""
    from backend.account_mode import set_account_mode as _set_am

    mode = mode_data.get("mode")
    if mode in ("prod", "demo"):
        _set_am("prod")
        return {"status": "success", "mode": "prod"}
    return {"status": "error", "message": "Invalid mode"}

# Trade data endpoints — GET /trades is implemented on read_api; main proxies for same-origin cookies.
@app.get("/trades")
async def get_trades_proxy(request: Request):
    """Proxy to read_api: tenant trade list (paginated or full)."""
    q = request.url.query
    path = f"/trades?{q}" if q else "/trades"
    r = await _proxy_read_api_raw(request, "GET", path)
    return await _as_starlette_response(r)


@app.post("/api/trades/history/insights")
async def trade_history_insights_proxy(request: Request):
    """Proxy to read_api: summary + analysis over full filtered trade set."""
    body = await request.body()
    r = await _proxy_read_api_raw(
        request, "POST", "/api/trades/history/insights", body
    )
    return await _as_starlette_response(r)


@app.get("/api/get_trade_history_preferences")
async def get_trade_history_preferences_route():
    """Trade history UI prefs: same process/session as the tab (no read_api hop)."""
    from backend.core.trade_history_preferences_handlers import trade_history_preferences_get

    return trade_history_preferences_get()


@app.post("/api/set_trade_history_preferences")
async def set_trade_history_preferences_route(request: Request):
    """Persist trade history UI prefs; Redis fanout for /ws/preferences."""
    from backend.core.trade_history_preferences_handlers import trade_history_preferences_post

    return await trade_history_preferences_post(request)


@app.get("/trades/{trade_id}")
async def get_trade(trade_id: int):
    """Forward trade GET request to trade_manager."""
    try:
        # Get trade_manager port from centralized system
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades/{trade_id}"
        
        _main_logger.debug(f"[MAIN] Forwarding trade GET request to trade_manager at {trade_manager_url}")
        
        # Forward the request to trade_manager
        response = requests.get(
            trade_manager_url,
            timeout=10
        )
        
        if response.status_code == 200:
            _main_logger.debug(f"[MAIN] ✅ Trade GET request forwarded successfully to trade_manager")
            return response.json()
        else:
            _main_logger.warning(f"[MAIN] ❌ Trade GET request forwarding failed: {response.status_code}")
            return {"error": f"Trade manager returned status {response.status_code}"}
            
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error forwarding trade GET request: {e}")
        return {"error": str(e)}

@app.post("/trades")
async def create_trade(trade_data: dict):
    """Forward trade ticket to trade_manager."""
    try:
        # Get trade_manager port from centralized system
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades"
        
        _main_logger.debug(f"[MAIN] Forwarding trade ticket to trade_manager at {trade_manager_url}")
        
        # Forward the request to trade_manager
        response = requests.post(
            trade_manager_url,
            json=trade_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 201:
            _main_logger.debug(f"[MAIN] ✅ Trade ticket forwarded successfully to trade_manager")
            return response.json()
        else:
            _main_logger.warning(f"[MAIN] ❌ Trade ticket forwarding failed: {response.status_code}")
            return {"error": f"Trade manager returned status {response.status_code}"}
            
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error forwarding trade ticket: {e}")
        return {"error": str(e)}

# Additional endpoints for other data
@app.get("/btc_price_changes")
async def get_btc_changes():
    """Get BTC price changes from PostgreSQL live_data.price_change_btc."""
    try:
        import psycopg2
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        
        # Get latest price changes from the database
        cursor.execute("""
            SELECT change1h, change3h, change1d, timestamp 
            FROM live_data.price_change_btc 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            changes = {
                "change1h": float(result[0]) if result[0] is not None else None,
                "change3h": float(result[1]) if result[1] is not None else None,
                "change1d": float(result[2]) if result[2] is not None else None,
                "timestamp": result[3].isoformat() if result[3] else now_est().isoformat()
            }
        else:
            changes = {"change1h": None, "change3h": None, "change1d": None, "timestamp": now_est().isoformat()}
        
        return changes
        
    except Exception as e:
        _main_logger.warning(f"[btc_price_changes API] Error reading from PostgreSQL: {e}")
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": None}

@app.get("/eth_price_changes")
async def get_eth_changes():
    """Get ETH price changes from PostgreSQL live_data.price_change_eth."""
    try:
        import psycopg2
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        
        # Get latest price changes from the database
        cursor.execute("""
            SELECT change1h, change3h, change1d, timestamp 
            FROM live_data.price_change_eth 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            changes = {
                "change1h": float(result[0]) if result[0] is not None else None,
                "change3h": float(result[1]) if result[1] is not None else None,
                "change1d": float(result[2]) if result[2] is not None else None,
                "timestamp": result[3].isoformat() if result[3] else now_est().isoformat()
            }
        else:
            changes = {"change1h": None, "change3h": None, "change1d": None, "timestamp": now_est().isoformat()}
        
        return changes
        
    except Exception as e:
        _main_logger.warning(f"[eth_price_changes API] Error reading from PostgreSQL: {e}")
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": None}

@app.get("/kalshi_market_snapshot")
async def get_kalshi_snapshot():
    """Get Kalshi market snapshot from PostgreSQL."""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor() as cursor:
            # Get market data from PostgreSQL
            cursor.execute("""
                SELECT 
                    market_ticker,
                    yes_ask_dollars,
                    no_ask_dollars,
                    yes_bid_dollars,
                    no_bid_dollars,
                    last_price_dollars,
                    volume_fp,
                    open_interest_fp,
                    event_ticker,
                    strike
                FROM live_data.market_kalshi_hourly
                WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                  AND UPPER(TRIM(symbol::text)) = 'BTC'
                ORDER BY updated_at DESC
            """)
            
            markets_data = cursor.fetchall()
            conn.close()
            
            if not markets_data:
                return {"markets": []}
            
            markets = []
            for row in markets_data:
                market = {
                    "ticker": row[0],
                    "yes_ask_dollars": row[1],
                    "no_ask_dollars": row[2],
                    "yes_bid_dollars": row[3],
                    "no_bid_dollars": row[4],
                    "last_price_dollars": row[5],
                    "volume_fp": row[6],
                    "open_interest_fp": row[7],
                    "event_ticker": row[8],
                    "strike": row[9],
                }
                markets.append(market)
            
            # Return in the same format as the JSON file
            return {
                "markets": markets,
                "timestamp": now_est().isoformat()
            }
            
    except Exception as e:
        _main_logger.warning(f"Error getting Kalshi snapshot from PostgreSQL: {e}")
        return {"markets": []}

# API endpoints for account data
@app.post("/api/account/sync")
async def trigger_account_sync():
    """Trigger a full account retrieval cycle from kalshi_account_sync (balance, subaccounts, account history). Runs in background; returns immediately."""
    import threading
    def _run_sync():
        try:
            from backend.kalshi_account_sync_ws import sync_balance
            sync_balance()
        except Exception as e:
            _main_logger.warning(f"account/sync: sync_balance failed: {e}")
    threading.Thread(target=_run_sync, daemon=True).start()
    return {"ok": True}

def _api_no_store_headers(response: Response) -> None:
    """Avoid stale browser/CDN cache of JSON that differs by trading_mode."""
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"


@app.get("/api/account/balance")
async def get_account_balance(
    response: Response,
    mode: str = "prod",
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — must match UI toggle; same table selection as portfolio chart",
    ),
):
    """Get account balance from PostgreSQL database."""
    _api_no_store_headers(response)
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        if not conn:
            _main_logger.error(
                "get_account_balance: database connection unavailable "
                "(check main_app logs for 'Failed to open tenant PostgreSQL connection')"
            )
            return {
                "portfolio": 0,
                "positions": 0,
                "bankroll_current": 0,
                "mtb_base_value": None,
                "master_trading_bankroll": None,
            }

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            ab_ident = sql_ident_qualified_table(
                account_balance_table_for_user(
                    resolved_tenant_user_no_for_app(),
                    client_trading_mode=trading_mode,
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                SELECT portfolio, positions, bankroll_current, mtb_base_value, master_trading_bankroll
                FROM {}
                ORDER BY id DESC
                LIMIT 1
                """
                ).format(ab_ident)
            )
            balance_result = cursor.fetchone()
            
            
            conn.close()
            
            if balance_result:
                portfolio_value = balance_result['portfolio']
                positions_value = balance_result['positions'] if balance_result else 0
                bankroll_current = balance_result['bankroll_current'] if balance_result else 0
                mtb_base_value = balance_result.get('mtb_base_value')
                master_trading_bankroll = balance_result.get('master_trading_bankroll')
                return {
                    "portfolio": portfolio_value,
                    "positions": positions_value,
                    "bankroll_current": bankroll_current,
                    "mtb_base_value": mtb_base_value,
                    "master_trading_bankroll": master_trading_bankroll,
                }
            else:
                return {
                    "portfolio": 0,
                    "positions": 0,
                    "bankroll_current": 0,
                    "mtb_base_value": None,
                    "master_trading_bankroll": None,
                }
            
    except Exception as e:
        _main_logger.warning(f"Error getting account balance from PostgreSQL: {e}")
        return {
            "portfolio": 0,
            "positions": 0,
            "bankroll_current": 0,
            "mtb_base_value": None,
            "master_trading_bankroll": None,
        }

@app.get("/api/subaccounts")
async def get_subaccounts(response: Response, trading_mode: Optional[str] = None):
    """Get subaccounts for display (live or paper table). Balances in cents."""
    _api_no_store_headers(response)
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = get_postgresql_connection()
        if not conn:
            _main_logger.error(
                "get_subaccounts: database connection unavailable "
                "(check main_app logs for 'Failed to open tenant PostgreSQL connection')"
            )
            return {"subaccounts": []}
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(
                    resolved_tenant_user_no_for_app(), client_trading_mode=trading_mode
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                SELECT id, subaccount, balance, base_value, realized_pnl, realized_pnl_pct,
                       target_pnl__pct, transfer_amt, automatic_transfers
                FROM {}
                ORDER BY id
                """
                ).format(sa_ident)
            )
            rows = cursor.fetchall()
        conn.close()
        return {"subaccounts": [dict(r) for r in rows]}
    except Exception as e:
        _main_logger.warning(f"Error getting subaccounts from PostgreSQL: {e}")
        return {"subaccounts": []}

@app.patch("/api/subaccounts/automatic-transfers")
async def update_subaccount_automatic_transfers(request: Request):
    """Set automatic_transfers for a subaccount by name. Body: { \"subaccount\": \"Master Trading Bankroll\", \"automatic_transfers\": true }."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        automatic = payload.get("automatic_transfers")
        if subaccount_name is None or automatic is None:
            return {"ok": False, "error": "subaccount and automatic_transfers required"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            cursor.execute(
                sql.SQL("UPDATE {} SET automatic_transfers = %s WHERE subaccount = %s").format(sa_ident),
                (bool(automatic), subaccount_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error updating subaccount automatic_transfers: {e}")
        return {"ok": False, "error": str(e)}

@app.patch("/api/subaccounts/transfer-settings")
async def update_subaccount_transfer_settings(request: Request):
    """Set target_pnl__pct and/or transfer_amt for a subaccount. Body: { \"subaccount\": \"Master Trading Bankroll\", \"target_pnl__pct\": 0.115, \"transfer_amt\": 0.10 } (fractions)."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        target_pct = payload.get("target_pnl__pct")
        transfer_amt = payload.get("transfer_amt")
        if subaccount_name is None:
            return {"ok": False, "error": "subaccount required"}
        if target_pct is None and transfer_amt is None:
            return {"ok": False, "error": "at least one of target_pnl__pct or transfer_amt required"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            if target_pct is not None and transfer_amt is not None:
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET target_pnl__pct = %s, transfer_amt = %s WHERE subaccount = %s"
                    ).format(sa_ident),
                    (float(target_pct), float(transfer_amt), subaccount_name),
                )
            elif target_pct is not None:
                cursor.execute(
                    sql.SQL("UPDATE {} SET target_pnl__pct = %s WHERE subaccount = %s").format(sa_ident),
                    (float(target_pct), subaccount_name),
                )
            else:
                cursor.execute(
                    sql.SQL("UPDATE {} SET transfer_amt = %s WHERE subaccount = %s").format(sa_ident),
                    (float(transfer_amt), subaccount_name),
                )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error updating subaccount transfer settings: {e}")
        return {"ok": False, "error": str(e)}


@app.patch("/api/subaccounts/base-value")
async def update_subaccount_base_value(request: Request):
    """Set base_value (cents) for a subaccount. Body: { \"subaccount\": \"Master Trading Bankroll\", \"base_value\": 84329 } (base_value in cents)."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        base_value = payload.get("base_value")
        if subaccount_name is None:
            return {"ok": False, "error": "subaccount required"}
        if base_value is None:
            return {"ok": False, "error": "base_value required"}
        try:
            base_value_int = int(base_value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "base_value must be an integer (cents)"}
        if base_value_int < 0:
            return {"ok": False, "error": "base_value must be non-negative"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
            cursor.execute(
                sql.SQL("UPDATE {} SET base_value = %s WHERE subaccount = %s").format(sa_ident),
                (base_value_int, subaccount_name),
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error updating subaccount base_value: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/api/subaccounts/initiate-transfer")
async def initiate_transfer(request: Request):
    """
    Manual internal transfer between subaccounts (e.g. Cash Transfer ↔ Master Trading Bankroll).
    Body: { "from": "...", "to": "...", "amount": 100 } (amount in dollars).
    Inserts into transfers (live or paper), updates subaccounts. If Master Trading Bankroll is the
    from or to side, appends an account_balance row with bankroll_current and master_trading_bankroll
    set to the new MTB balance and notifies monitor_manager to refresh monitor allocations (live and paper).
    In live mode, kalshi_account_sync sync_balance runs only when MTB is not involved (rare); CT↔MTB
    reshuffles local slices only and does not change Kalshi totals.
    """
    try:
        payload = await request.json()
        from_name = payload.get("from")
        to_name = payload.get("to")
        amount_dollars = payload.get("amount")
        if not from_name or not to_name:
            return {"ok": False, "error": "from and to required"}
        if from_name == "PRIMARY" or to_name == "PRIMARY":
            return {"ok": False, "error": "PRIMARY cannot be from or to"}
        if from_name == "External" or to_name == "External":
            return {"ok": False, "error": "External transfers not supported yet"}
        if from_name == to_name:
            return {"ok": False, "error": "from and to must differ"}
        try:
            amount_val = float(amount_dollars)
        except (TypeError, ValueError):
            return {"ok": False, "error": "amount must be a number"}
        if amount_val <= 0:
            return {"ok": False, "error": "amount must be positive"}
        amount_cents = int(round(amount_val * 100))

        import psycopg2
        from zoneinfo import ZoneInfo
        from datetime import datetime
        EST = ZoneInfo("America/New_York")
        transfer_timestamp_est = now_est().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                sa_ident = sql_ident_qualified_table(
                subaccounts_table_for_user(resolved_tenant_user_no_for_app())
            )
                cursor.execute(
                    sql.SQL("SELECT balance FROM {} WHERE subaccount = %s").format(sa_ident),
                    (from_name,),
                )
                row = cursor.fetchone()
                if not row:
                    return {"ok": False, "error": f"subaccount not found: {from_name}"}
                from_balance = int(row[0]) if row[0] is not None else 0
                if from_balance < amount_cents:
                    return {"ok": False, "error": f"insufficient balance in {from_name}"}
                cursor.execute(
                    sql.SQL("SELECT 1 FROM {} WHERE subaccount = %s").format(sa_ident),
                    (to_name,),
                )
                if not cursor.fetchone():
                    return {"ok": False, "error": f"subaccount not found: {to_name}"}

                xfer_ident = sql_ident_qualified_table(
                    transfers_table_for_user(resolved_tenant_user_no_for_app())
                )
                insert_xfer = sql.SQL(
                    """
                    INSERT INTO {} (timestamp, type, "from", "to", amount, initiated)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """
                ).format(xfer_ident)
                cursor.execute(
                    insert_xfer,
                    (transfer_timestamp_est, "internal", from_name, to_name, amount_cents, "manual"),
                )
                cursor.execute(
                    sql.SQL("UPDATE {} SET balance = balance - %s WHERE subaccount = %s").format(sa_ident),
                    (amount_cents, from_name),
                )
                cursor.execute(
                    sql.SQL("UPDATE {} SET balance = balance + %s WHERE subaccount = %s").format(sa_ident),
                    (amount_cents, to_name),
                )
                conn.commit()
        finally:
            conn.close()

        # Notify frontend so Account Information panel refreshes immediately (subaccounts + transfers table)
        await broadcast_db_change("subaccounts", {"source": "initiate_transfer"})
        if is_paper_trading():
            await broadcast_db_change("transfers_paper", {"source": "initiate_transfer"})
        else:
            await broadcast_db_change("transfers", {"source": "initiate_transfer"})

        mtb_affected = from_name == "Master Trading Bankroll" or to_name == "Master Trading Bankroll"
        if mtb_affected:
            try:
                from backend.balance_snapshot import (
                    insert_account_balance_snapshot_after_mtb_subaccount_internal_transfer,
                )

                slot = resolved_tenant_user_no_for_app()
                ab_tbl = account_balance_table_for_user(slot)
                sa_tbl = subaccounts_table_for_user(slot)
                notify_name = "account_balance_paper" if is_paper_trading() else "account_balance"
                insert_account_balance_snapshot_after_mtb_subaccount_internal_transfer(
                    account_balance_table=ab_tbl,
                    subaccounts_table=sa_tbl,
                    notify_db_name=notify_name,
                )
            except Exception as e:
                _main_logger.warning(f"initiate-transfer: MTB account_balance snapshot failed: {e}")

        if not is_paper_trading() and not mtb_affected:
            # Live: poll Kalshi when the transfer did not only reshuffle MTB vs other local slices
            def _run_sync():
                try:
                    from backend.kalshi_account_sync_ws import sync_balance
                    sync_balance()
                except Exception as e:
                    _main_logger.warning(f"initiate-transfer: sync_balance failed: {e}")

            import threading
            threading.Thread(target=_run_sync, daemon=True).start()

        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error initiating transfer: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/monitor/bankroll")
async def get_monitor_bankroll(monitor_id: str):
    """Get monitor-specific bankroll allotment from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get monitor-specific bankroll allotment
            ml = legacy_users_monitor_list(effective_tenant_context_for_sql_rewrite().user_no)
            cursor.execute(
                f"""
                SELECT bankroll_allotment_total, name, symbol
                FROM {ml}
                WHERE id = %s
            """,
                (monitor_id,),
            )
            monitor_result = cursor.fetchone()
            
            conn.close()
            
            if monitor_result:
                bankroll_allotment = monitor_result['bankroll_allotment_total'] or 0
                return {
                    "monitor_id": monitor_id,
                    "bankroll_allotment_total": bankroll_allotment,
                    "name": monitor_result['name'],
                    "symbol": monitor_result['symbol']
                }
            else:
                return {"monitor_id": monitor_id, "bankroll_allotment_total": 0, "name": "Unknown", "symbol": "BTC"}
            
    except Exception as e:
        _main_logger.warning(f"Error getting monitor bankroll from PostgreSQL: {e}")
        return {"monitor_id": monitor_id, "bankroll_allotment_total": 0, "name": "Unknown", "symbol": "BTC"}

@app.get("/api/account/balance/history")
async def get_account_balance_history(
    mode: str = "prod", limit: int = 1000, trading_mode: Optional[str] = None
):
    """Get historical account balance data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            ab_ident = sql_ident_qualified_table(
                account_balance_table_for_user(
                    resolved_tenant_user_no_for_app(), client_trading_mode=trading_mode
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                SELECT portfolio, positions, updated_at
                FROM {}
                ORDER BY updated_at ASC
                LIMIT %s
                """
                ).format(ab_ident),
                (limit,),
            )
            balance_results = cursor.fetchall()
            
            conn.close()
            
            # Convert to list of dictionaries
            history_data = []
            for result in balance_results:
                history_data.append({
                    "portfolio": result['portfolio'],
                    "positions": result['positions'],
                    "timestamp": result['updated_at'].isoformat() if result['updated_at'] else None
                })
            
            return {"history": history_data}
            
    except Exception as e:
        _main_logger.warning(f"Error getting account balance history from PostgreSQL: {e}")
        return {"history": []}

@app.get("/api/db/fills")
def get_fills(response: Response):
    """Get fills data from PostgreSQL database."""
    _api_no_store_headers(response)
    if is_paper_trading():
        return {"fills": []}
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.fills_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            fills = cursor.fetchall()
            
            # Convert RealDictRow to dict; prefer _fp for count (rounded for display)
            fills_list = []
            for fill in fills:
                fill_dict = dict(fill)
                if fill_dict.get("count_fp") is not None:
                    try:
                        fill_dict["count"] = int(round(float(fill_dict["count_fp"])))
                    except (TypeError, ValueError):
                        pass
                fills_list.append(fill_dict)
            
            conn.close()
            return {"fills": fills_list}
            
    except Exception as e:
        _main_logger.warning(f"Error getting fills from PostgreSQL: {e}")
        return {"fills": []}

@app.get("/api/db/positions")
def get_positions(response: Response):
    """Get positions data from PostgreSQL database."""
    _api_no_store_headers(response)
    if is_paper_trading():
        return {"positions": []}
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.positions_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            positions = cursor.fetchall()
            
            # Convert to dict; prefer _fp for position/total_traded (rounded for display)
            positions_list = []
            for position in positions:
                position_dict = dict(position)
                if position_dict.get("position_fp") is not None:
                    try:
                        position_dict["position"] = int(round(float(position_dict["position_fp"])))
                    except (TypeError, ValueError):
                        pass
                if position_dict.get("total_traded_fp") is not None:
                    try:
                        position_dict["total_traded"] = int(round(float(position_dict["total_traded_fp"])))
                    except (TypeError, ValueError):
                        pass
                positions_list.append(position_dict)
            
            conn.close()
            return {"positions": positions_list}
            
    except Exception as e:
        _main_logger.warning(f"Error getting positions from PostgreSQL: {e}")
        return {"positions": []}

@app.get("/api/db/settlements")
def get_settlements(response: Response):
    """Get settlements data from PostgreSQL database."""
    _api_no_store_headers(response)
    if is_paper_trading():
        return {"settlements": []}
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.settlements_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            settlements = cursor.fetchall()
            
            # Convert to dict; prefer _fp for yes_count/no_count (rounded for display)
            settlements_list = []
            for settlement in settlements:
                settlement_dict = dict(settlement)
                if settlement_dict.get("yes_count_fp") is not None:
                    try:
                        settlement_dict["yes_count"] = int(round(float(settlement_dict["yes_count_fp"])))
                    except (TypeError, ValueError):
                        pass
                if settlement_dict.get("no_count_fp") is not None:
                    try:
                        settlement_dict["no_count"] = int(round(float(settlement_dict["no_count_fp"])))
                    except (TypeError, ValueError):
                        pass
                settlements_list.append(settlement_dict)
            
            conn.close()
            return {"settlements": settlements_list}
            
    except Exception as e:
        _main_logger.warning(f"Error getting settlements from PostgreSQL: {e}")
        return {"settlements": []}


@app.get("/api/db/transfers")
def get_transfers(
    response: Response,
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — match UI toggle (same table selection as subaccounts)",
    ),
):
    """Transfer history: live ``transfers_<slot>``; paper ``transfers_paper_<slot>``."""
    _api_no_store_headers(response)
    try:
        from psycopg2.extras import RealDictCursor

        conn = get_postgresql_connection()
        t_ident = sql_ident_qualified_table(
            transfers_table_for_user(
                resolved_tenant_user_no_for_app(),
                client_trading_mode=trading_mode,
            )
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                sql.SQL(
                    """
                SELECT id, timestamp, type, "from", "to", amount, initiated, status
                FROM {}
                ORDER BY id DESC
                LIMIT 100
                """
                ).format(t_ident),
            )
            rows = cursor.fetchall()

        transfers_list = [dict(r) for r in rows]
        conn.close()
        return {"transfers": transfers_list}

    except Exception as e:
        _main_logger.warning(f"Error getting transfers from PostgreSQL: {e}")
        return {"transfers": []}


@app.get("/api/db/system_health")
def get_system_health_from_db():
    """Get current system health from database with real-time capacity data"""
    try:
        import psycopg2
        import psutil
        
        # Get real-time system capacity data
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        memory_total_gb = memory.total / (1024**3)  # Convert bytes to GB
        memory_used_gb = memory.used / (1024**3)
        memory_available_gb = memory.available / (1024**3)
        
        disk_total_gb = disk.total / (1024**3)  # Convert bytes to GB
        disk_used_gb = disk.used / (1024**3)
        disk_free_gb = disk.free / (1024**3)
        
        conn = get_postgresql_connection()
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM system.health_status WHERE id = 1")
            result = cursor.fetchone()
            
            if result:
                cols = [d[0] for d in cursor.description]
                row = dict(zip(cols, result))
                service_summary = {}
                hd = row.get("health_details")
                if hd:
                    try:
                        if isinstance(hd, str):
                            import json

                            hd = json.loads(hd)
                        if isinstance(hd, dict):
                            service_summary = hd.get("service_summary") or {}
                    except Exception:
                        service_summary = {}
                return {
                    "overall_status": row.get("overall_status"),
                    "cpu_percent": float(row["cpu_percent"]) if row.get("cpu_percent") else None,
                    "memory_percent": float(row["memory_percent"]) if row.get("memory_percent") else None,
                    "disk_percent": float(row["disk_percent"]) if row.get("disk_percent") else None,
                    "database_status": row.get("database_status"),
                    "supervisor_status": row.get("supervisor_status"),
                    "services_healthy": row.get("services_healthy"),
                    "services_total": row.get("services_total"),
                    "failed_services": row.get("failed_services") or [],
                    "service_summary": service_summary,
                    "timestamp": row["timestamp"].isoformat() if row.get("timestamp") else None,
                    # Add real-time capacity data
                    "memory_total_gb": round(memory_total_gb, 1),
                    "memory_used_gb": round(memory_used_gb, 1),
                    "memory_available_gb": round(memory_available_gb, 1),
                    "disk_total_gb": round(disk_total_gb, 1),
                    "disk_used_gb": round(disk_used_gb, 1),
                    "disk_free_gb": round(disk_free_gb, 1),
                }
            else:
                return {"error": "No health data available"}
                
    except Exception as e:
        _main_logger.debug(f"[DB SYSTEM HEALTH] Error: {e}")
        return {"error": "Database error"}

@app.get("/api/db/trades")
def get_trades_from_postgresql():
    """Get trades data from PostgreSQL database."""
    try:
        import psycopg2

        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        slot = resolved_tenant_user_no_for_app()

        with conn.cursor() as cursor:
            if not fetch_master_trades_column_names(cursor, slot):
                conn.close()
                return {"trades": []}
            union_sql, _ = union_trades_with_archives_select(cursor, slot)
            cursor.execute(
                f"""
                SELECT * FROM ({union_sql}) AS all_trades
                ORDER BY id DESC
                """
            )
            trades = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]

            trades_list = []
            for row in trades:
                trade_dict = dict(zip(columns, row))
                # Ensure all fields are present for frontend compatibility
                trade_dict.update(
                    {
                        "id": trade_dict.get("id"),
                        "status": trade_dict.get("status", ""),
                        "date": trade_dict.get("date", ""),
                        "time": trade_dict.get("time", ""),
                        "symbol": trade_dict.get("symbol", "BTC"),
                        "trade_strategy": trade_dict.get("trade_strategy", ""),
                        "market": trade_dict.get("market", "hourly"),
                        "contract": trade_dict.get("contract", ""),
                        "strike": trade_dict.get("strike", ""),
                        "side": trade_dict.get("side", ""),
                        "prob": trade_dict.get("prob"),
                        "diff": trade_dict.get("diff"),
                        "buy_price": trade_dict.get("buy_price"),
                        "sell_price": trade_dict.get("sell_price"),
                        "position": trade_dict.get("position"),
                        "closed_at": trade_dict.get("closed_at"),
                        "fees": trade_dict.get("fees"),
                        "pnl": trade_dict.get("pnl"),
                        "symbol_open": trade_dict.get("symbol_open"),
                        "symbol_close": trade_dict.get("symbol_close"),
                        "momentum": trade_dict.get("momentum"),
                        "win_loss": trade_dict.get("win_loss"),
                    }
                )
                trades_list.append(trade_dict)

            conn.close()
            return {"trades": trades_list}

    except Exception as e:
        _main_logger.warning(f"Error getting trades from PostgreSQL: {e}")
        return {"trades": []}

# Fingerprint and strike probability endpoints
@app.get("/api/current_fingerprint")
async def get_current_fingerprint():
    """Get current fingerprint information."""
    try:
        from util.probability_calculator import get_probability_calculator
        
        calculator = get_probability_calculator()
        
        fingerprint_info = {
            "symbol": calculator.symbol,
            "current_momentum_bucket": calculator.current_momentum_bucket,
            "last_used_momentum_bucket": calculator.last_used_momentum_bucket,
            "fingerprint": f"{calculator.symbol}_fingerprint_directional_momentum_{calculator.current_momentum_bucket:03d}.csv",
            "fingerprint_file": f"{calculator.symbol}_fingerprint_directional_momentum_{calculator.current_momentum_bucket:03d}.csv",
            "available_buckets": list(calculator.momentum_fingerprints.keys()) if hasattr(calculator, 'momentum_fingerprints') else []
        }
        
        _main_logger.debug(f"[FINGERPRINT] Current fingerprint: {fingerprint_info['fingerprint_file']}")
        return fingerprint_info
        
    except Exception as e:
        _main_logger.warning(f"Error getting fingerprint: {e}")
        return {"fingerprint": "error", "error": str(e)}

@app.get("/api/momentum")
async def get_current_momentum(symbol: str = "BTC"):
    """Get current momentum score directly from PostgreSQL for specified symbol."""
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_score = float(result[0])
            return {
                "status": "ok",
                "momentum_score": momentum_score
            }
        else:
            return {
                "status": "error",
                "momentum_score": 0,
                "error": "No momentum data available"
            }
    except Exception as e:
        _main_logger.warning(f"Error getting momentum from PostgreSQL: {e}")
        return {
            "status": "error",
            "momentum_score": 0,
            "error": "Unable to get momentum from PostgreSQL"
        }

@app.get("/api/btc_price")
async def get_btc_price():
    """Get current BTC price directly from PostgreSQL live_data.live_price_log_1s_btc."""
    try:
        import psycopg2
        
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            price = float(result[0])
            return {"price": price, "source": "postgresql_live_data"}
        else:
            return {"price": None, "error": "No price data available"}
            
    except Exception as e:
        _main_logger.warning(f"Error getting BTC price from PostgreSQL: {e}")
        return {"price": None, "error": str(e)}

@app.get("/api/eth_price")
async def get_eth_price():
    """Get current ETH price directly from PostgreSQL live_data.live_price_log_1s_eth."""
    try:
        import psycopg2
        
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM live_data.live_price_log_1s_eth ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            price = float(result[0])
            return {"price": price, "source": "postgresql_live_data"}
        else:
            return {"price": None, "error": "No price data available"}
            
    except Exception as e:
        _main_logger.warning(f"Error getting ETH price from PostgreSQL: {e}")
        return {"price": None, "error": str(e)}

@app.get("/api/live_symbol_status_snapshot")
async def get_live_symbol_status_snapshot():
    """
    Standalone live UI snapshot:
    BTC/ETH/SOL/XRP symbol, price, momentum_percentile, volatility_percentile, movement_percentile.
    Values are pulled from live_data.live_symbol_status (trigger-synced from live_price_log_1s_*).
    """
    try:
        import psycopg2

        allowed = ("BTC", "ETH", "SOL", "XRP")
        conn = get_postgresql_connection()
        cursor = conn.cursor()

        out = []
        for sym in allowed:
            cursor.execute(
                """
                SELECT
                    symbol,
                    price,
                    momentum_percentile,
                    volatility_percentile,
                    movement_percentile,
                    "timestamp"
                FROM live_data.live_symbol_status
                WHERE symbol = %s
                """,
                (sym,),
            )
            row = cursor.fetchone()
            if not row:
                continue

            symbol, price, mom_pct, vol_pct, mov_pct, ts = row
            out.append(
                {
                    "symbol": symbol,
                    "price": float(price) if price is not None else None,
                    "momentum_percentile": float(mom_pct) if mom_pct is not None else None,
                    "volatility_percentile": float(vol_pct) if vol_pct is not None else None,
                    "movement_percentile": float(mov_pct) if mov_pct is not None else None,
                    "timestamp": ts,
                }
            )

        conn.close()

        # Convenience: include a single timestamp based on BTC if present, else ETH.
        ts_out = None
        for sym in allowed:
            found = next((r for r in out if r["symbol"] == sym), None)
            if found and found.get("timestamp"):
                ts_out = found["timestamp"]
                break

        return {"status": "ok", "timestamp": ts_out, "symbols": out}

    except Exception as e:
        _main_logger.warning(f"Error getting live symbol status snapshot: {e}")
        return {"status": "error", "message": str(e), "symbols": []}

@app.get("/api/momentum_score")
async def get_momentum_score():
    """Get current momentum score for mobile directly from PostgreSQL."""
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT momentum FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            weighted_score = float(result[0])
            return {"weighted_score": weighted_score}
        else:
            return {"weighted_score": 0, "error": "No momentum data available"}
    except Exception as e:
        _main_logger.warning(f"Error getting momentum score: {e}")
        return {"weighted_score": 0, "error": str(e)}

def _unified_strike_table_for_market(market: str) -> str:
    """Physical table in live_data: unified 15m or unified hourly (symbol scoped by exchange + symbol)."""
    m = (market or "").strip().lower()
    if m == "15m":
        return "strike_table_15m"
    if m == "hourly":
        return "strike_table_hourly"
    raise ValueError("market must be 'hourly' or '15m'")


@app.get("/api/strike_table")
async def get_strike_table_mobile(request: Request):
    """Get strike table data for mobile. Query params: symbol, market (required: hourly or 15m)."""
    try:
        import psycopg2
        symbol = (request.query_params.get("symbol") or "btc").lower()
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"strikes": [], "error": "market required (hourly or 15m)"}
        sym_u = symbol.upper()
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            if market == "hourly":
                h_tbl = _unified_strike_table_for_market("hourly")
                cursor.execute(
                    f"""
                    SELECT 
                        strike,
                        buffer,
                        buffer_pct,
                        probability_hourly,
                        yes_ask_dollars,
                        no_ask_dollars,
                        volume_fp,
                        open_interest_fp,
                        ticker,
                        yes_diff,
                        no_diff,
                        active_side
                    FROM live_data.{h_tbl}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u),
                )
            else:
                cursor.execute(
                    """
                    SELECT 
                        strike,
                        buffer,
                        buffer_pct,
                        probability_15m,
                        yes_ask_dollars,
                        no_ask_dollars,
                        volume_fp,
                        open_interest_fp,
                        ticker,
                        yes_diff,
                        no_diff,
                        active_side
                    FROM live_data.strike_table_15m
                    WHERE exchange = %s AND symbol = %s
                      AND "timestamp" = (
                        SELECT MAX("timestamp") FROM live_data.strike_table_15m
                        WHERE exchange = %s AND symbol = %s
                      )
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u, "kalshi", sym_u),
                )
            
            strikes_data = cursor.fetchall()
            conn.close()
            
            if not strikes_data:
                return {"strikes": [], "error": "No strike table data found"}
            
            strikes = []
            for row in strikes_data:
                strikes.append({
                    "strike": float(row[0]) if row[0] else None,
                    "buffer": float(row[1]) if row[1] else None,
                    "buffer_pct": float(row[2]) if row[2] else None,
                    "probability": float(row[3]) if row[3] else None,
                    "yes_ask_dollars": row[4],
                    "no_ask_dollars": row[5],
                    "volume_fp": row[6] if row[6] is None else str(row[6]).strip(),
                    "open_interest_fp": row[7] if row[7] is None else str(row[7]).strip(),
                    "ticker": row[8],
                    "yes_diff": float(row[9]) if row[9] else None,
                    "no_diff": float(row[10]) if row[10] else None,
                    "active_side": row[11],
                })
            
            return {"strikes": strikes}
            
    except Exception as e:
        _main_logger.warning(f"Error getting strike table from PostgreSQL: {e}")
        return {"strikes": [], "error": str(e)}

# === PREFERENCES API ENDPOINTS ===

# LEGACY REMOVED: /api/set_auto_stop endpoint - no longer used, auto stop now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/set_auto_entry endpoint - no longer used, auto entry now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_stop endpoint - no longer used, auto stop now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_entry endpoint - no longer used, auto entry now controlled by auto_trade in monitor_list

# Diff mode is now local only - no API endpoint needed

# Legacy position sizing endpoints removed - all position sizing now handled by monitor_list table

@app.post("/api/update_preferences")
async def update_preferences(request: Request):
    data = await request.json()
    prefs = load_preferences()
    updated = False

    if "position_size" in data:
        try:
            prefs["position_size"] = int(data["position_size"])
            updated = True
        except Exception as e:
            _main_logger.debug(f"[Invalid Position Size] {e}")

    if "multiplier" in data:
        try:
            prefs["multiplier"] = float(data["multiplier"])
            updated = True
        except Exception as e:
            _main_logger.debug(f"[Invalid Multiplier] {e}")

    if updated:
        await save_preferences(prefs)
        await broadcast_preferences_update()
    return {"status": "ok"}

# Legacy /api/get_preferences endpoint removed - position sizing and strategy now handled by monitor_list table

# === ACTIVE TRADES PROXY ROUTE ===
@app.get("/api/active_trades")
async def proxy_active_trades():
    """Proxy route to forward active trades requests to the active trade supervisor"""
    try:
        # Forward request to active trade supervisor
        response = requests.get(f"http://localhost:{ACTIVE_TRADE_SUPERVISOR_PORT}/api/active_trades", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"Active trade supervisor returned status {response.status_code}"}, response.status_code
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to connect to active trade supervisor: {str(e)}"}, 503

# Trade history preferences: GET/POST on main_app (same session as UI); read_api mirrors for direct tooling.

# LEGACY REMOVED: /api/get_auto_stop endpoint - no longer used, auto stop now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_entry endpoint - no longer used, auto entry now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_trade_settings endpoint - now using strategy-specific endpoints

# LEGACY REMOVED: /api/get_auto_entry_status endpoint - now using auto_trade_status system

# Legacy /api/get_trade_preferences endpoint removed - position sizing and strategy now handled by monitor_list table

# Legacy /api/update_trade_preferences endpoint removed - position sizing and strategy now handled by monitor_list table

# LEGACY REMOVED: /api/update_auto_entry_settings endpoint - now using /api/set_auto_entry_settings

# LEGACY REMOVED: /api/update_auto_stop_settings endpoint - now using /api/set_auto_entry_settings

import os
# Legacy auto stop settings path removed - all data now in PostgreSQL

# Legacy auto stop settings functions removed - all data now in PostgreSQL

# LEGACY REMOVED: /api/get_auto_stop_settings and /api/set_auto_stop_settings endpoints - now using /api/set_auto_entry_settings

# Legacy auto entry settings path removed - all data now in PostgreSQL

# Legacy auto entry settings functions removed - all data now in PostgreSQL

@app.get("/api/get_auto_entry_settings")
async def get_auto_entry_settings(monitor_id: str = None):
    """Get auto entry and auto stop settings for a specific monitor from monitor_list table"""
    if not monitor_id:
        return {"status": "error", "message": "Monitor ID required"}
    
    try:
        from backend.core.auto_entry_settings_store import monitor_list_flip_columns_available

        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            has_flip = monitor_list_flip_columns_available(cursor)
            sel_flip = """
                       , flip_sell_prob, flip_sell_prob_mult, flip_sell_floor, flip_sell_floor_mult
            """
            ml = legacy_users_monitor_list(effective_tenant_context_for_sql_rewrite().user_no)
            q = (
                """
                SELECT min_probability, max_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
                       spike_alert_enabled, spike_alert_momentum_threshold,
                       spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                       current_probability, min_ttc_seconds, momentum_spike_enabled,
                       momentum_spike_threshold, verification_period_enabled, verification_period_seconds,
                       min_volume, win_streak_threshold, performance_based_allocation,
                       momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, momentum_scalp_profit_target,
                       min_ask, max_ask, loss_prevention_toggle, max_price_spread, prob_adj,
                       min_cooldown_timer, max_cooldown_timer,
                       regime_monitor_enabled, regime_window, stop_loss_price, min_ask_range,
                       test_filter, time_in_force, order_type
            """
                + (sel_flip if has_flip else "")
                + """
                       , symbol_wide_loss_prevention, symbol_wide_cooldown_duration, symbol_wide_cooldown_start_time
            """
                + f"""
                FROM {ml} WHERE id = %s
            """
            )
            cursor.execute(q, (monitor_id,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                row = {
                    "min_probability": float(result[0]) if result[0] is not None else 95.00,
                    "max_probability": float(result[1]) if result[1] is not None else 100.00,
                    "min_differential": float(result[2]) if result[2] else 0.25,
                    "max_differential": float(result[3]) if result[3] is not None else None,
                    "min_time": result[4],
                    "max_time": result[5],
                    "allow_re_entry": result[6],
                    "spike_alert_enabled": result[7],
                    "spike_alert_momentum_threshold": result[8],
                    "spike_alert_cooldown_threshold": result[9],
                    "spike_alert_cooldown_minutes": result[10],
                    "current_probability": result[11],
                    "min_ttc_seconds": result[12],
                    "momentum_spike_enabled": result[13],
                    "momentum_spike_threshold": result[14],
                    "verification_period_enabled": result[15],
                    "verification_period_seconds": result[16],
                    "min_volume": result[17],
                    "win_streak_threshold": result[18],
                    "performance_based_allocation": result[19],
                    "momentum_scalp_entry_threshold": float(result[20]) if result[20] is not None else None,
                    "momentum_scalp_trailing_stop_amount": float(result[21]) if result[21] is not None else None,
                    "momentum_scalp_profit_target": float(result[22]) if result[22] is not None else None,
                    "min_ask": float(result[23]) if result[23] is not None else 0.0000,
                    "max_ask": float(result[24]) if result[24] is not None else 0.9800,
                    "loss_prevention_toggle": bool(result[25]) if result[25] is not None else True,
                    "max_price_spread": float(result[26]) if result[26] is not None else 0.0300,
                    "prob_adj": float(result[27]) if result[27] is not None else 5.00,
                    "min_cooldown_timer": result[28] if result[28] is not None else None,
                    "max_cooldown_timer": result[29] if result[29] is not None else None,
                    "regime_monitor_enabled": bool(result[30]) if result[30] is not None else False,
                    "regime_window": str(result[31]) if result[31] is not None else "30d",
                    "stop_loss_price": float(result[32]) if result[32] is not None else 0.0,
                    "min_ask_range": float(result[33]) if result[33] is not None else None,
                    "test_filter": bool(result[34]) if result[34] is not None else False,
                    "time_in_force": str(result[35]) if result[35] is not None else "fill_or_kill",
                    "order_type": str(result[36]) if result[36] is not None else "market",
                }
                if has_flip:
                    row["flip_sell_prob"] = bool(result[37]) if result[37] is not None else False
                    row["flip_sell_prob_mult"] = str(result[38]) if result[38] is not None else None
                    row["flip_sell_floor"] = bool(result[39]) if result[39] is not None else False
                    row["flip_sell_floor_mult"] = str(result[40]) if result[40] is not None else None
                    _sw_i = 41
                else:
                    row["flip_sell_prob"] = False
                    row["flip_sell_prob_mult"] = None
                    row["flip_sell_floor"] = False
                    row["flip_sell_floor_mult"] = None
                    _sw_i = 37
                row["symbol_wide_loss_prevention"] = (
                    bool(result[_sw_i]) if result[_sw_i] is not None else False
                )
                row["symbol_wide_cooldown_duration"] = (
                    int(result[_sw_i + 1]) if result[_sw_i + 1] is not None else 4
                )
                sw_start = result[_sw_i + 2]
                row["symbol_wide_cooldown_start_time"] = (
                    sw_start.isoformat() if hasattr(sw_start, "isoformat") else sw_start
                )
                return row
            else:
                return {"status": "error", "message": f"Monitor not found: {monitor_id}"}
                
    except Exception as e:
        _main_logger.debug(f"[Auto Entry Settings] ❌ Error getting monitor settings: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor_auto_stop_accuracy")
async def get_monitor_auto_stop_accuracy(request: Request, monitor_id: str = None):
    """Proxy: delegate auto-stop accuracy aggregates to read_api service."""
    try:
        params: Dict[str, Any] = {}
        if monitor_id:
            params["monitor_id"] = monitor_id
        params = _read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}/api/monitor_auto_stop_accuracy",
            params=params,
            headers=_read_api_forward_headers(request),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _main_logger.warning(f"[read_api proxy] Error getting monitor_auto_stop_accuracy from read_api: {e}")
        return {"status": "error", "message": "read_api proxy failed for /api/monitor_auto_stop_accuracy"}


@app.post("/api/set_auto_entry_settings")
async def set_auto_entry_settings(request: Request):
    data = await request.json()

    monitor_id = data.get("monitor_id")
    if not monitor_id:
        return {"status": "error", "message": "Monitor ID required"}

    try:
        from backend.core.auto_entry_settings_store import (
            apply_auto_entry_settings,
            trigger_regime_reconcile_after_auto_entry_save,
        )
        from backend.core.trading_redis_comms import (
            publish_auto_entry_settings_job,
            redis_client_optional,
            use_trading_redis_comms,
            wait_auto_entry_settings_ack,
        )

        # Prefer trading-plane Redis: monitor_manager applies UPDATE and returns ack (same response shape).
        if use_trading_redis_comms() and redis_client_optional():
            import uuid

            cid = str(uuid.uuid4())
            if publish_auto_entry_settings_job(
                str(monitor_id),
                data,
                cid,
                user_number=resolved_tenant_user_no_for_app(),
            ):
                ack = wait_auto_entry_settings_ack(cid)
                if ack is not None:
                    return ack
            _main_logger.debug(
                "[Auto Entry Settings] Redis path unavailable or timed out; applying in main"
            )

        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                result = apply_auto_entry_settings(cursor, str(monitor_id), data)
            if result.get("status") == "ok":
                conn.commit()
                trigger_regime_reconcile_after_auto_entry_save(
                    str(monitor_id),
                    user_number=resolved_tenant_user_no_for_app(),
                    source="set_auto_entry_settings",
                )
                _main_logger.debug(
                    "[Auto Entry & Auto Stop Settings] Updated monitor %s: %s",
                    monitor_id,
                    list(data.keys()),
                )
            else:
                conn.rollback()
            return result
        finally:
            conn.close()

    except Exception as e:
        _main_logger.debug(f"[Auto Entry Settings] ❌ Error updating strategy: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/trigger_open_trade")
async def trigger_open_trade(request: Request):
    """Trigger trade opening directly via the trade_manager service."""
    try:
        data = await request.json()
        strike = data.get("strike")
        side = data.get("side")
        ticker = data.get("ticker")
        buy_price = data.get("buy_price")
        prob = data.get("prob")
        symbol_open = data.get("symbol_open")
        momentum = data.get("momentum")
        contract = data.get("contract")
        symbol = data.get("symbol")
        position = data.get("position")
        trade_strategy = data.get("trade_strategy")
        paper_trade = data.get("paper_trade", False)
        
        _main_logger.debug(f"[TRIGGER OPEN TRADE] Received request: strike={strike}, side={side}, ticker={ticker}, buy_price={buy_price}, prob={prob}, symbol_open={symbol_open}, momentum={momentum}, paper_trade={paper_trade}")
        
        # Forward the request directly to the trade_manager service
        trade_manager_port = get_port("trade_manager")
        from backend.util.paths import get_host
        trade_manager_host = get_host()
        trade_manager_url = f"http://{trade_manager_host}:{trade_manager_port}/trades"
        
        # Create the exact same payload that trade_initiator would create
        import uuid
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        # Generate unique ticket ID (same format as trade_initiator)
        ticket_id = f"TICKET-{uuid.uuid4().hex[:9]}-{int(now_est().timestamp() * 1000)}"
        
        # Get current time in Eastern Time (same as trade_initiator)
        now = now_est()
        eastern_date = now.strftime('%Y-%m-%d')
        eastern_time = now.strftime('%H:%M:%S')
        
        # Convert side format (yes/no to Y/N) - same as trade_initiator
        converted_side = side
        if side == "yes":
            converted_side = "Y"
        elif side == "no":
            converted_side = "N"
        
        # Get current monitor information from the request - NO FALLBACKS
        monitor = data.get("monitor")
        if not monitor:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Error: No monitor specified in trade data")
            return {"status": "error", "message": "Monitor must be specified"}
        
        # Extract monitor ID from monitor string (e.g., "mon_0001_10001" -> "10001")
        monitor_id = monitor.split('_')[-1] if monitor and '_' in monitor else None
        if not monitor_id:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Error: Invalid monitor format: {monitor}")
            return {"status": "error", "message": "Invalid monitor format"}
        
        # Get bankroll_allotment_total from monitor configuration
        bankroll_allotment_total = None
        try:
            import psycopg2
            conn = get_postgresql_connection()
            with conn.cursor() as cursor:
                ml = legacy_users_monitor_list(effective_tenant_context_for_sql_rewrite().user_no)
                cursor.execute(
                    f"SELECT bankroll_allotment_total FROM {ml} WHERE id = %s",
                    (monitor_id,),
                )
                result = cursor.fetchone()
                if result:
                    bankroll_allotment_total = result[0]
                    _main_logger.debug(f"[TRIGGER OPEN TRADE] Bankroll allotment loaded from monitor {monitor_id}: {bankroll_allotment_total}")
                else:
                    _main_logger.debug(f"[TRIGGER OPEN TRADE] No monitor configuration found for monitor {monitor_id}")
                    return {"status": "error", "message": "Monitor configuration not found"}
        except Exception as e:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Error loading bankroll allotment from monitor {monitor_id}: {e}")
            return {"status": "error", "message": f"Failed to load monitor configuration: {e}"}
        finally:
            if conn:
                conn.close()
        
        # Prepare the trade data exactly like trade_initiator does (count_fp for full-chain consistency)
        position_val = position or 1
        trade_data = {
            "ticket_id": ticket_id,
            "status": "pending",
            "date": eastern_date,
            "time": eastern_time,
            "symbol": symbol or "BTC",
            "exchange": normalize_exchange(
                data.get("exchange", data.get("market"))
            ),
            "trade_strategy": trade_strategy or "Hourly HTC",
            "contract": contract or "BTC Market",
            "strike": strike,
            "side": converted_side,
            "ticker": ticker,
            "buy_price": buy_price,
            "position": position_val,
            "count_fp": f"{float(position_val):.2f}",
            "symbol_open": symbol_open,
            "symbol_close": None,
            "momentum": momentum,
            "prob": prob,
            "diff": data.get("diff"),  # Add diff from request
            "win_loss": None,
            "entry_method": data.get("entry_method", "manual"),
            "monitor": monitor,  # Add monitor field
            "bankroll_allotment_total": bankroll_allotment_total,
            "paper_trade": paper_trade  # Add paper_trade from request
        }
        
        # Send request directly to trade_manager
        response = requests.post(trade_manager_url, json=trade_data, timeout=10)
        
        if response.status_code == 201:
            result = response.json()
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Trade initiated successfully: {result}")
            return {
                "status": "success",
                "message": "Trade initiated successfully",
                "trade_data": result
            }
        else:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Trade initiation failed: {response.status_code} - {response.text}")
            return {
                "status": "error",
                "message": f"Trade initiation failed: {response.status_code}",
                "details": response.text
            }
        
    except Exception as e:
        _main_logger.debug(f"[TRIGGER OPEN TRADE] Error: {e}")
        return {"status": "error", "message": str(e)}



@app.get("/frontend-changes")
def frontend_changes():
    """Get the latest modification time of frontend files for cache busting."""
    import os
    latest = 0
    for root, dirs, files in os.walk("frontend"):
        for f in files:
            path = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(path)
                if mtime > latest:
                    latest = mtime
            except Exception:
                pass
    return {"last_modified": latest}

@app.get("/api/live_probabilities")
async def get_live_probabilities(request: Request):
    """Get live probabilities. Query params: symbol, market (required: hourly or 15m)."""
    try:
        import psycopg2
        symbol = (request.query_params.get("symbol") or "btc").lower()
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)"}
        sym_u = symbol.upper()
        tbl = _unified_strike_table_for_market(market)
        prob_col = "probability_15m" if market == "15m" else "probability_hourly"
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT strike, {prob_col}
                    FROM live_data.{tbl}
                    WHERE exchange = %s AND symbol = %s
                ORDER BY strike
                """,
                ("kalshi", sym_u),
            )
            
            probabilities_data = cursor.fetchall()
            conn.close()
            
            if not probabilities_data:
                return {"error": "No probability data found"}
            
            # Convert to the same format as the JSON file
            probabilities = []
            for row in probabilities_data:
                prob_data = {
                    "strike": float(row[0]) if row[0] else None,
                    "prob_within": float(row[1]) if row[1] else None
                }
                probabilities.append(prob_data)
            
            return {
                "probabilities": probabilities,
                "timestamp": now_est().isoformat()
            }
            
    except Exception as e:
        return {"error": f"Error loading live probabilities from PostgreSQL: {str(e)}"}

def safe_read_json(filepath: str, timeout: float = 0.1):
    """Read JSON data with file locking to prevent race conditions"""
    try:
        with open(filepath, 'r') as f:
            # Try to acquire a shared lock with timeout
            fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (IOError, OSError) as e:
        # If locking fails, fall back to normal read (rare)
        _main_logger.debug(f"Warning: File locking failed for {filepath}: {e}")
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as read_error:
            _main_logger.warning(f"Error reading JSON from {filepath}: {read_error}")
            return None

@app.get("/api/strike_tables/{symbol}")
async def get_strike_table(symbol: str, request: Request):
    """Get strike table data. Query param: market (required: hourly or 15m)."""
    try:
        import psycopg2
        
        # Convert symbol to lowercase for consistency (used for error messages/logs)
        symbol_lower = symbol.lower()
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sym_u = symbol.upper()
            if market == "15m":
                # Unified 15m source of truth.
                cursor.execute(
                    """
                    SELECT
                        symbol,
                        current_price,
                        ttc_15m,
                        event_ticker,
                        market_title,
                        strike_tier,
                        market_status,
                        momentum_percentile
                    FROM live_data.strike_table_15m
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY "timestamp" DESC
                    LIMIT 1
                    """,
                    ("kalshi", sym_u),
                )
                header_data = cursor.fetchone()
                if not header_data:
                    return {"error": f"No strike table data found for {symbol}"}
                cursor.execute(
                    """
                    SELECT
                        strike,
                        buffer,
                        buffer_pct,
                        probability_15m,
                        yes_ask_dollars,
                        no_ask_dollars,
                        volume_fp,
                        open_interest_fp,
                        ticker,
                        yes_diff,
                        no_diff,
                        active_side,
                        yes_ask_min_15m,
                        yes_ask_max_15m,
                        no_ask_min_15m,
                        no_ask_max_15m,
                        yes_ask_range_15m,
                        no_ask_range_15m
                    FROM live_data.strike_table_15m
                    WHERE exchange = %s AND symbol = %s
                      AND "timestamp" = (
                        SELECT MAX("timestamp") FROM live_data.strike_table_15m
                        WHERE exchange = %s AND symbol = %s
                      )
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u, "kalshi", sym_u),
                )
                strikes_data = cursor.fetchall()
            else:
                h_tbl = _unified_strike_table_for_market("hourly")
                cursor.execute(
                    f"""
                    SELECT
                        symbol,
                        current_price,
                        ttc_hourly,
                        event_ticker,
                        market_title,
                        strike_tier,
                        market_status,
                        momentum_percentile
                    FROM live_data.{h_tbl}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY "timestamp" DESC
                    LIMIT 1
                    """,
                    ("kalshi", sym_u),
                )
                header_data = cursor.fetchone()
                if not header_data:
                    return {"error": f"No strike table data found for {symbol}"}
                cursor.execute(
                    f"""
                    SELECT
                        strike,
                        buffer,
                        buffer_pct,
                        probability_hourly,
                        yes_ask_dollars,
                        no_ask_dollars,
                        volume_fp,
                        open_interest_fp,
                        ticker,
                        yes_diff,
                        no_diff,
                        active_side,
                        yes_ask_min_15m,
                        yes_ask_max_15m,
                        no_ask_min_15m,
                        no_ask_max_15m,
                        yes_ask_range_15m,
                        no_ask_range_15m
                    FROM live_data.{h_tbl}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u),
                )
                strikes_data = cursor.fetchall()
            conn.close()
            
            # Build response in the same format as JSON
            response = {
                "symbol": header_data[0],
                "current_price": float(header_data[1]) if header_data[1] else None,
                "ttc": int(header_data[2]) if header_data[2] else None,
                "event_ticker": header_data[3],
                "market_title": header_data[4],
                "strike_tier": header_data[5],
                "market_status": header_data[6],
                "momentum": {
                    "weighted_score": float(header_data[7]) if header_data[7] else 0.0
                },
                "strikes": []
            }
            
            for row in strikes_data:
                strike = {
                    "strike": float(row[0]) if row[0] else None,
                    "buffer": float(row[1]) if row[1] else None,
                    "buffer_pct": float(row[2]) if row[2] else None,
                    "probability": float(row[3]) if row[3] else None,
                    "yes_ask_dollars": row[4],
                    "no_ask_dollars": row[5],
                    "volume_fp": row[6] if row[6] is None else str(row[6]).strip(),
                    "open_interest_fp": row[7] if row[7] is None else str(row[7]).strip(),
                    "ticker": row[8],
                    "yes_diff": float(row[9]) if row[9] is not None else None,
                    "no_diff": float(row[10]) if row[10] is not None else None,
                    "active_side": row[11],
                    "yes_ask_min_15m": float(row[12]) if row[12] is not None else None,
                    "yes_ask_max_15m": float(row[13]) if row[13] is not None else None,
                    "no_ask_min_15m": float(row[14]) if row[14] is not None else None,
                    "no_ask_max_15m": float(row[15]) if row[15] is not None else None,
                    "yes_ask_range_15m": float(row[16]) if row[16] is not None else None,
                    "no_ask_range_15m": float(row[17]) if row[17] is not None else None,
                }
                response["strikes"].append(strike)
            
            return response
            
    except Exception as e:
        return {"error": f"Error loading strike table for {symbol} from PostgreSQL: {str(e)}"}

@app.get("/api/postgresql/strike_table/{symbol}")
async def get_postgresql_strike_table(symbol: str, request: Request):
    """Get strike table data. Query param: market (required: hourly or 15m)."""
    try:
        import psycopg2

        from backend.core.kalshi_contract_settlement import kalshi_contract_settlement_end_est

        def _strike_pack_settlement_end_ms(event_ticker, strike_rows, ticker_col_index):
            ref = (str(event_ticker).strip() if event_ticker else "") or ""
            if not ref and strike_rows:
                ref = str(strike_rows[0][ticker_col_index] or "").strip()
            if not ref:
                return None
            end = kalshi_contract_settlement_end_est(ref)
            return int(end.timestamp() * 1000) if end else None

        market = (request.query_params.get("market") or "").strip().lower()
        raw = (request.query_params.get("raw") or "").strip().lower() in ("1", "true", "yes")
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            sym_u = (symbol or "").upper()
            if market == "15m":
                cursor.execute(
                    """
                    SELECT
                        symbol,
                        current_price,
                        ttc_15m,
                        momentum_percentile,
                        market_title,
                        "timestamp",
                        event_ticker
                    FROM live_data.strike_table_15m
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY "timestamp" DESC
                    LIMIT 1
                    """,
                    ("kalshi", sym_u),
                )
                header_data = cursor.fetchone()
                if not header_data:
                    return {"error": f"No strike table data found for {symbol}"}
                cursor.execute(
                    """
                    SELECT
                        strike,
                        buffer,
                        buffer_pct,
                        probability_15m,
                        yes_ask_dollars,
                        no_ask_dollars,
                        volume_fp,
                        open_interest_fp,
                        ticker,
                        yes_diff,
                        no_diff,
                        active_side,
                        yes_ask_min_15m,
                        yes_ask_max_15m,
                        no_ask_min_15m,
                        no_ask_max_15m,
                        yes_ask_range_15m,
                        no_ask_range_15m
                    FROM live_data.strike_table_15m
                    WHERE exchange = %s AND symbol = %s
                      AND "timestamp" = (
                        SELECT MAX("timestamp") FROM live_data.strike_table_15m
                        WHERE exchange = %s AND symbol = %s
                      )
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u, "kalshi", sym_u),
                )
                strikes_data = cursor.fetchall()
                momentum_percentile = float(header_data[3]) if header_data[3] else 0.0
                momentum_bucket = round(momentum_percentile)
                response = {
                    "symbol": header_data[0],
                    "current_price": (str(header_data[1]) if raw else float(header_data[1])) if header_data[1] is not None else None,
                    "ttc_seconds": int(header_data[2]) if header_data[2] else None,
                    "momentum_percentile": momentum_percentile,
                    "momentum_bucket": momentum_bucket,
                    "market_title": header_data[4],
                    "timestamp": header_data[5].isoformat() if header_data[5] else None,
                    "event_ticker": header_data[6],
                    "strikes": [],
                }
                response["settlement_end_ms"] = _strike_pack_settlement_end_ms(
                    header_data[6], strikes_data, 8
                )
            else:
                h_tbl = _unified_strike_table_for_market("hourly")
                ttc_column = "ttc_hourly"
                prob_column = "probability_hourly"
                cursor.execute(
                    f"""
                    SELECT 
                        symbol,
                        current_price,
                        {ttc_column},
                        momentum_percentile,
                        market_title,
                        "timestamp",
                        event_ticker,
                        strike_tier
                    FROM live_data.{h_tbl}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY "timestamp" DESC
                    LIMIT 1
                    """,
                    ("kalshi", sym_u),
                )
                header_data = cursor.fetchone()
                if not header_data:
                    return {"error": f"No strike table data found for {symbol}"}
                cursor.execute(
                    f"""
                    SELECT 
                        strike,
                        buffer,
                        buffer_pct,
                        {prob_column},
                        yes_ask_dollars,
                        no_ask_dollars,
                        volume_fp,
                        open_interest_fp,
                        ticker,
                        yes_diff,
                        no_diff,
                        active_side,
                        yes_ask_min_15m,
                        yes_ask_max_15m,
                        no_ask_min_15m,
                        no_ask_max_15m,
                        yes_ask_range_15m,
                        no_ask_range_15m
                    FROM live_data.{h_tbl}
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u),
                )
                strikes_data = cursor.fetchall()
                momentum_percentile = float(header_data[3]) if header_data[3] else 0.0
                momentum_bucket = round(momentum_percentile)
                response = {
                    "symbol": header_data[0],
                    "current_price": (str(header_data[1]) if raw else float(header_data[1])) if header_data[1] is not None else None,
                    "ttc_seconds": int(header_data[2]) if header_data[2] else None,
                    "momentum_percentile": momentum_percentile,
                    "momentum_bucket": momentum_bucket,
                    "market_title": header_data[4],
                    "timestamp": header_data[5].isoformat() if header_data[5] else None,
                    "event_ticker": header_data[6],
                    "strike_tier": int(header_data[7]) if header_data[7] is not None else None,
                    "strikes": [],
                }
                response["settlement_end_ms"] = _strike_pack_settlement_end_ms(
                    header_data[6], strikes_data, 8
                )

            for strike_row in strikes_data:
                vfp = strike_row[6]
                oifp = strike_row[7]
                strike_data = {
                    "strike": (str(strike_row[0]) if raw else float(strike_row[0])) if strike_row[0] is not None else None,
                    "buffer": (str(strike_row[1]) if raw else float(strike_row[1])) if strike_row[1] is not None else None,
                    "buffer_pct": (str(strike_row[2]) if raw else float(strike_row[2])) if strike_row[2] is not None else None,
                    "probability": (str(strike_row[3]) if raw else float(strike_row[3])) if strike_row[3] is not None else None,
                    "yes_ask_dollars": strike_row[4],
                    "no_ask_dollars": strike_row[5],
                    "volume_fp": vfp if vfp is None else str(vfp).strip(),
                    "open_interest_fp": oifp if oifp is None else str(oifp).strip(),
                    "ticker": strike_row[8],
                    "yes_diff": (str(strike_row[9]) if raw else float(strike_row[9])) if strike_row[9] is not None else None,
                    "no_diff": (str(strike_row[10]) if raw else float(strike_row[10])) if strike_row[10] is not None else None,
                    "active_side": strike_row[11],
                    "yes_ask_min_15m": (str(strike_row[12]) if raw else float(strike_row[12])) if strike_row[12] is not None else None,
                    "yes_ask_max_15m": (str(strike_row[13]) if raw else float(strike_row[13])) if strike_row[13] is not None else None,
                    "no_ask_min_15m": (str(strike_row[14]) if raw else float(strike_row[14])) if strike_row[14] is not None else None,
                    "no_ask_max_15m": (str(strike_row[15]) if raw else float(strike_row[15])) if strike_row[15] is not None else None,
                    "yes_ask_range_15m": (str(strike_row[16]) if raw else float(strike_row[16])) if strike_row[16] is not None else None,
                    "no_ask_range_15m": (str(strike_row[17]) if raw else float(strike_row[17])) if strike_row[17] is not None else None,
                }
                response["strikes"].append(strike_data)
            
            conn.close()
            return response
            
    except Exception as e:
        _main_logger.warning(f"Error getting PostgreSQL strike table for {symbol}: {str(e)}")
        return {"error": f"Error loading PostgreSQL strike table for {symbol}: {str(e)}"}

@app.get("/api/watchlist/{monitor_name}")
async def get_watchlist(monitor_name: str):
    """Get watchlist data for a specific monitor from PostgreSQL"""
    try:
        import psycopg2
        import re
        
        # Extract the numeric part from monitor name (e.g., "mon_0001_10002" -> "0001_10002")
        # The table name format is watchlist_0001_10002, not watchlist_mon_0001_10002
        table_suffix = monitor_name
        if monitor_name.startswith('mon_'):
            table_suffix = monitor_name[4:]  # Remove "mon_" prefix
        
        # Connect to PostgreSQL using centralized config
        conn = get_postgresql_connection()
        if not conn:
            return {"error": "Database unavailable"}
        with conn.cursor() as cursor:
            # Get header data
            cursor.execute(f"""
                SELECT 
                    symbol,
                    current_price,
                    ttc_seconds,
                    broker,
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status
                FROM live_data.watchlist_{table_suffix}
                LIMIT 1
            """)
            
            header_data = cursor.fetchone()
            
            if not header_data:
                return {"error": f"No watchlist data found for monitor {monitor_name}"}
            
            # Get all strike rows
            cursor.execute(f"""
                SELECT 
                    strike,
                    buffer,
                    buffer_pct,
                    probability,
                    yes_ask_dollars,
                    no_ask_dollars,
                    yes_diff,
                    no_diff,
                    volume_fp,
                    ticker,
                    active_side
                FROM live_data.watchlist_{table_suffix}
                ORDER BY probability DESC
            """)
            
            strikes_data = cursor.fetchall()
            conn.close()
            
            # Build response in the same format as JSON
            response = {
                "symbol": header_data[0],
                "current_price": float(header_data[1]) if header_data[1] else None,
                "ttc": int(header_data[2]) if header_data[2] else None,
                "broker": header_data[3],
                "event_ticker": header_data[4],
                "market_title": header_data[5],
                "strike_tier": header_data[6],
                "market_status": header_data[7],
                "strikes": []
            }
            
            for row in strikes_data:
                strike = {
                    "strike": float(row[0]) if row[0] else None,
                    "buffer": float(row[1]) if row[1] else None,
                    "buffer_pct": float(row[2]) if row[2] else None,
                    "probability": float(row[3]) if row[3] else None,
                    "yes_ask_dollars": float(row[4]) if row[4] is not None else None,
                    "no_ask_dollars": float(row[5]) if row[5] is not None else None,
                    "yes_diff": float(row[6]) if row[6] else None,
                    "no_diff": float(row[7]) if row[7] else None,
                    "volume_fp": row[8] if row[8] is None else str(row[8]).strip(),
                    "ticker": row[9],
                    "active_side": row[10]
                }
                response["strikes"].append(strike)
            
            return response
            
    except Exception as e:
        return {"error": f"Error loading watchlist for monitor {monitor_name} from PostgreSQL: {str(e)}"}

@app.get("/api/active_trades/{monitor_name}")
async def get_active_trades_for_monitor(monitor_name: str):
    """Get active trades data for a specific monitor from PostgreSQL"""
    try:
        import psycopg2

        from backend.core.port_config import (
            monitor_suffix_uses_unified_15m_pool,
            monitor_suffix_uses_unified_hourly_pool,
        )
        
        # Extract the numeric part from monitor name (e.g., "mon_0001_10002" -> "0001_10002")
        # The table name format is active_trades_0001_10002, not active_trades_mon_0001_10002
        table_suffix = monitor_name
        if monitor_name.startswith('mon_'):
            table_suffix = monitor_name[4:]  # Remove "mon_" prefix

        use_15m_pool = monitor_suffix_uses_unified_15m_pool(table_suffix)
        use_hourly_pool = monitor_suffix_uses_unified_hourly_pool(table_suffix)
        pool_user, pool_mid = None, None
        if use_15m_pool or use_hourly_pool:
            parts = table_suffix.split("_", 1)
            if len(parts) == 2:
                pool_user, pool_mid = parts[0], parts[1]
        
        # Connect to PostgreSQL using centralized config
        conn = get_postgresql_connection()
        if not conn:
            return {"error": "Database unavailable"}
        with conn.cursor() as cursor:
            # Get all active trades for this monitor
            if use_15m_pool and pool_user and pool_mid:
                cursor.execute(f"""
                    SELECT 
                        trade_id, ticket_id, date, time, strike, side, buy_price, position,
                        contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                        momentum, prob, fees, diff, status, current_symbol_price,
                        current_probability, buffer_from_entry, time_since_entry,
                        current_close_price, current_pnl, last_updated, created_at
                    FROM users.active_trades_15m_{pool_user}
                    WHERE monitor_id = %s
                      AND status IN ('active', 'pending', 'closing')
                    ORDER BY created_at DESC
                """, (pool_mid,))
            elif use_hourly_pool and pool_user and pool_mid:
                cursor.execute(f"""
                    SELECT 
                        trade_id, ticket_id, date, time, strike, side, buy_price, position,
                        contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                        momentum, prob, fees, diff, status, current_symbol_price,
                        current_probability, buffer_from_entry, time_since_entry,
                        current_close_price, current_pnl, last_updated, created_at
                    FROM users.active_trades_hourly_{pool_user}
                    WHERE monitor_id = %s
                      AND status IN ('active', 'pending', 'closing')
                    ORDER BY created_at DESC
                """, (pool_mid,))
            else:
                cursor.execute(f"""
                    SELECT 
                        trade_id, ticket_id, date, time, strike, side, buy_price, position,
                        contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                        momentum, prob, fees, diff, status, current_symbol_price,
                        current_probability, buffer_from_entry, time_since_entry,
                        current_close_price, current_pnl, last_updated, created_at
                    FROM users.active_trades_{table_suffix}
                    WHERE status IN ('active', 'pending', 'closing')
                    ORDER BY created_at DESC
                """)
            
            trades_data = cursor.fetchall()
            conn.close()
            
            # Build response
            active_trades = []
            for row in trades_data:
                trade = {
                    "trade_id": row[0],
                    "ticket_id": row[1],
                    "date": row[2].isoformat() if row[2] else None,
                    "time": str(row[3]) if row[3] else None,
                    "strike": str(row[4]) if row[4] else None,
                    "side": row[5],
                    "buy_price": float(row[6]) if row[6] else None,
                    "position": round(float(row[7]), 2) if row[7] is not None else None,
                    "contract": row[8],
                    "ticker": row[9],
                    "symbol": row[10],
                    "exchange": row[11],
                    "trade_strategy": row[12],
                    "symbol_open": float(row[13]) if row[13] else None,
                    "momentum": float(row[14]) if row[14] else None,
                    "prob": float(row[15]) if row[15] else None,
                    "fees": float(row[16]) if row[16] else None,
                    "diff": float(row[17]) if row[17] else None,
                    "status": row[18],
                    "current_symbol_price": float(row[19]) if row[19] else None,
                    "current_probability": float(row[20]) if row[20] else None,
                    "buffer_from_entry": float(row[21]) if row[21] else None,
                    "time_since_entry": int(row[22]) if row[22] else None,
                    "current_close_price": float(row[23]) if row[23] else None,
                    "current_pnl": row[24],
                    "last_updated": row[25].isoformat() if row[25] else None,
                    "created_at": row[26].isoformat() if row[26] else None
                }
                active_trades.append(trade)
            
            return {
                "status": "success",
                "timestamp": now_est().isoformat(),
                "active_trades": active_trades,
                "count": len(active_trades),
                "monitor_identifier": monitor_name
            }
            
    except Exception as e:
        return {"error": f"Error loading active trades for monitor {monitor_name} from PostgreSQL: {str(e)}"}

@app.get("/api/unified_ttc/{symbol}")
async def get_unified_ttc(symbol: str, request: Request):
    """Get unified TTC data. Query param: market (required: hourly or 15m)."""
    try:
        import psycopg2
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)", "ttc_seconds": 0}
        sym_u = (symbol or "BTC").upper()
        tbl = _unified_strike_table_for_market(market)
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            ttc_column = "ttc_15m" if market == "15m" else "ttc_hourly"
            cursor.execute(
                f"""
                SELECT {ttc_column}, event_ticker, market_title, market_status
                    FROM live_data.{tbl}
                WHERE exchange = %s AND symbol = %s
                  AND market_status = 'active'
                ORDER BY "timestamp" DESC, {ttc_column} ASC NULLS LAST
                LIMIT 1
                """,
                ("kalshi", sym_u),
            )
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] is not None:
                ttc_seconds = int(result[0])
                return {
                    "ttc_seconds": ttc_seconds,
                    "event_ticker": result[1],
                    "market_title": result[2],
                    "market_status": result[3],
                    "symbol": symbol.upper()
                }
            else:
                return {
                    "ttc_seconds": 0,
                    "event_ticker": None,
                    "market_title": None,
                    "market_status": "no_active_markets",
                    "symbol": symbol.upper()
                }
    except Exception as e:
        return {"error": f"Error getting unified TTC: {str(e)}"}

@app.get("/api/failure_detector_status")
async def get_failure_detector_status():
    """Get the current status of the cascading failure detector."""
    try:
        from backend.cascading_failure_detector import CascadingFailureDetector
        detector = CascadingFailureDetector()
        return detector.generate_status_report()
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/auto_entry_indicator")
async def get_auto_entry_indicator(
    monitor_id: Optional[str] = None,
    user_number: Optional[str] = None,
):
    """Proxy endpoint to get auto entry indicator state from auto_entry_supervisor.

    For unified 15m AES pass monitor_id; user_number defaults to the logged-in tenant.
    """
    try:
        from backend.core.port_config import (
            get_auto_entry_supervisor_http_port_for_monitor_suffix,
            get_port,
        )

        if monitor_id:
            un = user_number or resolved_tenant_user_no_for_app()
            suffix = f"{un}_{monitor_id}"
            port = get_auto_entry_supervisor_http_port_for_monitor_suffix(suffix)
        else:
            port = get_port("auto_entry_supervisor")
        q = {}
        if monitor_id:
            q["monitor_id"] = monitor_id
            q["user_number"] = user_number or resolved_tenant_user_no_for_app()
        # Use localhost for internal service communication
        url = f"http://localhost:{port}/api/auto_entry_indicator"
        response = requests.get(url, params=q or None, timeout=2)
        if response.ok:
            return response.json()
        else:
            return {"error": f"Auto entry supervisor returned {response.status_code}"}
    except Exception as e:
        return {"error": f"Error getting auto entry indicator: {str(e)}"}

# Log event endpoint
from backend.util.trade_logger import log_trade_event, get_trade_logs

@app.get("/api/trade_logs")
async def get_trade_logs_endpoint(ticket_id: str = None, service: str = None, limit: int = 100):
    """Get trade logs from PostgreSQL"""
    try:
        logs = get_trade_logs(ticket_id=ticket_id, service=service, limit=limit)
        return {"status": "ok", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/historical_price_data")
async def get_historical_price_data(symbol: str = "BTC", limit: int = 1000, start_date: str = None, end_date: str = None):
    """Get historical price data from PostgreSQL"""
    try:
        import psycopg2
        from datetime import datetime
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        # Build query
        query = """
            SELECT timestamp, open_price, high_price, low_price, close_price, volume, momentum
            FROM live_data.historical_price_data 
            WHERE symbol = %s
        """
        params = [symbol.upper()]
        
        # Add date filters if provided
        if start_date:
            query += " AND timestamp >= %s"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= %s"
            params.append(end_date)
        
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            
        conn.close()
        
        # Format results
        data = []
        for row in results:
            data.append({
                "timestamp": row[0].isoformat() if row[0] else None,
                "open": float(row[1]) if row[1] else None,
                "high": float(row[2]) if row[2] else None,
                "low": float(row[3]) if row[3] else None,
                "close": float(row[4]) if row[4] else None,
                "volume": float(row[5]) if row[5] else None,
                "momentum": float(row[6]) if row[6] else None
            })
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "count": len(data),
            "data": data
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/log_event")
async def log_event(request: Request):
    """Log trade events to PostgreSQL instead of text files"""
    try:
        data = await request.json()
        ticket_id = data.get("ticket_id", "UNKNOWN")
        message = data.get("message", "No message provided")

        # Log to PostgreSQL
        log_trade_event(ticket_id, message, service="main")

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Momentum and fingerprint now consolidated in strike table - no separate broadcast endpoints needed



# Authentication endpoints (opaque proxy to read_api web data plane; no tenant SQL here)
@app.post("/api/auth/login")
async def login(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/auth/login", body)
    return await _as_starlette_response(r)


@app.post("/api/auth/verify")
async def verify_auth(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/auth/verify", body)
    return await _as_starlette_response(r)


@app.post("/api/auth/logout")
async def logout(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/auth/logout", body)
    return await _as_starlette_response(r)


@app.post("/api/auth/register")
async def auth_register(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/auth/register", body)
    return await _as_starlette_response(r)


@app.post("/api/auth/register/verify-email")
async def auth_register_verify_email(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/auth/register/verify-email", body)
    return await _as_starlette_response(r)


@app.post("/api/auth/register/resend-verification")
async def auth_register_resend_verification(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/auth/register/resend-verification", body)
    return await _as_starlette_response(r)


@app.get("/api/user/info")
async def get_user_info(request: Request):
    r = await _proxy_read_api_raw(request, "GET", "/api/user/info")
    return await _as_starlette_response(r)


@app.get("/api/user/admin/master_users")
async def get_admin_master_users(request: Request):
    r = await _proxy_read_api_raw(request, "GET", "/api/user/admin/master_users")
    return await _as_starlette_response(r)


@app.patch("/api/user/admin/master_users")
async def patch_admin_master_users(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "PATCH", "/api/user/admin/master_users", body)
    return await _as_starlette_response(r)


@app.post("/api/user/change-password")
async def change_password(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/user/change-password", body)
    return await _as_starlette_response(r)


@app.post("/api/user/activity")
async def post_user_activity(request: Request):
    body = await request.body()
    r = await _proxy_read_api_raw(request, "POST", "/api/user/activity", body)
    return await _as_starlette_response(r)


@app.get("/api/system/health")
async def get_system_health():
    """Get current system health status from database"""
    try:
        import psycopg2
        
        conn = get_postgresql_connection()
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM system.health_status WHERE id = 1")
            result = cursor.fetchone()
            
            if result:
                # Unpack the result (adjust column order as needed)
                id, overall_status, cpu_percent, memory_percent, disk_percent, \
                database_status, supervisor_status, services_healthy, services_total, \
                failed_services, health_details, timestamp = result
                
                return {
                    "overall_status": overall_status,
                    "cpu_percent": float(cpu_percent) if cpu_percent else None,
                    "memory_percent": float(memory_percent) if memory_percent else None,
                    "disk_percent": float(disk_percent) if disk_percent else None,
                    "database_status": database_status,
                    "supervisor_status": supervisor_status,
                    "services_healthy": services_healthy,
                    "services_total": services_total,
                    "failed_services": failed_services or [],
                    "timestamp": timestamp.isoformat() if timestamp else None
                }
            else:
                return {"error": "No health data available"}
                
    except Exception as e:
        _main_logger.debug(f"[SYSTEM HEALTH] Error getting system health: {e}")
        return {"error": "Failed to get system health information"}

@app.post("/api/admin/supervisor-status")
async def get_supervisor_status():
    """Execute supervisorctl status command and return output"""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root, get_supervisorctl_path, get_supervisor_config_path
        
        # Get dynamic paths
        project_dir = get_dynamic_project_root()
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()
        
        # Change to the project directory
        os.chdir(project_dir)
        
        # Set up environment
        env = os.environ.copy()
        
        # Execute the supervisorctl command with dynamic paths
        result = subprocess.run(
            [supervisorctl_path, "-c", supervisor_config_path, "status"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            cwd=project_dir
        )
        
        # supervisorctl returns non-zero exit codes when any process is stopped
        # but the output is still valid, so we should return success if we got output
        if result.stdout.strip():
            return {
                "success": True,
                "output": result.stdout
            }
        else:
            return {
                "success": False,
                "error": f"Command failed with return code {result.returncode}",
                "output": result.stderr
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/admin/execute-restart")
async def execute_restart():
    """Execute the restart script in background"""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root
        
        # Get dynamic project directory
        project_dir = get_dynamic_project_root()
        os.chdir(project_dir)
        
        # Set up environment with proper PATH
        env = os.environ.copy()
        # Add common paths for both macOS and Ubuntu
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
        
        # Execute the restart script in background (don't wait for it)
        subprocess.Popen(
            ["/bin/bash", "./scripts/restart"],
            cwd=project_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        # Return immediately - the script will run in background
        return {
            "success": True,
            "message": "Restart script initiated in background"
        }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/admin/execute-command")
async def execute_command(request: dict):
    """Execute arbitrary command at project level"""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root, get_supervisorctl_path, get_supervisor_config_path
        
        command = request.get("command", "")
        if not command:
            return {"success": False, "error": "No command provided"}
        
        # Get dynamic project directory and supervisor paths
        project_dir = get_dynamic_project_root()
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()
        
        os.chdir(project_dir)
        
        env = os.environ.copy()
        # Only restrict PATH for non-backup commands so supervisorctl etc. use a minimal PATH
        if 'package_user_data.sh' not in command:
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
        
        # Check if this is a supervisorctl command
        if command.startswith('supervisorctl'):
            # Parse the supervisorctl command
            parts = command.split()
            if len(parts) >= 2:
                action = parts[1]  # restart, status, etc.
                if len(parts) >= 3:
                    script_name = parts[2]  # script name
                    # Execute with proper supervisor configuration
                    result = subprocess.run(
                        [supervisorctl_path, "-c", supervisor_config_path, action, script_name],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=env,
                        cwd=project_dir
                    )
                else:
                    # No script name specified (e.g., "supervisorctl status")
                    result = subprocess.run(
                        [supervisorctl_path, "-c", supervisor_config_path, action],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=env,
                        cwd=project_dir
                    )
            else:
                return {"success": False, "error": "Invalid supervisorctl command"}
        else:
            timeout = 300 if 'package_user_data.sh' in command else 30
            # Backup script: run with PATH that can find pg_dump (IDE/launcher often don't have it)
            if 'package_user_data.sh' in command:
                import shlex
                run_cmd = ['/bin/bash', '-l', '-c', f'cd {shlex.quote(project_dir)} && {command}']
                backup_env = env.copy()
                extra_paths = '/opt/homebrew/bin:/usr/local/bin:/usr/bin'
                backup_env['PATH'] = (backup_env.get('PATH') or '') + ':' + extra_paths
                result = subprocess.run(
                    run_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=project_dir,
                    env=backup_env,
                )
            else:
                result = subprocess.run(
                    command.split(),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                    cwd=project_dir
                )
        
        if result.returncode == 0:
            return {"success": True, "output": result.stdout}
        else:
            err_detail = (result.stderr or "").strip() or (result.stdout or "").strip()
            err_msg = f"Command failed with return code {result.returncode}"
            if err_detail:
                err_msg += f". {err_detail[:500]}"
            return {"success": False, "error": err_msg, "output": result.stderr or result.stdout}
            
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 5 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/admin/get-log-stream")
async def get_log_stream(request: dict):
    """Stream log output for a specific script."""
    from fastapi.responses import StreamingResponse
    import subprocess
    import os
    
    script_name = request.get("script", "")
    log_type = request.get("logType", "out")
    
    if not script_name:
        return {"success": False, "error": "No script name provided"}
    
    # Determine log file path based on script name and type
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    if log_type == "combined":
        # For combined view, we'll need to handle multiple files
        log_files = []
        for suffix in [".out.log", ".err.log", ".log"]:
            potential_file = f"logs/{script_name}{suffix}"
            if os.path.exists(os.path.join(project_dir, potential_file)):
                log_files.append(potential_file)
        
        if not log_files:
            return {"success": False, "error": f"No log files found for {script_name}"}
        
        # Use the first available file for now (we can enhance this later)
        log_file = log_files[0]
    else:
        # For specific log types
        log_file = f"logs/{script_name}.{log_type}.log"
        if not os.path.exists(os.path.join(project_dir, log_file)):
            # Fallback to .log if specific type doesn't exist
            log_file = f"logs/{script_name}.log"
        
        # For auto_entry_supervisor, prioritize the dedicated .log file over .out.log
        if script_name == "auto_entry_supervisor" and log_type == "out":
            dedicated_log = f"logs/{script_name}.log"
            if os.path.exists(os.path.join(project_dir, dedicated_log)):
                log_file = dedicated_log
    
    if not os.path.exists(os.path.join(project_dir, log_file)):
        return {"success": False, "error": f"Log file not found: {log_file}"}
    
    def generate_log_stream():
        try:
            # Set up environment with proper PATH
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
            
            # First, get the last 100 lines of the log file
            try:
                result = subprocess.run(
                    ["/usr/bin/tail", "-n", "100", log_file],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=project_dir,
                    env=env
                )
                if result.returncode == 0 and result.stdout:
                    # Send the last 100 lines first
                    yield "=== Last 100 lines of log ===\n"
                    yield result.stdout
                    yield "\n=== Live tail starting ===\n"
            except Exception as e:
                yield f"Warning: Could not read existing log content: {str(e)}\n"
                yield "=== Starting live tail ===\n"
            
            # Start tail -f process with unbuffered output for real-time streaming
            process = subprocess.Popen(
                ["tail", "-f", log_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=project_dir,
                env=env,
                bufsize=1  # Line buffered
            )
            
            # Stream live output with immediate flushing
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                # Send each line immediately with proper encoding
                yield line.encode('utf-8').decode('utf-8')
            
        except Exception as e:
            yield f"Error: {str(e)}\n"
        finally:
            if 'process' in locals():
                process.terminate()
    
    return StreamingResponse(
        generate_log_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked"
        }
    )

@app.post("/api/admin/create-backup")
async def create_backup():
    """Create a database backup using the package_user_data.sh script."""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root
        
        # Get project directory
        project_dir = get_dynamic_project_root()
        
        # Set up environment with proper PATH
        env = os.environ.copy()
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
        
        # Execute the backup script
        result = subprocess.run(
            ['bash', 'scripts/backup/package_user_data.sh'],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minutes timeout for backup
            env=env,
            cwd=project_dir
        )
        
        if result.returncode == 0:
            # Parse the output to find the backup file
            output = result.stdout
            backup_match = output.find('user_data_package_')
            if backup_match != -1:
                # Extract the backup filename from the output
                lines = output.split('\n')
                for line in lines:
                    if 'user_data_package_' in line and '.tar.gz' in line:
                        backup_file = line.strip()
                        if backup_file.endswith('.tar.gz'):
                            backup_path = os.path.join(project_dir, 'backup', backup_file)
                            if os.path.exists(backup_path):
                                return {
                                    "success": True, 
                                    "output": output,
                                    "backup_file": backup_file,
                                    "backup_path": backup_path
                                }
            
            return {"success": True, "output": output}
        else:
            return {
                "success": False, 
                "error": f"Backup script failed with return code {result.returncode}",
                "output": result.stderr
            }
            
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Backup timed out after 2 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/admin/download-file")
async def download_file(request: dict):
    """Download a file from the server."""
    try:
        import os
        from fastapi.responses import FileResponse
        from pathlib import Path
        
        file_path = request.get("file_path", "")
        if not file_path:
            # Allow filename-only for backup files (resolved under project/backup)
            file_name = request.get("file", "").strip()
            if file_name:
                project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                file_path = os.path.join(project_dir, "backup", file_name)
            else:
                return {"success": False, "error": "No file path or file name provided"}
        if file_path:
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.abspath(file_path)
        
        if not file_path.startswith(project_dir):
            return {"success": False, "error": "Access denied: File path outside project directory"}
        
        if not os.path.exists(file_path):
            return {"success": False, "error": "File not found"}
        
        if not os.path.isfile(file_path):
            return {"success": False, "error": "Path is not a file"}
        
        # Return the file for download
        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type='application/octet-stream'
        )
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/admin/download-file")
async def download_file_get(file: str):
    """Download a file from the server via GET request."""
    try:
        import os
        from fastapi.responses import FileResponse
        from pathlib import Path
        
        if not file:
            return {"success": False, "error": "No file name provided"}
        
        # Security check: ensure the file is within the backup directory
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        backup_dir = os.path.join(project_dir, 'backup')
        file_path = os.path.join(backup_dir, file)
        file_path = os.path.abspath(file_path)
        
        # Ensure the file is within the backup directory
        if not file_path.startswith(backup_dir):
            return {"success": False, "error": "Access denied: File path outside backup directory"}
        
        if not os.path.exists(file_path):
            return {"success": False, "error": "File not found"}
        
        if not os.path.isfile(file_path):
            return {"success": False, "error": "Path is not a file"}
        
        # Return the file for download
        return FileResponse(
            path=file_path,
            filename=file,
            media_type='application/octet-stream'
        )
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/portfolio/current")
async def get_current_portfolio(trading_mode: Optional[str] = None):
    """Get the current portfolio value from PostgreSQL"""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor() as cursor:
            ab_ident = sql_ident_qualified_table(
                account_balance_table_for_user(
                    resolved_tenant_user_no_for_app(), client_trading_mode=trading_mode
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                SELECT portfolio
                FROM {}
                ORDER BY timestamp DESC
                LIMIT 1
                """
                ).format(ab_ident)
            )
            
            result = cursor.fetchone()
            
        conn.close()
        
        if result:
            portfolio_value = float(result[0]) / 100  # Convert cents to dollars
            return {
                "status": "ok",
                "portfolio": portfolio_value
            }
        else:
            return {
                "status": "error",
                "message": "No portfolio data found"
            }
        
    except Exception as e:
        _main_logger.warning(f"Error getting current portfolio: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/portfolio/history")
async def get_portfolio_history(
    request: Request,
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — same as UI toggle; session selects tenant"
    ),
    rollup_view: Optional[str] = Query(
        None, description="td|prev — calendar vs rolling (dashboard rollup toggle)"
    ),
):
    """Proxy portfolio history reads to read_api."""
    try:
        params: Dict[str, Any] = {"period": period}
        if trading_mode:
            params["trading_mode"] = trading_mode
        if rollup_view:
            params["rollup_view"] = rollup_view
        params = _read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}/api/portfolio/history",
            params=params,
            headers=_read_api_forward_headers(request),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _main_logger.warning(f"[read_api proxy] Error getting /api/portfolio/history from read_api: {e}")
        return {"status": "error", "message": "read_api proxy failed for /api/portfolio/history"}


@app.get("/api/bankroll/history")
async def get_bankroll_history(
    request: Request,
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — same as UI toggle; session selects tenant"
    ),
    rollup_view: Optional[str] = Query(
        None, description="td|prev — calendar vs rolling (dashboard rollup toggle)"
    ),
):
    try:
        params: Dict[str, Any] = {"period": period}
        if trading_mode:
            params["trading_mode"] = trading_mode
        if rollup_view:
            params["rollup_view"] = rollup_view
        params = _read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}/api/bankroll/history",
            params=params,
            headers=_read_api_forward_headers(request),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _main_logger.warning(f"[read_api proxy] Error getting /api/bankroll/history from read_api: {e}")
        return {"status": "error", "message": "read_api proxy failed for /api/bankroll/history"}


@app.get("/api/pnl/history")
async def get_pnl_history(
    request: Request,
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — same as UI toggle; session selects tenant"
    ),
    rollup_view: Optional[str] = Query(
        None, description="td|prev — calendar vs rolling (dashboard rollup toggle)"
    ),
):
    try:
        params: Dict[str, Any] = {"period": period}
        if trading_mode:
            params["trading_mode"] = trading_mode
        if rollup_view:
            params["rollup_view"] = rollup_view
        params = _read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}/api/pnl/history",
            params=params,
            headers=_read_api_forward_headers(request),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _main_logger.warning(f"[read_api proxy] Error getting /api/pnl/history from read_api: {e}")
        return {"status": "error", "message": "read_api proxy failed for /api/pnl/history"}


@app.get("/api/performance/realized")
async def get_performance_realized(
    request: Request,
    trading_mode: Optional[str] = Query(
        None, description="paper|live — same as UI toggle; session selects tenant"
    ),
):
    try:
        params: Dict[str, Any] = {}
        if trading_mode:
            params["trading_mode"] = trading_mode
        params = _read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}/api/performance/realized",
            params=params,
            headers=_read_api_forward_headers(request),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _main_logger.warning(f"[read_api proxy] Error getting /api/performance/realized from read_api: {e}")
        return {"status": "error", "message": "read_api proxy failed for /api/performance/realized"}


@app.get("/api/performance/rollups")
async def get_performance_rollups(
    request: Request,
    trading_mode: Optional[str] = Query(
        None, description="paper|live — same as UI toggle; session selects tenant"
    ),
    rollup_view: str = Query(
        "td",
        description="td = calendar-to-date; prev = rolling windows",
    ),
):
    try:
        params: Dict[str, Any] = {}
        if trading_mode:
            params["trading_mode"] = trading_mode
        if rollup_view:
            params["rollup_view"] = rollup_view
        params = _read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}/api/performance/rollups",
            params=params,
            headers=_read_api_forward_headers(request),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _main_logger.warning(f"[read_api proxy] Error getting /api/performance/rollups from read_api: {e}")
        return {"status": "error", "message": "read_api proxy failed for /api/performance/rollups"}


@app.get("/api/performance/monitor-tiles")
async def get_performance_monitor_tiles_proxy(
    request: Request,
    period: str = Query(
        "all",
        description="1d | 1w | 1m | 1y | all — dashboard chart window",
    ),
    rollup_view: str = Query("td", description="td | prev"),
):
    try:
        params: Dict[str, Any] = {"period": period, "rollup_view": rollup_view}
        params = _read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}/api/performance/monitor-tiles",
            params=params,
            headers=_read_api_forward_headers(request),
            timeout=5,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _main_logger.warning(
            f"[read_api proxy] Error getting /api/performance/monitor-tiles from read_api: {e}"
        )
        return {"status": "error", "message": "read_api proxy failed for /api/performance/monitor-tiles"}


@app.get("/api/dashboard/performance-snapshot")
async def get_dashboard_performance_snapshot():
    """
    Bootstrap: same JSON as ``performance_rollups_snapshot`` on ``/ws/db_changes``.

    **Redis-only:** no PostgreSQL cold-fill and no degraded path. If Redis is down, the key is missing,
    or the value is corrupt, respond with ``503`` so callers treat the realtime plane as unavailable.
    """
    slot = resolved_tenant_user_no_for_app()
    if not slot:
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "missing_tenant"},
        )

    from backend.core.trading_redis_comms import (
        redis_client_optional,
        redis_key_dashboard_performance_snapshot,
    )

    r = redis_client_optional()
    if not r:
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "redis_unavailable"},
        )
    try:
        r.ping()
    except Exception as e:
        _main_logger.warning("[dashboard performance-snapshot] redis ping failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "redis_unavailable"},
        )

    try:
        raw = r.get(redis_key_dashboard_performance_snapshot(slot))
    except Exception as e:
        _main_logger.warning("[dashboard performance-snapshot] redis get failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "redis_read_failed"},
        )

    if not raw:
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "no_snapshot"},
        )
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
    except Exception as e:
        _main_logger.warning("[dashboard performance-snapshot] parse failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "invalid_snapshot"},
        )
    if not isinstance(data, dict) or data.get("type") != "performance_rollups_snapshot":
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "invalid_snapshot"},
        )
    return data


@app.get("/api/dashboard/preferences")
async def get_dashboard_preferences(mode: str = "prod"):
    """Get dashboard preferences for the current user"""
    try:
        from backend.core.config.database import get_postgresql_connection
        import psycopg2

        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        pref_table = f"users.dashboard_preferences_{slot}"
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT portfolio_chart_view, monitor_view_mode, monitor_sort_by, allocation_view, portfolio_view,
                       performance_rollup_view
                FROM {pref_table}
                WHERE user_id = 1
                """
            )
            result = cursor.fetchone()

        conn.close()

        if result:
            rv = result[5] if len(result) > 5 else None
            if rv not in ("td", "prev"):
                rv = "td"
            return {
                "status": "ok",
                "portfolio_chart_view": result[0],
                "monitor_view_mode": result[1] if result[1] else "tile",
                "monitor_sort_by": result[2] if result[2] else "name",
                "allocation_view": result[3] if result[3] else "pie",
                "portfolio_view": result[4] if result[4] else "portfolio",
                "performance_rollup_view": rv,
            }
        return {
            "status": "ok",
            "portfolio_chart_view": "all",
            "monitor_view_mode": "tile",
            "monitor_sort_by": "name",
            "allocation_view": "pie",
            "portfolio_view": "portfolio",
            "performance_rollup_view": "td",
        }

    except psycopg2.Error as e:
        _main_logger.debug("dashboard preferences read skipped for slot (missing table or row): %s", e)
        return {
            "status": "ok",
            "portfolio_chart_view": "all",
            "monitor_view_mode": "tile",
            "monitor_sort_by": "name",
            "allocation_view": "pie",
            "portfolio_view": "portfolio",
            "performance_rollup_view": "td",
        }
    except Exception as e:
        _main_logger.warning(f"Error getting dashboard preferences: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/dashboard/preferences")
async def save_dashboard_preferences(request: Request):
    """Save dashboard preferences for the current user"""
    try:
        from backend.core.config.database import get_postgresql_connection
        import psycopg2

        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()

        data = await request.json()
        _main_logger.debug(f"[DASHBOARD PREFERENCES] Received data: {data}")
        portfolio_chart_view = data.get("portfolio_chart_view", "all")
        monitor_view_mode = data.get("monitor_view_mode", "tile")
        monitor_sort_by = data.get("monitor_sort_by", "name")
        allocation_view = data.get("allocation_view", "pie")
        portfolio_view = data.get("portfolio_view", "portfolio")
        if portfolio_view not in ("bankroll", "portfolio", "pnl"):
            portfolio_view = "portfolio"
        pref_table = f"users.dashboard_preferences_{slot}"
        performance_rollup_view = "td"
        if "performance_rollup_view" in data:
            v = data.get("performance_rollup_view")
            if v in ("td", "prev"):
                performance_rollup_view = v
        else:
            try:
                with conn.cursor() as cur0:
                    cur0.execute(
                        f"SELECT performance_rollup_view FROM {pref_table} WHERE user_id = 1"
                    )
                    row_prv = cur0.fetchone()
                    if row_prv and row_prv[0] in ("td", "prev"):
                        performance_rollup_view = row_prv[0]
            except Exception:
                pass
        _main_logger.debug(f"[DASHBOARD PREFERENCES] Extracted values: portfolio_chart_view={portfolio_chart_view}, monitor_view_mode={monitor_view_mode}, monitor_sort_by={monitor_sort_by}, allocation_view={allocation_view}, portfolio_view={portfolio_view}")

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {pref_table} (user_id, portfolio_chart_view, monitor_view_mode, monitor_sort_by, allocation_view, portfolio_view, performance_rollup_view, updated_at)
                VALUES (1, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    portfolio_chart_view = EXCLUDED.portfolio_chart_view,
                    monitor_view_mode = EXCLUDED.monitor_view_mode,
                    monitor_sort_by = EXCLUDED.monitor_sort_by,
                    allocation_view = EXCLUDED.allocation_view,
                    portfolio_view = EXCLUDED.portfolio_view,
                    performance_rollup_view = EXCLUDED.performance_rollup_view,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    portfolio_chart_view,
                    monitor_view_mode,
                    monitor_sort_by,
                    allocation_view,
                    portfolio_view,
                    performance_rollup_view,
                ),
            )

        conn.commit()
        conn.close()

        _main_logger.debug(f"[DASHBOARD PREFERENCES] Successfully saved preferences to database")
        return {
            "status": "ok",
            "message": "Preferences saved successfully"
        }

    except psycopg2.Error as e:
        _main_logger.warning(f"Error saving dashboard preferences (table may be missing for slot): {e}")
        return {"status": "error", "message": str(e)}
    except Exception as e:
        _main_logger.warning(f"Error saving dashboard preferences: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/total_position")
async def get_total_position():
    """Get total_position from the first row of the tenant ``monitor_list_*`` table."""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        
        with conn.cursor() as cursor:
            ml = legacy_users_monitor_list(effective_tenant_context_for_sql_rewrite().user_no)
            cursor.execute(f"SELECT total_position FROM {ml} ORDER BY id LIMIT 1")
            result = cursor.fetchone()
            
        conn.close()
        
        if result and result[0] is not None:
            return {"total_position": result[0]}
        else:
            return {"total_position": 0}
            
    except Exception as e:
        return {"total_position": 0}

@app.get("/api/monitors")
async def get_monitors(user_id: Optional[str] = None):
    """Get monitors list for the specified user"""
    try:
        from backend.core.monitor_list_api import get_monitors_api_payload

        user_number = _session_user_number_from_optional_user_id(user_id)
        return get_monitors_api_payload(user_number)
    except HTTPException:
        raise
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }


@app.get("/api/monitors/health")
async def get_monitors_health(user_id: Optional[str] = None):
    """Get monitor health only (power-light payload), without full monitor tile data."""
    try:
        from backend.core.config.database import get_postgresql_connection
        from backend.core.strike_pipeline_health import (
            row_passes_trade_gate,
            strike_pipeline_health_strict_mode_enabled,
        )

        conn = get_postgresql_connection()
        user_number = _session_user_number_from_optional_user_id(user_id)
        strict_pipeline_health = strike_pipeline_health_strict_mode_enabled()
        if not conn:
            _main_logger.error(
                "get_monitors_health: database connection unavailable "
                "(check main_app logs for 'Failed to open tenant PostgreSQL connection')"
            )
            return {
                "status": "error",
                "message": "Database connection failed",
            }

        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id, symbol, status, market
                FROM users.monitor_list_{user_number}
                WHERE status != 'ARCHIVED'
                ORDER BY dashboard_order, id
                """
            )
            monitor_rows = cursor.fetchall()
            health_by_sym_mkt = {}
            if strict_pipeline_health:
                cursor.execute(
                    """
                    SELECT
                        market,
                        symbol,
                        pipeline_healthy,
                        pipeline_health_reason,
                        EXTRACT(EPOCH FROM (NOW() - pipeline_health_checked_at)),
                        EXTRACT(EPOCH FROM (NOW() - ws_transport_ok_at))
                    FROM live_data.strike_pipeline_health
                    WHERE LOWER(TRIM(exchange::text)) = 'kalshi'
                    """
                )
                for mkt, sym, ph, pr, cage, tage in cursor.fetchall():
                    key = (str(sym).upper(), str(mkt).strip().lower())
                    ok, rsn = row_passes_trade_gate((ph, pr, cage, tage))
                    health_by_sym_mkt[key] = {
                        "monitor_healthy": ok,
                        "monitor_health_state": "healthy" if ok else "degraded",
                        "monitor_health_reason": "ok" if ok else rsn,
                        "monitor_health_age_sec": float(cage) if cage is not None else None,
                    }
        conn.close()

        out = {}
        for monitor_id, symbol, status, market in monitor_rows:
            monitor_key = f"mon_{user_number}_{monitor_id}"
            monitor_market = (market or "").strip().lower() if market else None
            monitor_symbol = str(symbol or "").upper()
            if monitor_market in ("15m", "hourly"):
                if not strict_pipeline_health:
                    out[monitor_key] = {
                        "monitor_healthy": True,
                        "monitor_health_state": "healthy",
                        "monitor_health_reason": "strict_mode_off",
                        "monitor_health_age_sec": 0.0,
                    }
                else:
                    h = health_by_sym_mkt.get((monitor_symbol, monitor_market))
                    if h:
                        out[monitor_key] = dict(h)
                    else:
                        out[monitor_key] = {
                            "monitor_healthy": False,
                            "monitor_health_state": "degraded",
                            "monitor_health_reason": "pipeline_health_missing",
                            "monitor_health_age_sec": None,
                        }
            else:
                out[monitor_key] = {
                    "monitor_healthy": True,
                    "monitor_health_state": "healthy",
                    "monitor_health_reason": "not_ws_gated_market",
                    "monitor_health_age_sec": 0.0,
                }
            out[monitor_key]["status"] = status

        return {
            "status": "ok",
            "user_id": f"user_{user_number}",
            "count": len(out),
            "monitors": out,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/symbols")
async def get_symbols():
    """Get available symbols for the symbol picker dropdown"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT symbol
            FROM live_data.symbols_list
            ORDER BY symbol
        """)
        
        results = cursor.fetchall()
        conn.close()
        
        symbols = []
        for row in results:
            symbol = row[0]
            symbols.append(symbol)
        
        return {
            "status": "ok",
            "count": len(symbols),
            "symbols": symbols
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/monitor/{monitor_id}")
async def get_monitor_details(monitor_id: int, user_id: Optional[str] = None):
    """Get details for a specific monitor"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        user_number = _session_user_number_from_optional_user_id(user_id)
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, name, symbol, strategy, position_size, multiplier, total_position, position_type, bankroll_allotment_total, auto_trade, paper_trade, test_filter, market
            FROM users.monitor_list_{user_number}
            WHERE id = %s AND status = 'active'
        """, (monitor_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            monitor_id, name, symbol, strategy, position_size, multiplier, total_position, position_type, bankroll_allotment_total, auto_trade, paper_trade, test_filter, market = result
            mkt = (market or "").strip().lower()
            if mkt not in ("hourly", "15m"):
                mkt = None
            return {
                "status": "ok",
                "monitor": {
                    "id": monitor_id,
                    "name": name,
                    "symbol": symbol,
                    "strategy": strategy,
                    "position_size": position_size,
                    "multiplier": multiplier,
                    "total_position": total_position,
                    "position_type": position_type,
                    "bankroll_allotment_total": bankroll_allotment_total,
                    "auto_trade": auto_trade,
                    "paper_trade": bool((paper_trade or False) or (test_filter or False)),
                    "test_filter": bool(test_filter) if test_filter is not None else False,
                    "market": mkt,
                }
            }
        else:
            return {
                "status": "error",
                "message": "Monitor not found"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/monitor/{monitor_id}/update")
async def update_monitor_details(monitor_id: int, request: dict, user_id: Optional[str] = None):
    """Update details for a specific monitor"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        user_number = _session_user_number_from_optional_user_id(user_id)
        
        # Get update data from request
        symbol = request.get("symbol")
        strategy = request.get("strategy")
        position_size = request.get("position_size")
        multiplier = request.get("multiplier")
        total_position = request.get("total_position")
        position_type = request.get("position_type")
        
        if not symbol and not strategy and position_size is None and multiplier is None and total_position is None and position_type is None:
            return {
                "status": "error",
                "message": "No fields to update"
            }
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        
        # Build update query dynamically
        update_fields = []
        values = []
        
        if symbol is not None:
            update_fields.append("symbol = %s")
            values.append(symbol)
        
        if strategy is not None:
            update_fields.append("strategy = %s")
            values.append(strategy)
        
        if position_size is not None:
            update_fields.append("position_size = %s")
            values.append(position_size)
        
        if multiplier is not None:
            update_fields.append("multiplier = %s")
            values.append(multiplier)
        
        if total_position is not None:
            update_fields.append("total_position = %s")
            values.append(total_position)
        
        if position_type is not None:
            update_fields.append("position_type = %s")
            values.append(position_type)
        
        values.append(monitor_id)
        
        query = f"""
            UPDATE users.monitor_list_{user_number}
            SET {', '.join(update_fields)}
            WHERE id = %s AND status = 'active'
        """
        
        cursor.execute(query, values)
        
        if cursor.rowcount == 0:
            conn.close()
            return {
                "status": "error",
                "message": "Monitor not found or no changes made"
            }
        
        conn.commit()
        conn.close()
        
        return {
            "status": "ok",
            "message": "Monitor updated successfully"
        }
            
    except HTTPException:
        raise
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/monitors/names")
async def get_monitor_names(user_id: Optional[str] = None):
    """Get just the monitor names for the monitor picker dropdown"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        user_number = _session_user_number_from_optional_user_id(user_id)
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, name, symbol, market, strategy, auto_trade_status, cooldown_timer
            FROM users.monitor_list_{user_number}
            WHERE status = 'active'
            ORDER BY name
        """)
        results = cursor.fetchall()
        conn.close()
        monitors = []
        for row in results:
            monitor_id, name, symbol, market, strategy, auto_trade_status, cooldown_timer = row
            mkt = (market or "").strip().lower() if market else None
            if mkt not in ("hourly", "15m"):
                mkt = None
            monitors.append({
                "id": monitor_id,
                "name": name,
                "symbol": symbol,
                "market": mkt,
                "strategy": strategy,
                "auto_trade_status": (str(auto_trade_status).strip().lower() if auto_trade_status is not None else "inactive"),
                "cooldown_timer": int(cooldown_timer or 0),
            })
        
        return {
            "status": "ok",
            "user_id": f"user_{user_number}",
            "count": len(monitors),
            "monitors": monitors
        }
    except HTTPException:
        raise
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/monitors/allocation")
async def get_monitors_allocation(
    user_id: Optional[str] = None,
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — which account_balance table backs dollar amounts (matches UI toggle)",
    ),
):
    """Get bankroll allocation data for active monitors"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        user_number = _session_user_number_from_optional_user_id(user_id)
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        with conn.cursor() as cursor:
            # Non-archived monitors with a positive allotment *percentage* (stored as decimal, e.g. 0.10 = 10%).
            # Do not require bankroll_allotment_total > 0: totals are often still zero when the monitor was
            # created before any bankroll existed; recompute display dollars from current bankroll × pct.
            cursor.execute(f"""
                SELECT 
                    id,
                    name,
                    symbol,
                    strategy,
                    bankroll_allotment_pct,
                    bankroll_allotment_total,
                    status
                FROM users.monitor_list_{user_number}
                WHERE status != 'ARCHIVED' AND COALESCE(bankroll_allotment_pct, 0) > 0
                ORDER BY bankroll_allotment_pct DESC, id
            """)
            
            monitor_results = cursor.fetchall()
            
            # Get total bankroll from account_balance (stored in cents)
            ab_ident = sql_ident_qualified_table(
                account_balance_table_for_user(
                    user_number, client_trading_mode=trading_mode
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                SELECT bankroll_current, portfolio
                FROM {}
                ORDER BY timestamp DESC
                LIMIT 1
                """
                ).format(ab_ident)
            )
            
            balance_result = cursor.fetchone()
            bankroll_value = balance_result[0] if balance_result and balance_result[0] else 0
            portfolio_value = balance_result[1] if balance_result and balance_result[1] else 0
            
            # Use bankroll_current if available, otherwise portfolio (both in cents)
            total_bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value
            total_bankroll_dollars = total_bankroll_cents / 100  # Convert cents to dollars
            
        conn.close()
        
        # Transform database results to frontend format
        allocations = []
        for row in monitor_results:
            monitor_id, name, symbol, strategy, bankroll_allotment_pct, bankroll_allotment_total, status = row

            # bankroll_allotment_pct is decimal fraction (0.10 = 10%)
            pct_decimal = float(bankroll_allotment_pct or 0)
            percentage = pct_decimal * 100
            # Prefer live bankroll × pct so the chart matches portfolio header after balance moves
            dollar_amount = total_bankroll_dollars * pct_decimal
            if dollar_amount <= 0 and bankroll_allotment_total:
                dollar_amount = float(bankroll_allotment_total) / 100.0

            allocations.append({
                "id": f"mon_{user_number}_{monitor_id}",
                "name": name,
                "symbol": symbol,
                "strategy": strategy,
                "bankroll_pct": round(percentage, 2),
                "dollar_amount": round(dollar_amount, 2),
                "total_bankroll": total_bankroll_dollars,
                "status": status,
            })
        
        return {
            "status": "ok",
            "allocations": allocations,
            "total_bankroll": total_bankroll_dollars
        }
        
    except HTTPException:
        raise
    except Exception as e:
        _main_logger.warning(f"Error getting monitors allocation: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/monitors/allocation/update")
async def update_monitors_allocation(request: dict):
    """Update bankroll allocation percentages for monitors"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        updates = request.get("updates", [])
        
        if not updates:
            return {"status": "error", "message": "No updates provided"}
        
        user_number = _session_user_number_from_optional_user_id(request.get("user_id"))
        tm = request.get("trading_mode")
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        with conn.cursor() as cursor:
            # Get current total bankroll to calculate new dollar amounts
            ab_ident = sql_ident_qualified_table(
                account_balance_table_for_user(
                    user_number, client_trading_mode=tm
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                SELECT bankroll_current, portfolio
                FROM {}
                ORDER BY timestamp DESC
                LIMIT 1
                """
                ).format(ab_ident)
            )

            balance_result = cursor.fetchone()
            bankroll_value = balance_result[0] if balance_result and balance_result[0] else 0
            portfolio_value = balance_result[1] if balance_result and balance_result[1] else 0

            # Use bankroll_current if available, otherwise portfolio (both in cents)
            total_bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value

            # Update each monitor's allocation
            for update in updates:
                monitor_id = update.get("id", "").replace(f"mon_{user_number}_", "")
                new_percentage = update.get("percentage", 0)
                
                if not monitor_id or new_percentage < 0:
                    continue
                
                # Convert percentage to decimal (99% -> 0.99)
                new_decimal = new_percentage / 100
                
                # Calculate new dollar amount in cents
                new_dollar_amount_cents = int(total_bankroll_cents * new_decimal)
                
                # Update the monitor's allocation
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET 
                        bankroll_allotment_pct = %s,
                        bankroll_allotment_total = %s
                    WHERE id = %s AND status = 'active'
                """, (new_decimal, new_dollar_amount_cents, monitor_id))
                
                # CRITICAL: Recalculate total_position after allotment change
                # Get current monitor settings for calculation
                cursor.execute(f"""
                    SELECT position_size, position_type, multiplier, current_max_pct_exposure 
                    FROM users.monitor_list_{user_number} 
                    WHERE id = %s
                """, (monitor_id,))
                
                pos_result = cursor.fetchone()
                if pos_result:
                    position_size, position_type, multiplier, current_max_pct_exposure = pos_result
                    
                    multiplier_value = float(multiplier or 0)
                    max_pct_cap = None
                    try:
                        if current_max_pct_exposure is not None:
                            max_pct_cap = float(current_max_pct_exposure)
                    except (TypeError, ValueError):
                        max_pct_cap = None
                    
                    if multiplier_value == 0:
                        new_total_position = 1
                    elif position_type == 'percent':
                        # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                        allotment_dollars = new_dollar_amount_cents / 100
                        base_pct = (position_size or 0) / 100.0
                        effective_pct = base_pct * multiplier_value
                        if max_pct_cap is not None and max_pct_cap > 0:
                            effective_pct = min(effective_pct, max_pct_cap)
                        new_total_position = int(round(allotment_dollars * effective_pct))
                        if new_total_position < 1:
                            new_total_position = 1
                    else:
                        # For contracts: position_size * multiplier
                        new_total_position = int(position_size * multiplier_value)
                    
                    # Update total_position
                    cursor.execute(f"""
                        UPDATE users.monitor_list_{user_number} 
                        SET total_position = %s 
                        WHERE id = %s
                    """, (new_total_position, monitor_id))
                    
                    _main_logger.debug(f"Updated monitor {monitor_id}: {new_percentage}% (${new_dollar_amount_cents/100:.2f}) -> total_position: {new_total_position}")
                    
                    # Emit frontend event via Redis preferences channel.
                    try:
                        from backend.core.trading_redis_comms import (
                            publish_preferences_event,
                            use_trading_redis_comms,
                        )
                        payload = {
                            "monitor_id": monitor_id,
                            "total_position": new_total_position,
                            "multiplier": multiplier_value,
                        }
                        if use_trading_redis_comms():
                            if not publish_preferences_event(
                                "monitor_total_position_updated",
                                payload,
                                tenant_user_no=user_number,
                            ):
                                _main_logger.warning(
                                    "Redis preferences publish failed for monitor_total_position_updated "
                                    "(monitor_id=%s)",
                                    monitor_id,
                                )
                    except Exception as e:
                        _main_logger.warning(
                            "Failed to emit total_position update notification: %s", e
                        )
                else:
                    _main_logger.debug(f"Updated monitor {monitor_id}: {new_percentage}% (${new_dollar_amount_cents/100:.2f}) - no position data found")
        
        conn.commit()
        conn.close()
        
        return {
            "status": "ok",
            "message": f"Updated {len(updates)} monitor allocations"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        _main_logger.warning(f"Error updating monitors allocation: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/monitors/update-order")
async def update_monitors_order(request: dict):
    """Update the dashboard order of monitors"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        monitor_orders = request.get("monitor_orders", [])
        
        if not monitor_orders:
            return {"status": "error", "message": "No monitor orders provided"}
        
        user_number = _session_user_number_from_optional_user_id(request.get("user_id"))
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        cursor = conn.cursor()
        
        # Update each monitor's dashboard_order
        for order_data in monitor_orders:
            monitor_id = order_data.get("monitor_id")
            new_order = order_data.get("order")
            
            if monitor_id and new_order is not None:
                # Extract the numeric ID from the monitor_id (e.g., mon_0001_10001 -> 10001 or MON_0001_10001 -> 10001)
                if "_" in monitor_id and (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")):
                    numeric_id = monitor_id.split("_")[-1]
                else:
                    numeric_id = monitor_id
                
                _main_logger.debug(f"[MONITOR ORDER] Updating monitor {monitor_id} -> numeric_id: {numeric_id}, order: {new_order}")
                
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET dashboard_order = %s
                    WHERE id = %s
                """, (new_order, numeric_id))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Monitor order updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/toggle-auto-trade")
async def toggle_auto_trade(request: dict):
    """Toggle auto_trade boolean value for a specific monitor"""
    try:
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        auto_trade = request.get("auto_trade")
        
        if not monitor_id or auto_trade is None:
            return {"status": "error", "message": "Missing monitor_id or auto_trade parameter"}
        
        user_number, db_monitor_id = _monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )
        
        # Update the database directly
        try:
            from backend.core.config.database import get_postgresql_connection
            conn = get_postgresql_connection()
            
            with conn.cursor() as cursor:
                # Update ONLY auto_trade boolean - do NOT change auto_trade_status
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET auto_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (auto_trade, db_monitor_id))
                
                if cursor.rowcount == 0:
                    conn.close()
                    return {"status": "error", "message": "Monitor not found"}
                
            conn.commit()
            conn.close()
            
            _main_logger.debug(f"[MAIN] ✅ Updated monitor {monitor_id} auto_trade to {auto_trade}")
            
        except Exception as e:
            _main_logger.warning(f"[MAIN] ❌ Error updating database: {e}")
            return {"status": "error", "message": f"Database error: {str(e)}"}
        
        # Broadcast the auto trade toggle to this tenant's WebSocket clients only
        try:
            message = {
                "type": "auto_trade_toggled",
                "monitor_id": monitor_id,
                "auto_trade": auto_trade,
                "tenant_user_no": _norm_slot(user_number),
                "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}",
            }
            
            _main_logger.debug(f"[MAIN] 🔔 Broadcasting auto trade toggle: {message}")
            _main_logger.debug(
                "[MAIN] 🔔 Preferences WebSocket clients (all tenants): %s",
                _prefs_ws_client_count(),
            )
            await _prefs_ws_send_json_to_slot(message, user_number)
            _main_logger.debug("[MAIN] ✅ Auto trade toggle sent to tenant %s", user_number)
        except Exception as e:
            _main_logger.debug(f"[MAIN] ⚠️ Warning: Failed to broadcast auto trade toggle: {e}")
        
        return {"status": "ok", "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        _main_logger.warning(f"Error in toggle auto trade: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/toggle-paper-trade")
async def toggle_paper_trade(request: Request):
    """Toggle paper_trade boolean value for a specific monitor"""
    try:
        if is_paper_trading():
            return {
                "status": "error",
                "message": "global_paper_mode",
                "code": "global_paper_mode",
            }

        # Extract parameters from request body
        data = await request.json()
        monitor_id = data.get("monitor_id")
        paper_trade = data.get("paper_trade")
        
        if not monitor_id or paper_trade is None:
            return {"status": "error", "message": "Missing monitor_id or paper_trade parameter"}
        
        user_number, db_monitor_id = _monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), data.get("user_id")
        )
        
        # Update the database directly
        try:
            from backend.core.config.database import get_postgresql_connection
            conn = get_postgresql_connection()
            
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT COALESCE(test_filter, FALSE)
                    FROM users.monitor_list_{user_number}
                    WHERE id = %s
                    """,
                    (db_monitor_id,),
                )
                tf_row = cursor.fetchone()
                test_filter_monitor = bool(tf_row and tf_row[0] is True)
                if test_filter_monitor and not paper_trade:
                    conn.close()
                    return {
                        "status": "error",
                        "message": "Test filter monitors must use PAPER mode",
                        "code": "test_filter_paper_only",
                    }

                # Update paper_trade boolean
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET paper_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (paper_trade, db_monitor_id))
                
                if cursor.rowcount == 0:
                    conn.close()
                    return {"status": "error", "message": "Monitor not found"}
                
            conn.commit()
            conn.close()
            
            _main_logger.debug(f"[MAIN] ✅ Updated monitor {monitor_id} paper_trade to {paper_trade}")
            
            message = {
                "type": "paper_trade_toggled",
                "monitor_id": monitor_id,  # Keep original format (MON_0001_10001)
                "paper_trade": paper_trade,
                "tenant_user_no": _norm_slot(user_number),
            }
            await _prefs_ws_send_json_to_slot(message, user_number)
            _main_logger.debug("[MAIN] ✅ Paper trade change sent to tenant %s", user_number)
            
            return {"status": "ok", "message": "Paper trade updated successfully"}
            
        except Exception as e:
            _main_logger.warning(f"[MAIN] ❌ Error updating database: {e}")
            return {"status": "error", "message": f"Database error: {str(e)}"}
            
    except HTTPException:
        raise
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error toggling paper trade: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/update_monitor_position")
async def update_monitor_position(request: Request):
    """Proxy endpoint to forward monitor position updates to monitor_manager"""
    try:
        data = await request.json()
        monitor_id = data.get("monitor_id")
        position_size = data.get("position_size")
        position_type = data.get("position_type")
        multiplier = data.get("multiplier")

        if monitor_id is None or position_size is None or position_type is None or multiplier is None:
            return {"error": "Missing required fields"}

        slot = _norm_slot(resolved_tenant_user_no_for_app())
        forward = {**data, "user_number": slot}
        mm_key = f"monitor_manager_{slot}"
        _main_logger.debug(f"[PROXY] Forwarding to {mm_key}: {forward}")

        response = requests.post(
            f"http://localhost:{get_port(mm_key)}/api/update_monitor_position",
            json=forward,
            timeout=30,
        )
        
        _main_logger.debug(f"[PROXY] Monitor manager response: {response.status_code}")
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"Monitor manager returned status {response.status_code}"}, response.status_code
            
    except Exception as e:
        _main_logger.debug(f"[PROXY] Error: {e}")
        return {"error": str(e)}, 500

@app.post("/api/monitor/archive")
async def archive_monitor(request: dict):
    """Archive a monitor by setting auto_trade to FALSE and status to ARCHIVED"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")
        
        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}
        
        user_number, db_monitor_id = _monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        slot = _norm_slot(user_number)
        tenant_schema = f"users_{slot}"
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))

        with conn.cursor() as cursor:
            # First, set auto_trade to FALSE to stop trading
            cursor.execute(
                sql.SQL(
                    """
                UPDATE {}
                SET auto_trade = FALSE
                WHERE id = %s
            """
                ).format(ml_ident),
                (db_monitor_id,),
            )

            if cursor.rowcount == 0:
                conn.close()
                return {"status": "error", "message": "Monitor not found"}

            # Then, set status to ARCHIVED to hide from dashboard
            cursor.execute(
                sql.SQL(
                    """
                UPDATE {}
                SET status = 'ARCHIVED'
                WHERE id = %s
            """
                ).format(ml_ident),
                (db_monitor_id,),
            )

            performance_table = f"monitor_cycle_performance_{slot}_{db_monitor_id}"
            # Bind params must not use legacy users.* (tenant isolation); use real tenant schema.
            cursor.execute(
                "SELECT to_regclass(%s)",
                (f"{tenant_schema}.{performance_table}",),
            )
            table_exists = cursor.fetchone()[0]

            if table_exists:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS archive")
                cursor.execute(
                    "SELECT to_regclass(%s)",
                    (f"archive.{performance_table}",),
                )
                archived_exists = cursor.fetchone()[0]
                if archived_exists:
                    cursor.execute(
                        sql.SQL("DROP TABLE {}.{}")
                        .format(sql.Identifier("archive"), sql.Identifier(performance_table))
                    )

                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} SET SCHEMA archive").format(
                        sql.Identifier(tenant_schema), sql.Identifier(performance_table)
                    )
                )

            try:
                trade_arch = archive_trades_for_monitor(
                    cursor, user_number, db_monitor_id, dry_run=False
                )
                _main_logger.debug("[ARCHIVE] trade log archival: %s", trade_arch)
            except Exception as trade_arch_exc:
                conn.rollback()
                conn.close()
                _main_logger.warning(
                    "[ARCHIVE] trade log archival failed (rolled back monitor archive): %s",
                    trade_arch_exc,
                )
                return {
                    "status": "error",
                    "message": f"Trade archive failed: {trade_arch_exc!s}",
                }

        conn.commit()
        conn.close()
        
        _main_logger.debug(f"[ARCHIVE] Monitor {monitor_name} (ID: {monitor_id}) archived successfully")
        
        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "archived",
            "tenant_user_no": _norm_slot(user_number),
        }
        await _prefs_ws_send_json_to_slot(message, user_number)
        _main_logger.debug("[ARCHIVE] ✅ Monitor list update sent to tenant %s", user_number)
        
        return {"status": "ok", "message": f"Monitor {monitor_name} archived successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        _main_logger.warning(f"Error archiving monitor: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/deactivate")
async def deactivate_monitor(request: dict):
    """Turn off a monitor: status = 'inactive' (stops AES/ATS scripts); also set auto_trade FALSE and auto_trade_status 'off' for UI/auto-trading."""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")
        
        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}
        
        user_number, db_monitor_id = _monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        slot = _norm_slot(user_number)
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))

        with conn.cursor() as cursor:
            # status = 'inactive' → AES/ATS for this monitor are torn down. auto_trade/auto_trade_status are for auto-trading only.
            cursor.execute(
                sql.SQL(
                    """
                UPDATE {}
                SET auto_trade = FALSE, status = 'inactive', auto_trade_status = 'off'
                WHERE id = %s
            """
                ).format(ml_ident),
                (db_monitor_id,),
            )
            
            if cursor.rowcount == 0:
                conn.close()
                return {"status": "error", "message": "Monitor not found"}
            
        conn.commit()
        conn.close()
        
        _main_logger.debug(f"[DEACTIVATE] Monitor {monitor_name} (ID: {monitor_id}) deactivated successfully")

        # Trigger an immediate monitor process sync so AES/ATS for this monitor
        # are torn down promptly. Try monitor_manager HTTP first; then always run
        # sync in-process so teardown happens even if monitor_manager is unreachable.
        try:
            import requests
            from backend.core.port_config import get_port

            monitor_manager_port = get_port("monitor_manager")
            sync_resp = requests.post(
                f"http://localhost:{monitor_manager_port}/api/sync_monitor_processes",
                json={"source": "main_app_deactivate", "monitor_id": monitor_id},
                timeout=10,
            )
            if not sync_resp.ok:
                _main_logger.warning(
                    f"[DEACTIVATE] ⚠️ sync_monitor_processes returned {sync_resp.status_code}: {sync_resp.text}"
                )
        except Exception as e:
            _main_logger.warning(f"[DEACTIVATE] ⚠️ Failed to trigger monitor process sync via HTTP: {e}")

        # Always run sync in-process so AES/ATS are torn down regardless of monitor_manager.
        try:
            import subprocess
            from backend.util.paths import get_project_root, get_supervisorctl_path, get_supervisor_config_path

            proot = get_project_root()
            gen_script = os.path.join(proot, "scripts", "config", "generate_unified_supervisor_config.py")
            if os.path.isfile(gen_script):
                env = os.environ.copy()
                env.setdefault("PYTHONPATH", proot)
                env.setdefault("REC_PROJECT_ROOT", proot)
                r0 = subprocess.run(
                    [sys.executable, gen_script],
                    cwd=proot,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r0.returncode != 0:
                    _main_logger.warning(f"[DEACTIVATE] ⚠️ generate_unified_supervisor_config failed: {r0.stderr or r0.stdout}")
                else:
                    ctl = get_supervisorctl_path()
                    cfg = get_supervisor_config_path()
                    for cmd in ["reread", "update"]:
                        r = subprocess.run([ctl, "-c", cfg, cmd], cwd=proot, capture_output=True, text=True, timeout=10)
                        if r.returncode != 0:
                            _main_logger.warning(f"[DEACTIVATE] ⚠️ supervisorctl {cmd} failed: {r.stderr or r.stdout}")
                            break
                    else:
                        _main_logger.debug("[DEACTIVATE] In-process monitor process sync completed")
            else:
                _main_logger.warning(f"[DEACTIVATE] ⚠️ generate script not found: {gen_script}")
        except Exception as e:
            _main_logger.warning(f"[DEACTIVATE] ⚠️ In-process monitor process sync failed: {e}")

        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "deactivated",
            "tenant_user_no": _norm_slot(user_number),
        }
        await _prefs_ws_send_json_to_slot(message, user_number)
        _main_logger.debug("[DEACTIVATE] ✅ Monitor list update sent to tenant %s", user_number)
        
        return {"status": "ok", "message": f"Monitor {monitor_name} deactivated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        _main_logger.warning(f"Error deactivating monitor: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/activate")
async def activate_monitor(request: dict):
    """Turn on a monitor: status = 'active' so AES/ATS script iterations are started. Does not change auto_trade/auto_trade_status."""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")
        
        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}
        
        user_number, db_monitor_id = _monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        slot = _norm_slot(user_number)
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))

        with conn.cursor() as cursor:
            # Set status to 'active' to activate the monitor
            cursor.execute(
                sql.SQL(
                    """
                UPDATE {}
                SET status = 'active'
                WHERE id = %s
            """
                ).format(ml_ident),
                (db_monitor_id,),
            )
            
            if cursor.rowcount == 0:
                conn.close()
                return {"status": "error", "message": "Monitor not found"}
            
        conn.commit()
        conn.close()
        
        _main_logger.debug(f"[ACTIVATE] Monitor {monitor_name} (ID: {monitor_id}) activated successfully")

        # Trigger sync so AES/ATS for this monitor are spun up. Try monitor_manager HTTP first;
        # then always run sync in-process so spawn happens even if monitor_manager is unreachable.
        try:
            import requests
            from backend.core.port_config import get_port

            monitor_manager_port = get_port("monitor_manager")
            sync_resp = requests.post(
                f"http://localhost:{monitor_manager_port}/api/sync_monitor_processes",
                json={"source": "main_app_activate", "monitor_id": monitor_id},
                timeout=10,
            )
            if not sync_resp.ok:
                _main_logger.warning(
                    f"[ACTIVATE] ⚠️ sync_monitor_processes returned {sync_resp.status_code}: {sync_resp.text}"
                )
        except Exception as e:
            _main_logger.warning(f"[ACTIVATE] ⚠️ Failed to trigger monitor process sync via HTTP: {e}")

        # Always run sync in-process so AES/ATS are spawned regardless of monitor_manager.
        try:
            import subprocess
            from backend.util.paths import get_project_root, get_supervisorctl_path, get_supervisor_config_path

            proot = get_project_root()
            gen_script = os.path.join(proot, "scripts", "config", "generate_unified_supervisor_config.py")
            if os.path.isfile(gen_script):
                env = os.environ.copy()
                env.setdefault("PYTHONPATH", proot)
                env.setdefault("REC_PROJECT_ROOT", proot)
                r0 = subprocess.run(
                    [sys.executable, gen_script],
                    cwd=proot,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r0.returncode != 0:
                    _main_logger.warning(f"[ACTIVATE] ⚠️ generate_unified_supervisor_config failed: {r0.stderr or r0.stdout}")
                else:
                    ctl = get_supervisorctl_path()
                    cfg = get_supervisor_config_path()
                    for cmd in ["reread", "update"]:
                        r = subprocess.run([ctl, "-c", cfg, cmd], cwd=proot, capture_output=True, text=True, timeout=10)
                        if r.returncode != 0:
                            _main_logger.warning(f"[ACTIVATE] ⚠️ supervisorctl {cmd} failed: {r.stderr or r.stdout}")
                            break
                    else:
                        _main_logger.debug("[ACTIVATE] In-process monitor process sync completed")
            else:
                _main_logger.warning(f"[ACTIVATE] ⚠️ generate script not found: {gen_script}")
        except Exception as e:
            _main_logger.warning(f"[ACTIVATE] ⚠️ In-process monitor process sync failed: {e}")

        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "activated",
            "tenant_user_no": _norm_slot(user_number),
        }
        await _prefs_ws_send_json_to_slot(message, user_number)
        _main_logger.debug("[ACTIVATE] ✅ Monitor list update sent to tenant %s", user_number)
        
        return {"status": "ok", "message": f"Monitor {monitor_name} activated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        _main_logger.warning(f"Error activating monitor: {e}")
        return {"status": "error", "message": str(e)}



@app.get("/api/strategies")
async def get_strategies(user_id: Optional[str] = None):
    """Strategy picker for the authenticated tenant (see :mod:`backend.core.tenant_strategy_list`)."""
    _ = user_id  # optional query ignored; session token is authoritative (rec_session may still send user_id)
    try:
        from backend.core.tenant_strategy_list import load_strategy_picker_for_slot

        slot = resolved_tenant_user_no_for_app()
        payload = load_strategy_picker_for_slot(slot)
        return {"status": "ok", **payload}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        _main_logger.warning("get_strategies: %s", e)
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/create")
async def create_monitor(request: dict):
    """Create a new monitor - delegates to monitor_manager"""
    try:
        import requests
        from backend.core.port_config import get_port
        from backend.core.tenant_context import resolved_tenant_user_no_for_app

        slot = resolved_tenant_user_no_for_app()
        monitor_manager_port = get_port(f"monitor_manager_{slot}")
        response = requests.post(
            f"http://localhost:{monitor_manager_port}/api/monitor/create",
            json=request,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": f"Monitor manager error: {response.text}"}
            
    except Exception as e:
        _main_logger.warning(f"Error forwarding monitor creation: {e}")
        return {"status": "error", "message": str(e)}

# Main entry point
if __name__ == "__main__":
    _main_logger.debug(f"[MAIN] 🚀 Launching app on centralized port {MAIN_APP_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=MAIN_APP_PORT)

