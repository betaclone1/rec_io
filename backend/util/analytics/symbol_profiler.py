#!/usr/bin/env python3
"""
SYMBOL PROFILER

This script analyzes historical data to create comprehensive profiles for trading symbols.
It creates two types of profiles:

1. MOMENTUM PROFILES: <symbol>_momentum_profile table showing the bell curve
   of momentum distributions in 1-percentile steps away from the mean.

2. PRICE PROFILES: <symbol>_price_profile table showing real-dollar price movement
   characteristics across different momentum ranges for probability lookup table design.

The analysis uses time-weighted importance where recent data is weighted more heavily than older data.
"""

import os
import sys
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import argparse
import logging
from typing import Dict, List, Tuple, Optional

# Add backend to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SymbolProfiler:
    """
    Analyzes historical data to create comprehensive momentum and price profiles for trading symbols.
    """
    
    def __init__(self, symbol: str = "btc"):
        self.symbol = symbol.lower()
        self.db_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
            'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
            'password': os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        }
        
        # Table names
        self.source_table = f"historical_data.{self.symbol}_price_history"
        self.momentum_profile_table = f"analytics.{self.symbol}_momentum_profile"
        self.price_profile_table = f"analytics.{self.symbol}_price_profile"
        
        logger.info(f"✅ Initialized symbol profiler for {self.symbol.upper()}")
    
    def get_postgresql_connection(self):
        """Get PostgreSQL connection"""
        try:
            # Force localhost connection for testing
            conn = psycopg2.connect(
                host='localhost',
                database='rec_io_db',
                user='rec_io_user',
                password='rec_io_password'
            )
            # Debug: Check which database we're actually connected to
            cursor = conn.cursor()
            cursor.execute("SELECT current_database(), inet_server_addr();")
            db_info = cursor.fetchone()
            logger.info(f"🔗 Connected to database: {db_info[0]} on {db_info[1]}")
            cursor.close()
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            return None
    
    def load_momentum_data(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        Load momentum data from the historical price table.
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
            
        Returns:
            DataFrame with timestamp and momentum data
        """
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Build query with optional date filters
            query = f"""
                SELECT timestamp, momentum
                FROM {self.source_table}
                WHERE momentum IS NOT NULL
            """
            
            params = []
            if start_date or end_date:
                query += " AND"
                if start_date:
                    query += " timestamp >= %s"
                    params.append(start_date)
                if end_date:
                    if start_date:
                        query += " AND"
                    query += " timestamp <= %s"
                    params.append(end_date)
            
            query += " ORDER BY timestamp"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            if not rows:
                raise Exception(f"No momentum data found for {self.symbol}")
            
            # Convert to DataFrame
            df = pd.DataFrame(rows, columns=['timestamp', 'momentum'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['momentum'] = df['momentum'].astype(float)
            
            logger.info(f"📊 Loaded {len(df)} momentum records from {self.symbol} table")
            return df
            
        except Exception as e:
            raise e
        finally:
            conn.close()
    
    def load_price_data(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        Load price and momentum data from the historical price table.
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
            
        Returns:
            DataFrame with timestamp, price, and momentum data
        """
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Build query with optional date filters
            query = f"""
                SELECT timestamp, close, momentum
                FROM {self.source_table}
                WHERE momentum IS NOT NULL AND close IS NOT NULL
            """
            
            params = []
            if start_date or end_date:
                query += " AND"
                if start_date:
                    query += " timestamp >= %s"
                    params.append(start_date)
                if end_date:
                    if start_date:
                        query += " AND"
                    query += " timestamp <= %s"
                    params.append(end_date)
            
            query += " ORDER BY timestamp"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            if not rows:
                raise Exception(f"No price data found for {self.symbol}")
            
            # Convert to DataFrame
            df = pd.DataFrame(rows, columns=['timestamp', 'close', 'momentum'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['close'] = df['close'].astype(float)
            df['momentum'] = df['momentum'].astype(float)
            
            logger.info(f"📊 Loaded {len(df)} price records from {self.symbol} table")
            return df
            
        except Exception as e:
            raise e
        finally:
            conn.close()
    
    def calculate_time_weights(self, df: pd.DataFrame) -> np.ndarray:
        """
        Calculate time-based weights where recent data is weighted more heavily.
        Uses exponential decay with more weight on recent years.
        
        Args:
            df: DataFrame with timestamp column
            
        Returns:
            Array of weights for each row
        """
        # Get the most recent timestamp
        max_timestamp = df['timestamp'].max()
        
        # Calculate days since most recent data for each row
        df['days_ago'] = (max_timestamp - df['timestamp']).dt.days
        
        # Calculate weights using exponential decay
        # Recent data (last year) gets weight ~1.0, older data gets progressively less weight
        decay_rate = 0.001  # Adjust this to control how quickly weights decay
        weights = np.exp(-decay_rate * df['days_ago'].values)
        
        # Normalize weights to sum to 1
        weights = weights / weights.sum()
        
        logger.info(f"⏰ Calculated time weights: {len(weights)} records, weight range: {weights.min():.6f} to {weights.max():.6f}")
        return weights
    
    def calculate_percentile_profile(self, df: pd.DataFrame, weights: np.ndarray) -> pd.DataFrame:
        """
        Calculate percentile-based momentum profile.
        
        Args:
            df: DataFrame with momentum data
            weights: Array of time weights
            
        Returns:
            DataFrame with percentile profile
        """
        momentum_values = df['momentum'].values
        
        # Calculate weighted statistics
        weighted_mean = np.average(momentum_values, weights=weights)
        weighted_std = np.sqrt(np.average((momentum_values - weighted_mean)**2, weights=weights))
        
        # Calculate percentiles (0.5th to 99.5th percentile in 0.5 increments)
        raw_percentiles = np.arange(0.5, 100, 0.5)  # 0.5, 1.0, 1.5, ..., 99.5
        
        # Calculate weighted percentiles
        weighted_percentiles = []
        for p in raw_percentiles:
            # Use weighted quantile calculation
            sorted_indices = np.argsort(momentum_values)
            sorted_weights = weights[sorted_indices]
            sorted_values = momentum_values[sorted_indices]
            
            # Calculate cumulative weights
            cumsum_weights = np.cumsum(sorted_weights)
            
            # Find the index where cumulative weight reaches the percentile
            target_weight = p / 100.0
            idx = np.searchsorted(cumsum_weights, target_weight)
            
            if idx >= len(sorted_values):
                percentile_value = sorted_values[-1]
            else:
                percentile_value = sorted_values[idx]
            
            weighted_percentiles.append(percentile_value)
        
        # Transform percentiles to centered scale (-99.5 to +99.5)
        # 0.5 -> -99.5, 50.0 -> 0.0, 99.5 -> +99.5
        centered_percentiles = []
        for p in raw_percentiles:
            # Linear transformation: map 0.5-99.5 to -99.5 to +99.5
            # Formula: centered_p = (p - 50) * 2
            # This gives: 0.5 -> -99, 50.0 -> 0, 99.5 -> +99
            centered_p = (p - 50) * 2
            centered_percentiles.append(centered_p)
        
        # Verify array lengths match
        assert len(centered_percentiles) == len(weighted_percentiles), f"Array length mismatch: centered_percentiles={len(centered_percentiles)}, weighted_percentiles={len(weighted_percentiles)}"
        
        # Create profile DataFrame
        profile_df = pd.DataFrame({
            'percentile': centered_percentiles,
            'momentum_value': weighted_percentiles,
            'deviation_from_mean': [p - weighted_mean for p in weighted_percentiles],
            'z_score': [(p - weighted_mean) / weighted_std for p in weighted_percentiles]
        })
        
        # Add summary statistics
        profile_df['weighted_mean'] = weighted_mean
        profile_df['weighted_std'] = weighted_std
        
        logger.info(f"📈 Calculated percentile profile: mean={weighted_mean:.4f}, std={weighted_std:.4f}")
        return profile_df
    
    def create_profile_table(self):
        """Create the momentum profile table in the analytics schema."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Create the profile table
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.momentum_profile_table} (
                percentile NUMERIC(6,1) PRIMARY KEY,
                momentum_value NUMERIC(15,6) NOT NULL,
                deviation_from_mean NUMERIC(15,6) NOT NULL,
                z_score NUMERIC(15,6) NOT NULL,
                weighted_mean NUMERIC(15,6) NOT NULL,
                weighted_std NUMERIC(15,6) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            
            cursor.execute(create_table_sql)
            conn.commit()
            
            logger.info(f"✅ Created/verified table: {self.momentum_profile_table}")
            
        except Exception as e:
            logger.error(f"❌ Error creating table: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def insert_profile_data(self, profile_df: pd.DataFrame):
        """Insert the calculated profile data into the database."""
        # Use consistent connection method
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Clear existing data
            cursor.execute(f"DELETE FROM {self.momentum_profile_table}")
            logger.info(f"Cleared existing data from {self.momentum_profile_table}")
            
            # Insert new profile data
            inserted_count = 0
            for idx, row in profile_df.iterrows():
                try:
                    # Convert values to proper types
                    percentile = float(row['percentile'])
                    momentum_value = float(row['momentum_value'])
                    deviation_from_mean = float(row['deviation_from_mean'])
                    z_score = float(row['z_score'])
                    weighted_mean = float(row['weighted_mean'])
                    weighted_std = float(row['weighted_std'])
                    
                    cursor.execute(f"""
                        INSERT INTO {self.momentum_profile_table} 
                        (percentile, momentum_value, deviation_from_mean, z_score, weighted_mean, weighted_std)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (percentile, momentum_value, deviation_from_mean, z_score, weighted_mean, weighted_std))
                    
                    inserted_count += 1
                    
                    # Log progress every 50 records
                    if inserted_count % 50 == 0:
                        logger.info(f"Inserted {inserted_count} records...")
                        
                except Exception as row_error:
                    logger.error(f"❌ Error inserting row {idx}: {row_error}")
                    logger.error(f"Row data: {row.to_dict()}")
                    raise
            
            conn.commit()
            logger.info(f"✅ Successfully inserted {inserted_count} percentile records (-99.5 to +99.5) into {self.momentum_profile_table}")
            
        except Exception as e:
            logger.error(f"❌ Error inserting profile data: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def generate_profile(self, start_date: str = None, end_date: str = None):
        """
        Generate the complete momentum profile.
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
        """
        logger.info(f"🚀 Starting momentum profile generation for {self.symbol.upper()}")
        
        try:
            # Load momentum data
            df = self.load_momentum_data(start_date, end_date)
            
            # Calculate time weights
            weights = self.calculate_time_weights(df)
            
            # Calculate percentile profile
            profile_df = self.calculate_percentile_profile(df, weights)
            
            # Create table if needed
            self.create_profile_table()
            
            # Insert profile data
            self.insert_profile_data(profile_df)
            
            # Log summary statistics
            logger.info(f"📊 Profile Summary:")
            logger.info(f"   - Total records analyzed: {len(df)}")
            logger.info(f"   - Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
            logger.info(f"   - Momentum range: {df['momentum'].min():.4f} to {df['momentum'].max():.4f}")
            logger.info(f"   - Weighted mean: {profile_df['weighted_mean'].iloc[0]:.4f}")
            logger.info(f"   - Weighted std: {profile_df['weighted_std'].iloc[0]:.4f}")
            logger.info(f"   - Percentiles calculated: -99.5 to +99.5 (0.5 increments)")
            
            return profile_df
            
        except Exception as e:
            logger.error(f"❌ Error generating momentum profile: {e}")
            raise

    def create_price_profile_table(self):
        """Create the price profile table in the analytics schema."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Create the price profile table
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.price_profile_table} (
                range_name VARCHAR(20) PRIMARY KEY,
                percentile_min NUMERIC(5,1) NOT NULL,
                percentile_max NUMERIC(5,1) NOT NULL,
                price_change_min NUMERIC(10,6) NOT NULL,
                price_change_max NUMERIC(10,6) NOT NULL,
                avg_price_change_pct NUMERIC(10,6) NOT NULL,
                sample_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            
            cursor.execute(create_table_sql)
            conn.commit()
            
            logger.info(f"✅ Created/verified table: {self.price_profile_table}")
            
        except Exception as e:
            logger.error(f"❌ Error creating price profile table: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def calculate_price_profile(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate price movement distribution across the full dataset.
        Creates a bell curve of 1-hour percentage price movements.
        
        Args:
            df: DataFrame with timestamp, close, and momentum data
            
        Returns:
            DataFrame with price profile data
        """
        logger.info(f"📊 Calculating price movement distribution for {len(df)} rows...")
        
        # Calculate 1-hour percentage price changes for the entire dataset
        df = df.copy()
        df['next_price'] = df['close'].shift(-60)  # 60 minutes ahead
        df['price_change_pct'] = ((df['next_price'] - df['close']) / df['close']) * 100
        
        # Remove rows where we don't have future data
        df = df.dropna(subset=['price_change_pct'])
        
        if len(df) == 0:
            raise Exception("No valid price change data found")
        
        # Get the distribution of percentage movements
        price_changes = df['price_change_pct'].abs()  # Use absolute values for distribution
        
        # Calculate key statistics
        min_change = price_changes.min()
        max_change = price_changes.max()
        mean_change = price_changes.mean()
        median_change = price_changes.median()
        std_change = price_changes.std()
        
        logger.info(f"📊 Price movement statistics:")
        logger.info(f"   Min: {min_change:.4f}%")
        logger.info(f"   Max: {max_change:.4f}%")
        logger.info(f"   Mean: {mean_change:.4f}%")
        logger.info(f"   Median: {median_change:.4f}%")
        logger.info(f"   Std Dev: {std_change:.4f}%")
        
        # Create percentile-based ranges (similar to momentum profile)
        percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
        percentile_values = [price_changes.quantile(p/100) for p in percentiles]
        
        # Create ranges based on percentiles
        ranges = []
        for i in range(len(percentiles) - 1):
            p1, p2 = percentiles[i], percentiles[i+1]
            v1, v2 = percentile_values[i], percentile_values[i+1]
            ranges.append({
                'range_name': f"{p1}-{p2}",
                'percentile_min': p1,
                'percentile_max': p2,
                'price_change_min': v1,
                'price_change_max': v2,
                'avg_price_change_pct': (v1 + v2) / 2,  # Midpoint of range
                'sample_count': len(price_changes[(price_changes >= v1) & (price_changes < v2)])
            })
        
        # Add overall statistics
        profile_data = [{
            'range_name': 'overall',
            'percentile_min': 0,
            'percentile_max': 100,
            'price_change_min': min_change,
            'price_change_max': max_change,
            'avg_price_change_pct': mean_change,
            'sample_count': len(price_changes)
        }]
        
        profile_data.extend(ranges)
        
        return pd.DataFrame(profile_data)

    def insert_price_profile_data(self, profile_df: pd.DataFrame):
        """Insert the calculated price profile data into the database."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Clear existing data
            cursor.execute(f"DELETE FROM {self.price_profile_table}")
            
            # Insert new profile data
            for _, row in profile_df.iterrows():
                cursor.execute(f"""
                    INSERT INTO {self.price_profile_table} 
                    (range_name, percentile_min, percentile_max, price_change_min,
                     price_change_max, avg_price_change_pct, sample_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    row['range_name'],
                    float(row['percentile_min']),
                    float(row['percentile_max']),
                    float(row['price_change_min']),
                    float(row['price_change_max']),
                    float(row['avg_price_change_pct']),
                    int(row['sample_count'])
                ))
            
            conn.commit()
            logger.info(f"✅ Inserted {len(profile_df)} price profile records into {self.price_profile_table}")
            
        except Exception as e:
            logger.error(f"❌ Error inserting price profile data: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def generate_price_profile(self, start_date: str = None, end_date: str = None):
        """
        Generate the complete price profile.
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
        """
        logger.info(f"🚀 Starting price profile generation for {self.symbol.upper()}")
        
        try:
            # Load price data
            df = self.load_price_data(start_date, end_date)
            
            # Calculate price profile
            profile_df = self.calculate_price_profile(df)
            
            # Create table if needed
            self.create_price_profile_table()
            
            # Insert profile data
            self.insert_price_profile_data(profile_df)
            
            # Log summary statistics
            logger.info(f"📊 Price Profile Summary:")
            logger.info(f"   - Total records analyzed: {len(df)}")
            logger.info(f"   - Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
            logger.info(f"   - Price range: ${df['close'].min():.2f} to ${df['close'].max():.2f}")
            logger.info(f"   - Momentum ranges analyzed: {len(profile_df)}")
            
            return profile_df
            
        except Exception as e:
            logger.error(f"❌ Error generating price profile: {e}")
            raise

    def assign_momentum_percentiles(self, start_date: str = None, end_date: str = None):
        """
        Assign momentum percentile values to rows in the master price table that are missing them.
        Only processes rows where momentum_percentile IS NULL to avoid unnecessary work.
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
        """
        logger.info(f"🚀 Starting momentum percentile assignment for {self.symbol.upper()}")
        
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # First, check if momentum_percentile column exists, create if not
            cursor.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'historical_data' 
                AND table_name = '{self.symbol}_price_history' 
                AND column_name = 'momentum_percentile'
            """)
            
            if not cursor.fetchone():
                logger.info(f"📊 Adding momentum_percentile column to {self.source_table}")
                cursor.execute(f"""
                    ALTER TABLE {self.source_table} 
                    ADD COLUMN momentum_percentile DECIMAL(5,1)
                """)
                conn.commit()
                logger.info(f"✅ Added momentum_percentile column")
            
            # Load momentum profile data for percentile mapping
            cursor.execute(f"""
                SELECT percentile, momentum_value
                FROM {self.momentum_profile_table}
                ORDER BY percentile
            """)
            
            profile_data = cursor.fetchall()
            if not profile_data:
                raise Exception(f"No momentum profile data found in {self.momentum_profile_table}")
            
            # Create percentile mapping dictionary
            percentile_mapping = {}
            for row in profile_data:
                percentile, momentum_value = row
                percentile_mapping[momentum_value] = percentile
            
            # Get rows that need momentum_percentile assignment
            query = f"""
                SELECT timestamp, momentum
                FROM {self.source_table}
                WHERE momentum IS NOT NULL 
                AND momentum_percentile IS NULL
            """
            
            params = []
            if start_date or end_date:
                query += " AND"
                if start_date:
                    query += " timestamp >= %s"
                    params.append(start_date)
                if end_date:
                    if start_date:
                        query += " AND"
                    query += " timestamp <= %s"
                    params.append(end_date)
            
            query += " ORDER BY timestamp"
            
            cursor.execute(query, params)
            rows_to_update = cursor.fetchall()
            
            if not rows_to_update:
                logger.info(f"ℹ️ No rows need momentum_percentile assignment for {self.symbol.upper()}")
                return 0
            
            logger.info(f"📊 Found {len(rows_to_update)} rows needing momentum_percentile assignment")
            
            # Process rows in batches
            batch_size = 1000
            total_updated = 0
            
            for i in range(0, len(rows_to_update), batch_size):
                batch = rows_to_update[i:i + batch_size]
                
                # Find the closest momentum value in the profile for each row
                updates = []
                for timestamp, momentum in batch:
                    if momentum is None:
                        continue
                    
                    # Find the closest momentum value in the profile
                    closest_momentum = min(percentile_mapping.keys(), 
                                         key=lambda x: abs(x - momentum))
                    assigned_percentile = percentile_mapping[closest_momentum]
                    updates.append((assigned_percentile, timestamp))
                
                # Update the batch
                if updates:
                    cursor.executemany(f"""
                        UPDATE {self.source_table} 
                        SET momentum_percentile = %s 
                        WHERE timestamp = %s
                    """, updates)
                    
                    batch_updated = len(updates)
                    total_updated += batch_updated
                    
                    logger.info(f"📊 Updated batch {i//batch_size + 1}: {batch_updated} rows")
            
            conn.commit()
            logger.info(f"✅ Successfully assigned momentum_percentile to {total_updated} rows")
            
            return total_updated
            
        except Exception as e:
            logger.error(f"❌ Error assigning momentum percentiles: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

def main():
    parser = argparse.ArgumentParser(description="Generate comprehensive symbol profiles for historical data")
    parser.add_argument("symbol", nargs='?', default="btc", help="Symbol to process (e.g., btc, eth)")
    parser.add_argument("--start-date", help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--momentum-only", action="store_true", help="Generate only momentum profile")
    parser.add_argument("--price-only", action="store_true", help="Generate only price profile")
    parser.add_argument("--assign-percentiles", action="store_true", help="Assign momentum percentiles to master table")
    parser.add_argument("--list-symbols", action="store_true", help="List available symbols")
    args = parser.parse_args()

    if args.list_symbols:
        # List available symbols (you can implement this if needed)
        print("Available symbols: btc, eth")
        return

    symbol = args.symbol.lower()
    
    # Create profiler
    profiler = SymbolProfiler(symbol)
    
    # Generate profiles based on arguments
    if args.assign_percentiles:
        # Assign momentum percentiles to master table
        rows_updated = profiler.assign_momentum_percentiles(args.start_date, args.end_date)
        print(f"\n✅ Momentum percentile assignment completed for {symbol.upper()}")
        print(f"📊 Rows updated: {rows_updated}")
    elif args.price_only:
        # Generate only price profile
        price_profile_df = profiler.generate_price_profile(args.start_date, args.end_date)
        print(f"\n✅ Price profile generated successfully for {symbol.upper()}")
        print(f"📊 Table: analytics.{symbol}_price_profile")
        print(f"📈 Records: {len(price_profile_df)} momentum ranges")
    elif args.momentum_only:
        # Generate only momentum profile
        momentum_profile_df = profiler.generate_profile(args.start_date, args.end_date)
        print(f"\n✅ Momentum profile generated successfully for {symbol.upper()}")
        print(f"📊 Table: analytics.{symbol}_momentum_profile")
        print(f"📈 Records: {len(momentum_profile_df)} percentiles (-99.5 to +99.5)")
    else:
        # Generate both profiles
        momentum_profile_df = profiler.generate_profile(args.start_date, args.end_date)
        price_profile_df = profiler.generate_price_profile(args.start_date, args.end_date)
        print(f"\n✅ Both profiles generated successfully for {symbol.upper()}")
        print(f"📊 Momentum Table: analytics.{symbol}_momentum_profile ({len(momentum_profile_df)} percentiles)")
        print(f"📊 Price Table: analytics.{symbol}_price_profile ({len(price_profile_df)} momentum ranges)")

if __name__ == "__main__":
    main()
