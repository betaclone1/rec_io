"""Same-origin proxies to read_api for dashboard charts and performance (GET + circuit breaker)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, Query, Request

from backend.core.port_config import get_port
from backend.web.read_api_history_breaker import (
    history_breaker_is_open,
    history_breaker_mark_failure,
    history_breaker_mark_success,
    history_breaker_snapshot,
)
from backend.web.read_api_proxy import read_api_forward_headers, read_api_query_with_session

_LOG = logging.getLogger("main_app")
READ_API_BASE_URL = f"http://127.0.0.1:{get_port('read_api')}"

dashboard_read_proxy_router = APIRouter(tags=["dashboard_read_proxy"])


def _session_params(
    request: Request, period: str, trading_mode: Optional[str], rollup_view: Optional[str]
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"period": period}
    if trading_mode:
        params["trading_mode"] = trading_mode
    if rollup_view:
        params["rollup_view"] = rollup_view
    return read_api_query_with_session(request, params)


async def _proxy_history(
    request: Request,
    *,
    breaker_key: str,
    upstream_path: str,
    period: str,
    trading_mode: Optional[str],
    rollup_view: Optional[str],
    timeout: int = 5,
) -> Any:
    if history_breaker_is_open(breaker_key):
        return {
            "status": "error",
            "message": "read_api history temporarily unavailable (breaker open)",
            "retry_in_sec": history_breaker_snapshot().get(breaker_key, {}).get("retry_in_sec", 0.0),
        }
    try:
        params = _session_params(request, period, trading_mode, rollup_view)
        resp = requests.get(
            f"{READ_API_BASE_URL}{upstream_path}",
            params=params,
            headers=read_api_forward_headers(request),
            timeout=timeout,
        )
        resp.raise_for_status()
        history_breaker_mark_success(breaker_key)
        return resp.json()
    except Exception as e:
        history_breaker_mark_failure(breaker_key)
        _LOG.warning("[read_api proxy] Error getting %s from read_api: %s", upstream_path, e)
        return {"status": "error", "message": f"read_api proxy failed for {upstream_path}"}


async def _proxy_simple_get(
    request: Request,
    upstream_path: str,
    params: Dict[str, Any],
    *,
    timeout: int = 5,
) -> Any:
    try:
        params = read_api_query_with_session(request, params)
        resp = requests.get(
            f"{READ_API_BASE_URL}{upstream_path}",
            params=params,
            headers=read_api_forward_headers(request),
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _LOG.warning("[read_api proxy] Error getting %s from read_api: %s", upstream_path, e)
        return {"status": "error", "message": f"read_api proxy failed for {upstream_path}"}


@dashboard_read_proxy_router.get("/api/portfolio/history")
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
    return await _proxy_history(
        request,
        breaker_key="portfolio_history",
        upstream_path="/api/portfolio/history",
        period=period,
        trading_mode=trading_mode,
        rollup_view=rollup_view,
        timeout=5,
    )


@dashboard_read_proxy_router.get("/api/bankroll/history")
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
    return await _proxy_history(
        request,
        breaker_key="bankroll_history",
        upstream_path="/api/bankroll/history",
        period=period,
        trading_mode=trading_mode,
        rollup_view=rollup_view,
        timeout=5,
    )


@dashboard_read_proxy_router.get("/api/pnl/history")
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
    return await _proxy_history(
        request,
        breaker_key="pnl_history",
        upstream_path="/api/pnl/history",
        period=period,
        trading_mode=trading_mode,
        rollup_view=rollup_view,
        timeout=5,
    )


@dashboard_read_proxy_router.get("/api/dashboard/history-bundle")
async def get_dashboard_history_bundle(
    request: Request,
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — same as UI toggle; session selects tenant"
    ),
    rollup_view: Optional[str] = Query(
        None, description="td|prev — calendar vs rolling (dashboard rollup toggle)"
    ),
):
    return await _proxy_history(
        request,
        breaker_key="dashboard_history_bundle",
        upstream_path="/api/dashboard/history-bundle",
        period=period,
        trading_mode=trading_mode,
        rollup_view=rollup_view,
        timeout=6,
    )


@dashboard_read_proxy_router.get("/api/performance/realized")
async def get_performance_realized(
    request: Request,
    trading_mode: Optional[str] = Query(
        None, description="paper|live — same as UI toggle; session selects tenant"
    ),
):
    params: Dict[str, Any] = {}
    if trading_mode:
        params["trading_mode"] = trading_mode
    return await _proxy_simple_get(request, "/api/performance/realized", params)


@dashboard_read_proxy_router.get("/api/performance/rollups")
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
    params: Dict[str, Any] = {}
    if trading_mode:
        params["trading_mode"] = trading_mode
    if rollup_view:
        params["rollup_view"] = rollup_view
    return await _proxy_simple_get(request, "/api/performance/rollups", params)


@dashboard_read_proxy_router.get("/api/performance/monitor-tiles")
async def get_performance_monitor_tiles_proxy(
    request: Request,
    period: str = Query(
        "all",
        description="1d | 1w | 1m | 1y | all — dashboard chart window",
    ),
    rollup_view: str = Query("td", description="td | prev"),
):
    params: Dict[str, Any] = {"period": period, "rollup_view": rollup_view}
    return await _proxy_simple_get(request, "/api/performance/monitor-tiles", params)
