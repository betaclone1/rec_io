"""
Symbol-wide loss prevention: shared reconciliation and fan-out from qualifying closed losses.

Qualifying loss: trades.status = closed, win_loss = L, paper_trade not true, test_filter false.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from backend.core.auto_entry_settings_store import loss_prevention_value_for_streak

_log = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")

# Trade rows store calendar day in ``date`` (TEXT) and close clock in ``closed_at`` (often time-only).
# ``date`` can lag (still yesterday while the row was finalized on the next ET day). In that case use
# the **ET calendar date of ``updated_at``** with the same ``closed_at`` / ``time`` — the anchor stays
# the trade's close wall time in New York, not the moment a script touched ``updated_at``.
_SQL_T_CLOSE_TIME = """COALESCE(
        NULLIF(TRIM(BOTH FROM t.closed_at::text), ''),
        NULLIF(TRIM(BOTH FROM t.time::text), ''),
        '00:00:00'
    )"""

_SQL_T_CLOSE_ANCHOR = f"""(
    CASE
        WHEN t.updated_at IS NOT NULL
         AND (NULLIF(TRIM(BOTH FROM t.date::text), ''))::date
             < ((t.updated_at AT TIME ZONE 'America/New_York')::date)
        THEN (
            ((t.updated_at AT TIME ZONE 'America/New_York')::date)::text
            || ' ' || {_SQL_T_CLOSE_TIME}
        )::timestamp AT TIME ZONE 'America/New_York'
        ELSE (
            (t.date::text || ' ' || {_SQL_T_CLOSE_TIME})
        )::timestamp AT TIME ZONE 'America/New_York'
    END
)"""


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=EST)
        return value.astimezone(EST)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=EST)
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return None
    if isinstance(value, str):
        try:
            # ISO from PostgreSQL
            raw = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=EST)
            return dt.astimezone(EST)
        except ValueError:
            return None
    return None


def symbol_wide_cooldown_window_live(
    sw_flag: Any,
    sw_start: Any,
    sw_dur: Any,
    *,
    now_est: Optional[datetime] = None,
) -> bool:
    """
    True when symbol-wide LP is enabled and wall clock (US/Eastern) is still inside
    [start, start + duration hours). Matches PostgreSQL (start + duration * interval '1 hour') > now().
    """
    if not sw_flag or sw_start is None or sw_dur is None:
        return False
    try:
        hrs = float(sw_dur)
    except (TypeError, ValueError):
        return False
    if hrs <= 0:
        return False
    start_est = _parse_ts(sw_start)
    if start_est is None:
        return False
    now = now_est or datetime.now(EST)
    end_est = start_est + timedelta(hours=hrs)
    return now < end_est


def recompute_monitor_loss_prevention(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
    *,
    now_est: Optional[datetime] = None,
) -> Optional[str]:
    """
    Set monitor_list.loss_prevention from symbol-wide cooldown (if active) else win-streak rule.
    Returns new loss_prevention or None if monitor row missing.
    """
    cursor.execute(
        f"""
        SELECT symbol_wide_loss_prevention, symbol_wide_cooldown_start_time, symbol_wide_cooldown_duration,
               win_streak, COALESCE(win_streak_threshold, 22), COALESCE(loss_prevention_toggle, TRUE)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    sw_flag, sw_start, sw_dur, ws, wthresh, lp_tog = row
    now = now_est or datetime.now(EST)

    new_lp: str
    if symbol_wide_cooldown_window_live(sw_flag, sw_start, sw_dur, now_est=now):
        new_lp = "symbol_one_contract"
    else:
        new_lp = loss_prevention_value_for_streak(int(ws or 0), bool(lp_tog), int(wthresh))

    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET loss_prevention = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (new_lp, monitor_id),
    )
    return new_lp


