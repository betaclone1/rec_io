"""Thin same-origin HTTP proxies to read_api (session cookies on main_app)."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, Query, Request, Response

from backend.core.port_config import get_port
from backend.web.read_api_proxy import as_starlette_response, proxy_read_api_raw

_LOG = logging.getLogger("main_app")
_READ_API = f"http://127.0.0.1:{get_port('read_api')}"

read_api_passthrough_router = APIRouter(tags=["read_api_proxy"])


async def _get(request: Request, path: str) -> Response:
    r = await proxy_read_api_raw(request, "GET", path, _READ_API, _LOG, None)
    return await as_starlette_response(r)


async def _post_body(request: Request, path: str, body: bytes) -> Response:
    r = await proxy_read_api_raw(request, "POST", path, _READ_API, _LOG, body)
    return await as_starlette_response(r)


@read_api_passthrough_router.get("/core")
async def get_core_data(request: Request):
    """Proxy to read_api: core trading data payload."""
    q = request.url.query
    path = f"/core?{q}" if q else "/core"
    return await _get(request, path)


@read_api_passthrough_router.get("/trades")
async def get_trades_proxy(request: Request):
    """Proxy to read_api: tenant trade list (paginated or full)."""
    q = request.url.query
    path = f"/trades?{q}" if q else "/trades"
    return await _get(request, path)


@read_api_passthrough_router.post("/api/trades/history/insights")
async def trade_history_insights_proxy(request: Request):
    """Proxy to read_api: summary + analysis over full filtered trade set."""
    body = await request.body()
    return await _post_body(request, "/api/trades/history/insights", body)


@read_api_passthrough_router.get("/api/live_symbol_spot_bootstrap")
async def live_symbol_spot_bootstrap_proxy(request: Request):
    """Proxy to read_api: spot bootstrap for trade monitor."""
    q = request.url.query
    path = (
        f"/api/live_symbol_spot_bootstrap?{q}"
        if q
        else "/api/live_symbol_spot_bootstrap"
    )
    return await _get(request, path)


@read_api_passthrough_router.get("/api/trade-monitor/orderbook")
async def trade_monitor_orderbook_proxy(request: Request):
    q = request.url.query
    path = f"/api/trade-monitor/orderbook?{q}" if q else "/api/trade-monitor/orderbook"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/trade-monitor/orderbook/liquidity")
async def trade_monitor_orderbook_liquidity_proxy(request: Request):
    q = request.url.query
    path = (
        f"/api/trade-monitor/orderbook/liquidity?{q}"
        if q
        else "/api/trade-monitor/orderbook/liquidity"
    )
    return await _get(request, path)


@read_api_passthrough_router.get("/btc_price_changes")
async def get_btc_changes(request: Request):
    return await _get(request, "/btc_price_changes")


@read_api_passthrough_router.get("/eth_price_changes")
async def get_eth_changes(request: Request):
    return await _get(request, "/eth_price_changes")


@read_api_passthrough_router.get("/api/account/balance")
async def get_account_balance(
    request: Request,
    response: Response,
    mode: str = "prod",
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — must match UI toggle; same table selection as portfolio chart",
    ),
):
    _ = response
    path = f"/api/account/balance?mode={quote_plus(str(mode))}"
    if trading_mode:
        path += f"&trading_mode={quote_plus(str(trading_mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/subaccounts")
async def get_subaccounts(
    request: Request, response: Response, trading_mode: Optional[str] = None
):
    _ = response
    path = "/api/subaccounts"
    if trading_mode:
        path += f"?trading_mode={quote_plus(str(trading_mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/account/balance/history")
async def get_account_balance_history(
    request: Request,
    mode: str = "prod",
    limit: int = 1000,
    trading_mode: Optional[str] = None,
):
    path = (
        f"/api/account/balance/history?mode={quote_plus(str(mode))}"
        f"&limit={int(limit)}"
    )
    if trading_mode:
        path += f"&trading_mode={quote_plus(str(trading_mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/db/fills")
async def get_fills(request: Request, response: Response, trading_mode: Optional[str] = None):
    _ = response
    path = "/api/db/fills"
    if trading_mode:
        path += f"?trading_mode={quote_plus(str(trading_mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/db/positions")
async def get_positions(request: Request, response: Response, trading_mode: Optional[str] = None):
    _ = response
    path = "/api/db/positions"
    if trading_mode:
        path += f"?trading_mode={quote_plus(str(trading_mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/db/settlements")
async def get_settlements(request: Request, response: Response, trading_mode: Optional[str] = None):
    _ = response
    path = "/api/db/settlements"
    if trading_mode:
        path += f"?trading_mode={quote_plus(str(trading_mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/db/transfers")
async def get_transfers(
    request: Request,
    response: Response,
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — match UI toggle (same table selection as subaccounts)",
    ),
):
    _ = response
    path = "/api/db/transfers"
    if trading_mode:
        path += f"?trading_mode={quote_plus(str(trading_mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/db/system_health")
async def get_system_health_from_db(request: Request) -> Response:
    return await _get(request, "/api/db/system_health")


@read_api_passthrough_router.get("/api/momentum")
async def get_current_momentum(request: Request):
    q = request.url.query
    path = f"/api/momentum?{q}" if q else "/api/momentum"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/btc_price")
async def get_btc_price(request: Request):
    return await _get(request, "/api/btc_price")


@read_api_passthrough_router.get("/api/eth_price")
async def get_eth_price(request: Request):
    return await _get(request, "/api/eth_price")


@read_api_passthrough_router.get("/api/live_symbol_status_snapshot")
async def get_live_symbol_status_snapshot(request: Request):
    return await _get(request, "/api/live_symbol_status_snapshot")


@read_api_passthrough_router.get("/api/postgresql/strike_table/{symbol}")
async def get_postgresql_strike_table(symbol: str, request: Request):
    q = request.url.query
    path = f"/api/postgresql/strike_table/{quote_plus(symbol)}"
    if q:
        path += f"?{q}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/unified_ttc/{symbol}")
async def get_unified_ttc(symbol: str, request: Request):
    q = request.url.query
    path = f"/api/unified_ttc/{quote_plus(symbol)}"
    if q:
        path += f"?{q}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/dashboard/preferences")
async def get_dashboard_preferences(request: Request, mode: str = "prod"):
    path = f"/api/dashboard/preferences?mode={quote_plus(str(mode))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/monitors")
async def get_monitors(request: Request, user_id: Optional[str] = None):
    path = "/api/monitors"
    if user_id:
        path += f"?user_id={quote_plus(str(user_id))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/monitors/health")
async def get_monitors_health(request: Request, user_id: Optional[str] = None):
    path = "/api/monitors/health"
    if user_id:
        path += f"?user_id={quote_plus(str(user_id))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/symbols")
async def get_symbols(request: Request):
    return await _get(request, "/api/symbols")


@read_api_passthrough_router.get("/api/monitor/{monitor_id}")
async def get_monitor_details(
    request: Request, monitor_id: int, user_id: Optional[str] = None
):
    path = f"/api/monitor/{int(monitor_id)}"
    if user_id:
        path += f"?user_id={quote_plus(str(user_id))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/monitors/names")
async def get_monitor_names(request: Request, user_id: Optional[str] = None):
    path = "/api/monitors/names"
    if user_id:
        path += f"?user_id={quote_plus(str(user_id))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/monitors/allocation")
async def get_monitors_allocation(
    request: Request,
    user_id: Optional[str] = None,
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — which account_balance table backs dollar amounts (matches UI toggle)",
    ),
):
    parts = []
    if user_id:
        parts.append(f"user_id={quote_plus(str(user_id))}")
    if trading_mode:
        parts.append(f"trading_mode={quote_plus(str(trading_mode))}")
    path = "/api/monitors/allocation"
    if parts:
        path += "?" + "&".join(parts)
    return await _get(request, path)


@read_api_passthrough_router.get("/api/strategies")
async def get_strategies(request: Request, user_id: Optional[str] = None):
    path = "/api/strategies"
    if user_id:
        path += f"?user_id={quote_plus(str(user_id))}"
    return await _get(request, path)


@read_api_passthrough_router.get("/api/earliest_trade_date")
async def get_earliest_trade_date(request: Request):
    return await _get(request, "/api/earliest_trade_date")
