import ccxt
import pandas as pd
import yfinance as yf
import os
from datetime import datetime, timedelta, timezone
import time
from typing import Optional, Tuple

# Use Coinbase (Kraken limits historical depth)
exchange = ccxt.coinbase({'enableRateLimit': True})
timeframe = '1m'
limit = 1000  # max per fetch

def get_latest_timestamp_from_csv(csv_path: str) -> Optional[datetime]:
    """
    Get the latest timestamp from an existing CSV file.
    
    Args:
        csv_path: Path to the CSV file
        
    Returns:
        Latest timestamp as datetime object, or None if file doesn't exist or is empty
    """
    if not os.path.exists(csv_path):
        return None
    
    try:
        # Read just the last few rows to get the latest timestamp
        df = pd.read_csv(csv_path, nrows=1000)
        if df.empty:
            return None
        
        # Get the last timestamp
        latest_timestamp = pd.to_datetime(df['timestamp'].iloc[-1])
        return latest_timestamp
    except Exception as e:
        print(f"Error reading latest timestamp from {csv_path}: {e}")
        return None

def fetch_full_5year_data(symbol: str = 'BTC/USD', output_dir: str = None) -> Tuple[str, int]:
    """
    Fetch full 5 years of symbol data from Coinbase API.
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD')
        output_dir: Directory to save the CSV file
        
    Returns:
        Tuple of (output_file_path, number_of_rows_fetched)
    """
    if output_dir is None:
        # Default to backend/data/live_data/price_history/{symbol_lower}
        symbol_lower = symbol.replace('/', '').lower()
        output_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'live_data', 'price_history', symbol_lower)
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Determine output filename
    symbol_clean = symbol.replace('/', '').lower()
    output_file = f"{symbol_clean}_1m_master_5y.csv"
    output_path = os.path.join(output_dir, output_file)
    
    return _perform_full_download(symbol, output_path)

def update_existing_csv(symbol: str = 'BTC/USD', csv_path: str = None) -> Tuple[str, int]:
    """
    Update an existing CSV file with new data from the last timestamp to current time.
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD')
        csv_path: Path to the existing CSV file. If None, uses default path.
        
    Returns:
        Tuple of (output_file_path, number_of_rows_fetched)
    """
    if csv_path is None:
        # Default to backend/data/live_data/price_history/{symbol_lower}/{symbol_clean}_1m_master_5y.csv
        symbol_lower = symbol.replace('/', '').lower()
        symbol_clean = symbol.replace('/', '').lower()
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'historical_data', f"{symbol_lower}_historical", f"{symbol_clean}_1m_master_5y.csv")
    
    print(f"Looking for CSV file: {csv_path}")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    
    return _perform_incremental_update(symbol, csv_path)

def _perform_incremental_update(symbol: str, output_path: str) -> Tuple[str, int]:
    """Perform incremental update: fetch from last timestamp to current time, rolling window, preserve columns."""
    print(f"Performing incremental update for {symbol}...")
    
    # Read existing data and get last timestamp
    existing_df = pd.read_csv(output_path)
    existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'])
    
    # Get the latest timestamp in existing data
    latest_timestamp = existing_df['timestamp'].max()
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
        return output_path, 0
    
    # Create DataFrame for new data
    new_df = pd.DataFrame(new_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])  # type: ignore
    new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms')
    
    # If 'momentum' column exists, add it as empty for new rows
    if 'momentum' in existing_df.columns:
        new_df['momentum'] = ''
        # Ensure all columns match
        for col in existing_df.columns:
            if col not in new_df.columns:
                new_df[col] = ''
        new_df = new_df[existing_df.columns]  # Reorder columns to match
    
    # Combine existing and new data
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    combined_df = combined_df.drop_duplicates(subset=['timestamp'], keep='last')
    combined_df = combined_df.sort_values('timestamp').reset_index(drop=True)
    
    # Rolling window: remove as many oldest rows as new rows added
    rows_added = len(new_df)
    if rows_added > 0:
        before_len = len(combined_df)
        combined_df = combined_df.iloc[rows_added:]
        after_len = len(combined_df)
        rows_removed = before_len - after_len
    else:
        rows_removed = 0
    
    # Save updated data
    combined_df.to_csv(output_path, index=False)
    
    print(f"Rolling update completed:")
    print(f"  - Added {rows_added:,} new rows")
    print(f"  - Removed {rows_removed:,} old rows (to keep file length constant)")
    print(f"  - Total rows: {len(combined_df):,}")
    print(f"  - Date range: {combined_df['timestamp'].min()} to {combined_df['timestamp'].max()}")
    if 'momentum' in combined_df.columns:
        print(f"  - Confirm: All new 'momentum' values are empty: {all(new_df['momentum'] == '')}")
    
    return output_path, rows_added

