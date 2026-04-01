#!/usr/bin/env python3
"""
MASTER PROBABILITY TABLE GENERATOR

This script generates a master lookup table containing pre-computed probability values
that match the live calculator's interpolation results exactly.

The master table will contain:
- ttc_seconds: Time to close in seconds
- buffer_points: Distance from current price in points
- momentum_bucket: Momentum bucket (-30 to +30)
- prob_positive: Interpolated positive probability
- prob_negative: Interpolated negative probability

This allows the lookup calculator to return identical results to the live calculator
without performing interpolation calculations.
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

# Add backend to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.util.paths import get_data_dir
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MasterProbabilityTableGenerator:
    """
    Generates master probability lookup tables using the same methodology as the live calculator.
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
        self.master_table_name = f"master_probability_lookup_{self.symbol}"
        self.fingerprint_table_prefix = f"{self.symbol}_fingerprint_directional_momentum_"
        
        logger.info(f"✅ Initialized master table generator for {self.symbol.upper()}")
    
    def get_available_momentum_buckets(self) -> List[int]:
        """Get list of available momentum buckets from PostgreSQL."""
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
    
    def load_fingerprint_data(self, momentum_bucket: int) -> Dict:
        """Load fingerprint data for a specific momentum bucket."""
        try:
            conn = psycopg2.connect(**self.db_config)
            
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
                          momentum_buckets: List[int], ttc_step: int = 30, buffer_step: int = 10):
        """
        Create the master probability lookup table.
        
        Args:
            ttc_range: (min_ttc_seconds, max_ttc_seconds)
            buffer_range: (min_buffer_points, max_buffer_points)
            momentum_buckets: List of momentum buckets to include
            ttc_step: Step size for TTC in seconds
            buffer_step: Step size for buffer in points
        """
        try:
            logger.info(f"🚀 Creating master probability table")
            logger.info(f"📊 TTC range: {ttc_range[0]}s to {ttc_range[1]}s (step: {ttc_step}s)")
            logger.info(f"📊 Buffer range: {buffer_range[0]} to {buffer_range[1]} points (step: {buffer_step})")
            logger.info(f"📊 Momentum buckets: {momentum_buckets}")
            
            # Calculate total combinations
            ttc_count = (ttc_range[1] - ttc_range[0]) // ttc_step + 1
            buffer_count = (buffer_range[1] - buffer_range[0]) // buffer_step + 1
            total_combinations = ttc_count * buffer_count * len(momentum_buckets)
            
            logger.info(f"📊 Total combinations to generate: {total_combinations:,}")
            
            # Create table
            conn = psycopg2.connect(**self.db_config)
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
            logger.info(f"✅ Master table created successfully!")
            logger.info(f"📊 Total combinations generated: {total_generated:,}")
            logger.info(f"📊 Total time: {elapsed/60:.1f} minutes")
            logger.info(f"📊 Average rate: {total_generated/elapsed:.0f} combinations/second")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error creating master table: {e}")
            return False
        finally:
            if conn:
                conn.close()


def main():
    """Main function to run the master table generator."""
    logger.info("🚀 Starting Master Probability Table Generator")
    
    # Initialize generator
    generator = MasterProbabilityTableGenerator("btc")
    
    # Generate full master table
    logger.info("🚀 Generating full master probability table...")
    
    # Full generation parameters (0-60 minutes, 0-2000 buffer, all momentum buckets)
    ttc_range = (0, 3600)  # 0 to 60 minutes (3600 seconds)
    buffer_range = (0, 2000)   # 0 to 2000 points
    momentum_buckets = generator.get_available_momentum_buckets()  # All 61 momentum buckets
    ttc_step = 1  # 1-second steps
    buffer_step = 1  # 1-point steps
    
    success = generator.create_master_table(
        ttc_range=ttc_range,
        buffer_range=buffer_range,
        momentum_buckets=momentum_buckets,
        ttc_step=ttc_step,
        buffer_step=buffer_step
    )
    
    if success:
        logger.info("🎉 Full master table created successfully!")
        logger.info("📁 Ready for production use")
    else:
        logger.error("❌ Failed to create full master table")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
