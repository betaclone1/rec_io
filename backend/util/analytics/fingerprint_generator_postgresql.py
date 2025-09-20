#!/usr/bin/env python3
"""
PostgreSQL Fingerprint Generator - Percentile-Based
Generates fingerprint tables directly in PostgreSQL from master price data using percentile buckets.
Creates 201 tables per symbol: <symbol>_fingerprint_-99 through <symbol>_fingerprint_+99
"""

from datetime import datetime
import os
import sys
import pandas as pd
import argparse
import json
import sqlite3
from datetime import datetime, timedelta
import numpy as np
from typing import Dict, List, Optional, Tuple

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
from backend.util.paths import get_project_root, get_data_dir

# Database imports
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("Warning: psycopg2 not available. PostgreSQL database operations will be skipped.")

def get_postgresql_connection():
    """Get a connection to the PostgreSQL database."""
    if not PSYCOPG2_AVAILABLE:
        return None
    
    try:
        from backend.core.config.database import get_postgresql_connection as get_db_conn
        return get_db_conn()
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return None

def create_analytics_schema(conn):
    """Create analytics schema if it doesn't exist."""
    try:
        cursor = conn.cursor()
        cursor.execute("CREATE SCHEMA IF NOT EXISTS analytics")
        conn.commit()
        cursor.close()
        print("✅ Analytics schema created/verified")
    except Exception as e:
        print(f"❌ Failed to create analytics schema: {e}")

def create_fingerprint_table(conn, table_name, df):
    """Create or replace fingerprint table in analytics schema."""
    try:
        cursor = conn.cursor()
        
        # Drop table if exists to overwrite
        cursor.execute(f"DROP TABLE IF EXISTS analytics.\"{table_name}\"")
        
        # Create table with time_to_close column first, then all threshold columns
        column_definitions = ['"time_to_close" TEXT PRIMARY KEY']
        
        # Convert original column names to PostgreSQL-friendly names
        for col in df.columns:
            # Parse original column name like ">= +0.05%" or "<= -0.05%"
            if '>=' in col and '+' in col and '%' in col:
                # Positive column: ">= +0.05%" -> "pos_0_05"
                percent_str = col.split('+')[1].split('%')[0]
                clean_name = f"pos_{percent_str.replace('.', '_')}"
            elif '<=' in col and '-' in col and '%' in col:
                # Negative column: "<= -0.05%" -> "neg_0_05"
                percent_str = col.split('-')[1].split('%')[0]
                clean_name = f"neg_{percent_str.replace('.', '_')}"
            else:
                # Fallback for any other format
                clean_name = f"col_{len(column_definitions) - 1}"
            
            column_definitions.append(f'"{clean_name}" DECIMAL(5,2)')
        
        create_sql = f"""
        CREATE TABLE analytics."{table_name}" (
            {', '.join(column_definitions)}
        )
        """
        
        cursor.execute(create_sql)
        conn.commit()
        cursor.close()
        print(f"✅ Created table analytics.\"{table_name}\" with clean column names")
        
    except Exception as e:
        print(f"❌ Failed to create table analytics.\"{table_name}\": {e}")
        conn.rollback()
        raise

def insert_fingerprint_data(conn, table_name, df):
    """Insert fingerprint data into PostgreSQL table."""
    try:
        cursor = conn.cursor()
        
        # Get clean column names for this table
        clean_columns = []
        for col in df.columns:
            if '>=' in col and '+' in col and '%' in col:
                percent_str = col.split('+')[1].split('%')[0]
                clean_name = f"pos_{percent_str.replace('.', '_')}"
            elif '<=' in col and '-' in col and '%' in col:
                percent_str = col.split('-')[1].split('%')[0]
                clean_name = f"neg_{percent_str.replace('.', '_')}"
            else:
                clean_name = f"col_{len(clean_columns)}"
            clean_columns.append(clean_name)
        
        # Use simple row-by-row insertion with proper error handling
        print(f"📥 Inserting {len(df)} rows...")
        
        success_count = 0
        for idx, row in df.iterrows():
            try:
                # Convert time_to_close to zero-padded format for correct ordering
                if 'm TTC' in idx:
                    minutes = idx.split('m')[0]
                    padded_minutes = minutes.zfill(2)  # Zero-pad to 2 digits
                    time_to_close = f"{padded_minutes}m TTC"
                else:
                    time_to_close = str(idx)
                
                # Prepare row data: time_to_close first, then all column values
                row_data = [time_to_close]  # time_to_close
                
                # Add each column value, converting to float
                for col in df.columns:
                    value = row[col]
                    if pd.isna(value):
                        row_data.append(None)  # NULL for missing values
                    else:
                        # Convert NumPy types to Python types
                        if hasattr(value, 'item'):
                            value = value.item()  # Convert NumPy scalar to Python scalar
                        row_data.append(float(value))
                
                # Create INSERT statement with clean column names
                placeholders = ', '.join(['%s'] * len(row_data))
                columns = ['time_to_close'] + clean_columns
                column_names = ', '.join([f'"{col}"' for col in columns])
                
                insert_sql = f'INSERT INTO analytics."{table_name}" ({column_names}) VALUES ({placeholders})'
                
                cursor.execute(insert_sql, row_data)
                success_count += 1
                
                # Show progress every 10 rows
                if success_count % 10 == 0:
                    print(f"   Inserted {success_count}/{len(df)} rows...")
                
            except Exception as e:
                print(f"❌ Failed to insert row {idx}: {e}")
                print(f"   Row data length: {len(row_data)}")
                print(f"   First 5 values: {row_data[:5]}")
                conn.rollback()
                raise
        
        conn.commit()
        cursor.close()
        print(f"✅ Successfully inserted {success_count}/{len(df)} rows")
        
    except Exception as e:
        print(f"❌ Failed to insert data into analytics.\"{table_name}\": {e}")
        conn.rollback()
        raise

