#!/usr/bin/env python3
"""
15-MINUTE MASTER PROBABILITY TABLE GENERATOR

Generates a pre-computed probability lookup table for the final 15 minutes (0-900 seconds)
of TTC window for BTC. This is a reduced scope test to validate the concept before
generating the full 1-hour table.

Usage:
    python backend/util/master_probability_table_generator_15min.py [--batch-size 10000]
"""

import os
import sys
import time
import argparse
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Tuple, Dict, Optional
from tqdm import tqdm
import logging

# Add backend to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.util.probability_calculator_postgresql import ProbabilityCalculatorPostgreSQL
from backend.util.paths import get_data_dir
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('master_probability_table_15min_generator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MasterProbabilityTableGenerator15Min:
    """
    Generates a 15-minute probability lookup table for BTC (0-900 seconds TTC).
    """

    def __init__(self, symbol: str = "btc", db_config: Optional[Dict] = None):
        self.symbol = symbol.lower()
        _base = db_config or {
            "host": "localhost",
            "database": "rec_io_db",
            "user": "rec_io_user",
            "password": "rec_io_password",
        }
        self.db_config = merge_psycopg2_connect_kwargs(_base)

        # Parameter ranges for 15-minute window
        self.ttc_range = range(0, 901)  # 0-900 seconds (15 minutes)
        self.buffer_range = range(0, 2001)  # 0-2000 points (BTC-specific)
        self.momentum_range = range(-30, 31)  # -30 to +30

        # Calculate total combinations
        self.total_combinations = len(self.ttc_range) * len(self.buffer_range) * len(self.momentum_range)
        logger.info(f"15-Minute Table - Total combinations to generate: {self.total_combinations:,}")
        logger.info(f"TTC Range: 0-900 seconds ({len(self.ttc_range)} values)")
        logger.info(f"Buffer Range: 0-2000 points ({len(self.buffer_range)} values)")
        logger.info(f"Momentum Range: -30 to +30 ({len(self.momentum_range)} values)")

        # Initialize probability calculator
        self.calculator = ProbabilityCalculatorPostgreSQL()

    def create_lookup_table(self) -> bool:
        """Create the 15-minute probability lookup table in PostgreSQL."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            # Create the lookup table
            table_name = f"master_probability_lookup_{self.symbol}_15min"
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS analytics.{table_name} (
                ttc_seconds INTEGER NOT NULL,
                buffer_points INTEGER NOT NULL,
                momentum_bucket INTEGER NOT NULL,
                prob_positive DECIMAL(5,2) NOT NULL,
                prob_negative DECIMAL(5,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ttc_seconds, buffer_points, momentum_bucket)
            );

            -- Create indexes for fast lookups
            CREATE INDEX IF NOT EXISTS idx_{table_name}_ttc ON analytics.{table_name} (ttc_seconds);
            CREATE INDEX IF NOT EXISTS idx_{table_name}_buffer ON analytics.{table_name} (buffer_points);
            CREATE INDEX IF NOT EXISTS idx_{table_name}_momentum ON analytics.{table_name} (momentum_bucket);
            CREATE INDEX IF NOT EXISTS idx_{table_name}_composite ON analytics.{table_name} (ttc_seconds, buffer_points, momentum_bucket);
            """

            cursor.execute(create_table_sql)
            conn.commit()

            logger.info(f"✅ Created 15-minute lookup table: analytics.{table_name}")
            return True

        except Exception as e:
            logger.error(f"❌ Error creating lookup table: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def calculate_probability_for_combination(self, ttc: int, buffer: int, momentum: int) -> Tuple[float, float]:
        """
        Calculate probability for a specific TTC, buffer, and momentum combination.

        Args:
            ttc: Time to close in seconds (0-900)
            buffer: Buffer points (0-2000)
            momentum: Momentum bucket (-30 to +30)

        Returns:
            Tuple of (prob_positive, prob_negative)
        """
        try:
            # Convert buffer points to percentage (assuming BTC price around 120k)
            current_price = 120000  # Base price for calculation
            buffer_percentage = (buffer / current_price) * 100

            # Calculate probabilities using the PostgreSQL calculator
            strike_above = current_price + buffer
            strike_below = current_price - buffer

            # Get probability for both directions
            prob_above = self.calculator.calculate_strike_probabilities(
                current_price=current_price,
                ttc_seconds=ttc,
                strikes=[strike_above],
                momentum_score=momentum
            )

            prob_below = self.calculator.calculate_strike_probabilities(
                current_price=current_price,
                ttc_seconds=ttc,
                strikes=[strike_below],
                momentum_score=momentum
            )

            # Extract probabilities
            if prob_above and prob_below:
                prob_positive = prob_above[0]['positive_prob']
                prob_negative = prob_below[0]['negative_prob']
                return prob_positive, prob_negative
            else:
                return 0.0, 0.0

        except Exception as e:
            logger.warning(f"Error calculating probability for ttc={ttc}, buffer={buffer}, momentum={momentum}: {e}")
            return 0.0, 0.0

    def generate_batch(self, batch_data: List[Tuple[int, int, int, float, float]],
                       table_name: str) -> bool:
        """Insert a batch of probability data into the lookup table."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            # Prepare batch insert
            insert_sql = f"""
            INSERT INTO analytics.{table_name}
            (ttc_seconds, buffer_points, momentum_bucket, prob_positive, prob_negative)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ttc_seconds, buffer_points, momentum_bucket)
            DO UPDATE SET
                prob_positive = EXCLUDED.prob_positive,
                prob_negative = EXCLUDED.prob_negative,
                created_at = CURRENT_TIMESTAMP
            """

            cursor.executemany(insert_sql, batch_data)
            conn.commit()

            return True

        except Exception as e:
            logger.error(f"❌ Error inserting batch: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def generate_master_table(self, batch_size: int = 10000,
                            progress_interval: int = 1000) -> bool:
        """
        Generate the complete 15-minute probability lookup table.

        Args:
            batch_size: Number of combinations to process before database insert
            progress_interval: How often to log progress
        """
        start_time = time.time()
        table_name = f"master_probability_lookup_{self.symbol}_15min"

        # Create the table
        if not self.create_lookup_table():
            return False

        logger.info(f"🚀 Starting generation of {self.total_combinations:,} probability combinations...")
        logger.info(f"📊 Estimated time: 2-3 days on cloud VM")
        logger.info(f"💰 Estimated cost: ~$38 on Google Cloud")

        batch_data = []
        processed_count = 0

        # Create progress bar
        with tqdm(total=self.total_combinations, desc="Generating 15-min probabilities") as pbar:

            for ttc in self.ttc_range:
                for buffer in self.buffer_range:
                    for momentum in self.momentum_range:

                        # Calculate probability for this combination
                        prob_positive, prob_negative = self.calculate_probability_for_combination(
                            ttc, buffer, momentum
                        )

                        # Add to batch
                        batch_data.append((ttc, buffer, momentum, prob_positive, prob_negative))

                        # Insert batch when it reaches the specified size
                        if len(batch_data) >= batch_size:
                            if self.generate_batch(batch_data, table_name):
                                processed_count += len(batch_data)
                                pbar.update(len(batch_data))

                                # Log progress
                                if processed_count % progress_interval == 0:
                                    elapsed = time.time() - start_time
                                    rate = processed_count / elapsed
                                    eta = (self.total_combinations - processed_count) / rate if rate > 0 else 0
                                    logger.info(f"📊 Processed {processed_count:,}/{self.total_combinations:,} "
                                              f"({processed_count/self.total_combinations*100:.1f}%) "
                                              f"Rate: {rate:.0f}/sec ETA: {eta/3600:.1f}h")
                            else:
                                logger.error(f"❌ Failed to insert batch at count {processed_count}")
                                return False

                            batch_data = []

                    # Insert any remaining data
                    if batch_data:
                        if self.generate_batch(batch_data, table_name):
                            processed_count += len(batch_data)
                            pbar.update(len(batch_data))
                        else:
                            logger.error(f"❌ Failed to insert final batch")
                            return False

        total_time = time.time() - start_time
        logger.info(f"✅ 15-minute master probability table generation complete!")
        logger.info(f"📊 Total combinations generated: {processed_count:,}")
        logger.info(f"⏱️ Total time: {total_time/3600:.2f} hours")
        logger.info(f"🚀 Average rate: {processed_count/total_time:.0f} combinations/second")

        return True

    def verify_table_integrity(self) -> bool:
        """Verify the generated table has the expected number of rows."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            table_name = f"master_probability_lookup_{self.symbol}_15min"
            cursor.execute(f"SELECT COUNT(*) FROM analytics.{table_name}")
            row_count = cursor.fetchone()[0]

            logger.info(f"📊 Table verification: {row_count:,} rows in analytics.{table_name}")
            logger.info(f"📊 Expected: {self.total_combinations:,} rows")

            if row_count == self.total_combinations:
                logger.info("✅ Table integrity verified!")
                return True
            else:
                logger.warning(f"⚠️ Table integrity check failed: expected {self.total_combinations:,}, got {row_count:,}")
                return False

        except Exception as e:
            logger.error(f"❌ Error verifying table integrity: {e}")
            return False
        finally:
            if conn:
                conn.close()

    def test_lookup_performance(self, num_tests: int = 1000) -> Dict:
        """Test the performance of probability lookups."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            table_name = f"master_probability_lookup_{self.symbol}_15min"

            # Generate random test parameters within 15-minute range
            test_params = []
            for _ in range(num_tests):
                ttc = np.random.randint(0, 901)  # 0-900 seconds
                buffer = np.random.randint(0, 2001)
                momentum = np.random.randint(-30, 31)
                test_params.append((ttc, buffer, momentum))

            # Test lookup performance
            start_time = time.time()

            for ttc, buffer, momentum in test_params:
                cursor.execute(f"""
                    SELECT prob_positive, prob_negative
                    FROM analytics.{table_name}
                    WHERE ttc_seconds = %s AND buffer_points = %s AND momentum_bucket = %s
                """, (ttc, buffer, momentum))

                result = cursor.fetchone()
                if not result:
                    logger.warning(f"⚠️ No result found for ttc={ttc}, buffer={buffer}, momentum={momentum}")

            total_time = time.time() - start_time
            avg_time = total_time / num_tests * 1000  # Convert to milliseconds

            performance_stats = {
                'total_lookups': num_tests,
                'total_time': total_time,
                'avg_lookup_time_ms': avg_time,
                'lookups_per_second': num_tests / total_time
            }

            logger.info(f"📊 15-minute lookup performance test results:")
            logger.info(f"   Average lookup time: {avg_time:.3f}ms")
            logger.info(f"   Lookups per second: {performance_stats['lookups_per_second']:.0f}")

            return performance_stats

        except Exception as e:
            logger.error(f"❌ Error testing lookup performance: {e}")
            return {}
        finally:
            if conn:
                conn.close()

    def get_sample_data(self, num_samples: int = 5) -> List[Dict]:
        """Get sample data from the generated table."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            table_name = f"master_probability_lookup_{self.symbol}_15min"
            cursor.execute(f"""
                SELECT ttc_seconds, buffer_points, momentum_bucket, prob_positive, prob_negative
                FROM analytics.{table_name}
                ORDER BY RANDOM()
                LIMIT %s
            """, (num_samples,))

            samples = []
            for row in cursor.fetchall():
                samples.append({
                    'ttc_seconds': row[0],
                    'buffer_points': row[1],
                    'momentum_bucket': row[2],
                    'prob_positive': row[3],
                    'prob_negative': row[4]
                })

            return samples

        except Exception as e:
            logger.error(f"❌ Error getting sample data: {e}")
            return []
        finally:
            if conn:
                conn.close()


def main():
    """Main function to run the 15-minute master probability table generator."""
    parser = argparse.ArgumentParser(description='Generate 15-minute master probability lookup table')
    parser.add_argument('--batch-size', type=int, default=10000, help='Batch size for database inserts (default: 10000)')
    parser.add_argument('--progress-interval', type=int, default=1000, help='Progress logging interval (default: 1000)')
    parser.add_argument('--verify-only', action='store_true', help='Only verify existing table integrity')
    parser.add_argument('--test-performance', action='store_true', help='Test lookup performance')
    parser.add_argument('--sample-data', action='store_true', help='Show sample data from table')

    args = parser.parse_args()

    logger.info(f"🎯 15-Minute Master Probability Table Generator for {args.symbol.upper()}")
    logger.info(f"📊 Batch size: {args.batch_size:,}")
    logger.info(f"📊 Progress interval: {args.progress_interval:,}")

    # Initialize generator
    generator = MasterProbabilityTableGenerator15Min(symbol="btc")

    if args.verify_only:
        logger.info("🔍 Running table integrity verification...")
        success = generator.verify_table_integrity()
        return 0 if success else 1

    elif args.test_performance:
        logger.info("⚡ Testing lookup performance...")
        performance = generator.test_lookup_performance()
        return 0 if performance else 1

    elif args.sample_data:
        logger.info("📋 Getting sample data...")
        samples = generator.get_sample_data()
        for i, sample in enumerate(samples, 1):
            logger.info(f"Sample {i}: TTC={sample['ttc_seconds']}s, Buffer={sample['buffer_points']}, "
                       f"Momentum={sample['momentum_bucket']}, Prob+={sample['prob_positive']:.2f}%, "
                       f"Prob-={sample['prob_negative']:.2f}%")
        return 0

    else:
        logger.info("🚀 Starting 15-minute master table generation...")
        logger.warning("⚠️ This will take 2-3 days to complete on cloud VM!")
        logger.warning("⚠️ Estimated cost: ~$38 on Google Cloud")

        # Ask for confirmation
        response = input("Continue with 15-minute table generation? (y/N): ")
        if response.lower() != 'y':
            logger.info("❌ Generation cancelled by user")
            return 0

        # Generate the table
        success = generator.generate_master_table(
            batch_size=args.batch_size,
            progress_interval=args.progress_interval
        )

        if success:
            # Verify integrity
            logger.info("🔍 Verifying table integrity...")
            generator.verify_table_integrity()

            # Test performance
            logger.info("⚡ Testing lookup performance...")
            generator.test_lookup_performance()

            # Show sample data
            logger.info("📋 Sample data from generated table:")
            samples = generator.get_sample_data()
            for i, sample in enumerate(samples, 1):
                logger.info(f"Sample {i}: TTC={sample['ttc_seconds']}s, Buffer={sample['buffer_points']}, "
                           f"Momentum={sample['momentum_bucket']}, Prob+={sample['prob_positive']:.2f}%, "
                           f"Prob-={sample['prob_negative']:.2f}%")

        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
