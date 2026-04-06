"""
read_api: dedicated read/aggregate service for frontend data.

Role: host all read-only/aggregate endpoints (dashboard, history, stats).
No WebSocket, no Redis subscription, no writes. See docs/REDIS_ARCHITECTURE.md.
"""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from psycopg2 import sql as psql

from backend.core.config.database import get_postgresql_connection
from backend.trading_mode import account_balance_table_for_user, is_paper_trading, sql_ident_qualified_table
from backend.util.trade_log_archivist import union_trades_with_archives_select

app = FastAPI(title="read_api")


def _format_currency_cents(value_cents: Any) -> float:
    if value_cents is None:
        return 0.0
    try:
        return float(value_cents) / 100.0
    except Exception:
        return 0.0


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "healthy",
            "service": "read_api",
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


@app.get("/api/portfolio/history")
async def get_portfolio_history(period: str = "1m") -> Dict[str, Any]:
    """
    Mirror of main.py /api/portfolio/history, but served from read_api.
    Historical portfolio data from users.account_balance_0001 for charting.
    """
    try:
        import psycopg2  # type: ignore

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        ab_ident = sql_ident_qualified_table(account_balance_table_for_user("0001"))

        # Use a timezone-aware reference for consistent timestamptz filtering.
        from zoneinfo import ZoneInfo  # local import to keep startup fast
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)
        results: List[Any] = []

        if period == "1d":
            today_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, portfolio
                    FROM {}
                    WHERE updated_at < %s
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                """
                    ).format(ab_ident),
                    (today_5am,),
                )
                last_before_5am = cursor.fetchone()

            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, portfolio
                    FROM {}
                    WHERE updated_at >= %s
                    ORDER BY updated_at ASC, id ASC
                """
                    ).format(ab_ident),
                    (today_5am,),
                )
                results = cursor.fetchall()

            if last_before_5am:
                results = [last_before_5am] + list(results)

        else:
            if period == "1w":
                start_time = now - timedelta(weeks=1)
            elif period == "1m":
                start_time = now - timedelta(days=30)
            elif period == "1y":
                start_time = now - timedelta(days=365)
            else:  # "all"
                start_time = datetime(2020, 1, 1, tzinfo=eastern)

            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, portfolio
                    FROM {}
                    WHERE updated_at >= %s
                    ORDER BY updated_at ASC, id ASC
                """
                    ).format(ab_ident),
                    (start_time,),
                )
                results = cursor.fetchall()

        conn.close()

        data: List[Dict[str, Any]] = []
        for row in results:
            timestamp, portfolio = row
            data.append(
                {
                    "timestamp": timestamp if timestamp else None,
                    "portfolio": _format_currency_cents(portfolio),
                }
            )

        return {
            "status": "ok",
            "period": period,
            "count": len(data),
            "data": data,
            "trading_mode": "paper" if is_paper_trading() else "live",
        }

    except Exception as e:  # pragma: no cover - defensive
        return {"status": "error", "message": str(e)}


@app.get("/api/bankroll/history")
async def get_bankroll_history(period: str = "1m") -> Dict[str, Any]:
    """
    Mirror of main.py /api/bankroll/history, but served from read_api.
    Historical MTB base value from account_balance for Bankroll chart.
    """
    try:
        import psycopg2  # type: ignore

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        ab_ident = sql_ident_qualified_table(account_balance_table_for_user("0001"))
        # Use a timezone-aware reference for consistent timestamptz filtering.
        from zoneinfo import ZoneInfo  # local import to keep startup fast
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)
        results: List[Any] = []

        if period == "1d":
            today_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, COALESCE(mtb_base_value, bankroll_current)
                    FROM {}
                    WHERE updated_at < %s
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                """
                    ).format(ab_ident),
                    (today_5am,),
                )
                last_before_5am = cursor.fetchone()

            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, COALESCE(mtb_base_value, bankroll_current)
                    FROM {}
                    WHERE updated_at >= %s
                    ORDER BY updated_at ASC, id ASC
                """
                    ).format(ab_ident),
                    (today_5am,),
                )
                results = cursor.fetchall()

            if last_before_5am:
                results = [last_before_5am] + list(results)

        else:
            if period == "1w":
                start_time = now - timedelta(weeks=1)
            elif period == "1m":
                start_time = now - timedelta(days=30)
            elif period == "1y":
                start_time = now - timedelta(days=365)
            else:  # "all"
                start_time = datetime(2020, 1, 1, tzinfo=eastern)

            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, COALESCE(mtb_base_value, bankroll_current)
                    FROM {}
                    WHERE updated_at >= %s
                    ORDER BY updated_at ASC, id ASC
                """
                    ).format(ab_ident),
                    (start_time,),
                )
                results = cursor.fetchall()

        conn.close()

        data: List[Dict[str, Any]] = []
        for row in results:
            timestamp, value_cents = row
            data.append(
                {
                    "timestamp": timestamp if timestamp else None,
                    "bankroll": _format_currency_cents(value_cents),
                }
            )

        return {
            "status": "ok",
            "period": period,
            "count": len(data),
            "data": data,
            "trading_mode": "paper" if is_paper_trading() else "live",
        }

    except Exception as e:  # pragma: no cover - defensive
        return {"status": "error", "message": str(e)}


