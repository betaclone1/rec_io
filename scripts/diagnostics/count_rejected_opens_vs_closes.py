#!/usr/bin/env python3
"""
One-off: count how many insufficient_resting_volume rejections were OPEN vs CLOSE.
Reads trade_executor.out.log and ``users.trades_<slot>``. Run from project root on prod.
"""
import argparse
import os
import re
import sys

# Allow running from project root; backend uses same
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def main():
    from backend.core.tenant_legacy_sql import legacy_users_trades
    from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no

    parser = argparse.ArgumentParser(description=__doc__)
    add_user_no_argument(parser)
    args = parser.parse_args()
    user_no = resolve_user_no(args)
    trades_t = legacy_users_trades(user_no)

    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", "trade_executor.out.log")
    if not os.path.exists(log_path):
        log_path = "/opt/rec_io_server/logs/trade_executor.out.log"
    if not os.path.exists(log_path):
        print("Log not found:", log_path)
        return 1

    ticket_ids = set()
    with open(log_path) as f:
        for line in f:
            if "insufficient_resting_volume" in line and "TRADE REJECTED" in line and "Ticket" in line:
                m = re.search(r"Ticket\s+(\d+)", line)
                if m:
                    ticket_ids.add(m.group(1))

    print(f"Unique ticket_ids in insufficient_resting_volume rejection lines: {len(ticket_ids)}")

    try:
        from backend.core.config.database import get_postgresql_connection

        conn = get_postgresql_connection(tenant_user_no=user_no)
        if not conn:
            print("DB connection failed")
            return 1
        cur = conn.cursor()
        opens = 0
        closes = 0
        not_found = 0
        for tid in ticket_ids:
            row = None
            # Try by ticket_id (various formats) then by id (in case log shows trade id)
            for key, val in [
                ("ticket_id", tid),
                ("ticket_id", "TICKET-" + tid),
                ("id", int(tid) if tid.isdigit() else None),
            ]:
                if val is None:
                    continue
                if key == "id":
                    cur.execute(f"SELECT order_id_open FROM {trades_t} WHERE id = %s", (val,))
                else:
                    cur.execute(f"SELECT order_id_open FROM {trades_t} WHERE ticket_id = %s", (val,))
                row = cur.fetchone()
                if row is not None:
                    break
            if row is None:
                not_found += 1
                continue
            if row[0] is not None and str(row[0]).strip() != "":
                closes += 1
            else:
                opens += 1
        conn.close()
        print(f"OPEN (new trade):   {opens}")
        print(f"CLOSE (existing):   {closes}")
        print(f"Not in {trades_t}: {not_found}")
        return 0
    except Exception as e:
        print("DB error:", e)
        return 1

if __name__ == "__main__":
    sys.exit(main())