def generate_directional_fingerprint(df, percentile_value=None, description="", bucket_size=1):
    """
    Generate a directional fingerprint matrix for the given dataframe.
    Tracks both positive and negative price movements relative to ATM line.
    If percentile_value is not None, only use rows with that percentile as the baseline,
    but lookahead is always over the full dataset.
    """
    year_weights = {
        2025: 5,
        2024: 4,
        2023: 3,
        2022: 2,
        2021: 1,
        2020: 1
    }

    df["year"] = df["timestamp"].dt.year
    df["weight"] = df["year"].map(year_weights).fillna(1)

    thresholds = [0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40, 1.45, 1.50, 1.55, 1.60, 1.65, 1.75, 1.80, 1.85, 1.90, 1.95, 2.00]  # in percent
    max_lookahead = 60

    # Initialize counters: for each lookahead and threshold, store [positive_successes, negative_successes, totals]
    results = {t: {th: [0, 0, 0] for th in thresholds} for t in range(1, max_lookahead + 1)}

    total_rows = len(df)
    
    # Filter data based on percentile if specified
    if percentile_value is not None:
        # Use momentum_percentile column for filtering
        if 'momentum_percentile' not in df.columns:
            print(f"❌ Error: momentum_percentile column not found for percentile filtering")
            return None
        
        # Filter to rows within the momentum bucket (e.g., bucket_value = -99 with bucket_size=10 means -99.0 to -90.0)
        bucket_min = percentile_value
        bucket_max = percentile_value + bucket_size
        
        filtered_df = df[(df['momentum_percentile'] >= bucket_min) & (df['momentum_percentile'] < bucket_max)]
        
        if len(filtered_df) == 0:
            print(f"⚠️  No data found for momentum bucket {percentile_value} (range {bucket_min} to {bucket_max})")
            return None
        
        print(f"📊 Using {len(filtered_df)} rows for momentum bucket {percentile_value} (range {bucket_min} to {bucket_max})")
        baseline_indices = filtered_df.index.tolist()
    else:
        # Use all data for baseline
        baseline_indices = df.index.tolist()
        print(f"📊 Using all {len(baseline_indices)} rows for baseline fingerprint")

    # Process each baseline point
    for baseline_idx in baseline_indices:
        baseline_price = df.loc[baseline_idx, 'close']
        baseline_weight = df.loc[baseline_idx, 'weight']
        
        # Look ahead from this point
        for lookahead in range(1, max_lookahead + 1):
            lookahead_idx = baseline_idx + lookahead
            
            if lookahead_idx >= len(df):
                break
            
            lookahead_price = df.loc[lookahead_idx, 'close']
            price_change_pct = ((lookahead_price - baseline_price) / baseline_price) * 100
            
            # Check each threshold
            for threshold in thresholds:
                if price_change_pct >= threshold:
                    results[lookahead][threshold][0] += baseline_weight  # Positive success
                if price_change_pct <= -threshold:
                    results[lookahead][threshold][1] += baseline_weight  # Negative success
                results[lookahead][threshold][2] += baseline_weight  # Total

    # Convert results to DataFrame
    rows = []
    for lookahead in range(1, max_lookahead + 1):
        row_data = {'time_to_close': f"{lookahead:02d}m TTC"}
        
        for threshold in thresholds:
            pos_success, neg_success, total = results[lookahead][threshold]
            
            if total > 0:
                pos_prob = (pos_success / total) * 100
                neg_prob = (neg_success / total) * 100
            else:
                pos_prob = 0
                neg_prob = 0
            
            row_data[f'>= +{threshold:.2f}%'] = pos_prob
            row_data[f'<= -{threshold:.2f}%'] = neg_prob
        
        rows.append(row_data)
    
    result_df = pd.DataFrame(rows)
    result_df.set_index('time_to_close', inplace=True)
    
    print(f"✅ Generated fingerprint for {description}: {len(result_df)} time periods, {len(result_df.columns)} thresholds")
    return result_df

