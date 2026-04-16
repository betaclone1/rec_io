"""
Server-side summary + analysis aggregates for trade history (full filtered set, not paginated).

Filter semantics mirror desktop trade_history applyFilters (date bounds applied separately via min/max).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException

from backend.util.trade_log_archivist import (
    fetch_master_trades_column_names,
    union_trades_with_archives_select,
)

_VALID_INTERVALS = frozenset({"annual", "monthly", "weekly", "daily", "hourly"})
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_iso(label: str, v: Optional[str]) -> None:
    if v is None or v == "":
        return
    if not _ISO.match(v.strip()):
        raise HTTPException(status_code=400, detail=f"Invalid {label}; use YYYY-MM-DD")


def build_trade_history_filter_sql(body: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Returns SQL fragment ``AND ...`` clauses (no leading WHERE) and param list."""
    clauses: List[str] = []
    params: List[Any] = []

    min_d = body.get("min_date")
    max_d = body.get("max_date")
    _validate_iso("min_date", min_d if isinstance(min_d, str) else None)
    _validate_iso("max_date", max_d if isinstance(max_d, str) else None)
    if isinstance(min_d, str) and min_d.strip():
        clauses.append("t.date >= %s")
        params.append(min_d.strip())
    if isinstance(max_d, str) and max_d.strip():
        clauses.append("t.date <= %s")
        params.append(max_d.strip())

    if not body.get("include_test_trades", False):
        clauses.append("(t.test_filter IS NOT TRUE)")

    show_win = bool(body.get("show_win", True))
    show_loss = bool(body.get("show_loss", True))
    if not show_win and not show_loss:
        clauses.append("1=0")
    elif show_win and show_loss:
        pass
    elif show_win:
        clauses.append(
            "(NOT (UPPER(TRIM(COALESCE(t.win_loss, ''))) IN ('L', 'LOSS')))"
        )
    elif show_loss:
        clauses.append(
            "(NOT (UPPER(TRIM(COALESCE(t.win_loss, ''))) IN ('W', 'WIN')))"
        )

    show_live = bool(body.get("show_live", True))
    show_paper = bool(body.get("show_paper", False))
    if not show_live and not show_paper:
        clauses.append("1=0")
    elif show_live and show_paper:
        pass
    elif show_live:
        clauses.append("(COALESCE(t.paper_trade, FALSE) = FALSE)")
    else:
        clauses.append("(COALESCE(t.paper_trade, FALSE) = TRUE)")

    symbols = body.get("symbols") or []
    if symbols:
        clauses.append("t.symbol = ANY(%s)")
        params.append(list(symbols))

    strategies = body.get("strategies") or []
    if strategies:
        clauses.append("t.trade_strategy = ANY(%s)")
        params.append(list(strategies))

    monitors = body.get("monitors") or []
    if monitors:
        clauses.append("LOWER(TRIM(COALESCE(t.monitor, ''))) = ANY(%s)")
        params.append([str(m).lower().strip() for m in monitors])

    dows = body.get("days_of_week")
    if dows is not None:
        if len(dows) == 0:
            clauses.append("1=0")
        elif len(dows) < 7:
            clauses.append("(EXTRACT(DOW FROM t.date::date))::int = ANY(%s)")
            params.append([int(x) for x in dows])

    if not clauses:
        return "", []
    return " AND ".join(clauses), params


def _hourly_period_key(date_str: str, contract: str) -> Optional[str]:
    if not date_str or not contract:
        return None
    c = contract.lower()
    m = re.search(r"(\d+)\s*am", c)
    if m:
        h = int(m.group(1))
        h24 = 0 if h == 12 else h
        return f"{date_str} {h24:02d}:00"
    m = re.search(r"(\d+)\s*pm", c)
    if m:
        h = int(m.group(1))
        h24 = 12 if h == 12 else h + 12
        return f"{date_str} {h24:02d}:00"
    return None