def _perform_rolling_update(symbol: str, output_path: str) -> Tuple[str, int]:
    """Perform rolling update: add latest week, remove oldest week to maintain 5-year window."""
    print(f"Performing rolling update for {symbol}...")
    
    # Read existing data
    existing_df = pd.read_csv(output_path)
    existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'])
    
    # Get the latest timestamp in existing data
    latest_timestamp = existing_df['timestamp'].max()
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
        return output_path, 0
    
    # Create DataFrame for new data
    new_df = pd.DataFrame(new_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])  # type: ignore
    new_df['timestamp'] = pd.to_datetime(new_df['timestamp'], unit='ms')
    
    # Combine existing and new data
    combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    combined_df = combined_df.drop_duplicates(subset=['timestamp'], keep='last')
    
    # Remove data older than 5 years to maintain rolling window
    combined_df = combined_df[combined_df['timestamp'] >= pd.Timestamp(five_years_ago)]
    
    # Sort by timestamp
    combined_df = combined_df.sort_values('timestamp').reset_index(drop=True)
    
    # Save updated data
    combined_df.to_csv(output_path, index=False)
    
    rows_added = len(new_df)
    rows_removed = len(existing_df) - len(combined_df) + rows_added
    
    print(f"Rolling update completed:")
    print(f"  - Added {rows_added:,} new rows")
    print(f"  - Removed {rows_removed:,} old rows")
    print(f"  - Total rows: {len(combined_df):,}")
    print(f"  - Date range: {combined_df['timestamp'].min()} to {combined_df['timestamp'].max()}")
    
    return output_path, rows_added

def _perform_full_download(symbol: str, output_path: str) -> Tuple[str, int]:
    """Perform full 5-year download."""
    print(f"Performing full 5-year download for {symbol}...")
    
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
        return output_path, 0
    
    # Create DataFrame and save
    df = pd.DataFrame(all_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])  # type: ignore
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.to_csv(output_path, index=False)
    print(f"Saved {len(df):,} bars to {output_path}")
    
    return output_path, len(df)

def update_all_symbols(symbols: Optional[list] = None) -> dict:
    """
    Update existing CSV files for multiple symbols with new data.
    
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
            output_path, rows_fetched = update_existing_csv(symbol)
            results[symbol] = {
                'output_path': output_path,
                'rows_fetched': rows_fetched,
                'status': 'success'
            }
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            results[symbol] = {
                'output_path': None,
                'rows_fetched': 0,
                'status': 'error',
                'error': str(e)
            }
    
    return results

def fetch_symbol_data(symbol: str, output_dir: str = None):
    """
    Fetch historical data for a symbol from Yahoo Finance.
    
    Args:
        symbol: The trading symbol (e.g., 'BTC-USD')
        output_dir: Output directory (defaults to backend/data/price_history/{symbol_lower})
    """
    try:
        # Default to backend/data/price_history/{symbol_lower}
        if output_dir is None:
            from backend.util.paths import get_price_history_dir
            output_dir = os.path.join(get_price_history_dir(), symbol.lower())
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Clean symbol name for filename
        symbol_clean = symbol.replace('-', '_').replace('/', '_')
        output_file = f"{symbol_clean}_1m_master_5y.csv"
        output_path = os.path.join(output_dir, output_file)
        
        print(f"📊 Fetching {symbol} data...")
        print(f"📁 Output: {output_path}")
        
        # Fetch data from Yahoo Finance
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="5y", interval="1m")
        
        if data.empty:
            print(f"❌ No data found for {symbol}")
            return None
        
        # Save to CSV
        data.to_csv(output_path)
        print(f"✅ Saved {len(data)} records to {output_path}")
        
        return output_path
        
    except Exception as e:
        print(f"❌ Error fetching {symbol} data: {e}")
        return None

def get_symbol_data_path(symbol: str) -> str:
    """
    Get the expected path for symbol data.
    
    Args:
        symbol: The trading symbol
        
    Returns:
        Expected path for the symbol's CSV file
    """
    from backend.util.paths import get_data_dir
    
    # Default to backend/data/price_history/{symbol_lower}/{symbol_clean}_1m_master_5y.csv
    symbol_lower = symbol.lower()
    symbol_clean = symbol.replace('-', '_').replace('/', '_')
    
    return os.path.join(get_data_dir(), "historical_data", f"{symbol_lower}_historical", f"{symbol_clean}_1m_master_5y.csv")

# Legacy function for backward compatibility
def fetch_btc_data():
    """Legacy function that fetches BTC data with default settings."""
    return fetch_full_5year_data('BTC/USD')

if __name__ == "__main__":
    # When run directly, fetch BTC data
    fetch_btc_data()