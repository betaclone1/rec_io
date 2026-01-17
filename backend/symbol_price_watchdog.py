import asyncio
import websockets
import json
from datetime import datetime, timedelta
from datetime import timezone
from zoneinfo import ZoneInfo
import os
import sys
import aiohttp
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
import argparse
from typing import Optional, Dict, Any, Tuple
import yliveticker
import numpy as np
import threading
import time

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

# Symbol configuration
SYMBOL_CONFIG = {
    'BTC': {
        'method': 'coinbase',
        'api_endpoint': 'wss://ws-feed.exchange.coinbase.com',
        'product_id': 'BTC-USD',
        'table_name': 'live_price_log_1s_btc',
        'heartbeat_file': 'btc_logger_heartbeat_postgresql.txt',
        'price_change_file': 'btc_price_change_postgresql.json'
    },
    'ETH': {
        'method': 'coinbase',
        'api_endpoint': 'wss://ws-feed.exchange.coinbase.com',
        'product_id': 'ETH-USD',
        'table_name': 'live_price_log_1s_eth',
        'heartbeat_file': 'eth_logger_heartbeat_postgresql.txt',
        'price_change_file': 'eth_price_change_postgresql.json'
    },
    'SPX': {
        'method': 'yahoo_finance',
        'yahoo_symbol': '^SPX',
        'table_name': 'live_price_log_1s_spx',
        'heartbeat_file': 'spx_logger_heartbeat_postgresql.txt',
        'price_change_file': 'spx_price_change_postgresql.json'
    },
    'NDX': {
        'method': 'yahoo_finance',
        'yahoo_symbol': '^NDX',
        'table_name': 'live_price_log_1s_ndx',
        'heartbeat_file': 'ndx_logger_heartbeat_postgresql.txt',
        'price_change_file': 'ndx_price_change_postgresql.json'
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

# Global volatility profile cache
VOLATILITY_PROFILES = {}

# Global volatility value cache: {symbol: {minute_key: (volatility_value, volatility_percentile)}}
VOLATILITY_CACHE = {}

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

def load_volatility_profile(symbol: str) -> Dict[float, float]:
    """Load volatility profile from database and cache it in memory"""
    if symbol in VOLATILITY_PROFILES:
        return VOLATILITY_PROFILES[symbol]
    
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        # Find the latest dated volatility profile table for this symbol
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'analytics' 
            AND table_name LIKE %s
            ORDER BY table_name DESC
        """, (f"{symbol.lower()}_volatility_profile_%",))
        
        results = cursor.fetchall()
        if not results:
            print(f"⚠️ No dated volatility profile found for {symbol}")
            conn.close()
            return {}
        
        # Use the most recent dated table
        profile_table = f"analytics.{results[0][0]}"
        print(f"📊 Using volatility profile: {results[0][0]}")
        
        cursor.execute(f"SELECT percentile, volatility_value FROM {profile_table} ORDER BY percentile")
        
        profile = {}
        for row in cursor.fetchall():
            profile[float(row[0])] = float(row[1])
        
        conn.close()
        VOLATILITY_PROFILES[symbol] = profile
        print(f"✅ Loaded volatility profile for {symbol}: {len(profile)} percentiles")
        return profile
        
    except Exception as e:
        print(f"❌ Error loading volatility profile for {symbol}: {e}")
        return {}

def calculate_volatility_percentile(symbol: str, volatility_value: float) -> Optional[float]:
    """Calculate interpolated percentile for a given volatility value using the cached profile"""
    if volatility_value is None:
        return None
    
    profile = VOLATILITY_PROFILES.get(symbol)
    if not profile:
        profile = load_volatility_profile(symbol)
        if not profile:
            return None
    
    # Convert profile to sorted lists for interpolation
    percentiles = sorted(profile.keys())
    volatility_values = [profile[p] for p in percentiles]
    
    # Handle edge cases
    if volatility_value <= volatility_values[0]:
        return percentiles[0]
    if volatility_value >= volatility_values[-1]:
        return percentiles[-1]
    
    # Find the two percentiles to interpolate between
    for i in range(len(volatility_values) - 1):
        if volatility_values[i] <= volatility_value <= volatility_values[i + 1]:
            p1, p2 = percentiles[i], percentiles[i + 1]
            v1, v2 = volatility_values[i], volatility_values[i + 1]
            
            if v2 == v1:
                return p1
            
            interpolated_percentile = p1 + (p2 - p1) * (volatility_value - v1) / (v2 - v1)
            return round(interpolated_percentile, 1)
    
    # Fallback: return closest percentile
    closest_percentile = None
    min_distance = float('inf')
    for percentile, profile_volatility in profile.items():
        distance = abs(profile_volatility - volatility_value)
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

def get_momentum_data(symbol: str = 'BTC') -> dict:
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

def calculate_5s_momentum_average(symbol: str = 'BTC') -> Optional[float]:
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

def calculate_30s_momentum_average(symbol: str = 'BTC') -> Optional[float]:
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

def calculate_native_momentum(symbol: str = 'BTC') -> Dict[str, Any]:
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

def get_minute_candles_for_volatility(symbol: str) -> list:
    """
    Get 1-minute OHLC candles from the last 60 minutes using separate connection.
    Returns list of dicts with keys: open, high, low, close
    """
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        
        # Get current time in EST
        now = datetime.now(ZoneInfo("America/New_York"))
        cutoff_time = now - timedelta(minutes=60)
        cutoff_str = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # SQL aggregation - returns 60 rows (one per minute)
        cursor.execute(f"""
            SELECT 
                DATE_TRUNC('minute', timestamp::timestamp)::text as minute,
                MIN(price) as low,
                MAX(price) as high,
                (array_agg(price ORDER BY timestamp))[1] as open,
                (array_agg(price ORDER BY timestamp DESC))[1] as close
            FROM live_data.{table_name}
            WHERE timestamp >= %s
            GROUP BY DATE_TRUNC('minute', timestamp::timestamp)
            ORDER BY minute
        """, (cutoff_str,))
        
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        candles = []
        for row in rows:
            candles.append({
                'open': float(row[3]),
                'high': float(row[1]),
                'low': float(row[2]),
                'close': float(row[4])
            })
        
        return candles
        
    except Exception as e:
        print(f"⚠️ Error getting minute candles for volatility: {e}")
        return []

def calculate_native_volatility(symbol: str = 'BTC') -> Optional[float]:
    """
    Calculate weighted multi-timeframe volatility using True Range (ATR-based approach).
    Matches the calculation method in volatility_generator_pg.py
    """
    try:
        # Get last 60 minutes of candles
        candles = get_minute_candles_for_volatility(symbol)
        
        if len(candles) < 59:  # Allow 59 candles (current minute might not be complete)
            return None
        
        # Calculate True Range for each candle
        tr_values = []
        for i in range(len(candles)):
            if i == 0:
                prev_close = candles[0]['open']
            else:
                prev_close = candles[i - 1]['close']
            
            high = candles[i]['high']
            low = candles[i]['low']
            
            # True Range formula
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            
            # Convert to percentage
            if prev_close > 0:
                tr_values.append(tr / prev_close)
        
        if len(tr_values) < 59:  # Need at least 59 candles (current minute might not be complete)
            return None
        
        # Calculate volatility for each timeframe
        # Use available data (might be 59 or 60 candles)
        num_candles = len(tr_values)
        
        # 1m volatility (last 1 minute) - just the TR value
        vol_1m = float(tr_values[-1]) if num_candles >= 1 else 0.0
        
        # 5m volatility (last 5 minutes) - standard deviation of TR values
        if num_candles >= 5:
            tr_5m = tr_values[-5:]
            vol_5m = float(np.std(tr_5m)) if len(tr_5m) > 1 else float(tr_5m[0] if tr_5m else 0.0)
        else:
            vol_5m = 0.0
        
        # 15m volatility (last 15 minutes)
        if num_candles >= 15:
            tr_15m = tr_values[-15:]
            vol_15m = float(np.std(tr_15m)) if len(tr_15m) > 1 else float(tr_15m[0] if tr_15m else 0.0)
        else:
            vol_15m = 0.0
        
        # 30m volatility (last 30 minutes)
        if num_candles >= 30:
            tr_30m = tr_values[-30:]
            vol_30m = float(np.std(tr_30m)) if len(tr_30m) > 1 else float(tr_30m[0] if tr_30m else 0.0)
        else:
            vol_30m = 0.0
        
        # 60m volatility (last 60 minutes) - use all available
        if num_candles >= 59:
            tr_60m = tr_values[-min(60, num_candles):]
            vol_60m = float(np.std(tr_60m)) if len(tr_60m) > 1 else float(tr_60m[0] if tr_60m else 0.0)
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
        
        if np.isnan(weighted_vol):
            return None
        
        # Convert to Python float (not numpy type) to avoid SQL errors
        return float(round(weighted_vol, 6))
        
    except Exception as e:
        print(f"⚠️ Error calculating volatility: {e}")
        return None

def get_volatility_for_minute(symbol: str, minute_key: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Get volatility value and percentile for a given minute.
    Calculates synchronously on first tick of new minute, then caches.
    """
    # Initialize cache for symbol if needed
    if symbol not in VOLATILITY_CACHE:
        VOLATILITY_CACHE[symbol] = {}
    
    # Check if we already have this minute cached
    if minute_key in VOLATILITY_CACHE[symbol]:
        return VOLATILITY_CACHE[symbol][minute_key]
    
    # New minute - calculate it now (synchronously, once per minute)
    try:
        volatility_value = calculate_native_volatility(symbol)
        volatility_percentile = None
        
        if volatility_value is not None:
            try:
                volatility_percentile = calculate_volatility_percentile(symbol, volatility_value)
            except Exception as e:
                print(f"⚠️ Volatility percentile calculation failed for {symbol}: {e}")
                volatility_percentile = None
    except Exception as e:
        print(f"⚠️ Volatility calculation failed for {symbol}: {e}")
        volatility_value = None
        volatility_percentile = None
    
    # Cache the result (even if None)
    VOLATILITY_CACHE[symbol][minute_key] = (volatility_value, volatility_percentile)
    
    # Keep cache size reasonable (last 2 minutes)
    if len(VOLATILITY_CACHE[symbol]) > 2:
        oldest_key = min(VOLATILITY_CACHE[symbol].keys())
        del VOLATILITY_CACHE[symbol][oldest_key]
    
    return (volatility_value, volatility_percentile)

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
        
        # Calculate momentum percentile
        momentum_percentile = None
        if momentum_data.get('momentum') is not None:
            try:
                momentum_percentile = calculate_momentum_percentile(symbol, momentum_data['momentum'])
            except Exception as e:
                print(f"⚠️ Momentum percentile calculation failed: {e}")
        
        # Calculate 5-second momentum average
        momentum_5s_avg = None
        try:
            momentum_5s_avg = calculate_5s_momentum_average(symbol)
        except Exception as e:
            print(f"⚠️ 5s momentum average calculation failed: {e}")
        
        # Calculate 30-second momentum average
        momentum_30s_avg = None
        try:
            momentum_30s_avg = calculate_30s_momentum_average(symbol)
        except Exception as e:
            print(f"⚠️ 30s momentum average calculation failed: {e}")
        
        # Get volatility for current minute (calculated synchronously on first tick of minute)
        minute_key = timestamp[:16]  # Extract minute key (YYYY-MM-DDTHH:MM)
        volatility_value, volatility_percentile = get_volatility_for_minute(symbol, minute_key)
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # Insert the data with all columns including momentum_percentile, momentum_5s_avg, momentum_30s_avg, volatility, and volatility_percentile
        cursor.execute(f'''
            INSERT INTO live_data.{table_name} 
            (timestamp, price, one_minute_avg, momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg, momentum_30s_avg, volatility, volatility_percentile) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                momentum_30s_avg = EXCLUDED.momentum_30s_avg,
                volatility = EXCLUDED.volatility,
                volatility_percentile = EXCLUDED.volatility_percentile
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
            momentum_30s_avg,
            volatility_value,
            volatility_percentile
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

async def log_symbol_price(symbol: str):
    """Log price data for the specified symbol"""
    global last_logged_second
    
    last_logged_second = None
    symbol_config = SYMBOL_CONFIG[symbol]
    
    # Pre-load momentum and volatility profiles for this symbol
    print(f"🔄 Pre-loading momentum profile for {symbol}...")
    load_momentum_profile(symbol)
    print(f"🔄 Pre-loading volatility profile for {symbol}...")
    load_volatility_profile(symbol)
    
    while True:
        try:
            async with websockets.connect(symbol_config['api_endpoint']) as websocket:
                subscribe_message = {
                    "type": "subscribe",
                    "channels": [{"name": "ticker", "product_ids": [symbol_config['product_id']]}]
                }
                await websocket.send(json.dumps(subscribe_message))

                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=10)
                        data = json.loads(message)

                        if data.get("type") != "ticker" or "price" not in data:
                            continue

                        price = float(data["price"])
                        now = datetime.now(ZoneInfo("America/New_York"))
                        now = now.replace(microsecond=0)

                        current_second = int(now.timestamp())
                        if last_logged_second == current_second:
                            continue
                        last_logged_second = current_second

                        rounded_timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
                        formatted_price = f"${price:,.2f}"

                        insert_tick(symbol, rounded_timestamp, price)

                        # Ensure the directory exists before writing to the heartbeat file
                        heartbeat_path = os.path.join(get_btc_price_history_dir(), symbol_config['heartbeat_file'])
                        os.makedirs(os.path.dirname(heartbeat_path), exist_ok=True)
                        with open(heartbeat_path, "w") as hb:
                            hb.write(f"{rounded_timestamp} {symbol} logger alive (PostgreSQL)\n")

                    except asyncio.TimeoutError:
                        print("⚠️ WebSocket timeout. Reconnecting...")
                        break
        except Exception as e:
            print("⚠️ Logger encountered an error:", e)
            import traceback
            traceback.print_exc()
            await asyncio.sleep(5)

async def poll_kraken_price_changes(symbol: str):
    """Poll Kraken for price changes (supports BTC and ETH)"""
    while True:
        try:
            # Configure Kraken API endpoints for different symbols
            if symbol == 'BTC':
                url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=60"
            elif symbol == 'ETH':
                url = "https://api.kraken.com/0/public/OHLC?pair=ETHUSD&interval=60"
            else:
                # Skip for unsupported symbols
                await asyncio.sleep(60)
                continue
                
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        json_data = await resp.json()
                        result = json_data.get("result", {})
                        pair_key = next((key for key in result.keys() if key != "last"), None)
                        if pair_key and pair_key in result:
                            data = result[pair_key]
                            if len(data) >= 25:
                                close_now = float(data[-1][4])
                                close_1h = float(data[-2][4])
                                close_3h = float(data[-4][4])
                                close_1d = float(data[-25][4])
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
                                        table_name = f"price_change_{symbol.lower()}"
                                        cursor.execute(f"""
                                            INSERT INTO live_data.{table_name} 
                                            (change1h, change3h, change1d, timestamp)
                                            VALUES (%s, %s, %s, %s)
                                        """, (changes["change1h"], changes["change3h"], changes["change1d"], changes["timestamp"]))
                                        conn.commit()
                                        cursor.close()
                                        conn.close()
                                    except Exception as e:
                                        print(f"[Database Error for {symbol}]", e)
                                        if conn:
                                            conn.close()
        except Exception as e:
            print(f"[Kraken Poll Error for {symbol}]", e)
        await asyncio.sleep(60)

def handle_yahoo_finance_symbol(symbol: str):
    """Handle Yahoo Finance symbols (SPX, NDX, etc.) synchronously"""
    symbol_config = SYMBOL_CONFIG[symbol]
    last_logged_second = None
    
    # Pre-load momentum and volatility profiles for this symbol
    print(f"🔄 Pre-loading momentum profile for {symbol}...")
    load_momentum_profile(symbol)
    print(f"🔄 Pre-loading volatility profile for {symbol}...")
    load_volatility_profile(symbol)
    
    def on_new_msg(ws, msg):
        """Handle incoming Yahoo Finance ticker messages"""
        nonlocal last_logged_second
        try:
            # Parse the Yahoo Finance message
            price = None
            if isinstance(msg, dict):
                # Try different possible price field names
                for price_field in ['price', 'regularMarketPrice', 'last', 'lastPrice', 'close']:
                    if price_field in msg and msg[price_field] is not None:
                        price = float(msg[price_field])
                        break
            
            if price is None:
                return
            
            now = datetime.now(ZoneInfo("America/New_York"))
            now = now.replace(microsecond=0)
            
            current_second = int(now.timestamp())
            if last_logged_second == current_second:
                return
            last_logged_second = current_second
            
            rounded_timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
            
            # Insert the tick data
            insert_tick(symbol, rounded_timestamp, price)
            
            # Update heartbeat file
            heartbeat_path = os.path.join(get_btc_price_history_dir(), symbol_config['heartbeat_file'])
            os.makedirs(os.path.dirname(heartbeat_path), exist_ok=True)
            with open(heartbeat_path, "w") as hb:
                hb.write(f"{rounded_timestamp} {symbol} logger alive (PostgreSQL)\n")
                
        except Exception as e:
            print(f"⚠️ Error processing Yahoo Finance message: {e}")
            import traceback
            traceback.print_exc()
    
    try:
        print(f"🚀 Starting Yahoo Finance watchdog for {symbol} ({symbol_config['yahoo_symbol']})")
        
        # Create and start the Yahoo Finance live ticker
        ticker = yliveticker.YLiveTicker(
            on_ticker=on_new_msg,
            ticker_names=[symbol_config['yahoo_symbol']]
        )
        
        # Keep the main thread alive
        while True:
            import time
            time.sleep(1)
            
    except KeyboardInterrupt:
        print(f"\n🛑 Stopping {symbol} watchdog...")
        if ticker:
            ticker.close()
    except Exception as e:
        print(f"❌ Yahoo Finance watchdog error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    parser = argparse.ArgumentParser(description='Symbol Price Watchdog')
    parser.add_argument('symbol', help='Symbol to monitor (e.g., BTC, ETH, SPX)')
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    
    if symbol not in SYMBOL_CONFIG:
        print(f"❌ Unsupported symbol: {symbol}")
        print(f"Supported symbols: {list(SYMBOL_CONFIG.keys())}")
        return
    
    config = SYMBOL_CONFIG[symbol]
    method = config.get('method', 'coinbase')  # Default to coinbase for backward compatibility
    
    print(f"Starting {symbol} Price Watchdog (PostgreSQL) using {method}")
    
    if method == 'yahoo_finance':
        # Yahoo Finance symbols (SPX, NDX, etc.) - run synchronously
        handle_yahoo_finance_symbol(symbol)
    else:
        # Coinbase symbols (BTC, ETH) - run async
        await asyncio.gather(
            log_symbol_price(symbol),
            poll_kraken_price_changes(symbol)
        )

if __name__ == "__main__":
    asyncio.run(main()) 