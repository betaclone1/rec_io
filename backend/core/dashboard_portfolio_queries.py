"""
Dashboard portfolio / bankroll / PnL charts and performance panel — one implementation.

Used by **main_app** (same origin as the UI, session tenant) and **read_api** (optional direct calls).
Keeps SQL in one place so we do not rely on HTTP proxy + forwarded cookies between services.
"""

from __future__ import annotations

from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from psycopg2 import sql as psql

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.trading_mode import (
    account_balance_table_for_user,
    sql_ident_qualified_table,
    use_paper_for_request,
)
from backend.util.trade_log_archivist import (
    fetch_master_trades_column_names,
    union_trades_with_archives_select,
)


def _format_currency_cents(value_cents: Any) -> float:
    if value_cents is None:
        return 0.0
    try:
        return float(value_cents) / 100.0
    except Exception:
        return 0.0


def _paper_trade_sql_clause(trading_mode: Optional[str]) -> str:
    return (
        "AND paper_trade IS TRUE"
        if use_paper_for_request(trading_mode)
        else "AND (paper_trade IS NULL OR paper_trade = FALSE)"
    )


def _trading_mode_label(trading_mode: Optional[str]) -> str:
    return "paper" if use_paper_for_request(trading_mode) else "live"


def _performance_panel_trade_mode_clause(trading_mode: Optional[str]) -> str:
    """
    Live mode: closed trades with paper_trade false only.
    Paper (global or client): include both live and paper rows (matches trade_history with both boxes on).
    """
    if use_paper_for_request(trading_mode):
        return ""
    return "AND (COALESCE(trades_all.paper_trade, FALSE) = FALSE)\n"


