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
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from psycopg2 import sql
from fastapi import FastAPI, HTTPException, Query, Request, Response
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
    dashboard_history_bundle_payload,
    performance_realized_payload,
    pnl_history_payload,
    portfolio_history_payload,
)
from backend.core.performance_rollups import (
    performance_monitor_tiles_read_payload,
    performance_rollups_read_payload,
)
from backend.core.monitor_list_api import get_monitors_api_payload
from backend.core.strike_pipeline_health import (
    evaluate_pipeline_gate_conn,
    strike_pipeline_health_strict_mode_enabled,
)
from backend.core.trades_list_query import TRADES_PAGE_SIZE_MAX, execute_trades_list_query
from backend.core.tenant_strategy_list import load_strategy_picker_for_slot
from backend.trading_mode import (
    account_balance_table_for_user,
    sql_ident_qualified_table,
    subaccounts_table_for_user,
    transfers_table_for_user,
)
from backend.util.trade_log_archivist import (
    canonical_monitor_key,
    fetch_master_trades_column_names,
    union_trades_with_archives_select,
)
from backend.web.auth_routes import auth_router, user_router
from backend.web.auth_self_registration import self_reg_router
from backend.web.tenant_asgi import WebTenantMiddleware
from backend.web.read_api_logging import get_read_api_logger
from backend.core.time_eastern import now_est

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
_read_logger = get_read_api_logger()

# Short TTL cache for Kraken public ticker (reduces duplicate HTTP on /core hot path).
_kraken_ticker_lock = threading.Lock()
_kraken_ticker_cache: Optional[Dict[str, Any]] = None
_kraken_ticker_expires_monotonic: float = 0.0
_KRAKEN_TICKER_TTL_SEC = 2.5

# Short TTL cache for batch orderbook liquidity probes (absorbs UI polling bursts).
_liquidity_map_lock = threading.Lock()
_liquidity_map_cache: Dict[str, Tuple[float, Dict[str, bool]]] = {}
_LIQUIDITY_MAP_TTL_SEC = 0.35


def _kraken_xxbtzusd_ticker_cached() -> Optional[Dict[str, Any]]:
    """Return Kraken ``XXBTZUSD`` ticker object or None; shared TTL across /core paths."""
    global _kraken_ticker_cache, _kraken_ticker_expires_monotonic
    now_m = time.monotonic()
    with _kraken_ticker_lock:
        if _kraken_ticker_cache is not None and now_m < _kraken_ticker_expires_monotonic:
            return _kraken_ticker_cache
    try:
        response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
        if response.status_code != 200:
            return None
        data = response.json()
        ticker = data.get("result", {}).get("XXBTZUSD")
        if not isinstance(ticker, dict):
            return None
        with _kraken_ticker_lock:
            _kraken_ticker_cache = ticker
            _kraken_ticker_expires_monotonic = time.monotonic() + _KRAKEN_TICKER_TTL_SEC
        return ticker
    except Exception:
        return None


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


def _api_no_store_headers(response: Response) -> None:
    """Avoid stale browser/CDN cache of account-manager JSON payloads."""
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"


def _session_user_number_from_optional_user_id(user_id: Optional[str]) -> str:
    """Authenticated tenant slot; optional ``user_id`` must match session."""
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


