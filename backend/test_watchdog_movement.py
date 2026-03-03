#!/usr/bin/env python3
"""Test movement write in symbol_price_watchdog: insert_tick then verify movement columns.

Run from project root with project deps installed (e.g. venv with requirements.txt):
  python -m backend.test_watchdog_movement
"""
import os
import sys
from zoneinfo import ZoneInfo
from datetime import datetime

# Project root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import psycopg2

# Use same env as watchdog
POSTGRES_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "database": os.getenv("POSTGRES_DB", "rec_io_db"),
    "user": os.getenv("POSTGRES_USER", "rec_io_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "rec_io_password"),
}


def main():
    from backend.symbol_price_watchdog import (
        insert_tick,
        load_movement_profile,
        get_postgres_connection,
        SYMBOL_CONFIG,
    )

    symbol = "BTC"
    table_name = SYMBOL_CONFIG[symbol]["table_name"]

    # Pre-load movement profile so percentile can be computed
    print("Loading movement profile for BTC...")
    load_movement_profile(symbol)

    now = datetime.now(ZoneInfo("America/New_York")).replace(microsecond=0)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    # Use a fixed price for reproducibility; in real run current price would be used
    conn = get_postgres_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT price FROM live_data.{table_name} ORDER BY timestamp DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    price = float(row[0]) if row else 97000.0

    print(f"Inserting tick: symbol={symbol} timestamp={timestamp} price={price}")
    insert_tick(symbol, timestamp, price)

    # Read back last row and print movement columns
    conn = get_postgres_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT timestamp, price,
               move_1m, move_2m, move_3m, move_4m, move_15m, move_30m,
               movement, movement_percentile
        FROM live_data.{table_name}
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    conn.close()

    if not row:
        print("No row found after insert")
        sys.exit(1)

    print("\nLast row movement columns:")
    print(f"  timestamp             = {row[0]}")
    print(f"  price                 = {row[1]}")
    print(f"  move_1m               = {row[2]}")
    print(f"  move_2m               = {row[3]}")
    print(f"  move_3m               = {row[4]}")
    print(f"  move_4m               = {row[5]}")
    print(f"  move_15m              = {row[6]}")
    print(f"  move_30m              = {row[7]}")
    print(f"  movement              = {row[8]}")
    print(f"  movement_percentile   = {row[9]}")

    # At least 1m and composite should be present when there is data in the 1m window
    if row[2] is not None and row[8] is not None:
        print("\nOK: move_1m and movement are set.")
    else:
        print("\nNote: move_1m or movement NULL (can happen if no ticks in window yet).")
    print("Done.")


if __name__ == "__main__":
    main()
