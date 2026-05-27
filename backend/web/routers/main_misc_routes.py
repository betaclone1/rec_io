"""System settings, paper seed, trade prefs, account sync, dashboard/portfolio helpers, logs, health."""

import asyncio
import json
import logging
import os
import threading
import time
from typing import Optional, Tuple

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from psycopg2 import sql
from starlette.responses import Response

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import (
    effective_tenant_context_for_sql_rewrite,
    resolved_tenant_user_no_for_app,
)
from backend.core.tenant_legacy_sql import legacy_users_monitor_list
from backend.trading_mode import account_balance_table_for_user, sql_ident_qualified_table
from backend.web.main_realtime import broadcast_db_change
from backend.web.response_cache_headers import apply_private_no_store_headers
from backend.util.trade_logger import get_trade_logs, log_trade_event

_log = logging.getLogger("main_app")

_frontend_changes_lock = threading.Lock()
_frontend_changes_cache: Optional[Tuple[float, float]] = None
_FRONTEND_CHANGES_TTL_SEC = 5.0

main_misc_router = APIRouter()


@main_misc_router.get("/api/system_settings")
async def get_system_settings_endpoint(response: Response):
    """Global system settings (drawdown halt, threshold) for dashboard gear menu."""
    apply_private_no_store_headers(response)
    from backend.core.system_settings_store import fetch_system_settings_row

    num = resolved_tenant_user_no_for_app()
    row = fetch_system_settings_row(num)
    if not row:
        return {"status": "error", "message": "system_settings not available for user"}
    return {"status": "ok", "user_number": num, **row}


@main_misc_router.post("/api/system_settings")
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
    mw_requested = any(
        k in body for k in ("market_wide_loss_prevention", "hero_monitor_id", "stop_loss_count_threshold")
    )
    dd_requested = halt is not None or pct is not None

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

    if not dd_requested and not mw_requested:
        return {"status": "error", "message": "no fields to update"}

    if dd_requested:
        ok, msg = update_system_settings_drawdown(
            num,
            drawdown_trading_halt=halt,
            drawdown_reset_threshold_pct=pct,
        )
        if not ok:
            return {"status": "error", "message": msg}

    mw_reconcile_done = False
    mw_reconcile_failed = False
    if mw_requested:
        from backend.core.system_settings_store import update_system_settings_market_wide_loss_prevention

        ok_mw, msg_mw, rec_ok = update_system_settings_market_wide_loss_prevention(num, body)
        if not ok_mw:
            return {"status": "error", "message": msg_mw}
        if msg_mw != "noop":
            mw_reconcile_done = rec_ok is True
            mw_reconcile_failed = rec_ok is False

    row = fetch_system_settings_row(num)
    out: dict = {"status": "ok", "user_number": num, **(row or {})}
    if mw_reconcile_done:
        out["fleet_sim_trade_lp_reconcile_completed"] = True
    elif mw_reconcile_failed:
        out["fleet_sim_trade_lp_reconcile_completed"] = False
    return out


@main_misc_router.post("/api/paper/bankroll/seed")
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
        _log.warning("paper bankroll seed: %s", e)
        return {"status": "error", "message": str(e)}


@main_misc_router.get("/api/get_trade_history_preferences")
async def get_trade_history_preferences_route():
    """Trade history UI prefs: same process/session as the tab (no read_api hop)."""
    from backend.core.trade_history_preferences_handlers import trade_history_preferences_get

    return trade_history_preferences_get()


@main_misc_router.post("/api/set_trade_history_preferences")
async def set_trade_history_preferences_route(request: Request):
    """Persist trade history UI prefs; Redis fanout for /ws/preferences."""
    from backend.core.trade_history_preferences_handlers import trade_history_preferences_post

    return await trade_history_preferences_post(request)


@main_misc_router.post("/api/account/sync")
async def trigger_account_sync():
    """Trigger a full account retrieval cycle from kalshi_account_sync (balance, subaccounts, account history). Runs in background; returns immediately."""

    def _run_sync():
        try:
            from backend.kalshi_account_sync_ws import sync_balance

            sync_balance()
        except Exception as e:
            _log.warning("account/sync: sync_balance failed: %s", e)

    threading.Thread(target=_run_sync, daemon=True).start()
    return {"ok": True}


def _compute_frontend_last_modified() -> float:
    latest = 0.0
    for root, dirs, files in os.walk("frontend"):
        for f in files:
            path = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(path)
                if mtime > latest:
                    latest = mtime
            except Exception:
                pass
    return float(latest)


@main_misc_router.get("/frontend-changes")
async def frontend_changes():
    """Get the latest modification time of frontend files for cache busting."""
    global _frontend_changes_cache
    now_m = time.monotonic()
    with _frontend_changes_lock:
        if _frontend_changes_cache is not None and now_m < _frontend_changes_cache[0]:
            return {"last_modified": _frontend_changes_cache[1]}
    latest = await asyncio.to_thread(_compute_frontend_last_modified)
    with _frontend_changes_lock:
        _frontend_changes_cache = (now_m + _FRONTEND_CHANGES_TTL_SEC, latest)
    return {"last_modified": latest}


