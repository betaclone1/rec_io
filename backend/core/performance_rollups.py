"""
Pre-aggregated performance rollups in users_<slot>.performance_{total,monitors}_<slot>.

Recomputed from closed/settled trades (union with archives). Trade-close path schedules a
debounced full recompute via monitor_manager; startup and backfills call recompute directly.
Calendar buckets (TD) use trade ``date`` in America/New_York; rolling (PREV) uses parsed ``closed_at``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, timedelta
from typing import Any, DefaultDict, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from psycopg2 import sql as psql

from backend.core.config.database import get_postgresql_connection
from backend.trading_mode import _norm_slot, trades_table_fqn
from backend.util.trade_log_archivist import (
    fetch_master_trades_column_names,
    union_trades_with_archives_select,
)

_log = logging.getLogger(__name__)
_EASTERN = ZoneInfo("America/New_York")
_CLOSE_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Hot path (trade close): coalesce many closes into one recompute + one snapshot publish.
_rollup_debounce_lock = threading.Lock()
_rollup_debounce_state: Dict[str, Dict[str, Any]] = {}

# Rollup column names: ``{window}_{td|prev}_{metric}_{live|paper|test}`` (e.g. ``1d_prev_pnl_paper``).
WINDOWS = ("1d", "1w", "1m", "1y", "all")
MODES = ("live", "paper", "test")
KINDS = ("td", "prev")
METRICS = ("pnl", "ret_pct", "fees", "trades_n", "win_rate")


@dataclass
class _Bucket:
    pnl: float = 0.0
    ret_pct: float = 0.0
    fees: float = 0.0
    trades_n: int = 0
    wins: int = 0


def _empty_mon_buckets() -> DefaultDict[Tuple[str, str, str], _Bucket]:
    return defaultdict(_Bucket)


def _mode_for_row(paper_trade: Any, test_filter: Any) -> Optional[str]:
    """
    Bucket rows like performance_realized: test_filter rows never count as live/paper aggregates.
    Paper + test_filter → ``test`` mode column; paper without test → paper; non-paper without test → live.
    """
    pt = paper_trade is True or str(paper_trade).lower() in ("t", "true", "1")
    tf = test_filter is True or str(test_filter).lower() in ("t", "true", "1")
    if tf:
        return "test" if pt else None
    if not pt:
        return "live"
    return "paper"


def _parse_trade_date(d: Any, eastern: ZoneInfo) -> Optional[Date]:
    if d is None:
        return None
    if isinstance(d, Date):
        return d
    s = str(d).strip()[:10]
    try:
        return Date.fromisoformat(s)
    except ValueError:
        return None


def _parse_close_ts(closed_at: Any, trade_date: Optional[Date], eastern: ZoneInfo) -> Optional[datetime]:
    if closed_at and isinstance(closed_at, datetime):
        dt = closed_at
        if dt.tzinfo is None:
            return dt.replace(tzinfo=eastern)
        return dt.astimezone(eastern)
    if closed_at and isinstance(closed_at, str) and _CLOSE_AT_RE.match(closed_at.strip()):
        try:
            raw = closed_at.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=eastern)
            return dt.astimezone(eastern)
        except ValueError:
            pass
    if closed_at and isinstance(closed_at, str) and trade_date:
        s = closed_at.strip()
        # Legacy: trade_manager stored ``strftime("%H:%M:%S")`` only. Rolling PREV used
        # trade-date midnight and matched calendar TD; combine session date + wall time.
        if re.match(r"^\d{1,2}:\d{2}:\d{2}$", s):
            try:
                hh, mm, ss = (int(x) for x in s.split(":"))
                tt = datetime.min.time().replace(
                    hour=min(hh, 23), minute=min(mm, 59), second=min(ss, 59)
                )
                return datetime.combine(trade_date, tt, tzinfo=eastern)
            except ValueError:
                pass
    if trade_date:
        return datetime.combine(trade_date, datetime.min.time(), tzinfo=eastern)
    return None


def _calendar_bounds(now: datetime, today: Date) -> Dict[str, Tuple[Optional[Date], Optional[Date]]]:
    days_since_sunday = (today.weekday() + 1) % 7
    sunday_d = today - timedelta(days=days_since_sunday)
    month_first = today.replace(day=1)
    year_first = Date(today.year, 1, 1)
    return {
        "1d": (today, today),
        "1w": (sunday_d, today),
        "1m": (month_first, today),
        "1y": (year_first, today),
        "all": (None, None),
    }


def _in_td_calendar(trade_d: Optional[Date], lo: Optional[Date], hi: Optional[Date]) -> bool:
    if trade_d is None:
        return False
    if lo is None and hi is None:
        return True
    if lo is not None and trade_d < lo:
        return False
    if hi is not None and trade_d > hi:
        return False
    return True


def _prev_cutoffs(now: datetime) -> Dict[str, Optional[datetime]]:
    return {
        "1d": now - timedelta(days=1),
        "1w": now - timedelta(days=7),
        "1m": now - timedelta(days=30),
        "1y": now - timedelta(days=365),
        "all": None,
    }


def _in_prev_rolling(close_ts: Optional[datetime], cutoff: Optional[datetime]) -> bool:
    if close_ts is None:
        return False
    if cutoff is None:
        return True
    return close_ts >= cutoff


def _add_to_bucket(b: _Bucket, pnl: float, ret_pct: float, fees: float, win_loss: Any) -> None:
    b.pnl += pnl
    b.ret_pct += ret_pct
    b.fees += fees
    b.trades_n += 1
    wl = (win_loss or "").strip().upper()
    if wl == "W":
        b.wins += 1


def _bucket_to_cols(
    buckets: DefaultDict[Tuple[str, str, str], _Bucket],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for win in WINDOWS:
        for kind in KINDS:
            for mode in MODES:
                b = buckets[(kind, win, mode)]
                n = b.trades_n
                wr = (b.wins / n) if n else 0.0
                prefix = f"{win}_{kind}_"
                out[prefix + "pnl_" + mode] = round(b.pnl, 8)
                out[prefix + "ret_pct_" + mode] = round(b.ret_pct, 6)
                out[prefix + "fees_" + mode] = round(b.fees, 8)
                out[prefix + "trades_n_" + mode] = int(n)
                out[prefix + "win_rate_" + mode] = round(wr, 6)
    return out


def _performance_table_names(slot: str) -> Tuple[str, str, str]:
    u = _norm_slot(slot)
    sch, _tbl = trades_table_fqn(u).split(".", 1)
    return sch, f"performance_total_{u}", f"performance_monitors_{u}"


def schedule_performance_rollup_recompute(slot: Optional[str] = None) -> None:
    """
    Debounced full recompute for a tenant (trailing edge + max-wait cap).

    Use from monitor_manager on trade close so bursts become a single DB scan + snapshot.
    Startup / backfills should call :func:`recompute_performance_rollups_for_slot` directly.
    """
    u = _norm_slot(slot or "")
    if not u:
        return

    debounce = float(os.getenv("PERFORMANCE_ROLLUP_RECOMPUTE_DEBOUNCE_SEC", "0.35"))
    debounce = max(0.05, min(debounce, 30.0))
    max_wait = float(os.getenv("PERFORMANCE_ROLLUP_RECOMPUTE_MAX_WAIT_SEC", "3.0"))
    max_wait = max(debounce, min(max_wait, 120.0))

    def fire() -> None:
        with _rollup_debounce_lock:
            st = _rollup_debounce_state.get(u)
            if st is not None:
                st["timer"] = None
                st["pending_since"] = None
        try:
            recompute_performance_rollups_for_slot(u)
        except Exception as e:
            _log.warning("debounced performance rollup recompute failed slot=%s: %s", u, e)

    now = time.monotonic()
    with _rollup_debounce_lock:
        st = _rollup_debounce_state.setdefault(
            u, {"timer": None, "pending_since": None}
        )
        if st["pending_since"] is None:
            st["pending_since"] = now
        elapsed = now - st["pending_since"]
        wait = debounce
        if elapsed + wait > max_wait:
            wait = max(0.05, max_wait - elapsed)
        old = st.get("timer")
        if old is not None:
            try:
                old.cancel()
            except Exception:
                pass
        t = threading.Timer(wait, fire)
        t.daemon = True
        st["timer"] = t
        t.start()


def recompute_performance_rollups_for_slot(slot: Optional[str] = None) -> Dict[str, Any]:
    """
    Full recompute for one tenant slot; UPSERT totals row (user_id = 1) and per-monitor rows.

    From the trade-close hot path, prefer :func:`schedule_performance_rollup_recompute` so work is debounced.
    """
    u = _norm_slot(slot or "")
    if not u:
        return {"status": "error", "message": "missing slot"}

    conn = get_postgresql_connection()
    if not conn:
        return {"status": "error", "message": "no db"}

    sch, tot_tbl, mon_tbl = _performance_table_names(u)
    tot_ident = psql.Identifier(sch, tot_tbl)
    mon_ident = psql.Identifier(sch, mon_tbl)

    try:
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'America/New_York'")
        now = datetime.now(_EASTERN)
        today = now.date()
        cal = _calendar_bounds(now, today)
        prev_cut = _prev_cutoffs(now)

        total_b: DefaultDict[Tuple[str, str, str], _Bucket] = defaultdict(_Bucket)
        per_mon: DefaultDict[str, DefaultDict[Tuple[str, str, str], _Bucket]] = defaultdict(_empty_mon_buckets)

        with conn.cursor() as cur:
            if not fetch_master_trades_column_names(cur, u):
                return {"status": "skipped", "message": "no trades table"}
            union_sql, _params = union_trades_with_archives_select(cur, u)
            cur.execute(
                f"""
                SELECT LOWER(TRIM(monitor)), paper_trade, test_filter,
                       COALESCE(pnl, 0)::float, COALESCE(ret_pct, 0)::float, COALESCE(fees, 0)::float,
                       win_loss, date, closed_at
                FROM ({union_sql}) AS trades_all
                WHERE LOWER(TRIM(status)) IN ('closed', 'settled')
                  AND pnl IS NOT NULL
                """
            )
            rows = cur.fetchall()

        for row in rows:
            mon_raw, paper_trade, test_filter, pnl, ret_pct, fees, win_loss, tdate, closed_at = row
            mode = _mode_for_row(paper_trade, test_filter)
            if mode is None:
                continue
            trade_d = _parse_trade_date(tdate, _EASTERN)
            close_ts = _parse_close_ts(closed_at, trade_d, _EASTERN)
            mon_key = (mon_raw or "").strip().lower()
            if not mon_key:
                continue

            for win in WINDOWS:
                lo_hi = cal[win]
                if _in_td_calendar(trade_d, lo_hi[0], lo_hi[1]):
                    _add_to_bucket(total_b[("td", win, mode)], pnl, ret_pct, fees, win_loss)
                    _add_to_bucket(per_mon[mon_key][("td", win, mode)], pnl, ret_pct, fees, win_loss)
                pc = prev_cut[win]
                if _in_prev_rolling(close_ts, pc):
                    _add_to_bucket(total_b[("prev", win, mode)], pnl, ret_pct, fees, win_loss)
                    _add_to_bucket(per_mon[mon_key][("prev", win, mode)], pnl, ret_pct, fees, win_loss)

        total_cols = _bucket_to_cols(total_b)
        col_names = list(total_cols.keys())
        values = [total_cols[k] for k in col_names]

        insert_cols = [psql.Identifier("user_id")] + [psql.Identifier(c) for c in col_names] + [
            psql.Identifier("updated_at")
        ]
        upd = psql.SQL(", ").join(
            [psql.SQL("{} = EXCLUDED.{}").format(psql.Identifier(c), psql.Identifier(c)) for c in col_names]
        )
        val_parts = [psql.SQL("1")] + [psql.Placeholder() for _ in col_names] + [psql.SQL("NOW()")]
        ins = psql.SQL(
            "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT (user_id) DO UPDATE SET updated_at = NOW(), {}"
        ).format(
            tot_ident,
            psql.SQL(", ").join(insert_cols),
            psql.SQL(", ").join(val_parts),
            upd,
        )

        with conn.cursor() as cur:
            cur.execute(ins, values)

            cur.execute(psql.SQL("DELETE FROM {}").format(mon_ident))
            for mkey, mbuckets in per_mon.items():
                if not any(b.trades_n > 0 for b in mbuckets.values()):
                    continue
                mcols = _bucket_to_cols(mbuckets)
                m_col_names = list(mcols.keys())
                m_vals = [mcols[k] for k in m_col_names]
                mic = [psql.Identifier("monitor")] + [psql.Identifier(c) for c in m_col_names] + [
                    psql.Identifier("updated_at")
                ]
                mon_val_parts = [psql.Placeholder()] + [psql.Placeholder() for _ in m_col_names] + [psql.SQL("NOW()")]
                mins = psql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    mon_ident,
                    psql.SQL(", ").join(mic),
                    psql.SQL(", ").join(mon_val_parts),
                )
                cur.execute(mins, [mkey] + m_vals)

        conn.commit()
        try:
            publish_performance_rollups_ws_snapshot(u)
        except Exception:
            pass
        return {"status": "ok", "slot": u, "trades_scanned": len(rows), "monitors": len(per_mon)}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"status": "error", "message": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _rollup_metric_aggregate(
    d: Dict[str, Any],
    kind: str,
    w: str,
    metric: str,
    trading_mode: Optional[str],
) -> float:
    """Match ``performance_realized`` filters: live vs live+paper (non-test); test-filter paper in ``test`` columns."""
    from backend.core.dashboard_portfolio_queries import use_paper_for_request

    key_live = f"{w}_{kind}_{metric}_live"
    key_paper = f"{w}_{kind}_{metric}_paper"
    if not use_paper_for_request(trading_mode):
        return float(d.get(key_live) or 0)
    if metric == "trades_n":
        return float(int(d.get(key_live) or 0) + int(d.get(key_paper) or 0))
    if metric == "win_rate":
        n_live = int(d.get(f"{w}_{kind}_trades_n_live") or 0)
        n_paper = int(d.get(f"{w}_{kind}_trades_n_paper") or 0)
        n = n_live + n_paper
        if n == 0:
            return 0.0
        wr_live = float(d.get(f"{w}_{kind}_win_rate_live") or 0)
        wr_paper = float(d.get(f"{w}_{kind}_win_rate_paper") or 0)
        return (wr_live * n_live + wr_paper * n_paper) / n
    return float(d.get(key_live) or 0) + float(d.get(key_paper) or 0)


def _periods_dict_from_total_row(
    d: Dict[str, Any],
    kind: str,
    trading_mode: Optional[str],
    prev_pnls: Dict[str, float],
) -> Dict[str, Any]:
    periods_spec = [("day", "1d"), ("week", "1w"), ("month", "1m"), ("year", "1y")]
    out: Dict[str, Any] = {}
    for label, w in periods_spec:
        pnl = _rollup_metric_aggregate(d, kind, w, "pnl", trading_mode)
        ret = _rollup_metric_aggregate(d, kind, w, "ret_pct", trading_mode)
        ret_b = _rollup_metric_aggregate(d, kind, w, "ret_pct", trading_mode)
        prev_pnl = float(prev_pnls.get(label) or 0.0)
        out[label] = {
            "pnl": round(pnl, 2),
            "ret_pct": round(ret, 2),
            "ret_pct_base": round(ret_b, 2),
            "prev_pnl": round(prev_pnl, 2),
        }
    return out


def performance_rollups_read_payload_for_slot(
    slot: str,
    *,
    trading_mode: Optional[str],
    rollup_view: str = "td",
) -> Dict[str, Any]:
    """
    Same as :func:`performance_rollups_read_payload` but for an explicit tenant slot (writer / WS fanout).
    """
    from backend.core.dashboard_portfolio_queries import (
        performance_previous_period_pnls,
        use_paper_for_request,
    )

    u = _norm_slot(slot or "")
    if not u:
        return {"status": "error", "message": "missing slot"}

    kind = "prev" if (rollup_view or "").lower() == "prev" else "td"
    conn = get_postgresql_connection()
    if not conn:
        return {"status": "error", "message": "No DB connection"}

    sch, tot_tbl, _mon = _performance_table_names(u)
    mode_lbl = "paper" if use_paper_for_request(trading_mode) else "live"

    try:
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'America/New_York'")
            cur.execute(
                psql.SQL("SELECT * FROM {} WHERE user_id = 1").format(
                    psql.Identifier(sch, tot_tbl)
                )
            )
            colnames = [d[0] for d in cur.description] if cur.description else []
            row = cur.fetchone()
            if not row:
                return {
                    "status": "ok",
                    "source": "rollups",
                    "rollup_view": kind,
                    "periods": {},
                    "trading_mode": mode_lbl,
                }

            d = dict(zip(colnames, row))
            prev_pnls = performance_previous_period_pnls(
                cursor=cur, slot=u, trading_mode=trading_mode
            )

        periods = _periods_dict_from_total_row(d, kind, trading_mode, prev_pnls)
        return {
            "status": "ok",
            "source": "rollups",
            "rollup_view": kind,
            "periods": periods,
            "trading_mode": mode_lbl,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def performance_rollups_read_payload(
    *,
    trading_mode: Optional[str],
    rollup_view: str = "td",
) -> Dict[str, Any]:
    """
    Read persisted rollups and shape like ``performance_realized_payload`` ``periods``.
    ``rollup_view``: ``td`` (calendar buckets on trade ``date``) or ``prev`` (rolling on ``closed_at``).
    ``prev_pnl`` uses the same **calendar previous period** sums as the realized endpoint (not rolling cross-compare).
    """
    from backend.core.tenant_context import resolved_tenant_user_no_for_app

    slot = resolved_tenant_user_no_for_app()
    if not slot:
        return {"status": "error", "message": "missing tenant"}
    return performance_rollups_read_payload_for_slot(
        slot,
        trading_mode=trading_mode,
        rollup_view=rollup_view,
    )


def _dashboard_tile_aggregate_all_modes(rd: Dict[str, Any], prefix: str) -> Tuple[float, int, float, float]:
    """
    Dashboard monitor tiles: live + paper + test combined.
    ``ret_pct_*`` columns store **sums** of per-trade ret_pct (see rollup buckets); combined ret is the sum
    of those sums. Win rate combines modes by trade count.
    """
    n_live = int(rd.get(f"{prefix}trades_n_live") or 0)
    n_paper = int(rd.get(f"{prefix}trades_n_paper") or 0)
    n_test = int(rd.get(f"{prefix}trades_n_test") or 0)
    trades_n = n_live + n_paper + n_test
    pnl = (
        float(rd.get(f"{prefix}pnl_live") or 0)
        + float(rd.get(f"{prefix}pnl_paper") or 0)
        + float(rd.get(f"{prefix}pnl_test") or 0)
    )
    ret_sum = (
        float(rd.get(f"{prefix}ret_pct_live") or 0)
        + float(rd.get(f"{prefix}ret_pct_paper") or 0)
        + float(rd.get(f"{prefix}ret_pct_test") or 0)
    )
    if trades_n == 0:
        return pnl, 0, 0.0, ret_sum
    wr_live = float(rd.get(f"{prefix}win_rate_live") or 0)
    wr_paper = float(rd.get(f"{prefix}win_rate_paper") or 0)
    wr_test = float(rd.get(f"{prefix}win_rate_test") or 0)
    wr = (wr_live * n_live + wr_paper * n_paper + wr_test * n_test) / trades_n
    return pnl, trades_n, wr, ret_sum


def _fetch_performance_monitor_join_rows(cur: Any, slot: str) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    u = _norm_slot(slot)
    sch, _tot, mon_tbl = _performance_table_names(u)
    ml_tbl = f"monitor_list_{u}"
    cur.execute(
        psql.SQL(
            """
            SELECT ml.id AS ml_id, pm.*
            FROM {pm} pm
            INNER JOIN {ml} ml
              ON LOWER(TRIM(BOTH FROM pm.monitor::text))
               = LOWER('mon_' || {slot} || '_' || ml.id::text)
            """
        ).format(
            pm=psql.Identifier(sch, mon_tbl),
            ml=psql.Identifier(sch, ml_tbl),
            slot=psql.Literal(u),
        ),
    )
    colnames = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall() or []
    return colnames, rows


def _monitor_tiles_numeric_payloads_from_join(
    colnames: List[str],
    rows: List[Tuple[Any, ...]],
    u: str,
    window: str,
    kind: str,
) -> List[Dict[str, Any]]:
    """Per-monitor numeric tile metrics (live+paper+test) for one ``WINDOWS`` bucket and td/prev kind."""
    prefix = f"{window}_{kind}_"
    tiles: List[Dict[str, Any]] = []
    for row in rows:
        rd = dict(zip(colnames, row))
        mid = rd.get("ml_id")
        if mid is None:
            continue
        pnl, trades_n, wr, ret_sum = _dashboard_tile_aggregate_all_modes(rd, prefix)
        win_pct = wr * 100.0 if wr <= 1.0 else wr
        fe_id = f"mon_{u}_{mid}"
        tiles.append(
            {
                "id": fe_id,
                "trades": int(trades_n),
                "win_loss": round(win_pct, 1),
                "ret_pct": round(ret_sum, 1),
                "pnl": round(pnl, 2),
            }
        )
    return tiles


def performance_monitor_tiles_read_payload(
    *,
    period: str = "all",
    rollup_view: str = "td",
) -> Dict[str, Any]:
    """
    Per-monitor stats from ``performance_monitors_<slot>`` for dashboard tiles.
    ``period``: 1d / 1w / 1m / 1y / all (same as portfolio chart window).
    ``rollup_view``: td (calendar on trade date) or prev (rolling on closed_at).
    Tiles always aggregate live + paper + test (not scoped by UI trading_mode).
    """
    from backend.core.tenant_context import resolved_tenant_user_no_for_app

    slot = resolved_tenant_user_no_for_app()
    if not slot:
        return {"status": "error", "message": "missing tenant"}

    p = (period or "all").strip().lower()
    if p not in WINDOWS:
        p = "all"
    kind = "prev" if (rollup_view or "").lower() == "prev" else "td"

    conn = get_postgresql_connection()
    if not conn:
        return {"status": "error", "message": "No DB connection"}

    u = _norm_slot(slot)
    try:
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'America/New_York'")
            colnames, rows = _fetch_performance_monitor_join_rows(cur, slot)
        tiles = _monitor_tiles_numeric_payloads_from_join(colnames, rows, u, p, kind)
        return {
            "status": "ok",
            "period": p,
            "rollup_view": kind,
            "tiles": tiles,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def write_dashboard_performance_snapshot_redis(
    snap: Dict[str, Any],
    *,
    payload: Optional[str] = None,
) -> None:
    """
    Best-effort cache for ``GET /api/dashboard/performance-snapshot`` (same JSON as pub/sub).
    """
    try:
        from backend.core.trading_redis_comms import (
            redis_client_optional,
            redis_key_dashboard_performance_snapshot,
        )

        r = redis_client_optional()
        if not r:
            return
        u = str(snap.get("tenant_user_no") or "").strip()
        if not u:
            return
        pl = payload if payload is not None else json.dumps(snap, default=str)
        ttl_raw = os.getenv("REDIS_TTL_DASHBOARD_PERFORMANCE_SNAPSHOT", "86400")
        ttl_sec = max(60, int(ttl_raw))
        r.setex(redis_key_dashboard_performance_snapshot(u), ttl_sec, pl)
    except Exception as exc:
        _log.warning("write_dashboard_performance_snapshot_redis failed: %s", exc)


def build_performance_rollups_ws_snapshot(slot: str) -> Optional[Dict[str, Any]]:
    """
    Rich /ws/db_changes payload (same Redis channel as db_change) so dashboards can update
    like trade-monitor ``live_symbol_spot`` without an extra HTTP round trip.
    Monitor tiles: ``tiles_matrix`` only (all windows × td/prev); no duplicate legacy tile list.
    """
    from datetime import datetime, timezone

    from backend.core.dashboard_portfolio_queries import performance_previous_period_pnls

    u = _norm_slot(slot or "")
    if not u:
        return None

    conn = get_postgresql_connection()
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'America/New_York'")
            sch, tot_tbl, _mon = _performance_table_names(u)
            cur.execute(
                psql.SQL("SELECT * FROM {} WHERE user_id = 1").format(
                    psql.Identifier(sch, tot_tbl)
                )
            )
            colnames = [d[0] for d in cur.description] if cur.description else []
            row = cur.fetchone()

            strip = {"live": {}, "paper": {}}
            if not row:
                for mode_lbl in ("live", "paper"):
                    strip[mode_lbl] = {
                        "td": {
                            "status": "ok",
                            "source": "rollups",
                            "rollup_view": "td",
                            "periods": {},
                            "trading_mode": mode_lbl,
                        },
                        "prev": {
                            "status": "ok",
                            "source": "rollups",
                            "rollup_view": "prev",
                            "periods": {},
                            "trading_mode": mode_lbl,
                        },
                    }
            else:
                d = dict(zip(colnames, row))
                prev_live = performance_previous_period_pnls(
                    cursor=cur, slot=u, trading_mode="live"
                )
                prev_paper = performance_previous_period_pnls(
                    cursor=cur, slot=u, trading_mode="paper"
                )
                for mode_lbl in ("live", "paper"):
                    tm = mode_lbl
                    prev_pnls = prev_live if mode_lbl == "live" else prev_paper
                    strip[mode_lbl] = {
                        "td": {
                            "status": "ok",
                            "source": "rollups",
                            "rollup_view": "td",
                            "periods": _periods_dict_from_total_row(d, "td", tm, prev_pnls),
                            "trading_mode": mode_lbl,
                        },
                        "prev": {
                            "status": "ok",
                            "source": "rollups",
                            "rollup_view": "prev",
                            "periods": _periods_dict_from_total_row(d, "prev", tm, prev_pnls),
                            "trading_mode": mode_lbl,
                        },
                    }

            colnames_m, rows_m = _fetch_performance_monitor_join_rows(cur, u)
            tiles_matrix: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
            for win in WINDOWS:
                tiles_matrix[win] = {
                    "td": _monitor_tiles_numeric_payloads_from_join(
                        colnames_m, rows_m, u, win, "td"
                    ),
                    "prev": _monitor_tiles_numeric_payloads_from_join(
                        colnames_m, rows_m, u, win, "prev"
                    ),
                }

        return {
            "type": "performance_rollups_snapshot",
            "tenant_user_no": u,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strip": strip,
            "tiles_matrix": tiles_matrix,
        }
    except Exception as e:
        _log.warning("build_performance_rollups_ws_snapshot failed: %s", e)
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def publish_performance_rollups_ws_snapshot(slot: str) -> None:
    """Fire-and-forget Redis publish for dashboard / trade-monitor-style push."""
    try:
        from backend.core.trading_redis_comms import channel_db_changes, redis_client_optional

        snap = build_performance_rollups_ws_snapshot(slot)
        if not snap:
            return
        r = redis_client_optional()
        if not r:
            _log.error(
                "publish_performance_rollups_ws_snapshot: redis unavailable; snapshot not published (slot=%s)",
                slot,
            )
            return
        payload = json.dumps(snap, default=str)
        r.publish(channel_db_changes(), payload)
        write_dashboard_performance_snapshot_redis(snap, payload=payload)
    except Exception as e:
        _log.warning("publish_performance_rollups_ws_snapshot failed: %s", e)