@app.get("/api/account/balance")
async def get_account_balance(
    response: Response,
    mode: str = "prod",
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — must match UI toggle",
    ),
):
    _api_no_store_headers(response)
    _ = mode  # Kept for backward-compatible query contract.
    try:
        from psycopg2.extras import RealDictCursor

        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {
                "portfolio": 0,
                "positions": 0,
                "bankroll_current": 0,
                "mtb_base_value": None,
                "master_trading_bankroll": None,
            }
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                ab_ident = sql_ident_qualified_table(
                    account_balance_table_for_user(slot, client_trading_mode=trading_mode)
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
                row = cursor.fetchone()
            if not row:
                return {
                    "portfolio": 0,
                    "positions": 0,
                    "bankroll_current": 0,
                    "mtb_base_value": None,
                    "master_trading_bankroll": None,
                }
            return {
                "portfolio": row.get("portfolio") or 0,
                "positions": row.get("positions") or 0,
                "bankroll_current": row.get("bankroll_current") or 0,
                "mtb_base_value": row.get("mtb_base_value"),
                "master_trading_bankroll": row.get("master_trading_bankroll"),
            }
        finally:
            conn.close()
    except Exception:
        return {
            "portfolio": 0,
            "positions": 0,
            "bankroll_current": 0,
            "mtb_base_value": None,
            "master_trading_bankroll": None,
        }


@app.get("/api/subaccounts")
async def get_subaccounts(response: Response, trading_mode: Optional[str] = None):
    _api_no_store_headers(response)
    try:
        from psycopg2.extras import RealDictCursor

        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {"subaccounts": []}
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                sa_ident = sql_ident_qualified_table(
                    subaccounts_table_for_user(slot, client_trading_mode=trading_mode)
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
            return {"subaccounts": [dict(r) for r in rows]}
        finally:
            conn.close()
    except Exception:
        return {"subaccounts": []}


@app.get("/api/account/balance/history")
async def get_account_balance_history(
    mode: str = "prod",
    limit: int = 1000,
    trading_mode: Optional[str] = None,
):
    _ = mode  # Kept for backward-compatible query contract.
    try:
        from psycopg2.extras import RealDictCursor

        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {"history": []}
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                ab_ident = sql_ident_qualified_table(
                    account_balance_table_for_user(slot, client_trading_mode=trading_mode)
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
                rows = cursor.fetchall()
            history = []
            for row in rows:
                history.append(
                    {
                        "portfolio": row.get("portfolio"),
                        "positions": row.get("positions"),
                        "timestamp": row.get("updated_at").isoformat()
                        if row.get("updated_at")
                        else None,
                    }
                )
            return {"history": history}
        finally:
            conn.close()
    except Exception:
        return {"history": []}


@app.get("/api/db/fills")
async def get_fills(response: Response, trading_mode: Optional[str] = None):
    _api_no_store_headers(response)
    if trading_mode == "paper":
        return {"fills": []}
    try:
        from psycopg2.extras import RealDictCursor

        conn = get_postgresql_connection()
        if not conn:
            return {"fills": []}
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM users.fills_0001
                    ORDER BY id DESC
                    LIMIT 100
                    """
                )
                rows = cursor.fetchall()
            out = []
            for row in rows:
                d = dict(row)
                if d.get("outcome_side") is not None:
                    d.setdefault("side", d["outcome_side"])
                if d.get("count_fp") is not None:
                    try:
                        d["count"] = int(round(float(d["count_fp"])))
                    except (TypeError, ValueError):
                        pass
                out.append(d)
            return {"fills": out}
        finally:
            conn.close()
    except Exception:
        return {"fills": []}


@app.get("/api/db/positions")
async def get_positions(response: Response, trading_mode: Optional[str] = None):
    _api_no_store_headers(response)
    if trading_mode == "paper":
        return {"positions": []}
    try:
        from psycopg2.extras import RealDictCursor

        conn = get_postgresql_connection()
        if not conn:
            return {"positions": []}
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM users.positions_0001
                    ORDER BY id DESC
                    LIMIT 100
                    """
                )
                rows = cursor.fetchall()
            out = []
            for row in rows:
                d = dict(row)
                if d.get("position_fp") is not None:
                    try:
                        d["position"] = int(round(float(d["position_fp"])))
                    except (TypeError, ValueError):
                        pass
                if d.get("total_traded_fp") is not None:
                    try:
                        d["total_traded"] = int(round(float(d["total_traded_fp"])))
                    except (TypeError, ValueError):
                        pass
                out.append(d)
            return {"positions": out}
        finally:
            conn.close()
    except Exception:
        return {"positions": []}


@app.get("/api/db/settlements")
async def get_settlements(response: Response, trading_mode: Optional[str] = None):
    _api_no_store_headers(response)
    if trading_mode == "paper":
        return {"settlements": []}
    try:
        from psycopg2.extras import RealDictCursor

        conn = get_postgresql_connection()
        if not conn:
            return {"settlements": []}
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM users.settlements_0001
                    ORDER BY id DESC
                    LIMIT 100
                    """
                )
                rows = cursor.fetchall()
            out = []
            for row in rows:
                d = dict(row)
                if d.get("yes_count_fp") is not None:
                    try:
                        d["yes_count"] = int(round(float(d["yes_count_fp"])))
                    except (TypeError, ValueError):
                        pass
                if d.get("no_count_fp") is not None:
                    try:
                        d["no_count"] = int(round(float(d["no_count_fp"])))
                    except (TypeError, ValueError):
                        pass
                out.append(d)
            return {"settlements": out}
        finally:
            conn.close()
    except Exception:
        return {"settlements": []}


@app.get("/api/db/transfers")
async def get_transfers(
    response: Response,
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — match UI toggle (same table selection as subaccounts)",
    ),
):
    _api_no_store_headers(response)
    try:
        from psycopg2.extras import RealDictCursor

        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {"transfers": []}
        try:
            t_ident = sql_ident_qualified_table(
                transfers_table_for_user(slot, client_trading_mode=trading_mode)
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
                    ).format(t_ident)
                )
                rows = cursor.fetchall()
            return {"transfers": [dict(r) for r in rows]}
        finally:
            conn.close()
    except Exception:
        return {"transfers": []}


@app.get("/api/db/system_health")
async def get_system_health_from_db():
    """System health snapshot for System tab/mobile (moved from main_app)."""
    try:
        import psutil

        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        memory_total_gb = memory.total / (1024**3)
        memory_used_gb = memory.used / (1024**3)
        memory_available_gb = memory.available / (1024**3)

        disk_total_gb = disk.total / (1024**3)
        disk_used_gb = disk.used / (1024**3)
        disk_free_gb = disk.free / (1024**3)

        conn = get_postgresql_connection()
        if not conn:
            return {"error": "Database error"}
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM system.health_status WHERE id = 1")
                result = cursor.fetchone()
                if not result:
                    return {"error": "No health data available"}
                cols = [d[0] for d in cursor.description]
                row = dict(zip(cols, result))
        finally:
            conn.close()

        service_summary = {}
        hd = row.get("health_details")
        if hd:
            try:
                if isinstance(hd, str):
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
            "memory_total_gb": round(memory_total_gb, 1),
            "memory_used_gb": round(memory_used_gb, 1),
            "memory_available_gb": round(memory_available_gb, 1),
            "disk_total_gb": round(disk_total_gb, 1),
            "disk_used_gb": round(disk_used_gb, 1),
            "disk_free_gb": round(disk_free_gb, 1),
        }
    except Exception:
        return {"error": "Database error"}


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
    started = time.perf_counter()
    from backend.core.trade_monitor_live_orderbook_payload import (
        build_trade_monitor_orderbook_liquidity_map,
    )

    tickers = []
    for tok in str(market_tickers or "").split(","):
        mt = tok.strip()
        if mt:
            tickers.append(mt)
    try:
        if not tickers:
            return JSONResponse({"liquidity_by_ticker": {}})
        # Keep request bounded to avoid accidental oversized probes.
        tickers = tickers[:200]

        cache_key = ",".join(sorted(set(tickers)))
        now_mono = time.monotonic()
        with _liquidity_map_lock:
            hit = _liquidity_map_cache.get(cache_key)
            if hit is not None and now_mono < hit[0]:
                return JSONResponse({"liquidity_by_ticker": hit[1]})

        conn = get_system_postgresql_connection()
        if not conn:
            return JSONResponse({"error": "database_unavailable"}, status_code=503)
        try:
            with conn.cursor() as cursor:
                payload = build_trade_monitor_orderbook_liquidity_map(
                    cursor,
                    market_tickers=tickers,
                )
            with _liquidity_map_lock:
                _liquidity_map_cache[cache_key] = (
                    time.monotonic() + _LIQUIDITY_MAP_TTL_SEC,
                    payload,
                )
            return JSONResponse({"liquidity_by_ticker": payload})
        except Exception:
            return JSONResponse({"error": "orderbook_liquidity_failed"}, status_code=503)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    finally:
        _log_route_timing("/api/trade-monitor/orderbook/liquidity", started)


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
    started = time.perf_counter()
    try:
        return dashboard_history_bundle_payload(
            period=period, trading_mode=trading_mode, rollup_view=rollup_view
        )
    finally:
        _log_route_timing("/api/dashboard/history-bundle", started)


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


@app.get("/api/dashboard/preferences")
async def get_dashboard_preferences(mode: str = "prod") -> Dict[str, Any]:
    """Get dashboard preferences for the current tenant."""
    _ = mode
    try:
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
    except Exception:
        return {
            "status": "ok",
            "portfolio_chart_view": "all",
            "monitor_view_mode": "tile",
            "monitor_sort_by": "name",
            "allocation_view": "pie",
            "portfolio_view": "portfolio",
            "performance_rollup_view": "td",
        }


@app.get("/api/monitors")
async def get_monitors(user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        user_number = _session_user_number_from_optional_user_id(user_id)
        return get_monitors_api_payload(user_number)
    except HTTPException:
        raise
    except Exception as exc:
        _read_logger.exception("GET /api/monitors failed")
        raise HTTPException(
            status_code=500,
            detail=f"get_monitors_failed: {exc}"[:2000],
        ) from exc


@app.get("/api/monitors/health")
async def get_monitors_health(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Get monitor health only (power-light payload), without full monitor tile data."""
    try:
        conn = get_postgresql_connection()
        user_number = _session_user_number_from_optional_user_id(user_id)
        strict_pipeline_health = strike_pipeline_health_strict_mode_enabled()
        if not conn:
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
            health_by_symbol_market: dict = {}
            if strict_pipeline_health:
                sym_mkt_pairs = sorted(
                    {
                        (str(symbol).upper(), (market or "").strip().lower())
                        for _mid, symbol, _status, market in monitor_rows
                        if symbol and ((market or "").strip().lower() in ("15m", "hourly"))
                    }
                )
                for sym, mkt in sym_mkt_pairs:
                    ok, rsn = evaluate_pipeline_gate_conn(
                        conn, exchange="kalshi", market=mkt, symbol=sym
                    )
                    health_by_symbol_market[(sym, mkt)] = {
                        "monitor_healthy": ok,
                        "monitor_health_state": "healthy" if ok else "degraded",
                        "monitor_health_reason": "ok" if ok else rsn,
                        "monitor_health_age_sec": None,
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
                    h = health_by_symbol_market.get((monitor_symbol, monitor_market))
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
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/symbols")
async def get_symbols() -> Dict[str, Any]:
    try:
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT symbol
            FROM live_data.symbols_list
            ORDER BY symbol
            """
        )
        results = cursor.fetchall()
        conn.close()
        symbols = [row[0] for row in results]
        return {"status": "ok", "count": len(symbols), "symbols": symbols}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitor/{monitor_id}")
async def get_monitor_details(monitor_id: int, user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        user_number = _session_user_number_from_optional_user_id(user_id)
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT id, name, symbol, strategy, position_size, multiplier, total_position, position_type, bankroll_allotment_total, auto_trade, paper_trade, test_filter, market
            FROM users.monitor_list_{user_number}
            WHERE id = %s AND status = 'active'
            """,
            (monitor_id,),
        )
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
                },
            }
        return {"status": "error", "message": "Monitor not found"}
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitors/names")
async def get_monitor_names(user_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        user_number = _session_user_number_from_optional_user_id(user_id)
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT id, name, symbol, market, strategy, auto_trade_status, cooldown_timer
            FROM users.monitor_list_{user_number}
            WHERE status = 'active'
            ORDER BY name
            """
        )
        results = cursor.fetchall()
        conn.close()
        monitors = []
        for row in results:
            monitor_id, name, symbol, market, strategy, auto_trade_status, cooldown_timer = row
            mkt = (market or "").strip().lower() if market else None
            if mkt not in ("hourly", "15m"):
                mkt = None
            monitors.append(
                {
                    "id": monitor_id,
                    "name": name,
                    "symbol": symbol,
                    "market": mkt,
                    "strategy": strategy,
                    "auto_trade_status": (
                        str(auto_trade_status).strip().lower()
                        if auto_trade_status is not None
                        else "inactive"
                    ),
                    "cooldown_timer": int(cooldown_timer or 0),
                }
            )
        return {
            "status": "ok",
            "user_id": f"user_{user_number}",
            "count": len(monitors),
            "monitors": monitors,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/monitors/allocation")
async def get_monitors_allocation(
    user_id: Optional[str] = None,
    trading_mode: Optional[str] = Query(
        None,
        description="paper|live — which account_balance table backs dollar amounts (matches UI toggle)",
    ),
) -> Dict[str, Any]:
    try:
        user_number = _session_user_number_from_optional_user_id(user_id)
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
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
                """
            )
            monitor_results = cursor.fetchall()

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
            total_bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value
            total_bankroll_dollars = total_bankroll_cents / 100
        conn.close()

        allocations = []
        for row in monitor_results:
            monitor_id, name, symbol, strategy, bankroll_allotment_pct, bankroll_allotment_total, status = row
            pct_decimal = float(bankroll_allotment_pct or 0)
            percentage = pct_decimal * 100
            dollar_amount = total_bankroll_dollars * pct_decimal
            if dollar_amount <= 0 and bankroll_allotment_total:
                dollar_amount = float(bankroll_allotment_total) / 100.0
            allocations.append(
                {
                    "id": f"mon_{user_number}_{monitor_id}",
                    "name": name,
                    "symbol": symbol,
                    "strategy": strategy,
                    "bankroll_pct": round(percentage, 2),
                    "dollar_amount": round(dollar_amount, 2),
                    "total_bankroll": total_bankroll_dollars,
                    "status": status,
                }
            )
        return {
            "status": "ok",
            "allocations": allocations,
            "total_bankroll": total_bankroll_dollars,
        }
    except HTTPException:
        raise
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/strategies")
async def get_strategies(user_id: Optional[str] = None) -> Dict[str, Any]:
    _ = user_id
    try:
        slot = resolved_tenant_user_no_for_app()
        payload = load_strategy_picker_for_slot(slot)
        return {"status": "ok", **payload}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/earliest_trade_date")
