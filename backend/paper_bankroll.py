"""Initialize or reset paper subaccounts + first account_balance_paper row (user-configured cents)."""

from __future__ import annotations

from backend.balance_snapshot import apply_paper_aggregate_snapshot
from backend.core.config.database import get_postgresql_connection


def seed_paper_bankroll_cents(total_cents: int) -> bool:
    """
    Set PRIMARY / MTB / Cash Transfer for paper subaccounts and write one balance snapshot.
    Cash Transfer = 0; PRIMARY = MTB = total_cents; MTB base_value = total_cents.
    """
    if total_cents < 0:
        raise ValueError("total_cents must be non-negative")
    conn = get_postgresql_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users.subaccounts_paper_0001 SET balance = %s WHERE subaccount = 'Cash Transfer'",
                (0,),
            )
            cur.execute(
                "UPDATE users.subaccounts_paper_0001 SET balance = %s, base_value = %s WHERE subaccount = 'PRIMARY'",
                (total_cents, total_cents),
            )
            cur.execute(
                """
                UPDATE users.subaccounts_paper_0001
                SET balance = %s, base_value = %s,
                    realized_pnl = 0, realized_pnl_pct = 0
                WHERE subaccount = 'Master Trading Bankroll'
                """,
                (total_cents, total_cents),
            )
        conn.commit()
    finally:
        conn.close()

    apply_paper_aggregate_snapshot(balance_cents=total_cents, positions_cents=0, throttle=False)
    return True
