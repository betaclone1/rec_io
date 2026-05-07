"""
read_api: dedicated read/aggregate service for frontend data.

Role: host read/aggregate endpoints (dashboard, history, stats) and the auth/user plane
(login, session, profile, throttled ``POST /api/user/activity`` for ``last_login``).
Also **GET /trades** (tenant trade log: master + archive union, optional date filter and keyset
pagination). main_app keeps a thin same-origin proxy to this route for cookies/session.
**Trade history UI preferences** (``GET/POST /api/get|set_trade_history_preferences``): same handlers as
main_app (PostgreSQL + Redis ``trade_history_preferences_updated``). Browsers should call **main** same-origin;
this copy exists for direct :3050 access. No WebSocket on this process.
Aside from auth/session, that activity touch, and trade-history prefs, avoids writes.
Also performs a single Redis **GET** of the cached release string
(`redis_key_system_release_version`) for the System UI. **GET /api/orderbook** reads the Kalshi
orderbook UI snapshot from Redis (``testing:orderbook_ui:current``). **GET /api/trade-monitor/orderbook**
returns the trade-monitor orderbook JSON from ``live_data`` (``market_kalshi_*`` + per-ticker
``orderbook_kalshi_*``), same shape as ``orderbook-redis-ui.js``. Trade monitor NEW sets
``__ORDERBOOK_API__`` to read_api (default port 3050) for that route. See docs/REDIS_ARCHITECTURE.md.
**GET /api/live_symbol_spot_bootstrap** returns the same JSON as WebSocket ``live_symbol_spot``
(``redis_switchboard.build_live_symbol_spot_payload``) so the NEW monitor can hydrate the price
panel without adding routes to main_app.
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.core.trades_history_insights import run_trade_history_insights
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core.config.database import get_postgresql_connection, get_system_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.core.trade_history_preferences_handlers import (
    trade_history_preferences_get,
    trade_history_preferences_post,
)
from backend.core.dashboard_portfolio_queries import (
    bankroll_history_payload,
    performance_realized_payload,
    pnl_history_payload,
    portfolio_history_payload,
)
from backend.core.performance_rollups import (
    performance_monitor_tiles_read_payload,
    performance_rollups_read_payload,
)
from backend.core.trades_list_query import TRADES_PAGE_SIZE_MAX, execute_trades_list_query
from backend.util.trade_log_archivist import (
    canonical_monitor_key,
    fetch_master_trades_column_names,
    union_trades_with_archives_select,
)
from backend.web.auth_routes import auth_router, user_router
from backend.web.auth_self_registration import self_reg_router
from backend.web.tenant_asgi import WebTenantMiddleware

app = FastAPI(title="read_api")

app.add_middleware(WebTenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router, prefix="/api/auth")
app.include_router(self_reg_router, prefix="/api/auth")
app.include_router(user_router, prefix="/api/user")


class TradeHistoryInsightsBody(BaseModel):
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    include_test_trades: bool = False
    show_win: bool = True
    show_loss: bool = True
    show_live: bool = True
    show_paper: bool = False
    symbols: List[str] = Field(default_factory=list)
    strategies: List[str] = Field(default_factory=list)
    monitors: List[str] = Field(default_factory=list)
    days_of_week: Optional[List[int]] = None
    analysis_interval: str = "daily"


@app.get("/api/get_trade_history_preferences")
async def get_trade_history_preferences() -> Dict[str, Any]:
    """Trade history filter UI state (per-tenant PostgreSQL). Prefer main_app same-origin route in browsers."""
    return trade_history_preferences_get()


@app.post("/api/set_trade_history_preferences")
async def set_trade_history_preferences(request: Request) -> Dict[str, Any]:
    """Merge JSON body into saved trade history preferences; notify Redis preferences channel."""
    return await trade_history_preferences_post(request)


@app.post("/api/trades/history/insights")
async def post_trade_history_insights(body: TradeHistoryInsightsBody) -> Dict[str, Any]:
    """Summary + period analysis over the full filtered trade set (not paginated)."""
    slot = resolved_tenant_user_no_for_app()
    conn = get_postgresql_connection()
    if not conn:
        raise HTTPException(
            status_code=503,
            detail="Trade history insights temporarily unavailable (database busy or error)",
        )
    try:
        with conn.cursor() as cursor:
            return run_trade_history_insights(
                cursor, user_slot=slot, body=body.model_dump()
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Trade history insights temporarily unavailable (database busy or error)",
        )
    finally:
        conn.close()


@app.get("/trades")
async def get_trades(
    status: Optional[str] = None,
    min_date: Optional[str] = Query(
        None,
        description="Inclusive lower bound on trades.date (YYYY-MM-DD text in DB).",
    ),
    max_date: Optional[str] = Query(
        None,
        description="Inclusive upper bound on trades.date (YYYY-MM-DD text in DB).",
    ),
    page_size: Optional[int] = Query(
        None,
        ge=1,
        le=TRADES_PAGE_SIZE_MAX,
        description=f"When set, response is trades/has_more/next_before_id (keyset page). Max {TRADES_PAGE_SIZE_MAX}.",
    ),
    before_id: Optional[int] = Query(
        None,
        ge=1,
        description="Keyset cursor for ORDER BY id DESC: rows with id < before_id. Requires page_size.",
    ),
):
    """Tenant trade log from PostgreSQL (same contract as main_app proxy)."""
    try:
        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            raise HTTPException(
                status_code=503,
                detail="Trade list temporarily unavailable (database busy or error)",
            )
        try:
            with conn.cursor() as cursor:
                return execute_trades_list_query(
                    cursor,
                    slot=slot,
                    status=status,
                    min_date=min_date,
                    max_date=max_date,
                    page_size=page_size,
                    before_id=before_id,
                )
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Trade list temporarily unavailable (database busy or error)",
        )


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "healthy",
            "service": "read_api",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


@app.get("/api/system/release_version")
async def get_release_version() -> Dict[str, Any]:
    """Latest release from Redis (populated by system_monitor from ``system.version_control``)."""
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


_ORDERBOOK_UI_REDIS_KEY = "testing:orderbook_ui:current"


@app.get("/api/orderbook")
async def get_orderbook_ui_snapshot() -> JSONResponse:
    """
    Kalshi orderbook UI JSON from Redis (same key and shape as ``orderbook_ui_redis_server``).
    Browsers on main_app (:3000) call this on read_api (:3050) so the trade monitor stays Redis-backed
    without adding routes to main_app.
    """
    from backend.core.trading_redis_comms import redis_client_optional

    r = redis_client_optional()
    if r is None:
        return JSONResponse({"error": "redis_unavailable"})
    try:
        raw = r.get(_ORDERBOOK_UI_REDIS_KEY)
    except Exception:
        return JSONResponse({"error": "redis_read_failed"})
    if not raw:
        return JSONResponse({"error": "no_data"})
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return JSONResponse(payload)
    except Exception:
        pass
    return JSONResponse({"error": "invalid_payload"})


@app.get("/api/trade-monitor/orderbook")
async def get_trade_monitor_orderbook(
    symbol: str = Query("BTC", description="Kalshi symbol, e.g. BTC"),
    market: str = Query("15m", description="15m or hourly"),
    market_ticker: Optional[str] = Query(
        None,
        description="Optional Kalshi market_ticker; default is latest row for symbol+market",
    ),
) -> JSONResponse:
    """DB-backed orderbook for trade monitor NEW (``live_data`` sidecar tables)."""
    from backend.core.trade_monitor_live_orderbook_payload import build_trade_monitor_orderbook_payload

    conn = get_system_postgresql_connection()
    if not conn:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    try:
        with conn.cursor() as cursor:
            payload = build_trade_monitor_orderbook_payload(
                cursor,
                market_ticker=market_ticker,
                symbol=symbol,
                market=market,
            )
        return JSONResponse(payload)
    except Exception:
        return JSONResponse({"error": "orderbook_payload_failed"}, status_code=503)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get("/api/trade-monitor/orderbook/liquidity")
async def get_trade_monitor_orderbook_liquidity(
    market_tickers: str = Query(
        "",
        description="Comma-separated Kalshi market_ticker values",
    ),
) -> JSONResponse:
    """Batch liquidity probe for trade-monitor strike rows."""
    from backend.core.trade_monitor_live_orderbook_payload import (
        build_trade_monitor_orderbook_liquidity_map,
    )

    tickers = []
    for tok in str(market_tickers or "").split(","):
        mt = tok.strip()
        if mt:
            tickers.append(mt)
    if not tickers:
        return JSONResponse({"liquidity_by_ticker": {}})
    # Keep request bounded to avoid accidental oversized probes.
    tickers = tickers[:200]

    conn = get_system_postgresql_connection()
    if not conn:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    try:
        with conn.cursor() as cursor:
            payload = build_trade_monitor_orderbook_liquidity_map(
                cursor,
                market_tickers=tickers,
            )
        return JSONResponse({"liquidity_by_ticker": payload})
    except Exception:
        return JSONResponse({"error": "orderbook_liquidity_failed"}, status_code=503)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get("/api/live_symbol_spot_bootstrap")
async def live_symbol_spot_bootstrap() -> JSONResponse:
    """
    Same payload shape as WebSocket ``live_symbol_spot`` (``redis_switchboard``).
    Trade Monitor NEW calls read_api (with ``__ORDERBOOK_API__``); live updates stay on ``/ws/db_changes`` on main.
    """
    try:
        from backend.redis_switchboard import build_live_symbol_spot_payload

        payload = await asyncio.to_thread(build_live_symbol_spot_payload)
        if not payload:
            return JSONResponse(
                {
                    "type": "live_symbol_spot",
                    "timestamp": None,
                    "spot_by_symbol": {},
                    "changes_by_symbol": {},
                    "rows": [],
                }
            )
        return JSONResponse(payload)
    except Exception:
        return JSONResponse(
            {
                "type": "live_symbol_spot",
                "timestamp": None,
                "spot_by_symbol": {},
                "changes_by_symbol": {},
                "rows": [],
            }
        )


@app.get("/api/portfolio/history")
async def get_portfolio_history(
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
    rollup_view: Optional[str] = Query(
        None,
        description="td|prev — calendar vs rolling window (matches performance rollups / dashboard toggle)",
    ),
) -> Dict[str, Any]:
    """Same implementation as main_app (shared module)."""
    return portfolio_history_payload(
        period=period, trading_mode=trading_mode, rollup_view=rollup_view
    )


@app.get("/api/bankroll/history")
async def get_bankroll_history(
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
    rollup_view: Optional[str] = Query(
        None,
        description="td|prev — calendar vs rolling window (matches performance rollups / dashboard toggle)",
    ),
) -> Dict[str, Any]:
    return bankroll_history_payload(
        period=period, trading_mode=trading_mode, rollup_view=rollup_view
    )


@app.get("/api/pnl/history")
async def get_pnl_history(
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
    rollup_view: Optional[str] = Query(
        None,
        description="td|prev — calendar vs rolling window (matches performance rollups / dashboard toggle)",
    ),
) -> Dict[str, Any]:
    return pnl_history_payload(period=period, trading_mode=trading_mode, rollup_view=rollup_view)


@app.get("/api/dashboard/history-bundle")
async def get_dashboard_history_bundle(
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
    rollup_view: Optional[str] = Query(
        None,
        description="td|prev — calendar vs rolling window (matches performance rollups / dashboard toggle)",
    ),
) -> Dict[str, Any]:
    """Single payload for dashboard history panels to reduce read amplification."""
    portfolio = portfolio_history_payload(
        period=period, trading_mode=trading_mode, rollup_view=rollup_view
    )
    bankroll = bankroll_history_payload(
        period=period, trading_mode=trading_mode, rollup_view=rollup_view
    )
    pnl = pnl_history_payload(period=period, trading_mode=trading_mode, rollup_view=rollup_view)
    return {"status": "ok", "period": period, "portfolio": portfolio, "bankroll": bankroll, "pnl": pnl}


@app.get("/api/performance/realized")
async def get_performance_realized(
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
) -> Dict[str, Any]:
    return performance_realized_payload(trading_mode=trading_mode)


@app.get("/api/performance/rollups")
async def get_performance_rollups(
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
    rollup_view: str = Query(
        "td",
        description="td = calendar-to-date (trade date); prev = rolling windows from closed_at",
    ),
) -> Dict[str, Any]:
    return performance_rollups_read_payload(trading_mode=trading_mode, rollup_view=rollup_view)


@app.get("/api/performance/monitor-tiles")
async def get_performance_monitor_tiles(
    period: str = Query(
        "all",
        description="1d | 1w | 1m | 1y | all — dashboard portfolio chart window",
    ),
    rollup_view: str = Query(
        "td",
        description="td = calendar (trade date); prev = rolling (closed_at)",
    ),
) -> Dict[str, Any]:
    return performance_monitor_tiles_read_payload(period=period, rollup_view=rollup_view)


def _monitor_auto_stop_accuracy_bucket(
    cursor: Any, union_sql: str, monitor_key: str, close_method: str, days: int
) -> Dict[str, Any]:
    """
    Losing closed trades for this monitor and ``close_method``, closed in the last ``days`` days
    (rolling window from ``closed_at`` / ``created_at`` fallback).

    Percentage = among those losses, share with ``win_loss_confirmed`` IS TRUE (e.g. 3/4 → 75%).

    Uses the same closed_at-as-text fallback as /api/pnl/history and /api/performance/realized.
    """
    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE t.win_loss_confirmed IS TRUE),
            COUNT(*)
        FROM ("""
        + union_sql
        + """) AS t
        WHERE t.status = 'closed'
          AND t.win_loss = 'L'
          AND LOWER(TRIM(COALESCE(t.close_method, ''))) = %s
          AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
          AND (CASE
            WHEN t.closed_at IS NOT NULL AND t.closed_at ~ '^\\d{4}-\\d{2}-\\d{2}'
            THEN t.closed_at::timestamptz
            ELSE t.created_at
          END) >= (CURRENT_TIMESTAMP - (%s::integer * INTERVAL '1 day'))
        """,
        (close_method.lower(), monitor_key, days),
    )
    row = cursor.fetchone()
    confirmed = int(row[0] or 0)
    total = int(row[1] or 0)
    pct = None
    if total > 0:
        pct = round(100.0 * confirmed / total, 1)
    return {"confirmed": confirmed, "total": total, "accuracy_pct": pct}


