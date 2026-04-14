#!/usr/bin/env python3
"""
One-off diagnostic: print trade by id and monitor config for comparison.
Usage: PYTHONPATH=$(pwd) python scripts/inspect_trade_and_monitor.py [--user-no NNNN] <trade_id> [monitor_id]
Example: PYTHONPATH=$(pwd) python scripts/inspect_trade_and_monitor.py --user-no 0001 9948 10026
"""
import argparse
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
os.chdir(_project_root)

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no


def main():
    parser = argparse.ArgumentParser(description="Inspect trade + monitor row")
    add_user_no_argument(parser)
    parser.add_argument("trade_id", type=int)
    parser.add_argument("monitor_id", nargs="?", type=int, default=None)
    args = parser.parse_args()
    trade_id = args.trade_id
    monitor_id = args.monitor_id
    user_no = resolve_user_no(args)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Failed to connect to database")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, status, date, time, symbol, exchange, trade_strategy, contract, strike, side,
                       entry_method, monitor, paper_trade, ticket_id
                FROM users.trades_0001 WHERE id = %s
            """, (trade_id,))
            row = cur.fetchone()
        if not row:
            print(f"Trade {trade_id} not found in users.trades_0001")
            sys.exit(1)

        cols = ["id", "status", "date", "time", "symbol", "exchange", "trade_strategy", "contract", "strike", "side",
                "entry_method", "monitor", "paper_trade", "ticket_id"]
        print("--- Trade ---")
        for c, v in zip(cols, row):
            print(f"  {c}: {v}")

        # If monitor is in the trade, or monitor_id given, show monitor_list row
        mon_from_trade = None
        if row[11]:  # monitor
            # e.g. mon_0001_10026 -> 10026
            parts = str(row[11]).split("_")
            if len(parts) >= 3:
                try:
                    mon_from_trade = int(parts[2])
                except ValueError:
                    pass
        look_id = monitor_id if monitor_id is not None else mon_from_trade
        if look_id is not None:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, symbol, strategy, market, paper_trade, auto_trade, status
                    FROM users.monitor_list_0001 WHERE id = %s
                """, (look_id,))
                mrow = cur.fetchone()
            if mrow:
                mcols = ["id", "name", "symbol", "strategy", "market", "paper_trade", "auto_trade", "status"]
                print("\n--- Monitor (monitor_list_0001) ---")
                for c, v in zip(mcols, mrow):
                    print(f"  {c}: {v}")
                if row[6] != mrow[3]:  # trade_strategy != monitor strategy
                    print(f"\n  >>> MISMATCH: trade.trade_strategy = {row[6]!r}  vs  monitor.strategy = {mrow[3]!r}")
            else:
                print(f"\nMonitor id {look_id} not found in users.monitor_list_0001")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
