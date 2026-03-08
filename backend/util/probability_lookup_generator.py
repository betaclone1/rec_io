#!/usr/bin/env python3
"""
PROBABILITY LOOKUP TABLE GENERATOR

This script generates probability lookup tables containing pre-computed probability values
that match the live calculator's interpolation results exactly.

The lookup table will contain:
- ttc_seconds: Time to close in seconds (5-second increments)
- buffer_points: Distance from current price in points (10-point increments)
- momentum_bucket: Momentum bucket (-30 to +30)
- prob_within_positive: Interpolated positive probability (within buffer)
- prob_within_negative: Interpolated negative probability (within buffer)

This allows the lookup calculator to return identical results to the live calculator
without performing interpolation calculations.

OPTIMIZED VERSION: Uses 5-second TTC increments and 10-point buffer increments
to dramatically reduce table size while maintaining acceptable precision.
"""

import os
import sys
import psycopg2
import logging

from backend.core.config.database import get_postgresql_connection
import numpy as np
from scipy.interpolate import griddata
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import multiprocessing

# Add backend to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.util.paths import get_data_dir

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
        # Table names
        self.master_table_name = f"probability_lookup_{self.symbol}"
        self.fingerprint_table_prefix = f"{self.symbol}_fingerprint_directional_momentum_"
        self.work_progress_schema = "work_progress"
        
        # Parallel processing settings
        self.max_workers = min(multiprocessing.cpu_count(), 6)  # Use up to 6 cores
        self.batch_size = 1000  # Batch size for database inserts
        
        logger.info(f"✅ Initialized probability lookup generator for {self.symbol.upper()}")
        logger.info(f"📊 Max workers: {self.max_workers}")
    
    def get_available_momentum_buckets(self) -> List[int]:
        """Get list of available momentum buckets from PostgreSQL."""
        try:
            conn = get_postgresql_connection()
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
            
            buckets = []
            for table in tables:
                table_name = table[0]
                # Extract momentum bucket from table name like "btc_fingerprint_directional_momentum_010"
                bucket_str = table_name.replace(self.fingerprint_table_prefix, "")
                try:
                    bucket = int(bucket_str)
                    buckets.append(bucket)
                except ValueError:
                    logger.warning(f"Could not parse momentum bucket from {table_name}")
                    continue
            
            logger.info(f"📊 Found {len(buckets)} momentum buckets: {min(buckets)} to {max(buckets)}")
            return buckets
            
        except Exception as e:
            logger.error(f"❌ Error getting momentum buckets: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def setup_work_progress_schema(self, ttc_range: Tuple[int, int], ttc_step: int):
        """Create work_progress schema and progress tracking table."""
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            # Create work_progress schema
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {self.work_progress_schema}")
            
            # Create progress tracking table
            progress_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.work_progress_schema}.ttc_progress_incremental (
                ttc_seconds INTEGER PRIMARY KEY,
                status VARCHAR(20) DEFAULT 'pending',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                rows_generated INTEGER DEFAULT 0,
                error_message TEXT,
                table_name VARCHAR(100)
            )
            """
            cursor.execute(progress_table_sql)
            
            # Initialize progress for all TTC values (using ttc_step increments)
            ttc_values = list(range(ttc_range[0], ttc_range[1] + 1, ttc_step))
            for ttc in ttc_values:
                cursor.execute(f"""
                INSERT INTO {self.work_progress_schema}.ttc_progress_incremental (ttc_seconds, status)
                VALUES (%s, 'pending')
                ON CONFLICT (ttc_seconds) DO NOTHING
                """, (ttc,))
            
            conn.commit()
            logger.info(f"✅ Work progress schema setup complete for {len(ttc_values)} TTC values")
            
        except Exception as e:
            logger.error(f"❌ Error setting up work progress schema: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def get_pending_ttc_values(self) -> List[int]:
        """Get list of TTC values that need processing."""
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            cursor.execute(f"""
            SELECT ttc_seconds FROM {self.work_progress_schema}.ttc_progress_incremental 
            WHERE status IN ('pending', 'failed')
            ORDER BY ttc_seconds
            """)
            
            pending_ttc = [row[0] for row in cursor.fetchall()]
            logger.info(f"📊 Found {len(pending_ttc)} pending TTC values")
            return pending_ttc
            
        except Exception as e:
            logger.error(f"❌ Error getting pending TTC values: {e}")
            return []
        finally:
            if conn:
                conn.close()
    
    def update_ttc_status(self, ttc_seconds: int, status: str, rows_generated: int = 0, error_message: str = None):
        """Update the status of a TTC value in the progress table."""
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            if status == 'processing':
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.ttc_progress_incremental 
                SET status = %s, started_at = CURRENT_TIMESTAMP
                WHERE ttc_seconds = %s
                """, (status, ttc_seconds))
            elif status == 'completed':
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.ttc_progress_incremental 
                SET status = %s, completed_at = CURRENT_TIMESTAMP, rows_generated = %s
                WHERE ttc_seconds = %s
                """, (status, rows_generated, ttc_seconds))
            elif status == 'failed':
                cursor.execute(f"""
                UPDATE {self.work_progress_schema}.ttc_progress_incremental 
                SET status = %s, error_message = %s
                WHERE ttc_seconds = %s
                """, (status, error_message, ttc_seconds))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"❌ Error updating TTC status: {e}")
        finally:
            if conn:
                conn.close()
    
    def load_fingerprint_data(self, momentum_bucket: int) -> Dict:
        """Load fingerprint data for a specific momentum bucket."""
        try:
            conn = get_postgresql_connection()
            
            # Format table name correctly for negative and positive momentum buckets
            if momentum_bucket < 0:
                table_name = f"{self.fingerprint_table_prefix}-{abs(momentum_bucket):02d}"
            else:
                table_name = f"{self.fingerprint_table_prefix}{momentum_bucket:03d}"
            
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
            
            # Create interpolation points for positive and negative
            positive_interp_points = []
            positive_interp_values = []
            negative_interp_points = []
            negative_interp_values = []
            
            for i, ttc in enumerate(ttc_values):
                for j, move_pct in enumerate(positive_move_percentages):
                    positive_interp_points.append([ttc, move_pct])
                    positive_interp_values.append(positive_probability_matrix[i, j])
                    
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
            
            logger.info(f"📊 Loaded fingerprint data for momentum bucket {momentum_bucket}")
            logger.info(f"   TTC range: {min(ttc_values)}s to {max(ttc_values)}s")
            logger.info(f"   Positive move range: {min(positive_move_percentages):.2f}% to {max(positive_move_percentages):.2f}%")
            logger.info(f"   Negative move range: {min(negative_move_percentages):.2f}% to {max(negative_move_percentages):.2f}%")
            
            return fingerprint_data
            
        except Exception as e:
            logger.error(f"❌ Error loading fingerprint data for momentum {momentum_bucket}: {e}")
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
                          momentum_buckets: List[int], ttc_step: int = 5, buffer_step: int = 10):
        """
        Create the master probability lookup table.
        
        Args:
            ttc_range: (min_ttc_seconds, max_ttc_seconds)
            buffer_range: (min_buffer_points, max_buffer_points)
            momentum_buckets: List of momentum buckets to include
            ttc_step: Step size for TTC in seconds (default: 5 seconds)
            buffer_step: Step size for buffer in points (default: 10 points)
        """
        try:
            logger.info(f"🚀 Creating incremental master probability table")
            logger.info(f"📊 TTC range: {ttc_range[0]}s to {ttc_range[1]}s (step: {ttc_step}s)")
            logger.info(f"📊 Buffer range: {buffer_range[0]} to {buffer_range[1]} points (step: {buffer_step})")
            logger.info(f"📊 Momentum buckets: {momentum_buckets}")
            
            # Calculate total combinations
            ttc_count = (ttc_range[1] - ttc_range[0]) // ttc_step + 1
            buffer_count = (buffer_range[1] - buffer_range[0]) // buffer_step + 1
            total_combinations = ttc_count * buffer_count * len(momentum_buckets)
            

            logger.info(f"📊 Total combinations to generate: {total_combinations:,}")
            
            # Create table
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            # Drop existing table if it exists
            cursor.execute(f"DROP TABLE IF EXISTS analytics.{self.master_table_name}")
            
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
            
            # Load fingerprint data for all momentum buckets
            fingerprint_data_cache = {}
            for momentum_bucket in momentum_buckets:
                fingerprint_data = self.load_fingerprint_data(momentum_bucket)
                if fingerprint_data:
                    fingerprint_data_cache[momentum_bucket] = fingerprint_data
                else:
                    logger.warning(f"⚠️ Skipping momentum bucket {momentum_bucket} - no data")
            
            if not fingerprint_data_cache:
                raise ValueError("No fingerprint data available for any momentum bucket")
            
            # Generate all combinations
            total_generated = 0
            start_time = time.time()
            
            for ttc_seconds in range(ttc_range[0], ttc_range[1] + 1, ttc_step):
                for buffer_points in range(buffer_range[0], buffer_range[1] + 1, buffer_step):
                    for momentum_bucket in momentum_buckets:
                        if momentum_bucket not in fingerprint_data_cache:
                            continue
                        
                        # Calculate move percentage (assuming $120,000 base price for now)
                        base_price = 120000
                        move_percent = (buffer_points / base_price) * 100
                        
                        # Interpolate both positive and negative probabilities
                        prob_within_positive, prob_within_negative = self.interpolate_probabilities(
                            fingerprint_data_cache[momentum_bucket], ttc_seconds, move_percent
                        )
                        
                        # Insert into table
                        insert_sql = f"""
                        INSERT INTO analytics.{self.master_table_name} 
                        (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        cursor.execute(insert_sql, (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative))
                        
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
                         momentum_buckets: List[int], buffer_step: int, 
                         fingerprint_data_cache: Dict) -> int:
        """
        Process a single TTC value and generate all combinations for it.
        
        Returns:
            Number of combinations generated for this TTC value
        """
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            rows_generated = 0
            
            # Generate all buffer and momentum combinations for this TTC
            for buffer_points in range(buffer_range[0], buffer_range[1] + 1, buffer_step):
                for momentum_bucket in momentum_buckets:
                    if momentum_bucket not in fingerprint_data_cache:
                        continue
                    
                    # Calculate move percentage (assuming $120,000 base price for now)
                    base_price = 120000
                    move_percent = (buffer_points / base_price) * 100
                    
                    # Interpolate both positive and negative probabilities
                    prob_within_positive, prob_within_negative = self.interpolate_probabilities(
                        fingerprint_data_cache[momentum_bucket], ttc_seconds, move_percent
                    )
                    
                    # Insert into table
                    insert_sql = f"""
                    INSERT INTO analytics.{self.master_table_name} 
                    (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (ttc_seconds, buffer_points, momentum_bucket) DO NOTHING
                    """
                    cursor.execute(insert_sql, (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative))
                    
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
                                  momentum_buckets: List[int], ttc_step: int = 5, buffer_step: int = 10):
        """
        Create the master probability lookup table using batched processing with resume capability.
        """
        try:
            logger.info(f"🚀 Creating incremental master probability table (batched)")
            logger.info(f"📊 TTC range: {ttc_range[0]}s to {ttc_range[1]}s (step: {ttc_step}s)")
            logger.info(f"📊 Buffer range: {buffer_range[0]} to {buffer_range[1]} points (step: {buffer_step})")
            logger.info(f"📊 Momentum buckets: {momentum_buckets}")
            
            # Setup work progress tracking
            self.setup_work_progress_schema(ttc_range, ttc_step)
            
            # Create main table if it doesn't exist
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS analytics.{self.master_table_name} (
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
            conn.commit()
            conn.close()
            
            # Load fingerprint data for all momentum buckets
            fingerprint_data_cache = {}
            for momentum_bucket in momentum_buckets:
                fingerprint_data = self.load_fingerprint_data(momentum_bucket)
                if fingerprint_data:
                    fingerprint_data_cache[momentum_bucket] = fingerprint_data
                else:
                    logger.warning(f"⚠️ Skipping momentum bucket {momentum_bucket} - no data")
            
            if not fingerprint_data_cache:
                raise ValueError("No fingerprint data available for any momentum bucket")
            
            # Get pending TTC values
            pending_ttc = self.get_pending_ttc_values()
            if not pending_ttc:
                logger.info("✅ All TTC values already completed!")
                return True
            
            logger.info(f"📊 Processing {len(pending_ttc)} TTC values...")
            
            # Process TTC values with parallel processing
            total_generated = 0
            start_time = time.time()
            
            def process_ttc_with_tracking(ttc_seconds):
                try:
                    # Mark as processing
                    self.update_ttc_status(ttc_seconds, 'processing')
                    
                    # Process this TTC value
                    rows_generated = self.process_ttc_value(
                        ttc_seconds, buffer_range, momentum_buckets, buffer_step, fingerprint_data_cache
                    )
                    
                    # Mark as completed
                    self.update_ttc_status(ttc_seconds, 'completed', rows_generated)
                    
                    elapsed = time.time() - start_time
                    logger.info(f"✅ TTC {ttc_seconds}s completed: {rows_generated:,} combinations in {elapsed/60:.1f}min")
                    
                    return rows_generated
                    
                except Exception as e:
                    logger.error(f"❌ Error processing TTC {ttc_seconds}: {e}")
                    self.update_ttc_status(ttc_seconds, 'failed', error_message=str(e))
                    return 0
            
            # Use ThreadPoolExecutor for parallel processing
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(process_ttc_with_tracking, ttc) for ttc in pending_ttc]
                
                for future in futures:
                    try:
                        rows_generated = future.result()
                        total_generated += rows_generated
                    except Exception as e:
                        logger.error(f"❌ Error in parallel processing: {e}")
                        continue
            
            # Create index for faster lookups
            conn = get_postgresql_connection()
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


def main():
    """Main function to run the incremental master table generator."""
    logger.info("🚀 Starting Incremental Master Probability Table Generator")
    
    # Initialize generator
    generator = ProbabilityLookupGenerator("btc")
    
    # Generate incremental master table
    logger.info("🚀 Generating incremental master probability table...")
    
    # FULL DATASET: Complete BTC probability table
    ttc_range = (0, 3600)  # 0 to 60 minutes (3600 seconds)
    buffer_range = (0, 2000)   # 0 to 2000 points (BTC-specific - see FUTURE ENHANCEMENT comment above)
    momentum_buckets = generator.get_available_momentum_buckets()  # All 61 momentum buckets
    ttc_step = 5  # 5-second steps (optimized)
    buffer_step = 10  # 10-point steps (optimized - BTC-specific)
    
    success = generator.create_master_table_batched(
        ttc_range=ttc_range,
        buffer_range=buffer_range,
        momentum_buckets=momentum_buckets,
        ttc_step=ttc_step,
        buffer_step=buffer_step
    )
    
    if success:
        logger.info("🎉 Incremental master table created successfully!")
        logger.info("📁 Ready for production use with PostgreSQL interpolation")
    else:
        logger.error("❌ Failed to create incremental master table")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
