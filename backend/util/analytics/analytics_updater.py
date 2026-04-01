#!/usr/bin/env python3
"""
WEEKLY DATA UPDATE SCRIPT - POSTGRESQL VERSION
Runs every Saturday at 11:59:59 PM to update the entire data pipeline.

Pipeline Steps:
1. Update symbol master 5y datasets using symbol_data_fetch_pg (PostgreSQL)
2. Run momentum generator on new master datasets using momentum_generator_pg (PostgreSQL)
3. Generate momentum profiles using symbol_profiler (PostgreSQL)
4. Assign momentum percentiles to master datasets
5. Confirm new data is complete (5 years of 1m candlestick data, all rows with momentum score)
6. Archive existing fingerprint files with dated zip file
7. Run fingerprint_generator_postgresql to generate updated percentile-based fingerprints (PostgreSQL)
8. Run probability_lookup_generator to generate probability lookup tables (PostgreSQL)
9. Record log of operations for review
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
import pandas as pd
import subprocess
import json

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
from fingerprint_archiver import create_archive, find_fingerprint_files
from volatility_generator_pg import fill_missing_volatility_in_db

def is_weekday_9am_to_12pm(timestamp_str):
    """
    Check if timestamp is a weekday between 9:00 AM and 12:00 PM East Coast time.
    
    Args:
        timestamp_str: Timestamp string in format 'YYYY-MM-DD HH:MM:SS'
        
    Returns:
        bool: True if weekday between 9am-12pm East Coast time
    """
    # Parse timestamp (assume it's already in East Coast time since that's how we store it)
    dt = pd.to_datetime(timestamp_str)
    
    # Check if it's a weekday (Monday=0, Sunday=6)
    is_weekday = dt.weekday() < 5  # Monday=0 to Friday=4
    
    # Check if time is between 9:00 AM and 12:00 PM
    time_9am = dt_time(9, 0, 0)
    time_12pm = dt_time(12, 0, 0)
    is_business_hours = time_9am <= dt.time() < time_12pm
    
    return is_weekday and is_business_hours

# Configure logging
def setup_logging():
    """Setup logging for the weekly update process."""
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"weekly_update_{timestamp}.log"
    
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

def log_table_operation(logger, operation, symbol, table_name, details=""):
    """Log table-specific operations with detailed information."""
    message = f"TABLE: {operation} - {symbol.upper()} - {table_name}"
    if details:
        message += f" - {details}"
    logger.info(message)
    
    # Force flush logs immediately
    for handler in logger.handlers:
        handler.flush()

def get_symbols_from_db():
    """Get list of symbols from PostgreSQL database."""
    try:
        from momentum_generator_pg import get_symbols_from_db
        symbols = get_symbols_from_db()
        return [symbol.upper() for symbol in symbols] if symbols else []
    except Exception as e:
        print(f"Error getting symbols from database: {e}")
        return []

def update_symbol_datasets(logger, symbols):
    """Step 1: Update symbol master 5y datasets using symbol_data_fetch_pg."""
    logger.info("📊 Step 1: Updating symbol master datasets in PostgreSQL")
    
    logger.info(f"Processing symbols: {symbols}")
    
    updated_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Updating {symbol} dataset in PostgreSQL...")
            log_table_operation(logger, "UPDATING", symbol, f"{symbol.lower()}_price_history", "Starting price data update")
            
            # Update the dataset in PostgreSQL
            # Financial symbols don't need /USD suffix
            if symbol.upper() in ['SPX', 'NDX', 'SPY', 'QQQ']:
                symbol_for_fetch = symbol
            else:
                symbol_for_fetch = f"{symbol}/USD"
            
            table_name, rows_fetched = update_existing_db(symbol_for_fetch)
            
            if rows_fetched > 0:
                logger.info(f"✅ {symbol} dataset updated successfully: {rows_fetched} new rows")
                log_table_operation(logger, "COMPLETED", symbol, f"{symbol.lower()}_price_history", f"{rows_fetched} new rows added")
                updated_symbols.append(symbol)
            else:
                logger.warning(f"⚠️ {symbol} dataset update: no new data")
                log_table_operation(logger, "NO_UPDATE", symbol, f"{symbol.lower()}_price_history", "No new data available")
                
        except Exception as e:
            logger.error(f"❌ Error updating {symbol} dataset: {e}")
    
    logger.info(f"Updated {len(updated_symbols)} symbols: {updated_symbols}")
    return updated_symbols

def run_momentum_generation(logger, symbols):
    """Step 2: Run momentum generator on new master datasets using momentum_generator_pg."""
    logger.info("📈 Step 2: Running momentum generation in PostgreSQL")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating momentum for {symbol} in PostgreSQL...")
            log_table_operation(logger, "PROCESSING", symbol, f"{symbol.lower()}_price_history", "Calculating momentum values")
            
            # Run momentum generation in PostgreSQL
            fill_missing_momentum_in_db(symbol)
            
            logger.info(f"✅ {symbol} momentum generation completed")
            log_table_operation(logger, "COMPLETED", symbol, f"{symbol.lower()}_price_history", "Momentum calculation finished")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating momentum for {symbol}: {e}")
    
    logger.info(f"Momentum generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def run_movement_generation(logger, symbols):
    """Step 2a: Run movement generator on master datasets (right after momentum)."""
    logger.info("📈 Step 2a: Running movement generation in PostgreSQL")
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating movement for {symbol} in PostgreSQL...")
            log_table_operation(logger, "PROCESSING", symbol, f"{symbol.lower()}_price_history", "Calculating movement values")
            fill_missing_movement_in_db(symbol)
            logger.info(f"✅ {symbol} movement generation completed")
            log_table_operation(logger, "COMPLETED", symbol, f"{symbol.lower()}_price_history", "Movement calculation finished")
            processed_symbols.append(symbol)
        except Exception as e:
            logger.error(f"❌ Error generating movement for {symbol}: {e}")
    logger.info(f"Movement generation completed for {len(processed_symbols)} symbols")
    return processed_symbols


def run_volatility_generation(logger, symbols):
    """Step 2b: Run volatility generator on master datasets using volatility_generator_pg."""
    logger.info("📊 Step 2b: Running volatility generation in PostgreSQL")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating volatility for {symbol} in PostgreSQL...")
            log_table_operation(logger, "PROCESSING", symbol, f"{symbol.lower()}_price_history", "Calculating volatility values")
            
            # Run volatility generation in PostgreSQL
            fill_missing_volatility_in_db(symbol)
            
            logger.info(f"✅ {symbol} volatility generation completed")
            log_table_operation(logger, "COMPLETED", symbol, f"{symbol.lower()}_price_history", "Volatility calculation finished")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating volatility for {symbol}: {e}")
    
    logger.info(f"Volatility generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def generate_momentum_profiles(logger, symbols):
    """Step 3: Generate momentum and price profiles using symbol_profiler."""
    logger.info("📊 Step 3: Generating momentum and price profiles in PostgreSQL")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating profiles for {symbol}...")
            
            # Create profiler and generate profile
            profiler = SymbolProfiler(symbol.lower())
            
            # Generate momentum profile
            from datetime import datetime
            today = datetime.now().strftime("%Y%m%d")
            momentum_table = f"{symbol.lower()}_momentum_profile_{today}"
            price_table = f"{symbol.lower()}_price_profile_{today}"
            
            log_table_operation(logger, "CREATING", symbol, momentum_table, "Generating momentum profile")
            profile_df = profiler.generate_profile()
            log_table_operation(logger, "COMPLETED", symbol, momentum_table, f"{len(profile_df)} percentile records")
            
            # Generate price profile
            log_table_operation(logger, "CREATING", symbol, price_table, "Generating price profile")
            profiler.generate_price_profile()
            log_table_operation(logger, "COMPLETED", symbol, price_table, "Price profile generated")
            
            logger.info(f"✅ {symbol} momentum and price profiles generated: {len(profile_df)} percentiles")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating profiles for {symbol}: {e}")
    
    logger.info(f"Profile generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def generate_volatility_profiles(logger, symbols):
    """Step 3b: Generate volatility percentile profiles using symbol_profiler."""
    logger.info("📊 Step 3b: Generating volatility percentile profiles in PostgreSQL")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating volatility profile for {symbol}...")
            
            # Create profiler and generate volatility profile
            profiler = SymbolProfiler(symbol.lower())
            
            # Generate volatility profile
            from datetime import datetime
            today = datetime.now().strftime("%Y%m%d")
            volatility_table = f"{symbol.lower()}_volatility_profile_{today}"
            
            log_table_operation(logger, "CREATING", symbol, volatility_table, "Generating volatility profile")
            profile_df = profiler.generate_volatility_profile()
            log_table_operation(logger, "COMPLETED", symbol, volatility_table, f"{len(profile_df)} percentile records")
            
            logger.info(f"✅ {symbol} volatility profile generated: {len(profile_df)} percentiles")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating volatility profile for {symbol}: {e}")
    
    logger.info(f"Volatility profile generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def generate_movement_profiles(logger, symbols, weekday_filter=False):
    """Generate movement profiles (formatted like MOMENTUM profile, using movement data)."""
    logger.info("📊 Generating movement profiles")
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    suffix = "_weekday" if weekday_filter else ""
    processed_symbols = []
    for symbol in symbols:
        try:
            profiler = SymbolProfiler(symbol.lower())
            profiler.movement_profile_table = f"analytics.{symbol.lower()}_movement_profile_{today}{suffix}"
            profiler.generate_movement_profile()
            processed_symbols.append(symbol)
        except Exception as e:
            logger.error(f"❌ Error generating movement profile for {symbol}: {e}")
    logger.info(f"Movement profile generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def assign_momentum_percentiles(logger, symbols, weekday_filter=False):
    """Step 4: Assign momentum percentiles to price history tables."""
    logger.info("📊 Step 4: Assigning momentum percentiles to price history tables")
    
    if weekday_filter:
        logger.info("📅 Using weekday filter for percentile assignment: Only processing data from weekdays 9:00 AM - 12:00 PM East Coast")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Assigning momentum percentiles for {symbol}...")
            
            # Create profiler instance
            profiler = SymbolProfiler(symbol.lower())
            
            # Override table names with date suffix
            from datetime import datetime
            today = datetime.now().strftime("%Y%m%d")
            suffix = "_weekday" if weekday_filter else ""
            profiler.momentum_profile_table = f"analytics.{symbol.lower()}_momentum_profile_{today}{suffix}"
            
            # Assign momentum percentiles
            profiler.assign_momentum_percentiles()
            
            logger.info(f"✅ {symbol} momentum percentiles assigned successfully")
            processed_symbols.append(symbol)
                
        except Exception as e:
            logger.error(f"❌ Error assigning momentum percentiles for {symbol}: {e}")
    
    logger.info(f"Momentum percentile assignment completed for {len(processed_symbols)} symbols")
    return processed_symbols

def assign_volatility_percentiles(logger, symbols):
    """Step 4b: Assign volatility percentiles to price history tables."""
    logger.info("📊 Step 4b: Assigning volatility percentiles to price history tables")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Assigning volatility percentiles for {symbol}...")
            
            # Create profiler instance
            profiler = SymbolProfiler(symbol.lower())
            
            # Assign volatility percentiles (overwrites all existing values)
            profiler.assign_volatility_percentiles()
            
            logger.info(f"✅ {symbol} volatility percentiles assigned successfully")
            processed_symbols.append(symbol)
                
        except Exception as e:
            logger.error(f"❌ Error assigning volatility percentiles for {symbol}: {e}")
    
    logger.info(f"Volatility percentile assignment completed for {len(processed_symbols)} symbols")
    return processed_symbols

def assign_movement_percentiles(logger, symbols):
    """Assign movement percentiles from movement profile to price history."""
    logger.info("📊 Assigning movement percentiles")
    processed_symbols = []
    for symbol in symbols:
        try:
            profiler = SymbolProfiler(symbol.lower())
            profiler.assign_movement_percentiles()
            processed_symbols.append(symbol)
        except Exception as e:
            logger.error(f"❌ Error assigning movement percentiles for {symbol}: {e}")
    logger.info(f"Movement percentile assignment completed for {len(processed_symbols)} symbols")
    return processed_symbols

def verify_data_completeness(logger, symbols):
    """Step 4: Confirm new data is complete (5 years of 1m candlestick data, all rows with momentum score)."""
    logger.info("🔍 Step 4: Verifying data completeness in PostgreSQL")
    
    verification_results = {}
    
    for symbol in symbols:
        try:
            logger.info(f"Verifying {symbol} dataset in PostgreSQL...")
            
            # Load data from PostgreSQL
            from momentum_generator_pg import load_data_from_db
            df = load_data_from_db(symbol)
            
            # Check data completeness
            total_rows = len(df)
            expected_rows = 5 * 365 * 24 * 60  # 5 years of 1-minute data
            
            # Check date range
            date_range = df['timestamp'].max() - df['timestamp'].min()
            days_covered = date_range.days
            
            # Check momentum completeness
            momentum_complete = df['momentum'].notna().all()
            
            # Check for any missing values in critical columns
            critical_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'momentum']
            missing_data = df[critical_columns].isnull().sum().sum() > 0
            
            verification_results[symbol] = {
                'total_rows': total_rows,
                'expected_rows': expected_rows,
                'days_covered': days_covered,
                'momentum_complete': momentum_complete,
                'missing_data': missing_data,
                'date_range_start': df['timestamp'].min(),
                'date_range_end': df['timestamp'].max()
            }
            
            logger.info(f"✅ {symbol} verification:")
            logger.info(f"   - Rows: {total_rows:,} (expected ~{expected_rows:,})")
            logger.info(f"   - Date range: {days_covered} days")
            logger.info(f"   - Momentum complete: {momentum_complete}")
            logger.info(f"   - Missing data: {missing_data}")
            
        except Exception as e:
            logger.error(f"❌ Error verifying {symbol}: {e}")
            verification_results[symbol] = {'error': str(e)}
    
    return verification_results

def archive_existing_fingerprints(logger, symbols):
    """Step 5: Archive existing fingerprint files with dated zip file."""
    logger.info("📦 Step 5: Archiving existing fingerprint files")
    
    archived_files = {}
    
    for symbol in symbols:
        try:
            logger.info(f"Archiving {symbol} fingerprint files...")
            
            # Find fingerprint files - using absolute path
            project_root = Path(__file__).parent.parent.parent
            fingerprint_dir = project_root / "backend" / "data" / "historical_data" / f"{symbol.lower()}_historical" / "symbol_fingerprints"
            fingerprint_files = find_fingerprint_files(str(fingerprint_dir))
            
            if fingerprint_files:
                # Create archive
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_name = f"{symbol.lower()}_fingerprint_archive_{timestamp}"
                output_dir = project_root / "backend" / "data" / "archives"
                
                archive_path = create_archive(fingerprint_files, str(output_dir), archive_name, symbol.lower())
                
                if archive_path:
                    logger.info(f"✅ {symbol} fingerprints archived: {archive_path}")
                    archived_files[symbol] = archive_path
                else:
                    logger.warning(f"⚠️ Failed to archive {symbol} fingerprints")
            else:
                logger.info(f"ℹ️ No fingerprint files found for {symbol}")
                
        except Exception as e:
            logger.error(f"❌ Error archiving {symbol} fingerprints: {e}")
    
    return archived_files

def generate_new_fingerprints(logger, symbols, weekday_filter=False):
    """Step 7: Run fingerprint_generator_postgresql to generate updated percentile-based fingerprints."""
    logger.info("🔢 Step 7: Generating new percentile-based fingerprint tables in PostgreSQL")
    
    if weekday_filter:
        logger.info("📅 Using weekday filter: Only processing data from weekdays 9:00 AM - 12:00 PM East Coast")
    
    logger.info(f"Generating percentile-based fingerprints for symbols: {symbols}")
    
    # Run fingerprint generation using subprocess with symbol arguments
    # The new fingerprint generator takes symbol names directly
    command = [sys.executable, os.path.join(os.path.dirname(__file__), "fingerprint_generator_postgresql.py")] + symbols
    
    # Add weekday filter argument if enabled
    if weekday_filter:
        command.append("--weekday-filter")
    
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=os.path.dirname(__file__))
    
    # Monitor progress in real-time
    total_tables = len(symbols) * 20  # 20 bucketed fingerprint tables per symbol
    completed_tables = 0
    
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            line = output.strip()
            logger.info(f"FINGERPRINT: {line}")
            print(f"FINGERPRINT: {line}", flush=True)  # Real-time output
            
            # Track actual progress
            if "Processing momentum bucket:" in line:
                completed_tables += 1
                percent = (completed_tables / total_tables) * 100
                logger.info(f"PROGRESS: Step 7 - {completed_tables}/{total_tables} tables ({percent:.1f}%)")
                print(f"PROGRESS: Step 7 - {completed_tables}/{total_tables} tables ({percent:.1f}%)", flush=True)
    
    result = process.poll()
    if result != 0:
        logger.error(f"Fingerprint generation failed with return code: {result}")
        raise Exception(f"Fingerprint generation failed with return code: {result}")
    
    logger.info(f"✅ Percentile-based fingerprint generation completed for all symbols")
    logger.info(f"Fingerprint generation completed for {len(symbols)} symbols")
    return symbols

def generate_momentum_profiles(logger, symbols, weekday_filter=False):
    """Step 3: Generate momentum and price profiles with dated table names."""
    logger.info("📊 Step 3: Generating momentum and price profiles")
    
    if weekday_filter:
        logger.info("📅 Using weekday filter for profile generation: Only processing data from weekdays 9:00 AM - 12:00 PM East Coast")
    
    from datetime import datetime
    
    # Get today's date for table naming
    today = datetime.now().strftime("%Y%m%d")
    
    successful_symbols = []
    
    for symbol in symbols:
        symbol_lower = symbol.lower()
        logger.info(f"🔧 Generating profiles for {symbol.upper()}...")
        
        try:
            # Create SymbolProfiler instance with custom table names
            suffix = "_weekday" if weekday_filter else ""
            momentum_table_name = f"{symbol_lower}_momentum_profile_{today}{suffix}"
            price_table_name = f"{symbol_lower}_price_profile_{today}{suffix}"
            
            # Create profiler and override table names
            profiler = SymbolProfiler(symbol_lower)
            profiler.momentum_profile_table = f"analytics.{momentum_table_name}"
            profiler.price_profile_table = f"analytics.{price_table_name}"
            
            # Generate momentum profile with dated table name
            logger.info(f"📊 Creating momentum profile: {momentum_table_name}")
            profiler.generate_profile()
            
            # Generate price profile with dated table name  
            logger.info(f"📊 Creating price profile: {price_table_name}")
            profiler.generate_price_profile()
            
            logger.info(f"✅ Successfully generated profiles for {symbol.upper()}")
            successful_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating profiles for {symbol.upper()}: {e}")
            continue
    
    logger.info(f"✅ Profile generation completed for {len(successful_symbols)} symbols")
    return successful_symbols

def generate_lookup_tables(logger, symbols, weekday_filter=False):
    """Step 8: Run probability_lookup_generator to generate probability lookup tables."""
    logger.info("📊 Step 8: Generating probability lookup tables in PostgreSQL")
    
    logger.info(f"Generating probability lookup tables for symbols: {symbols}")
    
    # Build command arguments
    command_args = symbols + ["--reset-progress"]
    
    # Add weekday filter argument if enabled
    if weekday_filter:
        command_args.append("--weekday-filter")
    
    # Run lookup table generation using subprocess with symbol arguments
    # The lookup generator takes symbol names directly and has resume capability
    # Always reset progress to ensure fresh generation
    process = subprocess.Popen([
        sys.executable, os.path.join(os.path.dirname(__file__), "probability_lookup_generator.py")
    ] + command_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=os.path.dirname(__file__))
    
    # Monitor progress in real-time
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            line = output.strip()
            logger.info(f"LOOKUP: {line}")
            print(f"LOOKUP: {line}", flush=True)  # Real-time output
            
            # Track actual progress from lookup generator
            if "Generated" in line and "combinations" in line:
                logger.info(f"PROGRESS: Step 8 - {line}")
                print(f"PROGRESS: Step 8 - {line}", flush=True)
    
    result = process.poll()
    if result != 0:
        logger.error(f"Lookup table generation failed with return code: {result}")
        raise Exception(f"Lookup table generation failed with return code: {result}")
    
    logger.info(f"✅ Probability lookup table generation completed for all symbols")
    logger.info(f"Lookup table generation completed for {len(symbols)} symbols")
    return symbols

def create_master_lookup_tables(logger, symbols):
    """Step 9: Create and verify master lookup tables for production use."""
    logger.info("🎯 Step 9: Creating master lookup tables for production use")
    
    import psycopg2
    from datetime import datetime
    
    # Database configuration
    db_config = {
        'host': 'localhost',
        'database': 'rec_io_db',
        'user': 'rec_io_user',
        'password': 'rec_io_password'
    }
    
    # Get today's date for the master table naming
    today = datetime.now().strftime("%Y%m%d")
    
    successful_symbols = []
    
    for symbol in symbols:
        symbol_lower = symbol.lower()
        logger.info(f"🔧 Creating master lookup table for {symbol.upper()}...")
        
        try:
            conn = psycopg2.connect(**merge_psycopg2_connect_kwargs(db_config))
            cursor = conn.cursor()
            
            # Find the most recent timestamped lookup table that was just created
            cursor.execute(f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name LIKE 'probability_lookup_{symbol_lower}_%'
                AND table_name NOT LIKE '%master%'
                AND table_name NOT LIKE '%test%'
                ORDER BY table_name DESC
                LIMIT 1
            """)
            
            result = cursor.fetchone()
            if not result:
                logger.warning(f"⚠️ No timestamped lookup table found for {symbol.upper()}, skipping master table creation")
                conn.close()
                continue
            
            timestamped_table_name = result[0]
            logger.info(f"📋 Found timestamped table: {timestamped_table_name}")
            
            # Check if the timestamped table has data
            cursor.execute(f"SELECT COUNT(*) FROM analytics.{timestamped_table_name}")
            row_count = cursor.fetchone()[0]
            
            if row_count == 0:
                logger.warning(f"⚠️ Timestamped lookup table {timestamped_table_name} is empty, skipping master table creation")
                conn.close()
                continue
            
            # Create master table name
            master_table_name = f"probability_lookup_{symbol_lower}_master_{today}"
            
            # Check if master table already exists
            cursor.execute(f"""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name = '{master_table_name}'
            """)
            
            if cursor.fetchone()[0] > 0:
                logger.info(f"📋 Master table {master_table_name} already exists, skipping creation")
                successful_symbols.append(symbol)
                conn.close()
                continue
            
            # Create the master table by copying the timestamped table
            logger.info(f"📋 Creating master table: {master_table_name}")
            cursor.execute(f"""
                CREATE TABLE analytics.{master_table_name} AS 
                SELECT * FROM analytics.{timestamped_table_name}
            """)
            
            # Create index for optimal performance
            logger.info(f"🔍 Creating index for {master_table_name}")
            cursor.execute(f"""
                CREATE INDEX idx_{master_table_name}_lookup 
                ON analytics.{master_table_name} (ttc_seconds, buffer_points, momentum_bucket)
            """)
            
            # Verify completeness
            logger.info(f"✅ Verifying completeness of {master_table_name}")
            verification_result = verify_lookup_table_completeness(cursor, master_table_name, symbol_lower)
            
            if verification_result['is_complete']:
                logger.info(f"🎉 Master table {master_table_name} created successfully!")
                logger.info(f"📊 TTC Range: {verification_result['ttc_range']}")
                logger.info(f"📊 Momentum Range: {verification_result['momentum_range']}")
                logger.info(f"📊 Buffer Range: {verification_result['buffer_range']}")
                logger.info(f"📊 Total Rows: {verification_result['total_rows']:,}")
                successful_symbols.append(symbol)
            else:
                logger.error(f"❌ Master table {master_table_name} failed verification!")
                logger.error(f"❌ Missing TTC values: {verification_result['missing_ttc']}")
                logger.error(f"❌ Missing momentum values: {verification_result['missing_momentum']}")
                # Drop the incomplete table
                cursor.execute(f"DROP TABLE analytics.{master_table_name}")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"❌ Error creating master lookup table for {symbol.upper()}: {e}")
            if 'conn' in locals():
                conn.close()
    
    logger.info(f"✅ Master lookup table creation completed for {len(successful_symbols)} symbols")
    return successful_symbols