def load_symbol_data(symbol):
    """Load symbol data from the historical_data schema."""
    conn = get_postgresql_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        # Load price data with momentum and momentum_percentile
        query = f"""
        SELECT timestamp, open, high, low, close, volume, momentum, momentum_percentile
        FROM historical_data.{symbol}_price_history
        WHERE momentum IS NOT NULL AND momentum_percentile IS NOT NULL
        ORDER BY timestamp
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print(f"❌ No data found for symbol {symbol}")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'momentum', 'momentum_percentile'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        print(f"📊 Loaded {len(df)} rows for {symbol.upper()}")
        print(f"   Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
        print(f"   Momentum range: {df['momentum'].min():.4f} to {df['momentum'].max():.4f}")
        print(f"   Percentile range: {df['momentum_percentile'].min():.1f} to {df['momentum_percentile'].max():.1f}")
        
        return df
        
    except Exception as e:
        print(f"❌ Error loading data for {symbol}: {e}")
        return None
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(
        description="Generate percentile-based fingerprint tables for trading symbols",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate fingerprints for BTC
  python fingerprint_generator_postgresql.py btc
  
  # Generate fingerprints for ETH
  python fingerprint_generator_postgresql.py eth
  
  # Generate fingerprints for multiple symbols
  python fingerprint_generator_postgresql.py btc eth
        """
    )
    parser.add_argument("symbols", nargs="+", help="Symbols to process (e.g., btc eth)")
    
    args = parser.parse_args()
    
    # Setup PostgreSQL connection
    db_conn = get_postgresql_connection()
    if db_conn:
        create_analytics_schema(db_conn)
        print("✅ PostgreSQL database connection established")
    else:
        print("❌ PostgreSQL database connection failed - cannot proceed")
        return

    # Process each symbol
    for symbol in args.symbols:
        symbol = symbol.lower()
        print(f"\n🚀 Processing symbol: {symbol.upper()}")
        
        # Load symbol data
        df = load_symbol_data(symbol)
        if df is None:
            print(f"❌ Skipping {symbol.upper()} - no data available")
            continue
        
        # Generate bucketed fingerprints (-99 to +99, grouped in 10-point ranges)
        momentum_buckets = []
        # Negative buckets: -90, -80, -70, -60, -50, -40, -30, -20, -10
        for i in range(-90, 0, 10):
            momentum_buckets.append(i)
        # Positive buckets: +10, +20, +30, +40, +50, +60, +70, +80, +90
        for i in range(10, 100, 10):
            momentum_buckets.append(i)
        
        print(f"📊 Generating {len(momentum_buckets)} bucketed fingerprint tables for {symbol.upper()}")
        print(f"📊 Each bucket represents a 10-point momentum range (e.g., -99 bucket = -99 to -90)")
        
        for bucket_value in momentum_buckets:
            print(f"   Processing momentum bucket: {bucket_value:3d} (range {bucket_value:3d} to {bucket_value+9:3d})")
            
            # Generate fingerprint for this momentum bucket (10-point range)
            bucket_df = generate_directional_fingerprint(df, bucket_value, f"momentum bucket {bucket_value}", bucket_size=10)
            
            if bucket_df is not None:
                # Create table name with proper formatting
                if bucket_value < 0:
                    table_name = f"{symbol}_fingerprint_{bucket_value:03d}"  # e.g., btc_fingerprint_-90
                else:
                    table_name = f"{symbol}_fingerprint_{bucket_value:02d}"  # e.g., btc_fingerprint_10
                
                # Write to PostgreSQL database
                create_fingerprint_table(db_conn, table_name, bucket_df)
                insert_fingerprint_data(db_conn, table_name, bucket_df)
            else:
                print(f"   ⚠️  Skipping momentum bucket {bucket_value} - no data")

    # Close database connection
    if db_conn:
        db_conn.close()
        print("\n✅ Database connection closed")

    print("\n🎉 All percentile-based fingerprint generation complete!")

if __name__ == "__main__":
    main()
