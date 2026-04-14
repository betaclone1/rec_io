"""
Shared balance snapshot write path for live (Kalshi) and paper (simulated) accounts.

Keeps subaccounts + account_balance INSERT + notify/monitor_manager ripple aligned.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any, Optional, Tuple

from psycopg2 import sql

from backend.core.system_settings_store import (
    get_drawdown_trading_controls,
    parse_user_number_from_account_balance_table,
)
from backend.core.tenant_context import (
    effective_tenant_context_for_sql_rewrite,
    resolved_tenant_user_no_for_app,
)

_LOG = logging.getLogger("balance_snapshot")

_SUBACC_FQN_RE = re.compile(
    r"^users\.subaccounts(?:_paper)?_\d{4}$"
    r"|^users_(?P<s>\d{4})\.subaccounts(?:_paper)?_(?P=s)$"
)
_AB_FQN_RE = re.compile(
    r"^users\.account_balance(?:_paper)?_\d{4}$"
    r"|^users_(?P<s>\d{4})\.account_balance(?:_paper)?_(?P=s)$"
)


def _allowed_subaccounts_fqn(fqn: str) -> bool:
    return bool(fqn and _SUBACC_FQN_RE.match(str(fqn).strip()))


def _allowed_account_balance_fqn(fqn: str) -> bool:
    return bool(fqn and _AB_FQN_RE.match(str(fqn).strip()))


def _transfers_fqn_for_subaccounts_fqn(subaccounts_table: str) -> str:
    s = str(subaccounts_table).strip()
    m = re.fullmatch(r"users_(?P<slot>\d{4})\.subaccounts_paper_(?P=slot)", s)
    if m:
        u = m.group("slot")
        return f"users_{u}.transfers_paper_{u}"
    m = re.fullmatch(r"users_(?P<slot>\d{4})\.subaccounts_(?P=slot)", s)
    if m:
        u = m.group("slot")
        return f"users_{u}.transfers_{u}"
    m = re.search(r"^users\.subaccounts_paper_(\d{4})$", s)
    if m:
        u = m.group(1)
        return f"users_{u}.transfers_paper_{u}"
    m = re.search(r"^users\.subaccounts_(\d{4})$", s)
    if m:
        u = m.group(1)
        return f"users_{u}.transfers_{u}"
    raise ValueError(f"cannot derive transfers table from {subaccounts_table!r}")


def _balance_cents_int(value: Any) -> int:
    """Normalize cash balance to integer cents for DB + comparisons (column is integer)."""
    if value is None:
        return 0
    return int(round(float(value)))


def _split_fqn(fqn: str) -> Tuple[str, str]:
    parts = fqn.split(".")
    if len(parts) == 2:
        sch, tbl = parts[0], parts[1]
    else:
        sch, tbl = "users", parts[0]
    if sch == "users":
        sch = effective_tenant_context_for_sql_rewrite().pg_schema
    # Explicit users_NNNN.* (from account_balance_table_for_user, etc.): use as-is.
    return sch, tbl


def subaccounts_update(
    cursor,
    portfolio_value: int,
    *,
    subaccounts_table: str = "users.subaccounts_0001",
    record_internal_transfers: bool = True,
) -> Tuple[int, bool]:
    """
    Update PRIMARY, MTB, optional internal transfer. Same logic as kalshi_account_sync_ws.
    Returns (master_bankroll_balance, transfer_triggered).
    """
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))

    cursor.execute(
        sql.SQL("UPDATE {} SET balance = %s WHERE subaccount = 'PRIMARY'").format(ident),
        (portfolio_value,),
    )
    cursor.execute(
        sql.SQL("SELECT COALESCE(balance, 0) FROM {} WHERE subaccount = 'Cash Transfer'").format(ident),
    )
    cash_transfer_row = cursor.fetchone()
    cash_transfer_balance = int(cash_transfer_row[0]) if cash_transfer_row else 0
    master_bankroll_balance = portfolio_value - cash_transfer_balance

    cursor.execute(
        sql.SQL(
            "SELECT base_value, target_pnl__pct, transfer_amt, automatic_transfers FROM {} WHERE subaccount = 'Master Trading Bankroll'"
        ).format(ident),
    )
    mtb_row = cursor.fetchone()
    base_value = int(mtb_row[0]) if mtb_row and mtb_row[0] is not None else None
    target_pnl_pct = float(mtb_row[1]) if mtb_row and mtb_row[1] is not None else None
    transfer_amt = float(mtb_row[2]) if mtb_row and mtb_row[2] is not None else None
    automatic_transfers = bool(mtb_row[3]) if mtb_row and mtb_row[3] is not None else False

    if base_value is not None and base_value != 0:
        realized_pnl = master_bankroll_balance - base_value
        ratio = (master_bankroll_balance - base_value) / base_value
        realized_pnl_pct = float(int(ratio * 10000)) / 10000.0
    else:
        realized_pnl = None
        realized_pnl_pct = None

    cursor.execute(
        sql.SQL(
            "UPDATE {} SET balance = %s, realized_pnl = %s, realized_pnl_pct = %s WHERE subaccount = 'Master Trading Bankroll'"
        ).format(ident),
        (master_bankroll_balance, realized_pnl, realized_pnl_pct),
    )

    transfer_triggered = False
    post_transfer_realized_pnl = None
    post_transfer_realized_pnl_pct = None

    if (
        record_internal_transfers
        and automatic_transfers
        and base_value is not None
        and base_value != 0
        and target_pnl_pct is not None
        and transfer_amt is not None
        and realized_pnl_pct is not None
        and realized_pnl_pct >= target_pnl_pct
    ):
        transfer_amount = int(round(transfer_amt * base_value))
        new_cash_transfer_balance = cash_transfer_balance + transfer_amount
        cursor.execute(
            sql.SQL("UPDATE {} SET balance = %s WHERE subaccount = 'Cash Transfer'").format(ident),
            (new_cash_transfer_balance,),
        )
        new_mtb_balance = portfolio_value - new_cash_transfer_balance
        base_step_pct = target_pnl_pct - transfer_amt
        new_base_value = int(round(base_value * (1 + base_step_pct)))
        post_transfer_realized_pnl = new_mtb_balance - new_base_value
        post_transfer_ratio = (new_mtb_balance - new_base_value) / new_base_value if new_base_value else 0
        post_transfer_realized_pnl_pct = float(int(post_transfer_ratio * 10000)) / 10000.0
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET balance = %s, base_value = %s, realized_pnl = %s, realized_pnl_pct = %s WHERE subaccount = 'Master Trading Bankroll'"
            ).format(ident),
            (new_mtb_balance, new_base_value, post_transfer_realized_pnl, post_transfer_realized_pnl_pct),
        )
        master_bankroll_balance = new_mtb_balance
        transfer_triggered = True
        from backend.core.time_eastern import now_est

        transfer_timestamp_est = now_est().strftime("%Y-%m-%d %H:%M:%S")
        xfer_row = (
            transfer_timestamp_est,
            "internal",
            "Master Trading Bankroll",
            "Cash Transfer",
            transfer_amount,
            "automatic",
        )
        xfer_tbl = _transfers_fqn_for_subaccounts_fqn(subaccounts_table)
        cursor.execute(
            f"""
            INSERT INTO {xfer_tbl} (timestamp, type, "from", "to", amount, initiated)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            xfer_row,
        )

    return (master_bankroll_balance, transfer_triggered)


