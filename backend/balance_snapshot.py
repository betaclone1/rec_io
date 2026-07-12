"""
Shared balance snapshot write path for live (Kalshi) and paper (simulated) accounts.

Keeps subaccounts + account_balance INSERT + notify/monitor_manager ripple aligned.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

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


def drawdown_halt_applies_to_balance_table(account_balance_table: str) -> bool:
    """
    Emergency drawdown halts use balances that match global trading mode only.

    Global LIVE → live ``account_balance_*`` / subaccount rows only.
    Global PAPER → paper ``account_balance_paper_*`` rows only.
    """
    from backend.trading_mode import get_trading_mode

    is_paper_table = "_paper_" in str(account_balance_table)
    mode = get_trading_mode()
    if mode == "paper":
        return is_paper_table
    return not is_paper_table


def _drawdown_stepped_down_for_halt(
    account_balance_table: str,
    bankroll_stepped_down: bool,
) -> bool:
    if not bankroll_stepped_down:
        return False
    if drawdown_halt_applies_to_balance_table(account_balance_table):
        return True
    from backend.trading_mode import get_trading_mode

    _LOG.debug(
        "Ignoring drawdown step-down for halt (table=%s global_mode=%s)",
        account_balance_table,
        get_trading_mode(),
    )
    return False


_SUBACC_FQN_RE = re.compile(
    r"^users\.subaccounts(?:_paper)?_\d{4}$"
    r"|^users_(?P<s>\d{4})\.subaccounts(?:_paper)?_(?P=s)$"
)
_AB_FQN_RE = re.compile(
    r"^users\.account_balance(?:_paper)?_\d{4}$"
    r"|^users_(?P<s>\d{4})\.account_balance(?:_paper)?_(?P=s)$"
)
_SAB_FQN_RE = re.compile(
    r"^users\.subaccount_balance_\d{4}_\d+$"
    r"|^users_(?P<s>\d{4})\.subaccount_balance_(?P=s)_\d+$"
)


def _allowed_subaccounts_fqn(fqn: str) -> bool:
    return bool(fqn and _SUBACC_FQN_RE.match(str(fqn).strip()))


def _allowed_account_balance_fqn(fqn: str) -> bool:
    f = str(fqn).strip()
    return bool(f and (_AB_FQN_RE.match(f) or _SAB_FQN_RE.match(f)))


def _is_subaccount_balance_fqn(fqn: str) -> bool:
    return bool(fqn and _SAB_FQN_RE.match(str(fqn).strip()))


def _subaccount_number_from_balance_fqn(fqn: str) -> Optional[int]:
    m = re.search(r"_(\d+)$", str(fqn).strip())
    if not m:
        return None
    return int(m.group(1))


def ensure_subaccount_balance_table(cursor, table_fqn: str) -> None:
    """CREATE TABLE IF NOT EXISTS subaccount_balance_<slot>_<n> LIKE account_balance_<slot>."""
    if not _is_subaccount_balance_fqn(table_fqn):
        raise ValueError(f"not a subaccount_balance table: {table_fqn!r}")
    sch, tbl = _split_fqn(table_fqn)
    slot_m = re.search(r"subaccount_balance_(\d{4})_\d+$", tbl)
    if not slot_m:
        raise ValueError(f"cannot parse slot from {table_fqn!r}")
    slot = slot_m.group(1)
    ab_tbl = f"account_balance_{slot}"
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        """,
        (sch, tbl),
    )
    if cursor.fetchone():
        return
    cursor.execute(
        sql.SQL("CREATE TABLE {} (LIKE {}.{} INCLUDING ALL)").format(
            ident,
            sql.Identifier(sch),
            sql.Identifier(ab_tbl),
        )
    )
    _LOG.info("Created subaccount balance table %s", table_fqn)


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
        sql.SQL("UPDATE {} SET balance = %s WHERE subaccount = 'CASH'").format(ident),
        (portfolio_value,),
    )
    cursor.execute(
        sql.SQL("SELECT COALESCE(balance, 0) FROM {} WHERE subaccount = 'undefined_2'").format(ident),
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

    if record_internal_transfers:
        transfer_amount = compute_automatic_mtb_rake_amount_cents(cursor, subaccounts_table)
        if transfer_amount is not None:
            new_mtb_balance = int(master_bankroll_balance) - int(transfer_amount)
            cursor.execute(
                sql.SQL("SELECT COALESCE(balance, 0) FROM {} WHERE subaccount = 'CASH'").format(ident),
            )
            cash_row = cursor.fetchone()
            cash_balance = int(cash_row[0]) if cash_row else 0
            cursor.execute(
                sql.SQL("UPDATE {} SET balance = %s WHERE subaccount = 'CASH'").format(ident),
                (cash_balance + int(transfer_amount),),
            )
            apply_automatic_mtb_rake_post_transfer_db(
                cursor,
                subaccounts_table,
                int(transfer_amount),
                new_mtb_balance,
            )
            master_bankroll_balance = new_mtb_balance
            transfer_triggered = True

    return (master_bankroll_balance, transfer_triggered)


def update_mtb_balance_from_primary_and_ct(
    cursor,
    subaccounts_table: str,
    primary_cents: int,
) -> Optional[int]:
    """
    Set Master Trading Bankroll balance to ``primary_cents - Cash Transfer`` and refresh
    realized_pnl / realized_pnl_pct from MTB base_value (same formulas as ``subaccounts_update``).

    Call after PRIMARY and Cash Transfer have been updated so MTB + CT == PRIMARY holds.
    Returns the new MTB balance in cents, or None if the MTB row is missing.
    """
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL("SELECT COALESCE(balance, 0) FROM {} WHERE subaccount = 'undefined_2'").format(ident),
    )
    cash_transfer_row = cursor.fetchone()
    cash_transfer_balance = int(cash_transfer_row[0]) if cash_transfer_row else 0
    master_bankroll_balance = int(primary_cents) - cash_transfer_balance

    cursor.execute(
        sql.SQL(
            "SELECT base_value, target_pnl__pct, transfer_amt, automatic_transfers FROM {} WHERE subaccount = 'Master Trading Bankroll'"
        ).format(ident),
    )
    mtb_row = cursor.fetchone()
    base_value = int(mtb_row[0]) if mtb_row and mtb_row[0] is not None else None
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
    return master_bankroll_balance


