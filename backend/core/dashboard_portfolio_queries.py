"""
Dashboard portfolio / bankroll / PnL charts and performance panel — one implementation.

Used by **main_app** (same origin as the UI, session tenant) and **read_api** (optional direct calls).
Keeps SQL in one place so we do not rely on HTTP proxy + forwarded cookies between services.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

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


def _period_return_vs_equity(pnl: float, equity_dollars: Optional[float]) -> Optional[float]:
    if equity_dollars is None or equity_dollars <= 0:
        return None
    return round(100.0 * float(pnl) / float(equity_dollars), 2)


def _account_balance_row_near_period_start(
    cursor: Any,
    ab_ident: Any,
    period_start: datetime,
    period_end: datetime,
) -> Any:
    """
    Prefer last snapshot strictly before period_start; else first snapshot inside [period_start, period_end].
    """
    cursor.execute(
        psql.SQL(
            """
            SELECT COALESCE(master_trading_bankroll, bankroll_current), mtb_base_value
            FROM {}
            WHERE updated_at < %s
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).format(ab_ident),
        (period_start,),
    )
    row = cursor.fetchone()
    if row and (row[0] is not None or row[1] is not None):
        return row
    cursor.execute(
        psql.SQL(
            """
            SELECT COALESCE(master_trading_bankroll, bankroll_current), mtb_base_value
            FROM {}
            WHERE updated_at >= %s AND updated_at <= %s
            ORDER BY updated_at ASC, id ASC
            LIMIT 1
            """
        ).format(ab_ident),
        (period_start, period_end),
    )
    return cursor.fetchone()


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

        paper_clause = _paper_trade_sql_clause(trading_mode)
        ab_ident = sql_ident_qualified_table(
            account_balance_table_for_user(slot, client_trading_mode=trading_mode)
        )

        result: Dict[str, Any] = {}
        with conn.cursor() as cursor:
            has_trades = bool(fetch_master_trades_column_names(cursor, slot))
            union_sql = None
            if has_trades:
                union_sql, _ = union_trades_with_archives_select(cursor, slot)
            for key, period_start, prev_start in periods_spec:
                if not union_sql:
                    result[key] = {
                        "pnl": 0.0,
                        "ret_pct": None,
                        "ret_pct_base": None,
                        "prev_pnl": 0.0,
                    }
                    continue
                period_end = now
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(pnl), 0), COALESCE(SUM(ret_pct), 0), COALESCE(SUM(ret_pct_base), 0)
                    FROM ("""
                    + union_sql
                    + """) AS trades_all
                    WHERE (test_filter IS NULL OR test_filter = FALSE)
                    """
                    + paper_clause
                    + """
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) >= %s
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) <= %s
                """,
                    (period_start, period_end),
                )
                row = cursor.fetchone()
                pnl = float(row[0]) if row and row[0] is not None else 0.0
                ret_pct_sum = float(row[1]) if row and row[1] is not None else 0.0
                ret_pct_base_sum = float(row[2]) if row and row[2] is not None else 0.0

                bal_row = _account_balance_row_near_period_start(
                    cursor, ab_ident, period_start, period_end
                )
                br0: Optional[float] = None
                mtb0: Optional[float] = None
                if bal_row:
                    br_raw, mtb_raw = bal_row[0], bal_row[1]
                    if br_raw is not None:
                        br0 = _format_currency_cents(br_raw)
                    if mtb_raw is not None:
                        mtb0 = _format_currency_cents(mtb_raw)

                ret_pct_calc = _period_return_vs_equity(pnl, br0)
                ret_pct_base_calc = _period_return_vs_equity(pnl, mtb0)
                ret_pct = (
                    ret_pct_calc
                    if ret_pct_calc is not None
                    else round(ret_pct_sum, 2)
                )
                ret_pct_base = (
                    ret_pct_base_calc
                    if ret_pct_base_calc is not None
                    else round(ret_pct_base_sum, 2)
                )

                duration = period_end - period_start
                prev_end = prev_start + duration
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(pnl), 0)
                    FROM ("""
                    + union_sql
                    + """) AS trades_all
                    WHERE (test_filter IS NULL OR test_filter = FALSE)
                    """
                    + paper_clause
                    + """
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) >= %s
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) <= %s
                """,
                    (prev_start, prev_end),
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
