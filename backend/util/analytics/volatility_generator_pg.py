import pandas as pd
import os
import argparse
import sys
import psycopg2
from datetime import datetime, timedelta
import numpy as np
from typing import Optional

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

def get_postgresql_connection():
    """Global historical_data pipeline: system DB, not tenant-scoped."""
    try:
        from backend.core.config.database import get_system_postgresql_connection

        return get_system_postgresql_connection()
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None

def calculate_weighted_multi_timeframe_volatility(df: pd.DataFrame, index: int) -> Optional[float]:
    """
    Calculate weighted multi-timeframe volatility using True Range (ATR-based approach).
    
    True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
    Converted to percentage: TR / prev_close
    
    Weights:
    - 1m: 0.40
    - 5m: 0.30
    - 15m: 0.15
    - 30m: 0.10
    - 60m: 0.05
    
    Args:
        df: DataFrame with price data (must have open, high, low, close columns)
        index: Current row index
        
    Returns:
        Volatility value (float) or None if insufficient data
    """
    if index < 60:
        return None
    
    try:
        def calculate_true_range(current_idx: int) -> Optional[float]:
            """Calculate True Range for a given index as a percentage."""
            if current_idx < 1:
                return None
            
            high = df.loc[current_idx, 'high']
            low = df.loc[current_idx, 'low']
            prev_close = df.loc[current_idx - 1, 'close']
            
            # True Range formula
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            
            # Convert to percentage
            if prev_close > 0:
                return tr / prev_close
            return None
        
        # Calculate True Range values for each timeframe
        # 1m volatility (last 1 minute)
        if index >= 1:
            tr_1m = calculate_true_range(index)
            vol_1m = tr_1m if tr_1m is not None else 0.0
        else:
            vol_1m = 0.0
        
        # 5m volatility (last 5 minutes) - standard deviation of TR values
        if index >= 5:
            tr_values_5m = []
            for i in range(5):
                if index - i >= 1:
                    tr = calculate_true_range(index - i)
                    if tr is not None:
                        tr_values_5m.append(tr)
            vol_5m = np.std(tr_values_5m) if len(tr_values_5m) > 1 else (tr_values_5m[0] if tr_values_5m else 0.0)
        else:
            vol_5m = 0.0
        
        # 15m volatility (last 15 minutes)
        if index >= 15:
            tr_values_15m = []
            for i in range(15):
                if index - i >= 1:
                    tr = calculate_true_range(index - i)
                    if tr is not None:
                        tr_values_15m.append(tr)
            vol_15m = np.std(tr_values_15m) if len(tr_values_15m) > 1 else (tr_values_15m[0] if tr_values_15m else 0.0)
        else:
            vol_15m = 0.0
        
        # 30m volatility (last 30 minutes)
        if index >= 30:
            tr_values_30m = []
            for i in range(30):
                if index - i >= 1:
                    tr = calculate_true_range(index - i)
                    if tr is not None:
                        tr_values_30m.append(tr)
            vol_30m = np.std(tr_values_30m) if len(tr_values_30m) > 1 else (tr_values_30m[0] if tr_values_30m else 0.0)
        else:
            vol_30m = 0.0
        
        # 60m volatility (last 60 minutes)
        if index >= 60:
            tr_values_60m = []
            for i in range(60):
                if index - i >= 1:
                    tr = calculate_true_range(index - i)
                    if tr is not None:
                        tr_values_60m.append(tr)
            vol_60m = np.std(tr_values_60m) if len(tr_values_60m) > 1 else (tr_values_60m[0] if tr_values_60m else 0.0)
        else:
            vol_60m = 0.0
        
        # Weighted average
        weighted_vol = (
            vol_1m * 0.40 +
            vol_5m * 0.30 +
            vol_15m * 0.15 +
            vol_30m * 0.10 +
            vol_60m * 0.05
        )
        
        return round(weighted_vol, 6) if not np.isnan(weighted_vol) else None
        
    except (IndexError, KeyError, ZeroDivisionError):
        return None

