"""
Server-side summary + analysis aggregates for trade history (full filtered set, not paginated).

Filter semantics mirror desktop trade_history applyFilters (date bounds applied separately via min/max).
"""

from __future__ import annotations

import re
from datetime import date as DateOnly
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

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


# Clock token only (1–12 + optional :mm + am/pm). Avoid ``(\d+)pm`` which matches strike digits (e.g. 45pm → 57:00).
_HOURLY_CONTRACT_CLOCK = re.compile(
    r"(?P<h>1[0-2]|0?[1-9])(?::(?P<m>[0-5][0-9]))?\s*(?P<ap>am|pm)\b",
    re.IGNORECASE,
)
# Kalshi-style suffix …-T1230 (HHMM ET) or …-T19 (hour only)
_HOURLY_KALSHI_HHMM = re.compile(r"T(?P<hhmm>[01][0-9][0-5][0-9])\b")
_HOURLY_KALSHI_HH = re.compile(r"T(?P<hh>(?:0[1-9]|1[0-9]|2[0-3]))\b")


_ET = ZoneInfo("America/New_York")
# ``closed_at`` may be full timestamp or time-only (combine with ``date``).
_TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$")


def _trade_row_date_iso(date_s: Any) -> str:
    """
    Normalize trade row ``date`` to ``YYYY-MM-DD`` for hourly bucketing.

    PostgreSQL often returns ``date`` as ``datetime.date`` or ``datetime``; stringifying
    the latter can yield ``YYYY-MM-DD HH:MM:SS+00:00``, which breaks ``YYYY-MM-DD``
    matching and prevents time-only ``closed_at`` from pairing with the row date.
    """
    if date_s is None:
        return ""
    typ = type(date_s)
    if typ is datetime:
        if date_s.tzinfo is not None:
            return date_s.astimezone(_ET).date().isoformat()
        return date_s.date().isoformat()
    if typ is DateOnly:
        return date_s.isoformat()
    s = str(date_s).strip()
    if len(s) >= 10 and _ISO.match(s[:10]):
        return s[:10]
    return ""


def _parse_datetime_flexible(raw: str, date_fallback: str) -> Optional[datetime]:
    """Parse DB/API datetime string; if time-only, combine with ``date_fallback`` (YYYY-MM-DD)."""
    s = raw.strip()
    if not s:
        return None
    if _ISO.match(date_fallback) and _TIME_ONLY.match(s.split(".")[0]):
        tpart = s.split(".")[0]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(f"{date_fallback} {tpart}", fmt)
            except ValueError:
                continue
        return None
    iso = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(s[:32], fmt)
        except ValueError:
            continue
    return None


def _trade_execution_datetime_et(date_iso: str, time_s: Any) -> Optional[datetime]:
    """Trade execution instant ET from calendar ``date`` + row ``time`` (what the UI shows as Time)."""
    d = (date_iso or "").strip()
    if not _ISO.match(d) or time_s is None or not str(time_s).strip():
        return None
    tpart = str(time_s).strip().split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{d} {tpart}", fmt).replace(tzinfo=_ET)
        except ValueError:
            continue
    return None


def _trade_closed_at_datetime_et(date_iso: str, closed_at: Any) -> Optional[datetime]:
    """Best-effort ET instant from ``closed_at`` only (timestamp or time-of-day + row date)."""
    d = (date_iso or "").strip()
    if not _ISO.match(d):
        d = ""

    if isinstance(closed_at, datetime):
        dt = closed_at
        if dt.tzinfo is None:
            return dt.replace(tzinfo=_ET)
        return dt.astimezone(_ET)

    if closed_at is not None and str(closed_at).strip():
        raw = str(closed_at).strip()
        dt = _parse_datetime_flexible(raw, d) if d else _parse_datetime_flexible(raw, "")
        if dt is None and d:
            dt = _parse_datetime_flexible(raw, "")
        if dt is not None:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=_ET)
            return dt.astimezone(_ET)
    return None


