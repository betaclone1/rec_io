import asyncio
import json
from datetime import datetime, timedelta
from datetime import timezone
from zoneinfo import ZoneInfo
import os
import sys
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import argparse
from typing import Optional, Dict, Any
import yliveticker

# Add the project root to the Python path (permanent scalable fix)
from backend.util.paths import get_project_root
if get_project_root() not in sys.path:
    sys.path.insert(0, get_project_root())
print('DEBUG sys.path:', sys.path)

# Now import everything else
from backend.core.config.settings import config
from backend.core.port_config import get_port
from backend.util.paths import get_btc_price_history_dir, ensure_data_dirs

# Ensure all data directories exist
ensure_data_dirs()

# Symbol configuration for test version (SPX and NDX)
SYMBOL_CONFIG = {
    'SPX': {
        'yahoo_symbol': '^SPX',  # SPX Index on Yahoo Finance
        'table_name': 'live_price_log_1s_spx_test',
        'heartbeat_file': 'spx_test_logger_heartbeat_postgresql.txt',
        'price_change_file': 'spx_test_price_change_postgresql.json'
    },
    'NDX': {
        'yahoo_symbol': '^NDX',  # NASDAQ-100 Index on Yahoo Finance
        'table_name': 'live_price_log_1s_ndx_test',
        'heartbeat_file': 'ndx_test_logger_heartbeat_postgresql.txt',
        'price_change_file': 'ndx_test_price_change_postgresql.json'
    }
}

# PostgreSQL connection parameters
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
    'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
}

# Global momentum profile cache
MOMENTUM_PROFILES = {}

