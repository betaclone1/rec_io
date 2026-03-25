#!/usr/bin/env python3
"""
WEEKLY DATA UPDATE SCRIPT - POSTGRESQL VERSION
Runs every Saturday at 11:59:59 PM to update the entire data pipeline.

Pipeline Steps:
1. Update symbol master 5y datasets using symbol_data_fetch_pg (PostgreSQL)
2. Run momentum generator on new master datasets using momentum_generator_pg (PostgreSQL)
3. Generate momentum profiles using momentum_profiler (PostgreSQL)
4. Confirm new data is complete (5 years of 1m candlestick data, all rows with momentum score)
5. Archive existing fingerprint files with dated zip file
6. Run fingerprint_generator_postgresql to generate updated fingerprints (PostgreSQL)
7. Record log of operations for review
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import subprocess
import json

# Add the util directory to the path so we can import our modules
sys.path.append(os.path.dirname(__file__))

from symbol_data_fetch_pg import update_existing_db
from momentum_generator_pg import fill_missing_momentum_in_db
from momentum_profiler import MomentumProfiler
from fingerprint_archiver import create_archive, find_fingerprint_files

# Configure logging
def setup_logging():
    """Setup logging for the weekly update process."""
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"weekly_update_{timestamp}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__), log_file

def log_step(logger, step_name, start_time=None):
    """Log a step with timing information."""
    if start_time:
        elapsed = time.time() - start_time
        logger.info(f"✅ {step_name} completed in {elapsed:.2f} seconds")
    else:
        logger.info(f"🚀 Starting: {step_name}")
        return time.time()

def get_symbols_from_db():
    """Get list of symbols from PostgreSQL database."""
    try:
        from momentum_generator_pg import get_symbols_from_db
        symbols = get_symbols_from_db()
        return [symbol.upper() for symbol in symbols] if symbols else []
    except Exception as e:
        logging.getLogger(__name__).error("Error getting symbols from database: %s", e)
        return []

def update_symbol_datasets(logger):
    """Step 1: Update symbol master 5y datasets using symbol_data_fetch_pg."""
    logger.info("📊 Step 1: Updating symbol master datasets in PostgreSQL")
    
    symbols = get_symbols_from_db()
    logger.info(f"Found symbols to update: {symbols}")
    
    updated_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Updating {symbol} dataset in PostgreSQL...")
            
            # Update the dataset in PostgreSQL
            table_name, rows_fetched = update_existing_db(f"{symbol}/USD")
            
            if rows_fetched > 0:
                logger.info(f"✅ {symbol} dataset updated successfully: {rows_fetched} new rows")
                updated_symbols.append(symbol)
            else:
                logger.warning(f"⚠️ {symbol} dataset update: no new data")
                
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
            
            # Run momentum generation in PostgreSQL
            fill_missing_momentum_in_db(symbol)
            
            logger.info(f"✅ {symbol} momentum generation completed")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating momentum for {symbol}: {e}")
    
    logger.info(f"Momentum generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def generate_momentum_profiles(logger, symbols):
    """Step 3: Generate momentum profiles using momentum_profiler."""
    logger.info("📊 Step 3: Generating momentum profiles in PostgreSQL")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating momentum profile for {symbol}...")
            
            # Create profiler and generate profile
            profiler = MomentumProfiler(symbol.lower())
            profile_df = profiler.generate_profile()
            
            logger.info(f"✅ {symbol} momentum profile generated: {len(profile_df)} percentiles")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating momentum profile for {symbol}: {e}")
    
    logger.info(f"Momentum profile generation completed for {len(processed_symbols)} symbols")
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

def generate_new_fingerprints(logger, symbols):
    """Step 6: Run fingerprint_generator_postgresql to generate updated fingerprints."""
    logger.info("🔢 Step 6: Generating new fingerprint files in PostgreSQL")
    
    generated_symbols = []
    
    for symbol in symbols:
        try:
            logger.info(f"Generating fingerprints for {symbol} in PostgreSQL...")
            
            # We need to create a temporary CSV file from PostgreSQL data for fingerprint generation
            # since fingerprint_generator_postgresql.py expects a CSV input
            from momentum_generator_pg import load_data_from_db
            df = load_data_from_db(symbol)
            
            # Create temporary CSV file
            temp_csv_path = f"/tmp/{symbol.lower()}_temp_data.csv"
            df.to_csv(temp_csv_path, index=False)
            
            # Run fingerprint generation using subprocess
            result = subprocess.run([
                sys.executable, "fingerprint_generator_postgresql.py", temp_csv_path
            ], capture_output=True, text=True, cwd=os.path.dirname(__file__))
            
            # Clean up temporary file
            os.remove(temp_csv_path)
            
            if result.returncode != 0:
                raise Exception(f"Fingerprint generation failed: {result.stderr}")
            
            logger.info(f"✅ {symbol} fingerprint generation completed")
            generated_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating fingerprints for {symbol}: {e}")
    
    logger.info(f"Fingerprint generation completed for {len(generated_symbols)} symbols")
    return generated_symbols

def create_summary_report(logger, results):
    """Create a summary report of the weekly update."""
    logger.info("📋 Creating summary report...")
    
    summary = {
        'timestamp': datetime.now().isoformat(),
        'symbols_processed': results.get('symbols', []),
        'symbols_updated': results.get('updated_symbols', []),
        'symbols_with_momentum': results.get('momentum_symbols', []),
        'symbols_with_profiles': results.get('profile_symbols', []),
        'verification_results': results.get('verification_results', {}),
        'archived_files': results.get('archived_files', {}),
        'generated_symbols': results.get('generated_symbols', []),
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
    logger.info(f"Momentum profiles generated: {len(summary['symbols_with_profiles'])}")
    logger.info(f"Fingerprints generated: {len(summary['generated_symbols'])}")
    logger.info(f"Archives created: {len(summary['archived_files'])}")
    logger.info("=" * 60)
    
    return summary_file

def main():
    """Main weekly update function."""
    start_time = time.time()
    
    # Setup logging
    logger, log_file = setup_logging()
    
    logger.info("🌙 WEEKLY DATA UPDATE STARTING (PostgreSQL Version)")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Log file: {log_file}")
    
    results = {
        'symbols': [],
        'updated_symbols': [],
        'momentum_symbols': [],
        'profile_symbols': [],
        'verification_results': {},
        'archived_files': {},
        'generated_symbols': [],
        'total_duration': 0
    }
    
    try:
        # Step 1: Update symbol datasets
        step_start = log_step(logger, "Symbol dataset updates")
        results['symbols'] = get_symbols_from_db()
        results['updated_symbols'] = update_symbol_datasets(logger)
        log_step(logger, "Symbol dataset updates", step_start)
        
        # Step 2: Run momentum generation
        step_start = log_step(logger, "Momentum generation")
        results['momentum_symbols'] = run_momentum_generation(logger, results['updated_symbols'])
        log_step(logger, "Momentum generation", step_start)
        
        # Step 3: Generate momentum profiles
        step_start = log_step(logger, "Momentum profile generation")
        results['profile_symbols'] = generate_momentum_profiles(logger, results['momentum_symbols'])
        log_step(logger, "Momentum profile generation", step_start)
        
        # Step 4: Verify data completeness
        step_start = log_step(logger, "Data completeness verification")
        results['verification_results'] = verify_data_completeness(logger, results['profile_symbols'])
        log_step(logger, "Data completeness verification", step_start)
        
        # Step 5: Archive existing fingerprints
        step_start = log_step(logger, "Fingerprint archiving")
        results['archived_files'] = archive_existing_fingerprints(logger, results['profile_symbols'])
        log_step(logger, "Fingerprint archiving", step_start)
        
        # Step 6: Generate new fingerprints
        step_start = log_step(logger, "Fingerprint generation")
        results['generated_symbols'] = generate_new_fingerprints(logger, results['profile_symbols'])
        log_step(logger, "Fingerprint generation", step_start)
        
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