def _mtb_balance_base_from_row(row: Any) -> Tuple[Any, Any]:
    """Tuple row or RealDictCursor dict → (balance, base_value)."""
    if isinstance(row, dict):
        return row.get("balance"), row.get("base_value")
    return row[0], row[1]


def refresh_mtb_realized_pnl_from_balance(cursor, subaccounts_table: str) -> Optional[int]:
    """
    Recompute MTB realized_pnl / realized_pnl_pct from current MTB balance and base_value.
    Used after live Kalshi subaccount balance sync (no synthetic PRIMARY − Cash Transfer math).
    """
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL("SELECT balance, base_value FROM {} WHERE subaccount = 'Master Trading Bankroll'").format(ident),
    )
    row = cursor.fetchone()
    if not row:
        return None
    master_bankroll_balance, base_value = _mtb_balance_base_from_row(row)
    if master_bankroll_balance is None:
        return None
    master_bankroll_balance = int(master_bankroll_balance)
    base_value = int(base_value) if base_value is not None else None
    if base_value is not None and base_value != 0:
        realized_pnl = master_bankroll_balance - base_value
        ratio = (master_bankroll_balance - base_value) / base_value
        realized_pnl_pct = float(int(ratio * 10000)) / 10000.0
    else:
        realized_pnl = None
        realized_pnl_pct = None
    cursor.execute(
        sql.SQL(
            "UPDATE {} SET realized_pnl = %s, realized_pnl_pct = %s WHERE subaccount = 'Master Trading Bankroll'"
        ).format(ident),
        (realized_pnl, realized_pnl_pct),
    )
    return master_bankroll_balance


def compute_bankroll_current_ratchet_from_mtb(
    master_bankroll_balance: int,
    prev_bankroll: Optional[int],
    *,
    drawdown_halt_on: bool,
    drawdown_pct: Any,
) -> Tuple[int, bool]:
    """
    Same sticky bankroll / drawdown step-down rules as the non-transfer branch of
    ``apply_balance_snapshot`` (when automatic internal transfer did not fire).
    Returns (bankroll_current, bankroll_stepped_down).
    """
    try:
        _dd_ratio = float((100.0 - float(drawdown_pct)) / 100.0)
    except (TypeError, ValueError):
        _dd_ratio = 0.5

    drawdown_threshold = (int(round(prev_bankroll * _dd_ratio)) if prev_bankroll else None)
    bankroll_stepped_down = False

    if prev_bankroll is None:
        return master_bankroll_balance, False
    if master_bankroll_balance > prev_bankroll:
        return master_bankroll_balance, False
    if (
        drawdown_halt_on
        and drawdown_threshold is not None
        and master_bankroll_balance <= drawdown_threshold
    ):
        if prev_bankroll > drawdown_threshold:
            bankroll_stepped_down = True
        return master_bankroll_balance, bankroll_stepped_down
    return prev_bankroll, False


def append_account_balance_after_withdrawal_cycle(
    cursor,
    *,
    account_balance_table: str,
    subaccounts_table: str,
    current_timestamp: str,
) -> Tuple[bool, bool]:
    """
    Append one ``account_balance`` row after external withdrawal + MTB↔CT reconciliation.
    Uses current MTB from subaccounts and applies the drawdown ratchet against the latest
    sticky ``bankroll_current`` (same logic as ``apply_balance_snapshot``).

    Returns (inserted, bankroll_stepped_down). On success, notifies frontend and monitor_manager.
    """
    if not _allowed_account_balance_fqn(account_balance_table):
        raise ValueError(f"Invalid account_balance table: {account_balance_table}")
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")

    ab_sch, ab_tbl = _split_fqn(account_balance_table)
    ab_ident = sql.SQL("{}.{}").format(sql.Identifier(ab_sch), sql.Identifier(ab_tbl))

    cursor.execute(
        sql.SQL(
            """
            SELECT balance, exposure, positions, portfolio, bankroll_current, COALESCE(portfolio_value, 0)
            FROM {}
            ORDER BY id DESC
            LIMIT 1
            """
        ).format(ab_ident),
    )
    prev_row = cursor.fetchone()
    if not prev_row:
        return False, False

    balance_amount, exposure_v, positions_v, portfolio_v, prev_bankroll, portfolio_value_raw = prev_row
    mtb_balance, mtb_base = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)
    if mtb_balance is None:
        return False, False

    user_no = parse_user_number_from_account_balance_table(account_balance_table)
    drawdown_halt_on, drawdown_pct = get_drawdown_trading_controls(
        cursor, user_number=user_no or resolved_tenant_user_no_for_app()
    )
    bankroll_current, bankroll_stepped_down = compute_bankroll_current_ratchet_from_mtb(
        int(mtb_balance),
        int(prev_bankroll) if prev_bankroll is not None else None,
        drawdown_halt_on=drawdown_halt_on,
        drawdown_pct=drawdown_pct,
    )

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
            current_timestamp,
            int(mtb_balance),
            int(mtb_base) if mtb_base is not None else None,
        ),
    )

    from backend.kalshi_account_sync_ws import notify_frontend_db_change, notify_monitor_manager

    total_portfolio_value = bal_i + pvr_i
    notify_db_name = "account_balance_paper" if "_paper_" in account_balance_table else "account_balance"
    notify_frontend_db_change(
        notify_db_name,
        {
            "balance": bal_i,
            "exposure": exp_i,
            "positions": pos_i,
            "portfolio": ptf_i,
            "portfolio_value_raw": pvr_i,
            "total_portfolio": total_portfolio_value,
            "source": "external_withdrawal_bankroll",
        },
    )
    notify_monitor_manager(bankroll_stepped_down=bankroll_stepped_down)
    return True, bankroll_stepped_down


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
    balance, base_value = _mtb_balance_base_from_row(row)
    return (
        int(balance) if balance is not None else None,
        int(base_value) if base_value is not None else None,
    )


