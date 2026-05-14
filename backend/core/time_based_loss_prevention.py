"""
Per-monitor time-based loss prevention: ``loss_prevention_cooldown_loss_count`` is derived from
closed ``L`` rows on the live and simulated trade logs (deduped per ``date`` / ``weekly_cycle`` /
``ticker``). **Startup / full replay** rebuilds ``original_loss_prevention_cooldown_start_time``,
sliding live/sim anchors, and the tally from those two tables alone: the last **episode** of losses
is losses separated by a gap longer than ``loss_prevention_duration``; if the latest loss in that
episode still has an open cooldown window (``latest + duration > NOW()``), that episode is
restored; otherwise LP timestamps and the count are cleared.

Incremental paths call :func:`refresh_loss_prevention_tally_from_trades`, which applies the same
log-derived episode rebuild as restart (no reliance on a possibly wrong ``original`` on the row).
"""

from __future__ import annotations

import logging
import re
import zlib
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from backend.core.auto_entry_settings_store import loss_prevention_value_for_streak
from backend.core.symbol_wide_loss_prevention import (
    configured_symbol_wide_monitor_ids,
    project_symbol_wide_loss_prevention_to_monitor,
    sync_market_wide_loss_prevention_followers,
    sync_symbol_wide_loss_prevention_from_monitor,
    try_sync_market_wide_after_hero_recompute,
)
from backend.core.tenant_legacy_sql import legacy_users_sim_trade_lp_cycle_ledger, legacy_users_trades_simulated
_log = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")


def _sql_sim_cooldown_live_expr(prefix: str = "") -> str:
    """Matches ``monitor_list_api`` / dashboard ``simulated_loss_prevention_cooldown_live`` (server ``NOW()``)."""
    p = prefix
    return f"""(
    COALESCE({p}loss_prevention_toggle, FALSE)
    AND COALESCE(NULLIF({p}loss_prevention_method, ''), 'win_streak') = 'time'
    AND COALESCE({p}simulated_trade_loss_prevention, FALSE)
    AND {p}simulated_loss_prevention_cooldown_start_time IS NOT NULL
    AND COALESCE({p}loss_prevention_duration, 0) > 0
    AND (
        {p}simulated_loss_prevention_cooldown_start_time
        + (COALESCE({p}loss_prevention_duration, 0) || ' hours')::interval
    ) > NOW()
)"""


def _sql_live_loss_prevention_cooldown_live_expr(prefix: str = "") -> str:
    """Trades-log loss throttle window: same duration as ``loss_prevention_duration``."""
    p = prefix
    return f"""(
    COALESCE({p}loss_prevention_toggle, FALSE)
    AND COALESCE(NULLIF({p}loss_prevention_method, ''), 'win_streak') = 'time'
    AND {p}live_loss_prevention_cooldown_start_time IS NOT NULL
    AND COALESCE({p}loss_prevention_duration, 0) > 0
    AND (
        {p}live_loss_prevention_cooldown_start_time
        + (COALESCE({p}loss_prevention_duration, 0) || ' hours')::interval
    ) > NOW()
)"""


def _sql_close_anchor_timestamptz(alias: str) -> str:
    """Absolute close instant as ``timestamptz`` for trade row ``alias`` (SQL fragment).

    ``users.trades_*`` uses typed ``closed_at TIMESTAMP`` (legacy rows may be time-only).
    ``users.trades_simulated_*`` uses ``closed_at TEXT``, often a full ISO-8601 string.
    Concatenating ``date::text || ' ' || closed_at::text`` when ``closed_at`` already
    contains a calendar date produces invalid timestamps (duplicate date prefix).
    """
    return f"""(
        CASE
            WHEN pg_typeof({alias}.closed_at)::regtype IN (
                'timestamp without time zone'::regtype,
                'timestamp with time zone'::regtype
            )
                THEN {alias}.closed_at::timestamptz
            WHEN btrim(COALESCE({alias}.closed_at::text, ''))
                ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}[Tt ]'
                THEN btrim({alias}.closed_at::text)::timestamptz
            ELSE (
                btrim({alias}.date::text) || ' ' || btrim({alias}.closed_at::text)
            )::timestamp AT TIME ZONE 'America/New_York'
        END
    )"""


def _sql_close_anchor_epoch(alias: str) -> str:
    """POSIX seconds (UTC) for close anchor — avoids psycopg2 ``timestamptz`` → naive local."""
    return f"EXTRACT(EPOCH FROM ({_sql_close_anchor_timestamptz(alias)}))"


# Trade-close row: anchor as epoch only (see :func:`_sql_close_anchor_epoch`).
_SQL_T_CLOSE_ANCHOR_EPOCH = _sql_close_anchor_epoch("t")

