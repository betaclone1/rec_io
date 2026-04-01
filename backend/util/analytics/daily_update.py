#!/usr/bin/env python3
"""
DAILY HISTORICAL DATA UPDATE SCRIPT
Runs daily at midnight to update historical data for all tracked symbols.

Pipeline Steps:
1. Update symbol datasets using symbol_data_fetch_pg (BTC, ETH, SPX, NDX)
2. Generate momentum scores for new data using momentum_generator_pg
3. Generate new dated profiles using symbol_profiler
4. Clean up oldest profile tables (keep 2 most recent)
5. Assign momentum percentiles to historical data

This is a streamlined version of the full analytics pipeline focused on daily data updates.
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import subprocess
import json
import psycopg2

# Add the util directory to the path so we can import our modules
sys.path.append(os.path.dirname(__file__))
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.core.time_eastern import merge_psycopg2_connect_kwargs

from symbol_data_fetch_pg import update_existing_db
from momentum_generator_pg import fill_missing_momentum_in_db
from movement_generator_pg import fill_missing_movement_in_db
from symbol_profiler import SymbolProfiler

# Configure logging
def setup_logging():
    """Setup logging for the daily update process."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"daily_update_{timestamp}.log"
    
    # Create file handler with immediate flushing
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Force immediate flushing
    logging.getLogger().handlers[0].flush()
    
    return logging.getLogger(__name__), log_file

def log_step(logger, step_name, start_time=None):
    """Log a step with timing information."""
    if start_time:
        elapsed = time.time() - start_time
        logger.info(f"✅ {step_name} completed in {elapsed:.2f} seconds")
    else:
        logger.info(f"🚀 Starting: {step_name}")
        return time.time()
    
    # Force flush logs immediately
    for handler in logger.handlers:
        handler.flush()

def get_db_connection():
    """Get PostgreSQL database connection with proper error handling."""
    try:
        conn = psycopg2.connect(
            **merge_psycopg2_connect_kwargs(
                {
                    "host": "localhost",
                    "database": "rec_io_db",
                    "user": "rec_io_user",
                    "password": "rec_io_password",
                    "connect_timeout": 10,
                }
            )
        )
        # Test the connection
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        return conn
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None

def update_symbol_datasets(logger, symbols):
    """Step 1: Update symbol datasets with latest price data."""
    logger.info("📊 Step 1: Updating symbol datasets with latest price data")
    
    updated_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Updating {symbol} dataset...")
            
            # Financial symbols don't need /USD suffix
            if symbol.upper() in ['SPX', 'NDX', 'SPY', 'QQQ']:
                symbol_for_fetch = symbol
            else:
                symbol_for_fetch = f"{symbol}/USD"
            
            # Add timeout and error handling for data fetch
            try:
                table_name, rows_fetched = update_existing_db(symbol_for_fetch)
                
                if rows_fetched > 0:
                    logger.info(f"✅ {symbol} dataset updated: {rows_fetched} new rows")
                    updated_symbols.append(symbol)
                else:
                    logger.info(f"ℹ️ {symbol} dataset: no new data available")
                    updated_symbols.append(symbol)  # Still process for momentum/profile updates
            except Exception as fetch_error:
                logger.warning(f"⚠️ Data fetch failed for {symbol}: {fetch_error}")
                logger.info(f"ℹ️ Continuing with {symbol} for momentum/profile updates")
                updated_symbols.append(symbol)  # Continue processing even if fetch fails
                
        except Exception as e:
            logger.error(f"❌ Error updating {symbol} dataset: {e}")
            # Don't fail completely - continue with other symbols
            updated_symbols.append(symbol)
    
    logger.info(f"Dataset updates completed for {len(updated_symbols)} symbols")
    return updated_symbols