def get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table: str = "users.subaccounts_0001") -> Tuple[Optional[int], Optional[int]]:
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL("SELECT balance, base_value FROM {} WHERE subaccount = 'Master Trading Bankroll'").format(ident),
    )
    row = cursor.fetchone()
    if not row:
        return None, None
    balance, base_value = row
    return (
        int(balance) if balance is not None else None,
        int(base_value) if base_value is not None else None,
    )


def apply_balance_snapshot(
    cursor,
    *,
    balance_amount: Any,
    portfolio_value_raw: Any,
    positions_value: int,
    total_exposure: int,
    portfolio_value: int,
    account_balance_table: str,
    subaccounts_table: str,
    current_timestamp: str,
    throttle: bool = True,
    notify_db_name: str = "account_balance",
    record_internal_transfers: bool = True,
    paper_bankroll_force_match: bool = False,
) -> Tuple[bool, bool]:
    """
    One full tick: ratchet bankroll, optional INSERT, notify frontend + monitor_manager.
    Returns (inserted_new_row, bankroll_stepped_down).

    ``paper_bankroll_force_match`` (paper only): set ``bankroll_current`` to MTB / portfolio for this
    tick instead of the sticky ratchet — used when the user explicitly seeds paper bankroll so a
    lower total is not masked by the previous row's ``bankroll_current``.
    """
    if not _allowed_account_balance_fqn(account_balance_table):
        raise ValueError(f"Invalid account_balance table: {account_balance_table}")
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")

    paper_ab = "_paper_" in account_balance_table
    paper_sa = "_paper_" in subaccounts_table
    if paper_ab != paper_sa:
        raise ValueError(
            "account_balance and subaccounts must both be live or both paper (matching slot): "
            f"{account_balance_table!r} vs {subaccounts_table!r}"
        )
    u_ab = parse_user_number_from_account_balance_table(account_balance_table)
    u_sa = parse_user_number_from_account_balance_table(subaccounts_table)
    if u_ab != u_sa:
        raise ValueError(
            f"account_balance slot {u_ab!r} != subaccounts slot {u_sa!r}: "
            f"{account_balance_table!r} vs {subaccounts_table!r}"
        )
    is_paper = paper_ab

    balance_amount = _balance_cents_int(balance_amount)
    # Paper simulates Kalshi GET /portfolio/balance: balance = cash, portfolio_value = open-position mark, both >= 0.
    if is_paper:
        pos_mark = max(0, int(round(float(portfolio_value_raw))))
        positions_value = pos_mark
        total_exposure = pos_mark
        portfolio_value_raw = pos_mark
        portfolio_value = balance_amount + pos_mark
    else:
        positions_value = int(positions_value)
        total_exposure = int(total_exposure)
        portfolio_value_raw = int(round(float(portfolio_value_raw)))
        portfolio_value = int(portfolio_value)

    ab_sch, ab_tbl = _split_fqn(account_balance_table)
    ab_ident = sql.SQL("{}.{}").format(sql.Identifier(ab_sch), sql.Identifier(ab_tbl))

    cursor.execute(
        sql.SQL("SELECT portfolio, bankroll_current FROM {} ORDER BY id DESC LIMIT 1").format(ab_ident),
    )
    prev_result = cursor.fetchone()
    prev_bankroll = prev_result[1] if prev_result else None

    user_no = parse_user_number_from_account_balance_table(account_balance_table)
    drawdown_halt_on, drawdown_pct = get_drawdown_trading_controls(
        cursor, user_number=user_no or resolved_tenant_user_no_for_app()
    )
    try:
        _dd_ratio = float((100.0 - float(drawdown_pct)) / 100.0)
    except (TypeError, ValueError):
        _dd_ratio = 0.5

    bankroll_stepped_down = False
    # Live: only ripple subaccounts when flat (matches historical Kalshi sync behavior).
    # Paper: ripple every tick so PRIMARY/MTB match simulated total portfolio like a real balance payload.
    if positions_value == 0 or is_paper:
        master_bankroll_balance, transfer_triggered = subaccounts_update(
            cursor,
            portfolio_value,
            subaccounts_table=subaccounts_table,
            record_internal_transfers=record_internal_transfers,
        )
        if transfer_triggered:
            bankroll_current = master_bankroll_balance
        elif paper_bankroll_force_match and is_paper:
            # User seed / explicit reset: do not keep a sticky bankroll above the new portfolio total.
            bankroll_current = master_bankroll_balance
        else:
            # Step down when MTB <= (1 - drawdown_pct/100) * sticky bankroll (if drawdown_trading_halt on).
            drawdown_threshold = (int(round(prev_bankroll * _dd_ratio)) if prev_bankroll else None)
            if prev_bankroll is None:
                bankroll_current = master_bankroll_balance
            elif master_bankroll_balance > prev_bankroll:
                bankroll_current = master_bankroll_balance
            elif (
                drawdown_halt_on
                and drawdown_threshold is not None
                and master_bankroll_balance <= drawdown_threshold
            ):
                bankroll_current = master_bankroll_balance
                if prev_bankroll > drawdown_threshold:
                    bankroll_stepped_down = True
            else:
                bankroll_current = prev_bankroll
    else:
        bankroll_current = prev_bankroll if prev_bankroll is not None else portfolio_value

    skip_balance_write = False
    if throttle:
        cursor.execute(
            sql.SQL(
                """
                SELECT balance, exposure, positions, portfolio, bankroll_current,
                       EXTRACT(EPOCH FROM (NOW() - created_at)) AS age_seconds
                FROM {} ORDER BY id DESC LIMIT 1
                """
            ).format(ab_ident),
        )
        last_row = cursor.fetchone()
        if last_row:
            last_balance, last_exposure, last_positions, last_portfolio, last_bankroll, age_seconds = last_row
            if age_seconds is not None and age_seconds < 120 and (
                _balance_cents_int(last_balance) == balance_amount
                and int(last_exposure or 0) == int(total_exposure or 0)
                and int(last_positions or 0) == positions_value
                and int(last_portfolio or 0) == portfolio_value
                and int(last_bankroll or 0) == bankroll_current
            ):
                skip_balance_write = True
                _LOG.debug("Balance unchanged (throttled), skip insert")

    if skip_balance_write:
        return False, bankroll_stepped_down

    mtb_balance, mtb_base = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)
    cursor.execute(
        sql.SQL(
            """
            INSERT INTO {} (
                balance, exposure, positions, portfolio, bankroll_current,
                portfolio_value, "timestamp", master_trading_bankroll, mtb_base_value,
                created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            """
        ).format(ab_ident),
        (
            balance_amount,
            total_exposure,
            positions_value,
            portfolio_value,
            bankroll_current,
            portfolio_value_raw,
            current_timestamp,
            mtb_balance,
            mtb_base,
        ),
    )

    from backend.kalshi_account_sync_ws import notify_frontend_db_change, notify_monitor_manager

    total_portfolio_value = int(balance_amount or 0) + int(portfolio_value_raw or 0)
    notify_frontend_db_change(
        notify_db_name,
        {
            "balance": balance_amount,
            "exposure": total_exposure,
            "positions": positions_value,
            "portfolio": portfolio_value,
            "portfolio_value_raw": portfolio_value_raw,
            "total_portfolio": total_portfolio_value,
        },
    )
    # monitor_manager: update bankroll_allotment_total + total_position per monitor (live or paper table).
    notify_monitor_manager(bankroll_stepped_down=bankroll_stepped_down)
    return True, bankroll_stepped_down


