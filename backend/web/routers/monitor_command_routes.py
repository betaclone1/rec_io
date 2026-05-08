"""Monitor bankroll read, allocation/order mutations, toggles, archive/activate, and monitor_manager proxies."""

import logging
import os
import subprocess
import sys
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Request

from backend.core.config.database import get_postgresql_connection
from backend.core.port_config import get_port
from backend.core.tenant_context import (
    effective_tenant_context_for_sql_rewrite,
    resolved_tenant_user_no_for_app,
)
from backend.core.tenant_legacy_sql import legacy_users_monitor_list
from backend.trading_mode import (
    _norm_slot,
    account_balance_table_for_user,
    is_paper_trading,
    monitor_list_fqn,
    sql_ident_qualified_table,
)
from backend.util.paths import get_project_root, get_supervisor_config_path, get_supervisorctl_path
from backend.util.trade_log_archivist import archive_trades_for_monitor
from backend.web import main_realtime
from backend.web.session_monitor_id import (
    monitor_slot_and_db_id_from_monitor_id,
    session_user_number_from_optional_user_id,
)
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

_log = logging.getLogger("main_app")

monitor_command_router = APIRouter()


@monitor_command_router.get("/api/monitor/bankroll")
async def get_monitor_bankroll(monitor_id: str):
    """Get monitor-specific bankroll allotment from PostgreSQL database."""
    try:
        conn = get_postgresql_connection()

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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
                bankroll_allotment = monitor_result["bankroll_allotment_total"] or 0
                return {
                    "monitor_id": monitor_id,
                    "bankroll_allotment_total": bankroll_allotment,
                    "name": monitor_result["name"],
                    "symbol": monitor_result["symbol"],
                }
            else:
                return {"monitor_id": monitor_id, "bankroll_allotment_total": 0, "name": "Unknown", "symbol": "BTC"}

    except Exception as e:
        _log.warning("Error getting monitor bankroll from PostgreSQL: %s", e)
        return {"monitor_id": monitor_id, "bankroll_allotment_total": 0, "name": "Unknown", "symbol": "BTC"}


@monitor_command_router.post("/api/monitor/{monitor_id}/update")
async def update_monitor_details(monitor_id: int, request: dict, user_id: Optional[str] = None):
    """Update details for a specific monitor"""
    try:
        user_number = session_user_number_from_optional_user_id(user_id)

        symbol = request.get("symbol")
        strategy = request.get("strategy")
        position_size = request.get("position_size")
        multiplier = request.get("multiplier")
        total_position = request.get("total_position")
        position_type = request.get("position_type")

        if (
            not symbol
            and not strategy
            and position_size is None
            and multiplier is None
            and total_position is None
            and position_type is None
        ):
            return {
                "status": "error",
                "message": "No fields to update",
            }

        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed",
            }

        cursor = conn.cursor()

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
                "message": "Monitor not found or no changes made",
            }

        conn.commit()
        conn.close()

        return {
            "status": "ok",
            "message": "Monitor updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }


@monitor_command_router.post("/api/monitors/allocation/update")
async def update_monitors_allocation(request: dict):
    """Update bankroll allocation percentages for monitors"""
    try:
        updates = request.get("updates", [])

        if not updates:
            return {"status": "error", "message": "No updates provided"}

        user_number = session_user_number_from_optional_user_id(request.get("user_id"))
        tm = request.get("trading_mode")

        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed",
            }

        with conn.cursor() as cursor:
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

            total_bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value

            for update in updates:
                monitor_id = update.get("id", "").replace(f"mon_{user_number}_", "")
                new_percentage = update.get("percentage", 0)

                if not monitor_id or new_percentage < 0:
                    continue

                new_decimal = new_percentage / 100

                new_dollar_amount_cents = int(total_bankroll_cents * new_decimal)

                cursor.execute(
                    f"""
                    UPDATE users.monitor_list_{user_number}
                    SET 
                        bankroll_allotment_pct = %s,
                        bankroll_allotment_total = %s
                    WHERE id = %s AND status = 'active'
                """,
                    (new_decimal, new_dollar_amount_cents, monitor_id),
                )

                cursor.execute(
                    f"""
                    SELECT position_size, position_type, multiplier, current_max_pct_exposure 
                    FROM users.monitor_list_{user_number} 
                    WHERE id = %s
                """,
                    (monitor_id,),
                )

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
                    elif position_type == "percent":
                        allotment_dollars = new_dollar_amount_cents / 100
                        base_pct = (position_size or 0) / 100.0
                        effective_pct = base_pct * multiplier_value
                        if max_pct_cap is not None and max_pct_cap > 0:
                            effective_pct = min(effective_pct, max_pct_cap)
                        new_total_position = int(round(allotment_dollars * effective_pct))
                        if new_total_position < 1:
                            new_total_position = 1
                    else:
                        new_total_position = int(position_size * multiplier_value)

                    cursor.execute(
                        f"""
                        UPDATE users.monitor_list_{user_number} 
                        SET total_position = %s 
                        WHERE id = %s
                    """,
                        (new_total_position, monitor_id),
                    )

                    _log.debug(
                        "Updated monitor %s: %s%% ($%.2f) -> total_position: %s",
                        monitor_id,
                        new_percentage,
                        new_dollar_amount_cents / 100,
                        new_total_position,
                    )

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
                                _log.warning(
                                    "Redis preferences publish failed for monitor_total_position_updated "
                                    "(monitor_id=%s)",
                                    monitor_id,
                                )
                    except Exception as e:
                        _log.warning("Failed to emit total_position update notification: %s", e)
                else:
                    _log.debug(
                        "Updated monitor %s: %s%% ($%.2f) - no position data found",
                        monitor_id,
                        new_percentage,
                        new_dollar_amount_cents / 100,
                    )

        conn.commit()
        conn.close()

        return {
            "status": "ok",
            "message": f"Updated {len(updates)} monitor allocations",
        }

    except HTTPException:
        raise
    except Exception as e:
        _log.warning("Error updating monitors allocation: %s", e)
        return {
            "status": "error",
            "message": str(e),
        }


