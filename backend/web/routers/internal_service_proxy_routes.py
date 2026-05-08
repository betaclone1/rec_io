"""Trade manager forwards, ATS active-trades proxy, per-monitor active_trades SQL, failure detector, AES indicator."""

import logging
from typing import Optional

import requests
from fastapi import APIRouter

from backend.core.config.database import get_postgresql_connection
from backend.core.port_config import (
    get_auto_entry_supervisor_http_port_for_monitor_suffix,
    get_port,
    monitor_suffix_uses_unified_15m_pool,
    monitor_suffix_uses_unified_hourly_pool,
    unified_active_trade_supervisor_service_name,
)
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.core.time_eastern import now_est
from backend.util.paths import get_host

_log = logging.getLogger("main_app")

_ACTIVE_TRADE_SUPERVISOR_PORT = get_port(unified_active_trade_supervisor_service_name())

internal_service_proxy_router = APIRouter()


@internal_service_proxy_router.get("/trades/{trade_id}")
async def get_trade(trade_id: int):
    """Forward trade GET request to trade_manager."""
    try:
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades/{trade_id}"

        _log.debug("[MAIN] Forwarding trade GET request to trade_manager at %s", trade_manager_url)

        response = requests.get(
            trade_manager_url,
            timeout=10,
        )

        if response.status_code == 200:
            _log.debug("[MAIN] Trade GET request forwarded successfully to trade_manager")
            return response.json()
        else:
            _log.warning("[MAIN] Trade GET request forwarding failed: %s", response.status_code)
            return {"error": f"Trade manager returned status {response.status_code}"}

    except Exception as e:
        _log.warning("[MAIN] Error forwarding trade GET request: %s", e)
        return {"error": str(e)}


@internal_service_proxy_router.post("/trades")
async def create_trade(trade_data: dict):
    """Forward trade ticket to trade_manager."""
    try:
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades"

        _log.debug("[MAIN] Forwarding trade ticket to trade_manager at %s", trade_manager_url)

        response = requests.post(
            trade_manager_url,
            json=trade_data,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )

        if response.status_code == 201:
            _log.debug("[MAIN] Trade ticket forwarded successfully to trade_manager")
            return response.json()
        else:
            _log.warning("[MAIN] Trade ticket forwarding failed: %s", response.status_code)
            return {"error": f"Trade manager returned status {response.status_code}"}

    except Exception as e:
        _log.warning("[MAIN] Error forwarding trade ticket: %s", e)
        return {"error": str(e)}


@internal_service_proxy_router.get("/api/active_trades")
async def proxy_active_trades():
    """Proxy route to forward active trades requests to the active trade supervisor"""
    try:
        response = requests.get(
            f"http://localhost:{_ACTIVE_TRADE_SUPERVISOR_PORT}/api/active_trades", timeout=5
        )
        if response.status_code == 200:
            return response.json()
        else:
            return (
                {"error": f"Active trade supervisor returned status {response.status_code}"},
                response.status_code,
            )
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to connect to active trade supervisor: {str(e)}"}, 503


@internal_service_proxy_router.get("/api/active_trades/{monitor_name}")
async def get_active_trades_for_monitor(monitor_name: str):
    """Get active trades data for a specific monitor from PostgreSQL"""
    try:
        table_suffix = monitor_name
        if monitor_name.startswith("mon_"):
            table_suffix = monitor_name[4:]

        use_15m_pool = monitor_suffix_uses_unified_15m_pool(table_suffix)
        use_hourly_pool = monitor_suffix_uses_unified_hourly_pool(table_suffix)
        pool_user, pool_mid = None, None
        if use_15m_pool or use_hourly_pool:
            parts = table_suffix.split("_", 1)
            if len(parts) == 2:
                pool_user, pool_mid = parts[0], parts[1]

        conn = get_postgresql_connection()
        if not conn:
            return {"error": "Database unavailable"}
        with conn.cursor() as cursor:
            if use_15m_pool and pool_user and pool_mid:
                cursor.execute(
                    f"""
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
                """,
                    (pool_mid,),
                )
            elif use_hourly_pool and pool_user and pool_mid:
                cursor.execute(
                    f"""
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
                """,
                    (pool_mid,),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT 
                        trade_id, ticket_id, date, time, strike, side, buy_price, position,
                        contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                        momentum, prob, fees, diff, status, current_symbol_price,
                        current_probability, buffer_from_entry, time_since_entry,
                        current_close_price, current_pnl, last_updated, created_at
                    FROM users.active_trades_{table_suffix}
                    WHERE status IN ('active', 'pending', 'closing')
                    ORDER BY created_at DESC
                """
                )

            trades_data = cursor.fetchall()
            conn.close()

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
                    "created_at": row[26].isoformat() if row[26] else None,
                }
                active_trades.append(trade)

            return {
                "status": "success",
                "timestamp": now_est().isoformat(),
                "active_trades": active_trades,
                "count": len(active_trades),
                "monitor_identifier": monitor_name,
            }

    except Exception as e:
        return {
            "error": f"Error loading active trades for monitor {monitor_name} from PostgreSQL: {str(e)}"
        }


@internal_service_proxy_router.get("/api/failure_detector_status")
async def get_failure_detector_status():
    """Get the current status of the cascading failure detector."""
    try:
        from backend.cascading_failure_detector import CascadingFailureDetector

        detector = CascadingFailureDetector()
        return detector.generate_status_report()
    except Exception as e:
        return {"error": str(e)}


@internal_service_proxy_router.get("/api/auto_entry_indicator")
async def get_auto_entry_indicator(
    monitor_id: Optional[str] = None,
    user_number: Optional[str] = None,
):
    """Proxy endpoint to get auto entry indicator state from auto_entry_supervisor.

    For unified 15m AES pass monitor_id; user_number defaults to the logged-in tenant.
    """
    try:
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
        url = f"http://localhost:{port}/api/auto_entry_indicator"
        response = requests.get(url, params=q or None, timeout=2)
        if response.ok:
            return response.json()
        else:
            return {"error": f"Auto entry supervisor returned {response.status_code}"}
    except Exception as e:
        return {"error": f"Error getting auto entry indicator: {str(e)}"}
