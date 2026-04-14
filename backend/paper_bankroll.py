"""Initialize or reset paper subaccounts + first account_balance_paper row (user-configured cents)."""

from __future__ import annotations

from psycopg2 import sql

from backend.balance_snapshot import (
    _ensure_tx_connection,
    _paper_aggregate_xact_lock,
    _run_paper_balance_snapshot_tx,
)
from backend.core.config.database import get_postgresql_connection
from backend.core.time_eastern import now_est
from backend.core.tenant_context import resolved_tenant_user_no_for_app
from backend.trading_mode import (
    paper_account_balance_fqn,
    paper_subaccounts_fqn,
    sql_ident_qualified_table,
)


def seed_paper_bankroll_cents(total_cents: int) -> bool:
    """
    Set PRIMARY / MTB / Cash Transfer for paper subaccounts and write one balance snapshot.

    ``total_cents`` is **total equity** (Kalshi ``portfolio``): cash + open-position marks.

    With **no** prior ``account_balance_paper`` row (or zero marks), cash = total and positions = 0.

    With **open** marks on the latest row, those ``positions`` / ``exposure`` values are carried
    forward, ``portfolio`` is set to ``total_cents``, and **cash** = ``total_cents - marks`` so the
    row stays Kalshi-shaped. If ``total_cents`` is below carried marks, raises ``ValueError``.

    ``master_trading_bankroll`` / ``mtb_base_value`` on the new row come from subaccounts after
    ``subaccounts_update`` (same as every paper tick). Subaccount updates and the snapshot run in
    **one** transaction with the paper aggregate advisory lock.
    """
    if total_cents < 0:
        raise ValueError("total_cents must be non-negative")
    slot = resolved_tenant_user_no_for_app()
    sa_ident = sql_ident_qualified_table(paper_subaccounts_fqn(slot))
    ab_sch, ab_tbl = paper_account_balance_fqn(slot).split(".", 1)
    ab_ident = sql.SQL("{}.{}").format(sql.Identifier(ab_sch), sql.Identifier(ab_tbl))
    conn = get_postgresql_connection()
    if not conn:
        return False
    _ensure_tx_connection(conn)
    ts = now_est().isoformat()
    try:
        with conn.cursor() as cur:
            _paper_aggregate_xact_lock(cur, slot)
            cur.execute(
                sql.SQL(
                    """
                    SELECT COALESCE(positions, 0), COALESCE(exposure, 0)
                    FROM {}
                    ORDER BY id DESC
                    LIMIT 1
                    """
                ).format(ab_ident)
            )
            prev = cur.fetchone()
            pos_prev = int(prev[0] or 0) if prev else 0
            exp_prev = int(prev[1] or 0) if prev else 0
            marks_cents = max(pos_prev, exp_prev)
            if total_cents < marks_cents:
                raise ValueError(
                    f"Paper bankroll {total_cents}¢ is below open position marks {marks_cents}¢ "
                    "(carry-forward from latest row). Close or reduce positions, or use a higher total."
                )
            cash_cents = int(total_cents) - marks_cents

            cur.execute(
                sql.SQL(
                    "UPDATE {} SET balance = %s WHERE subaccount = 'Cash Transfer'"
                ).format(sa_ident),
                (0,),
            )
            cur.execute(
                sql.SQL(
                    "UPDATE {} SET balance = %s, base_value = %s WHERE subaccount = 'PRIMARY'"
                ).format(sa_ident),
                (total_cents, total_cents),
            )
            cur.execute(
                sql.SQL(
                    """
                    UPDATE {}
                    SET balance = %s, base_value = %s,
                        realized_pnl = 0, realized_pnl_pct = 0
                    WHERE subaccount = 'Master Trading Bankroll'
                    """
                ).format(sa_ident),
                (total_cents, total_cents),
            )
            _run_paper_balance_snapshot_tx(
                cur,
                balance_cents=cash_cents,
                positions_cents=marks_cents,
                throttle=False,
                bankroll_force_match=True,
                current_timestamp=ts,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True