def estimate_kalshi_taker_fee_dollars(position: int, price: float) -> float:
    """Same formula as trade_manager.estimate_kalshi_taker_fee (taker leg, dollars)."""
    if position is None or int(position) <= 0 or price is None or float(price) <= 0 or float(price) >= 1:
        return 0.0
    raw = 0.07 * int(position) * float(price) * (1.0 - float(price))
    return math.ceil(raw * 100) / 100


def paper_open_cost_and_fee_cents(buy_price: float, position: int, open_fee_dollars: float) -> Tuple[int, int]:
    """Premium (position mark) in cents, and open fee in cents."""
    cost_cents = int(round(float(buy_price) * int(position) * 100.0))
    fee_cents = int(round(float(open_fee_dollars) * 100.0))
    return cost_cents, fee_cents


def paper_close_adjust_cents(buy_price: float, position: int, pnl_dollars: float) -> Tuple[int, int, int]:
    """
    Return (cost_basis_cents, balance_delta_cents, positions_delta_cents) for a closed paper trade.
    balance increases by cost_basis + pnl (in cents); positions decrease by cost_basis.
    """
    cost_cents = int(round(float(buy_price) * int(position) * 100.0))
    pnl_cents = int(round(float(pnl_dollars) * 100.0))
    return cost_cents, cost_cents + pnl_cents, -cost_cents


