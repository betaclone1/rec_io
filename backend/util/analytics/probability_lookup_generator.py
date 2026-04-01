#!/usr/bin/env python3
"""
PROBABILITY LOOKUP TABLE GENERATOR

This script generates probability lookup tables containing pre-computed probability values
that match the live calculator's interpolation results exactly.

The lookup table will contain:
- ttc_seconds: Time to close in seconds (5-second increments)
- buffer_points: Distance from current price in points (10-point increments)
- momentum_bucket: Momentum percentile bucket (-99 to +99)
- prob_within_positive: Interpolated positive probability (within buffer)
- prob_within_negative: Interpolated negative probability (within buffer)

This allows the lookup calculator to return identical results to the live calculator
without performing interpolation calculations.

OPTIMIZED VERSION: Uses 5-second TTC increments and 10-point buffer increments
to dramatically reduce table size while maintaining acceptable precision.

CRITICAL FIXES APPLIED:
1. Fixed interpolation bug: Negative interpolation points now use correct negative move percentages
2. Standardized terminology: Changed from 'percentile_bucket' to 'momentum_percentile' throughout
3. Fixed table schema: Uses 'momentum_bucket' column name to match existing database
4. Removed hardcoded base price: Now uses dynamic buffer configuration for current price
5. Extended momentum range: Full -99 to +99 range instead of limited -30 to +30
6. Fixed parameter type consistency: buffer_step is consistently float type
"""

import os
import sys
import psycopg2
import logging
import numpy as np
from scipy.interpolate import griddata
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import argparse