async def get_earliest_trade_date() -> Dict[str, Any]:
    try:
        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {"earliest_date": None}
        try:
            with conn.cursor() as cursor:
                if not fetch_master_trades_column_names(cursor, slot):
                    return {"earliest_date": None}
                union_sql, _ = union_trades_with_archives_select(cursor, slot)
                cursor.execute(
                    """
                    SELECT MIN(
                        CASE
                            WHEN t.date IS NOT NULL AND TRIM(t.date) <> '' THEN TRIM(t.date)
                            WHEN t.created_at IS NOT NULL THEN to_char(t.created_at::date, 'YYYY-MM-DD')
                            ELSE NULL
                        END
                    )
                    FROM ("""
                    + union_sql
                    + """) AS t
                    """
                )
                row = cursor.fetchone()
                earliest = row[0] if row else None
                return {"earliest_date": earliest}
        finally:
            conn.close()
    except Exception:
        return {"earliest_date": None}


@app.get("/api/btc_price")
async def get_btc_price() -> Dict[str, Any]:
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1"
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return {"price": float(result[0]), "source": "postgresql_live_data"}
        return {"price": None, "error": "No price data available"}
    except Exception as e:
        return {"price": None, "error": str(e)}


@app.get("/api/eth_price")
async def get_eth_price() -> Dict[str, Any]:
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT price FROM live_data.live_price_log_1s_eth ORDER BY timestamp DESC LIMIT 1"
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return {"price": float(result[0]), "source": "postgresql_live_data"}
        return {"price": None, "error": "No price data available"}
    except Exception as e:
        return {"price": None, "error": str(e)}


