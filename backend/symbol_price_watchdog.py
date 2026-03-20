import asyncio
import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
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
import logging

# Add the project root to the Python path (permanent scalable fix)
from backend.util.paths import get_project_root
if get_project_root() not in sys.path:
    sys.path.insert(0, get_project_root())

# Now import everything else
from backend.core.config.settings import config
from backend.core.port_config import get_port
from backend.util.paths import get_btc_price_history_dir, ensure_data_dirs

# Ensure all data directories exist
ensure_data_dirs()

# Logging: EST timestamps, single handler to stdout, flush after each line (real-time visibility)
def _est_formatter():
    class ESTFormatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            if datefmt:
                return dt.strftime(datefmt)
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return ESTFormatter(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _FlushingStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_logging():
    log = logging.getLogger("symbol_price_watchdog")
    if log.handlers:
        return log
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_est_formatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()

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

# Global movement profile cache (percentile -> movement_value)
MOVEMENT_PROFILES = {}

def update_prev_day_avg_for_symbol(symbol: str, cursor, table_name: str, yesterday_start: str, yesterday_end: str):
    """
    Compute previous calendar day's average momentum/volatility/movement percentiles from this symbol's
    live price log (per-minute resample then daily avg) and UPDATE live_symbol_status.
    Uses the same connection/cursor as the caller (e.g. insert_tick).
    """
    cursor.execute("""
        WITH per_minute AS (
            SELECT
                DATE_TRUNC(%s, timestamp::timestamp) AS minute,
                AVG(momentum_percentile)   AS mom_pct,
                AVG(volatility_percentile) AS vol_pct,
                AVG(movement_percentile)   AS mov_pct
            FROM live_data.""" + table_name + """
            WHERE timestamp >= %s AND timestamp < %s
            GROUP BY DATE_TRUNC(%s, timestamp::timestamp)
        )
        SELECT AVG(mom_pct), AVG(vol_pct), AVG(mov_pct) FROM per_minute
    """, ('minute', yesterday_start, yesterday_end, 'minute'))
    row = cursor.fetchone()
    if row and (row[0] is not None or row[1] is not None or row[2] is not None):
        daily_update_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%dT%H:%M:%S")
        cursor.execute("""
            UPDATE live_data.live_symbol_status SET
                prev_day_avg_momentum_percentile = %s,
                prev_day_avg_volatility_percentile = %s,
                prev_day_avg_movement_percentile = %s,
                daily_update = %s
            WHERE symbol = %s
        """, (row[0], row[1], row[2], daily_update_str, symbol))
        mom = f"{row[0]:.1f}" if row[0] is not None else "NULL"
        vol = f"{row[1]:.1f}" if row[1] is not None else "NULL"
        mov = f"{row[2]:.1f}" if row[2] is not None else "NULL"
        logger.debug("%s prev_day_avg updated: momentum=%s volatility=%s movement=%s", symbol, mom, vol, mov)

def _run_daily_prev_day_avg_0005(symbol: str):
    """Background thread: run prev_day_avg update every day at 00:05 EST. No dependency on ticks."""
    table_name = SYMBOL_CONFIG[symbol]["table_name"]
    logger.debug("[%s] Daily prev_day_avg thread started, waiting for 00:05 EST", symbol)
    while True:
        now = datetime.now(ZoneInfo("America/New_York"))
        target = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        time.sleep(wait_seconds)
        now_after_sleep = datetime.now(ZoneInfo("America/New_York"))
        logger.debug("[%s] Running daily prev_day_avg at %s EST", symbol, now_after_sleep.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            conn = get_postgres_connection()
            if not conn:
                logger.warning("[%s] Failed to get DB connection for prev_day_avg", symbol)
                continue
            cursor = conn.cursor()
            today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            today_dt = datetime.strptime(today_str, "%Y-%m-%d")
            yesterday_dt = today_dt - timedelta(days=1)
            yesterday_start = yesterday_dt.strftime("%Y-%m-%d") + "T00:00:00"
            yesterday_end = today_str + "T00:00:00"
            logger.debug("[%s] Computing prev_day_avg for %s to %s", symbol, yesterday_start, yesterday_end)
            update_prev_day_avg_for_symbol(symbol, cursor, table_name, yesterday_start, yesterday_end)
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.warning("[%s] daily prev_day_avg (00:05) failed: %s", symbol, e, exc_info=True)

def load_movement_profile(symbol: str) -> Dict[float, float]:
    """Load movement profile from database and cache (same pattern as momentum)."""
    if symbol in MOVEMENT_PROFILES:
        return MOVEMENT_PROFILES[symbol]
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'analytics' AND table_name LIKE %s
            ORDER BY table_name DESC
        """, (f"{symbol.lower()}_movement_profile_%",))
        results = cursor.fetchall()
        if not results:
            profile_table = f"analytics.{symbol.lower()}_movement_profile"
        else:
            profile_table = f"analytics.{results[0][0]}"
        cursor.execute(f"SELECT percentile, movement_value FROM {profile_table} ORDER BY percentile")
        profile = {float(row[0]): float(row[1]) for row in cursor.fetchall()}
        conn.close()
        MOVEMENT_PROFILES[symbol] = profile
        return profile
    except Exception as e:
        logger.warning("Load movement profile for %s: %s", symbol, e)
        return {}

def calculate_movement_percentile(symbol: str, movement_value: float) -> Optional[float]:
    """Interpolated percentile for movement value using cached movement profile."""
    if movement_value is None:
        return None
    profile = MOVEMENT_PROFILES.get(symbol) or load_movement_profile(symbol)
    if not profile:
        return None
    percentiles = sorted(profile.keys())
    values = [profile[p] for p in percentiles]
    if movement_value <= values[0]:
        return percentiles[0]
    if movement_value >= values[-1]:
        return percentiles[-1]
    for i in range(len(values) - 1):
        if values[i] <= movement_value <= values[i + 1]:
            p1, p2 = percentiles[i], percentiles[i + 1]
            v1, v2 = values[i], values[i + 1]
            if v2 == v1:
                return p1
            return round(p1 + (p2 - p1) * (movement_value - v1) / (v2 - v1), 1)
    closest = min(profile.keys(), key=lambda p: abs(profile[p] - movement_value))
    return closest

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
            profile_table = f"analytics.{symbol.lower()}_momentum_profile"
            logger.debug("No dated momentum profile for %s, using base table", symbol)
        else:
            profile_table = f"analytics.{results[0][0]}"
            logger.debug("Using momentum profile: %s", results[0][0])
        cursor.execute(f"SELECT percentile, momentum_value FROM {profile_table} ORDER BY percentile")
        profile = {}
        for row in cursor.fetchall():
            profile[float(row[0])] = float(row[1])
        conn.close()
        MOMENTUM_PROFILES[symbol] = profile
        logger.debug("Loaded momentum profile for %s: %s percentiles", symbol, len(profile))
        return profile
    except Exception as e:
        logger.error("Error loading momentum profile for %s: %s", symbol, e)
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
            logger.debug("No dated volatility profile for %s", symbol)
            conn.close()
            return {}
        profile_table = f"analytics.{results[0][0]}"
        logger.debug("Using volatility profile: %s", results[0][0])
        cursor.execute(f"SELECT percentile, volatility_value FROM {profile_table} ORDER BY percentile")
        profile = {}
        for row in cursor.fetchall():
            profile[float(row[0])] = float(row[1])
        conn.close()
        VOLATILITY_PROFILES[symbol] = profile
        logger.debug("Loaded volatility profile for %s: %s percentiles", symbol, len(profile))
        return profile
    except Exception as e:
        logger.error("Error loading volatility profile for %s: %s", symbol, e)
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
        logger.warning("Error calculating 1m average price: %s", e)
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
        logger.warning("Error getting current price: %s", e)
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
        logger.warning("Failed to calculate momentum data: %s", e)
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
        logger.warning("Error getting price at %sm offset: %s", minutes_ago, e)
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
        logger.warning("Error getting current price: %s", e)
        return None

def get_high_low_open_for_window(symbol: str, minutes_ago: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (high, low, open) for the last N minutes from live table. Open = price at window start (oldest tick)."""
    try:
        conn = get_postgres_connection()
        cursor = conn.cursor()
        est_tz = ZoneInfo("America/New_York")
        now_est = datetime.now(est_tz)
        cutoff = (now_est - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S")
        table_name = SYMBOL_CONFIG[symbol]["table_name"]
        cursor.execute(f"""
            SELECT MIN(price) AS low, MAX(price) AS high,
                   (array_agg(price ORDER BY timestamp ASC))[1] AS open_price
            FROM live_data.{table_name}
            WHERE timestamp >= %s
        """, (cutoff,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None and row[1] is not None and row[2] is not None:
            return (float(row[1]), float(row[0]), float(row[2]))
        return (None, None, None)
    except Exception as e:
        logger.warning("get_high_low_open_for_window(%s, %sm): %s", symbol, minutes_ago, e)
        return (None, None, None)

def calculate_move_for_window(symbol: str, minutes: int) -> Optional[float]:
    """Raw movement for window: (high - low) / open * 100. Returns None if insufficient data or open is 0."""
    high, low, open_price = get_high_low_open_for_window(symbol, minutes)
    if high is None or low is None or open_price is None or open_price == 0:
        return None
    return (high - low) / open_price * 100.0

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

# Movement windows and weights (mirror momentum: 1m, 2m, 3m, 4m, 15m, 30m)
MOVEMENT_WINDOWS = [1, 2, 3, 4, 15, 30]
MOVEMENT_WEIGHTS = {1: 0.3, 2: 0.25, 3: 0.2, 4: 0.15, 15: 0.05, 30: 0.05}

def get_movement_data(symbol: str) -> Dict[str, Any]:
    """Compute move_1m..move_30m from tick high/low/open, weighted movement, and movement_percentile."""
    moves = {}
    for m in MOVEMENT_WINDOWS:
        moves[f"move_{m}m"] = calculate_move_for_window(symbol, m)
    weighted_sum = 0.0
    total_weight = 0.0
    for m in MOVEMENT_WINDOWS:
        w = MOVEMENT_WEIGHTS[m]
        v = moves[f"move_{m}m"]
        if v is not None:
            weighted_sum += v * w
            total_weight += w
    movement = (weighted_sum / total_weight) if total_weight > 0 else None
    movement_percentile = calculate_movement_percentile(symbol, movement) if movement is not None else None
    return {
        "move_1m": moves["move_1m"],
        "move_2m": moves["move_2m"],
        "move_3m": moves["move_3m"],
        "move_4m": moves["move_4m"],
        "move_15m": moves["move_15m"],
        "move_30m": moves["move_30m"],
        "movement": movement,
        "movement_percentile": movement_percentile,
    }

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
        logger.debug("5s momentum average calculation failed: %s", e)
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
        logger.debug("30s momentum average calculation failed: %s", e)
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

def get_minute_candles_for_volatility(symbol: str, lookback_minutes: int = 60) -> list:
    """
    Get 1-minute OHLC candles from the last lookback_minutes using separate connection.
    Returns list of dicts with keys: open, high, low, close (oldest first).
    """
    try:
        conn = get_postgres_connection()
        if not conn:
            return []
        cursor = conn.cursor()
        
        # Get current time in EST
        now = datetime.now(ZoneInfo("America/New_York"))
        cutoff_time = now - timedelta(minutes=lookback_minutes)
        cutoff_str = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
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
        logger.debug("Error getting minute candles for volatility: %s", e)
        return []

def calculate_native_volatility(symbol: str = 'BTC') -> Optional[float]:
    """
    Calculate weighted multi-timeframe volatility using True Range (ATR-based approach).
    Matches the calculation method in volatility_generator_pg.py.
    After a feed gap we may have fewer than 59 candles in the last 60 minutes; try
    longer lookbacks (90, 120 min) so volatility recovers instead of staying NULL for hours.
    """
    try:
        # Get candles: try 60 min, then 90, then 120 so we recover after gaps
        candles = get_minute_candles_for_volatility(symbol, 60)
        if len(candles) < 59:
            candles = get_minute_candles_for_volatility(symbol, 90)
        if len(candles) < 59:
            candles = get_minute_candles_for_volatility(symbol, 120)
        
        if len(candles) < 59:  # Still not enough (e.g. very long outage)
            return None
        
        # Use only the most recent 60 candles so volatility = "last 60 minutes"
        candles = candles[-60:]
        
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
        logger.debug("Error calculating volatility: %s", e)
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
                logger.debug("Volatility percentile calculation failed for %s: %s", symbol, e)
                volatility_percentile = None
    except Exception as e:
        logger.debug("Volatility calculation failed for %s: %s", symbol, e)
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
            logger.debug("1m average calculation failed (no historical data yet): %s", e)
            one_minute_avg = price  # Use current price as fallback

        try:
            momentum_data = get_momentum_data(symbol)
        except Exception as e:
            logger.debug("Momentum calculation failed (no historical data yet): %s", e)
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
                logger.debug("Momentum percentile calculation failed: %s", e)
        momentum_5s_avg = None
        try:
            momentum_5s_avg = calculate_5s_momentum_average(symbol)
        except Exception as e:
            logger.debug("5s momentum average calculation failed: %s", e)
        momentum_30s_avg = None
        try:
            momentum_30s_avg = calculate_30s_momentum_average(symbol)
        except Exception as e:
            logger.debug("30s momentum average calculation failed: %s", e)
        
        # Get volatility for current minute (calculated synchronously on first tick of minute)
        minute_key = timestamp[:16]  # Extract minute key (YYYY-MM-DDTHH:MM)
        volatility_value, volatility_percentile = get_volatility_for_minute(symbol, minute_key)
        
        # Get movement data (move_1m..move_30m, movement, movement_percentile)
        try:
            movement_data = get_movement_data(symbol)
        except Exception as e:
            logger.debug("Movement calculation failed: %s", e)
            movement_data = {
                "move_1m": None, "move_2m": None, "move_3m": None, "move_4m": None,
                "move_15m": None, "move_30m": None, "movement": None, "movement_percentile": None,
            }
        
        table_name = SYMBOL_CONFIG[symbol]['table_name']
        
        # Insert the data with all columns including momentum, volatility, and movement
        cursor.execute(f'''
            INSERT INTO live_data.{table_name} 
            (timestamp, price, one_minute_avg, momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg, momentum_30s_avg, volatility, volatility_percentile, move_1m, move_2m, move_3m, move_4m, move_15m, move_30m, movement, movement_percentile) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                volatility_percentile = EXCLUDED.volatility_percentile,
                move_1m = EXCLUDED.move_1m,
                move_2m = EXCLUDED.move_2m,
                move_3m = EXCLUDED.move_3m,
                move_4m = EXCLUDED.move_4m,
                move_15m = EXCLUDED.move_15m,
                move_30m = EXCLUDED.move_30m,
                movement = EXCLUDED.movement,
                movement_percentile = EXCLUDED.movement_percentile
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
            volatility_percentile,
            movement_data.get('move_1m'),
            movement_data.get('move_2m'),
            movement_data.get('move_3m'),
            movement_data.get('move_4m'),
            movement_data.get('move_15m'),
            movement_data.get('move_30m'),
            movement_data.get('movement'),
            movement_data.get('movement_percentile'),
        ))
        
        # Dual write to live_symbol_status is now trigger-driven for BTC/ETH.
        # For other symbols (SPX/NDX), we keep the Python-side dual-write behavior.
        if symbol not in ("BTC", "ETH"):
            tick_values = (
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
                volatility_percentile,
                movement_data.get('move_1m'),
                movement_data.get('move_2m'),
                movement_data.get('move_3m'),
                movement_data.get('move_4m'),
                movement_data.get('move_15m'),
                movement_data.get('move_30m'),
                movement_data.get('movement'),
                movement_data.get('movement_percentile'),
            )
            cursor.execute("""
                UPDATE live_data.live_symbol_status SET
                    "timestamp" = %s,
                    price = %s,
                    one_minute_avg = %s,
                    momentum = %s,
                    delta_1m = %s,
                    delta_2m = %s,
                    delta_3m = %s,
                    delta_4m = %s,
                    delta_15m = %s,
                    delta_30m = %s,
                    momentum_percentile = %s,
                    momentum_5s_avg = %s,
                    volatility = %s,
                    volatility_percentile = %s,
                    momentum_30s_avg = %s,
                    move_1m = %s,
                    move_2m = %s,
                    move_3m = %s,
                    move_4m = %s,
                    move_15m = %s,
                    move_30m = %s,
                    movement = %s,
                    movement_percentile = %s
                WHERE symbol = %s
            """, tick_values + (symbol,))
            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO live_data.live_symbol_status
                    (symbol, "timestamp", price, one_minute_avg, momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg, volatility, volatility_percentile, momentum_30s_avg, move_1m, move_2m, move_3m, move_4m, move_15m, move_30m, movement, movement_percentile)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (symbol,) + tick_values)
        
        # ROLLING WINDOW: Clean up data older than 30 days
        dt = datetime.now(ZoneInfo("America/New_York")).replace(microsecond=0)
        cutoff_time = dt - timedelta(days=30)
        cutoff_iso = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")
        cursor.execute(f"DELETE FROM live_data.{table_name} WHERE timestamp < %s", (cutoff_iso,))
        
        conn.commit()
        logger.debug("%s price logged: $%s at %s", symbol, f"{price:,.2f}", timestamp)
    except Exception as e:
        logger.error("Logger encountered an error: %s", e, exc_info=True)
        conn.rollback()
        raise
    finally:
        conn.close()

HEARTBEAT_INTERVAL_SEC = 300  # 5 min internal heartbeat to stdout

async def log_symbol_price(symbol: str):
    """Log price data for the specified symbol"""
    global last_logged_second

    last_logged_second = None
    last_heartbeat = time.time()
    symbol_config = SYMBOL_CONFIG[symbol]

    # Pre-load momentum, volatility, and movement profiles for this symbol
    logger.debug("Pre-loading momentum profile for %s", symbol)
    load_momentum_profile(symbol)
    logger.debug("Pre-loading volatility profile for %s", symbol)
    load_volatility_profile(symbol)
    logger.debug("Pre-loading movement profile for %s", symbol)
    load_movement_profile(symbol)

    while True:
        try:
            async with websockets.connect(symbol_config['api_endpoint']) as websocket:
                subscribe_message = {
                    "type": "subscribe",
                    "channels": [
                        {"name": "ticker", "product_ids": [symbol_config['product_id']]},
                        {"name": "heartbeat", "product_ids": [symbol_config['product_id']]}
                    ]
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
                        insert_tick(symbol, rounded_timestamp, price)

                        if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                            logger.info("heartbeat")
                            last_heartbeat = time.time()

                    except asyncio.TimeoutError:
                        logger.warning("[%s] WebSocket timeout, reconnecting", symbol)
                        break
                    except (ConnectionClosedError, ConnectionClosedOK) as e:
                        logger.warning("[%s] WebSocket connection closed: %s. Reconnecting.", symbol, e)
                        break
                    except Exception as e:
                        logger.error("[%s] Unexpected WebSocket error: %s. Reconnecting.", symbol, e, exc_info=True)
                        break
        except Exception as e:
            logger.error("Logger encountered an error: %s", e, exc_info=True)
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
                                        logger.warning("Database error for %s: %s", symbol, e)
                                        if conn:
                                            conn.close()
        except Exception as e:
            logger.warning("Kraken poll error for %s: %s", symbol, e)
        await asyncio.sleep(60)

def handle_yahoo_finance_symbol(symbol: str):
    """Handle Yahoo Finance symbols (SPX, NDX, etc.) synchronously"""
    symbol_config = SYMBOL_CONFIG[symbol]
    last_logged_second = None
    last_heartbeat = [time.time()]  # use list so on_new_msg can update

    logger.debug("Pre-loading momentum profile for %s", symbol)
    load_momentum_profile(symbol)
    logger.debug("Pre-loading volatility profile for %s", symbol)
    load_volatility_profile(symbol)
    logger.debug("Pre-loading movement profile for %s", symbol)
    load_movement_profile(symbol)

    def on_new_msg(ws, msg):
        nonlocal last_logged_second
        try:
            price = None
            if isinstance(msg, dict):
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
            insert_tick(symbol, rounded_timestamp, price)
            if time.time() - last_heartbeat[0] >= HEARTBEAT_INTERVAL_SEC:
                logger.info("heartbeat")
                last_heartbeat[0] = time.time()
        except Exception as e:
            logger.warning("Error processing Yahoo Finance message: %s", e, exc_info=True)

    ticker = None
    try:
        logger.debug("Starting Yahoo Finance watchdog for %s (%s)", symbol, symbol_config['yahoo_symbol'])
        ticker = yliveticker.YLiveTicker(
            on_ticker=on_new_msg,
            ticker_names=[symbol_config['yahoo_symbol']]
        )
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.debug("Stopping %s watchdog", symbol)
        if ticker:
            ticker.close()
    except Exception as e:
        logger.error("Yahoo Finance watchdog error: %s", e, exc_info=True)

async def main():
    parser = argparse.ArgumentParser(description='Symbol Price Watchdog')
    parser.add_argument('symbol', help='Symbol to monitor (e.g., BTC, ETH, SPX)')
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    
    if symbol not in SYMBOL_CONFIG:
        logger.error("Unsupported symbol: %s (supported: %s)", symbol, list(SYMBOL_CONFIG.keys()))
        return
    config = SYMBOL_CONFIG[symbol]
    method = config.get('method', 'coinbase')
    logger.debug("Starting %s Price Watchdog (PostgreSQL) using %s", symbol, method)
    t = threading.Thread(target=_run_daily_prev_day_avg_0005, args=(symbol,), daemon=True)
    t.start()
    
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