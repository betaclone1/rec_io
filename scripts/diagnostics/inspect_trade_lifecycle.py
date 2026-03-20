#!/usr/bin/env python3
"""
Inspect the full lifecycle of a trade (DB-only view) to help
diagnose monitor_confirmed = FALSE cases.

Usage:
  python3 scripts/diagnostics/inspect_trade_lifecycle.py 14050

Prints:
- Core fields from users.trades_0001
- Any matching rows in users.trades_simulated_0001
"""

import sys
from pprint import pprint

from backend.core.config.database import get_postgresql_connection


def fetch_one(cur, sql, params):
  cur.execute(sql, params)
  return cur.fetchone()


def main(trade_id: int) -> None:
  conn = get_postgresql_connection()
  if not conn:
    print("Failed to get DB connection")
    return

  with conn:
    with conn.cursor() as cur:
      print(f"=== users.trades_0001 id={trade_id} ===")
      row = fetch_one(
        cur,
        """
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
        FROM users.trades_0001
        WHERE id = %s
        """,
        (trade_id,),
      )
      if not row:
        print("No row in users.trades_0001")
      else:
        pprint(row)

      print(f"\n=== users.trades_simulated_0001 id={trade_id} (if any) ===")
      sim_row = fetch_one(
        cur,
        """
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
        FROM users.trades_simulated_0001
        WHERE id = %s
        """,
        (trade_id,),
      )
      if not sim_row:
        print("No row in users.trades_simulated_0001")
      else:
        pprint(sim_row)


if __name__ == "__main__":
  if len(sys.argv) != 2:
    print("Usage: python3 scripts/diagnostics/inspect_trade_lifecycle.py <trade_id>")
    sys.exit(1)
  main(int(sys.argv[1]))