MONITOR_KEY_PATTERN = re.compile(r"^mon_(\d+?)_(\d+)$", re.IGNORECASE)

# Session advisory lock: trade_manager + AES both call startup reconcile; serialize per tenant.
_SIM_LP_ADV_MAGIC = 0x53494D4C  # 'SIML'


def _pg_advisory_key_sim_lp_reconcile(tenant_slot: str) -> int:
    h = zlib.crc32(str(tenant_slot).strip().encode("utf-8")) & 0xFFFFFFFF
    return int((_SIM_LP_ADV_MAGIC << 32) | h) & ((1 << 63) - 1)


def _loss_anchor_utc_epoch(loss_anchor_ts: datetime) -> float:
    """POSIX seconds (UTC) for the loss instant; naive datetimes = Eastern wall (trade log rule)."""
    if loss_anchor_ts.tzinfo is None:
        loss_anchor_ts = loss_anchor_ts.replace(tzinfo=EST)
    return float(loss_anchor_ts.astimezone(timezone.utc).timestamp())


_LOSS_LOG_LOOKBACK_DAYS = 14


def _lp_dedupe_key(date_s: Any, weekly_cycle: Any, ticker_s: Any) -> Tuple[str, str, str]:
    d = str(date_s or "").strip()
    w = str(weekly_cycle) if weekly_cycle is not None else ""
    tk = str(ticker_s or "").strip().lower()
    return (d, w, tk)


def _segment_closed_loss_rows_by_cooldown_gap(
    rows: List[Tuple[str, Any, Any, Any, Any]], duration_h: float
) -> List[List[Tuple[str, Any, Any, Any, Any]]]:
    """Split ascending ``(src, date, wc, ticker, epoch)`` when the gap between closes exceeds duration."""
    if not rows:
        return []
    dur_sec = max(float(duration_h or 0), 0.001) * 3600.0
    out: List[List[Tuple[str, Any, Any, Any, Any]]] = []
    cur: List[Tuple[str, Any, Any, Any, Any]] = [rows[0]]
    for i in range(1, len(rows)):
        prev_ep = float(rows[i - 1][4] or 0)
        cur_ep = float(rows[i][4] or 0)
        if cur_ep - prev_ep > dur_sec:
            out.append(cur)
            cur = [rows[i]]
        else:
            cur.append(rows[i])
    out.append(cur)
    return out


def _deduped_loss_count_in_episode(ep: List[Tuple[str, Any, Any, Any, Any]]) -> int:
    """Live rows + sim rows without a live row sharing the same (date, weekly_cycle, ticker)."""
    live_keys = {_lp_dedupe_key(r[1], r[2], r[3]) for r in ep if r[0] == "live"}
    live_n = sum(1 for r in ep if r[0] == "live")
    sim_only = 0
    for r in ep:
        if r[0] != "sim":
            continue
        if _lp_dedupe_key(r[1], r[2], r[3]) in live_keys:
            continue
        sim_only += 1
    return int(live_n + sim_only)