def _et_ceil_hour_bucket_key(dt: datetime) -> str:
    """
    Hourly chart ``period`` = **hour the market cycle closes at** (ET), derived from a
    wall-clock trade timestamp:

    - 12:54 → ``… 13:00`` (same as grouping 12:xx trades under the 13:00 column)
    - 13:09 → ``… 14:00``
    - Exactly ``…:00:00`` maps to that hour (13:00:00 → ``… 13:00``).
    """
    if dt.tzinfo is None:
        zdt = dt.replace(tzinfo=_ET)
    else:
        zdt = dt.astimezone(_ET)
    if zdt.minute != 0 or zdt.second != 0 or zdt.microsecond != 0:
        base = zdt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        base = zdt.replace(minute=0, second=0, microsecond=0)
    return f"{base:%Y-%m-%d} {base.hour:02d}:00"


def _hourly_insights_bucket_key(
    date_s: Any,
    contract: str,
    closed_at: Any,
    time_s: Any,
) -> Optional[str]:
    """
    Hourly analysis period ``YYYY-MM-DD HH:00`` (ET).

    The chart column is the **cycle close hour** (Kalshi-style): trades with execution
    time in 12:xx belong under ``… 13:00``, trades in 13:xx under ``… 14:00``. We therefore
    prefer **``date`` + ``time``** (execution), apply ceil-to-hour, then fall back to
    ``closed_at`` if time is missing, then contract parsing.
    """
    ds = _trade_row_date_iso(date_s)
    dt = _trade_execution_datetime_et(ds, time_s)
    if dt is None:
        dt = _trade_closed_at_datetime_et(ds, closed_at)
    if dt is not None:
        key = _et_ceil_hour_bucket_key(dt)
        if _hourly_period_output_ok(key):
            return key
    return _hourly_period_key(ds, str(contract or ""))


def _hourly_period_key(date_str: str, contract: str) -> Optional[str]:
    """Wall-clock ET hour bucket ``YYYY-MM-DD HH:00`` from trade ``date`` + human ``contract`` (or ticker)."""
    if not date_str or not contract:
        return None
    c = str(contract).strip()
    if not c:
        return None

    # Raw Kalshi ticker segment (e.g. KXBTCD-…-T1930)
    km = _HOURLY_KALSHI_HHMM.search(c)
    if km:
        hhmm = int(km.group("hhmm"))
        h24, _minute = hhmm // 100, hhmm % 100
        if 0 <= h24 <= 23:
            return f"{date_str} {h24:02d}:00"
    km2 = _HOURLY_KALSHI_HH.search(c)
    if km2:
        h24 = int(km2.group("hh"))
        if 0 <= h24 <= 23:
            return f"{date_str} {h24:02d}:00"

    last = None
    for m in _HOURLY_CONTRACT_CLOCK.finditer(c):
        last = m
    if not last:
        return None
    h12 = int(last.group("h"))
    minute = int(last.group("m") or 0)
    if not (1 <= h12 <= 12 and 0 <= minute <= 59):
        return None
    ap = (last.group("ap") or "").lower()
    if ap == "am":
        h24 = 0 if h12 == 12 else h12
    elif ap == "pm":
        h24 = 12 if h12 == 12 else h12 + 12
    else:
        return None
    if not (0 <= h24 <= 23):
        return None
    return f"{date_str} {h24:02d}:00"


def _hourly_period_output_ok(key: str) -> bool:
    """Reject malformed bucket keys (should not happen with ``_hourly_period_key``)."""
    parts = str(key).strip().split()
    if len(parts) != 2:
        return False
    if not _ISO.match(parts[0]):
        return False
    try:
        hh = int(parts[1].split(":")[0])
    except ValueError:
        return False
    return 0 <= hh <= 23


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
            SELECT t.date, t.contract, t.pnl, t.ret_pct, t.closed_at, t."time"
            FROM ({union_sql}) AS t
            {where_sql}
            """,
            tuple(filt_params),
        )
        groups: Dict[str, List[Tuple[Any, Any]]] = {}
        for date_s, contract, pnl, ret_pct, closed_at, time_s in cursor.fetchall():
            key = _hourly_insights_bucket_key(
                date_s,
                str(contract or ""),
                closed_at,
                time_s,
            )
            if not key:
                continue
            groups.setdefault(key, []).append(
                (float(pnl or 0), float(ret_pct or 0))
            )
        for period in sorted(groups.keys()):
            if not _hourly_period_output_ok(period):
                continue
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