def cleanup_analytics_tables(logger, symbols):
    """Clean up working tables and old master tables after successful analytics update."""
    logger.info("🧹 Starting analytics table cleanup...")
    
    import psycopg2
    from datetime import datetime
    
    # Database configuration
    db_config = {
        'host': 'localhost',
        'database': 'rec_io_db',
        'user': 'rec_io_user',
        'password': 'rec_io_password'
    }
    
    today = datetime.now().strftime("%Y%m%d")
    
    for symbol in symbols:
        symbol_lower = symbol.lower()
        logger.info(f"🧹 Cleaning up tables for {symbol.upper()}...")
        
        try:
            conn = psycopg2.connect(**merge_psycopg2_connect_kwargs(db_config))
            cursor = conn.cursor()
            
            # 1. Delete working tables from current session (timestamped, non-master)
            cursor.execute(f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name LIKE 'probability_lookup_{symbol_lower}_%'
                AND table_name NOT LIKE '%master%'
                ORDER BY table_name DESC
            """)
            
            working_tables = cursor.fetchall()
            for (table_name,) in working_tables:
                logger.info(f"🗑️ Deleting working table: {table_name}")
                cursor.execute(f"DROP TABLE analytics.{table_name}")
            
            # 2. Delete oldest master lookup tables (keep current and previous)
            cursor.execute(f"""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'analytics' 
                AND table_name LIKE 'probability_lookup_{symbol_lower}_master_%'
                ORDER BY table_name ASC
            """)
            
            all_master_tables = [row[0] for row in cursor.fetchall()]
            
            # Delete all but the 2 most recent (delete oldest ones)
            if len(all_master_tables) > 2:
                tables_to_delete = all_master_tables[:-2]  # Keep last 2, delete the rest
                for table_name in tables_to_delete:
                    logger.info(f"🗑️ Deleting old master table: {table_name}")
                    cursor.execute(f"DROP TABLE analytics.{table_name}")
            
            # 3. Delete oldest profile tables (momentum, price, volatility, movement) - keep only latest 2
            for profile_type in ['momentum_profile', 'price_profile', 'volatility_profile', 'movement_profile']:
                cursor.execute(f"""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'analytics' 
                    AND table_name LIKE '{symbol_lower}_{profile_type}_%'
                    ORDER BY table_name ASC
                """)
                
                all_profile_tables = [row[0] for row in cursor.fetchall()]
                
                # Delete all but the 2 most recent (keep last 2, delete the rest)
                if len(all_profile_tables) > 2:
                    tables_to_delete = all_profile_tables[:-2]  # Keep last 2, delete the rest
                    for table_name in tables_to_delete:
                        logger.info(f"🗑️ Deleting old {profile_type} table: {table_name}")
                        cursor.execute(f"DROP TABLE analytics.{table_name}")
            
            conn.commit()
            conn.close()
            logger.info(f"✅ Cleanup completed for {symbol.upper()}")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup for {symbol.upper()}: {e}")
            if 'conn' in locals():
                conn.close()
    
    logger.info("✅ Analytics table cleanup completed")

def verify_lookup_table_completeness(cursor, table_name, symbol):
    """Verify that a lookup table has complete coverage of all required parameters."""
    try:
        # Get basic statistics
        cursor.execute(f"""
            SELECT 
                MIN(ttc_seconds) as min_ttc,
                MAX(ttc_seconds) as max_ttc,
                COUNT(DISTINCT ttc_seconds) as unique_ttc_count,
                MIN(momentum_bucket) as min_momentum,
                MAX(momentum_bucket) as max_momentum,
                COUNT(DISTINCT momentum_bucket) as unique_momentum_count,
                MIN(buffer_points) as min_buffer,
                MAX(buffer_points) as max_buffer,
                COUNT(DISTINCT buffer_points) as unique_buffer_count,
                COUNT(*) as total_rows
            FROM analytics.{table_name}
        """)
        
        stats = cursor.fetchone()
        min_ttc, max_ttc, ttc_count, min_momentum, max_momentum, momentum_count, min_buffer, max_buffer, buffer_count, total_rows = stats
        
        # Check for missing TTC values (should be 0-3600 in 10-second increments = 361 values)
        cursor.execute(f"""
            WITH expected_ttc AS (
                SELECT generate_series(0, 3600, 10) as ttc_seconds
            ),
            actual_ttc AS (
                SELECT DISTINCT ttc_seconds FROM analytics.{table_name}
            )
            SELECT STRING_AGG(e.ttc_seconds::text, ', ' ORDER BY e.ttc_seconds) as missing_ttc
            FROM expected_ttc e
            LEFT JOIN actual_ttc a ON e.ttc_seconds = a.ttc_seconds
            WHERE a.ttc_seconds IS NULL
        """)
        
        missing_ttc = cursor.fetchone()[0] or ""
        
        # Check for missing momentum values (should be 18 buckets: -90, -80, ..., -10, 10, 20, ..., 90)
        cursor.execute(f"""
            WITH expected_momentum AS (
                SELECT unnest(ARRAY[-90, -80, -70, -60, -50, -40, -30, -20, -10, 10, 20, 30, 40, 50, 60, 70, 80, 90]) as momentum_bucket
            ),
            actual_momentum AS (
                SELECT DISTINCT momentum_bucket FROM analytics.{table_name}
            )
            SELECT STRING_AGG(e.momentum_bucket::text, ', ' ORDER BY e.momentum_bucket) as missing_momentum
            FROM expected_momentum e
            LEFT JOIN actual_momentum a ON e.momentum_bucket = a.momentum_bucket
            WHERE a.momentum_bucket IS NULL
        """)
        
        missing_momentum = cursor.fetchone()[0] or ""
        
        # Determine if table is complete
        is_complete = (
            min_ttc == 0 and max_ttc == 3600 and ttc_count == 361 and
            min_momentum == -90 and max_momentum == 90 and momentum_count == 18 and
            missing_ttc == "" and missing_momentum == ""
        )
        
        return {
            'is_complete': is_complete,
            'ttc_range': f"{min_ttc}-{max_ttc} ({ttc_count} values)",
            'momentum_range': f"{min_momentum}-{max_momentum} ({momentum_count} values)",
            'buffer_range': f"{min_buffer}-{max_buffer} ({buffer_count} values)",
            'total_rows': total_rows,
            'missing_ttc': missing_ttc,
            'missing_momentum': missing_momentum
        }
        
    except Exception as e:
        return {
            'is_complete': False,
            'error': str(e)
        }

def create_summary_report(logger, results):
    """Create a summary report of the weekly update."""
    logger.info("📋 Creating summary report...")
    
    summary = {
        'timestamp': datetime.now().isoformat(),
        'symbols_processed': results.get('symbols', []),
        'symbols_updated': results.get('updated_symbols', []),
        'symbols_with_momentum': results.get('momentum_symbols', []),
        'symbols_with_profiles': results.get('profile_symbols', []),
        'symbols_with_percentiles': results.get('percentile_symbols', []),
        'verification_results': results.get('verification_results', {}),
        'archived_files': results.get('archived_files', {}),
        'generated_symbols': results.get('generated_symbols', []),
        'lookup_symbols': results.get('lookup_symbols', []),
        'total_duration': results.get('total_duration', 0)
    }
    
    # Save summary to file
    summary_file = Path(__file__).parent.parent / "logs" / f"weekly_update_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2, default=str)
    
    logger.info(f"📄 Summary report saved: {summary_file}")
    
    # Log summary
    logger.info("=" * 60)
    logger.info("📊 WEEKLY UPDATE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total duration: {summary['total_duration']:.2f} seconds")
    logger.info(f"Symbols processed: {len(summary['symbols_processed'])}")
    logger.info(f"Datasets updated: {len(summary['symbols_updated'])}")
    logger.info(f"Momentum generated: {len(summary['symbols_with_momentum'])}")
    logger.info(f"Profiles generated: {len(summary['symbols_with_profiles'])}")
    logger.info(f"Percentiles assigned: {len(summary['symbols_with_percentiles'])}")
    logger.info(f"Fingerprints generated: {len(summary['generated_symbols'])}")
    logger.info(f"Lookup tables generated: {len(summary['lookup_symbols'])}")
    logger.info(f"Archives created: {len(summary['archived_files'])}")
    logger.info("=" * 60)
    
    return summary_file

def main():
    """Main weekly update function."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run analytics update for specified symbols")
    parser.add_argument("symbols", nargs="+", help="Symbols to process (e.g., btc eth)")
    parser.add_argument("--steps", nargs="+", help="Specific steps to run (e.g., update_price_logs generate_lookup_tables)")
    parser.add_argument("--skip-steps", nargs="+", help="Steps to skip (e.g., update_price_logs)")
    parser.add_argument("--weekday-filter", action="store_true", help="Filter data to weekdays 9:00 AM - 12:00 PM East Coast only")
    args = parser.parse_args()
    
    # Convert symbols to uppercase
    symbols = [symbol.upper() for symbol in args.symbols]
    
    start_time = time.time()
    
    # Setup logging
    logger, log_file = setup_logging()
    
    logger.info("🌙 WEEKLY DATA UPDATE STARTING (PostgreSQL Version)")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Processing symbols: {symbols}")
    
    # Log weekday filter setting
    if args.weekday_filter:
        logger.info("📅 Weekday filter ENABLED: Only using data from weekdays 9:00 AM - 12:00 PM East Coast")
    else:
        logger.info("📅 Weekday filter DISABLED: Using all historical data")
    
    # Define all available steps (consolidated for GUI: price logs = fetch + momentum + movement + volatility)
    all_steps = [
        "update_price_logs",
        "generate_profiles",
        "assign_percentiles",
        "verify_data",
        "archive_fingerprints",
        "generate_fingerprints",
        "generate_lookup_tables",
        "create_master_lookup_tables"
    ]
    
    # Determine which steps to run
    if args.steps:
        # User specified specific steps
        steps_to_run = args.steps
        logger.info(f"Running specific steps: {steps_to_run}")
    elif args.skip_steps:
        # User specified steps to skip
        steps_to_run = [step for step in all_steps if step not in args.skip_steps]
        logger.info(f"Skipping steps: {args.skip_steps}")
        logger.info(f"Running steps: {steps_to_run}")
    else:
        # Run all steps (default behavior)
        steps_to_run = all_steps
        logger.info("Running all steps")
    
    results = {
        'symbols': symbols,
        'updated_symbols': [],
        'momentum_symbols': [],
        'profile_symbols': [],
        'percentile_symbols': [],
        'verification_results': {},
        'archived_files': {},
        'generated_symbols': [],
        'lookup_symbols': [],
        'master_symbols': [],
        'total_duration': 0
    }
    
    try:
        # Step 1: Update price logs (fetch + momentum + movement + volatility)
        if "update_price_logs" in steps_to_run:
            step_start = log_step(logger, "Update price logs (fetch, momentum, movement, volatility)")
            results['updated_symbols'] = update_symbol_datasets(logger, symbols)
            if not results['updated_symbols']:
                logger.info("📊 No new price data found, but processing all requested symbols for analytics")
                results['updated_symbols'] = symbols
            run_momentum_generation(logger, results['updated_symbols'])
            run_movement_generation(logger, results['updated_symbols'])
            run_volatility_generation(logger, results['updated_symbols'])
            results['volatility_symbols'] = results['updated_symbols']
            log_step(logger, "Update price logs", step_start)
        else:
            logger.info("⏭️ Skipping Step 1: Update price logs")
            results['updated_symbols'] = symbols
            results['volatility_symbols'] = symbols

        # Step 2: Generate profiles (momentum, price, volatility, movement)
        if "generate_profiles" in steps_to_run:
            step_start = log_step(logger, "Profile generation (momentum, price, volatility, movement)")
            results['profile_symbols'] = generate_momentum_profiles(logger, results['volatility_symbols'], args.weekday_filter)
            results['volatility_profile_symbols'] = generate_volatility_profiles(logger, results['profile_symbols'])
            generate_movement_profiles(logger, results['profile_symbols'])
            log_step(logger, "Profile generation", step_start)
        else:
            logger.info("⏭️ Skipping Step 2: Profile generation")
            results['profile_symbols'] = results['volatility_symbols']
            results['volatility_profile_symbols'] = results['volatility_symbols']

        # Step 3: Assign percentiles (momentum, volatility, movement)
        if "assign_percentiles" in steps_to_run:
            step_start = log_step(logger, "Assign percentiles (momentum, volatility, movement)")
            results['percentile_symbols'] = assign_momentum_percentiles(logger, results['volatility_profile_symbols'], args.weekday_filter)
            assign_volatility_percentiles(logger, results['percentile_symbols'])
            assign_movement_percentiles(logger, results['percentile_symbols'])
            results['volatility_percentile_symbols'] = results['percentile_symbols']
            log_step(logger, "Assign percentiles", step_start)
        else:
            logger.info("⏭️ Skipping Step 3: Assign percentiles")
            results['volatility_percentile_symbols'] = results['volatility_profile_symbols']
        
        # Step 5: Verify data completeness
        if "verify_data" in steps_to_run:
            step_start = log_step(logger, "Data completeness verification")
            results['verification_results'] = verify_data_completeness(logger, results['volatility_percentile_symbols'])
            log_step(logger, "Data completeness verification", step_start)
        else:
            logger.info("⏭️ Skipping Step 5: Data completeness verification")
            results['verification_results'] = {}
        
        # Step 6: Archive existing fingerprints
        if "archive_fingerprints" in steps_to_run:
            step_start = log_step(logger, "Fingerprint archiving")
            results['archived_files'] = archive_existing_fingerprints(logger, results['volatility_percentile_symbols'])
            log_step(logger, "Fingerprint archiving", step_start)
        else:
            logger.info("⏭️ Skipping Step 6: Fingerprint archiving")
            results['archived_files'] = {}
        
        # Step 7: Generate new fingerprints
        if "generate_fingerprints" in steps_to_run:
            step_start = log_step(logger, "Fingerprint generation")
            results['generated_symbols'] = generate_new_fingerprints(logger, results['volatility_percentile_symbols'], args.weekday_filter)
            log_step(logger, "Fingerprint generation", step_start)
        else:
            logger.info("⏭️ Skipping Step 7: Fingerprint generation")
            results['generated_symbols'] = results['volatility_percentile_symbols']
        
        # Step 8: Generate probability lookup tables
        if "generate_lookup_tables" in steps_to_run:
            step_start = log_step(logger, "Lookup table generation")
            results['lookup_symbols'] = generate_lookup_tables(logger, results['generated_symbols'], args.weekday_filter)
            log_step(logger, "Lookup table generation", step_start)
        else:
            logger.info("⏭️ Skipping Step 8: Lookup table generation")
            results['lookup_symbols'] = results['generated_symbols']
        
        # Step 9: Create master lookup tables for production use
        if "create_master_lookup_tables" in steps_to_run:
            step_start = log_step(logger, "Master lookup table creation")
            results['master_symbols'] = create_master_lookup_tables(logger, results['lookup_symbols'])
            log_step(logger, "Master lookup table creation", step_start)
        else:
            logger.info("⏭️ Skipping Step 9: Master lookup table creation")
            results['master_symbols'] = results['lookup_symbols']
        
        # Step 10: Cleanup old tables (always run if master tables were created)
        if "create_master_lookup_tables" in steps_to_run and results['master_symbols']:
            step_start = log_step(logger, "Analytics table cleanup")
            cleanup_analytics_tables(logger, results['master_symbols'])
            log_step(logger, "Analytics table cleanup", step_start)
        
        # Create summary report
        results['total_duration'] = time.time() - start_time
        summary_file = create_summary_report(logger, results)
        
        logger.info("🎉 WEEKLY UPDATE COMPLETED SUCCESSFULLY!")
        logger.info(f"Total duration: {results['total_duration']:.2f} seconds")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ WEEKLY UPDATE FAILED: {e}")
        logger.error(f"Error occurred after {time.time() - start_time:.2f} seconds")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