def rebuild_monitor_time_lp_from_trade_logs_on_restart(
    cursor,
    *,
    monitor_list_qualified: str,
    trades_qualified: str,
    trades_simulated_qualified: str,
    tenant_slot: str,
    monitor_id: str,
) -> bool:
    """Rebuild LP episode fields from live + simulated trade logs (startup / full replay).

    * **Episode:** consecutive closed ``L`` closes (union of both tables) where each gap between
      sorted close anchors is at most ``loss_prevention_duration`` hours. The **last** episode is
      the only candidate for an open cooldown.
    * **Still open:** ``latest_close_epoch + duration > NOW()`` (UTC clock).
    * **original_loss_prevention_cooldown_start_time:** ``MIN(close anchor)`` in that episode.
    * **Sliding anchors:** ``MAX(live anchor)`` / ``MAX(sim anchor)`` within the episode (sim side
      only when ``simulated_trade_loss_prevention`` is enabled).
    * **Count:** :func:`_deduped_loss_count_in_episode` on episode rows.

    If no episode is open, clears ``original``, live/sim anchors, and the tally.

    Returns True when an open episode was written to the monitor row; False when cleared or
    unknown monitor.
    """
    monitor_key = f"mon_{tenant_slot}_{monitor_id}"
    cursor.execute(
        f"""
        SELECT COALESCE(loss_prevention_duration, 4),
               COALESCE(simulated_trade_loss_prevention, FALSE)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    cfg = cursor.fetchone()
    if not cfg:
        return False
    duration_h = float(cfg[0] or 4)
    include_sim = bool(cfg[1])

    te = _sql_close_anchor_epoch("t")
    tt = _sql_close_anchor_timestamptz("t")
    live_sql = f"""
      SELECT 'live'::text AS src,
             t.date::text AS d,
             t.weekly_cycle AS wc,
             COALESCE(t.ticker::text, '') AS tk,
             ({te})::float8 AS ep
      FROM {trades_qualified} AS t
      WHERE t.monitor = %s
        AND t.status = 'closed'
        AND t.win_loss = 'L'
        AND ({tt}) >= NOW() - interval '{_LOSS_LOG_LOOKBACK_DAYS} days'
    """
    if include_sim:
        se = _sql_close_anchor_epoch("s")
        st = _sql_close_anchor_timestamptz("s")
        sim_sql = f"""
          SELECT 'sim'::text AS src,
                 s.date::text AS d,
                 s.weekly_cycle AS wc,
                 COALESCE(s.ticker::text, '') AS tk,
                 ({se})::float8 AS ep
          FROM {trades_simulated_qualified} AS s
          WHERE s.monitor = %s
            AND s.status = 'closed'
            AND s.win_loss = 'L'
            AND COALESCE(s.test_filter, FALSE) IS NOT TRUE
            AND ({st}) >= NOW() - interval '{_LOSS_LOG_LOOKBACK_DAYS} days'
        """
        cursor.execute(
            f"{live_sql} UNION ALL {sim_sql} ORDER BY ep ASC",
            (monitor_key, monitor_key),
        )
    else:
        cursor.execute(f"{live_sql} ORDER BY ep ASC", (monitor_key,))

    rows = list(cursor.fetchall() or [])
    now_ts = datetime.now(timezone.utc).timestamp()
    dur_sec = max(float(duration_h or 0), 0.001) * 3600.0

    def _clear_lp_row() -> None:
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET original_loss_prevention_cooldown_start_time = NULL,
                live_loss_prevention_cooldown_start_time = NULL,
                simulated_loss_prevention_cooldown_start_time = NULL,
                loss_prevention_cooldown_loss_count = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (monitor_id,),
        )

    if not rows:
        _clear_lp_row()
        return False

    episodes = _segment_closed_loss_rows_by_cooldown_gap(rows, duration_h)
    last = episodes[-1]
    latest_ep = max(float(r[4]) for r in last)
    if latest_ep + dur_sec <= now_ts:
        _clear_lp_row()
        return False

    min_ep = min(float(r[4]) for r in last)
    live_eps = [float(r[4]) for r in last if r[0] == "live"]
    sim_eps = [float(r[4]) for r in last if r[0] == "sim"]
    max_live = max(live_eps) if live_eps else None
    max_sim = max(sim_eps) if sim_eps and include_sim else None
    tally = _deduped_loss_count_in_episode(last)

    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET original_loss_prevention_cooldown_start_time = to_timestamp(%s::float8),
            live_loss_prevention_cooldown_start_time = CASE
                WHEN %s::float8 IS NULL THEN NULL ELSE to_timestamp(%s::float8)
            END,
            simulated_loss_prevention_cooldown_start_time = CASE
                WHEN %s IS NOT TRUE THEN NULL
                WHEN %s::float8 IS NULL THEN NULL
                ELSE to_timestamp(%s::float8)
            END,
            loss_prevention_cooldown_loss_count = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            min_ep,
            max_live,
            max_live,
            include_sim,
            max_sim,
            max_sim,
            tally,
            monitor_id,
        ),
    )
    _log.debug(
        "[LP restart] monitor=%s episode_rows=%d tally=%d original_epoch=%.3f latest_epoch=%.3f",
        monitor_id,
        len(last),
        tally,
        min_ep,
        latest_ep,
    )
    return True


def refresh_loss_prevention_tally_from_trades(
    cursor,
    *,
    monitor_list_qualified: str,
    trades_qualified: str,
    trades_simulated_qualified: str,
    tenant_slot: str,
    monitor_id: str,
    anchor_floor_epoch: Optional[float] = None,
    update_sliding_timestamps: bool = True,
) -> bool:
    """Recompute LP episode fields from trade logs (same algorithm as restart / full replay).

    Sets ``original_loss_prevention_cooldown_start_time``, live and simulated sliding anchors, and
    ``loss_prevention_cooldown_loss_count`` from closed ``L`` rows only (episode segmentation by
    ``loss_prevention_duration`` gaps). ``anchor_floor_epoch`` and ``update_sliding_timestamps`` are
    kept for backward compatibility with callers and are ignored.
    """
    _ = (anchor_floor_epoch, update_sliding_timestamps)
    return rebuild_monitor_time_lp_from_trade_logs_on_restart(
        cursor,
        monitor_list_qualified=monitor_list_qualified,
        trades_qualified=trades_qualified,
        trades_simulated_qualified=trades_simulated_qualified,
        tenant_slot=tenant_slot,
        monitor_id=monitor_id,
    )


def monitor_key_to_slot_and_id(monitor_key: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not monitor_key:
        return None, None
    m = MONITOR_KEY_PATTERN.match(str(monitor_key).strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        try:
            value = float(value)
        except Exception:
            return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone(EST)
        except (OSError, OverflowError, ValueError):
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
            raw = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=EST)
            return dt.astimezone(EST)
        except ValueError:
            return None
    return None


def ensure_sim_trade_ledger_table(cursor, tenant_slot: str) -> None:
    tbl = legacy_users_sim_trade_lp_cycle_ledger(tenant_slot)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {tbl} (
            monitor_id INTEGER NOT NULL,
            cycle_date DATE NOT NULL,
            weekly_cycle NUMERIC(10, 1) NOT NULL,
            applied_units INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (monitor_id, cycle_date, weekly_cycle)
        )
        """
    )


