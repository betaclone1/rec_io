#!/usr/bin/env python3
"""
Recompute users.trades_<slot>.fees from synced Kalshi orders (open + close order_ids)
and recalculate pnl, win_loss, roi_pct, ret_pct, ret_pct_base to match close-confirm logic.

Use when a trade row has incorrect cumulative fees (e.g. double-count from overlapping confirms)
but orders_* still has the canonical taker/maker fee fields.

  PYTHONPATH=$(pwd) venv/bin/python3 scripts/db/repair_trade_fees_pnl_from_orders.py --user-no 0001 17658
  PYTHONPATH=$(pwd) venv/bin/python3 scripts/db/repair_trade_fees_pnl_from_orders.py --user-no 0001 17658 --dry-run

Production DB: set DB_HOST (e.g. REC_PROD_DB_HOST); see docs/PRODUCTION_HOST.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
os.chdir(_project_root)

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_orders, legacy_users_trades
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no


def _fee_pair(row) -> float:
    if not row:
        return 0.0

    def f(x):
        if x is None:
            return 0.0
        if isinstance(x, Decimal):
            return float(x)
        return float(x)

    return f(row[0]) + f(row[1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair trade fees + PnL from orders table")
    add_user_no_argument(parser)
    parser.add_argument("trade_id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    user_no = resolve_user_no(args)
    trade_id = args.trade_id

    trades_t = legacy_users_trades(user_no)
    orders_t = legacy_users_orders(user_no)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Failed to connect to database.", file=sys.stderr)
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, status, order_id_open, order_id_close, buy_price, sell_price, position,
                       fees, pnl, ret_pct, ret_pct_base, roi_pct, bankroll, mtb_base_value, win_loss, paper_trade
                FROM {trades_t} WHERE id = %s
                """,
                (trade_id,),
            )
            row = cur.fetchone()
            if not row:
                print(f"Trade {trade_id} not found in {trades_t}", file=sys.stderr)
                sys.exit(1)
            if row[-1]:
                print("Refusing paper_trade row (fees are not sourced from Kalshi orders).", file=sys.stderr)
                sys.exit(2)
            if str(row[1]) != "closed":
                print(f"Trade {trade_id} status is {row[1]!r}; this script targets closed rows.", file=sys.stderr)
                sys.exit(2)

            oid_open, oid_close = row[2], row[3]
            open_f = close_f = 0.0
            if oid_open:
                cur.execute(
                    f"SELECT taker_fees_dollars, maker_fees_dollars FROM {orders_t} WHERE order_id = %s",
                    (oid_open,),
                )
                orow = cur.fetchone()
                if not orow:
                    print(f"Open order {oid_open!r} not in {orders_t}", file=sys.stderr)
                    sys.exit(3)
                open_f = _fee_pair(orow)
            if oid_close:
                cur.execute(
                    f"SELECT taker_fees_dollars, maker_fees_dollars FROM {orders_t} WHERE order_id = %s",
                    (oid_close,),
                )
                crow = cur.fetchone()
                if not crow:
                    print(f"Close order {oid_close!r} not in {orders_t}", file=sys.stderr)
                    sys.exit(3)
                close_f = _fee_pair(crow)

            total_fees = open_f + close_f
            buy_price = float(row[4])
            sell_price = float(row[5])
            position = float(row[6])
            buy_value = buy_price * position
            sell_value = sell_price * position
            pnl = round(sell_value - buy_value - total_fees, 2)
            win_loss = "W" if pnl > 0 else ("L" if pnl < 0 else "D")
            roi_pct = round((pnl / buy_value) * 100.0, 5) if buy_value > 0 else None
            bankroll = row[12]
            mtb_base = row[13]
            ret_pct = None
            if bankroll is not None and float(bankroll) > 0:
                ret_pct = round((pnl / (float(bankroll) / 100.0)) * 100.0, 5)
            ret_pct_base = None
            if mtb_base is not None and float(mtb_base) > 0:
                ret_pct_base = round((pnl / (float(mtb_base) / 100.0)) * 100.0, 5)

            print(
                f"orders fees: open={open_f} close={close_f} total={total_fees} | "
                f"was fees={row[7]} pnl={row[8]} | new pnl={pnl} win_loss={win_loss} "
                f"roi_pct={roi_pct} ret_pct={ret_pct} ret_pct_base={ret_pct_base}"
            )

            if args.dry_run:
                return

            cur.execute(
                f"""
                UPDATE {trades_t}
                SET fees = %s, pnl = %s, win_loss = %s, roi_pct = %s, ret_pct = %s, ret_pct_base = %s
                WHERE id = %s
                """,
                (total_fees, pnl, win_loss, roi_pct, ret_pct, ret_pct_base, trade_id),
            )
        conn.commit()
        print(f"Updated trade {trade_id} ({cur.rowcount} row).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
