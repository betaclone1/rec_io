#!/usr/bin/env python3
"""
Recalculate pnl, ret_pct, and win_loss for closed paper trades using existing fees
(assumes fees have been backfilled via backfill_paper_trade_fees.py).
Updates ONLY pnl, ret_pct, win_loss for rows where paper_trade = TRUE and sell_price IS NOT NULL.
Then refreshes cycle_pnl, cycle_ret_pct, cycle_win_loss for every cycle that contains
at least one updated paper trade (all trades in those cycles get cycle_* updated).

Formulas:
  pnl = round(sell_value - buy_value - fees, 2)
  ret_pct = round((pnl / (bankroll/100)) * 100, 5) when bankroll in cents
  win_loss = 'W' | 'L' | 'D'

Run against production: DB_HOST=$REC_PROD_SSH_HOST PYTHONPATH=$(pwd) python3 scripts/db/backfill_paper_trade_pnl_ret.py
Dry run: add --dry-run
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backend.core.config.database import get_postgresql_connection
from psycopg2 import extras


def main():
    parser = argparse.ArgumentParser(description="Backfill paper trade pnl, ret_pct, win_loss")
    parser.add_argument("--dry-run", action="store_true", help="Do not UPDATE; only report")
    args = parser.parse_args()

    conn = get_postgresql_connection()
    if not conn:
        print("Failed to connect to database.")
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, buy_price, position, sell_price, fees, bankroll, monitor, contract, date
            FROM users.trades_0001
            WHERE paper_trade = TRUE AND sell_price IS NOT NULL
        """)
        rows = cur.fetchall()

    if not rows:
        print("No closed paper trades found (paper_trade=TRUE and sell_price NOT NULL).")
        conn.close()
        return

    updates = []
    cycles_seen = set()
    for row in rows:
        id_, buy_price, position, sell_price, fees, bankroll, monitor, contract, date = row
        try:
            pos = int(position) if position is not None else 0
            bp = float(buy_price) if buy_price is not None else None
            sp = float(sell_price) if sell_price is not None else None
            f = float(fees) if fees is not None else 0.0
            br = float(bankroll) if bankroll is not None else None
        except (TypeError, ValueError):
            continue
        if bp is None or sp is None or pos <= 0:
            continue
        buy_value = bp * pos
        sell_value = sp * pos
        pnl = round(sell_value - buy_value - f, 2)
        win_loss = "W" if pnl > 0 else "L" if pnl < 0 else "D"
        ret_pct = None
        if br is not None and br > 0:
            ret_pct = round((pnl / (br / 100.0)) * 100, 5)
        updates.append((id_, pnl, ret_pct, win_loss))
        if monitor and contract and date:
            cycles_seen.add((monitor, contract, date))

    if not updates:
        print("No rows to update after computing pnl/ret.")
        conn.close()
        return

    if args.dry_run:
        print(f"DRY RUN: would set pnl/ret_pct/win_loss for {len(updates)} paper trade(s). Sample: id={updates[0][0]} pnl={updates[0][1]} ret_pct={updates[0][2]} win_loss={updates[0][3]}")
        print(f"Would refresh cycle metrics for {len(cycles_seen)} cycle(s).")
        conn.close()
        return

    with conn.cursor() as cur:
        extras.execute_values(
            cur,
            """
            UPDATE users.trades_0001 AS t
            SET pnl = v.pnl, ret_pct = v.ret_pct, win_loss = v.win_loss
            FROM (VALUES %s) AS v(id, pnl, ret_pct, win_loss)
            WHERE t.id = v.id::bigint AND t.paper_trade = TRUE
            """,
            [(id_, pnl, ret_pct, win_loss) for id_, pnl, ret_pct, win_loss in updates],
            template="(%s::bigint, %s::numeric, %s::numeric, %s)",
            page_size=500,
        )
    conn.commit()
    print(f"Updated pnl, ret_pct, win_loss for {len(updates)} paper trade(s).")

    # Refresh cycle metrics for every cycle that contains an updated paper trade
    with conn.cursor() as cur:
        for monitor, contract, date in cycles_seen:
            cur.execute(
                """
                SELECT SUM(pnl) AS total_pnl, SUM(ret_pct) AS total_ret_pct
                FROM users.trades_0001
                WHERE monitor = %s AND contract = %s AND date = %s
                  AND status IN ('closed', 'expired')
                  AND pnl IS NOT NULL AND ret_pct IS NOT NULL
                """,
                (monitor, contract, date),
            )
            row = cur.fetchone()
            if not row or row[0] is None or row[1] is None:
                continue
            total_pnl, total_ret_pct = row[0], row[1]
            cycle_win_loss = "W" if total_pnl > 0 else "L"
            cur.execute(
                """
                UPDATE users.trades_0001
                SET cycle_pnl = %s, cycle_ret_pct = %s, cycle_win_loss = %s
                WHERE monitor = %s AND contract = %s AND date = %s AND status IN ('closed', 'expired')
                """,
                (total_pnl, total_ret_pct, cycle_win_loss, monitor, contract, date),
            )
    conn.commit()
    print(f"Refreshed cycle_pnl, cycle_ret_pct, cycle_win_loss for {len(cycles_seen)} cycle(s).")
    conn.close()


if __name__ == "__main__":
    main()