def _period_expr_sql(interval: str) -> str:
    if interval == "annual":
        return "to_char(t.date::date, 'YYYY')"
    if interval == "monthly":
        return "to_char(t.date::date, 'YYYY-MM')"
    if interval == "weekly":
        return (
            "to_char("
            "t.date::date - (EXTRACT(DOW FROM t.date::date))::integer * interval '1 day',"
            " 'YYYY-MM-DD'"
            ")"
        )
    if interval == "daily":
        return "t.date"
    raise ValueError(interval)


def run_trade_history_insights(
    cursor: Any,
    *,
    user_slot: str,
    body: Dict[str, Any],
) -> Dict[str, Any]:
    interval = str(body.get("analysis_interval") or "daily").strip()
    if interval not in _VALID_INTERVALS:
        raise HTTPException(status_code=400, detail="Invalid analysis_interval")

    if not fetch_master_trades_column_names(cursor, user_slot):
        return {
            "summary": {
                "trade_count": 0,
                "avg_prob": 0.0,
                "win_percentage": 0.0,
                "avg_buy": 0.0,
                "avg_diff": 0.0,
                "sum_ret_pct": 0.0,
                "total_pnl": 0.0,
            },
            "analysis_interval": interval,
            "period_data": [],
            "by_monitor": [],
        }

    union_sql, _ = union_trades_with_archives_select(cursor, user_slot)
    filt_sql, filt_params = build_trade_history_filter_sql(body)
    where_sql = f" WHERE {filt_sql}" if filt_sql else ""

    # --- Summary (single row) ---
    cursor.execute(
        f"""
        SELECT
          COUNT(*)::bigint AS n,
          AVG(t.prob) FILTER (WHERE t.prob IS NOT NULL) AS avg_prob,
          SUM(
            CASE
              WHEN UPPER(TRIM(COALESCE(t.win_loss, ''))) IN ('W', 'WIN') THEN 1
              ELSE 0
            END
          ) AS wins,
          SUM(
            CASE
              WHEN UPPER(TRIM(COALESCE(t.win_loss, ''))) IN ('W', 'WIN', 'L', 'LOSS')
              THEN 1 ELSE 0
            END
          ) AS wl_n,
          AVG(
            CASE
              WHEN t.diff ~ '^[+-]?[0-9]+(\\.?[0-9]*)?$' THEN t.diff::double precision
              ELSE NULL
            END
          ) AS avg_diff,
          AVG(t.buy_price) FILTER (WHERE t.buy_price IS NOT NULL) AS avg_buy,
          COALESCE(SUM(t.ret_pct), 0)::double precision AS sum_ret_pct,
          COALESCE(SUM(t.pnl), 0)::double precision AS total_pnl
        FROM ({union_sql}) AS t
        {where_sql}
        """,
        tuple(filt_params),
    )
    srow = cursor.fetchone()
    n = int(srow[0] or 0)
    avg_prob = float(srow[1] or 0.0)
    wins = int(srow[2] or 0)
    wl_n = int(srow[3] or 0)
    win_pct = (100.0 * wins / wl_n) if wl_n > 0 else 0.0
    avg_diff = float(srow[4] or 0.0)
    avg_buy = float(srow[5] or 0.0)
    sum_ret_pct = float(srow[6] or 0.0)
    total_pnl = float(srow[7] or 0.0)

    summary = {
        "trade_count": n,
        "avg_prob": avg_prob,
        "win_percentage": win_pct,
        "avg_buy": avg_buy,
        "avg_diff": avg_diff,
        "sum_ret_pct": sum_ret_pct,
        "total_pnl": total_pnl,
    }

    # --- Per-monitor aggregates (full filtered set; same formulas as summary row) ---
    by_monitor: List[Dict[str, Any]] = []
    if n > 0:
        if filt_sql:
            mg_where = (
                f" WHERE {filt_sql} AND LOWER(TRIM(COALESCE(t.monitor, ''))) <> ''"
            )
            mg_params: Tuple[Any, ...] = tuple(filt_params)
        else:
            mg_where = " WHERE LOWER(TRIM(COALESCE(t.monitor, ''))) <> ''"
            mg_params = tuple()
        cursor.execute(
            f"""
            SELECT
              LOWER(TRIM(COALESCE(t.monitor, ''))) AS mnorm,
              MAX(t.monitor) AS monitor_label,
              COUNT(*)::bigint AS n_m,
              AVG(t.prob) FILTER (WHERE t.prob IS NOT NULL) AS avg_prob_m,
              SUM(
                CASE
                  WHEN UPPER(TRIM(COALESCE(t.win_loss, ''))) IN ('W', 'WIN') THEN 1
                  ELSE 0
                END
              ) AS wins_m,
              SUM(
                CASE
                  WHEN UPPER(TRIM(COALESCE(t.win_loss, ''))) IN ('W', 'WIN', 'L', 'LOSS')
                  THEN 1 ELSE 0
                END
              ) AS wl_n_m,
              AVG(
                CASE
                  WHEN t.diff ~ '^[+-]?[0-9]+(\\.?[0-9]*)?$' THEN t.diff::double precision
                  ELSE NULL
                END
              ) AS avg_diff_m,
              AVG(t.buy_price) FILTER (WHERE t.buy_price IS NOT NULL) AS avg_buy_m,
              COALESCE(SUM(t.ret_pct), 0)::double precision AS sum_ret_pct_m,
              COALESCE(SUM(t.pnl), 0)::double precision AS total_pnl_m
            FROM ({union_sql}) AS t
            {mg_where}
            GROUP BY 1
            ORDER BY sum_ret_pct_m DESC NULLS LAST
            """,
            mg_params,
        )
        for prow in cursor.fetchall():
            _mnorm, label, n_m, ap_m, wins_m, wl_n_m, ad_m, ab_m, sr_m, tp_m = prow
            wl_d = int(wl_n_m or 0)
            w_pct_m = (100.0 * int(wins_m or 0) / wl_d) if wl_d > 0 else 0.0
            by_monitor.append(
                {
                    "monitor": str(label or _mnorm or "").strip(),
                    "trade_count": int(n_m or 0),
                    "avg_prob": float(ap_m or 0.0),
                    "win_percentage": float(w_pct_m),
                    "avg_buy": float(ab_m or 0.0),
                    "avg_diff": float(ad_m or 0.0),
                    "sum_ret_pct": float(sr_m or 0.0),
                    "total_pnl": float(tp_m or 0.0),
                }
            )

    # --- Period breakdown ---
    period_data: List[Dict[str, Any]] = []
    if n == 0:
        return {
            "summary": summary,
            "analysis_interval": interval,
            "period_data": period_data,
            "by_monitor": by_monitor,
        }

    if interval == "hourly":
        cursor.execute(
            f"""
            SELECT t.date, t.contract, t.pnl, t.ret_pct
            FROM ({union_sql}) AS t
            {where_sql}
            """,
            tuple(filt_params),
        )
        groups: Dict[str, List[Tuple[Any, Any]]] = {}
        for date_s, contract, pnl, ret_pct in cursor.fetchall():
            key = _hourly_period_key(str(date_s or ""), str(contract or ""))
            if not key:
                continue
            groups.setdefault(key, []).append(
                (float(pnl or 0), float(ret_pct or 0))
            )
        for period in sorted(groups.keys()):
            rows = groups[period]
            period_data.append(
                {
                    "period": period,
                    "trades": len(rows),
                    "pnl": sum(p for p, _ in rows),
                    "retPct": sum(r for _, r in rows),
                }
            )
    else:
        pexpr = _period_expr_sql(interval)
        cursor.execute(
            f"""
            SELECT
              ({pexpr}) AS period,
              COUNT(*)::bigint,
              COALESCE(SUM(t.pnl), 0)::double precision,
              COALESCE(SUM(t.ret_pct), 0)::double precision
            FROM ({union_sql}) AS t
            {where_sql}
            GROUP BY 1
            ORDER BY 1
            """,
            tuple(filt_params),
        )
        for prow in cursor.fetchall():
            period_data.append(
                {
                    "period": str(prow[0]),
                    "trades": int(prow[1] or 0),
                    "pnl": float(prow[2] or 0),
                    "retPct": float(prow[3] or 0),
                }
            )

    return {
        "summary": summary,
        "analysis_interval": interval,
        "period_data": period_data,
        "by_monitor": by_monitor,
    }