@app.get("/api/monitor_auto_stop_accuracy")
async def get_monitor_auto_stop_accuracy(monitor_id: str | None = None) -> Dict[str, Any]:
    """
    Per monitor, per auto-stop ``close_method`` (``auto_probability`` vs ``auto_stop_loss_floor``):
    among **losing** closed trades in rolling 7d / 30d, percentage with ``win_loss_confirmed`` TRUE.

    Includes tenant trades table and archive tables.
    """
    if not monitor_id:
        return {"status": "error", "message": "monitor_id required"}
    mid = str(monitor_id).strip()
    if not mid.isdigit():
        return {"status": "error", "message": "monitor_id must be numeric"}

    try:
        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}
        monitor_key = canonical_monitor_key(slot, mid)
        with conn.cursor() as cursor:
            if not fetch_master_trades_column_names(cursor, slot):
                conn.close()
                return {
                    "status": "ok",
                    "monitor_key": monitor_key,
                    "probability_stop": {
                        "30d": {"confirmed": 0, "total": 0, "accuracy_pct": None},
                        "7d": {"confirmed": 0, "total": 0, "accuracy_pct": None},
                    },
                    "stop_loss_floor": {
                        "30d": {"confirmed": 0, "total": 0, "accuracy_pct": None},
                        "7d": {"confirmed": 0, "total": 0, "accuracy_pct": None},
                    },
                }
            union_sql, _ = union_trades_with_archives_select(cursor, slot)
            prob_30 = _monitor_auto_stop_accuracy_bucket(
                cursor, union_sql, monitor_key, "auto_probability", 30
            )
            prob_7 = _monitor_auto_stop_accuracy_bucket(
                cursor, union_sql, monitor_key, "auto_probability", 7
            )
            sl_30 = _monitor_auto_stop_accuracy_bucket(
                cursor, union_sql, monitor_key, "auto_stop_loss_floor", 30
            )
            sl_7 = _monitor_auto_stop_accuracy_bucket(
                cursor, union_sql, monitor_key, "auto_stop_loss_floor", 7
            )
        conn.close()
        return {
            "status": "ok",
            "monitor_key": monitor_key,
            "probability_stop": {"30d": prob_30, "7d": prob_7},
            "stop_loss_floor": {"30d": sl_30, "7d": sl_7},
        }
    except Exception as e:  # pragma: no cover - defensive
        return {"status": "error", "message": str(e)}


def main() -> None:
    import uvicorn

    host = os.getenv("READ_API_HOST", "0.0.0.0")
    port = int(os.getenv("READ_API_PORT", "3050"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