AUTOMATIC_MTB_RAKE_TO_SUBACCOUNT = "CASH"
KALSHI_MTB_SUBACCOUNT_NUMBER = 1
KALSHI_CASH_SUBACCOUNT_NUMBER = 0
MTB_SUBACCOUNT_NAME = "Master Trading Bankroll"
CASH_SUBACCOUNT_NAMES = frozenset({"CASH", "PRIMARY"})


def is_cash_to_mtb_funding_transfer(from_name: str, to_name: str) -> bool:
    """True when moving idle CASH wallet funds into the trading bankroll."""
    return str(from_name) in CASH_SUBACCOUNT_NAMES and str(to_name) == MTB_SUBACCOUNT_NAME


def bump_mtb_base_value_for_cash_funding(
    cursor,
    subaccounts_table: str,
    amount_cents: int,
) -> int:
    """
    Raise MTB ``base_value`` by ``amount_cents`` before a CASH→MTB funding transfer.

    Recomputes realized_pnl / realized_pnl_pct against the **current** MTB balance so a
    post-transfer Kalshi poll does not look like a profit spike and trigger automatic rake.
    Returns the new base_value in cents.
    """
    if int(amount_cents) <= 0:
        raise ValueError("amount_cents must be positive")
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")

    mtb_balance, base_value = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)
    if mtb_balance is None:
        raise ValueError("Master Trading Bankroll row not found")

    anchor = int(base_value) if base_value is not None else int(mtb_balance)
    new_base_value = anchor + int(amount_cents)
    realized_pnl = int(mtb_balance) - new_base_value
    realized_pnl_pct = _mtb_realized_pnl_pct(int(mtb_balance), new_base_value)

    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL(
            """
            UPDATE {}
            SET base_value = %s, realized_pnl = %s, realized_pnl_pct = %s
            WHERE subaccount = %s
            """
        ).format(ident),
        (new_base_value, realized_pnl, realized_pnl_pct, MTB_SUBACCOUNT_NAME),
    )
    return new_base_value


def revert_mtb_base_value_cash_funding_bump(
    cursor,
    subaccounts_table: str,
    amount_cents: int,
) -> None:
    """Undo :func:`bump_mtb_base_value_for_cash_funding` when Kalshi transfer fails."""
    if int(amount_cents) <= 0:
        return
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")

    mtb_balance, base_value = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)
    if mtb_balance is None or base_value is None:
        return

    new_base_value = max(0, int(base_value) - int(amount_cents))
    realized_pnl = int(mtb_balance) - new_base_value
    realized_pnl_pct = _mtb_realized_pnl_pct(int(mtb_balance), new_base_value)

    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL(
            """
            UPDATE {}
            SET base_value = %s, realized_pnl = %s, realized_pnl_pct = %s
            WHERE subaccount = %s
            """
        ).format(ident),
        (new_base_value, realized_pnl, realized_pnl_pct, MTB_SUBACCOUNT_NAME),
    )


def _mtb_realized_pnl_pct(mtb_balance: int, base_value: Optional[int]) -> Optional[float]:
    if base_value is None or base_value == 0:
        return None
    ratio = (int(mtb_balance) - int(base_value)) / int(base_value)
    return float(int(ratio * 10000)) / 10000.0


def compute_automatic_mtb_rake_amount_cents(
    cursor,
    subaccounts_table: str,
) -> Optional[int]:
    """
    If MTB automatic-transfers settings are met, return rake amount in cents; else None.
    Caller should refresh MTB realized_pnl from Kalshi-synced balance first when live.
    """
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL(
            """
            SELECT balance, base_value, target_pnl__pct, transfer_amt, automatic_transfers
            FROM {} WHERE subaccount = 'Master Trading Bankroll'
            """
        ).format(ident),
    )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        mtb_balance = row.get("balance")
        base_value = row.get("base_value")
        target_pnl_pct = row.get("target_pnl__pct")
        transfer_amt = row.get("transfer_amt")
        automatic_transfers = row.get("automatic_transfers")
    else:
        mtb_balance, base_value, target_pnl_pct, transfer_amt, automatic_transfers = row
    if not automatic_transfers:
        return None
    if base_value is None or int(base_value) == 0:
        return None
    if target_pnl_pct is None or transfer_amt is None:
        return None
    if mtb_balance is None:
        return None
    mtb_balance = int(mtb_balance)
    base_value = int(base_value)
    realized_pnl_pct = _mtb_realized_pnl_pct(mtb_balance, base_value)
    if realized_pnl_pct is None or realized_pnl_pct < float(target_pnl_pct):
        return None
    transfer_amount = int(round(float(transfer_amt) * base_value))
    return transfer_amount if transfer_amount > 0 else None


