#!/usr/bin/env python3
"""
Recalc pnl and ret_pct for trade 9948 using current position (and existing buy_price, sell_price, fees, bankroll).
Formulas (from trade_manager): pnl = sell_value - buy_value - fees; ret_pct = (pnl / (bankroll/100)) * 100.
Bankroll is stored in cents.

Run: PYTHONPATH=/opt/rec_io_server python3 scripts/recalc_trade_9948_pnl_ret_pct.py
"""
import argparse
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
os.chdir(_project_root)

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_trades
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no

TRADE_ID = 9948


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_user_no_argument(parser)
    args = parser.parse_args()
    user_no = resolve_user_no(args)
    trades_t = legacy_users_trades(user_no)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Failed to connect to database")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT buy_price, position, sell_price, fees, bankroll, pnl, ret_pct, win_loss
                FROM {trades_t} WHERE id = %s AND status = 'closed'
                """,
                (TRADE_ID,),
            )
            row = cur.fetchone()
        if not row:
            print(f"Trade {TRADE_ID} not found or not closed")
            sys.exit(1)

        buy_price, position, sell_price, fees, bankroll, old_pnl, old_ret_pct, old_win_loss = row
        fees = fees or 0.0

        if buy_price is None or position is None or sell_price is None:
            print(f"Trade {TRADE_ID}: missing buy_price, position, or sell_price; cannot recalc")
            sys.exit(1)

        buy_value = buy_price * position
        sell_value = sell_price * position
        pnl = round(sell_value - buy_value - fees, 2)
        win_loss = "W" if pnl > 0 else "L" if pnl < 0 else "D"

        ret_pct = None
        if bankroll is not None and bankroll > 0:
            ret_pct = round((pnl / (bankroll / 100.0)) * 100, 5)

        print(f"Trade {TRADE_ID}: position={position}, buy_price={buy_price}, sell_price={sell_price}, fees={fees}, bankroll={bankroll}")
        print(f"  buy_value={buy_value}, sell_value={sell_value} -> pnl={pnl}, win_loss={win_loss}, ret_pct={ret_pct}")
        print(f"  (previous: pnl={old_pnl}, ret_pct={old_ret_pct}, win_loss={old_win_loss})")

        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {trades_t}
                SET pnl = %s, ret_pct = %s, win_loss = %s
                WHERE id = %s
                """,
                (pnl, ret_pct, win_loss, TRADE_ID),
            )
        conn.commit()
        print(f"Updated trade {TRADE_ID} with new pnl, ret_pct, win_loss.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
