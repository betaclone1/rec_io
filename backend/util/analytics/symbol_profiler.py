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
        self.movement_profile_table = f"analytics.{self.symbol}_movement_profile"
        self.price_profile_table = f"analytics.{self.symbol}_price_profile"
        self.volatility_profile_table = f"analytics.{self.symbol}_volatility_profile"
        
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

    def load_movement_data(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Load movement data for profile generation (same shape as momentum)."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'historical_data' AND table_name = '{self.symbol}_price_history'
                AND column_name = 'movement'
            """)
            if not cursor.fetchone():
                conn.close()
                raise Exception(f"No movement column in {self.source_table}")
            query = f"""SELECT timestamp, movement FROM {self.source_table} WHERE movement IS NOT NULL"""
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
                raise Exception(f"No movement data found for {self.symbol}")
            df = pd.DataFrame(rows, columns=['timestamp', 'movement'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['movement'] = df['movement'].astype(float)
            logger.info(f"📊 Loaded {len(df)} movement records from {self.symbol} table")
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
    
    def _percentile_profile_from_values(self, values: np.ndarray, weights: np.ndarray, use_centered_scale: bool = True) -> pd.DataFrame:
        """
        Build percentile profile from a value array and weights.
        - use_centered_scale=True (momentum): percentile column -99.5 to +99.5.
        - use_centered_scale=False (movement): percentile column 0.5 to 99.5 (movement is always >= 0).
        """
        weighted_mean = np.average(values, weights=weights)
        weighted_std = np.sqrt(np.average((values - weighted_mean)**2, weights=weights))
        raw_percentiles = np.arange(0.5, 100, 0.5)
        weighted_percentiles = []
        sorted_indices = np.argsort(values)
        sorted_weights = weights[sorted_indices]
        sorted_values = values[sorted_indices]
        cumsum_weights = np.cumsum(sorted_weights)
        for p in raw_percentiles:
            target_weight = p / 100.0
            idx = np.searchsorted(cumsum_weights, target_weight)
            percentile_value = sorted_values[-1] if idx >= len(sorted_values) else sorted_values[idx]
            weighted_percentiles.append(percentile_value)
        percentile_labels = [(p - 50) * 2 for p in raw_percentiles] if use_centered_scale else list(raw_percentiles)
        profile_df = pd.DataFrame({
            'percentile': percentile_labels,
            'momentum_value': weighted_percentiles,
            'deviation_from_mean': [x - weighted_mean for x in weighted_percentiles],
            'z_score': [(x - weighted_mean) / weighted_std for x in weighted_percentiles]
        })
        profile_df['weighted_mean'] = weighted_mean
        profile_df['weighted_std'] = weighted_std
        return profile_df

    def calculate_percentile_profile(self, df: pd.DataFrame, weights: np.ndarray) -> pd.DataFrame:
        """
        Calculate percentile-based momentum profile.
        
        Args:
            df: DataFrame with momentum data
            weights: Array of time weights
            
        Returns:
            DataFrame with percentile profile
        """
        logger.info(f"📈 Calculated percentile profile from momentum values")
        return self._percentile_profile_from_values(df['momentum'].values, weights)
    
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

    def create_movement_profile_table(self):
        """Create the movement profile table (value column is movement_value)."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.movement_profile_table} (
                    percentile NUMERIC(6,1) PRIMARY KEY,
                    movement_value NUMERIC(15,6) NOT NULL,
                    deviation_from_mean NUMERIC(15,6) NOT NULL,
                    z_score NUMERIC(15,6) NOT NULL,
                    weighted_mean NUMERIC(15,6) NOT NULL,
                    weighted_std NUMERIC(15,6) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            logger.info(f"✅ Created/verified table: {self.movement_profile_table}")
        except Exception as e:
            logger.error(f"❌ Error creating movement profile table: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def insert_movement_profile_data(self, profile_df: pd.DataFrame):
        """Insert movement profile data (column movement_value)."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        try:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {self.movement_profile_table}")
            for idx, row in profile_df.iterrows():
                cursor.execute(f"""
                    INSERT INTO {self.movement_profile_table}
                    (percentile, movement_value, deviation_from_mean, z_score, weighted_mean, weighted_std)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (float(row['percentile']), float(row['movement_value']), float(row['deviation_from_mean']),
                      float(row['z_score']), float(row['weighted_mean']), float(row['weighted_std'])))
            conn.commit()
            logger.info(f"✅ Inserted {len(profile_df)} records into {self.movement_profile_table}")
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()

    def generate_movement_profile(self, start_date: str = None, end_date: str = None):
        """Generate movement profile: percentiles 0.5 to 99.5 (movement is always positive)."""
        logger.info(f"🚀 Starting movement profile generation for {self.symbol.upper()}")
        df = self.load_movement_data(start_date, end_date)
        weights = self.calculate_time_weights(df)
        profile_df = self._percentile_profile_from_values(df['movement'].values, weights, use_centered_scale=False)
        profile_df = profile_df.rename(columns={'momentum_value': 'movement_value'})
        self.create_movement_profile_table()
        self.insert_movement_profile_data(profile_df)
        logger.info(f"📊 Movement profile: {len(df)} records, mean={profile_df['weighted_mean'].iloc[0]:.4f}")
        return profile_df
    
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
            
            # Get the latest momentum profile table (with date suffix)
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            profile_table = f"{self.momentum_profile_table}_{date_str}"
            
            # Check if profile table exists, if not try to find the most recent one
            cursor.execute(f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name LIKE '{self.symbol}_momentum_profile_%'
                ORDER BY table_name DESC
                LIMIT 1
            """)
            
            profile_result = cursor.fetchone()
            if profile_result:
                profile_table = f"analytics.{profile_result[0]}"
            else:
                # Try without date suffix as fallback
                profile_table = self.momentum_profile_table
            
            # Load momentum profile data for percentile mapping
            cursor.execute(f"""
                SELECT percentile, momentum_value
                FROM {profile_table}
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
            
            # Get ALL rows that need momentum_percentile assignment (overwrite all, not just NULLs)
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
            rows_to_update = cursor.fetchall()
            
            if not rows_to_update:
                logger.info(f"ℹ️ No rows need momentum_percentile assignment for {self.symbol.upper()}")
                return 0
            
            logger.info(f"📊 Found {len(rows_to_update)} rows for momentum_percentile assignment")
            
            # First, set all momentum_percentile to NULL to ensure clean overwrite
            update_query = f"UPDATE {self.source_table} SET momentum_percentile = NULL WHERE momentum IS NOT NULL"
            if start_date or end_date:
                update_query += " AND"
                if start_date:
                    update_query += " timestamp >= %s"
                if end_date:
                    if start_date:
                        update_query += " AND"
                    update_query += " timestamp <= %s"
            cursor.execute(update_query, params)
            logger.info(f"📊 Cleared existing momentum_percentile values for {cursor.rowcount} rows")
            
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

    def assign_movement_percentiles(self, start_date: str = None, end_date: str = None):
        """Assign movement percentile from movement profile (same pattern as momentum)."""
        logger.info(f"🚀 Starting movement percentile assignment for {self.symbol.upper()}")
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'historical_data' AND table_name = '{self.symbol}_price_history'
                AND column_name = 'movement_percentile'
            """)
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE {self.source_table} ADD COLUMN movement_percentile NUMERIC(5,1)")
                conn.commit()
            cursor.execute(f"""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'analytics' AND table_name LIKE '{self.symbol}_movement_profile_%'
                ORDER BY table_name DESC LIMIT 1
            """)
            row = cursor.fetchone()
            profile_table = f"analytics.{row[0]}" if row else self.movement_profile_table
            cursor.execute(f"SELECT percentile, movement_value FROM {profile_table} ORDER BY percentile")
            profile_data = cursor.fetchall()
            if not profile_data:
                logger.warning(f"No movement profile found for {self.symbol}")
                conn.close()
                return 0
            percentile_mapping = {mv: pct for pct, mv in profile_data}
            query = f"SELECT timestamp, movement FROM {self.source_table} WHERE movement IS NOT NULL"
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
                conn.close()
                return 0
            batch_size = 1000
            total_updated = 0
            for i in range(0, len(rows_to_update), batch_size):
                batch = rows_to_update[i:i + batch_size]
                updates = []
                for timestamp, movement in batch:
                    closest = min(percentile_mapping.keys(), key=lambda x: abs(x - movement))
                    updates.append((percentile_mapping[closest], timestamp))
                if updates:
                    cursor.executemany(f"""
                        UPDATE {self.source_table} SET movement_percentile = %s WHERE timestamp = %s
                    """, updates)
                    total_updated += len(updates)
            conn.commit()
            logger.info(f"✅ Assigned movement_percentile to {total_updated} rows")
            return total_updated
        except Exception as e:
            logger.error(f"❌ Error assigning movement percentiles: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def load_volatility_data(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        Load volatility data from the historical price table.
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
            
        Returns:
            DataFrame with timestamp and volatility data
        """
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Check if volatility column exists
            cursor.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'historical_data' 
                AND table_name = '{self.symbol}_price_history' 
                AND column_name = 'volatility'
            """)
            
            if not cursor.fetchone():
                logger.warning(f"⚠️ Volatility column does not exist in {self.source_table}")
                return pd.DataFrame()
            
            # Build query with optional date filters
            query = f"""
                SELECT timestamp, volatility
                FROM {self.source_table}
                WHERE volatility IS NOT NULL
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
                logger.warning(f"⚠️ No volatility data found for {self.symbol}")
                return pd.DataFrame()
            
            # Convert to DataFrame
            df = pd.DataFrame(rows, columns=['timestamp', 'volatility'])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['volatility'] = df['volatility'].astype(float)
            
            logger.info(f"📊 Loaded {len(df)} volatility records from {self.symbol} table")
            return df
            
        except Exception as e:
            logger.error(f"Error loading volatility data: {e}")
            return pd.DataFrame()
        finally:
            conn.close()
    
    def calculate_volatility_percentile_profile(self, df: pd.DataFrame, weights: np.ndarray) -> pd.DataFrame:
        """
        Calculate percentile-based volatility profile.
        Uses positive percentiles (0.5 to 99.5) since volatility is always positive.
        
        Args:
            df: DataFrame with volatility data
            weights: Array of time weights
            
        Returns:
            DataFrame with percentile profile
        """
        volatility_values = df['volatility'].values
        
        # Calculate weighted statistics
        weighted_mean = np.average(volatility_values, weights=weights)
        weighted_std = np.sqrt(np.average((volatility_values - weighted_mean)**2, weights=weights))
        
        # Calculate percentiles (0.5th to 99.5th percentile in 0.5 increments)
        raw_percentiles = np.arange(0.5, 100, 0.5)  # 0.5, 1.0, 1.5, ..., 99.5
        
        # Calculate weighted percentiles
        weighted_percentiles = []
        for p in raw_percentiles:
            # Use weighted quantile calculation
            sorted_indices = np.argsort(volatility_values)
            sorted_weights = weights[sorted_indices]
            sorted_values = volatility_values[sorted_indices]
            
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
        
        # For volatility, use positive percentiles (0.5 to 99.5)
        # No centering transformation needed
        
        # Create profile DataFrame
        profile_df = pd.DataFrame({
            'percentile': raw_percentiles,  # Positive percentiles (0.5 to 99.5)
            'volatility_value': weighted_percentiles,
            'deviation_from_mean': [p - weighted_mean for p in weighted_percentiles],
            'z_score': [(p - weighted_mean) / weighted_std for p in weighted_percentiles]
        })
        
        # Add summary statistics
        profile_df['weighted_mean'] = weighted_mean
        profile_df['weighted_std'] = weighted_std
        
        logger.info(f"📈 Calculated volatility percentile profile: mean={weighted_mean:.6f}, std={weighted_std:.6f}")
        return profile_df
    
    def create_volatility_profile_table(self):
        """Create the volatility profile table in the analytics schema."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Get current date for table name
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            table_name = f"{self.volatility_profile_table}_{date_str}"
            
            # Create the profile table
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                percentile NUMERIC(5,1) PRIMARY KEY,
                volatility_value NUMERIC(15,6) NOT NULL,
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
            
            logger.info(f"✅ Created/verified table: {table_name}")
            return table_name
            
        except Exception as e:
            logger.error(f"❌ Error creating volatility profile table: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def insert_volatility_profile_data(self, profile_df: pd.DataFrame, table_name: str):
        """Insert the calculated volatility profile data into the database."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Clear existing data
            cursor.execute(f"DELETE FROM {table_name}")
            logger.info(f"Cleared existing data from {table_name}")
            
            # Insert new profile data
            inserted_count = 0
            for idx, row in profile_df.iterrows():
                try:
                    # Convert values to proper types
                    percentile = float(row['percentile'])
                    volatility_value = float(row['volatility_value'])
                    deviation_from_mean = float(row['deviation_from_mean'])
                    z_score = float(row['z_score'])
                    weighted_mean = float(row['weighted_mean'])
                    weighted_std = float(row['weighted_std'])
                    
                    cursor.execute(f"""
                        INSERT INTO {table_name} 
                        (percentile, volatility_value, deviation_from_mean, z_score, weighted_mean, weighted_std)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (percentile, volatility_value, deviation_from_mean, z_score, weighted_mean, weighted_std))
                    
                    inserted_count += 1
                    
                    # Log progress every 50 records
                    if inserted_count % 50 == 0:
                        logger.info(f"Inserted {inserted_count} records...")
                        
                except Exception as row_error:
                    logger.error(f"❌ Error inserting row {idx}: {row_error}")
                    logger.error(f"Row data: {row.to_dict()}")
                    continue
            
            conn.commit()
            logger.info(f"✅ Inserted {inserted_count} volatility profile records into {table_name}")
            
        except Exception as e:
            logger.error(f"❌ Error inserting volatility profile data: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def generate_volatility_profile(self, start_date: str = None, end_date: str = None):
        """
        Generate the complete volatility profile.
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
        """
        logger.info(f"🚀 Starting volatility profile generation for {self.symbol.upper()}")
        
        try:
            # Load volatility data
            df = self.load_volatility_data(start_date, end_date)
            
            if df.empty:
                raise Exception(f"No volatility data found for {self.symbol}")
            
            # Calculate time weights
            weights = self.calculate_time_weights(df)
            
            # Calculate percentile profile
            profile_df = self.calculate_volatility_percentile_profile(df, weights)
            
            # Create table if needed
            table_name = self.create_volatility_profile_table()
            
            # Insert profile data
            self.insert_volatility_profile_data(profile_df, table_name)
            
            # Log summary statistics
            logger.info(f"📊 Volatility Profile Summary:")
            logger.info(f"   - Total records analyzed: {len(df)}")
            logger.info(f"   - Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
            logger.info(f"   - Volatility range: {df['volatility'].min():.6f} to {df['volatility'].max():.6f}")
            logger.info(f"   - Weighted mean: {profile_df['weighted_mean'].iloc[0]:.6f}")
            logger.info(f"   - Weighted std: {profile_df['weighted_std'].iloc[0]:.6f}")
            logger.info(f"   - Percentiles calculated: 0.5 to 99.5 (0.5 increments)")
            
            return profile_df
            
        except Exception as e:
            logger.error(f"❌ Error generating volatility profile: {e}")
            raise
    
    def assign_volatility_percentiles(self, start_date: str = None, end_date: str = None):
        """
        Assign volatility percentile values to ALL rows in the master price table.
        OVERWRITES all existing volatility_percentile values (not just NULLs).
        
        Args:
            start_date: Optional start date filter (YYYY-MM-DD)
            end_date: Optional end date filter (YYYY-MM-DD)
        """
        logger.info(f"🚀 Starting volatility percentile assignment for {self.symbol.upper()}")
        
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # First, check if volatility_percentile column exists, create if not
            cursor.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'historical_data' 
                AND table_name = '{self.symbol}_price_history' 
                AND column_name = 'volatility_percentile'
            """)
            
            if not cursor.fetchone():
                logger.info(f"📊 Adding volatility_percentile column to {self.source_table}")
                cursor.execute(f"""
                    ALTER TABLE {self.source_table} 
                    ADD COLUMN volatility_percentile DECIMAL(5,1)
                """)
                conn.commit()
                logger.info(f"✅ Added volatility_percentile column")
            
            # Get the latest volatility profile table
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d")
            profile_table = f"{self.volatility_profile_table}_{date_str}"
            
            # Check if profile table exists, if not try to find the most recent one
            cursor.execute(f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name LIKE '{self.symbol}_volatility_profile_%'
                ORDER BY table_name DESC
                LIMIT 1
            """)
            
            profile_result = cursor.fetchone()
            if profile_result:
                profile_table = f"analytics.{profile_result[0]}"
            else:
                raise Exception(f"No volatility profile table found for {self.symbol}")
            
            # Load volatility profile data for percentile mapping
            cursor.execute(f"""
                SELECT percentile, volatility_value
                FROM {profile_table}
                ORDER BY percentile
            """)
            
            profile_data = cursor.fetchall()
            if not profile_data:
                raise Exception(f"No volatility profile data found in {profile_table}")
            
            # Create percentile mapping dictionary
            percentile_mapping = {}
            for row in profile_data:
                percentile, volatility_value = row
                percentile_mapping[volatility_value] = percentile
            
            # Get ALL rows that need volatility_percentile assignment (overwrite all, not just NULLs)
            query = f"""
                SELECT timestamp, volatility
                FROM {self.source_table}
                WHERE volatility IS NOT NULL
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
                logger.info(f"ℹ️ No rows need volatility_percentile assignment for {self.symbol.upper()}")
                return 0
            
            logger.info(f"📊 Found {len(rows_to_update)} rows for volatility_percentile assignment")
            
            # First, set all volatility_percentile to NULL to ensure clean overwrite
            update_query = f"UPDATE {self.source_table} SET volatility_percentile = NULL WHERE volatility IS NOT NULL"
            if start_date or end_date:
                update_query += " AND"
                if start_date:
                    update_query += " timestamp >= %s"
                if end_date:
                    if start_date:
                        update_query += " AND"
                    update_query += " timestamp <= %s"
            cursor.execute(update_query, params)
            logger.info(f"📊 Cleared existing volatility_percentile values for {cursor.rowcount} rows")
            
            # Process rows in batches
            batch_size = 1000
            total_updated = 0
            
            for i in range(0, len(rows_to_update), batch_size):
                batch = rows_to_update[i:i + batch_size]
                
                # Find the closest volatility value in the profile for each row using linear interpolation
                updates = []
                for timestamp, volatility in batch:
                    if volatility is None:
                        continue
                    
                    # Use linear interpolation to find percentile
                    sorted_profile = sorted(percentile_mapping.items())
                    volatility_values = [v for v, _ in sorted_profile]
                    percentiles = [p for _, p in sorted_profile]
                    
                    # Find where this volatility value fits
                    if volatility <= volatility_values[0]:
                        assigned_percentile = percentiles[0]
                    elif volatility >= volatility_values[-1]:
                        assigned_percentile = percentiles[-1]
                    else:
                        # Linear interpolation
                        for j in range(len(volatility_values) - 1):
                            if volatility_values[j] <= volatility <= volatility_values[j + 1]:
                                v0, v1 = volatility_values[j], volatility_values[j + 1]
                                p0, p1 = percentiles[j], percentiles[j + 1]
                                # Interpolate
                                t = (volatility - v0) / (v1 - v0)
                                assigned_percentile = p0 + t * (p1 - p0)
                                break
                        else:
                            assigned_percentile = percentiles[-1]
                    
                    updates.append((assigned_percentile, timestamp))
                
                # Update the batch
                if updates:
                    cursor.executemany(f"""
                        UPDATE {self.source_table} 
                        SET volatility_percentile = %s 
                        WHERE timestamp = %s
                    """, updates)
                    
                    batch_updated = len(updates)
                    total_updated += batch_updated
                    
                    logger.info(f"📊 Updated batch {i//batch_size + 1}: {batch_updated} rows")
            
            conn.commit()
            logger.info(f"✅ Successfully assigned volatility_percentile to {total_updated} rows")
            
            return total_updated
            
        except Exception as e:
            logger.error(f"❌ Error assigning volatility percentiles: {e}")
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