@main_misc_router.get("/api/trade_logs")
async def get_trade_logs_endpoint(ticket_id: str = None, service: str = None, limit: int = 100):
    """Get trade logs from PostgreSQL"""
    try:
        logs = get_trade_logs(ticket_id=ticket_id, service=service, limit=limit)
        return {"status": "ok", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@main_misc_router.get("/api/historical_price_data")
async def get_historical_price_data(
    symbol: str = "BTC", limit: int = 1000, start_date: str = None, end_date: str = None
):
    """Get historical price data from PostgreSQL"""
    try:
        conn = get_postgresql_connection()

        query = """
            SELECT timestamp, open_price, high_price, low_price, close_price, volume, momentum
            FROM live_data.historical_price_data 
            WHERE symbol = %s
        """
        params = [symbol.upper()]

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

        data = []
        for row in results:
            data.append(
                {
                    "timestamp": row[0].isoformat() if row[0] else None,
                    "open": float(row[1]) if row[1] else None,
                    "high": float(row[2]) if row[2] else None,
                    "low": float(row[3]) if row[3] else None,
                    "close": float(row[4]) if row[4] else None,
                    "volume": float(row[5]) if row[5] else None,
                    "momentum": float(row[6]) if row[6] else None,
                }
            )

        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "count": len(data),
            "data": data,
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


@main_misc_router.post("/api/log_event")
async def log_event(request: Request):
    """Log trade events to PostgreSQL instead of text files"""
    try:
        data = await request.json()
        ticket_id = data.get("ticket_id", "UNKNOWN")
        message = data.get("message", "No message provided")

        log_trade_event(ticket_id, message, service="main")

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@main_misc_router.get("/api/system/health")
async def get_system_health():
    """Get current system health status from database"""
    try:
        conn = get_postgresql_connection()

        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM system.health_status WHERE id = 1")
            result = cursor.fetchone()

            if result:
                _pk, overall_status, cpu_percent, memory_percent, disk_percent, database_status, supervisor_status, services_healthy, services_total, failed_services, health_details, timestamp = result

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
                    "timestamp": timestamp.isoformat() if timestamp else None,
                }
            else:
                return {"error": "No health data available"}

    except Exception as e:
        _log.debug("[SYSTEM HEALTH] Error getting system health: %s", e)
        return {"error": "Failed to get system health information"}


@main_misc_router.get("/api/portfolio/current")
async def get_current_portfolio(trading_mode: Optional[str] = None):
    """Get the current portfolio value from PostgreSQL"""
    try:
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
            portfolio_value = float(result[0]) / 100
            return {
                "status": "ok",
                "portfolio": portfolio_value,
            }
        else:
            return {
                "status": "error",
                "message": "No portfolio data found",
            }

    except Exception as e:
        _log.warning("Error getting current portfolio: %s", e)
        return {"status": "error", "message": str(e)}


@main_misc_router.get("/api/dashboard/performance-snapshot")
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
        _log.warning("[dashboard performance-snapshot] redis ping failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "redis_unavailable"},
        )

    try:
        raw = r.get(redis_key_dashboard_performance_snapshot(slot))
    except Exception as e:
        _log.warning("[dashboard performance-snapshot] redis get failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "message": "redis_read_failed"},
        )

    if not raw:
        try:
            from backend.core.performance_rollups import publish_performance_rollups_ws_snapshot

            publish_performance_rollups_ws_snapshot(slot)
            raw = r.get(redis_key_dashboard_performance_snapshot(slot))
        except Exception as e:
            _log.warning(
                "[dashboard performance-snapshot] lazy publish failed slot=%s: %s",
                slot,
                e,
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
        _log.warning("[dashboard performance-snapshot] parse failed: %s", e)
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


@main_misc_router.post("/api/dashboard/preferences")
async def save_dashboard_preferences(request: Request):
    """Save dashboard preferences for the current user"""
    try:
        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()

        data = await request.json()
        _log.debug("[DASHBOARD PREFERENCES] Received data: %s", data)
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
        _log.debug(
            "[DASHBOARD PREFERENCES] Extracted values: portfolio_chart_view=%s, monitor_view_mode=%s, monitor_sort_by=%s, allocation_view=%s, portfolio_view=%s",
            portfolio_chart_view,
            monitor_view_mode,
            monitor_sort_by,
            allocation_view,
            portfolio_view,
        )

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

        _log.debug("[DASHBOARD PREFERENCES] Successfully saved preferences to database")
        return {
            "status": "ok",
            "message": "Preferences saved successfully",
        }

    except psycopg2.Error as e:
        _log.warning("Error saving dashboard preferences (table may be missing for slot): %s", e)
        return {"status": "error", "message": str(e)}
    except Exception as e:
        _log.warning("Error saving dashboard preferences: %s", e)
        return {"status": "error", "message": str(e)}


@main_misc_router.get("/api/total_position")
async def get_total_position():
    """Get total_position from the first row of the tenant ``monitor_list_*`` table."""
    try:
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
