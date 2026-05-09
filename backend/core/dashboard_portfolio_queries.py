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


def _rollup_view_norm(rollup_view: Optional[str]) -> str:
    return "prev" if (rollup_view or "").lower() == "prev" else "td"


def _chart_history_window_start(
    *,
    period: str,
    rollup_view: Optional[str],
    eastern: Any,
    now: datetime,
) -> datetime:
    """
    Start of account_balance / bankroll chart window in America/New_York.
    ``td`` = calendar-aligned (week/month/year); ``prev`` = rolling lookback from ``now``.
    """
    today: Date = now.date()
    rv = _rollup_view_norm(rollup_view)

    if period == "1d":
        if rv == "prev":
            return now - timedelta(hours=24)
        return now.replace(hour=5, minute=0, second=0, microsecond=0)

    if rv == "prev":
        if period == "1w":
            return now - timedelta(weeks=1)
        if period == "1m":
            return now - timedelta(days=30)
        if period == "1y":
            return now - timedelta(days=365)
        return datetime(2020, 1, 1, tzinfo=eastern)

    if period == "1w":
        days_since_sunday = (today.weekday() + 1) % 7
        sunday_d = today - timedelta(days=days_since_sunday)
        return datetime.combine(sunday_d, datetime.min.time(), tzinfo=eastern)
    if period == "1m":
        month_first = today.replace(day=1)
        return datetime.combine(month_first, datetime.min.time(), tzinfo=eastern)
    if period == "1y":
        year_first = Date(today.year, 1, 1)
        return datetime.combine(year_first, datetime.min.time(), tzinfo=eastern)
    return datetime(2020, 1, 1, tzinfo=eastern)


def _pnl_td_calendar_date_bounds(period: str, now: datetime) -> Tuple[Date, Date]:
    """Inclusive trade ``date`` bounds (Eastern calendar) for TD mode."""
    today: Date = now.date()
    if period == "1d":
        return (today, today)
    if period == "1w":
        days_since_sunday = (today.weekday() + 1) % 7
        sunday_d = today - timedelta(days=days_since_sunday)
        return (sunday_d, today)
    if period == "1m":
        return (today.replace(day=1), today)
    if period == "1y":
        return (Date(today.year, 1, 1), today)
    return (Date(2020, 1, 1), today)


def _pnl_prev_window_start(period: str, now: datetime) -> datetime:
    if period == "1d":
        return now - timedelta(hours=24)
    if period == "1w":
        return now - timedelta(weeks=1)
    if period == "1m":
        return now - timedelta(days=30)
    if period == "1y":
        return now - timedelta(days=365)
    return datetime(2020, 1, 1, tzinfo=now.tzinfo)