def load_data_from_db(symbol: str, start_date: str = None, end_date: str = None):
    """
    Load price data from PostgreSQL database.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
        
    Returns:
        DataFrame with price data
    """
    conn = get_postgresql_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_price_history"
        
        # Build query
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM historical_data.{table_name}
        """
        
        conditions = []
        if start_date:
            conditions.append(f"timestamp >= '{start_date}'")
        if end_date:
            conditions.append(f"timestamp <= '{end_date}'")
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY timestamp"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print(f"No data found for {symbol}")
            return None
        
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Ensure numeric types
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        print(f"Loaded {len(df)} rows from {symbol} table")
        return df
        
    except Exception as e:
        print(f"Error loading data: {e}")
        return None
    finally:
        conn.close()

def update_volatility_in_db(symbol: str, df: pd.DataFrame, indices_to_update=None):
    """
    Update volatility values in PostgreSQL database.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        df: DataFrame with calculated volatility values
        indices_to_update: Optional list of indices to update (if None, updates all)
    """
    conn = get_postgresql_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_price_history"
        
        if indices_to_update is None:
            indices_to_update = range(60, len(df))  # Start from index 60 (need 60 minutes of history)
        
        updated_count = 0
        for idx in indices_to_update:
            if idx >= len(df) or pd.isna(df.loc[idx, 'volatility']):
                continue
            
            timestamp = df.loc[idx, 'timestamp']
            volatility = df.loc[idx, 'volatility']
            
            cursor.execute(f"""
                UPDATE historical_data.{table_name}
                SET volatility = %s
                WHERE timestamp = %s
            """, (float(volatility), timestamp))
            
            updated_count += 1
        
        conn.commit()
        print(f"Updated {updated_count} volatility values in database")
        
    except Exception as e:
        conn.rollback()
        print(f"Error updating volatility: {e}")
    finally:
        conn.close()

def fill_missing_volatility_in_db(symbol: str, start_date: str = None, end_date: str = None):
    """
    Calculate and fill volatility values in the database.
    Recalculates ALL volatility values (not just missing ones) to ensure consistency.
    Processes in batches and writes incrementally to avoid memory issues.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
    """
    print(f"Calculating volatility for {symbol} in database...")
    print(f"Loading price data from database...")
    
    # Load data
    df = load_data_from_db(symbol, start_date, end_date)
    if df is None or len(df) < 60:
        print(f"Insufficient data for {symbol}")
        return
    
    total_rows = len(df)
    rows_to_process = total_rows - 60  # Start from index 60
    print(f"✅ Loaded {total_rows:,} rows from database")
    print(f"Calculating volatility for {rows_to_process:,} rows (starting from index 60)...")
    
    # Process in batches to avoid memory issues and provide progress updates
    batch_size = 10000
    print(f"Processing in batches of {batch_size:,} rows...")
    total_calculated = 0
    total_updated = 0
    
    conn = get_postgresql_connection()
    if not conn:
        print("Failed to connect to PostgreSQL")
        return
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_price_history"
        
        # Process in batches
        for batch_start in range(60, total_rows, batch_size):
            batch_end = min(batch_start + batch_size, total_rows)
            batch_calculated = 0
            
            print(f"Starting batch {batch_start:,}-{batch_end:,}...")
            
            # Calculate volatility for this batch
            for idx in range(batch_start, batch_end):
                volatility = calculate_weighted_multi_timeframe_volatility(df, idx)
                if volatility is not None:
                    # Update in database immediately
                    timestamp = df.loc[idx, 'timestamp']
                    try:
                        cursor.execute(f"""
                            UPDATE historical_data.{table_name}
                            SET volatility = %s
                            WHERE timestamp = %s
                        """, (float(volatility), timestamp))
                        batch_calculated += 1
                    except Exception as e:
                        print(f"Error updating row {idx} ({timestamp}): {e}")
                        conn.rollback()
                        continue
                
                # Progress update every 1000 rows within batch
                if (idx - batch_start) % 1000 == 0 and (idx - batch_start) > 0:
                    print(f"  Processed {idx - batch_start:,} rows in current batch...")
            
            # Commit this batch
            conn.commit()
            total_calculated += batch_calculated
            total_updated += batch_calculated
            
            # Progress update
            progress_pct = (batch_end - 60) / rows_to_process * 100
            print(f"✅ Completed batch {batch_start:,}-{batch_end:,}: {batch_calculated:,} rows calculated ({progress_pct:.1f}% complete, {total_calculated:,} total)")
        
        print(f"✅ Completed: Calculated and updated {total_updated:,} volatility values in database.")
        
    except Exception as e:
        conn.rollback()
        print(f"Error processing volatility: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculate and fill volatility values")
    parser.add_argument("--symbol", required=True, help="Symbol (BTC, ETH, etc.)")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    fill_missing_volatility_in_db(args.symbol, args.start_date, args.end_date)