def fetch_qualifying_loss_row(
    cursor, trades_qualified: str, trade_id: int
) -> Optional[Tuple[str, Any, str, bool, bool]]:
    """Return (symbol, cooldown_anchor_timestamptz, win_loss, paper_trade, test_filter) or None."""
    cursor.execute(
        f"""
        SELECT symbol, {_SQL_T_CLOSE_ANCHOR}, win_loss,
               COALESCE(paper_trade, FALSE), COALESCE(test_filter, FALSE)
        FROM {trades_qualified} AS t
        WHERE id = %s
        """,
        (trade_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return row[0], row[1], row[2], bool(row[3]), bool(row[4])


def apply_symbol_wide_loss_fanout(
    cursor,
    monitor_list_qualified: str,
    symbol: str,
    cooldown_start,
) -> List[str]:
    """
    Set symbol_wide_cooldown_start_time for all monitors on symbol with feature on.
    Returns list of monitor ids affected.
    """
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET symbol_wide_cooldown_start_time = %s, updated_at = CURRENT_TIMESTAMP
        WHERE symbol = %s AND symbol_wide_loss_prevention IS TRUE
        RETURNING id
        """,
        (cooldown_start, symbol),
    )
    ids = [str(r[0]) for r in (cursor.fetchall() or [])]
    return ids


def recompute_monitors_by_ids(
    cursor,
    monitor_list_qualified: str,
    monitor_ids: Sequence[str],
) -> None:
    seen = set()
    for mid in monitor_ids:
        if mid in seen:
            continue
        seen.add(mid)
        recompute_monitor_loss_prevention(cursor, monitor_list_qualified, mid)


def on_trade_closed_symbol_wide_loss(
    cursor,
    trades_qualified: str,
    monitor_list_qualified: str,
    trade_id: int,
) -> bool:
    """
    If trade is a qualifying loss, fan-out cooldown start to all monitors on that symbol
    with symbol_wide_loss_prevention and recompute loss_prevention for each.
    Returns True if symbol-wide path ran.
    """
    row = fetch_qualifying_loss_row(cursor, trades_qualified, trade_id)
    if not row:
        return False
    symbol, cooldown_anchor, win_loss, paper, test_filter = row
    if win_loss != "L" or paper or test_filter:
        return False
    if not symbol or not str(symbol).strip():
        return False

    ids = apply_symbol_wide_loss_fanout(
        cursor, monitor_list_qualified, str(symbol).strip(), cooldown_anchor
    )
    if not ids:
        return False
    recompute_monitors_by_ids(cursor, monitor_list_qualified, ids)
    return True


def startup_reconcile_symbol_wide_for_tenant(
    cursor,
    trades_qualified: str,
    monitor_list_qualified: str,
) -> None:
    """
    Align symbol_wide_cooldown_start_time from last qualifying loss per symbol, then recompute LP.
    """
    cursor.execute(
        f"""
        SELECT DISTINCT symbol
        FROM {monitor_list_qualified}
        WHERE symbol_wide_loss_prevention IS TRUE
        """
    )
    symbols = [r[0] for r in (cursor.fetchall() or []) if r and r[0]]
    if not symbols:
        return

    cursor.execute(
        f"""
        SELECT t.symbol, MAX({_SQL_T_CLOSE_ANCHOR}) AS t_last
        FROM {trades_qualified} AS t
        WHERE t.status = 'closed'
          AND t.win_loss = 'L'
          AND (t.paper_trade IS NOT TRUE)
          AND (t.test_filter IS NOT TRUE)
          AND t.symbol = ANY(%s)
        GROUP BY t.symbol
        """,
        (symbols,),
    )
    last_by_symbol = {r[0]: r[1] for r in (cursor.fetchall() or [])}

    for sym in symbols:
        t_last = last_by_symbol.get(sym)
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET symbol_wide_cooldown_start_time = %s, updated_at = CURRENT_TIMESTAMP
            WHERE symbol = %s AND symbol_wide_loss_prevention IS TRUE
            """,
            (t_last, sym),
        )

    cursor.execute(
        f"""
        SELECT id FROM {monitor_list_qualified}
        WHERE symbol_wide_loss_prevention IS TRUE
        """
    )
    all_ids = [str(r[0]) for r in (cursor.fetchall() or [])]
    recompute_monitors_by_ids(cursor, monitor_list_qualified, all_ids)


def sync_symbol_wide_after_monitor_settings_save(
    cursor,
    monitor_list_qualified: str,
    trades_qualified: str,
    monitor_id: str,
) -> None:
    """
    After monitor_list row is updated from settings UI: align cooldown anchor and recompute LP.
    """
    cursor.execute(
        f"""
        SELECT symbol, COALESCE(symbol_wide_loss_prevention, FALSE)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return
    sym, sw = row[0], row[1]
    if not sym:
        return
    sym = str(sym).strip()
    if not sw:
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET symbol_wide_cooldown_start_time = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (monitor_id,),
        )
        recompute_monitor_loss_prevention(cursor, monitor_list_qualified, str(monitor_id))
        return

    cursor.execute(
        f"""
        SELECT MAX({_SQL_T_CLOSE_ANCHOR})
        FROM {trades_qualified} AS t
        WHERE t.symbol = %s
          AND t.status = 'closed'
          AND t.win_loss = 'L'
          AND (t.paper_trade IS NOT TRUE)
          AND (t.test_filter IS NOT TRUE)
        """,
        (sym,),
    )
    row2 = cursor.fetchone()
    t_last = row2[0] if row2 else None

    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET symbol_wide_cooldown_start_time = %s, updated_at = CURRENT_TIMESTAMP
        WHERE symbol = %s AND symbol_wide_loss_prevention IS TRUE
        """,
        (t_last, sym),
    )
    cursor.execute(
        f"""
        SELECT id FROM {monitor_list_qualified}
        WHERE symbol = %s AND symbol_wide_loss_prevention IS TRUE
        """,
        (sym,),
    )
    ids = [str(r[0]) for r in (cursor.fetchall() or [])]
    recompute_monitors_by_ids(cursor, monitor_list_qualified, ids)