def tier_from_sim_loss_count(count: int) -> str:
    """Sim tier from the shared ``loss_prevention_cooldown_loss_count`` while sim window is active."""
    c = int(count or 0)
    if c < 1:
        return "off"
    if c >= 3:
        return "sim_loss_1c"
    if c == 2:
        return "sim_loss_25"
    return "sim_loss_50"


def resolve_monitor_loss_prevention_value(
    *,
    live_loss_prevention_cooldown_live: bool = False,
    simulated_loss_prevention_cooldown_live: bool,
    sim_loss_count: int,
    loss_prevention_toggle: bool,
    loss_prevention_method: str = "win_streak",
    win_streak: int,
    win_streak_threshold: int,
    current_loss_prevention: Optional[str],
    cycle_had_loss: Optional[bool] = None,
) -> str:
    if not loss_prevention_toggle:
        return "off"
    method = str(loss_prevention_method or "win_streak").strip().lower()
    if method == "time":
        if live_loss_prevention_cooldown_live:
            return "live_loss_1c"
        if simulated_loss_prevention_cooldown_live:
            tier = tier_from_sim_loss_count(sim_loss_count)
            if tier == "off":
                return "off"
            return tier
        return "off"
    cur = str(current_loss_prevention or "").strip().lower()
    if cur == "new" and cycle_had_loss is not True:
        return "new"
    return loss_prevention_value_for_streak(
        int(win_streak or 0), bool(loss_prevention_toggle), int(win_streak_threshold or 22)
    )


def _expire_live_trade_cooldown_if_needed(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
) -> bool:
    """Clear expired live throttle anchor.

    ``loss_prevention_cooldown_loss_count`` is the episode master tally. When the live
    window ends but the **sim** cooldown window is still open, only drop the live
    timestamp (symmetric to :func:`_expire_simulated_trade_state_if_needed`). When
    sim is not in window, end the episode: clear anchors and zero the tally.
    """
    live_expired = """
          AND live_loss_prevention_cooldown_start_time IS NOT NULL
          AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE
          AND COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak') = 'time'
          AND COALESCE(loss_prevention_duration, 0) > 0
          AND (
            live_loss_prevention_cooldown_start_time
            + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
          ) <= NOW()
    """
    sim_window_open = """
          AND COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
          AND simulated_loss_prevention_cooldown_start_time IS NOT NULL
          AND COALESCE(loss_prevention_duration, 0) > 0
          AND (
            simulated_loss_prevention_cooldown_start_time
            + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
          ) > NOW()
    """
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET live_loss_prevention_cooldown_start_time = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        {live_expired}
        {sim_window_open}
        """,
        (monitor_id,),
    )
    n_a = int(getattr(cursor, "rowcount", 0) or 0)
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET live_loss_prevention_cooldown_start_time = NULL,
            original_loss_prevention_cooldown_start_time = NULL,
            simulated_loss_prevention_cooldown_start_time = NULL,
            loss_prevention_cooldown_loss_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        {live_expired}
          AND NOT (
            COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
            AND simulated_loss_prevention_cooldown_start_time IS NOT NULL
            AND COALESCE(loss_prevention_duration, 0) > 0
            AND (
                simulated_loss_prevention_cooldown_start_time
                + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
            ) > NOW()
          )
        """,
        (monitor_id,),
    )
    n_b = int(getattr(cursor, "rowcount", 0) or 0)
    return bool(n_a or n_b)


