"""
read_api: dedicated read/aggregate service for frontend data.

Role: host read/aggregate endpoints (dashboard, history, stats) and the auth/user plane
(login, session, profile, throttled ``POST /api/user/activity`` for ``last_login``).
No WebSocket, no Redis pub/sub. Aside from auth/session and that activity touch, avoids writes.
Also performs a single Redis **GET** of the cached release string
(`redis_key_system_release_version`) for the System UI. See docs/REDIS_ARCHITECTURE.md.
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.core.dashboard_portfolio_queries import (
    bankroll_history_payload,
    performance_realized_payload,
    pnl_history_payload,
    portfolio_history_payload,
)
from backend.util.trade_log_archivist import (
    canonical_monitor_key,
    fetch_master_trades_column_names,
    union_trades_with_archives_select,
)
from backend.web.auth_routes import auth_router, user_router
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
app.include_router(user_router, prefix="/api/user")


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


@app.get("/api/portfolio/history")
async def get_portfolio_history(
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
) -> Dict[str, Any]:
    """Same implementation as main_app (shared module)."""
    return portfolio_history_payload(period=period, trading_mode=trading_mode)


@app.get("/api/bankroll/history")
async def get_bankroll_history(
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
) -> Dict[str, Any]:
    return bankroll_history_payload(period=period, trading_mode=trading_mode)


@app.get("/api/pnl/history")
async def get_pnl_history(
    period: str = "1m",
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
) -> Dict[str, Any]:
    return pnl_history_payload(period=period, trading_mode=trading_mode)


@app.get("/api/performance/realized")
async def get_performance_realized(
    trading_mode: Optional[str] = Query(
        None, description="paper|live — match UI toggle; omit to use server global mode file"
    ),
) -> Dict[str, Any]:
    return performance_realized_payload(trading_mode=trading_mode)


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
        WHERE (t.test_filter IS NULL OR t.test_filter = FALSE)
          AND t.status = 'closed'
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

