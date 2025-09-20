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
    """Get PostgreSQL connection"""
    try:
        return psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None

def interpolate_momentum_percentile(momentum_value, momentum_profile_df):
    """
    Interpolate momentum percentile based on momentum value and profile.
    
    Args:
        momentum_value: The momentum value to interpolate for
        momentum_profile_df: DataFrame with percentile and momentum_value columns
        
    Returns:
        Interpolated percentile value (rounded to 1 decimal place)
    """
    if momentum_profile_df.empty:
        return None
    
    # Sort by momentum_value for interpolation
    profile_sorted = momentum_profile_df.sort_values('momentum_value')
    
    # Find the closest two points for interpolation
    momentum_values = profile_sorted['momentum_value'].values
    percentiles = profile_sorted['percentile'].values
    
    # Handle edge cases
    if momentum_value <= momentum_values[0]:
        return round(percentiles[0], 1)
    if momentum_value >= momentum_values[-1]:
        return round(percentiles[-1], 1)
    
    # Find the two closest points
    for i in range(len(momentum_values) - 1):
        if momentum_values[i] <= momentum_value <= momentum_values[i + 1]:
            # Linear interpolation
            x0, x1 = momentum_values[i], momentum_values[i + 1]
            y0, y1 = percentiles[i], percentiles[i + 1]
            
            # Interpolate
            interpolated_percentile = y0 + (y1 - y0) * (momentum_value - x0) / (x1 - x0)
            return round(interpolated_percentile, 1)
    
    return None

def load_momentum_profile(symbol):
    """
    Load momentum profile from analytics schema.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        
    Returns:
        DataFrame with percentile and momentum_value columns
    """
    conn = get_postgresql_connection()
    if not conn:
        return pd.DataFrame()
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_momentum_profile"
        
        cursor.execute(f"""
            SELECT percentile, momentum_value
            FROM analytics.{table_name}
            ORDER BY percentile
        """)
        
        rows = cursor.fetchall()
        if not rows:
            print(f"No momentum profile found for {symbol}")
            return pd.DataFrame()
        
        df = pd.DataFrame(rows, columns=['percentile', 'momentum_value'])
        
        # Convert Decimal objects to float
        df['percentile'] = df['percentile'].astype(float)
        df['momentum_value'] = df['momentum_value'].astype(float)
        
        return df
        
    except Exception as e:
        print(f"Error loading momentum profile: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def calculate_momentum(df):
    print(f"Processing {len(df)} rows...")
    
    # Pre-allocate the momentum scores array for better performance
    momentum_scores = pd.Series([None] * len(df), dtype="float64")
    
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
            SELECT timestamp, open, high, low, close, volume, momentum, momentum_percentile
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
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'momentum', 'momentum_percentile'])
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Convert numeric columns to float (handle Decimal objects from PostgreSQL)
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'momentum', 'momentum_percentile']
        for col in numeric_columns:
            df[col] = df[col].astype(float)
        
        print(f"Loaded {len(df)} rows from {symbol} table")
        return df
        
    except Exception as e:
        raise e
    finally:
        conn.close()

