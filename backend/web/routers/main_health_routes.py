"""Health, port manifest, and aggregate system-health endpoints for main_app."""

from __future__ import annotations

import logging
from typing import Any, Dict

import requests
from fastapi import APIRouter, Request
from starlette.responses import Response

from backend.core.port_config import (
    get_port,
    get_port_info,
    unified_active_trade_supervisor_service_name,
    user_scoped_service_name,
)
from backend.core.time_eastern import now_est
from backend.web.read_api_history_breaker import history_breaker_snapshot

_LOG = logging.getLogger("main_app")
READ_API_BASE_URL = f"http://127.0.0.1:{get_port('read_api')}"

main_health_router = APIRouter(tags=["health"])


@main_health_router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "main_app",
        "port": get_port("main_app"),
        "timestamp": now_est().isoformat(),
        "port_system": "centralized",
    }


@main_health_router.get("/health/read-path")
async def read_path_health_check():
    """Read-path health for dashboard-critical data routes."""
    test_url = f"{READ_API_BASE_URL}/api/pnl/history"
    params = {"period": "1d"}
    try:
        resp = requests.get(test_url, params=params, timeout=3)
        ok = resp.ok or resp.status_code in (401, 403)
        return {
            "status": "healthy" if ok else "degraded",
            "service": "main_app",
            "read_api_status_code": resp.status_code,
            "auth_required": resp.status_code in (401, 403),
            "breaker": history_breaker_snapshot(),
            "timestamp": now_est().isoformat(),
        }
    except Exception as e:
        return {
            "status": "degraded",
            "service": "main_app",
            "error": str(e),
            "breaker": history_breaker_snapshot(),
            "timestamp": now_est().isoformat(),
        }


@main_health_router.get("/api/system/release_version")
async def get_release_version_main(request: Request) -> Response:
    from backend.web.read_api_proxy import as_starlette_response, proxy_read_api_raw

    r = await proxy_read_api_raw(
        request,
        "GET",
        "/api/system/release_version",
        READ_API_BASE_URL,
        _LOG,
        None,
    )
    return await as_starlette_response(r)


@main_health_router.get("/api/ports")
async def get_ports(request: Request) -> Dict[str, Any]:
    port_info = get_port_info()
    protocol = request.headers.get("x-forwarded-proto", "http")
    if protocol == "https":
        host = port_info["host"]
        ports = port_info["ports"]
        port_info["service_urls"] = {name: f"https://{host}:{port}" for name, port in ports.items()}
    return port_info


@main_health_router.get("/api/system-health")
async def get_system_health():
    from backend.system_monitor import SystemMonitor

    try:
        monitor = SystemMonitor()
        health_report = monitor.generate_health_report()
        overall_status = "healthy"
        issues = []
        if health_report.get("supervisor_status", {}).get("status") != "running":
            overall_status = "offline"
            issues.append("Supervisor not running")
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
        db_health = health_report.get("database_health", {})
        if db_health.get("status") != "healthy":
            overall_status = "degraded"
            issues.append("Database issues detected")
        return {
            "status": overall_status,
            "issues": issues,
            "timestamp": now_est().isoformat(),
            "health_report": health_report,
        }
    except Exception as e:
        return {
            "status": "offline",
            "issues": [f"System monitor error: {str(e)}"],
            "timestamp": now_est().isoformat(),
            "error": str(e),
        }