@monitor_command_router.post("/api/monitors/update-order")
async def update_monitors_order(request: dict):
    """Update the dashboard order of monitors"""
    try:
        monitor_orders = request.get("monitor_orders", [])

        if not monitor_orders:
            return {"status": "error", "message": "No monitor orders provided"}

        user_number = session_user_number_from_optional_user_id(request.get("user_id"))

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}

        cursor = conn.cursor()

        for order_data in monitor_orders:
            monitor_id = order_data.get("monitor_id")
            new_order = order_data.get("order")

            if monitor_id and new_order is not None:
                if "_" in monitor_id and (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")):
                    numeric_id = monitor_id.split("_")[-1]
                else:
                    numeric_id = monitor_id

                _log.debug(
                    "[MONITOR ORDER] Updating monitor %s -> numeric_id: %s, order: %s",
                    monitor_id,
                    numeric_id,
                    new_order,
                )

                cursor.execute(
                    f"""
                    UPDATE users.monitor_list_{user_number}
                    SET dashboard_order = %s
                    WHERE id = %s
                """,
                    (new_order, numeric_id),
                )

        conn.commit()
        conn.close()

        return {"status": "ok", "message": "Monitor order updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@monitor_command_router.post("/api/monitor/toggle-auto-trade")
async def toggle_auto_trade(request: dict):
    """Toggle auto_trade boolean value for a specific monitor"""
    try:
        monitor_id = request.get("monitor_id")
        auto_trade = request.get("auto_trade")

        if not monitor_id or auto_trade is None:
            return {"status": "error", "message": "Missing monitor_id or auto_trade parameter"}

        user_number, db_monitor_id = monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )

        try:
            conn = get_postgresql_connection()

            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE users.monitor_list_{user_number}
                    SET auto_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """,
                    (auto_trade, db_monitor_id),
                )

                if cursor.rowcount == 0:
                    conn.close()
                    return {"status": "error", "message": "Monitor not found"}

            conn.commit()
            conn.close()

            _log.debug("[MAIN] Updated monitor %s auto_trade to %s", monitor_id, auto_trade)

        except Exception as e:
            _log.warning("[MAIN] Error updating database: %s", e)
            return {"status": "error", "message": f"Database error: {str(e)}"}

        try:
            message = {
                "type": "auto_trade_toggled",
                "monitor_id": monitor_id,
                "auto_trade": auto_trade,
                "tenant_user_no": _norm_slot(user_number),
                "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}",
            }

            _log.debug("[MAIN] Broadcasting auto trade toggle: %s", message)
            _log.debug("[MAIN] Preferences WebSocket clients (all tenants): %s", main_realtime.prefs_ws_client_count())
            await main_realtime.prefs_ws_send_json_to_slot(message, user_number)
            _log.debug("[MAIN] Auto trade toggle sent to tenant %s", user_number)
        except Exception as e:
            _log.debug("[MAIN] Warning: Failed to broadcast auto trade toggle: %s", e)

        return {"status": "ok", "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}"}

    except HTTPException:
        raise
    except Exception as e:
        _log.warning("Error in toggle auto trade: %s", e)
        return {"status": "error", "message": str(e)}


@monitor_command_router.post("/api/monitor/toggle-paper-trade")
async def toggle_paper_trade(request: Request):
    """Toggle paper_trade boolean value for a specific monitor"""
    try:
        if is_paper_trading():
            return {
                "status": "error",
                "message": "global_paper_mode",
                "code": "global_paper_mode",
            }

        data = await request.json()
        monitor_id = data.get("monitor_id")
        paper_trade = data.get("paper_trade")

        if not monitor_id or paper_trade is None:
            return {"status": "error", "message": "Missing monitor_id or paper_trade parameter"}

        user_number, db_monitor_id = monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), data.get("user_id")
        )

        try:
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

                cursor.execute(
                    f"""
                    UPDATE users.monitor_list_{user_number}
                    SET paper_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """,
                    (paper_trade, db_monitor_id),
                )

                if cursor.rowcount == 0:
                    conn.close()
                    return {"status": "error", "message": "Monitor not found"}

            conn.commit()
            conn.close()

            _log.debug("[MAIN] Updated monitor %s paper_trade to %s", monitor_id, paper_trade)

            message = {
                "type": "paper_trade_toggled",
                "monitor_id": monitor_id,
                "paper_trade": paper_trade,
                "tenant_user_no": _norm_slot(user_number),
            }
            await main_realtime.prefs_ws_send_json_to_slot(message, user_number)
            _log.debug("[MAIN] Paper trade change sent to tenant %s", user_number)

            return {"status": "ok", "message": "Paper trade updated successfully"}

        except Exception as e:
            _log.warning("[MAIN] Error updating database: %s", e)
            return {"status": "error", "message": f"Database error: {str(e)}"}

    except HTTPException:
        raise
    except Exception as e:
        _log.warning("[MAIN] Error toggling paper trade: %s", e)
        return {"status": "error", "message": str(e)}


@monitor_command_router.post("/api/update_monitor_position")
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
        _log.debug("[PROXY] Forwarding to %s: %s", mm_key, forward)

        response = requests.post(
            f"http://localhost:{get_port(mm_key)}/api/update_monitor_position",
            json=forward,
            timeout=30,
        )

        _log.debug("[PROXY] Monitor manager response: %s", response.status_code)

        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"Monitor manager returned status {response.status_code}"}, response.status_code

    except Exception as e:
        _log.debug("[PROXY] Error: %s", e)
        return {"error": str(e)}, 500


@monitor_command_router.post("/api/monitor/archive")
async def archive_monitor(request: dict):
    """Archive a monitor by setting auto_trade to FALSE and status to ARCHIVED"""
    try:
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")

        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}

        user_number, db_monitor_id = monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}

        slot = _norm_slot(user_number)
        tenant_schema = f"users_{slot}"
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))

        with conn.cursor() as cursor:
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
                        sql.SQL("DROP TABLE {}.{}").format(
                            sql.Identifier("archive"), sql.Identifier(performance_table)
                        )
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
                _log.debug("[ARCHIVE] trade log archival: %s", trade_arch)
            except Exception as trade_arch_exc:
                conn.rollback()
                conn.close()
                _log.warning(
                    "[ARCHIVE] trade log archival failed (rolled back monitor archive): %s",
                    trade_arch_exc,
                )
                return {
                    "status": "error",
                    "message": f"Trade archive failed: {trade_arch_exc!s}",
                }

        conn.commit()
        conn.close()

        _log.debug("[ARCHIVE] Monitor %s (ID: %s) archived successfully", monitor_name, monitor_id)

        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "archived",
            "tenant_user_no": _norm_slot(user_number),
        }
        await main_realtime.prefs_ws_send_json_to_slot(message, user_number)
        _log.debug("[ARCHIVE] Monitor list update sent to tenant %s", user_number)

        return {"status": "ok", "message": f"Monitor {monitor_name} archived successfully"}

    except HTTPException:
        raise
    except Exception as e:
        _log.warning("Error archiving monitor: %s", e)
        return {"status": "error", "message": str(e)}


@monitor_command_router.post("/api/monitor/deactivate")
async def deactivate_monitor(request: dict):
    """Turn off a monitor: status = 'inactive' (stops AES/ATS scripts); also set auto_trade FALSE and auto_trade_status 'off' for UI/auto-trading."""
    try:
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")

        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}

        user_number, db_monitor_id = monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}

        slot = _norm_slot(user_number)
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))

        with conn.cursor() as cursor:
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

        _log.debug("[DEACTIVATE] Monitor %s (ID: %s) deactivated successfully", monitor_name, monitor_id)

        try:
            monitor_manager_port = get_port("monitor_manager")
            sync_resp = requests.post(
                f"http://localhost:{monitor_manager_port}/api/sync_monitor_processes",
                json={"source": "main_app_deactivate", "monitor_id": monitor_id},
                timeout=10,
            )
            if not sync_resp.ok:
                _log.warning(
                    "[DEACTIVATE] sync_monitor_processes returned %s: %s",
                    sync_resp.status_code,
                    sync_resp.text,
                )
        except Exception as e:
            _log.warning("[DEACTIVATE] Failed to trigger monitor process sync via HTTP: %s", e)

        try:
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
                    _log.warning(
                        "[DEACTIVATE] generate_unified_supervisor_config failed: %s",
                        r0.stderr or r0.stdout,
                    )
                else:
                    ctl = get_supervisorctl_path()
                    cfg = get_supervisor_config_path()
                    for cmd in ["reread", "update"]:
                        r = subprocess.run([ctl, "-c", cfg, cmd], cwd=proot, capture_output=True, text=True, timeout=10)
                        if r.returncode != 0:
                            _log.warning(
                                "[DEACTIVATE] supervisorctl %s failed: %s",
                                cmd,
                                r.stderr or r.stdout,
                            )
                            break
                    else:
                        _log.debug("[DEACTIVATE] In-process monitor process sync completed")
            else:
                _log.warning("[DEACTIVATE] generate script not found: %s", gen_script)
        except Exception as e:
            _log.warning("[DEACTIVATE] In-process monitor process sync failed: %s", e)

        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "deactivated",
            "tenant_user_no": _norm_slot(user_number),
        }
        await main_realtime.prefs_ws_send_json_to_slot(message, user_number)
        _log.debug("[DEACTIVATE] Monitor list update sent to tenant %s", user_number)

        return {"status": "ok", "message": f"Monitor {monitor_name} deactivated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        _log.warning("Error deactivating monitor: %s", e)
        return {"status": "error", "message": str(e)}


@monitor_command_router.post("/api/monitor/activate")
async def activate_monitor(request: dict):
    """Turn on a monitor: status = 'active' so AES/ATS script iterations are started. Does not change auto_trade/auto_trade_status."""
    try:
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")

        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}

        user_number, db_monitor_id = monitor_slot_and_db_id_from_monitor_id(
            str(monitor_id), request.get("user_id")
        )

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}

        slot = _norm_slot(user_number)
        ml_ident = sql_ident_qualified_table(monitor_list_fqn(slot))

        with conn.cursor() as cursor:
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

        _log.debug("[ACTIVATE] Monitor %s (ID: %s) activated successfully", monitor_name, monitor_id)

        try:
            monitor_manager_port = get_port("monitor_manager")
            sync_resp = requests.post(
                f"http://localhost:{monitor_manager_port}/api/sync_monitor_processes",
                json={"source": "main_app_activate", "monitor_id": monitor_id},
                timeout=10,
            )
            if not sync_resp.ok:
                _log.warning(
                    "[ACTIVATE] sync_monitor_processes returned %s: %s",
                    sync_resp.status_code,
                    sync_resp.text,
                )
        except Exception as e:
            _log.warning("[ACTIVATE] Failed to trigger monitor process sync via HTTP: %s", e)

        try:
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
                    _log.warning(
                        "[ACTIVATE] generate_unified_supervisor_config failed: %s",
                        r0.stderr or r0.stdout,
                    )
                else:
                    ctl = get_supervisorctl_path()
                    cfg = get_supervisor_config_path()
                    for cmd in ["reread", "update"]:
                        r = subprocess.run([ctl, "-c", cfg, cmd], cwd=proot, capture_output=True, text=True, timeout=10)
                        if r.returncode != 0:
                            _log.warning(
                                "[ACTIVATE] supervisorctl %s failed: %s",
                                cmd,
                                r.stderr or r.stdout,
                            )
                            break
                    else:
                        _log.debug("[ACTIVATE] In-process monitor process sync completed")
            else:
                _log.warning("[ACTIVATE] generate script not found: %s", gen_script)
        except Exception as e:
            _log.warning("[ACTIVATE] In-process monitor process sync failed: %s", e)

        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "activated",
            "tenant_user_no": _norm_slot(user_number),
        }
        await main_realtime.prefs_ws_send_json_to_slot(message, user_number)
        _log.debug("[ACTIVATE] Monitor list update sent to tenant %s", user_number)

        return {"status": "ok", "message": f"Monitor {monitor_name} activated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        _log.warning("Error activating monitor: %s", e)
        return {"status": "error", "message": str(e)}


@monitor_command_router.post("/api/monitor/create")
async def create_monitor(request: dict):
    """Create a new monitor - delegates to monitor_manager"""
    try:
        slot = resolved_tenant_user_no_for_app()
        monitor_manager_port = get_port(f"monitor_manager_{slot}")
        response = requests.post(
            f"http://localhost:{monitor_manager_port}/api/monitor/create",
            json=request,
            timeout=10,
        )

        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": f"Monitor manager error: {response.text}"}

    except Exception as e:
        _log.warning("Error forwarding monitor creation: %s", e)
        return {"status": "error", "message": str(e)}
