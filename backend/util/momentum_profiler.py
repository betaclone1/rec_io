#!/usr/bin/env python3
"""
MOMENTUM PROFILER

This script analyzes historical momentum data to create percentile-based distribution profiles.
It creates a <symbol>_momentum_profile table in the analytics schema showing the bell curve
of momentum distributions in 1-percentile steps away from the mean.

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
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from backend.core.time_eastern import merge_psycopg2_connect_kwargs

class MomentumProfiler:
    """
    Analyzes historical momentum data to create percentile-based distribution profiles.
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
        self.source_table = f"historical_data.{self.symbol}_price_history"
        self.profile_table = f"analytics.{self.symbol}_momentum_profile"
        
        logger.info(f"✅ Initialized momentum profiler for {self.symbol.upper()}")
    
    def get_postgresql_connection(self):
        """Get PostgreSQL connection"""
        try:
            return psycopg2.connect(**self.db_config)
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
        percentiles = np.arange(0.5, 100, 0.5)  # 0.5, 1.0, 1.5, ..., 99.5
        
        # Calculate weighted percentiles
        weighted_percentiles = []
        for p in percentiles:
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
        
        # Create profile DataFrame
        profile_df = pd.DataFrame({
            'percentile': percentiles,
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
            CREATE TABLE IF NOT EXISTS {self.profile_table} (
                percentile NUMERIC(5,1) PRIMARY KEY,
                momentum_value NUMERIC(10,4) NOT NULL,
                deviation_from_mean NUMERIC(10,4) NOT NULL,
                z_score NUMERIC(10,4) NOT NULL,
                weighted_mean NUMERIC(10,4) NOT NULL,
                weighted_std NUMERIC(10,4) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            
            cursor.execute(create_table_sql)
            conn.commit()
            
            logger.info(f"✅ Created/verified table: {self.profile_table}")
            
        except Exception as e:
            logger.error(f"❌ Error creating table: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def insert_profile_data(self, profile_df: pd.DataFrame):
        """Insert the calculated profile data into the database."""
        conn = self.get_postgresql_connection()
        if not conn:
            raise Exception("Failed to connect to PostgreSQL")
        
        try:
            cursor = conn.cursor()
            
            # Clear existing data
            cursor.execute(f"DELETE FROM {self.profile_table}")
            
            # Insert new profile data
            for _, row in profile_df.iterrows():
                cursor.execute(f"""
                    INSERT INTO {self.profile_table} 
                    (percentile, momentum_value, deviation_from_mean, z_score, weighted_mean, weighted_std)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    float(row['percentile']),
                    float(row['momentum_value']),
                    float(row['deviation_from_mean']),
                    float(row['z_score']),
                    float(row['weighted_mean']),
                    float(row['weighted_std'])
                ))
            
            conn.commit()
            logger.info(f"✅ Inserted {len(profile_df)} percentile records (0.5-99.5) into {self.profile_table}")
            
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
            logger.info(f"   - Percentiles calculated: 0.5-99.5 (0.5 increments)")
            
            return profile_df
            
        except Exception as e:
            logger.error(f"❌ Error generating momentum profile: {e}")
            raise

def main():
    parser = argparse.ArgumentParser(description="Generate momentum profile for historical data")
    parser.add_argument("symbol", nargs='?', default="btc", help="Symbol to process (e.g., btc, eth)")
    parser.add_argument("--start-date", help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date filter (YYYY-MM-DD)")
    parser.add_argument("--list-symbols", action="store_true", help="List available symbols")
    args = parser.parse_args()

    if args.list_symbols:
        # List available symbols (you can implement this if needed)
        print("Available symbols: btc, eth")
        return

    symbol = args.symbol.lower()
    
    # Create profiler and generate profile
    profiler = MomentumProfiler(symbol)
    profile_df = profiler.generate_profile(args.start_date, args.end_date)
    
    print(f"\n✅ Momentum profile generated successfully for {symbol.upper()}")
    print(f"📊 Table: analytics.{symbol}_momentum_profile")
    print(f"📈 Records: {len(profile_df)} percentiles (0.5-99.5)")

if __name__ == "__main__":
    main()
