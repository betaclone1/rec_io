"""Per-monitor bankroll resolution from assigned Kalshi subaccount."""

from __future__ import annotations

import logging
from typing import Optional

from psycopg2 import sql

from backend.trading_mode import (
    account_balance_table_for_user,
    sql_ident_qualified_table,
    subaccount_balance_table_fqn,
    subaccounts_table_for_user,
    use_paper_for_request,
)

_log = logging.getLogger(__name__)


def _cents_from_bankroll_portfolio(bankroll_current, portfolio) -> int:
    bc = int(bankroll_current) if bankroll_current is not None else 0
    pf = int(portfolio) if portfolio is not None else 0
    return bc if bc > 0 else pf


def latest_bankroll_cents_for_subaccount(
    cursor,
    user_number: str,
    subaccount_number: int,
    *,
    client_trading_mode: Optional[str] = None,
) -> int:
    """
    Authoritative bankroll cents for monitor allotments for one Kalshi subaccount id.

    Live: latest ``bankroll_current`` (else ``portfolio``) from
    ``subaccount_balance_<slot>_<n>``. Missing table/row → 0 (no hero/MTB substitute).

    Paper: subaccount 1 uses sticky ``account_balance_paper.bankroll_current``;
    other ids use ``subaccounts_paper.balance`` for that id (no paper per-shard
    ``bankroll_current`` history). Missing row → 0.
    """
    un = str(user_number).strip().zfill(4)
    try:
        sa = int(subaccount_number)
    except (TypeError, ValueError):
        return 0

    if use_paper_for_request(client_trading_mode):
        if sa == 1:
            ab_ident = sql_ident_qualified_table(
                account_balance_table_for_user(
                    un, client_trading_mode=client_trading_mode
                )
            )
            cursor.execute(
                sql.SQL(
                    """
                    SELECT bankroll_current, portfolio
                    FROM {}
                    ORDER BY timestamp DESC NULLS LAST, id DESC
                    LIMIT 1
                    """
                ).format(ab_ident)
            )
            row = cursor.fetchone()
            if not row:
                return 0
            return _cents_from_bankroll_portfolio(row[0], row[1])

        sa_tbl = subaccounts_table_for_user(
            un, client_trading_mode=client_trading_mode
        )
        sa_ident = sql_ident_qualified_table(sa_tbl)
        cursor.execute(
            sql.SQL("SELECT balance FROM {} WHERE id = %s").format(sa_ident),
            (sa,),
        )
        row = cursor.fetchone()
        if not row or row[0] is None:
            return 0
        return int(row[0])

    fqn = subaccount_balance_table_fqn(un, sa)
    try:
        bal_ident = sql_ident_qualified_table(fqn)
    except Exception:
        _log.warning("invalid subaccount_balance fqn for user=%s sa=%s", un, sa)
        return 0

    sch, tbl = fqn.split(".", 1)
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        )
        """,
        (sch, tbl),
    )
    exists_row = cursor.fetchone()
    if not exists_row or not exists_row[0]:
        return 0

    cursor.execute(
        sql.SQL(
            """
            SELECT bankroll_current, portfolio
            FROM {}
            ORDER BY timestamp DESC NULLS LAST, id DESC
            LIMIT 1
            """
        ).format(bal_ident)
    )
    row = cursor.fetchone()
    if not row:
        return 0
    return _cents_from_bankroll_portfolio(row[0], row[1])


def subaccount_id_exists(
    cursor,
    user_number: str,
    subaccount_number: int,
    *,
    client_trading_mode: Optional[str] = None,
) -> bool:
    """True if ``subaccounts_*`` has a row with this Kalshi id."""
    un = str(user_number).strip().zfill(4)
    try:
        sa = int(subaccount_number)
    except (TypeError, ValueError):
        return False
    sa_ident = sql_ident_qualified_table(
        subaccounts_table_for_user(un, client_trading_mode=client_trading_mode)
    )
    cursor.execute(
        sql.SQL("SELECT 1 FROM {} WHERE id = %s LIMIT 1").format(sa_ident),
        (sa,),
    )
    return cursor.fetchone() is not None