@app.get("/api/pnl/history")
async def get_pnl_history(period: str = "1m") -> Dict[str, Any]:
    """
    Cumulative PnL time series for charting.
    Mirrors the working implementation from main.py using the `pnl` column.
    """
    try:
        import psycopg2  # type: ignore

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        now = datetime.now()
        if period == "1d":
            start_time = now - timedelta(hours=24)
        elif period == "1w":
            start_time = now - timedelta(days=7)
        elif period == "1m":
            start_time = now - timedelta(days=30)
        elif period == "1y":
            start_time = now - timedelta(days=365)
        else:
            start_time = datetime(2020, 1, 1)

        start_date_sql = start_time.strftime("%Y-%m-%d")

        paper_clause = (
            "AND paper_trade IS TRUE"
            if is_paper_trading()
            else "AND (paper_trade IS NULL OR paper_trade = FALSE)"
        )

        with conn.cursor() as cursor:
            union_sql, _ = union_trades_with_archives_select(cursor, "0001")
            cursor.execute(
                """
                SELECT COALESCE(
                    CASE WHEN closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE NULL END,
                    created_at
                ) AS ts, pnl
                FROM ("""
                + union_sql
                + """) AS trades_all
                WHERE (test_filter IS NULL OR test_filter = FALSE)
                """
                + paper_clause
                + """
                  AND LOWER(TRIM(status)) IN ('closed', 'settled')
                  AND pnl IS NOT NULL
                  AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN (closed_at::timestamptz)::date ELSE created_at::date END) >= %s::date
                ORDER BY ts ASC
            """,
                (start_date_sql,),
            )
            rows = cursor.fetchall()

        conn.close()

        # Build cumulative series starting at $0
        data: List[Dict[str, Any]] = []
        cumulative = 0.0
        # First point: start of window at $0
        data.append({"timestamp": start_date_sql + "T00:00:00", "pnl": 0.0})
        for ts, pnl in rows:
            pnl_val = float(pnl) if pnl is not None else 0.0
            cumulative += pnl_val
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            data.append({"timestamp": ts_str, "pnl": round(cumulative, 2)})

        return {
            "status": "ok",
            "period": period,
            "count": len(data),
            "data": data,
            "total_pnl": round(cumulative, 2),
            "trading_mode": "paper" if is_paper_trading() else "live",
        }

    except Exception as e:  # pragma: no cover - defensive
        return {"status": "error", "message": str(e)}