def _expire_simulated_trade_state_if_needed(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
    *,
    now_est: datetime,
) -> bool:
    """Clear expired sim cooldown anchor.

    ``loss_prevention_cooldown_loss_count`` is the master tally (live + sim). When the sim
    window ends but the **live** throttle window is still open, only drop the sim timestamp
    so live sizing and the tally stay consistent. When live is not in window, end the
    whole episode: clear anchors and zero the tally.
    """
    del now_est  # Expire using DB ``NOW()`` only (host OS / psycopg2 tz must not affect this).
    sim_expired = """
          AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE
          AND COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak') = 'time'
          AND COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
          AND simulated_loss_prevention_cooldown_start_time IS NOT NULL
          AND COALESCE(loss_prevention_duration, 0) > 0
          AND (
            simulated_loss_prevention_cooldown_start_time
            + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
          ) <= NOW()
    """
    live_window_open = """
          AND live_loss_prevention_cooldown_start_time IS NOT NULL
          AND COALESCE(loss_prevention_duration, 0) > 0
          AND (
            live_loss_prevention_cooldown_start_time
            + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
          ) > NOW()
    """
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET simulated_loss_prevention_cooldown_start_time = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        {sim_expired}
        {live_window_open}
        """,
        (monitor_id,),
    )
    n_a = int(getattr(cursor, "rowcount", 0) or 0)
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET original_loss_prevention_cooldown_start_time = NULL,
            simulated_loss_prevention_cooldown_start_time = NULL,
            live_loss_prevention_cooldown_start_time = NULL,
            loss_prevention_cooldown_loss_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        {sim_expired}
          AND NOT (
            live_loss_prevention_cooldown_start_time IS NOT NULL
            AND COALESCE(loss_prevention_duration, 0) > 0
            AND (
                live_loss_prevention_cooldown_start_time
                + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
            ) > NOW()
          )
        """,
        (monitor_id,),
    )
    n_b = int(getattr(cursor, "rowcount", 0) or 0)
    return bool(n_a or n_b)


