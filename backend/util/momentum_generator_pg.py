import pandas as pd
import os
import argparse
import sys
import psycopg2
from datetime import datetime, timedelta

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

from backend.core.time_eastern import merge_psycopg2_connect_kwargs


def get_postgresql_connection():
    """Get PostgreSQL connection"""
    try:
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

def calculate_momentum(df):
    print(f"Processing {len(df)} rows...")
    
    # Pre-allocate the momentum scores array for better performance
    momentum_scores = pd.Series([None] * len(df), dtype="Int64")
    
    # Process in batches for better memory management
    batch_size = 10000
    total_batches = (len(df) - 30) // batch_size + 1
    
    for batch_start in range(30, len(df), batch_size):
        batch_end = min(batch_start + batch_size, len(df))
        batch_num = (batch_start - 30) // batch_size + 1
        
        print(f"Processing batch {batch_num}/{total_batches} (rows {batch_start}-{batch_end})")
        
        for i in range(batch_start, batch_end):
            P_now = df.loc[i, 'close']
            P_1m  = df.loc[i - 1, 'close']
            P_2m  = df.loc[i - 2, 'close']
            P_3m  = df.loc[i - 3, 'close']
            P_4m  = df.loc[i - 4, 'close']
            P_15m = df.loc[i - 15, 'close']
            P_30m = df.loc[i - 30, 'close']

            score = (
                ((P_now - P_1m)  / P_1m)  * 0.30 +
                ((P_now - P_2m)  / P_2m)  * 0.25 +
                ((P_now - P_3m)  / P_3m)  * 0.20 +
                ((P_now - P_4m)  / P_4m)  * 0.15 +
                ((P_now - P_15m) / P_15m) * 0.05 +
                ((P_now - P_30m) / P_30m) * 0.05
            ) * 100

            momentum_scores.iloc[i] = round(score, 4)
    
    print("Momentum calculation complete!")
    return momentum_scores

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
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_price_history"
        
        # Build query with optional date filters
        query = f"""
            SELECT timestamp, open, high, low, close, volume, momentum
            FROM historical_data.{table_name}
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
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            raise Exception(f"No data found for {symbol}")
        
        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'momentum'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Convert numeric columns to float (handle Decimal objects from PostgreSQL)
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_columns:
            df[col] = df[col].astype(float)
        
        print(f"Loaded {len(df)} rows from {symbol} table")
        return df
        
    except Exception as e:
        raise e
    finally:
        conn.close()

def update_momentum_in_db(symbol: str, df: pd.DataFrame, indices_to_update=None):
    """
    Update momentum values in the PostgreSQL database.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        df: DataFrame with calculated momentum values
        indices_to_update: Optional list of row indices to update (if None, updates all non-null momentum)
    """
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_price_history"
        
        # Update momentum values in batches
        batch_size = 1000
        updated_count = 0
        
        # If indices_to_update is provided, only update those specific rows
        if indices_to_update is not None:
            rows_to_update = df.loc[indices_to_update]
        else:
            # Fallback to updating all non-null momentum rows (for backward compatibility)
            rows_to_update = df[df['momentum'].notna()]
        
        for i in range(0, len(rows_to_update), batch_size):
            batch_df = rows_to_update.iloc[i:i+batch_size]
            
            for _, row in batch_df.iterrows():
                if pd.notna(row['momentum']):  # Only update if momentum is not null
                    cursor.execute(f"""
                        UPDATE historical_data.{table_name}
                        SET momentum = %s
                        WHERE timestamp = %s
                    """, (float(row['momentum']), row['timestamp']))
                    updated_count += cursor.rowcount
            
            # Commit each batch
            conn.commit()
            print(f"Updated batch {i//batch_size + 1}: {len(batch_df)} rows")
        
        print(f"Successfully updated {updated_count} momentum values in database")
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def fill_missing_momentum_in_db(symbol: str, start_date: str = None, end_date: str = None):
    """
    Fill missing momentum values in the PostgreSQL database.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
    """
    print(f"Filling missing momentum for {symbol} in database...")
    
    # Load data from database
    df = load_data_from_db(symbol, start_date, end_date)
    
    # Find rows where momentum is null
    mask = df['momentum'].isnull()
    indices = df[mask].index
    print(f"Found {len(indices)} rows with missing momentum.")
    
    if len(indices) == 0:
        print("No missing momentum values to fill.")
        return
    
    # Calculate momentum for missing rows
    calculated_indices = []
    for i in indices:
        if i < 30:
            continue  # Not enough history
        
        P_now = df.loc[i, 'close']
        P_1m  = df.loc[i - 1, 'close']
        P_2m  = df.loc[i - 2, 'close']
        P_3m  = df.loc[i - 3, 'close']
        P_4m  = df.loc[i - 4, 'close']
        P_15m = df.loc[i - 15, 'close']
        P_30m = df.loc[i - 30, 'close']
        
        score = (
            ((P_now - P_1m)  / P_1m)  * 0.30 +
            ((P_now - P_2m)  / P_2m)  * 0.25 +
            ((P_now - P_3m)  / P_3m)  * 0.20 +
            ((P_now - P_4m)  / P_4m)  * 0.15 +
            ((P_now - P_15m) / P_15m) * 0.05 +
            ((P_now - P_30m) / P_30m) * 0.05
        ) * 100
        
        df.at[i, 'momentum'] = round(score, 4)
        calculated_indices.append(i)
    
    # Update database with calculated momentum values (only the ones we calculated)
    update_momentum_in_db(symbol, df, calculated_indices)
    print(f"Filled missing momentum for {len(calculated_indices)} rows in database.")

def calculate_momentum_for_db(symbol: str, start_date: str = None, end_date: str = None, overwrite: bool = False):
    """
    Calculate momentum for all rows in the database table.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
        overwrite: Whether to overwrite existing momentum values
    """
    print(f"Calculating momentum for {symbol} in database...")
    
    # Load data from database
    df = load_data_from_db(symbol, start_date, end_date)
    
    if not overwrite:
        # Check if momentum already exists
        if not df['momentum'].isnull().all():
            print("Momentum values already exist. Use --overwrite to recalculate.")
            return
    
    # Calculate momentum for all rows
    df['momentum'] = calculate_momentum(df)
    
    # Update database with calculated momentum values
    update_momentum_in_db(symbol, df)
    print(f"Successfully calculated and updated momentum for {symbol} in database.")

def get_symbols_from_db():
    """
    Get list of available symbols from the database.
    
    Returns:
        List of symbol names
    """
    conn = get_postgresql_connection()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'historical_data' 
            AND table_name LIKE '%_price_history'
        """)
        
        tables = cursor.fetchall()
        symbols = [table[0].replace('_price_history', '').upper() for table in tables]
        return symbols
        
    except Exception as e:
        print(f"Error getting symbols: {e}")
        return []
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(description="Generate momentum scores for price data in PostgreSQL database.")
    parser.add_argument("symbol", nargs='?', help="Symbol to process (e.g., BTC, ETH)")
    parser.add_argument("--start-date", help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--fill-missing", action="store_true", help="Only fill missing momentum values, do not overwrite existing values.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing momentum values.")
    parser.add_argument("--list-symbols", action="store_true", help="List available symbols in database.")
    args = parser.parse_args()

    if args.list_symbols:
        symbols = get_symbols_from_db()
        if symbols:
            print("Available symbols:")
            for symbol in symbols:
                print(f"  - {symbol}")
        else:
            print("No symbols found in database.")
        return

    if not args.symbol:
        parser.error("Symbol is required unless using --list-symbols")

    symbol = args.symbol.upper()
    
    # Check if symbol exists in database
    available_symbols = get_symbols_from_db()
    if symbol not in available_symbols:
        print(f"Symbol {symbol} not found in database. Available symbols: {available_symbols}")
        return

    if args.fill_missing:
        fill_missing_momentum_in_db(symbol, args.start_date, args.end_date)
    else:
        calculate_momentum_for_db(symbol, args.start_date, args.end_date, args.overwrite)

if __name__ == "__main__":
    main()