def update_momentum_in_db(symbol: str, df: pd.DataFrame, indices_to_update=None, update_percentiles=True):
    """
    Update momentum values and percentiles in the PostgreSQL database.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        df: DataFrame with calculated momentum values
        indices_to_update: Optional list of row indices to update (if None, updates all non-null momentum)
        update_percentiles: Whether to also update momentum percentiles
    """
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_price_history"
        
        # Load momentum profile for percentile interpolation
        momentum_profile_df = pd.DataFrame()
        if update_percentiles:
            momentum_profile_df = load_momentum_profile(symbol)
            if momentum_profile_df.empty:
                print("Warning: Could not load momentum profile, skipping percentile updates")
                update_percentiles = False
        
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
                    if update_percentiles:
                        # Interpolate momentum percentile
                        momentum_percentile = interpolate_momentum_percentile(row['momentum'], momentum_profile_df)
                        
                        cursor.execute(f"""
                            UPDATE historical_data.{table_name}
                            SET momentum = %s, momentum_percentile = %s
                            WHERE timestamp = %s
                        """, (float(row['momentum']), float(momentum_percentile) if momentum_percentile is not None else None, row['timestamp']))
                    else:
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
    Uses gap substitution method for financial symbols.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        start_date: Optional start date filter (YYYY-MM-DD)
        end_date: Optional end date filter (YYYY-MM-DD)
    """
    print(f"Filling missing momentum for {symbol} in database...")
    
    # Check if this is a financial symbol
    is_financial = is_financial_symbol(symbol)
    print(f"Symbol type: {'Financial' if is_financial else 'Crypto'}")
    
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
        if is_financial:
            momentum = calculate_financial_momentum_with_gaps(df, i)
        else:
            momentum = calculate_crypto_momentum_standard(df, i)
        
        if momentum is not None:
            df.at[i, 'momentum'] = momentum
            calculated_indices.append(i)
    
    # Update database with calculated momentum values (only the ones we calculated)
    update_momentum_in_db(symbol, df, calculated_indices, update_percentiles=True)
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
    update_momentum_in_db(symbol, df, update_percentiles=True)
    print(f"Successfully calculated and updated momentum for {symbol} in database.")

def is_financial_symbol(symbol: str) -> bool:
    """
    Determine if a symbol is a financial symbol (stocks, indices) vs crypto.
    """
    financial_symbols = ['SPX', 'NDX', 'SPY', 'QQQ', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
    crypto_symbols = ['BTC', 'ETH', 'LTC', 'XRP', 'ADA', 'DOT', 'SOL', 'AVAX', 'MATIC']
    
    base_symbol = symbol.split('/')[0].split('-')[0].upper()
    
    # Check crypto first
    if base_symbol in crypto_symbols:
        return False
    if '/' in symbol and 'USD' in symbol:
        return False  # Likely crypto (BTC/USD, ETH/USD)
    
    # Check financial
    if base_symbol in financial_symbols:
        return True
    
    # Default to financial for unknown single symbols
    return True

def calculate_financial_momentum_with_gaps(df: pd.DataFrame, index: int) -> Optional[float]:
    """
    Calculate momentum for financial symbols using gap substitution method.
    """
    if index < 1:
        return None
    
    current_price = df.loc[index, 'close']
    current_timestamp = df.loc[index, 'timestamp']
    
    # Get overnight gap (if we're early in trading session)
    overnight_gap = get_overnight_gap_delta(df, index)
    
    # Calculate each momentum component
    deltas = []
    weights = [0.30, 0.25, 0.20, 0.15, 0.05, 0.05]  # 1m, 2m, 3m, 4m, 15m, 30m
    lookbacks = [1, 2, 3, 4, 15, 30]
    
    for minutes_back, weight in zip(lookbacks, weights):
        if index >= minutes_back and is_same_trading_session(df, index, index - minutes_back):
            # We have live data for this lookback period
            past_price = df.loc[index - minutes_back, 'close']
            delta = (current_price - past_price) / past_price
        elif overnight_gap is not None:
            # Use overnight gap as substitute
            delta = overnight_gap
        else:
            # No data available, skip this component
            continue
            
        deltas.append(delta * weight)
    
    if not deltas:
        return None
    
    # Sum weighted deltas and convert to percentage
    momentum = sum(deltas) * 100
    return round(momentum, 4)

def calculate_crypto_momentum_standard(df: pd.DataFrame, index: int) -> Optional[float]:
    """
    Calculate momentum for crypto symbols using standard method.
    """
    if index < 30:
        return None  # Not enough history
    
    P_now = df.loc[index, 'close']
    P_1m  = df.loc[index - 1, 'close']
    P_2m  = df.loc[index - 2, 'close']
    P_3m  = df.loc[index - 3, 'close']
    P_4m  = df.loc[index - 4, 'close']
    P_15m = df.loc[index - 15, 'close']
    P_30m = df.loc[index - 30, 'close']
    
    score = (
        ((P_now - P_1m)  / P_1m)  * 0.30 +
        ((P_now - P_2m)  / P_2m)  * 0.25 +
        ((P_now - P_3m)  / P_3m)  * 0.20 +
        ((P_now - P_4m)  / P_4m)  * 0.15 +
        ((P_now - P_15m) / P_15m) * 0.05 +
        ((P_now - P_30m) / P_30m) * 0.05
    ) * 100
    
    return round(score, 4)

def get_overnight_gap_delta(df: pd.DataFrame, current_index: int) -> Optional[float]:
    """Get overnight gap delta if we're early in the trading session."""
    current_timestamp = df.loc[current_index, 'timestamp']
    current_price = df.loc[current_index, 'close']
    
    # Only use gap substitution in first 30 minutes of trading
    if not is_early_trading_session(current_timestamp):
        return None
    
    # Find previous trading day's close
    prev_close = find_previous_close(df, current_index)
    if prev_close is None:
        return None
    
    # Calculate overnight gap delta
    gap_delta = (current_price - prev_close) / prev_close
    return gap_delta

def is_early_trading_session(timestamp: pd.Timestamp) -> bool:
    """Check if we're in the first 30 minutes of trading (9:30-10:00 AM)."""
    import pandas as pd
    time_of_day = timestamp.time()
    return (pd.Timestamp('09:30:00').time() <= time_of_day <= pd.Timestamp('10:00:00').time())

def find_previous_close(df: pd.DataFrame, current_index: int) -> Optional[float]:
    """Find the previous trading day's closing price by looking for a significant time gap."""
    current_timestamp = df.loc[current_index, 'timestamp']
    
    # Look backwards for a gap > 30 minutes (indicates overnight/weekend break)
    for i in range(current_index - 1, max(0, current_index - 200), -1):
        past_timestamp = df.loc[i, 'timestamp']
        time_diff = (current_timestamp - past_timestamp).total_seconds() / 60  # minutes
        
        if time_diff > 30:  # Found overnight/weekend gap
            return df.loc[i, 'close']
    
    return None

def is_same_trading_session(df: pd.DataFrame, index1: int, index2: int) -> bool:
    """Check if two indices are from the same trading session."""
    if index1 < 0 or index2 < 0 or index1 >= len(df) or index2 >= len(df):
        return False
        
    timestamp1 = df.loc[index1, 'timestamp']
    timestamp2 = df.loc[index2, 'timestamp']
    
    # Different dates = different sessions
    if timestamp1.date() != timestamp2.date():
        return False
    
    # Check for gaps > 5 minutes
    time_diff = abs((timestamp1 - timestamp2).total_seconds() / 60)
    expected_diff = abs(index1 - index2) * 1.5  # Allow 1.5 minutes per index step
    
    return time_diff <= expected_diff

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