def portfolio_history_payload(*, period: str, trading_mode: Optional[str]) -> Dict[str, Any]:
    conn = None
    try:
        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        ab_ident = sql_ident_qualified_table(
            account_balance_table_for_user(slot, client_trading_mode=trading_mode)
        )

        from zoneinfo import ZoneInfo

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
            else:
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
            "trading_mode": _trading_mode_label(trading_mode),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def bankroll_history_payload(*, period: str, trading_mode: Optional[str]) -> Dict[str, Any]:
    conn = None
    try:
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        slot = resolved_tenant_user_no_for_app()
        ab_ident = sql_ident_qualified_table(
            account_balance_table_for_user(slot, client_trading_mode=trading_mode)
        )
        from zoneinfo import ZoneInfo

        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)
        results: List[Any] = []

        if period == "1d":
            today_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, COALESCE(master_trading_bankroll, bankroll_current)
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
                    SELECT updated_at, COALESCE(master_trading_bankroll, bankroll_current)
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
            else:
                start_time = datetime(2020, 1, 1, tzinfo=eastern)

            with conn.cursor() as cursor:
                cursor.execute(
                    psql.SQL(
                        """
                    SELECT updated_at, COALESCE(master_trading_bankroll, bankroll_current)
                    FROM {}
                    WHERE updated_at >= %s
                    ORDER BY updated_at ASC, id ASC
                """
                    ).format(ab_ident),
                    (start_time,),
                )
                results = cursor.fetchall()

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
            "trading_mode": _trading_mode_label(trading_mode),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def pnl_history_payload(*, period: str, trading_mode: Optional[str]) -> Dict[str, Any]:
    conn = None
    try:
        slot = resolved_tenant_user_no_for_app()
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

        paper_clause = _paper_trade_sql_clause(trading_mode)

        with conn.cursor() as cursor:
            if not fetch_master_trades_column_names(cursor, slot):
                rows = []
            else:
                union_sql, _ = union_trades_with_archives_select(cursor, slot)
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

        data: List[Dict[str, Any]] = []
        cumulative = 0.0
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
            "trading_mode": _trading_mode_label(trading_mode),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def performance_realized_payload(*, trading_mode: Optional[str]) -> Dict[str, Any]:
    """
    Calendar periods in America/New_York: today (trade ``date``), week from Sunday 00:00 through today,
    month-to-date, YTD. Same ``date`` bounds and live/paper rules as trade_history (insights / min_date).

    ``ret_pct`` / ``ret_pct_base`` are SUM(per-trade values), matching trade_history cumulative Ret %.
    """
    conn = None
    try:
        from zoneinfo import ZoneInfo

        slot = resolved_tenant_user_no_for_app()
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        with conn.cursor() as tz_cur:
            tz_cur.execute("SET TIME ZONE 'America/New_York'")
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)
        today = now.date()

        days_since_sunday = (today.weekday() + 1) % 7
        sunday_d = today - timedelta(days=days_since_sunday)
        month_first_d = today.replace(day=1)
        year_first_d = Date(today.year, 1, 1)
        yesterday = today - timedelta(days=1)
        prev_week_end = sunday_d - timedelta(days=1)
        prev_week_start = prev_week_end - timedelta(days=6)
        last_prev_month = month_first_d - timedelta(days=1)
        first_prev_month = last_prev_month.replace(day=1)
        first_prev_year = Date(today.year - 1, 1, 1)
        last_prev_year = Date(today.year - 1, 12, 31)

        periods_spec: List[Tuple[str, Date, Date, Date, Date]] = [
            ("day", today, today, yesterday, yesterday),
            ("week", sunday_d, today, prev_week_start, prev_week_end),
            ("month", month_first_d, today, first_prev_month, last_prev_month),
            ("year", year_first_d, today, first_prev_year, last_prev_year),
        ]

        mode_clause = _performance_panel_trade_mode_clause(trading_mode)

        sum_sql = (
            """
                    SELECT COALESCE(SUM(trades_all.pnl), 0), COALESCE(SUM(trades_all.ret_pct), 0), COALESCE(SUM(trades_all.ret_pct_base), 0)
                    FROM ("""
            + "{union}"
            + """) AS trades_all
                    WHERE (trades_all.test_filter IS NULL OR trades_all.test_filter = FALSE)
                    """
            + mode_clause
            + """
                      AND LOWER(TRIM(trades_all.status)) IN ('closed', 'settled')
                      AND trades_all.pnl IS NOT NULL
                      AND trades_all."date" IS NOT NULL
                      AND (trades_all."date"::date) >= %s::date
                      AND (trades_all."date"::date) <= %s::date
                """
        )
        prev_sql = (
            """
                    SELECT COALESCE(SUM(trades_all.pnl), 0)
                    FROM ("""
            + "{union}"
            + """) AS trades_all
                    WHERE (trades_all.test_filter IS NULL OR trades_all.test_filter = FALSE)
                    """
            + mode_clause
            + """
                      AND LOWER(TRIM(trades_all.status)) IN ('closed', 'settled')
                      AND trades_all.pnl IS NOT NULL
                      AND trades_all."date" IS NOT NULL
                      AND (trades_all."date"::date) >= %s::date
                      AND (trades_all."date"::date) <= %s::date
                """
        )

        result: Dict[str, Any] = {}
        with conn.cursor() as cursor:
            has_trades = bool(fetch_master_trades_column_names(cursor, slot))
            union_sql = None
            if has_trades:
                union_sql, _ = union_trades_with_archives_select(cursor, slot)
            for key, d_lo, d_hi, prev_lo, prev_hi in periods_spec:
                if not union_sql:
                    result[key] = {
                        "pnl": 0.0,
                        "ret_pct": None,
                        "ret_pct_base": None,
                        "prev_pnl": 0.0,
                    }
                    continue
                q_sum = sum_sql.replace("{union}", union_sql)
                q_prev = prev_sql.replace("{union}", union_sql)
                cursor.execute(
                    q_sum,
                    (d_lo.isoformat(), d_hi.isoformat()),
                )
                row = cursor.fetchone()
                pnl = float(row[0]) if row and row[0] is not None else 0.0
                ret_pct_sum = float(row[1]) if row and row[1] is not None else 0.0
                ret_pct_base_sum = float(row[2]) if row and row[2] is not None else 0.0

                ret_pct = round(ret_pct_sum, 2)
                ret_pct_base = round(ret_pct_base_sum, 2)

                cursor.execute(
                    q_prev,
                    (prev_lo.isoformat(), prev_hi.isoformat()),
                )
                prev_row = cursor.fetchone()
                prev_pnl = float(prev_row[0]) if prev_row and prev_row[0] is not None else 0.0

                result[key] = {
                    "pnl": round(pnl, 2),
                    "ret_pct": ret_pct,
                    "ret_pct_base": ret_pct_base,
                    "prev_pnl": round(prev_pnl, 2),
                }

        return {
            "status": "ok",
            "periods": result,
            "trading_mode": _trading_mode_label(trading_mode),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