def read_last_paper_cash_and_positions() -> Optional[Tuple[int, int]]:
    """Latest paper row: (cash_cents, open_position_mark_cents) per Kalshi shape, or None."""
    from backend.core.config.database import get_postgresql_connection
    from backend.trading_mode import paper_account_balance_fqn

    slot = resolved_tenant_user_no_for_app()
    ab = paper_account_balance_fqn(slot)
    sch, tbl = ab.split(".", 1)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT balance, COALESCE(positions, 0)
                    FROM {}
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).format(ident)
            )
            row = cur.fetchone()
            if not row:
                return None
            return int(row[0]), int(row[1])
    finally:
        conn.close()


def read_last_paper_portfolio_total_cents() -> Optional[int]:
    """Latest total equity (``portfolio`` column) from paper balance history, or None."""
    from backend.core.config.database import get_postgresql_connection
    from backend.trading_mode import paper_account_balance_fqn

    slot = resolved_tenant_user_no_for_app()
    ab = paper_account_balance_fqn(slot)
    sch, tbl = ab.split(".", 1)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT portfolio
                    FROM {}
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).format(ident)
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return None
            return int(row[0])
    finally:
        conn.close()


def read_paper_primary_total_cents() -> Optional[int]:
    """PRIMARY subaccount balance (total portfolio target) when no AB row exists yet."""
    from backend.core.config.database import get_postgresql_connection
    from backend.trading_mode import paper_subaccounts_fqn

    slot = resolved_tenant_user_no_for_app()
    sa = paper_subaccounts_fqn(slot)
    sch, tbl = sa.split(".", 1)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    """
                    SELECT COALESCE(balance, 0)
                    FROM {}
                    WHERE subaccount = 'PRIMARY'
                    """
                ).format(ident)
            )
            row = cur.fetchone()
            if not row:
                return None
            return int(row[0])
    finally:
        conn.close()