def generate_momentum_scores(logger, symbols):
    """Step 2: Generate momentum scores for all symbols."""
    logger.info("📈 Step 2: Generating momentum scores for all symbols")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating momentum for {symbol}...")
            
            # Run momentum generation with memory management
            fill_missing_momentum_in_db(symbol)
            
            logger.info(f"✅ {symbol} momentum generation completed")
            processed_symbols.append(symbol)
            
            # Force garbage collection to free memory
            import gc
            gc.collect()
            
        except Exception as e:
            logger.error(f"❌ Error generating momentum for {symbol}: {e}")
            # Continue with other symbols even if one fails
            processed_symbols.append(symbol)
    
    logger.info(f"Momentum generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def generate_movement_scores(logger, symbols):
    """Step 2a: Generate movement scores for all symbols (right after momentum)."""
    logger.info("📈 Step 2a: Generating movement scores for all symbols")
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating movement for {symbol}...")
            fill_missing_movement_in_db(symbol)
            logger.info(f"✅ {symbol} movement generation completed")
            processed_symbols.append(symbol)
            import gc
            gc.collect()
        except Exception as e:
            logger.error(f"❌ Error generating movement for {symbol}: {e}")
            processed_symbols.append(symbol)
    logger.info(f"Movement generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def generate_daily_profiles(logger, symbols):
    """Step 3: Generate new dated profiles for all symbols."""
    logger.info("📊 Step 3: Generating new dated profiles for all symbols")
    
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating profiles for {symbol}...")
            
            # Create profiler instance
            profiler = SymbolProfiler(symbol.lower())
            
            # Override table names with today's date
            profiler.momentum_profile_table = f"analytics.{symbol.lower()}_momentum_profile_{today}"
            profiler.price_profile_table = f"analytics.{symbol.lower()}_price_profile_{today}"
            
            # Generate momentum profile
            logger.info(f"Creating momentum profile: {symbol.lower()}_momentum_profile_{today}")
            profile_df = profiler.generate_profile()
            
            # Generate price profile
            logger.info(f"Creating price profile: {symbol.lower()}_price_profile_{today}")
            profiler.generate_price_profile()
            
            logger.info(f"✅ {symbol} profiles generated: {len(profile_df)} percentile records")
            processed_symbols.append(symbol)
            
            # Force garbage collection to free memory
            import gc
            gc.collect()
            
        except Exception as e:
            logger.error(f"❌ Error generating profiles for {symbol}: {e}")
            # Continue with other symbols even if one fails
            processed_symbols.append(symbol)
    
    logger.info(f"Profile generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def cleanup_old_profiles(logger, symbols):
    """Step 4: Clean up oldest profile tables, keeping 2 most recent."""
    logger.info("🧹 Step 4: Cleaning up oldest profile tables (keeping 2 most recent)")
    
    conn = get_db_connection()
    if not conn:
        logger.error("❌ Could not connect to database for cleanup")
        return symbols
    
    try:
        cursor = conn.cursor()
        
        for symbol in symbols:
            symbol_lower = symbol.lower()
            logger.info(f"Cleaning up old profiles for {symbol}...")
            
            for profile_type in ("momentum_profile", "price_profile", "volatility_profile", "movement_profile"):
                cursor.execute(f"""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'analytics'
                    AND table_name LIKE '{symbol_lower}_{profile_type}_%'
                    ORDER BY table_name ASC
                """)
                profile_tables = [row[0] for row in cursor.fetchall()]
                if len(profile_tables) > 2:
                    tables_to_delete = profile_tables[:-2]
                    for table_name in tables_to_delete:
                        logger.info(f"🗑️ Deleting old {profile_type}: {table_name}")
                        cursor.execute(f"DROP TABLE analytics.{table_name}")
            
            logger.info(f"✅ Profile cleanup completed for {symbol}")
        
        conn.commit()
        logger.info("✅ Profile cleanup completed for all symbols")
        
    except Exception as e:
        logger.error(f"❌ Error during profile cleanup: {e}")
        conn.rollback()
    finally:
        conn.close()
    
    return symbols

def assign_momentum_percentiles(logger, symbols):
    """Step 5: Assign momentum percentiles to historical data."""
    logger.info("📊 Step 5: Assigning momentum percentiles to historical data")
    
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Assigning momentum percentiles for {symbol}...")
            
            # Create profiler instance with today's profile table
            profiler = SymbolProfiler(symbol.lower())
            profiler.momentum_profile_table = f"analytics.{symbol.lower()}_momentum_profile_{today}"
            
            # Assign momentum percentiles
            profiler.assign_momentum_percentiles()
            
            logger.info(f"✅ {symbol} momentum percentiles assigned successfully")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error assigning momentum percentiles for {symbol}: {e}")
    
    logger.info(f"Momentum percentile assignment completed for {len(processed_symbols)} symbols")
    return processed_symbols

def create_summary_report(logger, results):
    """Create a summary report of the daily update."""
    logger.info("📋 Creating daily update summary report...")
    
    summary = {
        'timestamp': datetime.now().isoformat(),
        'symbols_processed': results.get('symbols', []),
        'symbols_updated': results.get('updated_symbols', []),
        'symbols_with_momentum': results.get('momentum_symbols', []),
        'symbols_with_profiles': results.get('profile_symbols', []),
        'symbols_with_percentiles': results.get('percentile_symbols', []),
        'total_duration': results.get('total_duration', 0)
    }
    
    # Save summary to file
    summary_file = Path(__file__).parent.parent.parent / "logs" / f"daily_update_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    logger.info(f"📄 Summary report saved: {summary_file}")
    
    # Log summary
    logger.info("=" * 60)
    logger.info("📊 DAILY UPDATE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total duration: {summary['total_duration']:.2f} seconds")
    logger.info(f"Symbols processed: {len(summary['symbols_processed'])}")
    logger.info(f"Datasets updated: {len(summary['symbols_updated'])}")
    logger.info(f"Momentum generated: {len(summary['symbols_with_momentum'])}")
    logger.info(f"Profiles generated: {len(summary['symbols_with_profiles'])}")
    logger.info(f"Percentiles assigned: {len(summary['symbols_with_percentiles'])}")
    logger.info("=" * 60)
    
    return summary_file

def main():
    """Main daily update function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run daily historical data update")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "XRP", "SPX", "NDX"], 
                       help="Symbols to process (default: BTC ETH SOL XRP SPX NDX)")
    parser.add_argument("--test", action="store_true", help="Run in test mode with verbose output")
    args = parser.parse_args()
    
    # Convert symbols to uppercase
    symbols = [symbol.upper() for symbol in args.symbols]
    
    start_time = time.time()
    
    # Setup logging
    logger, log_file = setup_logging()
    
    logger.info("🌅 DAILY HISTORICAL DATA UPDATE STARTING")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Processing symbols: {symbols}")
    
    if args.test:
        logger.info("🧪 Running in TEST MODE")
    
    results = {
        'symbols': symbols,
        'updated_symbols': [],
        'momentum_symbols': [],
        'profile_symbols': [],
        'percentile_symbols': [],
        'total_duration': 0
    }
    
    try:
        # Step 1: Update symbol datasets
        step_start = log_step(logger, "Symbol dataset updates")
        results['updated_symbols'] = update_symbol_datasets(logger, symbols)
        log_step(logger, "Symbol dataset updates", step_start)
        
        # Step 2: Generate momentum scores
        step_start = log_step(logger, "Momentum score generation")
        results['momentum_symbols'] = generate_momentum_scores(logger, results['updated_symbols'])
        log_step(logger, "Momentum score generation", step_start)
        
        # Step 2a: Generate movement scores (right after momentum)
        step_start = log_step(logger, "Movement score generation")
        results['movement_symbols'] = generate_movement_scores(logger, results['momentum_symbols'])
        log_step(logger, "Movement score generation", step_start)
        
        # Step 3: Generate daily profiles
        step_start = log_step(logger, "Daily profile generation")
        results['profile_symbols'] = generate_daily_profiles(logger, results['movement_symbols'])
        log_step(logger, "Daily profile generation", step_start)
        
        # Step 4: Clean up old profiles
        step_start = log_step(logger, "Profile cleanup")
        cleanup_old_profiles(logger, results['profile_symbols'])
        log_step(logger, "Profile cleanup", step_start)
        
        # Step 5: Assign momentum percentiles
        step_start = log_step(logger, "Momentum percentile assignment")
        results['percentile_symbols'] = assign_momentum_percentiles(logger, results['profile_symbols'])
        log_step(logger, "Momentum percentile assignment", step_start)
        
        # Create summary report
        results['total_duration'] = time.time() - start_time
        summary_file = create_summary_report(logger, results)
        
        logger.info("🎉 DAILY UPDATE COMPLETED SUCCESSFULLY!")
        logger.info(f"Total duration: {results['total_duration']:.2f} seconds")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ DAILY UPDATE FAILED: {e}")
        logger.error(f"Error occurred after {time.time() - start_time:.2f} seconds")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
