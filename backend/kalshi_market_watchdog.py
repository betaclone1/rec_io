#!/usr/bin/env python3

import sys
import os
import argparse
# Add the project root to the Python path (permanent scalable fix)
sys.path.insert(0, '/opt/rec_io_server')
from backend.util.paths import get_project_root
if get_project_root() not in sys.path:
    sys.path.insert(0, get_project_root())

import requests
import json
import time
import os
from datetime import datetime, timedelta
import pytz
import psycopg2
from psycopg2.extras import RealDictCursor

# Config
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
API_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "KalshiWatcher/1.0"
}

EST = pytz.timezone("America/New_York")

# Database configuration
DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
    'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
}

# Global variables
last_failed_ticker = None  # Global tracker
SYMBOL = None  # Will be set from command line argument

def get_watchdog_port():
    return 5432  # Default PostgreSQL port

def connect_database():
    """Connect to PostgreSQL database"""
    try:
        connection = psycopg2.connect(**DB_CONFIG)
        return connection
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Database connection failed: {e}")
        return None

def create_market_kalshi_table(connection, symbol):
    """Create the market_kalshi_{symbol} table if it doesn't exist"""
    try:
        cursor = connection.cursor()
        
        # Create the market_kalshi_{symbol} table
        table_name = f"market_kalshi_{symbol.lower()}"
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS live_data.{table_name} (
            id SERIAL PRIMARY KEY,
            event_ticker VARCHAR(50) NOT NULL,
            market_ticker VARCHAR(100) NOT NULL,
            strike VARCHAR(20),
            yes_bid INTEGER,
            yes_ask INTEGER,
            no_bid INTEGER,
            no_ask INTEGER,
            last_price INTEGER,
            volume INTEGER,
            volume_24h INTEGER,
            open_interest INTEGER,
            liquidity INTEGER,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        """
        
        cursor.execute(create_table_sql)
        
        # Add unique constraint if it doesn't exist
        try:
            constraint_name = f"{table_name}_event_market_unique"
            cursor.execute(f"""
                ALTER TABLE live_data.{table_name} 
                ADD CONSTRAINT {constraint_name} 
                UNIQUE (event_ticker, market_ticker)
            """)
        except Exception:
            # Constraint already exists
            pass
        
        connection.commit()
        print(f"[{datetime.now(EST)}] ✅ Market Kalshi {symbol.upper()} table ready")
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Failed to create table: {e}")
        connection.rollback()

def get_current_price(symbol):
    """Get current {symbol} price from the price log"""
    try:
        connection = connect_database()
        if not connection:
            return None
            
        cursor = connection.cursor()
        table_name = f"live_price_log_1s_{symbol.lower()}"
        cursor.execute(f"""
            SELECT price FROM live_data.{table_name} 
            ORDER BY timestamp DESC LIMIT 1
        """)
        result = cursor.fetchone()
        connection.close()
        
        if result:
            return result[0]
        return None
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error getting {symbol.upper()} price: {e}")
        return None

def get_current_event_ticker(symbol):
    global last_failed_ticker
    now = datetime.now(EST)

    # Define symbol-specific ticker prefixes and formats
    symbol_config = {
        'BTC': {'prefix': 'KXBTCD', 'format': 'crypto'},
        'ETH': {'prefix': 'KXETHD', 'format': 'crypto'},
        'INX': {'prefix': 'KXINXU', 'format': 'financial'},
        'SPX': {'prefix': 'KXINXU', 'format': 'financial'},  # SPX maps to INX tickers
        'NDX': {'prefix': 'KXNASDAQ100U', 'format': 'financial'},  # NDX maps to NASDAQ100 tickers
        'NASDAQ100': {'prefix': 'KXNASDAQ100U', 'format': 'financial'}
    }
    
    if symbol.upper() not in symbol_config:
        print(f"❌ Unsupported symbol: {symbol}")
        return None, None
    
    config = symbol_config[symbol.upper()]
    ticker_prefix = config['prefix']
    format_type = config['format']
    
    # Construct current hour ticker based on format
    test_time = now + timedelta(hours=1)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    
    if format_type == 'crypto':
        # Crypto format: KXBTCD-25SEP1013
        current_ticker = f"{ticker_prefix}-{year_str}{month_str}{day_str}{hour_str}"
    else:
        # Financial format: KXINXU-25SEP11H1400
        current_ticker = f"{ticker_prefix}-{year_str}{month_str}{day_str}H{hour_str}00"

    # Skip retrying if last attempt already failed this ticker
    if last_failed_ticker != current_ticker:
        data = fetch_event_json(current_ticker)
        if data and "markets" in data:
            return current_ticker, data
        else:
            last_failed_ticker = current_ticker

    # Try next hour
    test_time = now + timedelta(hours=2)
    year_str = test_time.strftime("%y")
    month_str = test_time.strftime("%b").upper()
    day_str = test_time.strftime("%d")
    hour_str = test_time.strftime("%H")
    
    if format_type == 'crypto':
        next_ticker = f"{ticker_prefix}-{year_str}{month_str}{day_str}{hour_str}"
    else:
        next_ticker = f"{ticker_prefix}-{year_str}{month_str}{day_str}H{hour_str}00"

    data = fetch_event_json(next_ticker)
    if data and "markets" in data:
        return next_ticker, data

    return None, None

def get_current_symbol_price(symbol):
    """Get current price for the symbol from live price tables"""
    try:
        connection = connect_database()
        if not connection:
            return None
            
        cursor = connection.cursor()
        
        # Map symbol to price table
        price_tables = {
            'BTC': 'live_price_log_1s_btc',
            'ETH': 'live_price_log_1s_eth', 
            'SPX': 'live_price_log_1s_spx',
            'NDX': 'live_price_log_1s_ndx'
        }
        
        table_name = price_tables.get(symbol.upper())
        if not table_name:
            connection.close()
            return None
            
        cursor.execute(f"SELECT price FROM live_data.{table_name} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        connection.close()
        
        if result:
            return float(result[0])
        return None
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error getting current price for {symbol}: {e}")
        return None

def filter_markets_by_price_range(markets_data, symbol, strike_count=75):
    """Filter markets to keep only the closest strikes to current price"""
    try:
        current_price = get_current_symbol_price(symbol)
        if not current_price:
            print(f"[{datetime.now(EST)}] ⚠️ No current price for {symbol}, returning all markets")
            return markets_data
        
        # Extract strike prices and sort by distance from current price
        markets_with_distance = []
        for market in markets_data:
            subtitle = market.get("subtitle", "")
            strike_str = subtitle.split(" or above")[0].strip() if "or above" in subtitle else ""
            
            try:
                # Parse strike price (remove $ and commas)
                strike_price = float(strike_str.replace("$", "").replace(",", ""))
                distance = abs(strike_price - current_price)
                markets_with_distance.append((market, strike_price, distance))
            except (ValueError, AttributeError):
                # Skip markets with unparseable strikes
                continue
        
        # Sort by distance from current price and take the closest ones
        markets_with_distance.sort(key=lambda x: x[2])  # Sort by distance
        closest_markets = markets_with_distance[:strike_count]
        
        # Extract just the market data
        filtered_markets = [market_data[0] for market_data in closest_markets]
        
        strike_range = ""
        if closest_markets:
            min_strike = min(m[1] for m in closest_markets)
            max_strike = max(m[1] for m in closest_markets)
            strike_range = f"${min_strike:,.0f} - ${max_strike:,.0f}"
        
        print(f"[{datetime.now(EST)}] 🎯 Filtered {len(markets_data)} markets to {len(filtered_markets)} strikes around ${current_price:,.2f} (range: {strike_range})")
        
        return filtered_markets
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error filtering markets: {e}")
        return markets_data  # Return all markets if filtering fails

def fetch_event_json(event_ticker):
    url = f"{BASE_URL}/events/{event_ticker}"
    try:
        response = requests.get(url, headers=API_HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            print(f"[{datetime.now(EST)}] ❌ API returned error for ticker {event_ticker}: {data['error']}")
            return None
        return data
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Exception fetching event JSON: {e}")
        return None

def save_market_data_to_postgresql(event_ticker, markets_data, symbol):
    """Save market data to PostgreSQL market_kalshi_{symbol} table"""
    try:
        connection = connect_database()
        if not connection:
            return False
            
        cursor = connection.cursor()
        table_name = f"market_kalshi_{symbol.lower()}"
        
        # Insert/update market data using ON CONFLICT
        for market in markets_data:
            try:
                # Extract market data
                market_ticker = market.get("ticker", "")
                
                # Extract strike from subtitle (e.g., "$104,250 or above" -> "$104,250")
                subtitle = market.get("subtitle", "")
                strike = subtitle.split(" or above")[0].strip() if "or above" in subtitle else ""
                
                # Format strike consistently for financial symbols (SPX, NDX, INX)
                if symbol.upper() in ['SPX', 'NDX', 'INX'] and strike:
                    try:
                        # Remove any existing $ and decimals, then reformat
                        clean_strike = strike.replace("$", "").replace(",", "")
                        strike_value = int(float(clean_strike))
                        strike = f"${strike_value:,}"
                    except (ValueError, TypeError):
                        pass  # Keep original strike if parsing fails
                
                yes_bid = market.get("yes_bid", 0)
                yes_ask = market.get("yes_ask", 0)
                no_bid = market.get("no_bid", 0)
                no_ask = market.get("no_ask", 0)
                last_price = market.get("last_price", 0)
                volume = market.get("volume", 0)
                volume_24h = market.get("volume_24h", 0)
                open_interest = market.get("open_interest", 0)
                liquidity = market.get("liquidity", 0)
                
                # Insert with ON CONFLICT to handle updates
                cursor.execute(f"""
                    INSERT INTO live_data.{table_name} 
                    (event_ticker, market_ticker, strike, yes_bid, yes_ask, no_bid, no_ask,
                     last_price, volume, volume_24h, open_interest, liquidity, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (event_ticker, market_ticker) DO UPDATE SET
                        yes_bid = EXCLUDED.yes_bid,
                        yes_ask = EXCLUDED.yes_ask,
                        no_bid = EXCLUDED.no_bid,
                        no_ask = EXCLUDED.no_ask,
                        last_price = EXCLUDED.last_price,
                        volume = EXCLUDED.volume,
                        volume_24h = EXCLUDED.volume_24h,
                        open_interest = EXCLUDED.open_interest,
                        liquidity = EXCLUDED.liquidity,
                        updated_at = NOW()
                """, (event_ticker, market_ticker, strike, yes_bid, yes_ask, no_bid, no_ask,
                      last_price, volume, volume_24h, open_interest, liquidity))
                
            except Exception as e:
                print(f"[{datetime.now(EST)}] ❌ Error processing market {market.get('ticker', 'unknown')}: {e}")
                continue
        
        connection.commit()
        connection.close()
        print(f"[{datetime.now(EST)}] ✅ Saved {len(markets_data)} markets to PostgreSQL for {event_ticker}")
        return True
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error saving to PostgreSQL: {e}")
        if connection:
            connection.rollback()
            connection.close()
        return False

def main():
    global SYMBOL
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Kalshi Market Watchdog for Symbol')
    parser.add_argument('symbol', help='Symbol to monitor (e.g., BTC, ETH)')
    args = parser.parse_args()
    
    SYMBOL = args.symbol.upper()
    
    print(f"[{datetime.now(EST)}] 🚀 Starting Kalshi API Market {SYMBOL} Watchdog")
    
    # Initialize database table
    connection = connect_database()
    if connection:
        create_market_kalshi_table(connection, SYMBOL)
        connection.close()
    
    # Track previous event ticker for cleanup
    previous_event_ticker = None
    
    while True:
        try:
            # Get current event ticker and data using same logic as active kalshi_api_watchdog
            event_ticker, event_data = get_current_event_ticker(SYMBOL)
            
            if event_ticker and event_data and "markets" in event_data:
                # Check if market changed - if so, clean up old data
                if previous_event_ticker and previous_event_ticker != event_ticker:
                    print(f"[{datetime.now(EST)}] 🔄 Market changed: {previous_event_ticker} → {event_ticker}")
                    print(f"[{datetime.now(EST)}] 🧹 Cleaning up old market data...")
                    
                    # Truncate table to remove old market data
                    connection = connect_database()
                    if connection:
                        cursor = connection.cursor()
                        table_name = f"live_data.market_kalshi_{SYMBOL.lower()}"
                        cursor.execute(f"TRUNCATE TABLE {table_name}")
                        connection.commit()
                        connection.close()
                        print(f"[{datetime.now(EST)}] ✅ Cleaned up old market data")
                
                print(f"[{datetime.now(EST)}] 📊 Processing event: {event_ticker}")
                
                # Filter markets to 75 closest strikes around current price
                filtered_markets = filter_markets_by_price_range(event_data["markets"], SYMBOL, 75)
                
                # Save to PostgreSQL
                success = save_market_data_to_postgresql(event_ticker, filtered_markets, SYMBOL)
                
                if not success:
                    print(f"[{datetime.now(EST)}] ❌ Failed to save data for {event_ticker}")
                
                # Update previous event ticker
                previous_event_ticker = event_ticker
            else:
                print(f"[{datetime.now(EST)}] ⚠️ No active event found")
            
            time.sleep(POLL_INTERVAL_SECONDS)
            
        except KeyboardInterrupt:
            print(f"\n[{datetime.now(EST)}] 🛑 Kalshi API Market {SYMBOL} Watchdog stopped")
            break
        except Exception as e:
            print(f"[{datetime.now(EST)}] ❌ Unexpected error: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    POLL_INTERVAL_SECONDS = 1
    main()
