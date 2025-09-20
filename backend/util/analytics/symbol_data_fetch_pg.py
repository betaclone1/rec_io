import ccxt
import pandas as pd
import os
import psycopg2
from datetime import datetime, timedelta, timezone
import time
from typing import Optional, Tuple
import pytz
import yfinance as yf

# Use Coinbase (Kraken limits historical depth)
exchange = ccxt.coinbase({'enableRateLimit': True})
timeframe = '1m'
limit = 1000  # max per fetch

# East Coast timezone for storing timestamps
EAST_COAST_TZ = pytz.timezone('America/New_York')

def convert_utc_to_east_coast(utc_timestamp):
    """
    Convert UTC timestamp to East Coast (New York) time.
    
    Args:
        utc_timestamp: UTC datetime object or pandas timestamp
        
    Returns:
        East Coast datetime object (timezone-naive)
    """
    if utc_timestamp.tz is None:
        # If no timezone info, assume it's UTC
        utc_timestamp = pytz.utc.localize(utc_timestamp)
    elif utc_timestamp.tz != pytz.UTC:
        # Convert to UTC first if it's in a different timezone
        utc_timestamp = utc_timestamp.tz_convert(pytz.UTC)
    
    # Convert to East Coast time and remove timezone info
    east_coast_time = utc_timestamp.tz_convert(EAST_COAST_TZ)
    return east_coast_time.tz_localize(None)

def is_financial_symbol(symbol: str) -> bool:
    """
    Determine if a symbol is a financial symbol (stocks, indices) vs crypto.
    
    Args:
        symbol: Trading symbol (e.g., 'SPX', 'BTC/USD')
        
    Returns:
        True if financial symbol, False if crypto
    """
    # Financial symbols (indices, stocks)
    financial_symbols = ['SPX', 'NDX', 'SPY', 'QQQ', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
    crypto_symbols = ['BTC', 'ETH', 'LTC', 'XRP', 'ADA', 'DOT', 'SOL', 'AVAX', 'MATIC']
    
    # Extract base symbol (remove /USD, -USD suffixes)
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

def get_yahoo_symbol_format(symbol: str) -> str:
    """
    Convert symbol to Yahoo Finance format.
    
    Args:
        symbol: Trading symbol (e.g., 'SPX')
        
    Returns:
        Yahoo Finance formatted symbol (e.g., '^GSPC' for SPX)
    """
    symbol_mapping = {
        'SPX': '^GSPC',  # S&P 500 Index
        'NDX': '^NDX',   # NASDAQ 100 Index
        'SPY': 'SPY',    # SPDR S&P 500 ETF
        'QQQ': 'QQQ'     # Invesco QQQ Trust
    }
    
    return symbol_mapping.get(symbol.upper(), symbol)

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

def get_latest_timestamp_from_db(symbol: str) -> Optional[datetime]:
    """
    Get the latest timestamp from the PostgreSQL database table.
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        
    Returns:
        Latest timestamp as datetime object, or None if table doesn't exist or is empty
    """
    conn = get_postgresql_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        table_name = f"{symbol.lower()}_price_history"
        
        # Check if table exists
        cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'historical_data' 
                AND table_name = '{table_name}'
            );
        """)
        
        if not cursor.fetchone()[0]:
            print(f"Table historical_data.{table_name} does not exist")
            return None
        
        # Get the latest timestamp
        cursor.execute(f"""
            SELECT MAX(timestamp) FROM historical_data.{table_name}
        """)
        
        result = cursor.fetchone()
        if result and result[0]:
            return result[0]
        return None
        
    except Exception as e:
        print(f"Error reading latest timestamp from database: {e}")
        return None
    finally:
        conn.close()

def fetch_full_5year_data_pg(symbol: str = 'BTC/USD') -> Tuple[str, int]:
    """
    Fetch full 5 years of symbol data from Coinbase API and store in PostgreSQL.
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD')
        
    Returns:
        Tuple of (table_name, number_of_rows_fetched)
    """
    # Extract symbol name (e.g., 'BTC/USD' -> 'BTC')
    symbol_name = symbol.split('/')[0]
    table_name = f"{symbol_name.lower()}_price_history"
    
    return _perform_full_download_pg(symbol, table_name)

def update_existing_db(symbol: str = 'BTC/USD') -> Tuple[str, int]:
    """
    Update an existing PostgreSQL table with new data from the last timestamp to current time.
    Supports both crypto symbols (via CCXT) and financial symbols (via Yahoo Finance).
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD', 'SPX')
        
    Returns:
        Tuple of (table_name, number_of_rows_fetched)
    """
    # Extract symbol name (e.g., 'BTC/USD' -> 'BTC', 'SPX' -> 'SPX')
    symbol_name = symbol.split('/')[0]
    table_name = f"{symbol_name.lower()}_price_history"
    
    print(f"Looking for table: historical_data.{table_name}")
    print(f"Symbol type: {'Financial' if is_financial_symbol(symbol) else 'Crypto'}")
    
    # Check if table exists
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'historical_data' 
                AND table_name = '{table_name}'
            );
        """)
        
        table_exists = cursor.fetchone()[0]
        
    finally:
        conn.close()
    
    if table_exists:
        # Table exists, check if it has data
        latest_timestamp = get_latest_timestamp_from_db(symbol.split('/')[0])
        if latest_timestamp:
            # Table has data, perform incremental update
            if is_financial_symbol(symbol):
                return _perform_incremental_update_yahoo_pg(symbol, table_name)
            else:
                return _perform_incremental_update_pg(symbol, table_name)
        else:
            # Table exists but is empty, perform full download
            print(f"Table {table_name} exists but is empty. Performing full download...")
            if is_financial_symbol(symbol):
                return _perform_full_download_yahoo_pg(symbol, table_name)
            else:
                return _perform_full_download_pg(symbol, table_name)
    else:
        # Table doesn't exist, create it and perform full download
        print(f"Table {table_name} doesn't exist. Creating table and performing full download...")
        create_table_if_not_exists(symbol)
        if is_financial_symbol(symbol):
            return _perform_full_download_yahoo_pg(symbol, table_name)
        else:
            return _perform_full_download_pg(symbol, table_name)