def portfolio_history_payload(
    *,
    period: str,
    trading_mode: Optional[str],
    rollup_view: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Dict[str, Any]:
    own_conn = False
    try:
        slot = resolved_tenant_user_no_for_app()
        if conn is None:
            conn = get_postgresql_connection()
            own_conn = bool(conn)
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
            if _rollup_view_norm(rollup_view) == "prev":
                window_start = now - timedelta(hours=24)
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
                        (window_start,),
                    )
                    last_before = cursor.fetchone()

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
                        (window_start,),
                    )
                    results = cursor.fetchall()

                if last_before:
                    results = [last_before] + list(results)
            else:
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
            start_time = _chart_history_window_start(
                period=period, rollup_view=rollup_view, eastern=eastern, now=now
            )

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
            "rollup_view": _rollup_view_norm(rollup_view),
            "count": len(data),
            "data": data,
            "trading_mode": _trading_mode_label(trading_mode),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def bankroll_history_payload(
    *,
    period: str,
    trading_mode: Optional[str],
    rollup_view: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Dict[str, Any]:
    own_conn = False
    try:
        if conn is None:
            conn = get_postgresql_connection()
            own_conn = bool(conn)
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
            if _rollup_view_norm(rollup_view) == "prev":
                window_start = now - timedelta(hours=24)
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
                        (window_start,),
                    )
                    last_before = cursor.fetchone()

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
                        (window_start,),
                    )
                    results = cursor.fetchall()

                if last_before:
                    results = [last_before] + list(results)
            else:
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
            start_time = _chart_history_window_start(
                period=period, rollup_view=rollup_view, eastern=eastern, now=now
            )

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
            "rollup_view": _rollup_view_norm(rollup_view),
            "count": len(data),
            "data": data,
            "trading_mode": _trading_mode_label(trading_mode),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def pnl_history_payload(
    *,
    period: str,
    trading_mode: Optional[str],
    rollup_view: Optional[str] = None,
    conn: Optional[Any] = None,
) -> Dict[str, Any]:
    from zoneinfo import ZoneInfo

    own_conn = False
    try:
        slot = resolved_tenant_user_no_for_app()
        if conn is None:
            conn = get_postgresql_connection()
            own_conn = bool(conn)
        if not conn:
            return {"status": "error", "message": "No DB connection"}

        eastern = ZoneInfo("America/New_York")
        now_e = datetime.now(eastern)
        trade_mode_clause = _performance_panel_trade_mode_clause(trading_mode)
        rv = _rollup_view_norm(rollup_view)

        with conn.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'America/New_York'")
            if not fetch_master_trades_column_names(cursor, slot):
                rows = []
            else:
                union_sql, _ = union_trades_with_archives_select(cursor, slot)
                if rv == "td":
                    lo, hi = _pnl_td_calendar_date_bounds(period, now_e)
                    q = (
                        """
                    SELECT COALESCE(
                        CASE WHEN closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE NULL END,
                        created_at
                    ) AS ts, pnl
                    FROM ("""
                        + union_sql
                        + """) AS trades_all
                    WHERE (trades_all.test_filter IS NULL OR trades_all.test_filter = FALSE)
                    """
                        + trade_mode_clause
                        + """
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND (trades_all."date"::date) >= %s::date
                      AND (trades_all."date"::date) <= %s::date
                    ORDER BY ts ASC
                """
                    )
                    cursor.execute(q, (lo, hi))
                else:
                    start_dt = _pnl_prev_window_start(period, now_e)
                    q = (
                        """
                    SELECT COALESCE(
                        CASE WHEN closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE NULL END,
                        created_at
                    ) AS ts, pnl
                    FROM ("""
                        + union_sql
                        + """) AS trades_all
                    WHERE (trades_all.test_filter IS NULL OR trades_all.test_filter = FALSE)
                    """
                        + trade_mode_clause
                        + """
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND COALESCE(
                        CASE WHEN closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE NULL END,
                        created_at::timestamptz
                      ) >= %s
                    ORDER BY ts ASC
                """
                    )
                    cursor.execute(q, (start_dt,))
                rows = cursor.fetchall()

        if rv == "td":
            lo, _hi = _pnl_td_calendar_date_bounds(period, now_e)
            anchor_ts = datetime.combine(lo, datetime.min.time(), tzinfo=eastern).isoformat()
        else:
            anchor_ts = _pnl_prev_window_start(period, now_e).isoformat()

        data: List[Dict[str, Any]] = []
        cumulative = 0.0
        data.append({"timestamp": anchor_ts, "pnl": 0.0})
        for ts, pnl in rows:
            pnl_val = float(pnl) if pnl is not None else 0.0
            cumulative += pnl_val
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            data.append({"timestamp": ts_str, "pnl": round(cumulative, 2)})

        return {
            "status": "ok",
            "period": period,
            "rollup_view": rv,
            "count": len(data),
            "data": data,
            "total_pnl": round(cumulative, 2),
            "trading_mode": _trading_mode_label(trading_mode),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def dashboard_history_bundle_payload(
    *, period: str, trading_mode: Optional[str], rollup_view: Optional[str] = None
) -> Dict[str, Any]:
    """
    Portfolio + bankroll + PnL in one response using a **single** PostgreSQL connection
    to avoid triple connect overhead on hot dashboard loads.
    """
    err = {"status": "error", "message": "No DB connection"}
    conn = get_postgresql_connection()
    if not conn:
        return {
            "status": "ok",
            "period": period,
            "portfolio": err,
            "bankroll": err,
            "pnl": err,
        }
    try:
        portfolio = portfolio_history_payload(
            period=period, trading_mode=trading_mode, rollup_view=rollup_view, conn=conn
        )
        bankroll = bankroll_history_payload(
            period=period, trading_mode=trading_mode, rollup_view=rollup_view, conn=conn
        )
        pnl = pnl_history_payload(
            period=period, trading_mode=trading_mode, rollup_view=rollup_view, conn=conn
        )
        return {
            "status": "ok",
            "period": period,
            "portfolio": portfolio,
            "bankroll": bankroll,
            "pnl": pnl,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def performance_previous_period_pnls(
    *,
    cursor: Any,
    slot: str,
    trading_mode: Optional[str],
) -> Dict[str, float]:
    """
    Calendar **previous** period realized PnL only (``day`` / ``week`` / ``month`` / ``year`` keys).
    Same date bounds and filters as :func:`performance_realized_payload` ``prev_pnl``.
    """
    from zoneinfo import ZoneInfo

    cursor.execute("SET TIME ZONE 'America/New_York'")
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

    out: Dict[str, float] = {}
    has_trades = bool(fetch_master_trades_column_names(cursor, slot))
    union_sql = None
    if has_trades:
        union_sql, _ = union_trades_with_archives_select(cursor, slot)
    for key, _d_lo, _d_hi, prev_lo, prev_hi in periods_spec:
        if not union_sql:
            out[key] = 0.0
            continue
        q_prev = prev_sql.replace("{union}", union_sql)
        cursor.execute(
            q_prev,
            (prev_lo.isoformat(), prev_hi.isoformat()),
        )
        prev_row = cursor.fetchone()
        out[key] = float(prev_row[0]) if prev_row and prev_row[0] is not None else 0.0
    return out


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