def load_momentum_profile(symbol: str) -> Dict[float, float]:
    """Load momentum profile from database and cache it in memory"""
    if symbol in MOMENTUM_PROFILES:
        return MOMENTUM_PROFILES[symbol]
    
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        # Find the latest dated momentum profile table for this symbol
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'analytics' 
            AND table_name LIKE %s
            ORDER BY table_name DESC
        """, (f"{symbol.lower()}_momentum_profile_%",))
        
        results = cursor.fetchall()
        if not results:
            # Fallback to base table if no dated tables exist
            profile_table = f"analytics.{symbol.lower()}_momentum_profile"
            print(f"⚠️ No dated momentum profile found for {symbol}, using base table")
        else:
            # Use the most recent dated table
            profile_table = f"analytics.{results[0][0]}"
            print(f"📊 Using momentum profile: {results[0][0]}")
        
        cursor.execute(f"SELECT percentile, momentum_value FROM {profile_table} ORDER BY percentile")
        
        profile = {}
        for row in cursor.fetchall():
            profile[float(row[0])] = float(row[1])
        
        conn.close()
        MOMENTUM_PROFILES[symbol] = profile
        print(f"✅ Loaded momentum profile for {symbol}: {len(profile)} percentiles")
        return profile
        
    except Exception as e:
        print(f"❌ Error loading momentum profile for {symbol}: {e}")
        return {}

def calculate_momentum_percentile(symbol: str, momentum_value: float) -> Optional[float]:
    """Calculate interpolated percentile for a given momentum value using the cached profile"""
    if momentum_value is None:
        return None
    
    profile = MOMENTUM_PROFILES.get(symbol)
    if not profile:
        profile = load_momentum_profile(symbol)
        if not profile:
            return None
    
    # Convert profile to sorted lists for interpolation
    percentiles = sorted(profile.keys())
    momentum_values = [profile[p] for p in percentiles]
    
    # Handle edge cases
    if momentum_value <= momentum_values[0]:
        return percentiles[0]  # Return minimum percentile
    if momentum_value >= momentum_values[-1]:
        return percentiles[-1]  # Return maximum percentile
    
    # Find the two percentiles to interpolate between
    for i in range(len(momentum_values) - 1):
        if momentum_values[i] <= momentum_value <= momentum_values[i + 1]:
            # Linear interpolation between these two points
            p1, p2 = percentiles[i], percentiles[i + 1]
            m1, m2 = momentum_values[i], momentum_values[i + 1]
            
            # Calculate interpolated percentile
            if m2 == m1:  # Avoid division by zero
                return p1
            
            # Linear interpolation formula: p = p1 + (p2-p1) * (m-m1)/(m2-m1)
            interpolated_percentile = p1 + (p2 - p1) * (momentum_value - m1) / (m2 - m1)
            return round(interpolated_percentile, 1)
    
    # Fallback: return closest percentile if interpolation fails
    closest_percentile = None
    min_distance = float('inf')
    
    for percentile, profile_momentum in profile.items():
        distance = abs(profile_momentum - momentum_value)
        if distance < min_distance:
            min_distance = distance
            closest_percentile = percentile
    
    return closest_percentile

def get_postgres_connection():
    """Get a PostgreSQL connection"""
    return psycopg2.connect(**POSTGRES_CONFIG)

def get_1m_avg_price(symbol: str) -> float:
    """
    Calculate the average price of the last 60 seconds from the PostgreSQL database.
    Returns the current price if insufficient data is available.
    """
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        # Get current time in EST
        now = datetime.now(ZoneInfo("America/New_York"))
        one_minute_ago = now - timedelta(minutes=1)
        one_minute_ago_str = one_minute_ago.strftime("%Y-%m-%dT%H:%M:%S")
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # Get all prices from the last 60 seconds
        cursor.execute(f"""
            SELECT price FROM live_data.{table_name} 
            WHERE timestamp >= %s 
            ORDER BY timestamp DESC
        """, (one_minute_ago_str,))
        
        results = cursor.fetchall()
        conn.close()
        
        if results:
            prices = [float(row[0]) for row in results]
            return sum(prices) / len(prices)
        else:
            # If no historical data, return current price
            return get_current_price(symbol)
            
    except Exception as e:
        print(f"Error calculating 1m average price: {e}")
        return get_current_price(symbol)

def get_current_price(symbol: str) -> float:
    """Get the most recent price from the PostgreSQL database"""
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        cursor.execute(f"SELECT price FROM live_data.{table_name} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return float(result[0])
        return 0.0
        
    except Exception as e:
        print(f"Error getting current price: {e}")
        return 0.0

def get_momentum_data(symbol: str = 'SPX') -> dict:
    """
    Calculate momentum data natively using the same logic as live_data_analysis.py
    Returns a dictionary with momentum information.
    """
    try:
        # Calculate momentum data natively
        momentum_data = calculate_native_momentum(symbol)
        return momentum_data
    except Exception as e:
        print(f"Failed to calculate momentum data: {e}")
        return {"momentum": None}

def get_price_at_offset(symbol: str, minutes_ago: int) -> Optional[float]:
    """Get price from X minutes ago using PostgreSQL database"""
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        # Calculate timestamp for X minutes ago in EST
        est_tz = ZoneInfo('US/Eastern')
        now_est = datetime.now(est_tz)
        target_time = now_est - timedelta(minutes=minutes_ago)
        target_timestamp = target_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # Get the closest price before the target time
        cursor.execute(f"""
            SELECT price FROM live_data.{table_name} 
            WHERE timestamp <= %s 
            ORDER BY timestamp DESC 
            LIMIT 1
        """, (target_timestamp,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return float(result[0])
        return None
        
    except Exception as e:
        print(f"Error getting price at {minutes_ago}m offset: {e}")
        return None

def get_current_price_from_db(symbol: str) -> Optional[float]:
    """Get the most recent price from PostgreSQL database"""
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        cursor.execute(f"SELECT price FROM live_data.{table_name} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return float(result[0])
        return None
        
    except Exception as e:
        print(f"Error getting current price: {e}")
        return None

def calculate_delta(current_price: float, past_price: Optional[float]) -> Optional[float]:
    """Calculate percentage delta between current and past price"""
    if past_price is None or past_price == 0:
        return None
    return ((current_price - past_price) / past_price) * 100

def calculate_momentum_deltas(symbol: str) -> Dict[str, Optional[float]]:
    """Calculate all momentum deltas (1m, 2m, 3m, 4m, 15m, 30m)"""
    current_price = get_current_price_from_db(symbol)
    if current_price is None:
        return {
            'delta_1m': None,
            'delta_2m': None,
            'delta_3m': None,
            'delta_4m': None,
            'delta_15m': None,
            'delta_30m': None
        }
    
    # Get prices at different time offsets
    price_1m = get_price_at_offset(symbol, 1)
    price_2m = get_price_at_offset(symbol, 2)
    price_3m = get_price_at_offset(symbol, 3)
    price_4m = get_price_at_offset(symbol, 4)
    price_15m = get_price_at_offset(symbol, 15)
    price_30m = get_price_at_offset(symbol, 30)
    
    # Calculate deltas
    deltas = {
        'delta_1m': calculate_delta(current_price, price_1m),
        'delta_2m': calculate_delta(current_price, price_2m),
        'delta_3m': calculate_delta(current_price, price_3m),
        'delta_4m': calculate_delta(current_price, price_4m),
        'delta_15m': calculate_delta(current_price, price_15m),
        'delta_30m': calculate_delta(current_price, price_30m)
    }
    
    return deltas

def calculate_weighted_momentum_score(deltas: Dict[str, Optional[float]]) -> Optional[float]:
    """Calculate weighted momentum score using the standard formula"""
    # Weights for each delta (same as live_data_analysis.py)
    weights = {
        'delta_1m': 0.3,
        'delta_2m': 0.25,
        'delta_3m': 0.2,
        'delta_4m': 0.15,
        'delta_15m': 0.05,
        'delta_30m': 0.05
    }
    
    weighted_sum = 0
    total_weight = 0
    
    for delta_key, weight in weights.items():
        delta_value = deltas.get(delta_key)
        if delta_value is not None:
            weighted_sum += delta_value * weight
            total_weight += weight
    
    if total_weight > 0:
        return weighted_sum / total_weight
    return None

def calculate_5s_momentum_average(symbol: str = 'SPX') -> Optional[float]:
    """Calculate 5-second rolling average of momentum values and return as percentile"""
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # Get the last 5 momentum values (last 5 seconds)
        cursor.execute(f"""
            SELECT momentum 
            FROM live_data.{table_name} 
            WHERE momentum IS NOT NULL 
            ORDER BY timestamp DESC 
            LIMIT 5
        """)
        
        results = cursor.fetchall()
        
        if len(results) < 1:
            conn.close()
            return None
        
        # Calculate average of the momentum values
        momentum_values = [float(row[0]) for row in results]
        momentum_5s_avg = sum(momentum_values) / len(momentum_values)
        
        # Convert the 5-second average to percentile
        momentum_5s_percentile = calculate_momentum_percentile(symbol, momentum_5s_avg)
        
        conn.close()
        return momentum_5s_percentile
        
    except Exception as e:
        print(f"⚠️ 5s momentum average calculation failed: {e}")
        return None

def calculate_30s_momentum_average(symbol: str = 'SPX') -> Optional[float]:
    """Calculate 30-second rolling average of momentum values and return as percentile"""
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # Get the last 30 momentum values (last 30 seconds)
        cursor.execute(f"""
            SELECT momentum 
            FROM live_data.{table_name} 
            WHERE momentum IS NOT NULL 
            ORDER BY timestamp DESC 
            LIMIT 30
        """)
        
        results = cursor.fetchall()
        
        if len(results) < 1:
            conn.close()
            return None
        
        # Calculate average of the momentum values
        momentum_values = [float(row[0]) for row in results]
        momentum_30s_avg = sum(momentum_values) / len(momentum_values)
        
        # Convert the 30-second average to percentile
        momentum_30s_percentile = calculate_momentum_percentile(symbol, momentum_30s_avg)
        
        conn.close()
        return momentum_30s_percentile
        
    except Exception as e:
        print(f"⚠️ 30s momentum average calculation failed: {e}")
        return None

def calculate_native_momentum(symbol: str = 'SPX') -> Dict[str, Any]:
    """Calculate complete momentum analysis including deltas and weighted score"""
    deltas = calculate_momentum_deltas(symbol)
    weighted_score = calculate_weighted_momentum_score(deltas)
    
    # Use EST timestamp
    est_tz = ZoneInfo('US/Eastern')
    now_est = datetime.now(est_tz)
    
    return {
        **deltas,
        'momentum': weighted_score,  # Alias for weighted_momentum_score
        'weighted_momentum_score': weighted_score,
        'timestamp': now_est.isoformat(),
        'current_price': get_current_price_from_db(symbol)
    }

def insert_tick(symbol: str, timestamp: str, price: float):
    """
    Insert symbol price tick with 1-minute average and momentum data into PostgreSQL.
    Maintains only the last 30 days of price data to prevent unlimited database growth.
    """
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Calculate 1-minute average price - handle case where no historical data exists yet
        try:
            one_minute_avg = get_1m_avg_price(symbol)
            if one_minute_avg == 0.0:  # No historical data
                one_minute_avg = price  # Use current price as fallback
        except Exception as e:
            print(f"⚠️ 1m average calculation failed (no historical data yet): {e}")
            one_minute_avg = price  # Use current price as fallback
        
        # Get momentum data - handle case where no historical data exists yet
        try:
            momentum_data = get_momentum_data(symbol)
        except Exception as e:
            print(f"⚠️ Momentum calculation failed (no historical data yet): {e}")
            momentum_data = {
                'momentum': None,
                'delta_1m': None,
                'delta_2m': None,
                'delta_3m': None,
                'delta_4m': None,
                'delta_15m': None,
                'delta_30m': None
            }
        
        # Skip momentum percentile calculation (no profile available for SPX yet)
        momentum_percentile = None
        
        # Skip 5-second momentum average for now
        momentum_5s_avg = None
        
        # Calculate 30-second momentum average
        momentum_30s_avg = None
        try:
            momentum_30s_avg = calculate_30s_momentum_average(symbol)
        except Exception as e:
            print(f"⚠️ 30s momentum average calculation failed: {e}")
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # Insert the data with all columns including momentum_percentile, momentum_5s_avg, and momentum_30s_avg
        cursor.execute(f'''
            INSERT INTO live_data.{table_name} 
            (timestamp, price, one_minute_avg, momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg, momentum_30s_avg) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (timestamp) DO UPDATE SET
                price = EXCLUDED.price,
                one_minute_avg = EXCLUDED.one_minute_avg,
                momentum = EXCLUDED.momentum,
                delta_1m = EXCLUDED.delta_1m,
                delta_2m = EXCLUDED.delta_2m,
                delta_3m = EXCLUDED.delta_3m,
                delta_4m = EXCLUDED.delta_4m,
                delta_15m = EXCLUDED.delta_15m,
                delta_30m = EXCLUDED.delta_30m,
                momentum_percentile = EXCLUDED.momentum_percentile,
                momentum_5s_avg = EXCLUDED.momentum_5s_avg,
                momentum_30s_avg = EXCLUDED.momentum_30s_avg
        ''', (
            timestamp, 
            price, 
            one_minute_avg,
            momentum_data.get('momentum'),
            momentum_data.get('delta_1m'),
            momentum_data.get('delta_2m'),
            momentum_data.get('delta_3m'),
            momentum_data.get('delta_4m'),
            momentum_data.get('delta_15m'),
            momentum_data.get('delta_30m'),
            momentum_percentile,
            momentum_5s_avg,
            momentum_30s_avg
        ))
        
        # ROLLING WINDOW: Clean up data older than 30 days
        dt = datetime.now(ZoneInfo("America/New_York")).replace(microsecond=0)
        cutoff_time = dt - timedelta(days=30)
        cutoff_iso = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
        cursor.execute(f"DELETE FROM live_data.{table_name} WHERE timestamp < %s", (cutoff_iso,))
        
        conn.commit()
        
        # Log successful price insertion
        print(f"✅ {symbol} price logged: ${price:,.2f} at {timestamp}")
        
    except Exception as e:
        print(f"⚠️ Logger encountered an error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

class YahooFinanceWatchdog:
    """Yahoo Finance WebSocket watchdog for SPX live data logging"""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.symbol_config = SYMBOL_CONFIG[symbol]
        self.last_logged_second = None
        self.ticker = None
        
        # Skip momentum profile for now - just focus on price feed
        print(f"🔄 Skipping momentum profile loading for {symbol} (test mode)...")
    
    def on_new_msg(self, ws, msg):
        """Handle incoming Yahoo Finance ticker messages"""
        try:
            print(f"📨 Received message: {msg}")  # Debug: print the actual message format
            
            # Parse the Yahoo Finance message - yliveticker returns different formats
            price = None
            if isinstance(msg, dict):
                # Try different possible price field names
                for price_field in ['price', 'regularMarketPrice', 'last', 'lastPrice', 'close']:
                    if price_field in msg and msg[price_field] is not None:
                        price = float(msg[price_field])
                        break
            
            if price is None:
                print(f"⚠️ No price found in message: {msg}")
                return
            
            now = datetime.now(ZoneInfo("America/New_York"))
            now = now.replace(microsecond=0)
            
            current_second = int(now.timestamp())
            if self.last_logged_second == current_second:
                return
            self.last_logged_second = current_second
            
            rounded_timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
            
            print(f"💰 Processing {self.symbol} price: ${price:,.2f}")
            
            # Insert the tick data
            insert_tick(self.symbol, rounded_timestamp, price)
            
            # Update heartbeat file
            heartbeat_path = os.path.join(get_btc_price_history_dir(), self.symbol_config['heartbeat_file'])
            os.makedirs(os.path.dirname(heartbeat_path), exist_ok=True)
            with open(heartbeat_path, "w") as hb:
                hb.write(f"{rounded_timestamp} {self.symbol} test logger alive (PostgreSQL)\n")
                
        except Exception as e:
            print(f"⚠️ Error processing Yahoo Finance message: {e}")
            import traceback
            traceback.print_exc()
    
    def start_logging(self):
        """Start the Yahoo Finance live ticker"""
        try:
            print(f"🚀 Starting Yahoo Finance watchdog for {self.symbol} ({self.symbol_config['yahoo_symbol']})")
            
            # Create and start the Yahoo Finance live ticker
            self.ticker = yliveticker.YLiveTicker(
                on_ticker=self.on_new_msg,
                ticker_names=[self.symbol_config['yahoo_symbol']]
            )
            
            # Keep the main thread alive
            while True:
                import time
                time.sleep(1)
                
        except KeyboardInterrupt:
            print(f"\n🛑 Stopping {self.symbol} watchdog...")
            if self.ticker:
                self.ticker.close()
        except Exception as e:
            print(f"❌ Yahoo Finance watchdog error: {e}")
            import traceback
            traceback.print_exc()

async def poll_yahoo_price_changes(symbol: str):
    """Poll Yahoo Finance for price changes using yfinance"""
    import yfinance as yf
    
    while True:
        try:
            yahoo_symbol = SYMBOL_CONFIG[symbol]['yahoo_symbol']
            ticker = yf.Ticker(yahoo_symbol)
            
            # Get historical data for the last day with 1-hour intervals
            hist = ticker.history(period="1d", interval="1h")
            
            if not hist.empty and len(hist) >= 2:
                close_now = hist['Close'].iloc[-1]
                close_1h = hist['Close'].iloc[-2] if len(hist) >= 2 else close_now
                close_3h = hist['Close'].iloc[-4] if len(hist) >= 4 else close_now
                close_1d = hist['Close'].iloc[0] if len(hist) >= 24 else close_now
                
                def pct_change(from_val, to_val):
                    return (to_val - from_val) / from_val * 100 if from_val else None
                
                changes = {
                    "change1h": pct_change(close_1h, close_now),
                    "change3h": pct_change(close_3h, close_now),
                    "change1d": pct_change(close_1d, close_now),
                    "timestamp": datetime.now(ZoneInfo("America/New_York"))
                }
                
                # Write to PostgreSQL database
                conn = get_postgres_connection()
                if conn:
                    try:
                        cursor = conn.cursor()
                        table_name = f"price_change_{symbol.lower()}_test"
                        cursor.execute(f"""
                            INSERT INTO live_data.{table_name} 
                            (change1h, change3h, change1d, timestamp)
                            VALUES (%s, %s, %s, %s)
                        """, (changes["change1h"], changes["change3h"], changes["change1d"], changes["timestamp"]))
                        conn.commit()
                        cursor.close()
                        conn.close()
                        print(f"📊 {symbol} price changes logged: 1h={changes['change1h']:.2f}%, 3h={changes['change3h']:.2f}%, 1d={changes['change1d']:.2f}%")
                    except Exception as e:
                        print(f"[Database Error for {symbol}]", e)
                        if conn:
                            conn.close()
                            
        except Exception as e:
            print(f"[Yahoo Finance Poll Error for {symbol}]", e)
        await asyncio.sleep(300)  # Poll every 5 minutes

async def main():
    parser = argparse.ArgumentParser(description='Symbol Price Watchdog Test Version')
    parser.add_argument('symbol', help='Symbol to monitor (e.g., SPX)')
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    
    if symbol not in SYMBOL_CONFIG:
        print(f"❌ Unsupported symbol: {symbol}")
        print(f"Supported symbols: {list(SYMBOL_CONFIG.keys())}")
        return
    
    print(f"Starting {symbol} Price Watchdog Test Version (PostgreSQL + Yahoo Finance)")
    
    # Create the watchdog instance
    watchdog = YahooFinanceWatchdog(symbol)
    
    # Start both the live ticker and price change polling
    try:
        # Run price change polling in the background
        poll_task = asyncio.create_task(poll_yahoo_price_changes(symbol))
        
        # Start the main watchdog (this will block)
        watchdog.start_logging()
        
    except KeyboardInterrupt:
        print(f"\n🛑 Shutting down {symbol} watchdog...")
        poll_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
