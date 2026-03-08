#!/usr/bin/env python3
"""
Backfill raw MOVEMENT scores in historical_data.btc_price_history_clone_MOVEMENT_TEST.

Movement definition:
- 1m (per row) = (high - low) / open
- 2m = avg of latest 2 rows' 1m movement, 3m = latest 3, 4m = latest 4, 15m = latest 15, 30m = latest 30
- Raw MOVEMENT score = 0.30*(1m) + 0.25*(2m) + 0.20*(3m) + 0.15*(4m) + 0.05*(15m) + 0.05*(30m), then * 100, round 4 decimals.
Same timeframes and weights as MOMENTUM. First 30 rows get NULL (need 30 bars for 30m).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pandas as pd
from core.config.database import get_postgresql_connection

TABLE = 'historical_data."btc_price_history_clone_MOVEMENT_TEST"'


def load_ohlc(conn):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT timestamp, open, high, low, close
        FROM {TABLE}
        ORDER BY timestamp
    """)
    rows = cur.fetchall()
    cur.close()
    df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def calculate_movement(df):
    # 1m movement per row
    one_m = (df['high'] - df['low']) / df['open']
    # Rolling averages (same lookbacks as momentum: 2,3,4,15,30)
    roll2 = one_m.rolling(2, min_periods=2).mean()
    roll3 = one_m.rolling(3, min_periods=3).mean()
    roll4 = one_m.rolling(4, min_periods=4).mean()
    roll15 = one_m.rolling(15, min_periods=15).mean()
    roll30 = one_m.rolling(30, min_periods=30).mean()
    # Weighted composite (1m = current row only; 2m..30m = rolling avg)
    composite = (
        0.30 * one_m
        + 0.25 * roll2
        + 0.20 * roll3
        + 0.15 * roll4
        + 0.05 * roll15
        + 0.05 * roll30
    ) * 100
    # First 30 rows: no 30m, so keep NaN; then round to 4 decimals
    movement = composite.round(4)
    return movement


def update_movement_in_db(conn, df):
    cur = conn.cursor()
    rows = df[df['movement'].notna()].copy()
    rows['timestamp'] = rows['timestamp'].astype('datetime64[ns]')
    cur.execute("""
        CREATE TEMP TABLE _movement_backfill (ts timestamp without time zone, movement numeric(10,4));
    """)
    # Use execute_values for fast bulk insert (psycopg2.extras)
    from psycopg2.extras import execute_values
    values = [(row['timestamp'], float(row['movement'])) for _, row in rows.iterrows()]
    execute_values(cur, "INSERT INTO _movement_backfill (ts, movement) VALUES %s", values, page_size=10000)
    print(f"Joined update from temp table...")
    cur.execute(f"""
        UPDATE {TABLE} t
        SET movement = m.movement
        FROM _movement_backfill m
        WHERE t.timestamp = m.ts
    """)
    updated = cur.rowcount
    conn.commit()
    cur.close()
    return updated


def main():
    conn = get_postgresql_connection()
    if not conn:
        sys.exit(1)
    print("Loading OHLC from MOVEMENT TEST table...")
    df = load_ohlc(conn)
    print(f"Loaded {len(df)} rows.")
    print("Computing movement scores...")
    df['movement'] = calculate_movement(df)
    valid = df['movement'].notna().sum()
    print(f"Computed {valid} movement values (first 30 rows NULL).")
    print("Writing to database...")
    updated = update_movement_in_db(conn, df)
    conn.close()
    print(f"Done. Updated {updated} rows.")


if __name__ == "__main__":
    main()
