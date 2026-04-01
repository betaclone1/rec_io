#!/usr/bin/env python3
"""
Movement generator for historical_data.{symbol}_price_history.

Raw MOVEMENT score: same timeframes and weights as MOMENTUM.
- 1m (per row) = (high - low) / open
- 2m = avg of latest 2 rows' 1m, 3m = latest 3, 4m = latest 4, 15m = latest 15, 30m = latest 30
- Composite = 0.30*(1m) + 0.25*(2m) + 0.20*(3m) + 0.15*(4m) + 0.05*(15m) + 0.05*(30m), then * 100, round 4 decimals.
First 30 rows get NULL.
"""

import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from backend.core.time_eastern import merge_psycopg2_connect_kwargs


def get_postgresql_connection():
    """Get PostgreSQL connection (same pattern as momentum_generator_pg)."""
    try:
        import psycopg2
        return psycopg2.connect(
            **merge_psycopg2_connect_kwargs(
                {
                    "host": "localhost",
                    "database": "rec_io_db",
                    "user": "rec_io_user",
                    "password": "rec_io_password",
                }
            )
        )
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None


def ensure_movement_columns(conn, symbol: str):
    """Ensure movement and movement_percentile columns exist on historical_data.{symbol}_price_history."""
    table = f"historical_data.{symbol.lower()}_price_history"
    cur = conn.cursor()
    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS movement NUMERIC(10,4)")
    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS movement_percentile NUMERIC(5,1)")
    conn.commit()
    cur.close()


def ensure_movement_column(conn, symbol: str):
    """Backward compat: ensure movement column (and movement_percentile) exist."""
    ensure_movement_columns(conn, symbol)


def load_data_from_db(symbol: str, start_date: str = None, end_date: str = None):
    """Load OHLC + movement from historical_data.{symbol}_price_history, ordered by timestamp."""
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    ensure_movement_columns(conn, symbol)
    try:
        cur = conn.cursor()
        table = f"{symbol.lower()}_price_history"
        query = f"""
            SELECT timestamp, open, high, low, close, movement
            FROM historical_data.{table}
        """
        params = []
        if start_date or end_date:
            query += " WHERE"
            if start_date:
                query += " timestamp >= %s"
                params.append(start_date)
            if end_date:
                if start_date:
                    query += " AND"
                query += " timestamp <= %s"
                params.append(end_date)
        query += " ORDER BY timestamp"
        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        if not rows:
            conn.close()
            raise Exception(f"No data found for {symbol}")
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'movement'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['movement'] = pd.to_numeric(df['movement'], errors='coerce')
        conn.close()
        return df
    except Exception:
        conn.close()
        raise


def calculate_movement(df: pd.DataFrame) -> pd.Series:
    """Compute raw movement score for each row. First 30 rows are NaN."""
    one_m = (df['high'] - df['low']) / df['open']
    roll2 = one_m.rolling(2, min_periods=2).mean()
    roll3 = one_m.rolling(3, min_periods=3).mean()
    roll4 = one_m.rolling(4, min_periods=4).mean()
    roll15 = one_m.rolling(15, min_periods=15).mean()
    roll30 = one_m.rolling(30, min_periods=30).mean()
    composite = (
        0.30 * one_m
        + 0.25 * roll2
        + 0.20 * roll3
        + 0.15 * roll4
        + 0.05 * roll15
        + 0.05 * roll30
    ) * 100
    return composite.round(4)


def update_movement_in_db(symbol: str, df: pd.DataFrame, indices_to_update=None):
    """Update movement values in the database. Batches of 1000."""
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    try:
        cur = conn.cursor()
        table = f"historical_data.{symbol.lower()}_price_history"
        if indices_to_update is not None:
            rows_to_update = df.loc[indices_to_update]
        else:
            rows_to_update = df[df['movement'].notna()]
        batch_size = 1000
        updated_count = 0
        for start in range(0, len(rows_to_update), batch_size):
            batch = rows_to_update.iloc[start:start + batch_size]
            for _, row in batch.iterrows():
                if pd.notna(row['movement']):
                    cur.execute(
                        f"UPDATE {table} SET movement = %s WHERE timestamp = %s",
                        (float(row['movement']), row['timestamp'])
                    )
                    updated_count += cur.rowcount
            conn.commit()
        cur.close()
        conn.close()
        return updated_count
    except Exception:
        conn.rollback()
        conn.close()
        raise


def fill_missing_movement_in_db(symbol: str, start_date: str = None, end_date: str = None):
    """Fill NULL movement for rows that have enough history (index >= 30)."""
    print(f"Filling missing movement for {symbol} in database...")
    df = load_data_from_db(symbol, start_date, end_date)
    mask = df['movement'].isnull()
    indices = df[mask].index.tolist()
    # Only rows with at least 30 prior rows
    indices = [i for i in indices if i >= 30]
    if not indices:
        print("No missing movement values to fill.")
        return
    print(f"Found {len(indices)} rows with missing movement.")
    movement_series = calculate_movement(df)
    for i in indices:
        df.at[i, 'movement'] = movement_series.iloc[i]
    update_movement_in_db(symbol, df, indices_to_update=indices)
    print(f"Filled missing movement for {len(indices)} rows.")


def get_symbols_from_db():
    """Return list of symbols that have historical_data.{symbol}_price_history tables."""
    conn = get_postgresql_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'historical_data' AND table_name LIKE '%_price_history'
        """)
        symbols = [r[0].replace('_price_history', '').upper() for r in cur.fetchall()]
        cur.close()
        conn.close()
        return symbols
    except Exception as e:
        print(f"Error getting symbols: {e}")
        conn.close()
        return []


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("symbol", nargs="?", default="btc", help="Symbol (e.g. btc, eth)")
    p.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    p.add_argument("--end", default=None, help="End date YYYY-MM-DD")
    args = p.parse_args()
    fill_missing_movement_in_db(args.symbol, args.start, args.end)