@app.get("/btc_price_changes")
async def get_btc_changes() -> Dict[str, Any]:
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT change1h, change3h, change1d, timestamp
            FROM live_data.price_change_btc
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "change1h": float(result[0]) if result[0] is not None else None,
                "change3h": float(result[1]) if result[1] is not None else None,
                "change1d": float(result[2]) if result[2] is not None else None,
                "timestamp": result[3].isoformat() if result[3] else datetime.utcnow().isoformat(),
            }
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": datetime.utcnow().isoformat()}
    except Exception:
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": None}


@app.get("/eth_price_changes")
async def get_eth_changes() -> Dict[str, Any]:
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT change1h, change3h, change1d, timestamp
            FROM live_data.price_change_eth
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "change1h": float(result[0]) if result[0] is not None else None,
                "change3h": float(result[1]) if result[1] is not None else None,
                "change1d": float(result[2]) if result[2] is not None else None,
                "timestamp": result[3].isoformat() if result[3] else datetime.utcnow().isoformat(),
            }
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": datetime.utcnow().isoformat()}
    except Exception:
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": None}


def _monitor_auto_stop_accuracy_bucket_counts(confirmed: int, total: int) -> Dict[str, Any]:
    """Build confirmed/total/accuracy_pct from pre-aggregated counts."""
    c = int(confirmed or 0)
    t = int(total or 0)
    pct = round(100.0 * c / t, 1) if t > 0 else None
    return {"confirmed": c, "total": t, "accuracy_pct": pct}


