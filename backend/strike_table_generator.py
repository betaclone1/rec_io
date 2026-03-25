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
import math
import psycopg2
import json
import logging
import argparse
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.config.config_manager import config
from backend.core.config.database import get_postgresql_connection
from backend.util.paths import get_data_dir, get_kalshi_data_dir


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
    log = logging.getLogger("strike_table_generator")
    if log.handlers:
        return log
    handler = _FlushingStreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_est_formatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


logger = _configure_logging()
HEARTBEAT_INTERVAL_SEC = 300

KALSHI_15M_SYMBOLS = frozenset({"BTC", "ETH", "SOL", "XRP"})
DEFAULT_KALSHI_15M_SYMBOL_ORDER = ("BTC", "ETH", "SOL", "XRP")


def fetch_kalshi_15m_symbols_ordered_from_db() -> tuple[str, ...]:
    """Same order as live_data.symbols_list (by id); Kalshi 15m subset only."""
    conn = None
    try:
        conn = get_postgresql_connection()
        if not conn:
            logger.warning(
                "Could not load symbols_list (no DB); using default order %s",
                DEFAULT_KALSHI_15M_SYMBOL_ORDER,
            )
            return DEFAULT_KALSHI_15M_SYMBOL_ORDER
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT symbol FROM live_data.symbols_list
            WHERE symbol IS NOT NULL AND trim(symbol) <> ''
            ORDER BY id
            """
        )
        seen: set[str] = set()
        ordered: list[str] = []
        for (raw,) in cursor.fetchall():
            u = raw.strip().upper()
            if u in KALSHI_15M_SYMBOLS and u not in seen:
                seen.add(u)
                ordered.append(u)
        conn.close()
        if not ordered:
            logger.warning(
                "symbols_list has no Kalshi 15m symbols; using default order %s",
                DEFAULT_KALSHI_15M_SYMBOL_ORDER,
            )
            return DEFAULT_KALSHI_15M_SYMBOL_ORDER
        return tuple(ordered)
    except Exception as e:
        logger.warning(
            "symbols_list read failed (%s); using default order %s",
            e,
            DEFAULT_KALSHI_15M_SYMBOL_ORDER,
        )
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return DEFAULT_KALSHI_15M_SYMBOL_ORDER


# SOL/XRP: spot and strike spacing need sub-cent precision in strike tables and lookup interpolation.
HIGH_PRECISION_PRICE_SYMBOLS = frozenset({"sol", "xrp"})
PRICE_BUFFER_DECIMAL_PLACES = 5
BUFFER_PCT_DECIMAL_PLACES_ALT = 6


def uses_high_precision_price(symbol: str) -> bool:
    return symbol.lower() in HIGH_PRECISION_PRICE_SYMBOLS


def round_price_buffer(val: float) -> float:
    return round(float(val), PRICE_BUFFER_DECIMAL_PLACES)


def strikes_equivalent(symbol: str, a: float, b: float) -> bool:
    """Match Kalshi floor strike to row strike; alt coins use 5dp equality."""
    if uses_high_precision_price(symbol):
        return math.isclose(
            float(a), float(b), rel_tol=0, abs_tol=10 ** (-PRICE_BUFFER_DECIMAL_PLACES)
        )
    return int(round(float(a))) == int(round(float(b)))


class LookupProbabilityCalculator:
    """Probability calculator using the lookup table instead of live interpolation."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.fine_price = uses_high_precision_price(symbol)
        self.lookup_table_name = self._find_latest_lookup_table()
        self.max_buffer = self._get_max_buffer_for_symbol()
    
    def _find_latest_lookup_table(self) -> str:
        """Find the most recent master lookup table for this symbol."""
        conn = None
        try:
            conn = get_postgresql_connection()
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
            logger.debug("Using lookup table: %s", latest_table)
            return latest_table
            
        except Exception as e:
            logger.error("Error finding lookup table for %s: %s", self.symbol.upper(), e)
            raise
        finally:
            if conn:
                conn.close()
    
    def _get_max_buffer_for_symbol(self) -> float:
        """Get the maximum buffer value for this symbol's lookup table."""
        conn = None
        try:
            conn = get_postgresql_connection()
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
            logger.error("Error getting max buffer for %s: %s", self.symbol.upper(), e)
            raise
        finally:
            if conn:
                conn.close()
    
    def get_probability(
        self, ttc_seconds: int, buffer_points: float, momentum_bucket: int, conn=None
    ) -> tuple[float, float]:
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
        if float(buffer_points) > float(self.max_buffer):
            logger.warning(
                "Buffer %s outside lookup table range (0-%s), using max buffer as fallback",
                buffer_points,
                self.max_buffer,
            )
            buffer_points = float(self.max_buffer)
        buffer_points = float(buffer_points)
        
        use_external_conn = conn is not None
        if not use_external_conn:
            conn = None
        try:
            if not use_external_conn:
                conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            # Search window around buffer_points for grid neighbors (BTC: large integer buffers; SOL/XRP: small USD buffers).
            mb = float(self.max_buffer)
            if self.fine_price:
                buffer_range = max(1e-4, mb * 0.05)
            else:
                buffer_range = max(5.0, mb * 0.01)
            
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
                logger.warning("No data found for TTC=%s, buffer=%s, momentum=%s", ttc_seconds, buffer_points, momentum_bucket)
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
                logger.error("Unexpected number of results: %s", len(results))
                raise ValueError(f"Unexpected number of lookup results: {len(results)}")
                
        except Exception as e:
            logger.error("Error in lookup probability calculation: %s", e)
            raise
        finally:
            if conn and not use_external_conn:
                conn.close()
    
    
    def _bilinear_interpolate(
        self, results: List[Tuple], ttc_seconds: int, buffer_points: float
    ) -> Tuple[float, float]:
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
                        if abs(float(result[0]) - float(ttc)) < 1e-6 and math.isclose(
                            float(result[1]),
                            float(buffer),
                            rel_tol=0,
                            abs_tol=1e-5,
                        ):
                            corners[(ttc, buffer)] = (float(result[2]), float(result[3]))
                            break
            
            if len(corners) != 4:
                # Fall back to linear interpolation if we don't have all 4 corners
                return self._linear_interpolate(sorted_results, ttc_seconds, buffer_points)
            
            # Perform bilinear interpolation
            pos_interp = self._interpolate_2d(
                float(corners[(ttc_lower, buffer_lower)][0]), float(corners[(ttc_upper, buffer_lower)][0]),
                float(corners[(ttc_lower, buffer_upper)][0]), float(corners[(ttc_upper, buffer_upper)][0]),
                float(ttc_lower), float(ttc_upper), float(buffer_lower), float(buffer_upper),
                float(ttc_seconds), float(buffer_points),
            )
            
            neg_interp = self._interpolate_2d(
                float(corners[(ttc_lower, buffer_lower)][1]), float(corners[(ttc_upper, buffer_lower)][1]),
                float(corners[(ttc_lower, buffer_upper)][1]), float(corners[(ttc_upper, buffer_upper)][1]),
                float(ttc_lower), float(ttc_upper), float(buffer_lower), float(buffer_upper),
                float(ttc_seconds), float(buffer_points),
            )
            
            return pos_interp, neg_interp
            
        except Exception as e:
            logger.error("Error in bilinear interpolation: %s", e)
            return 50.0, 50.0
    
    def _interpolate_2d(
        self,
        q11: float,
        q21: float,
        q12: float,
        q22: float,
        x1: float,
        x2: float,
        y1: float,
        y2: float,
        x: float,
        y: float,
    ) -> float:
        """Perform 2D bilinear interpolation (TTC and buffer may be fractional for alt-coin lookups)."""
        if x2 == x1 or y2 == y1:
            return q11
        
        # Bilinear interpolation formula
        f1 = q11 * (x2 - x) * (y2 - y) / ((x2 - x1) * (y2 - y1))
        f2 = q21 * (x - x1) * (y2 - y) / ((x2 - x1) * (y2 - y1))
        f3 = q12 * (x2 - x) * (y - y1) / ((x2 - x1) * (y2 - y1))
        f4 = q22 * (x - x1) * (y - y1) / ((x2 - x1) * (y2 - y1))
        
        return f1 + f2 + f3 + f4
    
    def _linear_interpolate(
        self, results: List[Tuple], ttc_seconds: int, buffer_points: float
    ) -> Tuple[float, float]:
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

    def __init__(
        self,
        symbol: str,
        interval: str = "hourly",
        *,
        unified_15m: bool = False,
        data_exchange: str = "kalshi",
        data_broker: str | None = None,
    ):
        self.unified_15m = unified_15m
        _ex = data_broker if data_broker is not None else data_exchange
        self.data_exchange = (_ex or "kalshi").strip().lower()
        self.symbol = symbol.lower()
        self.interval = interval.lower()  # "hourly" or "15m"
        if self.unified_15m and self.interval != "15m":
            raise ValueError("unified_15m requires interval 15m")
        if self.interval == "15m" and self.symbol not in ("btc", "eth", "sol", "xrp"):
            raise ValueError("15m interval only supported for BTC, ETH, SOL, XRP")
        logger.debug("Initializing strike table generator for %s (%s)", symbol.upper(), self.interval)
        self.calculator = LookupProbabilityCalculator(symbol)
        logger.debug("Strike table generator initialized for %s (%s)", symbol.upper(), self.interval)

    def _strike_table_name(self) -> str:
        """Table name: unified strike_table_15m or strike_table_hourly_{symbol} / strike_table_15m_{symbol}."""
        if self.unified_15m:
            return "strike_table_15m"
        suffix = "15m" if self.interval == "15m" else "hourly"
        return f"strike_table_{suffix}_{self.symbol}"

    def _setup_unified_15m_schema(self, cursor, conn) -> None:
        """CREATE IF NOT EXISTS live_data.strike_table_15m (matches migration)."""
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS live_data.strike_table_15m (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                symbol VARCHAR(10) NOT NULL,
                exchange VARCHAR(20) NOT NULL,
                market TEXT DEFAULT '15m',
                current_price NUMERIC(18,5),
                ttc_hourly INTEGER,
                ttc_15m INTEGER,
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike NUMERIC(18,5),
                buffer NUMERIC(18,5),
                buffer_pct NUMERIC(12,6),
                probability_hourly DECIMAL(5,2),
                probability_15m DECIMAL(5,2),
                yes_ask DECIMAL(5,2),
                no_ask DECIMAL(5,2),
                yes_ask_dollars TEXT,
                no_ask_dollars TEXT,
                yes_bid_dollars TEXT,
                no_bid_dollars TEXT,
                yes_price_spread NUMERIC(6,4),
                no_price_spread NUMERIC(6,4),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume INTEGER,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                momentum_percentile DECIMAL(5,1),
                volatility NUMERIC(10,6),
                volatility_percentile NUMERIC(5,1),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS strike_table_15m_exchange_symbol_idx
                ON live_data.strike_table_15m (exchange, symbol)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_strike_table_15m_lookup
                ON live_data.strike_table_15m (timestamp, symbol, current_price)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS strike_table_15m_exchange_symbol_timestamp_idx
                ON live_data.strike_table_15m (exchange, symbol, timestamp DESC)
            """
        )
        conn.commit()
        logger.debug("Unified strike_table_15m schema ready")

    def _normalize_floor_strike(self, floor_strike: float) -> float:
        """Kalshi floor strike as stored key: integer dollars for BTC/ETH; 5dp for SOL/XRP."""
        if uses_high_precision_price(self.symbol):
            return round_price_buffer(floor_strike)
        return float(int(round(float(floor_strike))))
    
    def generate_market_title(self, event_ticker: str) -> str:
        """
        Generate a human-readable market title from event ticker.
        Hourly: YYMMMDDHH e.g. 26MAR2514 -> "BTC price on Mar 25 at 2pm"
        15m:    DDMMMYY + HHMM e.g. 26FEB271745 -> "BTC price today at 5:45pm"
        """
        if not event_ticker:
            return f"{self.symbol.upper()} price today"
        
        try:
            parts = event_ticker.split('-')
            if len(parts) < 2:
                return f"{self.symbol.upper()} price today"
            
            date_time_part = parts[-1]  # 25AUG1515 (hourly) or 26FEB271745 (15m)
            
            if self.interval == "15m":
                # 15m: DDMMMYY + HHMM e.g. 26FEB271745 -> 26 FEB 27, 17:45
                if len(date_time_part) >= 11:
                    date_part = date_time_part[:7]   # 26FEB27
                    time_part = date_time_part[7:11] # 1745
                    hour_24 = int(time_part[:2])
                    minute = int(time_part[2:4])
                    # 12-hour with h:mm am/pm
                    if hour_24 == 0:
                        time_str = f"12:{minute:02d}am"
                    elif hour_24 < 12:
                        time_str = f"{hour_24}:{minute:02d}am"
                    elif hour_24 == 12:
                        time_str = f"12:{minute:02d}pm"
                    else:
                        time_str = f"{hour_24 - 12}:{minute:02d}pm"
                    return f"{self.symbol.upper()} price today at {time_str}"
                return f"{self.symbol.upper()} price today"
            
            # Hourly: YYMMMDDHH e.g. 26MAR2514 -> 2026 Mar 25, 2pm
            if len(date_time_part) >= 9:
                date_part = date_time_part[:7]   # 26MAR25 (YYMMMDD)
                hour_part = date_time_part[7:9]  # 14
                year_2 = date_part[:2]   # 26
                month = date_part[2:5]   # MAR
                day = date_part[5:7]      # 25
                hour_24 = int(hour_part)
                if hour_24 == 0:
                    time_str = "12am"
                elif hour_24 < 12:
                    time_str = f"{hour_24}am"
                elif hour_24 == 12:
                    time_str = "12pm"
                else:
                    time_str = f"{hour_24 - 12}pm"
                today = datetime.now()
                event_date = datetime.strptime(f"{day}{month}20{year_2}", "%d%b%Y")
                if event_date.date() == today.date():
                    return f"{self.symbol.upper()} price today at {time_str}"
                month_name = event_date.strftime("%b")
                return f"{self.symbol.upper()} price on {month_name} {day} at {time_str}"
            
            return f"{self.symbol.upper()} price today"
            
        except Exception as e:
            logger.error("Error parsing event ticker %s: %s", event_ticker, e)
            return f"{self.symbol.upper()} price today"
        
    def setup_live_data_schema(self):
        """Create live_data schema and tables if they don't exist."""
        conn = None
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            # Create live_data schema
            cursor.execute("CREATE SCHEMA IF NOT EXISTS live_data")

            if self.unified_15m:
                self._setup_unified_15m_schema(cursor, conn)
                return
            
            # Create strike table (hourly or 15m). Same column set: ttc_hourly, ttc_15m, probability_hourly, probability_15m.
            table_name = self._strike_table_name()
            if uses_high_precision_price(self.symbol):
                price_t, buffer_t, strike_t, buffer_pct_t = (
                    "NUMERIC(18,5)",
                    "NUMERIC(18,5)",
                    "NUMERIC(18,5)",
                    "NUMERIC(12,6)",
                )
            else:
                price_t, buffer_t, strike_t, buffer_pct_t = (
                    "DECIMAL(10,2)",
                    "DECIMAL(10,2)",
                    "INTEGER",
                    "DECIMAL(5,2)",
                )
            strike_table_sql = f"""
            CREATE TABLE IF NOT EXISTS live_data.{table_name} (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                symbol VARCHAR(10),
                market TEXT,
                current_price {price_t},
                ttc_hourly INTEGER,
                ttc_15m INTEGER,
                broker VARCHAR(20),
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike {strike_t},
                buffer {buffer_t},
                buffer_pct {buffer_pct_t},
                probability_hourly DECIMAL(5,2),
                probability_15m DECIMAL(5,2),
                yes_ask DECIMAL(5,2),
                no_ask DECIMAL(5,2),
                yes_ask_dollars TEXT,
                no_ask_dollars TEXT,
                yes_bid_dollars TEXT,
                no_bid_dollars TEXT,
                yes_price_spread NUMERIC(6,4),
                no_price_spread NUMERIC(6,4),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume INTEGER,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                momentum_percentile DECIMAL(5,1),
                volatility NUMERIC(10,6),
                volatility_percentile NUMERIC(5,1),
                movement NUMERIC(10,4),
                movement_percentile NUMERIC(5,1),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """
            cursor.execute(strike_table_sql)
            conn.commit()  # Persist table before ALTERs so rollback in loop doesn't drop it
            
            # Add missing columns if they don't exist
            missing_columns = [
                ("market", "TEXT"),
                ("momentum_weighted_score", "DECIMAL(5,3)"),
                ("yes_bid_dollars", "TEXT"),
                ("no_bid_dollars", "TEXT"),
                ("yes_price_spread", "NUMERIC(6,4)"),
                ("no_price_spread", "NUMERIC(6,4)"),
                ("volatility", "NUMERIC(10,6)"),
                ("volatility_percentile", "NUMERIC(5,1)"),
                ("movement", "NUMERIC(10,4)"),
                ("movement_percentile", "NUMERIC(5,1)"),
            ]
            for column_name, column_type in missing_columns:
                try:
                    cursor.execute(f"ALTER TABLE live_data.{table_name} ADD COLUMN {column_name} {column_type};")
                    conn.commit()
                except psycopg2.ProgrammingError:
                    conn.rollback()  # Only rolls back the failed ALTER
                    pass
            
            # Create index for strike table
            strike_index_sql = f"""
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_lookup
        ON live_data.{table_name} (timestamp, symbol, current_price)
            """
            cursor.execute(strike_index_sql)
            
            conn.commit()
            logger.debug("Live data schema and tables created for %s", self.symbol.upper())
            
        except Exception as e:
            logger.error("Error setting up live data schema: %s", e)
            raise
        finally:
            if conn:
                conn.close()
    
    def get_current_market_data(self) -> Dict[str, Any]:
        """Get current market data from live_data.live_price_log_1s_{symbol} and Kalshi snapshot."""
        try:
            # Get current price and momentum from PostgreSQL
            logger.debug("Connecting to database for %s price data", self.symbol.upper())
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            cursor.execute(f"""
            SELECT price, momentum, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile
            FROM live_data.live_price_log_1s_{self.symbol}
            ORDER BY timestamp DESC
            LIMIT 1
            """)
            
            result = cursor.fetchone()
            if not result:
                raise ValueError(f"No price data found in live_data.live_price_log_1s_{self.symbol}")
            
            current_price = float(result[0])
            momentum_score = float(result[1]) if result[1] is not None else 0.0
            momentum_percentile = float(result[2]) if result[2] is not None else 0.0
            volatility = float(result[3]) if result[3] is not None else None
            volatility_percentile = float(result[4]) if result[4] is not None else None
            movement = float(result[5]) if result[5] is not None else None
            movement_percentile = float(result[6]) if result[6] is not None else None
            
            conn.close()
            
            # Get market snapshot
            market_data = self.get_kalshi_market_snapshot()
            
            return {
                "current_price": current_price,
                "momentum_score": momentum_score,
                "momentum_percentile": momentum_percentile,
                "volatility": volatility,
                "volatility_percentile": volatility_percentile,
                "movement": movement,
                "movement_percentile": movement_percentile,
                "market_data": market_data
            }
            
        except Exception as e:
            logger.error("Error getting current market data: %s", e)
            raise
    
    def get_kalshi_market_snapshot(self) -> Dict[str, Any]:
        """Get live Kalshi market snapshot from market_kalshi_hourly_{symbol}, market_kalshi_15m_{symbol}, or unified market_kalshi_15m."""
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            sym_u = self.symbol.upper()

            if self.interval == "15m" and self.unified_15m:
                cursor.execute(
                    """
                    SELECT event_ticker
                    FROM live_data.market_kalshi_15m
                    WHERE exchange = %s AND symbol = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (self.data_exchange, sym_u),
                )
                result = cursor.fetchone()
                if not result:
                    raise ValueError(
                        "No event_ticker in market_kalshi_15m for exchange=%s symbol=%s"
                        % (self.data_exchange, sym_u)
                    )
                event_ticker = result[0]
                cursor.execute(
                    """
                    SELECT market_ticker, strike, yes_bid, yes_ask, no_bid, no_ask, last_price,
                           yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
                           volume_fp AS volume, volume_24h_fp AS volume_24h, open_interest, liquidity, updated_at
                    FROM live_data.market_kalshi_15m
                    WHERE event_ticker = %s AND exchange = %s AND symbol = %s
                    ORDER BY updated_at DESC
                    """,
                    (event_ticker, self.data_exchange, sym_u),
                )
                market_rows = cursor.fetchall()
            else:
                if self.interval == "15m":
                    market_table = f"market_kalshi_15m_{self.symbol}"
                else:
                    market_table = f"market_kalshi_hourly_{self.symbol}"

                cursor.execute(
                    f"""
                    SELECT event_ticker
                    FROM live_data.{market_table}
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
                result = cursor.fetchone()
                if not result:
                    raise ValueError("No event_ticker found in %s table" % market_table)
                event_ticker = result[0]

                cursor.execute(
                    f"""
                    SELECT market_ticker, strike, yes_bid, yes_ask, no_bid, no_ask, last_price,
                           yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars,
                           volume_fp AS volume, volume_24h_fp AS volume_24h, open_interest, liquidity, updated_at
                    FROM live_data.{market_table}
                    WHERE event_ticker = %s
                    ORDER BY updated_at DESC
                    """,
                    (event_ticker,),
                )
                market_rows = cursor.fetchall()
            if not market_rows:
                raise ValueError("No markets found for event_ticker: %s" % event_ticker)
            
            markets = []
            for row in market_rows:
                market_ticker, strike, yes_bid, yes_ask, no_bid, no_ask, last_price, yes_bid_dollars, yes_ask_dollars, no_bid_dollars, no_ask_dollars, last_price_dollars, volume, volume_24h, open_interest, liquidity, updated_at = row
                floor_strike = None
                if strike:
                    try:
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
                    "yes_bid_dollars": yes_bid_dollars,
                    "yes_ask_dollars": yes_ask_dollars,
                    "no_bid_dollars": no_bid_dollars,
                    "no_ask_dollars": no_ask_dollars,
                    "last_price_dollars": last_price_dollars,
                    "volume": volume,
                    "volume_24h": volume_24h,
                    "open_interest": open_interest,
                    "liquidity": liquidity,
                    "status": "active"
                }
                markets.append(market)
            
            # 15m: single strike, strike_tier 0; hourly: detect from spacing
            if self.interval == "15m":
                strike_tier = 0
            else:
                strike_tier = self.detect_strike_tier_spacing(markets)
            
            event_title = f"{self.symbol.upper()} Price at {event_ticker}"
            try:
                parts = event_ticker.split('-')
                if len(parts) >= 2:
                    date_part = parts[1]
                    year = "20" + date_part[:2]
                    month_str = date_part[2:5]
                    day = date_part[5:7]
                    hour = date_part[7:9] if len(date_part) >= 9 else "00"
                    try:
                        month = datetime.strptime(month_str.upper(), "%b").strftime("%m")
                    except ValueError:
                        month = "01"
                    strike_date = f"{year}-{month}-{day}T{hour}:00:00Z"
                else:
                    strike_date = "2025-08-15T15:00:00Z"
            except Exception:
                strike_date = "2025-08-15T15:00:00Z"
            
            conn.close()
            logger.debug("Loaded live market data - Event: %s, Markets: %s, Tier: $%s", event_ticker, len(markets), f"{strike_tier:,}")
            return {
                "event_ticker": event_ticker,
                "market_status": "active",
                "event_title": event_title,
                "strike_date": strike_date,
                "strike_tier": strike_tier,
                "markets": markets
            }
        except Exception as e:
            logger.error("Error getting Kalshi market data from database: %s", e)
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
        """Calculate time to close: top of next hour (hourly) or next 15m boundary (15m)."""
        try:
            from datetime import datetime, timedelta
            if self.interval == "15m":
                ttc_seconds = self._seconds_to_next_15m_boundary_est()
            else:
                now = datetime.now()
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                ttc_seconds = int((next_hour - now).total_seconds())
            return max(0, ttc_seconds)
        except Exception as e:
            logger.warning("Error calculating TTC, using default: %s", e)
            return 300

    def _seconds_to_next_15m_boundary_est(self) -> int:
        """Seconds until the next 15-minute boundary in EST (:00, :15, :30, :45). Used for ttc_15m column."""
        try:
            from datetime import datetime, timedelta
            import pytz
            est = pytz.timezone("America/New_York")
            now = datetime.now(est)
            minute = now.minute
            next_min = ((minute // 15) + 1) * 15
            if next_min >= 60:
                next_boundary = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                next_boundary = now.replace(minute=next_min, second=0, microsecond=0)
            return max(0, int((next_boundary - now).total_seconds()))
        except Exception as e:
            logger.warning("Error calculating 15m TTC, using default: %s", e)
            return 300
    
    def generate_strike_table(self) -> Tuple[bool, Optional[str], int]:
        """
        Generate complete strike table data and write to PostgreSQL.

        Returns:
            (success, event_ticker, num_strikes) on success; (False, None, 0) on failure.
        """
        conn = None
        try:
            # Get current market data
            logger.debug("Getting current market data")
            market_info = self.get_current_market_data()
            current_price = market_info["current_price"]
            momentum_score = market_info["momentum_score"]
            momentum_percentile = market_info["momentum_percentile"]
            volatility = market_info.get("volatility")
            volatility_percentile = market_info.get("volatility_percentile")
            movement = market_info.get("movement")
            movement_percentile = market_info.get("movement_percentile")
            market_data = market_info["market_data"]
            price_fmt = f"{current_price:,.5f}" if uses_high_precision_price(self.symbol) else f"{current_price:,.2f}"
            logger.debug("Got market data - Price: $%s, Momentum: %s", price_fmt, momentum_percentile)
            
            # Calculate TTC (hourly or 15m depending on interval) and always 15m boundary for ttc_15m column
            ttc_seconds = self.calculate_ttc_seconds(market_data["strike_date"])
            ttc_15m_seconds = self._seconds_to_next_15m_boundary_est()
            
            price_fmt2 = f"{current_price:,.5f}" if uses_high_precision_price(self.symbol) else f"{current_price:,.2f}"
            logger.debug(
                "Current data - Price: $%s, TTC: %ss, TTC_15m: %ss, Momentum: %s",
                price_fmt2,
                ttc_seconds,
                ttc_15m_seconds,
                momentum_percentile,
            )
            
            # Get available market strikes (use same integer as match logic so we find ask prices)
            markets = market_data.get("markets", [])
            available_strikes = []
            for market in markets:
                floor_strike = market.get("floor_strike")
                if floor_strike is not None:
                    available_strikes.append(self._normalize_floor_strike(float(floor_strike)))

            if self.interval == "15m":
                # Single strike only; strike_tier 0.
                # For 15m we do NOT depend on Kalshi strikes existing; if none are usable,
                # synthesize a strike from the current price.
                if available_strikes:
                    available_strikes.sort(
                        key=lambda x: abs(float(x) - float(current_price))
                    )
                    single = available_strikes[0]
                else:
                    if uses_high_precision_price(self.symbol):
                        single = round_price_buffer(current_price)
                    else:
                        single = int(round(current_price))
                    logger.warning(
                        "15m: no valid strikes from market data, using synthetic strike %s based on current_price %s",
                        single,
                        current_price,
                    )

                max_buffer = self.calculator.max_buffer
                if abs(current_price - single) > max_buffer:
                    logger.warning("15m strike %s outside lookup buffer %s, using anyway", single, max_buffer)
                strikes = [single]
                logger.debug("Processing 1 strike (15m): %s", single)
            else:
                if not available_strikes:
                    raise ValueError("No valid strikes found in market data")
                available_strikes.sort(key=lambda x: abs(x - current_price))
                max_buffer = self.calculator.max_buffer
                filtered_strikes = [s for s in available_strikes if abs(current_price - s) <= max_buffer]
                max_strikes = min(21, len(filtered_strikes))
                strikes = filtered_strikes[:max_strikes]
                logger.debug("Processing %s strikes from market data", len(strikes))
            
            # Use momentum percentile directly as bucket
            # momentum_percentile is already in percentile format like -47.0, -51.0, etc.
            momentum_bucket = round(momentum_percentile)
            
            # Write to database
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            table_name = self._strike_table_name()
            # All strike tables use ttc_hourly, ttc_15m, probability_hourly, probability_15m (15m tables leave hourly cols NULL).
            # Clear ALL previous strike table data - only keep current iteration
            try:
                if self.unified_15m:
                    cursor.execute(
                        f"DELETE FROM live_data.{table_name} WHERE exchange = %s AND symbol = %s",
                        (self.data_exchange, self.symbol.upper()),
                    )
                else:
                    cursor.execute(f"DELETE FROM live_data.{table_name}")
                logger.debug("Cleared previous strike table data for %s (%s)", self.symbol.upper(), self.interval)
            except Exception as e:
                logger.error("Error clearing strike table: %s", e)
                conn.rollback()
                raise
            
            # Process each strike
            strike_data = []
            for strike in strikes:
                try:
                    # Calculate buffer and probability
                    raw_buf = abs(float(current_price) - float(strike))
                    buffer = (
                        round_price_buffer(raw_buf)
                        if uses_high_precision_price(self.symbol)
                        else raw_buf
                    )
                    buffer_pct = (float(buffer) / float(current_price)) * 100 if current_price else None
                    if (
                        buffer_pct is not None
                        and uses_high_precision_price(self.symbol)
                    ):
                        buffer_pct = round(float(buffer_pct), BUFFER_PCT_DECIMAL_PLACES_ALT)
                    
                    # Probability lookups: hourly uses both TTCs; 15m uses only ttc_15m (same as probability_15m).
                    pos_prob, neg_prob = self.calculator.get_probability(
                        ttc_seconds, float(buffer), momentum_bucket, conn
                    )
                    if strike < current_price:
                        probability = pos_prob
                    else:
                        probability = neg_prob
                    if pos_prob is None or neg_prob is None:
                        logger.warning("No probability found for strike %s, skipping", strike)
                        continue
                    
                    pos_prob_15m, neg_prob_15m = self.calculator.get_probability(
                        ttc_15m_seconds, float(buffer), momentum_bucket, conn
                    )
                    if strike < current_price:
                        probability_15m = pos_prob_15m if pos_prob_15m is not None else None
                    else:
                        probability_15m = neg_prob_15m if neg_prob_15m is not None else None
                    if self.interval == "15m":
                        probability = probability_15m or probability  # 15m row uses 15m probability for diff calc
                    
                    # Get market data for this strike
                    yes_ask = None
                    no_ask = None
                    yes_ask_dollars = None
                    no_ask_dollars = None
                    yes_bid_dollars = None
                    no_bid_dollars = None
                    volume = None
                    ticker = None
                    
                    # Find the matching market
                    for market in markets:
                        floor_strike = market.get("floor_strike")
                        if floor_strike is not None:
                            if strikes_equivalent(self.symbol, float(floor_strike), float(strike)):
                                yes_ask = market.get("yes_ask")
                                no_ask = market.get("no_ask")
                                yes_ask_dollars = market.get("yes_ask_dollars")
                                no_ask_dollars = market.get("no_ask_dollars")
                                yes_bid_dollars = market.get("yes_bid_dollars")
                                no_bid_dollars = market.get("no_bid_dollars")
                                volume = market.get("volume")
                                ticker = market.get("ticker")
                                break
                    
                    if yes_ask is None or no_ask is None:
                        logger.warning("Missing ask prices for strike %s, skipping", strike)
                        continue
                    
                    # Calculate yes_diff and no_diff based on money line position using subpenny precision
                    # Convert _dollars values to cents for calculation (multiply by 100)
                    # Require _dollars values - no fallback to legacy cents
                    if not yes_ask_dollars or not no_ask_dollars:
                        logger.warning("Missing _dollars values for strike %s, skipping", strike)
                        continue
                    
                    # Calculate price spreads (ask_dollars - bid_dollars, always positive)
                    yes_price_spread = None
                    no_price_spread = None
                    if yes_ask_dollars and yes_bid_dollars:
                        try:
                            yes_price_spread = max(0, float(yes_ask_dollars) - float(yes_bid_dollars))
                        except (ValueError, TypeError):
                            yes_price_spread = None
                    if no_ask_dollars and no_bid_dollars:
                        try:
                            no_price_spread = max(0, float(no_ask_dollars) - float(no_bid_dollars))
                        except (ValueError, TypeError):
                            no_price_spread = None
                    
                    yes_ask_cents = float(yes_ask_dollars) * 100
                    no_ask_cents = float(no_ask_dollars) * 100
                    
                    if strike < current_price:
                        # Strike is BELOW current price (money line)
                        yes_diff = probability - yes_ask_cents
                        no_diff = 100 - probability - no_ask_cents
                        active_side = 'yes'
                    else:
                        # Strike is ABOVE current price (money line)
                        yes_diff = 100 - probability - yes_ask_cents
                        no_diff = probability - no_ask_cents
                        active_side = 'no'
                    
                    # Generate market title from event ticker
                    market_title = self.generate_market_title(market_data.get("event_ticker"))
                    # 15m: strike_tier 0; hourly: from market_data
                    strike_tier_val = 0 if self.interval == "15m" else market_data.get("strike_tier")
                    market_val = "15m" if self.interval == "15m" else "hourly"
                    ttc_hourly_val = ttc_seconds if self.interval == "hourly" else None
                    prob_hourly_val = probability if self.interval == "hourly" else None
                    # Insert: unified 15m uses exchange as execution venue key (e.g. kalshi).
                    if self.unified_15m:
                        cursor.execute(
                            f"""
                            INSERT INTO live_data.{table_name}
                            (symbol, exchange, market, current_price, ttc_hourly, ttc_15m, event_ticker, market_title,
                             strike_tier, market_status, strike, buffer, buffer_pct, probability_hourly, probability_15m,
                             yes_ask, no_ask, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
                             yes_price_spread, no_price_spread, yes_diff, no_diff, volume, ticker, active_side,
                             momentum_weighted_score, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile,
                             timestamp, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                self.symbol.upper(),
                                self.data_exchange,
                                market_val,
                                current_price,
                                ttc_hourly_val,
                                ttc_15m_seconds,
                                market_data.get("event_ticker"),
                                market_title,
                                strike_tier_val,
                                market_data.get("market_status"),
                                strike,
                                buffer,
                                buffer_pct,
                                prob_hourly_val,
                                probability_15m,
                                yes_ask,
                                no_ask,
                                yes_ask_dollars,
                                no_ask_dollars,
                                yes_bid_dollars,
                                no_bid_dollars,
                                yes_price_spread,
                                no_price_spread,
                                yes_diff,
                                no_diff,
                                volume,
                                ticker,
                                active_side,
                                momentum_score,
                                momentum_percentile,
                                volatility,
                                volatility_percentile,
                                movement,
                                movement_percentile,
                                datetime.now(),
                                datetime.now(),
                            ),
                        )
                    else:
                        cursor.execute(
                            f"""
                            INSERT INTO live_data.{table_name}
                            (symbol, market, current_price, ttc_hourly, ttc_15m, broker, event_ticker, market_title,
                             strike_tier, market_status, strike, buffer, buffer_pct, probability_hourly, probability_15m,
                             yes_ask, no_ask, yes_ask_dollars, no_ask_dollars, yes_bid_dollars, no_bid_dollars,
                             yes_price_spread, no_price_spread, yes_diff, no_diff, volume, ticker, active_side,
                             momentum_weighted_score, momentum_percentile, volatility, volatility_percentile, movement, movement_percentile,
                             timestamp, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                self.symbol.upper(),
                                market_val,
                                current_price,
                                ttc_hourly_val,
                                ttc_15m_seconds,
                                "Kalshi",
                                market_data.get("event_ticker"),
                                market_title,
                                strike_tier_val,
                                market_data.get("market_status"),
                                strike,
                                buffer,
                                buffer_pct,
                                prob_hourly_val,
                                probability_15m,
                                yes_ask,
                                no_ask,
                                yes_ask_dollars,
                                no_ask_dollars,
                                yes_bid_dollars,
                                no_bid_dollars,
                                yes_price_spread,
                                no_price_spread,
                                yes_diff,
                                no_diff,
                                volume,
                                ticker,
                                active_side,
                                momentum_score,
                                momentum_percentile,
                                volatility,
                                volatility_percentile,
                                movement,
                                movement_percentile,
                                datetime.now(),
                                datetime.now(),
                            ),
                        )
                    
                    strike_data.append({
                        "strike": strike,
                        "buffer": buffer,
                        "probability": probability,
                        "yes_ask": yes_ask,
                        "no_ask": no_ask,
                        "active_side": active_side
                    })
                    
                except Exception as e:
                    logger.error("Error processing strike %s: %s", strike, e)
                    continue
            
            conn.commit()
            event_ticker = market_data.get("event_ticker")
            logger.debug("Generated %s strike table records for %s", len(strike_data), self.symbol.upper())
            return (True, event_ticker, len(strike_data))
        except Exception as e:
            logger.error("Error generating strike table: %s", e)
            if conn:
                conn.rollback()
            return (False, None, 0)
        finally:
            if conn:
                conn.close()
    
    def get_latest_strike_table_json(self) -> Optional[Dict[str, Any]]:
        """Get the latest strike table data in JSON format compatible with frontend."""
        conn = None
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()

            table_name = self._strike_table_name()
            sym_u = self.symbol.upper()
            venue_col = "exchange" if self.unified_15m else "broker"

            if self.unified_15m:
                cursor.execute(
                    f"""
                    SELECT MAX(timestamp) FROM live_data.{table_name}
                    WHERE exchange = %s AND symbol = %s
                    """,
                    (self.data_exchange, sym_u),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT MAX(timestamp) FROM live_data.{table_name}
                    """
                )

            latest_timestamp = cursor.fetchone()[0]
            if not latest_timestamp:
                return None

            # Get all data for the latest timestamp. 15m tables use ttc_15m/probability_15m; hourly use ttc_hourly/probability_hourly.
            ttc_col = "ttc_15m" if self.interval == "15m" else "ttc_hourly"
            prob_col = "probability_15m" if self.interval == "15m" else "probability_hourly"

            if self.unified_15m:
                cursor.execute(
                    f"""
                    SELECT symbol, current_price, {ttc_col}, {venue_col}, event_ticker, market_title,
                           strike_tier, market_status, strike, buffer, buffer_pct, {prob_col},
                           yes_ask, no_ask, yes_ask_dollars, no_ask_dollars, yes_diff, no_diff, volume, ticker, active_side,
                           momentum_percentile, volatility, volatility_percentile, movement, movement_percentile
                    FROM live_data.{table_name}
                    WHERE exchange = %s AND symbol = %s AND timestamp = %s
                    ORDER BY strike
                    """,
                    (self.data_exchange, sym_u, latest_timestamp),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT symbol, current_price, {ttc_col}, {venue_col}, event_ticker, market_title,
                           strike_tier, market_status, strike, buffer, buffer_pct, {prob_col},
                           yes_ask, no_ask, yes_ask_dollars, no_ask_dollars, yes_diff, no_diff, volume, ticker, active_side,
                           momentum_percentile, volatility, volatility_percentile, movement, movement_percentile
                    FROM live_data.{table_name}
                    WHERE timestamp = %s
                    ORDER BY strike
                    """,
                    (latest_timestamp,),
                )
            
            rows = cursor.fetchall()
            
            if not rows:
                return None

            # Convert to JSON format matching the current UPC output
            # Column indices: 0-7 symbol..market_status, 8-20 strike..active_side, 21 momentum_percentile, 22-25 volatility, volatility_percentile, movement, movement_percentile
            raw_venue = rows[0][3]
            if self.unified_15m and raw_venue is not None and str(raw_venue).lower() == "kalshi":
                json_exchange = "Kalshi"
            else:
                json_exchange = raw_venue
            result = {
                "symbol": rows[0][0],
                "current_price": float(rows[0][1]),
                "ttc": rows[0][2],
                "exchange": json_exchange,
                "event_ticker": rows[0][4],
                "market_title": rows[0][5],
                "strike_tier": rows[0][6],
                "market_status": rows[0][7],
                "last_updated": latest_timestamp.isoformat(),
                "strikes": []
            }
            
            for row in rows:
                _sf = float(row[8]) if row[8] is not None else None
                _strike_out = (
                    int(_sf)
                    if _sf is not None and _sf == int(_sf)
                    else _sf
                )
                result["strikes"].append({
                    "strike": _strike_out,
                    "buffer": float(row[9]),
                    "buffer_pct": float(row[10]),
                    "probability": float(row[11]),
                    "yes_ask": float(row[12]) if row[12] is not None else None,
                    "no_ask": float(row[13]) if row[13] is not None else None,
                    "yes_ask_dollars": row[14],
                    "no_ask_dollars": row[15],
                    "yes_diff": float(row[16]) if row[16] is not None else None,
                    "no_diff": float(row[17]) if row[17] is not None else None,
                    "volume": int(row[18]) if row[18] is not None else None,
                    "ticker": row[19],
                    "active_side": row[20]
                })
            
            # Add momentum and market context (from first row; same for all strikes at this timestamp)
            result["momentum"] = {
                "percentile": float(rows[0][21]) if rows[0][21] is not None else None
            }
            result["volatility"] = float(rows[0][22]) if rows[0][22] is not None else None
            result["volatility_percentile"] = float(rows[0][23]) if rows[0][23] is not None else None
            result["movement"] = float(rows[0][24]) if rows[0][24] is not None else None
            result["movement_percentile"] = float(rows[0][25]) if rows[0][25] is not None else None
            
            return result
            
        except Exception as e:
            logger.error("Error getting latest strike table JSON: %s", e)
            return None
        finally:
            if conn:
                conn.close()

    def get_strike_table_consistency_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the consistency of the current strike table data.
        Returns None if no data exists, or a dict with consistency info.
        """
        conn = None
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            table_name = self._strike_table_name()
            if self.unified_15m:
                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) as total_records,
                        COUNT(DISTINCT timestamp) as unique_timestamps,
                        MIN(timestamp) as earliest_timestamp,
                        MAX(timestamp) as latest_timestamp,
                        MAX(timestamp) - MIN(timestamp) as time_span
                    FROM live_data.{table_name}
                    WHERE exchange = %s AND symbol = %s
                    """,
                    (self.data_exchange, self.symbol.upper()),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) as total_records,
                        COUNT(DISTINCT timestamp) as unique_timestamps,
                        MIN(timestamp) as earliest_timestamp,
                        MAX(timestamp) as latest_timestamp,
                        MAX(timestamp) - MIN(timestamp) as time_span
                    FROM live_data.{table_name}
                    """
                )
            result = cursor.fetchone()
            if not result or result[0] == 0:
                return None
            total_records, unique_timestamps, earliest, latest, time_span = result
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
            logger.error("Error checking strike table consistency: %s", e)
            return None
        finally:
            if conn:
                conn.close()

def run_continuous_generation(interval_seconds: int = 30, symbol: str = "btc", interval: str = "hourly"):
    """Run the strike table generator continuously."""
    logger.debug("Starting continuous strike table generation for %s (%s, interval: %ss)", symbol.upper(), interval, interval_seconds)
    generator = StrikeTableGenerator(symbol, interval=interval)
    generator.setup_live_data_schema()
    iteration = 0
    previous_event_ticker = None
    last_heartbeat = time.time()
    while True:
        try:
            iteration += 1
            logger.debug("Generation iteration %s", iteration)
            success, event_ticker, num_strikes = generator.generate_strike_table()
            if success:
                if previous_event_ticker is not None and previous_event_ticker != event_ticker:
                    logger.info(
                        "Strike table rotated: %s → %s (%s strikes)",
                        previous_event_ticker, event_ticker, num_strikes,
                    )
                previous_event_ticker = event_ticker
                try:
                    conn = get_postgresql_connection()
                    cursor = conn.cursor()
                    prob_col = "probability_15m" if generator.interval == "15m" else "probability_hourly"
                    cursor.execute(f"""
                    SELECT COUNT(*) as total_strikes, 
                           MIN({prob_col}) as min_prob, 
                           MAX({prob_col}) as max_prob,
                           AVG({prob_col}) as avg_prob
                    FROM live_data.{generator._strike_table_name()}
                    """)
                    result = cursor.fetchone()
                    if result:
                        total_strikes, min_prob, max_prob, avg_prob = result
                        logger.debug("Summary: %s strikes, Prob range: %s%%-%s%%, Avg: %s%%", total_strikes, min_prob, max_prob, avg_prob)
                    conn.close()
                except Exception as e:
                    logger.error("Error getting summary: %s", e)
            else:
                logger.error("Iteration %s failed", iteration)
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                logger.info("heartbeat")
                last_heartbeat = time.time()
            logger.debug("Waiting %s seconds before next generation", interval_seconds)
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.debug("Continuous generation stopped by user")
            break
        except Exception as e:
            logger.error("Error in continuous generation: %s", e, exc_info=True)
            logger.debug("Waiting 60 seconds before retry")
            time.sleep(60)


def run_master_15m_continuous(
    interval_seconds: int = 1,
    data_exchange: str = "kalshi",
    symbols: Optional[Tuple[str, ...]] = None,
) -> None:
    """One process: refresh strike_table_15m for each symbol in order; targets ~interval_seconds per full pass (sleep remainder)."""
    syms = tuple(s.upper() for s in (symbols or fetch_kalshi_15m_symbols_ordered_from_db()))
    if not syms:
        logger.error("run_master_15m_continuous: no symbols to process")
        return
    first = StrikeTableGenerator(
        syms[0].lower(),
        interval="15m",
        unified_15m=True,
        data_exchange=data_exchange,
    )
    first.setup_live_data_schema()
    prev_event: Dict[str, Optional[str]] = {s: None for s in syms}
    iteration = 0
    last_heartbeat = time.time()
    while True:
        loop_started = time.time()
        try:
            iteration += 1
            for sym in syms:
                g = StrikeTableGenerator(
                    sym.lower(),
                    interval="15m",
                    unified_15m=True,
                    data_exchange=data_exchange,
                )
                success, event_ticker, n = g.generate_strike_table()
                su = sym.upper()
                if success and event_ticker:
                    if prev_event[su] is not None and prev_event[su] != event_ticker:
                        logger.info(
                            "[%s] Strike table rotated: %s → %s (%s strikes)",
                            su,
                            prev_event[su],
                            event_ticker,
                            n,
                        )
                    prev_event[su] = event_ticker
                elif not success:
                    logger.error("[%s] Strike generation failed", su)
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                logger.info("heartbeat")
                last_heartbeat = time.time()
            slip = interval_seconds - (time.time() - loop_started)
            if slip > 0:
                time.sleep(slip)
        except KeyboardInterrupt:
            logger.debug("Master 15m continuous generation stopped by user")
            break
        except Exception as e:
            logger.error("Error in master 15m continuous generation: %s", e, exc_info=True)
            time.sleep(60)


def main():
    """Main function - choose between test mode and continuous mode."""
    parser = argparse.ArgumentParser(description='Strike Table Generator (Multi-Symbol)')
    parser.add_argument(
        '--master-15m',
        action='store_true',
        help='One process writes all 15m symbols to live_data.strike_table_15m (requires continuous mode and --interval 15m)',
    )
    parser.add_argument(
        '--data-exchange',
        default='kalshi',
        dest='data_exchange',
        help='Execution venue key for unified 15m rows (default: kalshi)',
    )
    parser.add_argument(
        '--data-broker',
        default=None,
        dest='data_broker_legacy',
        help='Deprecated: use --data-exchange',
    )
    parser.add_argument(
        '--symbols',
        nargs='*',
        default=None,
        help='With --master-15m, optional symbol list; default order from live_data.symbols_list',
    )
    parser.add_argument(
        '--master-interval-sec',
        type=int,
        default=1,
        help='Target seconds per full symbol pass (only with --master-15m; sleeps remainder after work; default 1, same as per-symbol continuous 1)',
    )
    parser.add_argument('symbol', nargs='?', help='Symbol (e.g., BTC); omit with --master-15m')
    parser.add_argument(
        'mode',
        nargs='?',
        help='Mode: test or continuous (omit with --master-15m; master is always continuous)',
    )
    parser.add_argument(
        'interval_sec',
        type=int,
        nargs='?',
        default=30,
        help='Seconds between generations (continuous mode, non-master)',
    )
    parser.add_argument(
        '--interval',
        choices=['hourly', '15m'],
        default='hourly',
        help='Market interval: hourly (default) or 15m (BTC, ETH, SOL, XRP)',
    )
    args = parser.parse_args()
    interval = args.interval
    _dex = args.data_broker_legacy if args.data_broker_legacy is not None else args.data_exchange
    data_exchange = (_dex or 'kalshi').strip().lower()

    if args.master_15m:
        if args.symbol:
            parser.error('Do not pass symbol when using --master-15m (use --symbols BTC ETH ... if needed)')
        if args.mode is not None:
            parser.error('Do not pass mode as a positional with --master-15m (master is always continuous)')
        if interval != '15m':
            parser.error('--master-15m requires --interval 15m')
        syms: Tuple[str, ...]
        if args.symbols:
            syms = tuple(s.strip().upper() for s in args.symbols if s and str(s).strip())
        else:
            syms = fetch_kalshi_15m_symbols_ordered_from_db()
        for s in syms:
            if s not in KALSHI_15M_SYMBOLS:
                parser.error('Invalid symbol %s for --master-15m (expected subset of BTC, ETH, SOL, XRP)' % s)
        run_master_15m_continuous(args.master_interval_sec, data_exchange, syms)
        return

    mode = args.mode
    interval_sec = args.interval_sec
    if mode is None:
        parser.error('mode is required: test or continuous')
    if not args.symbol:
        parser.error('symbol is required unless --master-15m')
    symbol = args.symbol.upper()
    if interval == '15m' and symbol.lower() not in ('btc', 'eth', 'sol', 'xrp'):
        parser.error('--interval 15m only supported for BTC, ETH, SOL, XRP')
    if mode == "continuous":
        run_continuous_generation(interval_sec, symbol, interval=interval)
    else:
        # Run in test mode
        logger.debug("Testing PostgreSQL Strike Table Generator for %s (%s)", symbol, interval)
        
        # Initialize generator
        generator = StrikeTableGenerator(symbol, interval=interval)
        
        # Setup schema
        generator.setup_live_data_schema()
        
        logger.debug("Generating test strike table")
        success, _event, _n = generator.generate_strike_table()
        if success:
            logger.debug("Strike table generation successful")
            
            # Test retrieval of strike table data
            logger.debug("Retrieving latest strike table data")
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            cursor.execute(f"""
            SELECT COUNT(*) as total_records, MAX(timestamp) as latest_update 
            FROM live_data.{generator._strike_table_name()}
            """)
            
            result = cursor.fetchone()
            if result:
                total_records, latest_update = result
                logger.debug("Strike table has %s records", total_records)
                logger.debug("Latest update: %s", latest_update)
                
                # Show sample strike table data
                prob_col = "probability_15m" if generator.interval == "15m" else "probability_hourly"
                cursor.execute(f"""
                SELECT strike, buffer, {prob_col}, yes_ask, no_ask, active_side 
                FROM live_data.{generator._strike_table_name()} 
                ORDER BY strike 
                LIMIT 5
                """)
                
                rows = cursor.fetchall()
                logger.debug("Sample strike table data")
                for row in rows:
                    strike, buffer, prob, yes_ask, no_ask, active_side = row
                    logger.debug("Strike $%s: %s%% | YES: %s | NO: %s | %s", f"{strike:,}", f"{prob:.2f}", yes_ask, no_ask, active_side.upper())
            else:
                logger.error("No strike table data found")
            
            conn.close()
        else:
            logger.error("Strike table generation failed")

if __name__ == "__main__":
    main()