@app.get("/api/performance/realized")
async def get_performance_realized() -> Dict[str, Any]:
    """
    Day/week/month/year realized PnL and returns.
    Mirrors the working implementation from main.py, inlining the SQL.
    """
    try:
        import psycopg2  # type: ignore
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo  # type: ignore

        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        with conn.cursor() as tz_cur:
            tz_cur.execute("SET TIME ZONE 'America/New_York'")
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)
        today = now.date()

        def et_start(y: int, m: int, d: int) -> datetime:
            return datetime(y, m, d, 0, 0, 0, tzinfo=eastern)

        day_start = et_start(today.year, today.month, today.day)
        days_since_sunday = (today.weekday() + 1) % 7
        sunday = today - timedelta(days=days_since_sunday)
        week_start = et_start(sunday.year, sunday.month, sunday.day)
        month_start = et_start(today.year, today.month, 1)
        year_start = et_start(today.year, 1, 1)

        yesterday = today - timedelta(days=1)
        prev_sunday = sunday - timedelta(days=7)
        prev_month_first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        prev_year_first = today.replace(month=1, day=1, year=today.year - 1)

        prev_day_start = et_start(yesterday.year, yesterday.month, yesterday.day)
        prev_week_start = et_start(prev_sunday.year, prev_sunday.month, prev_sunday.day)
        prev_month_start = et_start(prev_month_first.year, prev_month_first.month, prev_month_first.day)
        prev_year_start = et_start(prev_year_first.year, prev_year_first.month, prev_year_first.day)

        periods_spec = [
            ("day", day_start, prev_day_start),
            ("week", week_start, prev_week_start),
            ("month", month_start, prev_month_start),
            ("year", year_start, prev_year_start),
        ]

        result: Dict[str, Any] = {}
        with conn.cursor() as cursor:
            union_sql, _ = union_trades_with_archives_select(cursor, "0001")
            for key, period_start, prev_start in periods_spec:
                period_end = now
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(pnl), 0), COALESCE(SUM(ret_pct), 0), COALESCE(SUM(ret_pct_base), 0)
                    FROM ("""
                    + union_sql
                    + """) AS trades_all
                    WHERE (test_filter IS NULL OR test_filter = FALSE)
                      AND (paper_trade IS NULL OR paper_trade = FALSE)
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) >= %s
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) <= %s
                """,
                    (period_start, period_end),
                )
                row = cursor.fetchone()
                pnl = float(row[0]) if row and row[0] is not None else 0.0
                ret_pct_sum = float(row[1]) if row and row[1] is not None else None
                ret_pct_base_sum = float(row[2]) if row and row[2] is not None else None

                duration = period_end - period_start
                prev_end = prev_start + duration
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(pnl), 0)
                    FROM ("""
                    + union_sql
                    + """) AS trades_all
                    WHERE (test_filter IS NULL OR test_filter = FALSE)
                      AND (paper_trade IS NULL OR paper_trade = FALSE)
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) >= %s
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) <= %s
                """,
                    (prev_start, prev_end),
                )
                prev_row = cursor.fetchone()
                prev_pnl = float(prev_row[0]) if prev_row and prev_row[0] is not None else 0.0

                ret_pct = round(ret_pct_sum, 2) if ret_pct_sum is not None else None
                ret_pct_base = round(ret_pct_base_sum, 2) if ret_pct_base_sum is not None else None
                result[key] = {
                    "pnl": round(pnl, 2),
                    "ret_pct": ret_pct,
                    "ret_pct_base": ret_pct_base,
                    "prev_pnl": round(prev_pnl, 2),
                }

        conn.close()
        return {"status": "ok", "periods": result}

    except Exception as e:  # pragma: no cover - defensive
        return {"status": "error", "message": str(e)}


def main() -> None:
    import uvicorn

    host = os.getenv("READ_API_HOST", "0.0.0.0")
    port = int(os.getenv("READ_API_PORT", "3050"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

