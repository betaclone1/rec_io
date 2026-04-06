"""
Shared balance snapshot write path for live (Kalshi) and paper (simulated) accounts.

Keeps subaccounts + account_balance INSERT + notify/monitor_manager ripple aligned.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, Tuple

from psycopg2 import sql

_LOG = logging.getLogger("balance_snapshot")

_SUBALLOW = frozenset({"users.subaccounts_0001", "users.subaccounts_paper_0001"})
_ABALLOW = frozenset({"users.account_balance_0001", "users.account_balance_paper_0001"})


def _balance_cents_int(value: Any) -> int:
    """Normalize cash balance to integer cents for DB + comparisons (column is integer)."""
    if value is None:
        return 0
    return int(round(float(value)))


def _split_fqn(fqn: str) -> Tuple[str, str]:
    parts = fqn.split(".")
    if len(parts) == 2:
        return parts[0], parts[1]
    return "users", parts[0]


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
    if subaccounts_table not in _SUBALLOW:
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
        if subaccounts_table == "users.subaccounts_0001":
            from backend.core.time_eastern import now_est

            transfer_timestamp_est = now_est().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                """
                INSERT INTO users.transfers_0001 (timestamp, type, "from", "to", amount, initiated)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    transfer_timestamp_est,
                    "internal",
                    "Master Trading Bankroll",
                    "Cash Transfer",
                    transfer_amount,
                    "automatic",
                ),
            )

    return (master_bankroll_balance, transfer_triggered)


def get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table: str = "users.subaccounts_0001") -> Tuple[Optional[int], Optional[int]]:
    if subaccounts_table not in _SUBALLOW:
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
) -> Tuple[bool, bool]:
    """
    One full tick: ratchet bankroll, optional INSERT, notify frontend + monitor_manager.
    Returns (inserted_new_row, bankroll_stepped_down).
    """
    if account_balance_table not in _ABALLOW:
        raise ValueError(f"Invalid account_balance table: {account_balance_table}")
    if subaccounts_table not in _SUBALLOW:
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")

    paper_ab = account_balance_table == "users.account_balance_paper_0001"
    paper_sa = subaccounts_table == "users.subaccounts_paper_0001"
    if paper_ab != paper_sa:
        raise ValueError(
            "account_balance and subaccounts must both be live (_0001) or both paper (_paper_0001): "
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
        else:
            drawdown_threshold = (prev_bankroll * 0.7) if prev_bankroll else None
            if prev_bankroll is None:
                bankroll_current = master_bankroll_balance
            elif master_bankroll_balance > prev_bankroll:
                bankroll_current = master_bankroll_balance
            elif drawdown_threshold is not None and master_bankroll_balance <= drawdown_threshold:
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
                portfolio_value, timestamp, master_trading_bankroll, mtb_base_value
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT balance, COALESCE(positions, 0)
                FROM users.account_balance_paper_0001
                ORDER BY id DESC
                LIMIT 1
                """
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

    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT portfolio
                FROM users.account_balance_paper_0001
                ORDER BY id DESC
                LIMIT 1
                """
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

    conn = get_postgresql_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(balance, 0)
                FROM users.subaccounts_paper_0001
                WHERE subaccount = 'PRIMARY'
                """
            )
            row = cur.fetchone()
            if not row:
                return None
            return int(row[0])
    finally:
        conn.close()


def sum_open_paper_positions_mark_cents() -> int:
    """
    Kalshi ``portfolio_value`` analog: sum of position marks (premium in cents) for all
    non-closed paper trades, using the same rounding as premium math elsewhere.
    """
    from backend.core.config.database import get_postgresql_connection

    conn = get_postgresql_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT buy_price, position
                FROM users.trades_0001
                WHERE paper_trade IS TRUE
                  AND status IN ('open', 'closing', 'close_failed')
                  AND buy_price IS NOT NULL
                  AND "position" IS NOT NULL
                """
            )
            rows = cur.fetchall() or []
    finally:
        conn.close()

    total = 0
    for bp, pos in rows:
        try:
            total += int(round(float(bp) * int(pos) * 100.0))
        except (TypeError, ValueError):
            continue
    return max(0, total)


def sync_paper_balance_feed_after_open(open_fee_cents: int) -> bool:
    """
    Mimic one Kalshi balance poll after a paper open (DB row already ``open``).

    - ``positions`` = aggregate marks from open paper trades (source of truth).
    - ``total_equity`` = previous ``portfolio`` minus open fees (premium is neutral to total).
    - ``balance`` (cash) = ``total_equity - positions`` (then ``apply_balance_snapshot`` like live).
    """
    positions = sum_open_paper_positions_mark_cents()
    total = read_last_paper_portfolio_total_cents()
    if total is None:
        total = read_paper_primary_total_cents()
    if total is None:
        return False
    total = int(total) - max(0, int(open_fee_cents))
    cash = total - int(positions)
    return apply_paper_aggregate_snapshot(
        balance_cents=cash,
        positions_cents=positions,
        throttle=False,
    )


def sync_paper_balance_feed_after_close(pnl_cents: int) -> bool:
    """
    Mimic one Kalshi balance poll after a paper close (row already ``closed`` in DB).

    ``positions`` excludes the closed trade; ``total_equity`` increases by realized PnL (cents, net).
    """
    positions = sum_open_paper_positions_mark_cents()
    total = read_last_paper_portfolio_total_cents()
    if total is None:
        total = read_paper_primary_total_cents()
    if total is None:
        return False
    total = int(total) + int(pnl_cents)
    cash = total - int(positions)
    return apply_paper_aggregate_snapshot(
        balance_cents=cash,
        positions_cents=positions,
        throttle=False,
    )


def apply_paper_aggregate_snapshot(
    *,
    balance_cents: int,
    positions_cents: int,
    throttle: bool = False,
) -> bool:
    """
    Simulated Kalshi GET /portfolio/balance snapshot (cents).
    **Only** writes ``users.account_balance_paper_0001`` and ``users.subaccounts_paper_0001`` (never live _0001).

    - balance column = **cash** (settled, available — what Kalshi calls ``balance``).
    - positions / exposure = **open-position mark** (>= 0, same value for both; Kalshi ``portfolio_value``).
    - portfolio column = cash + open-position mark (total equity).

    Subaccounts_paper are updated every tick (unlike live, where ripple is flat-only).
    """
    from backend.core.config.database import get_postgresql_connection
    from backend.core.time_eastern import now_est

    cash = int(balance_cents)
    pos = max(0, int(positions_cents))
    portfolio_value = cash + pos
    conn = get_postgresql_connection()
    if not conn:
        return False
    ts = now_est().isoformat()
    inserted = False
    try:
        with conn.cursor() as cursor:
            ins, _ = apply_balance_snapshot(
                cursor,
                balance_amount=cash,
                portfolio_value_raw=pos,
                positions_value=pos,
                total_exposure=pos,
                portfolio_value=portfolio_value,
                account_balance_table="users.account_balance_paper_0001",
                subaccounts_table="users.subaccounts_paper_0001",
                current_timestamp=ts,
                throttle=throttle,
                notify_db_name="account_balance_paper",
                record_internal_transfers=False,
            )
            inserted = ins
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return inserted