def apply_automatic_mtb_rake_post_transfer_db(
    cursor,
    subaccounts_table: str,
    transfer_amount: int,
    new_mtb_balance: int,
    *,
    to_subaccount: str = AUTOMATIC_MTB_RAKE_TO_SUBACCOUNT,
) -> None:
    """Reset MTB base_value after rake and log transfer (balances come from Kalshi repoll when live)."""
    if not _allowed_subaccounts_fqn(subaccounts_table):
        raise ValueError(f"Invalid subaccounts table: {subaccounts_table}")
    sch, tbl = _split_fqn(subaccounts_table)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL(
            "SELECT base_value, target_pnl__pct, transfer_amt FROM {} WHERE subaccount = 'Master Trading Bankroll'"
        ).format(ident),
    )
    row = cursor.fetchone()
    if not row:
        return
    if isinstance(row, dict):
        base_value = row.get("base_value")
        target_pnl_pct = row.get("target_pnl__pct")
        transfer_amt = row.get("transfer_amt")
    else:
        base_value, target_pnl_pct, transfer_amt = row
    if base_value is None or target_pnl_pct is None or transfer_amt is None:
        return
    base_value = int(base_value)
    base_step_pct = float(target_pnl_pct) - float(transfer_amt)
    new_base_value = int(round(base_value * (1 + base_step_pct)))
    post_transfer_realized_pnl = int(new_mtb_balance) - new_base_value
    post_transfer_ratio = (
        (int(new_mtb_balance) - new_base_value) / new_base_value if new_base_value else 0
    )
    post_transfer_realized_pnl_pct = float(int(post_transfer_ratio * 10000)) / 10000.0
    cursor.execute(
        sql.SQL(
            """
            UPDATE {} SET balance = %s, base_value = %s, realized_pnl = %s, realized_pnl_pct = %s
            WHERE subaccount = 'Master Trading Bankroll'
            """
        ).format(ident),
        (
            int(new_mtb_balance),
            new_base_value,
            post_transfer_realized_pnl,
            post_transfer_realized_pnl_pct,
        ),
    )
    from backend.core.time_eastern import now_est

    transfer_timestamp_est = now_est().strftime("%Y-%m-%d %H:%M:%S")
    xfer_tbl = _transfers_fqn_for_subaccounts_fqn(subaccounts_table)
    cursor.execute(
        f"""
        INSERT INTO {xfer_tbl} (timestamp, type, "from", "to", amount, initiated)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            transfer_timestamp_est,
            "internal",
            "Master Trading Bankroll",
            to_subaccount,
            int(transfer_amount),
            "automatic",
        ),
    )


def maybe_execute_live_automatic_mtb_rake(
    cursor,
    user_no: str,
    *,
    subaccounts_table: str,
) -> bool:
    """
    Live: POST Kalshi transfer MTB (#1) → CASH (#0) when automatic rake triggers.
    Updates MTB base_value in DB; caller should repoll all subaccount balances afterward.
    """
    slot = str(user_no).zfill(4)[-4:]
    refresh_mtb_realized_pnl_from_balance(cursor, subaccounts_table)
    transfer_amount = compute_automatic_mtb_rake_amount_cents(cursor, subaccounts_table)
    if transfer_amount is None:
        return False
    mtb_balance, _ = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)
    if mtb_balance is None:
        _LOG.warning("Automatic MTB rake skipped: no MTB balance for user %s", slot)
        return False
    if int(mtb_balance) < int(transfer_amount):
        _LOG.warning(
            "Automatic MTB rake skipped: MTB balance %s < transfer %s (user %s)",
            mtb_balance,
            transfer_amount,
            slot,
        )
        return False
    import uuid

    from backend.bookkeeper.kalshi_subaccount_transfer import apply_subaccount_transfer

    try:
        apply_subaccount_transfer(
            slot,
            KALSHI_MTB_SUBACCOUNT_NUMBER,
            KALSHI_CASH_SUBACCOUNT_NUMBER,
            int(transfer_amount),
            str(uuid.uuid4()),
        )
    except Exception as exc:
        _LOG.warning("Automatic MTB rake Kalshi transfer failed for user %s: %s", slot, exc)
        return False
    new_mtb_balance = int(mtb_balance) - int(transfer_amount)
    apply_automatic_mtb_rake_post_transfer_db(
        cursor,
        subaccounts_table,
        int(transfer_amount),
        new_mtb_balance,
    )
    _LOG.info(
        "Automatic MTB rake: user %s transferred %s cents MTB→CASH via Kalshi API",
        slot,
        transfer_amount,
    )
    return True


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
    live_mtb_balance_cents: Optional[int] = None,
    skip_bankroll_ratchet: bool = False,
    notify_frontend: bool = True,
    notify_monitors: bool = True,
    defer_monitor_notify: bool = False,
) -> Tuple[bool, bool]:
    """
    One full tick: ratchet bankroll, optional INSERT, notify frontend + monitor_manager.
    Returns (inserted_new_row, bankroll_stepped_down).

    ``defer_monitor_notify``: skip in-process ``notify_monitor_manager`` (live balance poll
    commits in ``sync_balance`` first, then notifies so monitor_manager reads committed rows).

    ``paper_bankroll_force_match`` (paper only): set ``bankroll_current`` to MTB / portfolio for this
    tick instead of the sticky ratchet — used when the user explicitly seeds paper bankroll so a
    lower total is not masked by the previous row's ``bankroll_current``.

    ``skip_bankroll_ratchet`` (live only): keep ``bankroll_current`` sticky while updating cash /
    portfolio / MTB columns — used on deposit/withdrawal routing ticks (0↔2 Kalshi transfers).

    Drawdown emergency halts (``bankroll_stepped_down`` → monitor_manager) run only when the
    snapshot table matches global trading mode (live tables in LIVE mode, paper in PAPER mode).
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
    is_subaccount_balance = _is_subaccount_balance_fqn(account_balance_table)
    subaccount_number = _subaccount_number_from_balance_fqn(account_balance_table) if is_subaccount_balance else None

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
    transfer_triggered = False
    if is_subaccount_balance and subaccount_number != 1:
        master_bankroll_balance = portfolio_value
        if prev_bankroll is None:
            bankroll_current = portfolio_value
        elif portfolio_value > prev_bankroll:
            bankroll_current = portfolio_value
        else:
            bankroll_current = prev_bankroll
        bankroll_stepped_down = False
    elif is_paper:
        master_bankroll_balance, transfer_triggered = subaccounts_update(
            cursor,
            portfolio_value,
            subaccounts_table=subaccounts_table,
            record_internal_transfers=record_internal_transfers,
        )
    elif live_mtb_balance_cents is not None:
        master_bankroll_balance = int(live_mtb_balance_cents)
    elif positions_value == 0:
        master_bankroll_balance, transfer_triggered = subaccounts_update(
            cursor,
            portfolio_value,
            subaccounts_table=subaccounts_table,
            record_internal_transfers=record_internal_transfers,
        )
    else:
        mtb_snap, _ = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)
        master_bankroll_balance = mtb_snap if mtb_snap is not None else (prev_bankroll or portfolio_value)

    if is_subaccount_balance and subaccount_number != 1:
        pass  # bankroll_current already set above
    elif skip_bankroll_ratchet and not is_paper and not is_subaccount_balance:
        bankroll_current = (
            int(prev_bankroll) if prev_bankroll is not None else int(master_bankroll_balance)
        )
        bankroll_stepped_down = False
    elif is_paper or live_mtb_balance_cents is not None or positions_value == 0:
        if transfer_triggered:
            bankroll_current = master_bankroll_balance
        elif paper_bankroll_force_match and is_paper:
            bankroll_current = master_bankroll_balance
        else:
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

    bankroll_stepped_down = _drawdown_stepped_down_for_halt(
        account_balance_table,
        bankroll_stepped_down,
    )

    if is_subaccount_balance and subaccount_number != 1:
        mtb_balance, mtb_base = None, None
    else:
        mtb_balance, mtb_base = get_mtb_snapshot_from_subaccounts(cursor, subaccounts_table)

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

    if notify_frontend:
        from backend.kalshi_account_sync_ws import notify_frontend_db_change

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
    if (
        notify_monitors
        and not defer_monitor_notify
        and not (skip_bankroll_ratchet and not is_paper)
    ):
        from backend.kalshi_account_sync_ws import notify_monitor_manager

        notify_monitor_manager(bankroll_stepped_down=bankroll_stepped_down)
    return True, bankroll_stepped_down


def _latest_subaccount_balance_row(cursor, table_fqn: str) -> Optional[dict]:
    sch, tbl = _split_fqn(table_fqn)
    ident = sql.SQL("{}.{}").format(sql.Identifier(sch), sql.Identifier(tbl))
    cursor.execute(
        sql.SQL(
            """
            SELECT balance, exposure, positions, portfolio, portfolio_value,
                   bankroll_current, master_trading_bankroll, mtb_base_value
            FROM {} ORDER BY id DESC LIMIT 1
            """
        ).format(ident),
    )
    row = cursor.fetchone()
    if not row:
        return None
    keys = (
        "balance",
        "exposure",
        "positions",
        "portfolio",
        "portfolio_value",
        "bankroll_current",
        "master_trading_bankroll",
        "mtb_base_value",
    )
    return {k: row[i] for i, k in enumerate(keys)}


def aggregate_account_balance_from_subaccounts(
    cursor,
    *,
    user_no: str,
    account_balance_table: str,
    subaccount_numbers: list[int],
    current_timestamp: str,
    throttle: bool = True,
) -> Tuple[bool, bool]:
    """
    Sum latest per-subaccount balance snapshots; copy MTB bankroll fields from subaccount 1.
  Insert one hero row into account_balance_<slot>.
    """
    from backend.trading_mode import subaccount_balance_table_fqn

    if not _AB_FQN_RE.match(account_balance_table.strip()):
        raise ValueError(f"hero table required, got {account_balance_table!r}")

    sums = {k: 0 for k in ("balance", "exposure", "positions", "portfolio", "portfolio_value")}
    mtb_row: Optional[dict] = None
    for n in sorted(set(int(x) for x in subaccount_numbers)):
        sab_fqn = subaccount_balance_table_fqn(user_no, n)
        latest = _latest_subaccount_balance_row(cursor, sab_fqn)
        if not latest:
            continue
        for k in sums:
            sums[k] += int(latest.get(k) or 0)
        if int(n) == 1:
            mtb_row = latest

    if mtb_row is None:
        mtb_row = _latest_subaccount_balance_row(
            cursor, subaccount_balance_table_fqn(user_no, 1)
        )

    bankroll_current = int(mtb_row["bankroll_current"]) if mtb_row and mtb_row.get("bankroll_current") is not None else sums["portfolio"]
    mtb_balance = mtb_row.get("master_trading_bankroll") if mtb_row else None
    mtb_base = mtb_row.get("mtb_base_value") if mtb_row else None

    return apply_balance_snapshot(
        cursor,
        balance_amount=sums["balance"],
        portfolio_value_raw=sums["portfolio_value"],
        positions_value=sums["positions"],
        total_exposure=sums["exposure"],
        portfolio_value=sums["portfolio"],
        account_balance_table=account_balance_table,
        subaccounts_table=f"users_{user_no}.subaccounts_{user_no}",
        current_timestamp=current_timestamp,
        throttle=throttle,
        notify_db_name="account_balance",
        record_internal_transfers=False,
        live_mtb_balance_cents=bankroll_current,
        notify_frontend=True,
        notify_monitors=True,
        defer_monitor_notify=True,
    )


def _subaccount_numbers_from_subaccounts_table(cursor, subaccounts_table: str) -> list[int]:
    """Kalshi subaccount numbers = row ``id`` values in users.subaccounts_* (label is display-only)."""
    from backend.trading_mode import sql_ident_qualified_table

    ident = sql_ident_qualified_table(subaccounts_table)
    cursor.execute(sql.SQL("SELECT id FROM {}").format(ident))
    out: set[int] = set()
    for row in cursor.fetchall() or []:
        raw = row[0] if not isinstance(row, dict) else row.get("id")
        if raw is None:
            continue
        try:
            out.add(int(raw))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def notify_monitor_manager_after_balance_commit(*, bankroll_stepped_down: bool = False) -> None:
    """Call after balance poll transaction commit so monitor_manager reads committed bankroll."""
    from backend.kalshi_account_sync_ws import notify_monitor_manager

    notify_monitor_manager(bankroll_stepped_down=bankroll_stepped_down)


def _balance_glitch_guard_enabled() -> bool:
    v = os.environ.get("REC_BALANCE_GLITCH_GUARD", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _balance_glitch_min_cash_delta_cents() -> int:
    try:
        return max(0, int(os.environ.get("REC_BALANCE_GLITCH_MIN_CASH_DELTA_CENTS", "1000")))
    except (TypeError, ValueError):
        return 1000


def _balance_glitch_repoll_delays_sec() -> List[float]:
    raw = os.environ.get("REC_BALANCE_GLITCH_REPOLL_DELAYS_SEC", "2,3,5")
    out: List[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(max(0.0, float(part)))
        except (TypeError, ValueError):
            continue
    return out if out else [2.0, 3.0, 5.0]


def detect_settlement_balance_glitch(
    prev_row: dict,
    cash_cents: int,
    pv_cents: int,
) -> Tuple[bool, str]:
    """
    Return (is_glitch, reason) when Kalshi balance likely double-counts settlement cash
    with stale open-position marks (balance up, portfolio_value flat/up, total up ~cash).

    True glitch: cash credited while the settled position mark is still in portfolio_value.
    Valid win (cheap contracts): cash jumps by near face value while marks only drop by the
    prior small open mark — PV decreases, so this must not fire.

    Does not fire when both previous and current open-position marks are zero — that pattern
    matches internal CASH→MTB funding (cash up, no marks), not settlement double-count.
    """
    if not prev_row:
        return False, ""

    prev_cash = int(prev_row.get("balance") or 0)
    prev_pv = int(prev_row.get("portfolio_value") or 0)
    prev_portfolio = int(prev_row.get("portfolio") or (prev_cash + prev_pv))
    api_pv = int(pv_cents)

    if prev_pv == 0 and api_pv == 0:
        return False, ""

    cash_delta = int(cash_cents) - prev_cash
    if cash_delta < _balance_glitch_min_cash_delta_cents():
        return False, ""

    # Any PV decrease means open marks are clearing — not the stale double-count glitch.
    # (Requiring PV drop ≥ 25% of cash falsely blocked cheap winners: large cash, small marks.)
    pv_delta = api_pv - prev_pv
    if pv_delta < 0:
        return False, ""

    new_portfolio = int(cash_cents) + api_pv
    portfolio_delta = new_portfolio - prev_portfolio
    if portfolio_delta < cash_delta * 0.85:
        return False, ""

    return True, "pv_stale_with_cash_jump"


def _write_polled_subaccount_balances(
    cursor,
    *,
    slot: str,
    sa_fqn: str,
    ab_fqn: str,
    active_numbers: List[int],
    details_by_number: Dict[int, dict],
    current_timestamp: str,
    throttle: bool,
) -> Tuple[bool, bool]:
    """Persist per-subaccount rows and hero aggregate from pre-fetched Kalshi balance details."""
    from backend.trading_mode import subaccount_balance_table_fqn

    polled: list[int] = []
    for n in active_numbers:
        detail = details_by_number.get(n)
        if detail is None:
            continue
        sab_fqn = subaccount_balance_table_fqn(slot, n)
        ensure_subaccount_balance_table(cursor, sab_fqn)
        cash = int(detail["balance_cents"])
        pos = int(detail["portfolio_value_cents"])
        total = int(detail["total_portfolio_cents"])
        live_mtb = total if n == 1 else None
        apply_balance_snapshot(
            cursor,
            balance_amount=cash,
            portfolio_value_raw=pos,
            positions_value=pos,
            total_exposure=pos,
            portfolio_value=total,
            account_balance_table=sab_fqn,
            subaccounts_table=sa_fqn,
            current_timestamp=current_timestamp,
            throttle=False,
            notify_db_name="account_balance",
            record_internal_transfers=False,
            live_mtb_balance_cents=live_mtb,
            notify_frontend=False,
            notify_monitors=False,
        )
        polled.append(n)

    if not polled:
        _LOG.warning("No subaccount balance polls succeeded for user %s", slot)
        return False, False

    return aggregate_account_balance_from_subaccounts(
        cursor,
        user_no=slot,
        account_balance_table=ab_fqn,
        subaccount_numbers=polled,
        current_timestamp=current_timestamp,
        throttle=throttle,
    )


def poll_live_account_balances(
    cursor,
    user_no: str,
    *,
    throttle: bool = True,
    _after_automatic_rake: bool = False,
    deposit_cycle: bool = False,
    skip_automatic_mtb_rake: bool = False,
) -> Tuple[bool, bool]:
    """
    Live Kalshi balance pipeline: subaccounts poll → per-subaccount GET balance → hero aggregate.

    When automatic MTB rake fires, posts Kalshi transfer #1→#0 and repolls once (full refresh).

    On suspected settlement double-count (cash up, stale portfolio_value), skips the DB write,
    logs WARNING, and repolls with REC_BALANCE_GLITCH_REPOLL_DELAYS_SEC backoff.

    ``skip_automatic_mtb_rake``: set after manual CASH→MTB funding (base_value already raised).
    """
    from backend.bookkeeper.kalshi_portfolio_balance import (
        fetch_portfolio_balance_detail,
        fetch_subaccount_balances_cents_map,
    )
    from backend.core.time_eastern import now_est
    from backend.kalshi_account_sync_ws import _sync_subaccounts_from_kalshi_poll
    from backend.trading_mode import (
        account_balance_table_for_user,
        subaccount_balance_table_fqn,
        subaccounts_table_for_user,
    )

    slot = str(user_no).zfill(4)[-4:]
    sa_fqn = subaccounts_table_for_user(slot, force_live=True)
    ab_fqn = account_balance_table_for_user(slot, force_live=True)

    balances_by_number = fetch_subaccount_balances_cents_map(slot)
    if balances_by_number is None:
        _LOG.warning("Kalshi subaccount balances unavailable for user %s", slot)
        balances_by_number = {}

    _sync_subaccounts_from_kalshi_poll(cursor, sa_fqn, balances_by_number)
    refresh_mtb_realized_pnl_from_balance(cursor, sa_fqn)
    if (
        not skip_automatic_mtb_rake
        and not _after_automatic_rake
        and maybe_execute_live_automatic_mtb_rake(cursor, slot, subaccounts_table=sa_fqn)
    ):
        return poll_live_account_balances(
            cursor,
            user_no,
            throttle=False,
            _after_automatic_rake=True,
            deposit_cycle=deposit_cycle,
            skip_automatic_mtb_rake=skip_automatic_mtb_rake,
        )

    active_numbers = sorted(
        set(int(n) for n in balances_by_number.keys())
        | set(_subaccount_numbers_from_subaccounts_table(cursor, sa_fqn))
    )
    if not active_numbers:
        active_numbers = [0, 1]

    repoll_delays = _balance_glitch_repoll_delays_sec()
    max_attempts = 1 + len(repoll_delays)
    attempt = 0

    while True:
        attempt += 1
        ts = now_est().isoformat()
        details_by_number: Dict[int, dict] = {}
        for n in active_numbers:
            detail = fetch_portfolio_balance_detail(slot, subaccount=n)
            if detail is None:
                _LOG.warning("Kalshi balance poll failed for user %s subaccount %s", slot, n)
                continue
            details_by_number[n] = detail

        if not details_by_number:
            return False, False

        glitch_detected = False
        glitch_reason = ""
        if (
            _balance_glitch_guard_enabled()
            and not skip_automatic_mtb_rake
            and not _after_automatic_rake
            and not deposit_cycle
            and 1 in details_by_number
        ):
            mtb_fqn = subaccount_balance_table_fqn(slot, 1)
            prev_mtb = _latest_subaccount_balance_row(cursor, mtb_fqn)
            if prev_mtb:
                d1 = details_by_number[1]
                glitch_detected, glitch_reason = detect_settlement_balance_glitch(
                    prev_mtb,
                    int(d1["balance_cents"]),
                    int(d1["portfolio_value_cents"]),
                )

        if glitch_detected:
            prev_mtb = _latest_subaccount_balance_row(
                cursor, subaccount_balance_table_fqn(slot, 1)
            ) or {}
            d1 = details_by_number[1]
            prev_cash = int(prev_mtb.get("balance") or 0)
            prev_pv = int(prev_mtb.get("portfolio_value") or 0)
            prev_portfolio = int(prev_mtb.get("portfolio") or (prev_cash + prev_pv))
            api_cash = int(d1["balance_cents"])
            api_pv = int(d1["portfolio_value_cents"])
            cash_delta = api_cash - prev_cash
            _LOG.warning(
                "balance_settlement_glitch_skipped user=%s subaccount=1 attempt=%s/%s "
                "prev_cash=%s prev_pv=%s prev_portfolio=%s "
                "api_cash=%s api_pv=%s api_portfolio=%s cash_delta=%s reason=%s",
                slot,
                attempt,
                max_attempts,
                prev_cash,
                prev_pv,
                prev_portfolio,
                api_cash,
                api_pv,
                api_cash + api_pv,
                cash_delta,
                glitch_reason,
            )
            if attempt > len(repoll_delays):
                _LOG.error(
                    "balance glitch persists after %s repolls; keeping last good DB row (user=%s)",
                    len(repoll_delays),
                    slot,
                )
                return False, False
            time.sleep(repoll_delays[attempt - 1])
            continue

        if attempt > 1:
            _LOG.info(
                "balance_settlement_glitch_cleared user=%s attempt=%s delay_sec=%s",
                slot,
                attempt,
                repoll_delays[attempt - 2],
            )

        return _write_polled_subaccount_balances(
            cursor,
            slot=slot,
            sa_fqn=sa_fqn,
            ab_fqn=ab_fqn,
            active_numbers=active_numbers,
            details_by_number=details_by_number,
            current_timestamp=ts,
            throttle=throttle,
        )


def estimate_kalshi_taker_fee_dollars(position, price: float) -> float:
    """Same formula as trade_manager.estimate_kalshi_taker_fee (taker leg, dollars)."""
    try:
        pos = float(position)
    except (TypeError, ValueError):
        return 0.0
    if pos <= 0 or price is None or float(price) <= 0 or float(price) >= 1:
        return 0.0
    raw = 0.07 * pos * float(price) * (1.0 - float(price))
    return math.ceil(raw * 100) / 100


def paper_open_cost_and_fee_cents(buy_price: float, position, open_fee_dollars: float) -> Tuple[int, int]:
    """Premium (position mark) in cents, and open fee in cents."""
    try:
        pos = float(position)
    except (TypeError, ValueError):
        pos = 0.0
    cost_cents = int(round(float(buy_price) * pos * 100.0))
    fee_cents = int(round(float(open_fee_dollars) * 100.0))
    return cost_cents, fee_cents


def paper_close_adjust_cents(buy_price: float, position, pnl_dollars: float) -> Tuple[int, int, int]:
    """
    Return (cost_basis_cents, balance_delta_cents, positions_delta_cents) for a closed paper trade.
    balance increases by cost_basis + pnl (in cents); positions decrease by cost_basis.
    """
    try:
        pos = float(position)
    except (TypeError, ValueError):
        pos = 0.0
    cost_cents = int(round(float(buy_price) * pos * 100.0))
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
                    WHERE subaccount = 'CASH'
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
                  AND status IN ('open', 'closing')
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
          AND status IN ('open', 'closing')
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

    If the paper balance table is empty, fall back to ``subaccounts_paper.CASH`` (bootstrap).
    """
    cursor.execute(
        sql.SQL("SELECT portfolio FROM {} ORDER BY id DESC LIMIT 1 FOR UPDATE").format(ab_ident)
    )
    row = cursor.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    cursor.execute(
        sql.SQL("SELECT balance FROM {} WHERE subaccount = 'CASH' LIMIT 1").format(sa_ident)
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


def sync_paper_balance_feed_after_close(pnl_cents: int, buy_price: float, position) -> bool:
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
    open_fee_cents = int(round(estimate_kalshi_taker_fee_dollars(float(position), float(buy_price)) * 100.0))
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


def refresh_paper_snapshot_after_manual_internal_transfer(
    cursor,
    *,
    user_no: str,
    cash_delta_cents: int = 0,
) -> Tuple[bool, bool]:
    """
    Write one paper hero row after a manual internal transfer.

    ``cash_delta_cents``: change to hero cash (negative when funding MTB from CASH).
    Skips automatic MTB rake. Notifies frontend and monitor_manager via apply_balance_snapshot.
    """
    from backend.core.time_eastern import now_est
    from backend.trading_mode import paper_account_balance_fqn, paper_subaccounts_fqn

    slot = str(user_no).zfill(4)[-4:]
    ab_fqn = paper_account_balance_fqn(slot)
    ab_sch, ab_tbl = ab_fqn.split(".", 1)
    ab_ident = sql.SQL("{}.{}").format(sql.Identifier(ab_sch), sql.Identifier(ab_tbl))
    cursor.execute(
        sql.SQL(
            """
            SELECT balance, COALESCE(positions, 0)
            FROM {}
            ORDER BY id DESC
            LIMIT 1
            """
        ).format(ab_ident)
    )
    prev = cursor.fetchone()
    if not prev:
        return False, False
    cash = int(prev[0] or 0) + int(cash_delta_cents)
    pos = max(0, int(prev[1] or 0))
    if cash < 0:
        raise ValueError("paper cash would be negative after internal transfer")
    ts = now_est().isoformat()
    return apply_balance_snapshot(
        cursor,
        balance_amount=cash,
        portfolio_value_raw=pos,
        positions_value=pos,
        total_exposure=pos,
        portfolio_value=cash + pos,
        account_balance_table=ab_fqn,
        subaccounts_table=paper_subaccounts_fqn(slot),
        current_timestamp=ts,
        throttle=False,
        notify_db_name="account_balance_paper",
        record_internal_transfers=False,
        paper_bankroll_force_match=True,
    )


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
    enabled). Transfers move slices from MTB to CASH and affect ``bankroll_current`` / monitor bankroll
    — the same as live — without mutating total portfolio or cash+positions math.
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