# Add backend to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from backend.util.paths import get_data_dir
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ProbabilityLookupGenerator:
    """
    Probability Lookup Table Generator
    
    Generates probability lookup tables using the same methodology as the live calculator.
    OPTIMIZED VERSION: Uses 5-second TTC increments and 10-point buffer increments.
    
    FUTURE ENHANCEMENT - SYMBOL-SPECIFIC BUFFER CONFIGURATION:
    Currently uses fixed buffer range (0-2000 points) and increments (10 points) for all symbols.
    This should be made symbol-specific based on price range and volatility characteristics:
    
    Examples:
    - BTC ($120,000): Buffer 0-2000 points, 10-point increments (200 steps)
    - ETH ($4,000): Buffer 0-400 points, 2-point increments (200 steps) 
    - SOL ($100): Buffer 0-20 points, 0.5-point increments (40 steps)
    
    This would require:
    1. Symbol-specific buffer configuration (range, increments)
    2. Dynamic buffer step calculation based on symbol price
    3. Validation that buffer range covers typical price movements
    4. Configuration file or database table for symbol parameters
    
    Benefits:
    - More accurate interpolation for lower-priced symbols
    - Reduced table size for high-priced symbols
    - Better coverage of typical price movements per symbol
    """
    
    def __init__(self, symbol: str = "btc"):
        self.symbol = symbol.lower()
        self.db_config = merge_psycopg2_connect_kwargs(
            {
                "host": os.getenv("POSTGRES_HOST", "localhost"),
                "database": os.getenv("POSTGRES_DB", "rec_io_db"),
                "user": os.getenv("POSTGRES_USER", "rec_io_user"),
                "password": os.getenv("POSTGRES_PASSWORD", "rec_io_password"),
            }
        )
        
        # Table names
        self.master_table_name = None  # Will be set by main() function
        self.fingerprint_table_prefix = f"{self.symbol}_fingerprint"
        self.work_progress_schema = "work_progress"
        
        # Test mode table name will be set later if needed
        
        # Parallel processing settings
        self.max_workers = min(multiprocessing.cpu_count(), 6)  # Use up to 6 cores
        self.batch_size = 1000  # Batch size for database inserts
        
        logger.info(f"✅ Initialized probability lookup generator for {self.symbol.upper()}")
        logger.info(f"📊 Max workers: {self.max_workers}")

    def _is_low_price_symbol(self) -> bool:
        """Scoped carveout: only SOL/XRP use low-price buffer guards."""
        return self.symbol in {"sol", "xrp"}

    def _resolve_price_profile_table(self, cursor) -> str:
        """
        Prefer dated price profiles, fall back to base profile table.
        """
        cursor.execute(
            f"""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'analytics'
                  AND table_name LIKE '{self.symbol}_price_profile_%'
                ORDER BY table_name DESC
                LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row:
            return f"analytics.{row[0]}"

        base_table = f"{self.symbol}_price_profile"
        cursor.execute(
            """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'analytics'
                  AND table_name = %s
                LIMIT 1
            """,
            (base_table,),
        )
        if cursor.fetchone():
            return f"analytics.{base_table}"

        raise Exception(
            f"No price profile table found for {self.symbol} "
            f"(expected analytics.{self.symbol}_price_profile or dated suffix table)"
        )

    def _get_recent_market_buffer_width(self, cursor, current_price: float) -> Optional[float]:
        """
        Estimate required buffer coverage from recent 15m Kalshi strikes.
        Returns max absolute distance from recent strikes to current price.
        """
        table_name = f"market_kalshi_15m_{self.symbol}"
        cursor.execute(
            """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'live_data'
                  AND table_name = %s
                LIMIT 1
            """,
            (table_name,),
        )
        if not cursor.fetchone():
            return None

        cursor.execute(
            f"""
                SELECT strike
                FROM live_data.{table_name}
                WHERE strike IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT 200
            """
        )
        rows = cursor.fetchall()
        if not rows:
            return None

        distances = []
        for (strike_raw,) in rows:
            try:
                clean = str(strike_raw).replace("$", "").replace(",", "").strip()
                if not clean:
                    continue
                strike = float(clean)
                distances.append(abs(strike - current_price))
            except Exception:
                continue
        if not distances:
            return None
        return max(distances)
    
    def get_latest_symbol_price(self) -> float:
        """Get the latest price for the symbol (prefer live_data, fallback historical)."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            # Prefer the current live price so buffer sizing reflects recent regime.
            cursor.execute(
                f"""
                    SELECT price
                    FROM live_data.live_price_log_1s_{self.symbol}
                    ORDER BY timestamp DESC
                    LIMIT 1
                """
            )
            result = cursor.fetchone()
            if result and result[0] is not None:
                latest_price = float(result[0])
            else:
                cursor.execute(f"""
                    SELECT close 
                    FROM historical_data.{self.symbol}_price_history 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """)
                result = cursor.fetchone()
                if not result:
                    raise Exception(f"No price data found for {self.symbol}")
                latest_price = float(result[0])

            if self._is_low_price_symbol():
                logger.info(f"📊 Latest {self.symbol.upper()} price: ${latest_price:,.5f}")
            else:
                logger.info(f"📊 Latest {self.symbol.upper()} price: ${latest_price:,.2f}")
            
            return latest_price
            
        except Exception as e:
            logger.error(f"❌ Error getting latest price for {self.symbol}: {e}")
            raise
        finally:
            conn.close()
    
    def get_dynamic_buffer_config(self) -> Dict[str, float]:
        """Get dynamic buffer configuration based on symbol's price profile."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            price_profile_table = self._resolve_price_profile_table(cursor)

            # Get the 95-99th percentile price movement for extreme buffer sizing
            cursor.execute(f"""
                SELECT avg_price_change_pct 
                FROM {price_profile_table}
                WHERE range_name = '95-99'
            """)

            result = cursor.fetchone()
            if not result:
                raise Exception(f"No '95-99' range in price profile for {self.symbol}")

            extreme_movement_pct = float(result[0])

            # Get current price
            current_price = self.get_latest_symbol_price()

            # Default behavior (BTC/ETH legacy path) remains unchanged.
            buffer_width_pct = extreme_movement_pct
            buffer_width_usd = current_price * (buffer_width_pct / 100.0)
            target_steps = 200
            step_size_usd = buffer_width_usd / target_steps if buffer_width_usd > 0 else 0.0

            # SOL/XRP-only adaptive guard rails.
            if self._is_low_price_symbol():
                recent_market_width = self._get_recent_market_buffer_width(cursor, current_price)
                min_floor_usd = 0.05 if self.symbol == "xrp" else 0.25
                if recent_market_width is not None:
                    # Ensure lookup coverage reaches real listed strike distances with a small safety factor.
                    buffer_width_usd = max(buffer_width_usd, recent_market_width * 1.2, min_floor_usd)
                else:
                    buffer_width_usd = max(buffer_width_usd, min_floor_usd)

                # For low-priced assets, keep finer steps.
                step_floor = 0.0001
                step_size_usd = max(step_floor, buffer_width_usd / target_steps)
                # Keep table density bounded.
                est_steps = int(round(buffer_width_usd / step_size_usd)) if step_size_usd > 0 else 0
                if est_steps > 500:
                    step_size_usd = max(step_floor, buffer_width_usd / 500.0)
                elif est_steps < 100 and buffer_width_usd > 0:
                    step_size_usd = max(step_floor, buffer_width_usd / 100.0)

            step_size_pct = (step_size_usd / current_price * 100.0) if current_price else 0.0
            num_steps = int(buffer_width_usd / step_size_usd) if step_size_usd > 0 else 0

            config = {
                'current_price': current_price,
                'buffer_width_pct': buffer_width_pct,
                'buffer_width_usd': buffer_width_usd,
                'step_size_pct': step_size_pct,
                'step_size_usd': step_size_usd,
                'num_steps': num_steps
            }

            logger.info(f"📊 Dynamic buffer config for {self.symbol.upper()}:")
            logger.info(f"   Current price: ${current_price:,.5f}" if self._is_low_price_symbol() else f"   Current price: ${current_price:,.2f}")
            logger.info(f"   Buffer width: {buffer_width_pct:.2f}% (${buffer_width_usd:,.5f})" if self._is_low_price_symbol() else f"   Buffer width: {buffer_width_pct:.2f}% (${buffer_width_usd:,.2f})")
            logger.info(f"   Step size: {step_size_pct:.4f}% (${step_size_usd:,.5f})" if self._is_low_price_symbol() else f"   Step size: {step_size_pct:.4f}% (${step_size_usd:,.2f})")
            logger.info(f"   Number of steps: {config['num_steps']}")

            return config
            
        except Exception as e:
            logger.error(f"❌ Error getting dynamic buffer config for {self.symbol}: {e}")
            raise
        finally:
            conn.close()
    
    def get_available_momentum_percentiles(self) -> List[int]:
        """Get list of available momentum percentile buckets from PostgreSQL."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'analytics' 
            AND table_name LIKE %s
            ORDER BY table_name
            """
            
            cursor.execute(query, (f"{self.fingerprint_table_prefix}%",))
            tables = cursor.fetchall()
            
            percentiles = []
            for table in tables:
                table_name = table[0]
                # Extract momentum percentile from table name like "btc_fingerprint_00" or "btc_fingerprint_-99"
                percentile_str = table_name.replace(self.fingerprint_table_prefix, "")
                try:
                    percentile = int(percentile_str)
                    percentiles.append(percentile)
                except ValueError:
                    logger.warning(f"Could not parse momentum percentile from {table_name}")
                    continue
            
            logger.info(f"📊 Found {len(percentiles)} momentum percentiles: {min(percentiles)} to {max(percentiles)}")
            return percentiles
            
        except Exception as e:
            logger.error(f"❌ Error getting momentum percentiles: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def setup_work_progress_schema(self, ttc_range: Tuple[int, int], ttc_step: int):
        """Create work_progress schema and progress tracking table."""
        if not self.master_table_name:
            raise Exception("master_table_name must be set before calling setup_work_progress_schema")
        
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Create work_progress schema
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.work_progress_schema}")
            
            # Create SYMBOL-SPECIFIC progress tracking table
            progress_table_name = f"ttc_progress_{self.symbol}"
            progress_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.work_progress_schema}.{progress_table_name} (
                ttc_seconds INTEGER NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                rows_generated INTEGER DEFAULT 0,
                error_message TEXT,
                PRIMARY KEY (ttc_seconds)
            )
            """
            cursor.execute(progress_table_sql)
            
            # Initialize progress for all TTC values (using ttc_step increments)
            ttc_values = list(range(ttc_range[0], ttc_range[1] + 1, ttc_step))
            for ttc in ttc_values:
                cursor.execute(f"""
                INSERT INTO {self.work_progress_schema}.{progress_table_name} (ttc_seconds, status)
                VALUES (%s, 'pending')
                ON CONFLICT (ttc_seconds) DO NOTHING
                """, (ttc,))
            
            conn.commit()
            logger.info(f"✅ Work progress schema setup complete for {len(ttc_values)} TTC values in {progress_table_name}")
            
        except Exception as e:
            logger.error(f"❌ Error setting up work progress schema: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def get_pending_ttc_values(self) -> List[int]:
        """Get list of TTC values that need processing for the current symbol."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            progress_table_name = f"ttc_progress_{self.symbol}"
            cursor.execute(f"""
            SELECT ttc_seconds FROM {self.work_progress_schema}.{progress_table_name}
            WHERE status IN ('pending', 'failed')
            ORDER BY ttc_seconds
            """)
            
            pending_ttc = [row[0] for row in cursor.fetchall()]
            logger.info(f"📊 Found {len(pending_ttc)} pending TTC values for {self.symbol}")
            return pending_ttc
            
        except Exception as e:
            logger.error(f"❌ Error getting pending TTC values: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def update_ttc_status(self, ttc_seconds: int, status: str, rows_generated: int = 0, error_message: str = None):
        """Update the status of a TTC value in the progress table."""
        conn = None
        try:
            # Create a fresh connection for each thread
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            progress_table_name = f"ttc_progress_{self.symbol}"
            if status == 'processing':
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.{progress_table_name}
                SET status = %s, started_at = CURRENT_TIMESTAMP
                WHERE ttc_seconds = %s
                """, (status, ttc_seconds))
            elif status == 'completed':
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.{progress_table_name}
                SET status = %s, completed_at = CURRENT_TIMESTAMP, rows_generated = %s
                WHERE ttc_seconds = %s
                """, (status, rows_generated, ttc_seconds))
            elif status == 'failed':
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.{progress_table_name}
                SET status = %s, error_message = %s
                WHERE ttc_seconds = %s
                """, (status, error_message, ttc_seconds))
            
            # Verify the update actually happened
            rows_affected = cursor.rowcount
            if rows_affected == 0:
                logger.warning(f"⚠️ No rows updated for TTC {ttc_seconds} status {status}")
            
            conn.commit()
            logger.debug(f"✅ Updated TTC {ttc_seconds} status to {status} (rows affected: {rows_affected})")
            
        except Exception as e:
            logger.error(f"❌ Error updating TTC {ttc_seconds} status to {status}: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()
    
    def get_progress_stats(self) -> Dict:
        """Get progress statistics for the current lookup table generation."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            progress_table_name = f"ttc_progress_{self.symbol}"
            cursor.execute(f"""
            SELECT 
                status,
                COUNT(*) as count,
                SUM(rows_generated) as total_rows
            FROM {self.work_progress_schema}.{progress_table_name}
            GROUP BY status
            """)
            
            stats = {}
            total_ttc = 0
            total_rows = 0
            
            for row in cursor.fetchall():
                status, count, rows = row
                stats[status] = {
                    'count': count,
                    'rows': rows or 0
                }
                total_ttc += count
                total_rows += rows or 0
            
            # Calculate percentages
            if total_ttc > 0:
                stats['summary'] = {
                    'total_ttc_values': total_ttc,
                    'total_rows_generated': total_rows,
                    'completed_pct': (stats.get('completed', {}).get('count', 0) / total_ttc) * 100,
                    'pending_pct': (stats.get('pending', {}).get('count', 0) / total_ttc) * 100,
                    'failed_pct': (stats.get('failed', {}).get('count', 0) / total_ttc) * 100
                }
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Error getting progress stats: {e}")
            return {}
        finally:
            if conn:
                conn.close()
    
    def reset_progress(self):
        """Reset all progress to pending status (for fresh start)."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            progress_table_name = f"ttc_progress_{self.symbol}"
            cursor.execute(f"""
            UPDATE {self.work_progress_schema}.{progress_table_name}
            SET status = 'pending', started_at = NULL, completed_at = NULL, 
                rows_generated = 0, error_message = NULL
            """)
            
            conn.commit()
            logger.info(f"✅ Progress reset - all TTC values marked as pending for {self.symbol}")
            
        except Exception as e:
            logger.error(f"❌ Error resetting progress: {e}")
        finally:
            if conn:
                conn.close()
    
    def load_fingerprint_data(self, momentum_percentile: int) -> Dict:
        """Load fingerprint data for a specific momentum percentile bucket."""
        try:
            conn = psycopg2.connect(**self.db_config)
            
            # The momentum_percentile parameter is now the actual bucket value (e.g., -90, -80, 10, 20)
            # Format table name correctly for bucketed tables
            if momentum_percentile < 0:
                table_name = f"{self.fingerprint_table_prefix}_{momentum_percentile:03d}"  # e.g., btc_fingerprint_-90
            else:
                table_name = f"{self.fingerprint_table_prefix}_{momentum_percentile:02d}"  # e.g., btc_fingerprint_10
            
            # Get all data from the fingerprint table
            query = f'SELECT * FROM analytics."{table_name}" ORDER BY time_to_close'
            
            df = pd.read_sql_query(query, conn)
            
            # Parse TTC values (convert "Xm TTC" to seconds)
            ttc_values = []
            for ttc_str in df['time_to_close']:
                if 'm TTC' in ttc_str:
                    minutes = int(ttc_str.split('m')[0])
                    ttc_values.append(minutes * 60)  # Convert to seconds
                else:
                    ttc_values.append(0)
            
            # Parse move percentages and separate positive/negative
            positive_move_percentages = []
            negative_move_percentages = []
            positive_columns = []
            negative_columns = []
            
            for col in df.columns:
                if col == 'time_to_close':
                    continue
                if col.startswith('pos_'):
                    # Extract percentage from column name like "pos_0_20"
                    percent_str = col.replace('pos_', '').replace('_', '.')
                    percent = float(percent_str)
                    positive_move_percentages.append(percent)
                    positive_columns.append(col)
                elif col.startswith('neg_'):
                    # Extract percentage from column name like "neg_0_20"
                    percent_str = col.replace('neg_', '').replace('_', '.')
                    percent = float(percent_str)
                    negative_move_percentages.append(percent)
                    negative_columns.append(col)
            
            # Sort the TTC values and move percentages along with the data matrix
            ttc_sorted_indices = np.argsort(ttc_values)
            positive_sorted_indices = np.argsort(positive_move_percentages)
            negative_sorted_indices = np.argsort(negative_move_percentages)
            
            ttc_values = np.array(ttc_values)[ttc_sorted_indices]
            positive_move_percentages = np.array(positive_move_percentages)[positive_sorted_indices]
            negative_move_percentages = np.array(negative_move_percentages)[negative_sorted_indices]
            
            # Extract positive and negative probability matrices
            positive_data = df[positive_columns].values
            negative_data = df[negative_columns].values
            
            # Sort the data manually to avoid numpy indexing issues
            positive_probability_matrix = np.zeros((len(ttc_sorted_indices), len(positive_sorted_indices)))
            negative_probability_matrix = np.zeros((len(ttc_sorted_indices), len(negative_sorted_indices)))
            
            for i, ttc_idx in enumerate(ttc_sorted_indices):
                for j, pos_idx in enumerate(positive_sorted_indices):
                    positive_probability_matrix[i, j] = float(positive_data[ttc_idx][pos_idx])
                for j, neg_idx in enumerate(negative_sorted_indices):
                    negative_probability_matrix[i, j] = float(negative_data[ttc_idx][neg_idx])
            
            # Create interpolation points for positive and negative - FIXED: Use correct move percentages
            positive_interp_points = []
            positive_interp_values = []
            negative_interp_points = []
            negative_interp_values = []
            
            for i, ttc in enumerate(ttc_values):
                for j, move_pct in enumerate(positive_move_percentages):
                    positive_interp_points.append([ttc, move_pct])
                    positive_interp_values.append(positive_probability_matrix[i, j])
                
                for j, move_pct in enumerate(negative_move_percentages):
                    negative_interp_points.append([ttc, move_pct])
                    negative_interp_values.append(negative_probability_matrix[i, j])
            
            positive_interp_points = np.array(positive_interp_points)
            positive_interp_values = np.array(positive_interp_values)
            negative_interp_points = np.array(negative_interp_points)
            negative_interp_values = np.array(negative_interp_values)
            
            fingerprint_data = {
                'ttc_values': ttc_values,
                'positive_move_percentages': positive_move_percentages,
                'negative_move_percentages': negative_move_percentages,
                'positive_interp_points': positive_interp_points,
                'positive_interp_values': positive_interp_values,
                'negative_interp_points': negative_interp_points,
                'negative_interp_values': negative_interp_values
            }
            
            logger.info(f"📊 Loaded fingerprint data for momentum percentile {momentum_percentile}")
            logger.info(f"   TTC range: {min(ttc_values)}s to {max(ttc_values)}s")
            logger.info(f"   Positive move range: {min(positive_move_percentages):.2f}% to {max(positive_move_percentages):.2f}%")
            logger.info(f"   Negative move range: {min(negative_move_percentages):.2f}% to {max(negative_move_percentages):.2f}%")
            
            return fingerprint_data
            
        except Exception as e:
            logger.error(f"❌ Error loading fingerprint data for momentum percentile {momentum_percentile}: {e}")
            return None
        finally:
            if conn:
                conn.close()
    
    def interpolate_probabilities(self, fingerprint_data: Dict, ttc_seconds: float, move_percent: float) -> Tuple[float, float]:
        """
        Interpolate both positive and negative probabilities using the same method as the live calculator.
        
        Args:
            fingerprint_data: Loaded fingerprint data
            ttc_seconds: Time to close in seconds
            move_percent: Move percentage (e.g., 0.5 for 0.5%)
            
        Returns:
            Tuple of (prob_within_positive, prob_within_negative)
        """
        try:
            ttc_values = fingerprint_data['ttc_values']
            positive_interp_points = fingerprint_data['positive_interp_points']
            positive_interp_values = fingerprint_data['positive_interp_values']
            negative_interp_points = fingerprint_data['negative_interp_points']
            negative_interp_values = fingerprint_data['negative_interp_values']
            
            # Clamp TTC to valid range
            ttc_seconds = max(ttc_values[0], min(ttc_seconds, ttc_values[-1]))
            
            # Clamp move percentage to max fingerprint range
            max_move = max(fingerprint_data['positive_move_percentages'])
            move_percent = min(move_percent, max_move)
            
            point = np.array([[ttc_seconds, move_percent]])
            
            try:
                pos_prob = griddata(positive_interp_points, positive_interp_values, point, method='linear')[0]
                neg_prob = griddata(negative_interp_points, negative_interp_values, point, method='linear')[0]
            except:
                pos_prob = griddata(positive_interp_points, positive_interp_values, point, method='nearest')[0]
                neg_prob = griddata(negative_interp_points, negative_interp_values, point, method='nearest')[0]
            
            # Calculate prob_within for both directions
            # prob_within = 100 - prob_beyond
            prob_within_positive = 100.0 - pos_prob
            prob_within_negative = 100.0 - neg_prob
            
            return float(prob_within_positive), float(prob_within_negative)
            
        except Exception as e:
            logger.error(f"❌ Error interpolating probabilities: {e}")
            return 0.0, 0.0
    
    def create_master_table(self, ttc_range: Tuple[int, int], buffer_range: Tuple[int, int], 
                          momentum_percentiles: List[int], ttc_step: int = 10, buffer_step: int = 10):
        """
        Create the master probability lookup table.
        
        Args:
            ttc_range: (min_ttc_seconds, max_ttc_seconds)
            buffer_range: (min_buffer_points, max_buffer_points)
            momentum_percentiles: List of momentum percentile buckets to include
            ttc_step: Step size for TTC in seconds (default: 5 seconds)
            buffer_step: Step size for buffer in points (default: 10 points)
        """
        try:
            logger.info(f"🚀 Creating incremental master probability table")
            logger.info(f"📊 TTC range: {ttc_range[0]}s to {ttc_range[1]}s (step: {ttc_step}s)")
            logger.info(f"📊 Buffer range: {buffer_range[0]} to {buffer_range[1]} points (step: {buffer_step})")
            logger.info(f"📊 Momentum percentiles: {momentum_percentiles}")
            
            # Calculate total combinations
            ttc_count = (ttc_range[1] - ttc_range[0]) // ttc_step + 1
            buffer_count = (buffer_range[1] - buffer_range[0]) // buffer_step + 1
            total_combinations = ttc_count * buffer_count * len(momentum_percentiles)
            

            logger.info(f"📊 Total combinations to generate: {total_combinations:,}")
            
            # Create table
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # NEVER drop existing tables - only create new verification tables
            logger.info(f"🆕 Creating new verification table: analytics.{self.master_table_name}")
            
            # Create table
            create_table_sql = f"""
            CREATE TABLE analytics.{self.master_table_name} (
                ttc_seconds INTEGER NOT NULL,
                buffer_points INTEGER NOT NULL,
                momentum_bucket INTEGER NOT NULL,
                prob_within_positive NUMERIC(5,2) NOT NULL,
                prob_within_negative NUMERIC(5,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ttc_seconds, buffer_points, momentum_bucket)
            )
            """
            cursor.execute(create_table_sql)
            
            # Load fingerprint data for all percentile buckets
            fingerprint_data_cache = {}
            for momentum_percentile in momentum_percentiles:
                fingerprint_data = self.load_fingerprint_data(momentum_percentile)
                if fingerprint_data:
                    fingerprint_data_cache[momentum_percentile] = fingerprint_data
                else:
                    logger.warning(f"⚠️ Skipping percentile bucket {momentum_percentile} - no data")
            
            if not fingerprint_data_cache:
                raise ValueError("No fingerprint data available for any percentile bucket")
            
            # Generate all combinations
            total_generated = 0
            start_time = time.time()
            
            for ttc_seconds in range(ttc_range[0], ttc_range[1] + 1, ttc_step):
                for buffer_points in range(buffer_range[0], buffer_range[1] + 1, buffer_step):
                    for momentum_percentile in momentum_percentiles:
                        if momentum_percentile not in fingerprint_data_cache:
                            continue
                        
                        # Calculate move percentage using dynamic buffer configuration
                        buffer_config = self.get_dynamic_buffer_config()
                        current_price = buffer_config['current_price']
                        move_percent = (buffer_points / current_price) * 100
                        
                        # Interpolate both positive and negative probabilities
                        prob_within_positive, prob_within_negative = self.interpolate_probabilities(
                            fingerprint_data_cache[momentum_percentile], ttc_seconds, move_percent
                        )
                        
                        # Insert into table
                        insert_sql = f"""
                        INSERT INTO analytics.{self.master_table_name} 
                        (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(insert_sql, (ttc_seconds, buffer_points, momentum_percentile, prob_within_positive, prob_within_negative))
                        
                        total_generated += 1
                        
                        # Progress update every 1000 combinations
                        if total_generated % 1000 == 0:
                            elapsed = time.time() - start_time
                            rate = total_generated / elapsed
                            remaining = (total_combinations - total_generated) / rate if rate > 0 else 0
                            logger.info(f"📊 Generated {total_generated:,}/{total_combinations:,} combinations "
                                      f"({total_generated/total_combinations*100:.1f}%) "
                                      f"Rate: {rate:.0f}/s, ETA: {remaining/60:.1f}min")
            
            # Commit and create index
            conn.commit()
            
            # Create index for faster lookups
            index_sql = f"""
            CREATE INDEX idx_{self.master_table_name}_lookup 
            ON analytics.{self.master_table_name} (ttc_seconds, buffer_points, momentum_bucket)
            """
            cursor.execute(index_sql)
            conn.commit()
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Incremental master table created successfully!")
            logger.info(f"📊 Total combinations generated: {total_generated:,}")
            logger.info(f"📊 Total time: {elapsed/60:.1f} minutes")
            logger.info(f"📊 Average rate: {total_generated/elapsed:.0f} combinations/second")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error creating incremental master table: {e}")
            return False
        finally:
            if conn:
                conn.close()
    
    def process_ttc_value(self, ttc_seconds: int, buffer_range: Tuple[int, int], 
                         momentum_percentiles: List[int], buffer_step: float, 
                         fingerprint_data_cache: Dict) -> int:
        """
        Process a single TTC value and generate all combinations for it.
        
        Returns:
            Number of combinations generated for this TTC value
        """
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            rows_generated = 0
            
            # Generate all buffer and momentum combinations for this TTC
            buffer_points_list = []
            current_buffer = buffer_range[0]
            while current_buffer <= buffer_range[1]:
                buffer_points_list.append(float(current_buffer))
                current_buffer += buffer_step
            
            # Get dynamic buffer configuration for current price
            buffer_config = self.get_dynamic_buffer_config()
            current_price = buffer_config['current_price']
            
            for buffer_points in buffer_points_list:
                for momentum_percentile in momentum_percentiles:
                    if momentum_percentile not in fingerprint_data_cache:
                        continue
                    
                    # Calculate move percentage using dynamic buffer configuration
                    move_percent = (buffer_points / current_price) * 100
                    
                    # Interpolate both positive and negative probabilities
                    prob_within_positive, prob_within_negative = self.interpolate_probabilities(
                        fingerprint_data_cache[momentum_percentile], ttc_seconds, move_percent
                    )
                    
                    # Insert into table
                    insert_sql = f"""
                    INSERT INTO analytics.{self.master_table_name} 
                    (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (ttc_seconds, buffer_points, momentum_bucket) DO NOTHING
                    """
                    cursor.execute(insert_sql, (ttc_seconds, buffer_points, momentum_percentile, prob_within_positive, prob_within_negative))
                    
                    rows_generated += 1
            
            conn.commit()
            return rows_generated
            
        except Exception as e:
            logger.error(f"❌ Error processing TTC {ttc_seconds}: {e}")
            return 0
        finally:
            if conn:
                conn.close()
    
    def create_master_table_batched(self, ttc_range: Tuple[int, int], buffer_range: Tuple[int, int], 
                                  momentum_percentiles: List[int], ttc_step: int = 10, buffer_step: float = 10.0):
        """
        Create the master probability lookup table using batched processing with resume capability.
        """
        try:
            logger.info(f"🚀 Creating incremental master probability table (batched)")
            logger.info(f"📊 TTC range: {ttc_range[0]}s to {ttc_range[1]}s (step: {ttc_step}s)")
            logger.info(f"📊 Buffer range: {buffer_range[0]} to {buffer_range[1]} points (step: {buffer_step})")
            logger.info(f"📊 Momentum percentiles: {momentum_percentiles}")
            
            # Setup work progress tracking
            logger.info("📊 Setting up work progress tracking...")
            self.setup_work_progress_schema(ttc_range, ttc_step)
            
            # Get pending TTC values (resume capability)
            pending_ttc_values = self.get_pending_ttc_values()
            
            # Fix any stuck processing values before starting
            stuck_count = self.fix_stuck_processing_values()
            if stuck_count > 0:
                # Re-get pending values after fixing stuck ones
                pending_ttc_values = self.get_pending_ttc_values()
            
            if not pending_ttc_values:
                logger.info("✅ All TTC values already completed!")
                # Check if the table actually exists before returning True
                conn = psycopg2.connect(**self.db_config)
                cursor = conn.cursor()
                cursor.execute(f"""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'analytics' 
                    AND table_name = %s
                )
                """, (self.master_table_name,))
                table_exists = cursor.fetchone()[0]
                conn.close()
                
                if table_exists:
                    logger.info(f"✅ Table {self.master_table_name} already exists - skipping generation")
                    return True
                else:
                    logger.warning(f"⚠️ No pending TTC values but table {self.master_table_name} doesn't exist - will create new table")
                    # Continue with table creation
            
            logger.info(f"📊 Found {len(pending_ttc_values)} pending TTC values to process")
            
            # Create the lookup table
            # Create a new timestamped table for verification before replacing master
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # NEVER touch existing tables - only create new verification tables
            logger.info(f"🆕 Creating new verification table: analytics.{self.master_table_name}")
            
            # Check if verification table already exists (should not happen)
            cursor.execute(f"""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name = %s
            )
            """, (self.master_table_name,))
            
            if cursor.fetchone()[0]:
                raise Exception(f"CRITICAL ERROR: Verification table {self.master_table_name} already exists! This should never happen.")
            
            create_table_sql = f"""
            CREATE TABLE analytics.{self.master_table_name} (
                ttc_seconds INTEGER NOT NULL,
                buffer_points NUMERIC(10,4) NOT NULL,
                momentum_bucket INTEGER NOT NULL,
                prob_within_positive NUMERIC(5,2) NOT NULL,
                prob_within_negative NUMERIC(5,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ttc_seconds, buffer_points, momentum_bucket)
            )
            """
            cursor.execute(create_table_sql)
            logger.info(f"✅ Created new verification table: analytics.{self.master_table_name}")
            logger.info(f"📋 After verification, you can rename this to replace the master table")
            conn.commit()
            conn.close()
            
            # Load fingerprint data for all momentum percentiles
            fingerprint_data_cache = {}
            for momentum_percentile in momentum_percentiles:
                fingerprint_data = self.load_fingerprint_data(momentum_percentile)
                if fingerprint_data:
                    fingerprint_data_cache[momentum_percentile] = fingerprint_data
                else:
                    logger.warning(f"⚠️ Skipping momentum percentile {momentum_percentile} - no data")
            
            if not fingerprint_data_cache:
                raise ValueError("No fingerprint data available for any momentum percentile")
            
            logger.info(f"📊 Processing {len(pending_ttc_values)} pending TTC values...")
            
            # Process TTC values with progress tracking
            total_generated = 0
            start_time = time.time()
            
            def process_ttc_with_tracking(ttc_seconds):
                try:
                    # Mark as processing
                    self.update_ttc_status(ttc_seconds, 'processing')
                    
                    # Process this TTC value
                    rows_generated = self.process_ttc_value(
                        ttc_seconds, buffer_range, momentum_percentiles, buffer_step, fingerprint_data_cache
                    )
                    
                    # Mark as completed
                    self.update_ttc_status(ttc_seconds, 'completed', rows_generated)
                    
                    elapsed = time.time() - start_time
                    logger.info(f"✅ TTC {ttc_seconds}s completed: {rows_generated:,} combinations in {elapsed/60:.1f}min")
                    
                    return rows_generated
                    
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"❌ Error processing TTC {ttc_seconds}: {error_msg}")
                    self.update_ttc_status(ttc_seconds, 'failed', error_message=error_msg)
                    return 0
            
            # Use ThreadPoolExecutor for parallel processing
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(process_ttc_with_tracking, ttc) for ttc in pending_ttc_values]
                
                for future in futures:
                    try:
                        rows_generated = future.result()
                        total_generated += rows_generated
                    except Exception as e:
                        logger.error(f"❌ Error in parallel processing: {e}")
                        continue
            
            # Create index for faster lookups
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            index_sql = f"""
            CREATE INDEX IF NOT EXISTS idx_{self.master_table_name}_lookup 
            ON analytics.{self.master_table_name} (ttc_seconds, buffer_points, momentum_bucket)
            """
            cursor.execute(index_sql)
            conn.commit()
            conn.close()
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Incremental master table created successfully!")
            logger.info(f"📊 Total combinations generated: {total_generated:,}")
            logger.info(f"📊 Total time: {elapsed/60:.1f} minutes")
            logger.info(f"📊 Average rate: {total_generated/elapsed:.0f} combinations/second")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error creating incremental master table: {e}")
            return False

    def fix_stuck_processing_values(self):
        """Detect and fix TTC values stuck in 'processing' status."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            progress_table_name = f"ttc_progress_{self.symbol}"
            # Find TTC values stuck in processing for more than 1 hour
            cursor.execute(f"""
            SELECT ttc_seconds 
            FROM {self.work_progress_schema}.{progress_table_name}
            WHERE status = 'processing' 
            AND started_at < NOW() - INTERVAL '1 hour'
            """)
            
            stuck_values = [row[0] for row in cursor.fetchall()]
            
            if stuck_values:
                logger.warning(f"⚠️ Found {len(stuck_values)} TTC values stuck in processing status for {self.symbol}")
                logger.warning(f"⚠️   Stuck TTC values: {stuck_values}")
                
                # Reset them to pending
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.{progress_table_name}
                SET status = 'pending', started_at = NULL, completed_at = NULL, 
                    rows_generated = 0, error_message = NULL
                WHERE ttc_seconds = ANY(%s)
                """, (stuck_values,))
                
                rows_affected = cursor.rowcount
                conn.commit()
                logger.info(f"✅ Reset {rows_affected} stuck TTC values to pending status")
            
            conn.close()
            return len(stuck_values)
            
        except Exception as e:
            logger.error(f"❌ Error fixing stuck processing values: {e}")
            return 0

    def migrate_progress_table_schema(self):
        """Migrate existing progress table to support symbol-specific tracking."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Check if table_name column exists
            cursor.execute(f"""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = '{self.work_progress_schema}' 
            AND table_name = 'ttc_progress_incremental' 
            AND column_name = 'table_name'
            """)
            
            has_table_name_column = cursor.fetchone() is not None
            
            # Check current primary key
            cursor.execute(f"""
            SELECT constraint_name FROM information_schema.table_constraints 
            WHERE table_schema = '{self.work_progress_schema}' 
            AND table_name = 'ttc_progress_incremental' 
            AND constraint_type = 'PRIMARY KEY'
            """)
            
            pk_constraint = cursor.fetchone()
            
            if not has_table_name_column:
                logger.info("🔄 Adding table_name column...")
                cursor.execute(f"""
                ALTER TABLE {self.work_progress_schema}.ttc_progress_incremental 
                ADD COLUMN table_name VARCHAR(100)
                """)
                
                # Update existing records with the current symbol's table name
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.ttc_progress_incremental 
                SET table_name = %s 
                WHERE table_name IS NULL
                """, (self.master_table_name,))
            
            # Check if we need to update the primary key
            if pk_constraint:
                cursor.execute(f"""
                SELECT column_name FROM information_schema.key_column_usage 
                WHERE table_schema = '{self.work_progress_schema}' 
                AND table_name = 'ttc_progress_incremental' 
                AND constraint_name = %s
                ORDER BY ordinal_position
                """, (pk_constraint[0],))
                
                pk_columns = [row[0] for row in cursor.fetchall()]
                
                if pk_columns != ['ttc_seconds', 'table_name']:
                    logger.info("🔄 Updating primary key to composite (ttc_seconds, table_name)...")
                    
                    # Drop old primary key
                    cursor.execute(f"""
                    ALTER TABLE {self.work_progress_schema}.ttc_progress_incremental 
                    DROP CONSTRAINT {pk_constraint[0]}
                    """)
                    
                    # Add new composite primary key
                    cursor.execute(f"""
                    ALTER TABLE {self.work_progress_schema}.ttc_progress_incremental 
                    ADD PRIMARY KEY (ttc_seconds, table_name)
                    """)
            
            conn.commit()
            logger.info("✅ Progress table migration completed")
            
            conn.close()
            
        except Exception as e:
            logger.error(f"❌ Error migrating progress table: {e}")
            if conn:
                conn.rollback()
                conn.close()

    def run_comprehensive_test(self, symbol: str) -> bool:
        """
        Run a comprehensive test that validates the entire system in under 10 minutes.
        This test ensures data integrity and proper table creation.
        """
        logger.info(f"🧪 Starting comprehensive test for {symbol.upper()}")
        
        try:
            # Test 1: Verify fingerprint data exists
            logger.info("📊 Test 1: Verifying fingerprint data...")
            fingerprint_count = 0
            for percentile in range(-10, 11):  # Test range -10 to +10
                data = self.load_fingerprint_data(percentile)
                if data is not None and len(data) > 0:
                    fingerprint_count += 1
            
            if fingerprint_count < 15:  # Should have at least 15 fingerprint tables
                raise Exception(f"❌ Test 1 FAILED: Only {fingerprint_count} fingerprint tables found")
            logger.info(f"✅ Test 1 PASSED: {fingerprint_count} fingerprint tables verified")
            
            # Test 2: Verify buffer configuration
            logger.info("📊 Test 2: Verifying buffer configuration...")
            buffer_config = self.get_dynamic_buffer_config()
            required_keys = ['current_price', 'buffer_width_usd', 'step_size_usd', 'num_steps']
            for key in required_keys:
                if key not in buffer_config:
                    raise Exception(f"❌ Test 2 FAILED: Missing buffer config key: {key}")
                if buffer_config[key] <= 0:
                    raise Exception(f"❌ Test 2 FAILED: Invalid buffer config value for {key}: {buffer_config[key]}")
            logger.info(f"✅ Test 2 PASSED: Buffer configuration verified")
            
            # Test 3: Create small verification table (5 TTC values, 5 buffer steps, 5 momentum percentiles)
            logger.info("📊 Test 3: Creating small verification table...")
            test_table_name = f"test_verification_{symbol}_{int(time.time())}"
            
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Create test table
            create_sql = f"""
            CREATE TABLE analytics.{test_table_name} (
                ttc_seconds INTEGER NOT NULL,
                buffer_points NUMERIC(10,4) NOT NULL,
                momentum_bucket INTEGER NOT NULL,
                prob_within_positive NUMERIC(5,2) NOT NULL,
                prob_within_negative NUMERIC(5,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ttc_seconds, buffer_points, momentum_bucket)
            )
            """
            cursor.execute(create_sql)
            
            # Generate test data (5x5x5 = 125 combinations)
            test_ttc_values = [0, 60, 120, 180, 240]
            test_buffer_steps = [0, 10, 20, 30, 40]
            test_momentum_percentiles = [-10, -5, 0, 5, 10]
            
            rows_generated = 0
            for ttc in test_ttc_values:
                for buffer in test_buffer_steps:
                    for momentum in test_momentum_percentiles:
                        # Load fingerprint data for this momentum percentile
                        fingerprint_data = self.load_fingerprint_data(momentum)
                        if fingerprint_data is None:
                            continue
                        
                        # Calculate move percentage
                        current_price = buffer_config['current_price']
                        move_percent = (buffer / current_price) * 100
                        
                        # Interpolate probabilities
                        prob_positive, prob_negative = self.interpolate_probabilities(
                            fingerprint_data, ttc, move_percent
                        )
                        
                        # Insert test data
                        insert_sql = f"""
                        INSERT INTO analytics.{test_table_name} 
                        (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(insert_sql, (ttc, buffer, momentum, prob_positive, prob_negative))
                        rows_generated += 1
            
            conn.commit()
            
            # Verify test table data
            cursor.execute(f"SELECT COUNT(*) FROM analytics.{test_table_name}")
            actual_rows = cursor.fetchone()[0]
            
            if actual_rows < 100:  # Should have at least 100 rows
                raise Exception(f"❌ Test 3 FAILED: Only {actual_rows} rows generated, expected ~125")
            
            # Verify data integrity
            cursor.execute(f"""
            SELECT COUNT(DISTINCT ttc_seconds) as ttc_count,
                   COUNT(DISTINCT buffer_points) as buffer_count,
                   COUNT(DISTINCT momentum_bucket) as momentum_count
            FROM analytics.{test_table_name}
            """)
            counts = cursor.fetchone()
            
            if counts[0] < 4 or counts[1] < 4 or counts[2] < 4:
                raise Exception(f"❌ Test 3 FAILED: Insufficient data diversity: TTC={counts[0]}, Buffer={counts[1]}, Momentum={counts[2]}")
            
            logger.info(f"✅ Test 3 PASSED: Generated {actual_rows} test rows with proper data diversity")
            
            # Test 4: Verify no main table was touched
            logger.info("📊 Test 4: Verifying main table protection...")
            main_table_name = f"probability_lookup_{symbol.lower()}"
            cursor.execute(f"""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name = %s
            )
            """, (main_table_name,))
            
            if not cursor.fetchone()[0]:
                raise Exception(f"❌ Test 4 FAILED: Main table {main_table_name} was destroyed!")
            
            # Check main table row count hasn't changed significantly
            cursor.execute(f"SELECT COUNT(*) FROM analytics.{main_table_name}")
            main_table_rows = cursor.fetchone()[0]
            
            if main_table_rows < 1000000:  # Main table should have substantial data
                raise Exception(f"❌ Test 4 FAILED: Main table has suspiciously low row count: {main_table_rows}")
            
            logger.info(f"✅ Test 4 PASSED: Main table protected, {main_table_rows:,} rows intact")
            
            # Clean up test table
            cursor.execute(f"DROP TABLE analytics.{test_table_name}")
            conn.commit()
            conn.close()
            
            logger.info(f"🎉 ALL TESTS PASSED for {symbol.upper()}!")
            logger.info(f"✅ System is ready for production use")
            return True
            
        except Exception as e:
            logger.error(f"❌ Test FAILED: {e}")
            return False


def main():
    """Main function to run the incremental master table generator."""
    parser = argparse.ArgumentParser(description='Generate probability lookup tables with dynamic buffer sizing')
    parser.add_argument('symbols', nargs='+', help='Symbols to process (e.g., btc eth)')
    parser.add_argument('--test', action='store_true', help='Run in test mode with reduced data range')
    parser.add_argument('--comprehensive-test', action='store_true', help='Run comprehensive system test (under 10 minutes)')
    parser.add_argument('--reset-progress', action='store_true', help='Reset all progress and start fresh')
    parser.add_argument('--ttc-range', nargs=2, type=int, help='TTC range in seconds (e.g., 60 300)')
    parser.add_argument('--buffer-limit', type=int, help='Maximum buffer points (e.g., 200)')
    parser.add_argument('--momentum-range', nargs=2, type=int, help='Momentum percentile range (e.g., -10 10)')
    args = parser.parse_args()
    
    logger.info("🚀 Starting Incremental Master Probability Table Generator")
    
    for symbol in args.symbols:
        logger.info(f"🚀 Processing symbol: {symbol.upper()}")
        
        # Initialize generator for this symbol
        generator = ProbabilityLookupGenerator(symbol)
        
        # Run comprehensive test if requested
        if args.comprehensive_test:
            success = generator.run_comprehensive_test(symbol)
            if not success:
                logger.error(f"❌ Comprehensive test failed for {symbol.upper()}")
                return 1
            logger.info(f"✅ Comprehensive test completed for {symbol.upper()}")
            continue  # Skip normal processing for comprehensive test
        
        if args.test:
            generator.test_mode = True
            # Set the table name and keep it consistent throughout the process
            generator.master_table_name = f"probability_lookup_{symbol}_test"
        else:
            # For full runs, use timestamped names - GENERATE TIMESTAMP PER SYMBOL
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            generator.master_table_name = f"probability_lookup_{symbol}_{timestamp}"
        
        # Get dynamic buffer configuration based on symbol's price profile
        logger.info(f"🚀 Getting dynamic buffer configuration for {symbol.upper()}...")
        buffer_config = generator.get_dynamic_buffer_config()
        
        # Configure data ranges based on test mode
        if args.test:
            # TEST MODE: Reduced dataset for quick validation
            ttc_range = tuple(args.ttc_range) if args.ttc_range else (60, 300)  # 5 minutes
            max_buffer = min(int(buffer_config['buffer_width_usd']), args.buffer_limit or 200)
            buffer_range = (0, max_buffer)
            momentum_min = args.momentum_range[0] if args.momentum_range else -10
            momentum_max = args.momentum_range[1] if args.momentum_range else 10
            # Use the same bucketing approach for test mode
            momentum_percentiles = []
            for i in range(momentum_min, momentum_max + 1, 10):
                momentum_percentiles.append(i)
            logger.info(f"🧪 TEST MODE: TTC={ttc_range}, Buffer=0-{max_buffer}, Momentum={momentum_min}-{momentum_max}")
        else:
            # FULL DATASET: Complete probability table with full momentum range
            ttc_range = (0, 3600)  # 0 to 60 minutes (3600 seconds) with 10-second steps
            buffer_range = (0, buffer_config['buffer_width_usd'])  # Dynamic buffer width (preserve precision)
            # Use the same 18 momentum buckets as the fingerprint generator
            momentum_percentiles = []
            # Negative buckets: -90, -80, -70, -60, -50, -40, -30, -20, -10
            for i in range(-90, 0, 10):
                momentum_percentiles.append(i)
            # Positive buckets: +10, +20, +30, +40, +50, +60, +70, +80, +90
            for i in range(10, 100, 10):
                momentum_percentiles.append(i)
            logger.info(f"📊 FULL DATASET: Generating complete probability table with {len(momentum_percentiles)} momentum buckets")
            logger.info(f"📊 Momentum buckets: {momentum_percentiles}")
        
        ttc_step = 10  # 10-second steps (optimized)
        buffer_step = float(buffer_config['step_size_usd'])  # Dynamic step size (keep precision)
        
        # Reset progress if requested
        if args.reset_progress:
            logger.info(f"🔄 Resetting progress for {symbol.upper()}...")
            generator.setup_work_progress_schema(ttc_range, ttc_step)
            generator.reset_progress()
        
        # Generate incremental master table
        logger.info(f"🚀 Generating incremental master probability table for {symbol.upper()}...")
        
        # Check existing progress if any
        generator.setup_work_progress_schema(ttc_range, ttc_step)
        progress_stats = generator.get_progress_stats()
        if progress_stats:
            summary = progress_stats.get('summary', {})
            logger.info(f"📊 Current progress for {symbol.upper()}:")
            logger.info(f"   - Completed: {summary.get('completed_pct', 0):.1f}% ({progress_stats.get('completed', {}).get('count', 0)} TTC values)")
            logger.info(f"   - Pending: {summary.get('pending_pct', 0):.1f}% ({progress_stats.get('pending', {}).get('count', 0)} TTC values)")
            logger.info(f"   - Failed: {summary.get('failed_pct', 0):.1f}% ({progress_stats.get('failed', {}).get('count', 0)} TTC values)")
            logger.info(f"   - Total rows generated: {summary.get('total_rows_generated', 0):,}")
        
        success = generator.create_master_table_batched(
            ttc_range=ttc_range,
            buffer_range=buffer_range,
            momentum_percentiles=momentum_percentiles,
            ttc_step=ttc_step,
            buffer_step=buffer_step
        )
        
        if success:
            logger.info(f"🎉 Incremental master table created successfully for {symbol.upper()}!")
            logger.info(f"📁 Ready for production use with PostgreSQL interpolation")
        else:
            logger.error(f"❌ Failed to create incremental master table for {symbol.upper()}")
            return 1
    
    logger.info("🎉 All symbols processed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
