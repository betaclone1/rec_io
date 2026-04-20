#!/usr/bin/env python3
"""
One-off: fix trade 9948 so it reflects monitor 10026's correct strategy and contract.
Monitor 10026 is BTC, 15m HTC. Trade had time 09:45 -> 15m contract "BTC 9:45am".

Run from project root: PYTHONPATH=/opt/rec_io_server python3 scripts/fix_trade_9948_monitor_10026.py
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
MONITOR_ID = 10026

# Correct values for monitor 10026 (BTC, 15m HTC). Contract from trade time 09:45.
CORRECT_SYMBOL = "BTC"
CORRECT_STRATEGY = "15m HTC"
CORRECT_CONTRACT = "BTC 9:45am"


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
                f"SELECT id, symbol, trade_strategy, contract FROM {trades_t} WHERE id = %s",
                (TRADE_ID,),
            )
            row = cur.fetchone()
        if not row:
            print(f"Trade {TRADE_ID} not found")
            sys.exit(1)

        old_symbol, old_strategy, old_contract = row[1], row[2], row[3]
        print(f"Trade {TRADE_ID} current: symbol={old_symbol!r}, trade_strategy={old_strategy!r}, contract={old_contract!r}")
        print(f"Updating to: symbol={CORRECT_SYMBOL!r}, trade_strategy={CORRECT_STRATEGY!r}, contract={CORRECT_CONTRACT!r}")

        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {trades_t}
                SET symbol = %s, trade_strategy = %s, contract = %s
                WHERE id = %s
                """,
                (CORRECT_SYMBOL, CORRECT_STRATEGY, CORRECT_CONTRACT, TRADE_ID),
            )
        conn.commit()
        print(f"Updated trade {TRADE_ID}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
