"""Trade manager forwards, ATS active-trades proxy, per-monitor active_trades SQL, failure detector, AES indicator."""

import logging
from typing import Optional

import requests
from fastapi import APIRouter

from backend.core.port_config import (
    get_auto_entry_supervisor_http_port_for_monitor_suffix,
    get_port,
    unified_active_trade_supervisor_service_name,
)
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
    """Proxy per-monitor active trades to the unified ATS (Redis hot path)."""
    try:
        monitor_key = monitor_name[4:] if monitor_name.startswith("mon_") else monitor_name
        response = requests.get(
            f"http://localhost:{_ACTIVE_TRADE_SUPERVISOR_PORT}/api/active_trades/{monitor_key}",
            timeout=5,
        )
        if response.status_code == 200:
            return response.json()
        return (
            {"error": f"Active trade supervisor returned status {response.status_code}"},
            response.status_code,
        )
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to connect to active trade supervisor: {str(e)}"}, 503
    except Exception as e:
        return {"error": f"Error loading active trades for monitor {monitor_name}: {str(e)}"}


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