def recompute_monitor_loss_prevention(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
    *,
    now_est: Optional[datetime] = None,
    cycle_had_loss: Optional[bool] = None,
) -> Optional[str]:
    now = now_est or datetime.now(EST)
    _expire_live_trade_cooldown_if_needed(cursor, monitor_list_qualified, monitor_id)
    _expire_simulated_trade_state_if_needed(cursor, monitor_list_qualified, monitor_id, now_est=now)

    cursor.execute(
        f"""
        SELECT COALESCE(simulated_trade_loss_prevention, FALSE),
               {_sql_live_loss_prevention_cooldown_live_expr()},
               {_sql_sim_cooldown_live_expr()},
               COALESCE(loss_prevention_cooldown_loss_count, 0),
               win_streak, COALESCE(win_streak_threshold, 22), COALESCE(loss_prevention_toggle, TRUE),
               COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak'),
               loss_prevention_state
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    sim_flag, live_tl, sim_live, loss_cnt, ws, wthresh, lp_tog, lp_method, current_lp = row

    live_tl = bool(live_tl)
    sim_live = bool(sim_live)
    new_lp = resolve_monitor_loss_prevention_value(
        live_loss_prevention_cooldown_live=live_tl,
        simulated_loss_prevention_cooldown_live=sim_live,
        sim_loss_count=int(loss_cnt or 0),
        loss_prevention_toggle=bool(lp_tog),
        loss_prevention_method=str(lp_method or "win_streak"),
        win_streak=int(ws or 0),
        win_streak_threshold=int(wthresh),
        current_loss_prevention=current_lp if isinstance(current_lp, str) else None,
        cycle_had_loss=cycle_had_loss,
    )

    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET loss_prevention_state = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (new_lp, monitor_id),
    )
    synced_hero = sync_symbol_wide_loss_prevention_from_monitor(cursor, monitor_list_qualified, monitor_id)
    if not synced_hero:
        project_symbol_wide_loss_prevention_to_monitor(cursor, monitor_list_qualified, monitor_id)
    try_sync_market_wide_after_hero_recompute(cursor, monitor_list_qualified, str(monitor_id))
    return new_lp


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


def cycle_loss_contribution_units(sim_l: int, live_l: int) -> int:
    """Single-cycle simulated loss units.

    Live losses use ``live_loss_1c`` and do not advance the simulated tier count.
    ``live_l`` remains for older callers/tests but is intentionally ignored.
    """
    s = int(sim_l or 0)
    return s


def cycle_loss_contribution_and_anchor(
    cursor,
    trades_simulated_qualified: str,
    trades_qualified: str,
    monitor_key: str,
    cycle_date: Any,
    weekly_cycle: Any,
) -> Tuple[int, Optional[datetime]]:
    return _cycle_contribution(
        cursor, trades_simulated_qualified, trades_qualified, monitor_key, cycle_date, weekly_cycle
    )


def _cycle_contribution(
    cursor,
    trades_simulated_qualified: str,
    trades_qualified: str,
    monitor_key: str,
    cycle_date: Any,
    weekly_cycle: Any,
) -> Tuple[int, Optional[datetime]]:
    cursor.execute(
        f"""
        SELECT COUNT(*) FROM {trades_simulated_qualified}
        WHERE monitor = %s AND date = %s AND weekly_cycle = %s
          AND status = 'closed' AND win_loss = 'L'
        """,
        (monitor_key, cycle_date, weekly_cycle),
    )
    sim_l = int(cursor.fetchone()[0] or 0)

    contribution = cycle_loss_contribution_units(sim_l, 0)
    if contribution <= 0:
        return 0, None

    cursor.execute(
        f"""
        SELECT MAX({_sql_close_anchor_epoch("s")})
        FROM {trades_simulated_qualified} AS s
        WHERE s.monitor = %s AND s.date = %s AND s.weekly_cycle = %s
          AND s.status = 'closed' AND s.win_loss = 'L'
        """,
        (monitor_key, cycle_date, weekly_cycle),
    )
    anch = cursor.fetchone()[0]
    return contribution, _parse_ts(anch)


def apply_sim_trade_cycle_loss(
    cursor,
    *,
    monitor_list_qualified: str,
    trades_qualified: str,
    trades_simulated_qualified: str,
    ledger_qualified: str,
    tenant_slot: str,
    monitor_key: str,
    cycle_date: Any,
    weekly_cycle: Any,
    loss_anchor_ts: datetime,
    from_replay: bool = False,
) -> bool:
    slot, mid_str = monitor_key_to_slot_and_id(monitor_key)
    if not mid_str or slot != tenant_slot:
        return False
    ensure_sim_trade_ledger_table(cursor, tenant_slot)

    cursor.execute(
        f"""
        SELECT COALESCE(loss_prevention_toggle, FALSE),
               COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak'),
               COALESCE(simulated_trade_loss_prevention, FALSE)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (mid_str,),
    )
    row = cursor.fetchone()
    if not row or not (bool(row[0]) and str(row[1]).strip().lower() == "time" and bool(row[2])):
        return False

    sim_expired = _expire_simulated_trade_state_if_needed(
        cursor, monitor_list_qualified, mid_str, now_est=datetime.now(EST)
    )

    contribution, _ = _cycle_contribution(
        cursor, trades_simulated_qualified, trades_qualified, monitor_key, cycle_date, weekly_cycle
    )
    if contribution <= 0:
        live_expired = _expire_live_trade_cooldown_if_needed(cursor, monitor_list_qualified, mid_str)
        if live_expired or sim_expired:
            recompute_monitor_loss_prevention(cursor, monitor_list_qualified, mid_str)
        return False

    _ = (loss_anchor_ts, from_replay)

    refresh_loss_prevention_tally_from_trades(
        cursor,
        monitor_list_qualified=monitor_list_qualified,
        trades_qualified=trades_qualified,
        trades_simulated_qualified=trades_simulated_qualified,
        tenant_slot=tenant_slot,
        monitor_id=mid_str,
    )
    recompute_monitor_loss_prevention(cursor, monitor_list_qualified, mid_str)
    return True