def _sum_open_paper_positions_mark_cents_from_full_rows(rows: Any) -> int:
    """Net YES/NO premium per ticker (FIFO pairing); see ``backend.paper_collateral``."""
    from backend.paper_collateral import netted_open_premium_cents_from_rows

    return netted_open_premium_cents_from_rows(rows or [])


def sum_open_paper_positions_mark_cents() -> int:
    """
    Kalshi ``portfolio_value`` analog: netted open-premium cents (YES/NO paired per ticker
    FIFO), not a naive sum of per-trade marks.
    """
    from backend.core.config.database import get_postgresql_connection

    slot = resolved_tenant_user_no_for_app()
    conn = get_postgresql_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, side, buy_price, "position"
                FROM users.trades_{slot}
                WHERE paper_trade IS TRUE
                  AND status IN ('open', 'closing', 'close_failed')
                  AND buy_price IS NOT NULL
                  AND "position" IS NOT NULL
                ORDER BY id ASC
                """
            )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    return _sum_open_paper_positions_mark_cents_from_full_rows(rows)


def _sum_open_paper_positions_mark_cents_cursor(cursor, slot: str) -> int:
    cursor.execute(
        f"""
        SELECT id, ticker, side, buy_price, "position"
        FROM users.trades_{slot}
        WHERE paper_trade IS TRUE
          AND status IN ('open', 'closing', 'close_failed')
          AND buy_price IS NOT NULL
          AND "position" IS NOT NULL
        ORDER BY id ASC
        """
    )
    return _sum_open_paper_positions_mark_cents_from_full_rows(cursor.fetchall())


def _paper_aggregate_xact_lock(cursor, slot: str) -> None:
    """
    Serialize paper aggregate snapshot writers (seed, open/close sync, manual apply) so one session
    cannot read an old ``portfolio`` and INSERT after another session has already committed a newer
    row (READ COMMITTED allows that without a lock).
    """
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s::text))",
        (f"rec:paper_balance_agg:{slot}",),
    )


def _paper_equity_baseline_cents_cursor(cursor, ab_ident, sa_ident) -> Optional[int]:
    """
    Total equity in cents for paper open/close math: **latest** ``account_balance_paper`` row by
    ``id`` (same ordering as :func:`apply_balance_snapshot` uses for ``bankroll_current``).

    ``FOR UPDATE`` locks that predecessor row until commit so this baseline stays tied to the row
    we are extending. Call only after :func:`_paper_aggregate_xact_lock` so writers are serialized.

    If the paper balance table is empty, fall back to ``subaccounts_paper.PRIMARY`` (bootstrap).
    """
    cursor.execute(
        sql.SQL("SELECT portfolio FROM {} ORDER BY id DESC LIMIT 1 FOR UPDATE").format(ab_ident)
    )
    row = cursor.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    cursor.execute(
        sql.SQL("SELECT balance FROM {} WHERE subaccount = 'PRIMARY' LIMIT 1").format(sa_ident)
    )
    prow = cursor.fetchone()
    if prow is not None and prow[0] is not None:
        return int(prow[0])
    return None


def _ensure_tx_connection(conn) -> None:
    """Paper snapshot paths must not use autocommit (advisory lock + multi-statement atomicity)."""
    raw = getattr(conn, "_conn", conn)
    try:
        raw.autocommit = False
    except Exception:
        pass


def _run_paper_balance_snapshot_tx(
    cursor,
    *,
    balance_cents: int,
    positions_cents: int,
    throttle: bool,
    bankroll_force_match: bool,
    current_timestamp: str,
) -> Tuple[bool, bool]:
    from backend.trading_mode import paper_account_balance_fqn, paper_subaccounts_fqn

    slot = resolved_tenant_user_no_for_app()
    cash = int(balance_cents)
    pos = max(0, int(positions_cents))
    pv = cash + pos
    return apply_balance_snapshot(
        cursor,
        balance_amount=cash,
        portfolio_value_raw=pos,
        positions_value=pos,
        total_exposure=pos,
        portfolio_value=pv,
        account_balance_table=paper_account_balance_fqn(slot),
        subaccounts_table=paper_subaccounts_fqn(slot),
        current_timestamp=current_timestamp,
        throttle=throttle,
        notify_db_name="account_balance_paper",
        record_internal_transfers=True,
        paper_bankroll_force_match=bankroll_force_match,
    )


def sync_paper_balance_feed_after_open(open_fee_cents: int) -> bool:
    """
    Mimic one Kalshi balance poll after a paper open (DB row already ``open``).

    - ``positions`` = netted open-premium marks (YES/NO FIFO paired per ``ticker``; source of truth).
    - ``total_equity`` = previous total equity minus open fees (premium is neutral to total).
      Baseline is the latest ``account_balance_paper`` row by ``id`` (see
      :func:`_paper_equity_baseline_cents_cursor`).
    - ``balance`` (cash) = ``total_equity - positions`` (then ``apply_balance_snapshot`` like live).

    Read + insert run in **one transaction** with an advisory lock. Live Kalshi sync must never
    write to paper tables (see ``account_balance_table_for_user(..., force_live=True)`` in
    ``kalshi_account_sync_ws``); otherwise REST balance polls would overwrite simulated history.
    """
    from backend.core.config.database import get_postgresql_connection
    from backend.core.time_eastern import now_est
    from backend.trading_mode import paper_account_balance_fqn, paper_subaccounts_fqn

    slot = resolved_tenant_user_no_for_app()
    ab_sch, ab_tbl = paper_account_balance_fqn(slot).split(".", 1)
    sa_sch, sa_tbl = paper_subaccounts_fqn(slot).split(".", 1)
    ab_ident = sql.SQL("{}.{}").format(sql.Identifier(ab_sch), sql.Identifier(ab_tbl))
    sa_ident = sql.SQL("{}.{}").format(sql.Identifier(sa_sch), sql.Identifier(sa_tbl))

    conn = get_postgresql_connection()
    if not conn:
        return False
    _ensure_tx_connection(conn)
    ts = now_est().isoformat()
    try:
        with conn.cursor() as cursor:
            _paper_aggregate_xact_lock(cursor, slot)
            positions = _sum_open_paper_positions_mark_cents_cursor(cursor, slot)
            total = _paper_equity_baseline_cents_cursor(cursor, ab_ident, sa_ident)
            if total is None:
                return False
            total = int(total) - max(0, int(open_fee_cents))
            cash = total - int(positions)
            ins, _ = _run_paper_balance_snapshot_tx(
                cursor,
                balance_cents=cash,
                positions_cents=positions,
                throttle=False,
                bankroll_force_match=False,
                current_timestamp=ts,
            )
        conn.commit()
        return ins
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sync_paper_balance_feed_after_close(pnl_cents: int, buy_price: float, position: int) -> bool:
    """
    Mimic one Kalshi balance poll after a paper close (row already ``closed`` in DB).

    Trade rows store ``pnl`` net of **all** fees (open + close). On open we already applied
    ``total_equity -= open_fee`` (see ``sync_paper_balance_feed_after_open``). So the delta from
    ``T_after_open`` to ``T_after_close`` is ``pnl + open_fee``, not ``pnl`` alone — otherwise the
    open fee is double-counted and paper ``portfolio`` drifts from realized PnL (often by the sum
    of open fees across closed trades).

    Algebra: ``T_close = T_open + pnl + F_open`` with ``T_open = S - F_open`` gives ``T_close = S + pnl``.

    Same single-transaction read+write as open; baseline is latest paper row by ``id`` like open.
    """
    from backend.core.config.database import get_postgresql_connection
    from backend.core.time_eastern import now_est
    from backend.trading_mode import paper_account_balance_fqn, paper_subaccounts_fqn

    slot = resolved_tenant_user_no_for_app()
    ab_sch, ab_tbl = paper_account_balance_fqn(slot).split(".", 1)
    sa_sch, sa_tbl = paper_subaccounts_fqn(slot).split(".", 1)
    ab_ident = sql.SQL("{}.{}").format(sql.Identifier(ab_sch), sql.Identifier(ab_tbl))
    sa_ident = sql.SQL("{}.{}").format(sql.Identifier(sa_sch), sql.Identifier(sa_tbl))

    conn = get_postgresql_connection()
    if not conn:
        return False
    _ensure_tx_connection(conn)
    ts = now_est().isoformat()
    open_fee_cents = int(round(estimate_kalshi_taker_fee_dollars(int(position), float(buy_price)) * 100.0))
    try:
        with conn.cursor() as cursor:
            _paper_aggregate_xact_lock(cursor, slot)
            positions = _sum_open_paper_positions_mark_cents_cursor(cursor, slot)
            total = _paper_equity_baseline_cents_cursor(cursor, ab_ident, sa_ident)
            if total is None:
                return False
            total = int(total) + int(pnl_cents) + int(open_fee_cents)
            cash = total - int(positions)
            ins, _ = _run_paper_balance_snapshot_tx(
                cursor,
                balance_cents=cash,
                positions_cents=positions,
                throttle=False,
                bankroll_force_match=False,
                current_timestamp=ts,
            )
        conn.commit()
        return ins
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_paper_aggregate_snapshot(
    *,
    balance_cents: int,
    positions_cents: int,
    throttle: bool = False,
    bankroll_force_match: bool = False,
) -> bool:
    """
    Simulated Kalshi GET /portfolio/balance snapshot (cents).
    Writes the current tenant's paper ``account_balance_paper_<slot>`` and ``subaccounts_paper_<slot>`` (never live tables).

    - balance column = **cash** (settled, available — what Kalshi calls ``balance``).
    - positions / exposure = **open-position mark** (>= 0, same value for both; Kalshi ``portfolio_value``).
    - portfolio column = cash + open-position mark (total equity).

    Those Kalshi-shaped columns are **only** derived from cash + open marks; internal MTB↔Cash Transfer
    rules never change ``balance`` / ``portfolio`` / ``positions`` / ``exposure`` on the row.

    Subaccounts_paper still run full ``subaccounts_update`` (including automatic internal transfers when
    enabled). Transfers move slices between MTB and Cash Transfer and affect ``bankroll_current`` /
    monitor bankroll — the same as live — without mutating total portfolio or cash+positions math.
    """
    from backend.core.config.database import get_postgresql_connection
    from backend.core.time_eastern import now_est

    cash = int(balance_cents)
    pos = max(0, int(positions_cents))
    conn = get_postgresql_connection()
    if not conn:
        return False
    _ensure_tx_connection(conn)
    ts = now_est().isoformat()
    inserted = False
    try:
        with conn.cursor() as cursor:
            slot = resolved_tenant_user_no_for_app()
            _paper_aggregate_xact_lock(cursor, slot)
            ins, _ = _run_paper_balance_snapshot_tx(
                cursor,
                balance_cents=cash,
                positions_cents=pos,
                throttle=throttle,
                bankroll_force_match=bankroll_force_match,
                current_timestamp=ts,
            )
            inserted = ins
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return inserted


def insert_account_balance_snapshot_after_mtb_subaccount_internal_transfer(
    *,
    account_balance_table: str,
    subaccounts_table: str,
    notify_db_name: str,
) -> bool:
    """
    After subaccounts are updated by a manual internal transfer that changes the Master Trading
    Bankroll slice, append one ``account_balance`` / ``account_balance_paper`` row: same
    balance / exposure / positions / portfolio / portfolio_value as the latest row, but set
    ``bankroll_current`` and ``master_trading_bankroll`` to the current MTB balance from
    subaccounts (and ``mtb_base_value`` from MTB's base_value). Then notify the frontend and
    ``monitor_manager`` so monitor allocations refresh. Live and paper use the same shape.
    """
    if not _allowed_account_balance_fqn(account_balance_table):
        raise ValueError(f"Invalid account_balance table: {account_balance_table}")
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")

    from backend.core.config.database import get_postgresql_connection
    from backend.core.time_eastern import now_est

    ab_sch, ab_tbl = _split_fqn(account_balance_table)
    ab_ident = sql.SQL("{}.{}").format(sql.Identifier(ab_sch), sql.Identifier(ab_tbl))

    conn = get_postgresql_connection()
    if not conn:
        return False
    _ensure_tx_connection(conn)
    ts = now_est().isoformat()
    payload_notify: Optional[dict] = None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    """
                    SELECT balance, exposure, positions, portfolio, COALESCE(portfolio_value, 0)
                    FROM {}
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).format(ab_ident)
            )
            prev = cursor.fetchone()
            if not prev:
                conn.rollback()
                _LOG.warning(
                    "insert_account_balance_snapshot_after_mtb_subaccount_internal_transfer: no prior row in %s",
                    account_balance_table,
                )
                return False

            balance_amount, exposure_v, positions_v, portfolio_v, portfolio_value_raw = prev
            mtb_balance, mtb_base = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)
            if mtb_balance is None:
                conn.rollback()
                _LOG.warning(
                    "insert_account_balance_snapshot_after_mtb_subaccount_internal_transfer: no MTB row in %s",
                    subaccounts_table,
                )
                return False

            bankroll_current = int(mtb_balance)
            master_trading_bankroll = int(mtb_balance)
            bal_i = _balance_cents_int(balance_amount)
            exp_i = int(exposure_v or 0)
            pos_i = int(positions_v or 0)
            ptf_i = int(portfolio_v or 0)
            pvr_i = int(portfolio_value_raw or 0)

            cursor.execute(
                sql.SQL(
                    """
                    INSERT INTO {} (
                        balance, exposure, positions, portfolio, bankroll_current,
                        portfolio_value, "timestamp", master_trading_bankroll, mtb_base_value,
                        created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    """
                ).format(ab_ident),
                (
                    bal_i,
                    exp_i,
                    pos_i,
                    ptf_i,
                    bankroll_current,
                    pvr_i,
                    ts,
                    master_trading_bankroll,
                    int(mtb_base) if mtb_base is not None else None,
                ),
            )
        conn.commit()
        payload_notify = {
            "balance": bal_i,
            "exposure": exp_i,
            "positions": pos_i,
            "portfolio": ptf_i,
            "portfolio_value_raw": pvr_i,
            "total_portfolio": bal_i + pvr_i,
            "source": "internal_mtb_transfer",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not payload_notify:
        return False

    from backend.kalshi_account_sync_ws import notify_frontend_db_change, notify_monitor_manager

    notify_frontend_db_change(notify_db_name, payload_notify)
    notify_monitor_manager(bankroll_stepped_down=False)
    return True
