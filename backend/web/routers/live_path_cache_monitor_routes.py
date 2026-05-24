"""Unauthenticated local Live Path Cache Monitor (HTTP catalog + snapshot)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.core.live_path_cache_monitor import (
    build_snapshot,
    parse_spec_from_query,
    source_catalog,
    validate_spec,
)
from backend.trading_mode import _norm_slot

live_path_cache_monitor_router = APIRouter()


@live_path_cache_monitor_router.get("/debug/live-path-cache/catalog")
async def live_path_cache_catalog() -> JSONResponse:
    return JSONResponse({"sources": source_catalog()})


@live_path_cache_monitor_router.get("/debug/live-path-cache/snapshot")
async def live_path_cache_snapshot(
    source: str = Query("active_trades"),
    user_no: str = Query("0001"),
    exchange: str = Query("kalshi"),
    market: str = Query("15m"),
    symbol: str = Query("BTC"),
    redis_key: str = Query(""),
    ticker: str = Query(""),
) -> JSONResponse:
    spec = parse_spec_from_query(
        source=source,
        user_no=user_no,
        exchange=exchange,
        market=market,
        symbol=symbol,
        redis_key=redis_key,
        ticker=ticker,
    )
    err = validate_spec(spec)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return JSONResponse(build_snapshot(spec))


@live_path_cache_monitor_router.get("/debug/active-trades-hot-path/{user_no}")
async def debug_active_trades_redis_pool_legacy(user_no: str) -> JSONResponse:
    """Backward-compatible alias for active_trades snapshot."""
    slot = str(user_no).strip()
    if not slot.isdigit() or len(slot) > 4:
        raise HTTPException(status_code=400, detail="user_no must be a numeric tenant slot (e.g. 0001)")
    spec = parse_spec_from_query(source="active_trades", user_no=_norm_slot(slot))
    return JSONResponse(build_snapshot(spec))
