#!/usr/bin/env python3
"""
STRIKE TABLE GENERATOR - POSTGRESQL VERSION (MULTI-SYMBOL)
Generates strike table data using lookup table for probabilities and writes to PostgreSQL.

This system replaces the JSON-based strike table generation with PostgreSQL tables
in the live_data schema for better performance and data consistency.
Supports multiple symbols (BTC, ETH, etc.) via command line parameter.
"""

import os
import sys
import psycopg2
import json
import logging
import argparse
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config.config_manager import config
from backend.util.paths import get_data_dir, get_kalshi_data_dir

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# PostgreSQL connection parameters
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
    'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
    'password': os.getenv('POSTGRES_PASSWORD', '')
        }

class LookupProbabilityCalculator:
    """Probability calculator using the lookup table instead of live interpolation."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.db_config = POSTGRES_CONFIG
        self.lookup_table_name = self._find_latest_lookup_table()
        self.max_buffer = self._get_max_buffer_for_symbol()
    
    def _find_latest_lookup_table(self) -> str:
        """Find the most recent master lookup table for this symbol."""
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Query to find all lookup tables for this symbol
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name LIKE %s
                ORDER BY table_name DESC
            """, (f"probability_lookup_{self.symbol}_master_%",))
            
            results = cursor.fetchall()
            if not results:
                raise ValueError(f"No lookup tables found for symbol {self.symbol.upper()}")
            
            # Get the most recent table (highest date string)
            latest_table = results[0][0]
            logger.info(f"📊 Using lookup table: {latest_table}")
            return latest_table
            
        except Exception as e:
            logger.error(f"❌ Error finding lookup table for {self.symbol.upper()}: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def _get_max_buffer_for_symbol(self) -> float:
        """Get the maximum buffer value for this symbol's lookup table."""
        conn = None
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            cursor.execute(f"""
                SELECT MAX(buffer_points) as max_buffer
                FROM analytics.{self.lookup_table_name}
            """)
            
            result = cursor.fetchone()
            if not result or not result[0]:
                raise ValueError(f"No buffer data found in lookup table {self.lookup_table_name}")
            
            return float(result[0])
            
        except Exception as e:
            logger.error(f"Error getting max buffer for {self.symbol.upper()}: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def get_probability(self, ttc_seconds: int, buffer_points: int, momentum_bucket: int, conn=None) -> tuple[float, float]:
        """
        Get probability values from lookup table with bilinear interpolation.
        
        Args:
            ttc_seconds: Time to close in seconds
            buffer_points: Buffer distance in points
            momentum_bucket: Momentum bucket (-30 to +30)
            
        Returns:
            Tuple of (positive_probability, negative_probability) as prob_within values
        """
        # Round TTC to nearest 10-second increment to match lookup table granularity
        ttc_seconds = round(ttc_seconds / 10) * 10
        
        # Round momentum to nearest available bucket in lookup table
        # The lookup table has 10-point increments: -90, -80, -70, -60, -50, -40, -30, -20, -10, 10, 20, 30, 40, 50, 60, 70, 80, 90
        # Note: momentum=0 is not available, so it will round to -10 or 10
        available_buckets = [-90, -80, -70, -60, -50, -40, -30, -20, -10, 10, 20, 30, 40, 50, 60, 70, 80, 90]
        momentum_bucket = min(available_buckets, key=lambda x: abs(x - momentum_bucket))
        
        # Check if buffer is outside lookup table range for this symbol
        if buffer_points > self.max_buffer:
            logger.warning(f"Buffer {buffer_points} outside lookup table range (0-{self.max_buffer}), using max buffer as fallback")
            buffer_points = self.max_buffer
        
        use_external_conn = conn is not None
        if not use_external_conn:
            conn = None
        try:
            if not use_external_conn:
                conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Calculate dynamic buffer range based on symbol's buffer spacing
            # TTC spacing is always 5 seconds, buffer spacing varies by symbol
            buffer_range = max(5, self.max_buffer * 0.01)  # 1% of max_buffer, minimum 5
            
            # Find the 4 nearest points for bilinear interpolation
            query = f"""
            SELECT ttc_seconds, buffer_points, prob_within_positive, prob_within_negative
            FROM analytics.{self.lookup_table_name}
            WHERE momentum_bucket = %s
            AND ttc_seconds >= %s - 5 AND ttc_seconds <= %s + 5
            AND buffer_points >= %s - %s AND buffer_points <= %s + %s
            ORDER BY ABS(ttc_seconds - %s) + ABS(buffer_points - %s)
            LIMIT 4
            """
            
            cursor.execute(query, (
                momentum_bucket, ttc_seconds, ttc_seconds, 
                buffer_points, buffer_range, buffer_points, buffer_range, 
                ttc_seconds, buffer_points
            ))
            
            results = cursor.fetchall()
            
            # Convert Decimal types to float for all results
            results = [(float(r[0]), float(r[1]), float(r[2]), float(r[3])) for r in results]
            
            if len(results) == 0:
                logger.warning(f"No data found for TTC={ttc_seconds}, buffer={buffer_points}, momentum={momentum_bucket}")
                return None, None
            
            elif len(results) == 1:
                # Single point - return exact value
                return float(results[0][2]), float(results[0][3])
            
            elif len(results) == 2:
                # Linear interpolation between 2 points
                point1, point2 = results[0], results[1]
                ttc1, buffer1, pos1, neg1 = point1
                ttc2, buffer2, pos2, neg2 = point2
                
                # Calculate weights based on distance
                total_distance = abs(ttc2 - ttc1) + abs(buffer2 - buffer1)
                if total_distance == 0:
                    return float(pos1), float(neg1)
                
                weight1 = 1 - (abs(ttc_seconds - ttc1) + abs(buffer_points - buffer1)) / total_distance
                weight2 = 1 - weight1
                
                pos_interp = weight1 * float(pos1) + weight2 * float(pos2)
                neg_interp = weight1 * float(neg1) + weight2 * float(neg2)
                
                return pos_interp, neg_interp
            
            elif len(results) == 3:
                # Handle 3 results by using linear interpolation with the closest 2 points
                # Sort by distance and take the 2 closest
                results_with_distance = []
                for r in results:
                    distance = abs(r[0] - ttc_seconds) + abs(r[1] - buffer_points)
                    results_with_distance.append((distance, r))
                
                results_with_distance.sort(key=lambda x: x[0])
                closest_two = [r[1] for r in results_with_distance[:2]]
                
                # Use linear interpolation with the 2 closest points
                point1, point2 = closest_two[0], closest_two[1]
                ttc1, buffer1, pos1, neg1 = point1
                ttc2, buffer2, pos2, neg2 = point2
                
                # Calculate weights based on distance
                total_distance = abs(ttc2 - ttc1) + abs(buffer2 - buffer1)
                if total_distance == 0:
                    return float(pos1), float(neg1)
                
                weight1 = 1 - (abs(ttc_seconds - ttc1) + abs(buffer_points - buffer1)) / total_distance
                weight2 = 1 - weight1
                
                pos_interp = weight1 * float(pos1) + weight2 * float(pos2)
                neg_interp = weight1 * float(neg1) + weight2 * float(neg2)
                
                return pos_interp, neg_interp
            
            elif len(results) >= 4:
                # Bilinear interpolation with 4 points
                return self._bilinear_interpolate(results, ttc_seconds, buffer_points)
            
            else:
                logger.error(f"Unexpected number of results: {len(results)}")
                raise ValueError(f"Unexpected number of lookup results: {len(results)}")
                
        except Exception as e:
            logger.error(f"Error in lookup probability calculation: {e}")
            raise
        finally:
            if conn and not use_external_conn:
                conn.close()
    
    
    def _bilinear_interpolate(self, results: List[Tuple], ttc_seconds: int, buffer_points: int) -> Tuple[float, float]:
        """Perform bilinear interpolation with 4 points."""
        try:
            # Sort results by TTC and buffer to find corners
            sorted_results = sorted(results, key=lambda x: (x[0], x[1]))
            
            # Find the 4 corner points
            ttc_values = sorted(set(r[0] for r in sorted_results))
            buffer_values = sorted(set(r[1] for r in sorted_results))
            
            if len(ttc_values) < 2 or len(buffer_values) < 2:
                # Fall back to linear interpolation
                return self._linear_interpolate(sorted_results, ttc_seconds, buffer_points)
            
            # Find the 4 corners
            ttc_lower, ttc_upper = ttc_values[0], ttc_values[-1]
            buffer_lower, buffer_upper = buffer_values[0], buffer_values[-1]
            
            # Get the 4 corner values
            corners = {}
            for ttc in [ttc_lower, ttc_upper]:
                for buffer in [buffer_lower, buffer_upper]:
                    for result in sorted_results:
                        if result[0] == ttc and result[1] == buffer:
                            corners[(ttc, buffer)] = (float(result[2]), float(result[3]))
                            break
            
            if len(corners) != 4:
                # Fall back to linear interpolation if we don't have all 4 corners
                return self._linear_interpolate(sorted_results, ttc_seconds, buffer_points)
            
            # Perform bilinear interpolation
            pos_interp = self._interpolate_2d(
                float(corners[(ttc_lower, buffer_lower)][0]), float(corners[(ttc_upper, buffer_lower)][0]),
                float(corners[(ttc_lower, buffer_upper)][0]), float(corners[(ttc_upper, buffer_upper)][0]),
                int(ttc_lower), int(ttc_upper), int(buffer_lower), int(buffer_upper),
                ttc_seconds, buffer_points
            )
            
            neg_interp = self._interpolate_2d(
                float(corners[(ttc_lower, buffer_lower)][1]), float(corners[(ttc_upper, buffer_lower)][1]),
                float(corners[(ttc_lower, buffer_upper)][1]), float(corners[(ttc_upper, buffer_upper)][1]),
                int(ttc_lower), int(ttc_upper), int(buffer_lower), int(buffer_upper),
                ttc_seconds, buffer_points
            )
            
            return pos_interp, neg_interp
            
        except Exception as e:
            logger.error(f"Error in bilinear interpolation: {e}")
            return 50.0, 50.0
    
    def _interpolate_2d(self, q11: float, q21: float, q12: float, q22: float,
                       x1: int, x2: int, y1: int, y2: int,
                       x: int, y: int) -> float:
        """Perform 2D bilinear interpolation."""
        if x2 == x1 or y2 == y1:
            return q11
        
        # Bilinear interpolation formula
        f1 = q11 * (x2 - x) * (y2 - y) / ((x2 - x1) * (y2 - y1))
        f2 = q21 * (x - x1) * (y2 - y) / ((x2 - x1) * (y2 - y1))
        f3 = q12 * (x2 - x) * (y - y1) / ((x2 - x1) * (y2 - y1))
        f4 = q22 * (x - x1) * (y - y1) / ((x2 - x1) * (y2 - y1))
        
        return f1 + f2 + f3 + f4
    
    def _linear_interpolate(self, results: List[Tuple], ttc_seconds: int, buffer_points: int) -> Tuple[float, float]:
        """Fallback to linear interpolation."""
        if len(results) < 2:
            return float(results[0][2]), float(results[0][3])
        
        # Find closest two points
        distances = []
        for result in results:
            distance = abs(result[0] - ttc_seconds) + abs(result[1] - buffer_points)
            distances.append((distance, result))
        
        distances.sort()
        closest = distances[0][1]
        second_closest = distances[1][1]
        
        # Linear interpolation
        total_distance = distances[0][0] + distances[1][0]
        if total_distance == 0:
            return float(closest[2]), float(closest[3])
        
        weight1 = 1 - distances[0][0] / total_distance
        weight2 = 1 - weight1
        
        pos_interp = weight1 * float(closest[2]) + weight2 * float(second_closest[2])
        neg_interp = weight1 * float(closest[3]) + weight2 * float(second_closest[3])
        
        return pos_interp, neg_interp

class StrikeTableGenerator:
    """Generates strike table data and writes to PostgreSQL live_data schema."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.db_config = POSTGRES_CONFIG
        logger.info(f"🔧 Initializing strike table generator for {symbol.upper()}")
        self.calculator = LookupProbabilityCalculator(symbol)
        logger.info(f"✅ Strike table generator initialized for {symbol.upper()}")
    
    def generate_market_title(self, event_ticker: str) -> str:
        """
        Generate a human-readable market title from event ticker.
        
        Args:
            event_ticker: Event ticker like 'KXBTCD-25AUG1515'
            
        Returns:
            Formatted title like 'BTC price today at 3pm'
        """
        if not event_ticker:
            return f"{self.symbol.upper()} price today"
        
        try:
            # Parse event ticker format: KXBTCD-25AUG1515
            # KXBTCD = Kalshi Bitcoin Daily
            # 25AUG15 = August 15, 2025 at 15:00 (3pm)
            
            # Extract date and time from the end
            parts = event_ticker.split('-')
            if len(parts) < 2:
                return f"{self.symbol.upper()} price today"
            
            date_time_part = parts[-1]  # 25AUG1515
            
            # Extract date (25AUG15) and hour (15)
            if len(date_time_part) >= 7:
                date_part = date_time_part[:-2]  # 25AUG15
                hour_part = date_time_part[-2:]  # 15
                
                # Parse date
                day = date_part[:2]  # 25
                month = date_part[2:5]  # AUG
                year = date_part[5:]  # 15
                
                # Convert to 24-hour format and then to 12-hour format
                hour_24 = int(hour_part)
                if hour_24 == 0:
                    time_str = "12am"
                elif hour_24 < 12:
                    time_str = f"{hour_24}am"
                elif hour_24 == 12:
                    time_str = "12pm"
                else:
                    time_str = f"{hour_24 - 12}pm"
                
                # Check if it's today
                today = datetime.now()
                event_date = datetime.strptime(f"{day}{month}20{year}", "%d%b%Y")
                
                if event_date.date() == today.date():
                    return f"{self.symbol.upper()} price today at {time_str}"
                else:
                    # Format date like "Aug 15"
                    month_name = event_date.strftime("%b")
                    return f"{self.symbol.upper()} price on {month_name} {day} at {time_str}"
            
            return f"{self.symbol.upper()} price today"
            
        except Exception as e:
            logger.error(f"Error parsing event ticker {event_ticker}: {e}")
            return f"{self.symbol.upper()} price today"
        
    def setup_live_data_schema(self):
        """Create live_data schema and tables if they don't exist."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Create live_data schema
            cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data")
            
            # Create strike table data table
            strike_table_sql = f"""
            CREATE TABLE IF NOT EXISTS live_data.strike_table_{self.symbol.lower()} (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                symbol VARCHAR(10),
                current_price DECIMAL(10,2),
                ttc_seconds INTEGER,
                broker VARCHAR(20),
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike INTEGER,
                buffer DECIMAL(10,2),
                buffer_pct DECIMAL(5,2),
                probability DECIMAL(5,2),
                yes_ask DECIMAL(5,2),
                no_ask DECIMAL(5,2),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume INTEGER,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                momentum_percentile DECIMAL(5,1),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """
            cursor.execute(strike_table_sql)
            
            # Add missing momentum_weighted_score column if it doesn't exist
            try:
                cursor.execute(f"ALTER TABLE live_data.strike_table_{self.symbol.lower()} ADD COLUMN momentum_weighted_score DECIMAL(5,3);")
                conn.commit()  # Commit the ALTER TABLE before continuing
            except psycopg2.ProgrammingError:
                # Column already exists, ignore error
                conn.rollback()  # Rollback and continue
                pass
            
            # Create index for strike table
            strike_index_sql = f"""
                    CREATE INDEX IF NOT EXISTS idx_strike_table_{self.symbol.lower()}_lookup
        ON live_data.strike_table_{self.symbol.lower()} (timestamp, symbol, current_price)
            """
            cursor.execute(strike_index_sql)
            
            conn.commit()
            logger.info(f"✅ Live data schema and tables created for {self.symbol.upper()}")
            
        except Exception as e:
            logger.error(f"❌ Error setting up live data schema: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def get_current_market_data(self) -> Dict[str, Any]:
        """Get current market data from live_data.live_price_log_1s_{symbol} and Kalshi snapshot."""
        try:
            # Get current price and momentum from PostgreSQL
            logger.info(f"🔍 Connecting to database for {self.symbol.upper()} price data...")
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            cursor.execute(f"""
            SELECT price, momentum, momentum_percentile FROM live_data.live_price_log_1s_{self.symbol} 
            ORDER BY timestamp DESC 
            LIMIT 1
            """)
            
            result = cursor.fetchone()
            if not result:
                raise ValueError(f"No price data found in live_data.live_price_log_1s_{self.symbol}")
            
            current_price = float(result[0])
            momentum_score = float(result[1]) if result[1] is not None else 0.0
            momentum_percentile = float(result[2]) if result[2] is not None else 0.0
            
            conn.close()
            
            # Get market snapshot
            market_data = self.get_kalshi_market_snapshot()
            
            return {
                "current_price": current_price,
                "momentum_score": momentum_score,
                "momentum_percentile": momentum_percentile,
                "market_data": market_data
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting current market data: {e}")
            raise
    
    def get_kalshi_market_snapshot(self) -> Dict[str, Any]:
        """Get live Kalshi market snapshot from the market_kalshi_{symbol} database table"""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Get the latest event_ticker from the market_kalshi_{symbol} table
            cursor.execute(f"""
                SELECT event_ticker 
                FROM live_data.market_kalshi_{self.symbol} 
                ORDER BY updated_at DESC 
                LIMIT 1
            """)
            
            result = cursor.fetchone()
            if not result:
                raise ValueError(f"No event_ticker found in market_kalshi_{self.symbol} table")
            
            event_ticker = result[0]
            
            # Get all markets for this event_ticker
            cursor.execute(f"""
                SELECT market_ticker, strike, yes_bid, yes_ask, no_bid, no_ask, 
                       last_price, volume, volume_24h, open_interest, liquidity, updated_at
                FROM live_data.market_kalshi_{self.symbol} 
                WHERE event_ticker = %s
                ORDER BY updated_at DESC
            """, (event_ticker,))
            
            market_rows = cursor.fetchall()
            if not market_rows:
                raise ValueError(f"No markets found for event_ticker: {event_ticker}")
            
            # Convert database rows to market dictionary format
            markets = []
            for row in market_rows:
                market_ticker, strike, yes_bid, yes_ask, no_bid, no_ask, last_price, volume, volume_24h, open_interest, liquidity, updated_at = row
                
                # Convert strike from "$104,250" or "6,475.0099" format to float
                floor_strike = None
                if strike:
                    try:
                        # Handle both formats: with or without '$' prefix
                        clean_strike = strike.replace('$', '').replace(',', '')
                        floor_strike = float(clean_strike)
                    except ValueError:
                        continue
                
                market = {
                    "ticker": market_ticker,
                    "floor_strike": floor_strike,
                    "yes_bid": yes_bid,
                    "yes_ask": yes_ask,
                    "no_bid": no_bid,
                    "no_ask": no_ask,
                    "last_price": last_price,
                    "volume": volume,
                    "volume_24h": volume_24h,
                    "open_interest": open_interest,
                    "liquidity": liquidity,
                    "status": "active"  # Assume active status for database records
                }
                markets.append(market)
            
            # Detect strike tier spacing
            strike_tier = self.detect_strike_tier_spacing(markets)
            
            # For database records, we'll use the event_ticker as the title and estimate strike_date
            # The strike_date is typically the hour from the event_ticker
            event_title = f"{self.symbol.upper()} Price at {event_ticker}"
            
            # Extract date from event_ticker (e.g., KXBTCD-25AUG1515 -> 2025-08-15T15:00:00)
            try:
                # Parse event_ticker format: KXBTCD-25AUG1515
                # Extract year, month, day, hour
                parts = event_ticker.split('-')
                if len(parts) >= 2:
                    date_part = parts[1]  # 25AUG1515
                    year = "20" + date_part[:2]  # 25 -> 2025
                    month_str = date_part[2:5]  # AUG
                    day = date_part[5:7]  # 15
                    hour = date_part[7:9]  # 15
                    
                    # Convert month abbreviation to number
                    month_map = {
                        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
                        'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
                        'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
                    }
                    month = month_map.get(month_str, '01')
                    
                    strike_date = f"{year}-{month}-{day}T{hour}:00:00Z"
                else:
                    strike_date = "2025-08-15T15:00:00Z"  # Default fallback
            except Exception:
                strike_date = "2025-08-15T15:00:00Z"  # Default fallback
            
            conn.close()
            
            logger.info(f"📊 Loaded live market data from database - Event: {event_ticker}, Markets: {len(markets)}, Tier: ${strike_tier:,}")
            
            return {
                "event_ticker": event_ticker,
                "market_status": "active",
                "event_title": event_title,
                "strike_date": strike_date,
                "strike_tier": strike_tier,
                "markets": markets
            }
        except Exception as e:
            logger.error(f"❌ Error getting Kalshi market data from database: {e}")
            raise
    
    def detect_strike_tier_spacing(self, markets: List[Dict[str, Any]]) -> int:
        """Detect strike tier spacing from market snapshot"""
        try:
            if len(markets) < 2:
                raise ValueError("Insufficient markets to detect strike tier spacing")
                
            # Extract floor_strike values and sort them
            strikes = []
            for market in markets:
                floor_strike = market.get("floor_strike")
                if floor_strike is not None:
                    strikes.append(float(floor_strike))
            
            if len(strikes) < 2:
                raise ValueError("Insufficient valid strikes to detect spacing")
                
            strikes.sort()
            
            # Calculate differences between consecutive strikes
            differences = []
            for i in range(1, len(strikes)):
                diff = strikes[i] - strikes[i-1]
                differences.append(diff)
            
            # Find the most common difference (strike tier spacing)
            if differences:
                # Use the first difference as the tier spacing
                # (assuming consistent spacing across all strikes)
                tier_spacing = int(differences[0])
                return tier_spacing
            else:
                raise ValueError("No valid strike differences found")
                
        except Exception as e:
            raise
    
    def calculate_ttc_seconds(self, strike_date: str) -> int:
        """Calculate time to close in seconds - always top of next hour."""
        try:
            from datetime import datetime, timedelta
            now = datetime.now()
            
            # Calculate time to top of next hour
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            ttc_seconds = int((next_hour - now).total_seconds())
            
            return max(0, ttc_seconds)  # Allow countdown to 0
        except Exception as e:
            logger.warning(f"⚠️ Error calculating TTC, using default: {e}")
            return 300  # Default 5 minutes
    
    def generate_strike_table(self) -> bool:
        """
        Generate complete strike table data and write to PostgreSQL.
        
        Returns:
            True if successful
        """
        conn = None
        try:
            # Get current market data
            logger.info("📊 Getting current market data...")
            market_info = self.get_current_market_data()
            current_price = market_info["current_price"]
            momentum_score = market_info["momentum_score"]
            momentum_percentile = market_info["momentum_percentile"]
            market_data = market_info["market_data"]
            logger.info(f"✅ Got market data - Price: ${current_price:,.2f}, Momentum: {momentum_percentile:.1f}")
            
            # Calculate TTC
            ttc_seconds = self.calculate_ttc_seconds(market_data["strike_date"])
            
            logger.info(f"📊 Current data - Price: ${current_price:,.2f}, TTC: {ttc_seconds}s, Momentum Percentile: {momentum_percentile:.1f}")
            
            # Get available market strikes
            markets = market_data.get("markets", [])
            available_strikes = []
            
            for market in markets:
                floor_strike = market.get("floor_strike")
                if floor_strike:
                    # Convert from 118499.99 format to 118500
                    market_strike = int(float(floor_strike) + 0.01)
                    available_strikes.append(market_strike)
            
            if not available_strikes:
                raise ValueError("No valid strikes found in market data")
            
            # Sort by distance from current price
            available_strikes.sort(key=lambda x: abs(x - current_price))
            
            # Filter strikes to only include those within lookup table buffer range
            max_buffer = self.calculator.max_buffer
            filtered_strikes = []
            for strike in available_strikes:
                buffer = abs(current_price - strike)
                if buffer <= max_buffer:
                    filtered_strikes.append(strike)
                else:
                    logger.debug(f"Skipping strike {strike} - buffer {buffer} exceeds max buffer {max_buffer}")
            
            # Take the closest strikes (up to 21 total) from filtered list
            max_strikes = min(21, len(filtered_strikes))
            strikes = filtered_strikes[:max_strikes]
            
            logger.info(f"🎯 Processing {len(strikes)} strikes from market data")
            
            # Use momentum percentile directly as bucket
            # momentum_percentile is already in percentile format like -47.0, -51.0, etc.
            momentum_bucket = round(momentum_percentile)
            
            # Write to database
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Clear ALL previous strike table data - only keep current iteration
            try:
                cursor.execute(f"DELETE FROM live_data.strike_table_{self.symbol.lower()}")
                logger.info(f"✅ Cleared previous strike table data for {self.symbol.upper()}")
            except Exception as e:
                logger.error(f"❌ Error clearing strike table: {e}")
                conn.rollback()
                raise
            
            # Process each strike
            strike_data = []
            for strike in strikes:
                try:
                    # Calculate buffer and probability
                    buffer = abs(current_price - strike)
                    buffer_pct = (buffer / current_price) * 100
                    
                    # Get probability from lookup table
                    pos_prob, neg_prob = self.calculator.get_probability(
                        ttc_seconds, int(buffer), momentum_bucket, conn
                    )
                    
                    # Handle case where no probability found
                    if pos_prob is None or neg_prob is None:
                        logger.warning(f"⚠️ No probability found for strike {strike}, skipping")
                        continue
                    
                    # Determine probability based on strike position
                    if strike < current_price:
                        probability = pos_prob
                    else:
                        probability = neg_prob
                    
                    # Get market data for this strike
                    yes_ask = None
                    no_ask = None
                    volume = None
                    ticker = None
                    
                    # Find the matching market
                    for market in markets:
                        floor_strike = market.get("floor_strike")
                        if floor_strike is not None:
                            # Direct integer comparison - no precision issues
                            if int(float(floor_strike)) == strike:
                                yes_ask = market.get("yes_ask")
                                no_ask = market.get("no_ask")
                                volume = market.get("volume")
                                ticker = market.get("ticker")
                                break
                    
                    if yes_ask is None or no_ask is None:
                        logger.warning(f"⚠️ Missing ask prices for strike {strike}, skipping")
                        continue
                    
                    # Calculate yes_diff and no_diff based on money line position
                    if strike < current_price:
                        # Strike is BELOW current price (money line)
                        yes_diff = probability - yes_ask
                        no_diff = 100 - probability - no_ask
                        active_side = 'yes'
                    else:
                        # Strike is ABOVE current price (money line)
                        yes_diff = 100 - probability - yes_ask
                        no_diff = probability - no_ask
                        active_side = 'no'
                    
                    # Generate market title from event ticker
                    market_title = self.generate_market_title(market_data.get("event_ticker"))
                    
                    # Insert into database
                    cursor.execute(f"""
                    INSERT INTO live_data.strike_table_{self.symbol.lower()} 
                    (symbol, current_price, ttc_seconds, broker, event_ticker, market_title,
                     strike_tier, market_status, strike, buffer, buffer_pct, probability,
                     yes_ask, no_ask, yes_diff, no_diff, volume, ticker, active_side, 
                     momentum_weighted_score, momentum_percentile, timestamp, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        self.symbol.upper(), current_price, ttc_seconds, "Kalshi",
                        market_data.get("event_ticker"), market_title,
                        market_data.get("strike_tier"), market_data.get("market_status"),
                        strike, buffer, buffer_pct, probability,
                        yes_ask, no_ask, yes_diff, no_diff,
                        volume, ticker, active_side, momentum_score, momentum_percentile,
                        datetime.now(), datetime.now()
                    ))
                    
                    strike_data.append({
                        "strike": strike,
                        "buffer": buffer,
                        "probability": probability,
                        "yes_ask": yes_ask,
                        "no_ask": no_ask,
                        "active_side": active_side
                    })
                    
                except Exception as e:
                    logger.error(f"❌ Error processing strike {strike}: {e}")
                    continue
            
            conn.commit()
            logger.info(f"✅ Generated {len(strike_data)} strike table records for {self.symbol.upper()}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Error generating strike table: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                conn.close()
    
    def get_latest_strike_table_json(self) -> Optional[Dict[str, Any]]:
        """Get the latest strike table data in JSON format compatible with frontend."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Get the latest timestamp
            cursor.execute(f"""
            SELECT MAX(timestamp) FROM live_data.strike_table_{self.symbol.lower()}
            """)
            
            latest_timestamp = cursor.fetchone()[0]
            if not latest_timestamp:
                return None

            # Get all data for the latest timestamp
            cursor.execute(f"""
            SELECT symbol, current_price, ttc_seconds, broker, event_ticker, market_title,
                   strike_tier, market_status, strike, buffer, buffer_pct, probability,
                   yes_ask, no_ask, yes_diff, no_diff, volume, ticker, active_side, momentum_percentile
            FROM live_data.strike_table_{self.symbol.lower()}
            WHERE timestamp = %s
            ORDER BY strike
            """, (latest_timestamp,))
            
            rows = cursor.fetchall()
            
            if not rows:
                return None

            # Convert to JSON format matching the current UPC output
            result = {
                "symbol": rows[0][0],
                "current_price": float(rows[0][1]),
                "ttc": rows[0][2],
                "broker": rows[0][3],
                "event_ticker": rows[0][4],
                "market_title": rows[0][5],
                "strike_tier": rows[0][6],
                "market_status": rows[0][7],
                "last_updated": latest_timestamp.isoformat(),
                "strikes": []
            }
            
            for row in rows:
                result["strikes"].append({
                    "strike": int(row[8]),
                    "buffer": float(row[9]),
                    "buffer_pct": float(row[10]),
                    "probability": float(row[11]),
                    "yes_ask": float(row[12]) if row[12] is not None else None,
                    "no_ask": float(row[13]) if row[13] is not None else None,
                    "yes_diff": float(row[14]) if row[14] is not None else None,
                    "no_diff": float(row[15]) if row[15] is not None else None,
                    "volume": int(row[16]) if row[16] is not None else None,
                    "ticker": row[17],
                    "active_side": row[18]
                })
            
            # Add momentum data
            result["momentum"] = {
                "weighted_score": float(rows[0][19]) if rows[0][19] is not None else 0.0
            }
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error getting latest strike table JSON: {e}")
            return None
        finally:
            if conn:
                conn.close()

def run_continuous_generation(interval_seconds: int = 30, symbol: str = "btc"):
    """Run the strike table generator continuously."""
    logger.info(f"🚀 Starting continuous strike table generation for {symbol.upper()} (interval: {interval_seconds}s)")
    
    # Initialize generator
    generator = StrikeTableGenerator(symbol)
    
    # Setup schema
    generator.setup_live_data_schema()
    
    iteration = 0
    while True:
        try:
            iteration += 1
            logger.info(f"🔄 Generation iteration {iteration}")
            
            # Generate strike table
            success = generator.generate_strike_table()
            
            if success:
                logger.info(f"✅ Iteration {iteration} completed successfully")
                
                # Show summary of latest data
                try:
                    conn = psycopg2.connect(**POSTGRES_CONFIG)
                    cursor = conn.cursor()
                    
                    cursor.execute(f"""
                    SELECT COUNT(*) as total_strikes, 
                           MIN(probability) as min_prob, 
                           MAX(probability) as max_prob,
                           AVG(probability) as avg_prob
                    FROM live_data.strike_table_{generator.symbol.lower()}
                    """)
                    
                    result = cursor.fetchone()
                    if result:
                        total_strikes, min_prob, max_prob, avg_prob = result
                        logger.info(f"📊 Summary: {total_strikes} strikes, Prob range: {min_prob:.2f}%-{max_prob:.2f}%, Avg: {avg_prob:.2f}%")
                    
                    conn.close()
                except Exception as e:
                    logger.error(f"❌ Error getting summary: {e}")
            else:
                logger.error(f"❌ Iteration {iteration} failed")
            
            # Wait for next iteration
            logger.info(f"⏳ Waiting {interval_seconds} seconds before next generation...")
            import time
            time.sleep(interval_seconds)
            
        except KeyboardInterrupt:
            logger.info("🛑 Continuous generation stopped by user")
            break
        except Exception as e:
            logger.error(f"❌ Error in continuous generation: {e}")
            logger.info("⏳ Waiting 60 seconds before retry...")
            import time
            time.sleep(60)

def main():
    """Main function - choose between test mode and continuous mode."""
    parser = argparse.ArgumentParser(description='Strike Table Generator (Multi-Symbol)')
    parser.add_argument('symbol', help='Symbol to generate strike table for (e.g., BTC, ETH)')
    parser.add_argument('mode', help='Mode: test for single generation, continuous for ongoing generation')
    parser.add_argument('interval', type=int, nargs='?', default=30, help='Seconds between generations (for continuous mode)')
    
    args = parser.parse_args()
    symbol = args.symbol.upper()
    mode = args.mode
    interval = args.interval
    
    if mode == "continuous":
        # Run in continuous mode
        run_continuous_generation(interval, symbol)
    else:
        # Run in test mode
        logger.info(f"🚀 Testing PostgreSQL Strike Table Generator for {symbol}")
        
        # Initialize generator
        generator = StrikeTableGenerator(symbol)
        
        # Setup schema
        generator.setup_live_data_schema()
        
        # Test strike table generation
        logger.info("📊 Generating test strike table...")
        success = generator.generate_strike_table()
        
        if success:
            logger.info("✅ Strike table generation successful")
            
            # Test retrieval of strike table data
            logger.info("📊 Retrieving latest strike table data...")
            conn = psycopg2.connect(**POSTGRES_CONFIG)
            cursor = conn.cursor()
            
            cursor.execute(f"""
            SELECT COUNT(*) as total_records, MAX(timestamp) as latest_update 
            FROM live_data.strike_table_{generator.symbol.lower()}
            """)
            
            result = cursor.fetchone()
            if result:
                total_records, latest_update = result
                logger.info(f"✅ Strike table has {total_records} records")
                logger.info(f"📊 Latest update: {latest_update}")
                
                # Show sample strike table data
                cursor.execute(f"""
                SELECT strike, buffer, probability, yes_ask, no_ask, active_side 
                FROM live_data.strike_table_{generator.symbol.lower()} 
                ORDER BY strike 
                LIMIT 5
                """)
                
                rows = cursor.fetchall()
                logger.info("📊 Sample strike table data:")
                for row in rows:
                    strike, buffer, prob, yes_ask, no_ask, active_side = row
                    logger.info(f"   Strike ${strike:,}: {prob:.2f}% | YES: {yes_ask} | NO: {no_ask} | {active_side.upper()}")
            else:
                logger.error("❌ No strike table data found")
            
            conn.close()
        else:
            logger.error("❌ Strike table generation failed")
    
    def get_strike_table_consistency_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the consistency of the current strike table data.
        Returns None if no data exists, or a dict with consistency info.
        """
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Get timestamp consistency info
            cursor.execute(f"""
                SELECT 
                    COUNT(*) as total_records,
                    COUNT(DISTINCT timestamp) as unique_timestamps,
                    MIN(timestamp) as earliest_timestamp,
                    MAX(timestamp) as latest_timestamp,
                    MAX(timestamp) - MIN(timestamp) as time_span
                FROM live_data.strike_table_{self.symbol.lower()}
            """)
            
            result = cursor.fetchone()
            if not result or result[0] == 0:
                return None
            
            total_records, unique_timestamps, earliest, latest, time_span = result
            
            # Check if all records have the same timestamp (atomic update)
            is_consistent = unique_timestamps == 1
            
            return {
                "total_records": total_records,
                "unique_timestamps": unique_timestamps,
                "earliest_timestamp": earliest,
                "latest_timestamp": latest,
                "time_span_seconds": time_span.total_seconds() if time_span else 0,
                "is_consistent": is_consistent,
                "consistency_status": "CONSISTENT" if is_consistent else "MIXED_TIMESTAMPS"
            }
            
        except Exception as e:
            logger.error(f"❌ Error checking strike table consistency: {e}")
            return None
        finally:
            if conn:
                conn.close()

if __name__ == "__main__":
    main()