def _monitor_auto_stop_accuracy_all_buckets(
    cursor: Any, union_sql: str, monitor_key: str
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Single scan over union trades for all four (close_method × window) buckets.
    Semantics match the previous four separate queries (rolling windows from ts_eff).
    """
    cursor.execute(
        """
        SELECT
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_probability'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '30 days'
              AND t.win_loss_confirmed IS TRUE
          ),
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_probability'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '30 days'
          ),
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_probability'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '7 days'
              AND t.win_loss_confirmed IS TRUE
          ),
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_probability'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '7 days'
          ),
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_stop_loss_floor'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '30 days'
              AND t.win_loss_confirmed IS TRUE
          ),
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_stop_loss_floor'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '30 days'
          ),
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_stop_loss_floor'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '7 days'
              AND t.win_loss_confirmed IS TRUE
          ),
          COUNT(*) FILTER (
            WHERE t.status = 'closed' AND t.win_loss = 'L'
              AND LOWER(TRIM(COALESCE(t.monitor, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(t.close_method, ''))) = 'auto_stop_loss_floor'
              AND t.ts_eff >= CURRENT_TIMESTAMP - INTERVAL '7 days'
          )
        FROM (
          SELECT u.*,
            (CASE
              WHEN u.closed_at IS NOT NULL AND u.closed_at ~ '^\\d{4}-\\d{2}-\\d{2}'
              THEN u.closed_at::timestamptz
              ELSE u.created_at
            END) AS ts_eff
          FROM ("""
        + union_sql
        + """) AS u
        ) AS t
        """,
        (monitor_key,) * 8,
    )
    row = cursor.fetchone()
    if not row:
        empty = {"confirmed": 0, "total": 0, "accuracy_pct": None}
        return empty, empty, empty, empty
    prob_30 = _monitor_auto_stop_accuracy_bucket_counts(row[0], row[1])
    prob_7 = _monitor_auto_stop_accuracy_bucket_counts(row[2], row[3])
    sl_30 = _monitor_auto_stop_accuracy_bucket_counts(row[4], row[5])
    sl_7 = _monitor_auto_stop_accuracy_bucket_counts(row[6], row[7])
    return prob_30, prob_7, sl_30, sl_7


@app.get("/api/monitor_auto_stop_accuracy")
async def get_monitor_auto_stop_accuracy(monitor_id: str | None = None) -> Dict[str, Any]:
    """
    Per monitor, per auto-stop ``close_method`` (``auto_probability`` vs ``auto_stop_loss_floor``):
    among **losing** closed trades in rolling 7d / 30d, percentage with ``win_loss_confirmed`` TRUE.

    Includes tenant trades table and archive tables.
    """
    started = time.perf_counter()
    try:
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
                prob_30, prob_7, sl_30, sl_7 = _monitor_auto_stop_accuracy_all_buckets(
                    cursor, union_sql, monitor_key
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
    finally:
        _log_route_timing("/api/monitor_auto_stop_accuracy", started)


def _unified_strike_table_for_market(market: str) -> str:
    m = (market or "").strip().lower()
    if m == "15m":
        return "strike_table_15m"
    if m == "hourly":
        return "strike_table_hourly"
    raise ValueError("market must be 'hourly' or '15m'")


def _log_route_timing(route: str, started: float) -> None:
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _read_logger.info("read_api_route %s %.1fms", route, elapsed_ms)


def _core_ttc_data() -> Dict[str, Any]:
    try:
        ne = now_est()
        next_hour = ne.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        ttc_seconds = int((next_hour - ne).total_seconds())
        return {
            "ttc_seconds": ttc_seconds,
            "timestamp": ne.isoformat(),
            "current_time_est": ne.strftime("%I:%M:%S %p %Z"),
            "next_hour_est": next_hour.strftime("%I:%M:%S %p %Z"),
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/core")
async def get_core_data(symbol: str = "BTC") -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        now = now_est()
        date_str = now.strftime("%A, %B %d, %Y")
        time_str = now.strftime("%I:%M:%S %p %Z")

        ttc_seconds = 0
        try:
            ttc_data = _core_ttc_data()
            ttc_seconds = ttc_data.get("ttc_seconds", 0)
        except Exception:
            close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
            if now.time() >= close_time.time():
                close_time += timedelta(days=1)
            ttc_seconds = int((close_time - now).total_seconds())

        btc_price = 0.0
        momentum_data: Dict[str, Any] = {}
        latest_db_price = 0
        conn = None
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1"
            )
            row_btc = cursor.fetchone()
            if row_btc and row_btc[0] is not None:
                btc_price = float(row_btc[0])
            else:
                tk = _kraken_xxbtzusd_ticker_cached()
                if tk:
                    btc_price = float(tk["c"][0])

            cursor.execute(
                f"""
                SELECT momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg,
                       move_1m, move_2m, move_3m, move_4m, movement, movement_percentile
                FROM live_data.live_price_log_1s_{symbol.lower()}
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            result = cursor.fetchone()
            if result:
                (
                    momentum,
                    delta_1m,
                    delta_2m,
                    delta_3m,
                    delta_4m,
                    delta_15m,
                    delta_30m,
                    momentum_percentile,
                    momentum_5s_avg,
                    move_1m,
                    move_2m,
                    move_3m,
                    move_4m,
                    movement,
                    movement_percentile,
                ) = result
                momentum_data = {
                    "weighted_momentum_score": float(momentum) if momentum is not None else 0.0,
                    "delta_1m": float(delta_1m) if delta_1m is not None else None,
                    "delta_2m": float(delta_2m) if delta_2m is not None else None,
                    "delta_3m": float(delta_3m) if delta_3m is not None else None,
                    "delta_4m": float(delta_4m) if delta_4m is not None else None,
                    "delta_15m": float(delta_15m) if delta_15m is not None else None,
                    "delta_30m": float(delta_30m) if delta_30m is not None else None,
                    "momentum_percentile": float(momentum_percentile) if momentum_percentile is not None else None,
                    "momentum_5s_avg": float(momentum_5s_avg) if momentum_5s_avg is not None else None,
                    "move_1m": float(move_1m) if move_1m is not None else None,
                    "move_2m": float(move_2m) if move_2m is not None else None,
                    "move_3m": float(move_3m) if move_3m is not None else None,
                    "move_4m": float(move_4m) if move_4m is not None else None,
                    "movement": float(movement) if movement is not None else None,
                    "movement_percentile": float(movement_percentile) if movement_percentile is not None else None,
                }
            else:
                momentum_data = {
                    "delta_1m": None,
                    "delta_2m": None,
                    "delta_3m": None,
                    "delta_4m": None,
                    "delta_15m": None,
                    "delta_30m": None,
                    "weighted_momentum_score": None,
                    "move_1m": None,
                    "move_2m": None,
                    "move_3m": None,
                    "move_4m": None,
                    "movement": None,
                    "movement_percentile": None,
                }

            slot_price = resolved_tenant_user_no_for_app()
            if fetch_master_trades_column_names(cursor, slot_price):
                union_sql, _ = union_trades_with_archives_select(cursor, slot_price)
                cursor.execute(
                    f"""
                    SELECT buy_price FROM ({union_sql}) AS all_trades
                    WHERE test_filter IS NULL OR test_filter = FALSE
                    ORDER BY date DESC, time DESC LIMIT 1
                    """
                )
                row_lp = cursor.fetchone()
                if row_lp:
                    latest_db_price = row_lp[0]
        except Exception:
            momentum_data = {
                "delta_1m": None,
                "delta_2m": None,
                "delta_3m": None,
                "delta_4m": None,
                "delta_15m": None,
                "delta_30m": None,
                "weighted_momentum_score": None,
                "move_1m": None,
                "move_2m": None,
                "move_3m": None,
                "move_4m": None,
                "movement": None,
                "movement_percentile": None,
            }
            if btc_price == 0.0:
                tk = _kraken_xxbtzusd_ticker_cached()
                if tk:
                    try:
                        btc_price = float(tk["c"][0])
                    except (KeyError, TypeError, ValueError):
                        pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        kraken_changes: Dict[str, Any] = {}
        try:
            ticker = _kraken_xxbtzusd_ticker_cached()
            if ticker:
                current_price = float(ticker["c"][0])
                old_price = float(ticker["p"][0])
                for period in ("1h", "3h", "1d"):
                    change = (current_price - old_price) / old_price
                    kraken_changes[f"change{period}"] = change
        except Exception:
            pass

        return {
            "date": date_str,
            "time": time_str,
            "ttc_seconds": ttc_seconds,
            "btc_price": btc_price,
            "latest_db_price": latest_db_price,
            "timestamp": now_est().isoformat(),
            **momentum_data,
            "status": "online",
            "volScore": 0,
            "volSpike": 0,
            **kraken_changes,
            "kalshi_markets": [],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        _log_route_timing("/core", started)


@app.get("/api/momentum")
async def get_current_momentum(symbol: str = "BTC") -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        if result and result[0] is not None:
            return {"status": "ok", "momentum_score": float(result[0])}
        return {"status": "error", "momentum_score": 0, "error": "No momentum data available"}
    except Exception:
        return {"status": "error", "momentum_score": 0, "error": "Unable to get momentum from PostgreSQL"}
    finally:
        _log_route_timing("/api/momentum", started)


@app.get("/api/live_symbol_status_snapshot")
async def get_live_symbol_status_snapshot() -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        allowed = ("BTC", "ETH", "SOL", "XRP")
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT symbol, price, momentum_percentile, volatility_percentile, movement_percentile, "timestamp"
            FROM live_data.live_symbol_status
            WHERE symbol = ANY(%s)
            """,
            (list(allowed),),
        )
        rows = {str(r[0]).upper(): r for r in cursor.fetchall()}
        conn.close()
        out: List[Dict[str, Any]] = []
        for sym in allowed:
            row = rows.get(sym)
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
        ts_out = None
        for sym in allowed:
            found = next((r for r in out if r["symbol"] == sym), None)
            if found and found.get("timestamp"):
                ts_out = found["timestamp"]
                break
        return {"status": "ok", "timestamp": ts_out, "symbols": out}
    except Exception as e:
        return {"status": "error", "message": str(e), "symbols": []}
    finally:
        _log_route_timing("/api/live_symbol_status_snapshot", started)


@app.get("/api/postgresql/strike_table/{symbol}")
async def get_postgresql_strike_table(symbol: str, request: Request) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
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
                    SELECT symbol, current_price, ttc_15m, momentum_percentile, market_title, "timestamp", event_ticker
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
                # Latest row per ticker (matches strike_ladder_fetch). Avoids empty ladder when
                # batch inserts used per-row timestamps so max(timestamp) matched only one strike.
                cursor.execute(
                    """
                    SELECT strike, buffer, buffer_pct, probability_15m, yes_ask_dollars, no_ask_dollars,
                           volume_fp, open_interest_fp, ticker, yes_diff, no_diff, active_side,
                           yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                           yes_ask_range_15m, no_ask_range_15m
                    FROM (
                        SELECT DISTINCT ON (ticker)
                            strike, buffer, buffer_pct, probability_15m, yes_ask_dollars, no_ask_dollars,
                            volume_fp, open_interest_fp, ticker, yes_diff, no_diff, active_side,
                            yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                            yes_ask_range_15m, no_ask_range_15m
                        FROM live_data.strike_table_15m
                        WHERE exchange = %s AND symbol = %s
                        ORDER BY ticker, "timestamp" DESC
                    ) latest_per_ticker
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u),
                )
                strikes_data = cursor.fetchall()
                momentum_percentile = float(header_data[3]) if header_data[3] else 0.0
                response = {
                    "symbol": header_data[0],
                    "current_price": (str(header_data[1]) if raw else float(header_data[1])) if header_data[1] is not None else None,
                    "ttc_seconds": int(header_data[2]) if header_data[2] else None,
                    "momentum_percentile": momentum_percentile,
                    "momentum_bucket": round(momentum_percentile),
                    "market_title": header_data[4],
                    "timestamp": header_data[5].isoformat() if header_data[5] else None,
                    "event_ticker": header_data[6],
                    "strikes": [],
                }
                response["settlement_end_ms"] = _strike_pack_settlement_end_ms(header_data[6], strikes_data, 8)
            else:
                h_tbl = _unified_strike_table_for_market("hourly")
                cursor.execute(
                    f"""
                    SELECT symbol, current_price, ttc_hourly, momentum_percentile, market_title, "timestamp", event_ticker, strike_tier
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
                    SELECT strike, buffer, buffer_pct, probability_hourly, yes_ask_dollars, no_ask_dollars,
                           volume_fp, open_interest_fp, ticker, yes_diff, no_diff, active_side,
                           yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                           yes_ask_range_15m, no_ask_range_15m
                    FROM (
                        SELECT DISTINCT ON (ticker)
                            strike, buffer, buffer_pct, probability_hourly, yes_ask_dollars, no_ask_dollars,
                            volume_fp, open_interest_fp, ticker, yes_diff, no_diff, active_side,
                            yes_ask_min_15m, yes_ask_max_15m, no_ask_min_15m, no_ask_max_15m,
                            yes_ask_range_15m, no_ask_range_15m
                        FROM live_data.{h_tbl}
                        WHERE exchange = %s AND symbol = %s
                        ORDER BY ticker, "timestamp" DESC
                    ) latest_per_ticker
                    ORDER BY strike
                    """,
                    ("kalshi", sym_u),
                )
                strikes_data = cursor.fetchall()
                momentum_percentile = float(header_data[3]) if header_data[3] else 0.0
                response = {
                    "symbol": header_data[0],
                    "current_price": (str(header_data[1]) if raw else float(header_data[1])) if header_data[1] is not None else None,
                    "ttc_seconds": int(header_data[2]) if header_data[2] else None,
                    "momentum_percentile": momentum_percentile,
                    "momentum_bucket": round(momentum_percentile),
                    "market_title": header_data[4],
                    "timestamp": header_data[5].isoformat() if header_data[5] else None,
                    "event_ticker": header_data[6],
                    "strike_tier": int(header_data[7]) if header_data[7] is not None else None,
                    "strikes": [],
                }
                response["settlement_end_ms"] = _strike_pack_settlement_end_ms(header_data[6], strikes_data, 8)

            for strike_row in strikes_data:
                vfp = strike_row[6]
                oifp = strike_row[7]
                response["strikes"].append(
                    {
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
                )
            conn.close()
            return response
    except Exception as e:
        return {"error": f"Error loading PostgreSQL strike table for {symbol}: {str(e)}"}
    finally:
        _log_route_timing("/api/postgresql/strike_table/{symbol}", started)


@app.get("/api/unified_ttc/{symbol}")
async def get_unified_ttc(symbol: str, request: Request) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
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
                return {
                    "ttc_seconds": int(result[0]),
                    "event_ticker": result[1],
                    "market_title": result[2],
                    "market_status": result[3],
                    "symbol": symbol.upper(),
                }
            return {
                "ttc_seconds": 0,
                "event_ticker": None,
                "market_title": None,
                "market_status": "no_active_markets",
                "symbol": symbol.upper(),
            }
    except Exception as e:
        return {"error": f"Error getting unified TTC: {str(e)}"}
    finally:
        _log_route_timing("/api/unified_ttc/{symbol}", started)


def main() -> None:
    import uvicorn

    host = os.getenv("READ_API_HOST", "0.0.0.0")
    port = int(os.getenv("READ_API_PORT", "3050"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