def fetch_qualifying_loss_row_sim_lp(
    cursor, trades_qualified: str, trade_id: int
) -> Optional[Tuple[str, Any, str, Any, Any, bool]]:
    """monitor_key, anchor, win_loss, date, weekly_cycle, test_filter."""
    cursor.execute(
        f"""
        SELECT monitor, {_SQL_T_CLOSE_ANCHOR_EPOCH}, win_loss, date, weekly_cycle,
               COALESCE(test_filter, FALSE)
        FROM {trades_qualified} AS t
        WHERE id = %s
        """,
        (trade_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return row[0], row[1], row[2], row[3], row[4], bool(row[5])


def on_trade_closed_simulated_trade_loss(
    cursor,
    trades_qualified: str,
    monitor_list_qualified: str,
    trades_simulated_qualified: str,
    ledger_qualified: str,
    tenant_slot: str,
    trade_id: int,
) -> bool:
    row = fetch_qualifying_loss_row_sim_lp(cursor, trades_qualified, trade_id)
    if not row:
        return False
    monitor_key, anchor, win_loss, tr_date, wc, test_filter = row
    if win_loss != "L" or test_filter:
        return False
    if not monitor_key:
        return False
    anchor_dt = _parse_ts(anchor)
    if anchor_dt is None:
        return False
    return apply_sim_trade_cycle_loss(
        cursor,
        monitor_list_qualified=monitor_list_qualified,
        trades_qualified=trades_qualified,
        trades_simulated_qualified=trades_simulated_qualified,
        ledger_qualified=ledger_qualified,
        tenant_slot=tenant_slot,
        monitor_key=str(monitor_key).strip(),
        cycle_date=tr_date,
        weekly_cycle=wc,
        loss_anchor_ts=anchor_dt,
    )


def on_trade_closed_live_loss_throttle(
    cursor,
    trades_qualified: str,
    monitor_list_qualified: str,
    tenant_slot: str,
    trade_id: int,
) -> bool:
    """After any trades-log closed loss, refresh time-LP from the live + sim trade logs.

    Episode ``original``, sliding anchors, and the shared tally are recomputed from closed
    ``L`` rows (same rebuild as restart), not from incremental row patches.
    """
    cursor.execute(
        f"""
        SELECT t.monitor, t.win_loss, {_SQL_T_CLOSE_ANCHOR_EPOCH}
        FROM {trades_qualified} AS t
        WHERE t.id = %s
        """,
        (trade_id,),
    )
    row = cursor.fetchone()
    if not row:
        return False
    monitor_key, win_loss, anch_ep = (
        row[0],
        row[1],
        row[2],
    )
    if win_loss != "L":
        return False
    if not monitor_key:
        return False
    slot, mid_str = monitor_key_to_slot_and_id(str(monitor_key).strip())
    if not mid_str or slot != tenant_slot:
        return False
    cursor.execute(
        f"""
        SELECT COALESCE(loss_prevention_toggle, FALSE),
               COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak')
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (mid_str,),
    )
    flg = cursor.fetchone()
    if not flg or not (bool(flg[0]) and str(flg[1]).strip().lower() == "time"):
        return False
    if _parse_ts(anch_ep) is None:
        return False
    refresh_loss_prevention_tally_from_trades(
        cursor,
        monitor_list_qualified=monitor_list_qualified,
        trades_qualified=trades_qualified,
        trades_simulated_qualified=legacy_users_trades_simulated(tenant_slot),
        tenant_slot=tenant_slot,
        monitor_id=mid_str,
    )
    recompute_monitor_loss_prevention(cursor, monitor_list_qualified, mid_str)
    return True


def replay_live_loss_throttle_from_trades_log(
    cursor,
    trades_qualified: str,
    monitor_list_qualified: str,
    tenant_slot: str,
    monitor_id: str,
    *,
    duration_hours: Optional[float] = None,
    loss_anchor_floor_est: Optional[datetime] = None,
) -> bool:
    """Reconcile live throttle and the shared loss tally from trade logs (episode rebuild).

    Delegates to :func:`refresh_loss_prevention_tally_from_trades`. ``loss_anchor_floor_est`` is
    deprecated and ignored; episode bounds come only from closed ``L`` rows and duration gaps.
    """
    _ = loss_anchor_floor_est
    if duration_hours is None:
        cursor.execute(
            f"""
            SELECT COALESCE(loss_prevention_duration, 4)
            FROM {monitor_list_qualified}
            WHERE id = %s
            """,
            (monitor_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False
        duration_hours = float(row[0] or 4)

    if float(duration_hours or 0) <= 0:
        return False

    return refresh_loss_prevention_tally_from_trades(
        cursor,
        monitor_list_qualified=monitor_list_qualified,
        trades_qualified=trades_qualified,
        trades_simulated_qualified=legacy_users_trades_simulated(tenant_slot),
        tenant_slot=tenant_slot,
        monitor_id=str(monitor_id),
    )


def full_replay_monitor_sim_lp_state(
    cursor,
    monitor_list_qualified: str,
    trades_qualified: str,
    trades_simulated_qualified: str,
    ledger_qualified: str,
    tenant_slot: str,
    monitor_id: str,
) -> None:
    ensure_sim_trade_ledger_table(cursor, tenant_slot)
    cursor.execute(
        f"""
        SELECT COALESCE(loss_prevention_toggle, FALSE),
               COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak'),
               COALESCE(simulated_trade_loss_prevention, FALSE)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row or not (bool(row[0]) and str(row[1]).strip().lower() == "time"):
        return

    cursor.execute(
        f"DELETE FROM {ledger_qualified} WHERE monitor_id = %s",
        (int(monitor_id),),
    )
    rebuild_monitor_time_lp_from_trade_logs_on_restart(
        cursor,
        monitor_list_qualified=monitor_list_qualified,
        trades_qualified=trades_qualified,
        trades_simulated_qualified=trades_simulated_qualified,
        tenant_slot=tenant_slot,
        monitor_id=str(monitor_id),
    )
    recompute_monitor_loss_prevention(cursor, monitor_list_qualified, str(monitor_id))


def startup_reconcile_market_wide_loss_prevention_for_tenant(
    cursor,
    monitor_list_qualified: str,
    tenant_slot: str,
) -> None:
    """After sim-trade LP replay, align global hero + market-wide follower projection."""
    from backend.core.symbol_wide_loss_prevention import (
        read_market_wide_loss_prevention_settings,
        sync_market_wide_loss_prevention_followers,
    )

    enabled, hero_id, threshold = read_market_wide_loss_prevention_settings(cursor, tenant_slot)
    if not enabled or hero_id is None or threshold is None or int(threshold) < 1:
        sync_market_wide_loss_prevention_followers(cursor, monitor_list_qualified)
        return
    recompute_monitor_loss_prevention(cursor, monitor_list_qualified, str(hero_id))
    sync_market_wide_loss_prevention_followers(cursor, monitor_list_qualified)


def startup_reconcile_simulated_trade_for_tenant(
    cursor,
    trades_qualified: str,
    trades_simulated_qualified: str,
    monitor_list_qualified: str,
    tenant_slot: str,
) -> None:
    adv_key = _pg_advisory_key_sim_lp_reconcile(tenant_slot)
    cursor.execute("SELECT pg_advisory_lock(%s)", (adv_key,))
    try:
        ledger = legacy_users_sim_trade_lp_cycle_ledger(tenant_slot)
        ensure_sim_trade_ledger_table(cursor, tenant_slot)
        cursor.execute(
            f"""
            SELECT id FROM {monitor_list_qualified}
            WHERE COALESCE(loss_prevention_toggle, FALSE) IS TRUE
              AND COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak') = 'time'
            """
        )
        ids = [str(r[0]) for r in (cursor.fetchall() or [])]
        for mid in ids:
            full_replay_monitor_sim_lp_state(
                cursor,
                monitor_list_qualified,
                trades_qualified,
                trades_simulated_qualified,
                ledger,
                tenant_slot,
                mid,
            )

        replayed = set(ids)
        for mid in configured_symbol_wide_monitor_ids(cursor, monitor_list_qualified):
            if mid in replayed:
                continue
            recompute_monitor_loss_prevention(cursor, monitor_list_qualified, mid)

        startup_reconcile_market_wide_loss_prevention_for_tenant(
            cursor, monitor_list_qualified, tenant_slot
        )
        _log.info("[MARKET WIDE LP] startup reconcile completed for tenant %s", tenant_slot)
    finally:
        cursor.execute("SELECT pg_advisory_unlock(%s)", (adv_key,))


def sync_simulated_trade_after_monitor_settings_save(
    cursor,
    monitor_list_qualified: str,
    trades_qualified: str,
    trades_simulated_qualified: str,
    tenant_slot: str,
    monitor_id: str,
) -> None:
    ledger = legacy_users_sim_trade_lp_cycle_ledger(tenant_slot)
    ensure_sim_trade_ledger_table(cursor, tenant_slot)
    cursor.execute(
        f"""
        SELECT COALESCE(loss_prevention_toggle, FALSE),
               COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak'),
               COALESCE(simulated_trade_loss_prevention, FALSE)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row:
        return
    toggle_on = bool(row[0])
    method = str(row[1] or "win_streak").strip().lower()
    include_sim = bool(row[2])
    if not toggle_on or method != "time":
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET original_loss_prevention_cooldown_start_time = NULL,
                simulated_loss_prevention_cooldown_start_time = NULL,
                loss_prevention_cooldown_loss_count = 0,
                live_loss_prevention_cooldown_start_time = NULL,
                loss_prevention_state = 'off',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (monitor_id,),
        )
        cursor.execute(
            f"DELETE FROM {ledger} WHERE monitor_id = %s",
            (int(monitor_id),),
        )
        recompute_monitor_loss_prevention(cursor, monitor_list_qualified, str(monitor_id))
        return
    if not include_sim:
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET original_loss_prevention_cooldown_start_time = NULL,
                simulated_loss_prevention_cooldown_start_time = NULL,
                live_loss_prevention_cooldown_start_time = NULL,
                loss_prevention_cooldown_loss_count = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (monitor_id,),
        )
        cursor.execute(
            f"DELETE FROM {ledger} WHERE monitor_id = %s",
            (int(monitor_id),),
        )
        replay_live_loss_throttle_from_trades_log(
            cursor,
            trades_qualified,
            monitor_list_qualified,
            tenant_slot,
            str(monitor_id),
        )
        recompute_monitor_loss_prevention(cursor, monitor_list_qualified, str(monitor_id))
        return

    full_replay_monitor_sim_lp_state(
        cursor,
        monitor_list_qualified,
        trades_qualified,
        trades_simulated_qualified,
        ledger,
        tenant_slot,
        str(monitor_id),
    )
