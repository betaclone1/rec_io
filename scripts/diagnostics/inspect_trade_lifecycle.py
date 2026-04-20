#!/usr/bin/env python3
"""
Inspect the full lifecycle of a trade (DB-only view) to help
diagnose monitor_confirmed = FALSE cases.

Usage:
  PYTHONPATH=$(pwd) python3 scripts/diagnostics/inspect_trade_lifecycle.py [--user-no NNNN] 14050

Prints:
- Core fields from ``users.trades_<slot>``
- Any matching rows in ``users.trades_simulated_<slot>``
"""

from __future__ import annotations

import argparse
import os
import sys
from pprint import pprint

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.core.config.database import get_postgresql_connection
from backend.core.tenant_legacy_sql import legacy_users_trades, legacy_users_trades_simulated
from backend.core.tenant_script_args import add_user_no_argument, resolve_user_no


def fetch_one(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()


def main(trade_id: int, user_no: str) -> None:
    trades_t = legacy_users_trades(user_no)
    sim_t = legacy_users_trades_simulated(user_no)

    conn = get_postgresql_connection(tenant_user_no=user_no)
    if not conn:
        print("Failed to get DB connection")
        return

    with conn:
        with conn.cursor() as cur:
            print(f"=== {trades_t} id={trade_id} ===")
            row = fetch_one(
                cur,
                f"""
        SELECT
          id,
          status,
          date,
          time,
          symbol,
          trade_strategy,
          contract,
          strike,
          side,
          buy_price,
          position,
          sell_price,
          closed_at,
          ticker,
          ticket_id,
          monitor,
          symbol_open,
          symbol_close,
          high_price,
          low_price,
          monitor_confirmed,
          entry_method,
          close_method,
          created_at,
          updated_at
        FROM {trades_t}
        WHERE id = %s
        """,
                (trade_id,),
            )
            if not row:
                print(f"No row in {trades_t}")
            else:
                pprint(row)

            print(f"\n=== {sim_t} id={trade_id} (if any) ===")
            sim_row = fetch_one(
                cur,
                f"""
        SELECT
          id,
          status,
          date,
          time,
          symbol,
          trade_strategy,
          contract,
          strike,
          side,
          buy_price,
          position,
          sell_price,
          closed_at,
          ticker,
          ticket_id,
          monitor,
          symbol_open,
          symbol_close,
          high_price,
          low_price,
          monitor_confirmed,
          entry_method,
          close_method,
          created_at,
          updated_at
        FROM {sim_t}
        WHERE id = %s
        """,
                (trade_id,),
            )
            if not sim_row:
                print(f"No row in {sim_t}")
            else:
                pprint(sim_row)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    add_user_no_argument(parser)
    parser.add_argument("trade_id", type=int)
    args = parser.parse_args()
    user_no = resolve_user_no(args)
    main(args.trade_id, user_no)