def _perform_incremental_update_pg(symbol: str, table_name: str) -> Tuple[str, int]:
    """Perform incremental update: fetch from last timestamp to current time, rolling window."""
    print(f"Performing incremental update for {symbol} in table {table_name}...")
    
    # Get the latest timestamp in existing data
    latest_timestamp = get_latest_timestamp_from_db(symbol.split('/')[0])
    if not latest_timestamp:
        raise Exception(f"No existing data found in table {table_name}")
    
    print(f"Latest data timestamp: {latest_timestamp}")
    
    # Start from 1 minute after the latest timestamp
    start_time = latest_timestamp + timedelta(minutes=1)
    print(f"Fetching from: {start_time}")
    
    # Fetch new data from start_time to present
    since = exchange.parse8601(start_time.strftime('%Y-%m-%dT%H:%M:%SZ'))
    current_time = exchange.milliseconds()
    
    new_bars = []
    while since < current_time:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not bars:
                print("No more new data returned.")
                break

            print(f"Fetched {len(bars)} new bars from {pd.to_datetime(bars[0][0], unit='ms')} to {pd.to_datetime(bars[-1][0], unit='ms')}")
            new_bars.extend(bars)
            since = bars[-1][0] + 60 * 1000  # move 1m past last timestamp

            time.sleep(exchange.rateLimit / 1000)  # respect rate limit
        except Exception as e:
            print("Error encountered, retrying in 5 seconds:", e)
            time.sleep(5)
            continue
    
    if not new_bars:
        print("No new data to add.")
        return table_name, 0
    
    # Create DataFrame for new data
    new_df = pd.DataFrame(new_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms')
    # Convert UTC timestamps to East Coast time
    new_df['timestamp'] = new_df['timestamp'].apply(convert_utc_to_east_coast)
    
    # Insert new data into PostgreSQL
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        
        # Insert new data
        rows_added = 0
        for _, row in new_df.iterrows():
            try:
                cursor.execute(f"""
                    INSERT INTO historical_data.{table_name} 
                    (timestamp, open, high, low, close, volume, momentum, momentum_percentile)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (timestamp) DO NOTHING
                """, (
                    row['timestamp'],
                    float(row['open']),
                    float(row['high']),
                    float(row['low']),
                    float(row['close']),
                    float(row['volume']),
                    None,  # momentum column
                    None   # momentum_percentile column
                ))
                rows_added += cursor.rowcount
            except Exception as e:
                print(f"Error inserting row {row['timestamp']}: {e}")
                continue
        
        conn.commit()
        
        # Get total count after update
        cursor.execute(f"SELECT COUNT(*) FROM historical_data.{table_name}")
        total_rows = cursor.fetchone()[0]
        
        print(f"Incremental update completed:")
        print(f"  - Added {rows_added:,} new rows")
        print(f"  - Total rows in table: {total_rows:,}")
        
        return table_name, rows_added
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def _perform_rolling_update_pg(symbol: str, table_name: str) -> Tuple[str, int]:
    """Perform rolling update: add latest week, remove oldest week to maintain 5-year window."""
    print(f"Performing rolling update for {symbol} in table {table_name}...")
    
    # Get the latest timestamp in existing data
    latest_timestamp = get_latest_timestamp_from_db(symbol.split('/')[0])
    if not latest_timestamp:
        raise Exception(f"No existing data found in table {table_name}")
    
    print(f"Latest data timestamp: {latest_timestamp}")
    
    # Calculate 5 years ago from now
    five_years_ago = datetime.now(timezone.utc) - timedelta(days=5 * 365)
    print(f"5-year window start: {five_years_ago}")
    
    # Fetch new data from latest timestamp to present
    since = exchange.parse8601((latest_timestamp + timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))
    current_time = exchange.milliseconds()
    
    new_bars = []
    while since < current_time:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not bars:
                print("No more new data returned.")
                break

            print(f"Fetched {len(bars)} new bars from {pd.to_datetime(bars[0][0], unit='ms')} to {pd.to_datetime(bars[-1][0], unit='ms')}")
            new_bars.extend(bars)
            since = bars[-1][0] + 60 * 1000  # move 1m past last timestamp

            time.sleep(exchange.rateLimit / 1000)  # respect rate limit
        except Exception as e:
            print("Error encountered, retrying in 5 seconds:", e)
            time.sleep(5)
            continue
    
    if not new_bars:
        print("No new data to add.")
        return table_name, 0
    
    # Create DataFrame for new data
    new_df = pd.DataFrame(new_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms')
    # Convert UTC timestamps to East Coast time
    new_df['timestamp'] = new_df['timestamp'].apply(convert_utc_to_east_coast)
    
    # Insert new data and remove old data
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        
        # Insert new data
        rows_added = 0
        for _, row in new_df.iterrows():
            try:
                cursor.execute(f"""
                    INSERT INTO historical_data.{table_name} 
                    (timestamp, open, high, low, close, volume, momentum, momentum_percentile)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (timestamp) DO NOTHING
                """, (
                    row['timestamp'],
                    float(row['open']),
                    float(row['high']),
                    float(row['low']),
                    float(row['close']),
                    float(row['volume']),
                    None,  # momentum column
                    None   # momentum_percentile column
                ))
                rows_added += cursor.rowcount
            except Exception as e:
                print(f"Error inserting row {row['timestamp']}: {e}")
                continue
        
        # Remove data older than 5 years
        cursor.execute(f"""
            DELETE FROM historical_data.{table_name} 
            WHERE timestamp < %s
        """, (five_years_ago,))
        
        rows_removed = cursor.rowcount
        conn.commit()
        
        # Get total count after update
        cursor.execute(f"SELECT COUNT(*) FROM historical_data.{table_name}")
        total_rows = cursor.fetchone()[0]
        
        print(f"Rolling update completed:")
        print(f"  - Added {rows_added:,} new rows")
        print(f"  - Removed {rows_removed:,} old rows")
        print(f"  - Total rows in table: {total_rows:,}")
        
        return table_name, rows_added
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def _perform_full_download_pg(symbol: str, table_name: str) -> Tuple[str, int]:
    """Perform full 5-year download to PostgreSQL."""
    print(f"Performing full 5-year download for {symbol} to table {table_name}...")
    
    # Start 5 years ago from now, UTC-aware
    five_years_ago = datetime.now(timezone.utc) - timedelta(days=5 * 365)
    since = exchange.parse8601(five_years_ago.strftime('%Y-%m-%dT%H:%M:%SZ'))
    print(f"Starting full download from {five_years_ago.strftime('%Y-%m-%d %H:%M:%S')} to present...")
    
    all_bars = []
    current_time = exchange.milliseconds()
    
    while since < current_time:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not bars:
                print("No more data returned. Exiting.")
                break

            print(f"Fetched {len(bars)} bars from {pd.to_datetime(bars[0][0], unit='ms')} to {pd.to_datetime(bars[-1][0], unit='ms')}")
            all_bars.extend(bars)
            since = bars[-1][0] + 60 * 1000  # move 1m past last timestamp

            if len(all_bars) % (limit * 10) == 0:
                latest_dt = pd.to_datetime(all_bars[-1][0], unit='ms')
                print(f"Progress: {len(all_bars):,} rows — up to {latest_dt}")

            time.sleep(exchange.rateLimit / 1000)  # respect rate limit
        except Exception as e:
            print("Error encountered, retrying in 5 seconds:", e)
            time.sleep(5)
            continue
    
    if not all_bars:
        print("No data to save.")
        return table_name, 0
    
    # Create DataFrame
    df = pd.DataFrame(all_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    # Convert UTC timestamps to East Coast time
    df['timestamp'] = df['timestamp'].apply(convert_utc_to_east_coast)
    
    # Insert into PostgreSQL
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        
        # Clear existing data
        cursor.execute(f"DELETE FROM historical_data.{table_name}")
        
        # Insert all data
        rows_inserted = 0
        for _, row in df.iterrows():
            try:
                # Check for NaN values and skip them
                if pd.isna(row['open']) or pd.isna(row['high']) or pd.isna(row['low']) or pd.isna(row['close']) or pd.isna(row['volume']):
                    print(f"Skipping row {row['timestamp']} due to NaN values")
                    continue
                
                cursor.execute(f"""
                    INSERT INTO historical_data.{table_name} 
                    (timestamp, open, high, low, close, volume, momentum, momentum_percentile)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    row['timestamp'],
                    float(row['open']),
                    float(row['high']),
                    float(row['low']),
                    float(row['close']),
                    float(row['volume']),
                    None,  # momentum column
                    None   # momentum_percentile column
                ))
                rows_inserted += 1
                
                # Commit every 1000 rows to avoid long transactions
                if rows_inserted % 1000 == 0:
                    conn.commit()
                    print(f"Committed {rows_inserted} rows so far...")
                    
            except Exception as e:
                print(f"Error inserting row {row['timestamp']}: {e}")
                # Rollback and continue with next row
                conn.rollback()
                continue
        
        conn.commit()
        print(f"Saved {rows_inserted:,} bars to table {table_name}")
        
        return table_name, rows_inserted
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def update_all_symbols_pg(symbols: Optional[list] = None) -> dict:
    """
    Update existing PostgreSQL tables for multiple symbols with new data.
    
    Args:
        symbols: List of symbols to update. If None, uses default list.
        
    Returns:
        Dictionary with results for each symbol
    """
    if symbols is None:
        symbols = ['BTC/USD']  # Add more symbols here as needed
    
    results = {}
    for symbol in symbols:
        print(f"\n=== Processing {symbol} ===")
        try:
            table_name, rows_fetched = update_existing_db(symbol)
            results[symbol] = {
                'table_name': table_name,
                'rows_fetched': rows_fetched,
                'status': 'success'
            }
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            results[symbol] = {
                'table_name': None,
                'rows_fetched': 0,
                'status': 'error',
                'error': str(e)
            }
    
    return results

def create_table_if_not_exists(symbol: str):
    """
    Create the PostgreSQL table for a symbol if it doesn't exist.
    
    Args:
        symbol: The trading symbol (e.g., 'BTC/USD')
    """
    symbol_name = symbol.split('/')[0]
    table_name = f"{symbol_name.lower()}_price_history"
    
    conn = get_postgresql_connection()
    if not conn:
        raise Exception("Failed to connect to PostgreSQL")
    
    try:
        cursor = conn.cursor()
        
        # Create schema if it doesn't exist
        cursor.execute("CREATE SCHEMA IF NOT EXISTS historical_data")
        
        # Create table if it doesn't exist
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS historical_data.{table_name} (
                timestamp TIMESTAMP WITHOUT TIME ZONE PRIMARY KEY,
                open NUMERIC(20,8),
                high NUMERIC(20,8),
                low NUMERIC(20,8),
                close NUMERIC(20,8),
                volume NUMERIC(20,8),
                momentum NUMERIC(10,2),
                momentum_percentile NUMERIC(10,2)
            )
        """)
        
        # Add comment to document timezone
        cursor.execute(f"""
            COMMENT ON TABLE historical_data.{table_name} IS 
            'Price history data with timestamps in East Coast (America/New_York) timezone'
        """)
        
        # Create unique index on timestamp
        cursor.execute(f"""
            CREATE UNIQUE INDEX IF NOT EXISTS unique_{table_name}_timestamp 
            ON historical_data.{table_name} (timestamp)
        """)
        
        conn.commit()
        print(f"✅ Table historical_data.{table_name} created/verified")
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# Yahoo Finance functions for financial symbols
def _perform_incremental_update_yahoo_pg(symbol: str, table_name: str) -> Tuple[str, int]:
    """
    Perform incremental update for financial symbols using Yahoo Finance.
    
    Args:
        symbol: Financial symbol (e.g., 'SPX')
        table_name: Database table name
        
    Returns:
        Tuple of (table_name, number_of_rows_fetched)
    """
    print(f"Performing Yahoo Finance incremental update for {symbol} in table {table_name}...")
    
    # Get the latest timestamp in existing data
    latest_timestamp = get_latest_timestamp_from_db(symbol.split('/')[0])
    if not latest_timestamp:
        raise Exception(f"No existing data found in table {table_name}")
    
    print(f"Latest data timestamp: {latest_timestamp}")
    
    # Get Yahoo Finance formatted symbol
    yahoo_symbol = get_yahoo_symbol_format(symbol)
    print(f"Yahoo Finance symbol: {yahoo_symbol}")
    
    # Calculate how many days to fetch (from latest timestamp to now + buffer)
    days_to_fetch = (datetime.now() - latest_timestamp).days + 2
    print(f"Fetching {days_to_fetch} days of data")
    
    try:
        # Fetch data from Yahoo Finance
        ticker = yf.Ticker(yahoo_symbol)
        data = ticker.history(period=f"{days_to_fetch}d", interval="1m")
        
        if data.empty:
            print("No new data available from Yahoo Finance")
            return table_name, 0
        
        # Reset index to get timestamp as column
        data = data.reset_index()
        
        # Convert to our format
        new_df = pd.DataFrame()
        new_df['timestamp'] = data['Datetime']
        new_df['open'] = data['Open']
        new_df['high'] = data['High']
        new_df['low'] = data['Low']
        new_df['close'] = data['Close']
        new_df['volume'] = data['Volume']
        new_df['momentum'] = None
        new_df['momentum_percentile'] = None
        
        # Convert timestamps to East Coast time
        new_df['timestamp'] = pd.to_datetime(new_df['timestamp'])
        if new_df['timestamp'].dt.tz is not None:
            new_df['timestamp'] = new_df['timestamp'].dt.tz_convert('America/New_York').dt.tz_localize(None)
        
        # Filter out data we already have (only keep data after latest timestamp)
        new_df = new_df[new_df['timestamp'] > latest_timestamp]
        
        # Apply after-hours filtering (09:30-16:00 only)
        new_df = new_df[
            (new_df['timestamp'].dt.time >= pd.Timestamp('09:30:00').time()) &
            (new_df['timestamp'].dt.time <= pd.Timestamp('16:00:00').time())
        ]
        
        if new_df.empty:
            print("No new data after filtering")
            return table_name, 0
        
        print(f"Found {len(new_df)} new records to insert")
        
        # Insert new data into PostgreSQL
        conn = get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Insert new data
            for _, row in new_df.iterrows():
                cursor.execute(f"""
                    INSERT INTO historical_data.{table_name} 
                    (timestamp, open, high, low, close, volume, momentum, momentum_percentile)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (timestamp) DO NOTHING
                """, (
                    row['timestamp'],
                    float(row['open']),
                    float(row['high']),
                    float(row['low']),
                    float(row['close']),
                    float(row['volume']),
                    None,
                    None
                ))
            
            conn.commit()
            print(f"✅ Successfully inserted {len(new_df)} new records")
            return table_name, len(new_df)
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
    except Exception as e:
        print(f"❌ Error fetching Yahoo Finance data: {e}")
        raise e

def _perform_full_download_yahoo_pg(symbol: str, table_name: str) -> Tuple[str, int]:
    """
    Perform full download for financial symbols using Yahoo Finance.
    
    Args:
        symbol: Financial symbol (e.g., 'SPX')
        table_name: Database table name
        
    Returns:
        Tuple of (table_name, number_of_rows_fetched)
    """
    print(f"Performing Yahoo Finance full download for {symbol} in table {table_name}...")
    
    # Get Yahoo Finance formatted symbol
    yahoo_symbol = get_yahoo_symbol_format(symbol)
    print(f"Yahoo Finance symbol: {yahoo_symbol}")
    
    try:
        # Fetch 5 years of data from Yahoo Finance
        ticker = yf.Ticker(yahoo_symbol)
        data = ticker.history(period="5y", interval="1m")
        
        if data.empty:
            print("No data available from Yahoo Finance")
            return table_name, 0
        
        # Reset index to get timestamp as column
        data = data.reset_index()
        
        # Convert to our format
        df = pd.DataFrame()
        df['timestamp'] = data['Datetime']
        df['open'] = data['Open']
        df['high'] = data['High']
        df['low'] = data['Low']
        df['close'] = data['Close']
        df['volume'] = data['Volume']
        df['momentum'] = None
        df['momentum_percentile'] = None
        
        # Convert timestamps to East Coast time
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        if df['timestamp'].dt.tz is not None:
            df['timestamp'] = df['timestamp'].dt.tz_convert('America/New_York').dt.tz_localize(None)
        
        # Apply after-hours filtering (09:30-16:00 only)
        df = df[
            (df['timestamp'].dt.time >= pd.Timestamp('09:30:00').time()) &
            (df['timestamp'].dt.time <= pd.Timestamp('16:00:00').time())
        ]
        
        print(f"Found {len(df)} records after filtering")
        
        # Clear existing data and insert new data
        conn = get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Clear existing data
            cursor.execute(f"DELETE FROM historical_data.{table_name}")
            
            # Insert new data in batches
            batch_size = 1000
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i+batch_size]
                
                for _, row in batch.iterrows():
                    cursor.execute(f"""
                        INSERT INTO historical_data.{table_name} 
                        (timestamp, open, high, low, close, volume, momentum, momentum_percentile)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        row['timestamp'],
                        float(row['open']),
                        float(row['high']),
                        float(row['low']),
                        float(row['close']),
                        float(row['volume']),
                        None,
                        None
                    ))
                
                print(f"Inserted batch {i//batch_size + 1}/{(len(df)-1)//batch_size + 1}")
            
            conn.commit()
            print(f"✅ Successfully inserted {len(df)} records")
            return table_name, len(df)
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
    except Exception as e:
        print(f"❌ Error fetching Yahoo Finance data: {e}")
        raise e

# Legacy function for backward compatibility
def fetch_btc_data_pg():
    """Legacy function that fetches BTC data with default settings."""
    return fetch_full_5year_data_pg('BTC/USD')

if __name__ == "__main__":
    # When run directly, update BTC data
    update_existing_db('BTC/USD')
