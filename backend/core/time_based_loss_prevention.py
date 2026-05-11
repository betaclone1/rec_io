"""
Per-monitor simulated-trade loss prevention: cycle ledger, tiered loss_prevention, three-path
parity with former symbol-wide (trade_manager events, AES startup, settings sync).
"""

from __future__ import annotations

import logging
import re
import zlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from backend.core.auto_entry_settings_store import loss_prevention_value_for_streak
from backend.core.tenant_legacy_sql import legacy_users_sim_trade_lp_cycle_ledger
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
    """Live (non-paper) loss throttle window: same duration as ``loss_prevention_duration``."""
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
    """``date`` + ``closed_at`` text as Eastern wall → absolute ``timestamptz`` (SQL fragment)."""
    return (
        f"(TRIM(BOTH FROM {alias}.date::text) || ' ' || "
        f"TRIM(BOTH FROM {alias}.closed_at::text))::timestamp AT TIME ZONE 'America/New_York'"
    )


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
    c = int(count or 0)
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
            return tier_from_sim_loss_count(sim_loss_count)
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
) -> None:
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET live_loss_prevention_cooldown_start_time = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
          AND live_loss_prevention_cooldown_start_time IS NOT NULL
          AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE
          AND COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak') = 'time'
          AND COALESCE(loss_prevention_duration, 0) > 0
          AND (
            live_loss_prevention_cooldown_start_time
            + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
          ) <= NOW()
        """,
        (monitor_id,),
    )


def _expire_simulated_trade_state_if_needed(
    cursor,
    monitor_list_qualified: str,
    monitor_id: str,
    *,
    now_est: datetime,
) -> None:
    del now_est  # Expire using DB ``NOW()`` only (host OS / psycopg2 tz must not affect this).
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET original_loss_prevention_cooldown_start_time = NULL,
            simulated_loss_prevention_cooldown_start_time = NULL,
            loss_prevention_cooldown_loss_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
          AND COALESCE(loss_prevention_toggle, FALSE) IS TRUE
          AND COALESCE(NULLIF(loss_prevention_method, ''), 'win_streak') = 'time'
          AND COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
          AND simulated_loss_prevention_cooldown_start_time IS NOT NULL
          AND COALESCE(loss_prevention_duration, 0) > 0
          AND (
            simulated_loss_prevention_cooldown_start_time
            + (COALESCE(loss_prevention_duration, 0) || ' hours')::interval
          ) <= NOW()
        """,
        (monitor_id,),
    )


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

    _expire_live_trade_cooldown_if_needed(cursor, monitor_list_qualified, mid_str)
    _expire_simulated_trade_state_if_needed(
        cursor, monitor_list_qualified, mid_str, now_est=datetime.now(EST)
    )

    contribution, _ = _cycle_contribution(
        cursor, trades_simulated_qualified, trades_qualified, monitor_key, cycle_date, weekly_cycle
    )
    if contribution <= 0:
        return False

    cursor.execute(
        f"""
        SELECT COALESCE(applied_units, 0) FROM {ledger_qualified}
        WHERE monitor_id = %s AND cycle_date = %s AND weekly_cycle = %s
        """,
        (int(mid_str), cycle_date, weekly_cycle),
    )
    prev_row = cursor.fetchone()
    prev_applied = int(prev_row[0]) if prev_row else 0
    delta = contribution - prev_applied
    if delta <= 0:
        return False

    cursor.execute(
        f"""
        INSERT INTO {ledger_qualified} (monitor_id, cycle_date, weekly_cycle, applied_units)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (monitor_id, cycle_date, weekly_cycle)
        DO UPDATE SET applied_units = EXCLUDED.applied_units
        """,
        (int(mid_str), cycle_date, weekly_cycle, contribution),
    )

    cursor.execute(
        f"""
        SELECT original_loss_prevention_cooldown_start_time,
               simulated_loss_prevention_cooldown_start_time,
               COALESCE(loss_prevention_cooldown_loss_count, 0)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (mid_str,),
    )
    st = cursor.fetchone()
    if not st:
        return False
    orig, _, cnt = st[0], st[1], int(st[2] or 0)
    cursor.execute(
        f"""
        SELECT {_sql_live_loss_prevention_cooldown_live_expr()}
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (mid_str,),
    )
    live_row = cursor.fetchone()
    live_throttle_active = bool(live_row and live_row[0]) and not from_replay
    # While ``live_loss_1c`` is in effect, simulated losses may still slide
    # ``simulated_loss_prevention_cooldown_start_time`` (cooldown clock) but must not change
    # ``loss_prevention_cooldown_loss_count`` so tier cannot move (e.g. to sim_loss_25).
    # ``from_replay`` rebuilds ledger + counts from history and must not use this freeze.
    # ``to_timestamp(utc_epoch)``: never pass Python ``datetime`` into ``TIMESTAMPTZ`` (psycopg2 + host TZ).
    anchor_epoch = _loss_anchor_utc_epoch(loss_anchor_ts)
    if orig is None:
        new_cnt = cnt if live_throttle_active else cnt + delta
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET original_loss_prevention_cooldown_start_time = to_timestamp(%s),
                simulated_loss_prevention_cooldown_start_time = to_timestamp(%s),
                loss_prevention_cooldown_loss_count = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (anchor_epoch, anchor_epoch, new_cnt, mid_str),
        )
    elif live_throttle_active:
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET simulated_loss_prevention_cooldown_start_time = to_timestamp(%s),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (anchor_epoch, mid_str),
        )
    else:
        cursor.execute(
            f"""
            UPDATE {monitor_list_qualified}
            SET simulated_loss_prevention_cooldown_start_time = to_timestamp(%s),
                loss_prevention_cooldown_loss_count = loss_prevention_cooldown_loss_count + %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (anchor_epoch, delta, mid_str),
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
    """After a real (non-paper) closed loss, cap sizing at 1 contract for the cooldown window."""
    cursor.execute(
        f"""
        SELECT t.monitor, t.win_loss,
               COALESCE(t.test_filter, FALSE), COALESCE(t.paper_trade, FALSE),
               {_SQL_T_CLOSE_ANCHOR_EPOCH}
        FROM {trades_qualified} AS t
        WHERE t.id = %s
        """,
        (trade_id,),
    )
    row = cursor.fetchone()
    if not row:
        return False
    monitor_key, win_loss, test_filter, paper_trade, anch_ep = (
        row[0],
        row[1],
        row[2],
        row[3],
        row[4],
    )
    if win_loss != "L" or test_filter or paper_trade:
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
    anchor_dt = _parse_ts(anch_ep)
    if anchor_dt is None:
        return False
    epoch = _loss_anchor_utc_epoch(anchor_dt)
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET live_loss_prevention_cooldown_start_time = to_timestamp(%s), updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (epoch, mid_str),
    )
    recompute_monitor_loss_prevention(cursor, monitor_list_qualified, mid_str)
    return True


def _fetch_loss_cycles_for_monitor_since(
    cursor,
    trades_qualified: str,
    trades_simulated_qualified: str,
    monitor_key: str,
    horizon_est: datetime,
) -> List[Tuple[Any, Any, datetime]]:
    hz = float(horizon_est.astimezone(timezone.utc).timestamp())
    cursor.execute(
        f"""
        SELECT s.date AS d, s.weekly_cycle AS wc,
               MAX({_sql_close_anchor_epoch("s")}) AS epoch_ts
        FROM {trades_simulated_qualified} s
        WHERE s.monitor = %s AND s.status = 'closed' AND s.win_loss = 'L'
        GROUP BY s.date, s.weekly_cycle
        HAVING MAX({_sql_close_anchor_epoch("s")}) >= %s
        ORDER BY MAX({_sql_close_anchor_epoch("s")})
        """,
        (monitor_key, hz),
    )
    out: List[Tuple[Any, Any, datetime]] = []
    for r in cursor.fetchall() or []:
        ts_parsed = _parse_ts(r[2])
        if ts_parsed:
            out.append((r[0], r[1], ts_parsed))
    return out


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
               COALESCE(simulated_trade_loss_prevention, FALSE),
               COALESCE(loss_prevention_duration, 4)
        FROM {monitor_list_qualified}
        WHERE id = %s
        """,
        (monitor_id,),
    )
    row = cursor.fetchone()
    if not row or not (bool(row[0]) and str(row[1]).strip().lower() == "time" and bool(row[2])):
        return
    dur_h = float(row[3] or 4)
    now = datetime.now(EST)
    horizon = now - timedelta(hours=dur_h)

    cursor.execute(
        f"DELETE FROM {ledger_qualified} WHERE monitor_id = %s",
        (int(monitor_id),),
    )
    cursor.execute(
        f"""
        UPDATE {monitor_list_qualified}
        SET original_loss_prevention_cooldown_start_time = NULL,
            simulated_loss_prevention_cooldown_start_time = NULL,
            loss_prevention_cooldown_loss_count = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (monitor_id,),
    )

    monitor_key = f"mon_{tenant_slot}_{monitor_id}"
    cycles = _fetch_loss_cycles_for_monitor_since(
        cursor, trades_qualified, trades_simulated_qualified, monitor_key, horizon
    )
    for cdate, wc, anch in cycles:
        apply_sim_trade_cycle_loss(
            cursor,
            monitor_list_qualified=monitor_list_qualified,
            trades_qualified=trades_qualified,
            trades_simulated_qualified=trades_simulated_qualified,
            ledger_qualified=ledger_qualified,
            tenant_slot=tenant_slot,
            monitor_key=monitor_key,
            cycle_date=cdate,
            weekly_cycle=wc,
            loss_anchor_ts=anch,
            from_replay=True,
        )


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
              AND COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
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
