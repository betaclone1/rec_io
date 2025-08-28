#!/usr/bin/env python3
"""
WEEKLY DATA UPDATE SCRIPT
Runs every Saturday at 11:59:59 PM to update the entire data pipeline.

Pipeline Steps:
1. Update symbol master 5y datasets using symbol_data_fetch
2. Run momentum generator on new master datasets
3. Confirm new data is complete (5 years of 1m candlestick data, all rows with momentum score)
4. Archive existing fingerprint files with dated zip file
5. Run fingerprint_generator to generate updated fingerprints
6. Record log of operations for review
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

from symbol_data_fetch import update_existing_csv
from momentum_generator import fill_missing_momentum_inplace
from fingerprint_archiver import create_archive, find_fingerprint_files
from fingerprint_generator import main as run_fingerprint_generator

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

def get_symbols():
    """Get list of symbols to process."""
    data_dir = Path(__file__).parent.parent / "data" / "historical_data"
    symbols = []
    
    if data_dir.exists():
        for symbol_dir in data_dir.iterdir():
            if symbol_dir.is_dir() and not symbol_dir.name.startswith('.') and symbol_dir.name.endswith('_historical'):
                # Extract symbol name from directory (e.g., 'btc_historical' -> 'btc')
                symbol = symbol_dir.name.replace('_historical', '')
                symbols.append(symbol)
    
    return symbols

def update_symbol_datasets(logger):
    """Step 1: Update symbol master 5y datasets using symbol_data_fetch."""
    logger.info("📊 Step 1: Updating symbol master datasets")
    
    symbols = get_symbols()
    logger.info(f"Found symbols to update: {symbols}")
    
    updated_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Updating {symbol.upper()} dataset...")
            
            # Construct the master file path - using absolute path
            project_root = Path(__file__).parent.parent.parent
            master_file = project_root / "backend" / "data" / "historical_data" / f"{symbol}_historical" / f"{symbol}_1m_master_5y.csv"
            
            # Update the dataset
            result = update_existing_csv(f"{symbol.upper()}/USD", str(master_file))
            
            if result:
                logger.info(f"✅ {symbol.upper()} dataset updated successfully")
                updated_symbols.append(symbol)
            else:
                logger.warning(f"⚠️ {symbol.upper()} dataset update failed or no new data")
                
        except Exception as e:
            logger.error(f"❌ Error updating {symbol.upper()} dataset: {e}")
    
    logger.info(f"Updated {len(updated_symbols)} symbols: {updated_symbols}")
    return updated_symbols

def run_momentum_generation(logger, symbols):
    """Step 2: Run momentum generator on new master datasets."""
    logger.info("📈 Step 2: Running momentum generation")
    
    processed_symbols = []
    for symbol in symbols:
        try:
            logger.info(f"Generating momentum for {symbol.upper()}...")
            
            # Construct the master file path - using absolute path
            project_root = Path(__file__).parent.parent.parent
            master_file = project_root / "backend" / "data" / "historical_data" / f"{symbol}_historical" / f"{symbol}_1m_master_5y.csv"
            
            # Run momentum generation
            fill_missing_momentum_inplace(str(master_file))
            
            logger.info(f"✅ {symbol.upper()} momentum generation completed")
            processed_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating momentum for {symbol.upper()}: {e}")
    
    logger.info(f"Momentum generation completed for {len(processed_symbols)} symbols")
    return processed_symbols

def verify_data_completeness(logger, symbols):
    """Step 3: Confirm new data is complete (5 years of 1m candlestick data, all rows with momentum score)."""
    logger.info("🔍 Step 3: Verifying data completeness")
    
    verification_results = {}
    
    for symbol in symbols:
        try:
            logger.info(f"Verifying {symbol.upper()} dataset...")
            
            # Load the dataset - using absolute path
            project_root = Path(__file__).parent.parent.parent
            master_file = project_root / "backend" / "data" / "historical_data" / f"{symbol}_historical" / f"{symbol}_1m_master_5y.csv"
            df = pd.read_csv(str(master_file))
            
            # Check data completeness
            total_rows = len(df)
            expected_rows = 5 * 365 * 24 * 60  # 5 years of 1-minute data
            
            # Check date range
            df['timestamp'] = pd.to_datetime(df['timestamp'])
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
            
            logger.info(f"✅ {symbol.upper()} verification:")
            logger.info(f"   - Rows: {total_rows:,} (expected ~{expected_rows:,})")
            logger.info(f"   - Date range: {days_covered} days")
            logger.info(f"   - Momentum complete: {momentum_complete}")
            logger.info(f"   - Missing data: {missing_data}")
            
        except Exception as e:
            logger.error(f"❌ Error verifying {symbol.upper()}: {e}")
            verification_results[symbol] = {'error': str(e)}
    
    return verification_results

def archive_existing_fingerprints(logger, symbols):
    """Step 4: Archive existing fingerprint files with dated zip file."""
    logger.info("📦 Step 4: Archiving existing fingerprint files")
    
    archived_files = {}
    
    for symbol in symbols:
        try:
            logger.info(f"Archiving {symbol.upper()} fingerprint files...")
            
            # Find fingerprint files - using absolute path
            project_root = Path(__file__).parent.parent.parent
            fingerprint_dir = project_root / "backend" / "data" / "historical_data" / f"{symbol}_historical" / "symbol_fingerprints"
            fingerprint_files = find_fingerprint_files(str(fingerprint_dir))
            
            if fingerprint_files:
                # Create archive
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archive_name = f"{symbol}_fingerprint_archive_{timestamp}"
                output_dir = project_root / "backend" / "data" / "archives"
                
                archive_path = create_archive(fingerprint_files, str(output_dir), archive_name, symbol)
                
                if archive_path:
                    logger.info(f"✅ {symbol.upper()} fingerprints archived: {archive_path}")
                    archived_files[symbol] = archive_path
                else:
                    logger.warning(f"⚠️ Failed to archive {symbol.upper()} fingerprints")
            else:
                logger.info(f"ℹ️ No fingerprint files found for {symbol.upper()}")
                
        except Exception as e:
            logger.error(f"❌ Error archiving {symbol.upper()} fingerprints: {e}")
    
    return archived_files

def generate_new_fingerprints(logger, symbols):
    """Step 5: Run fingerprint_generator to generate updated fingerprints."""
    logger.info("🔢 Step 5: Generating new fingerprint files")
    
    generated_symbols = []
    
    for symbol in symbols:
        try:
            logger.info(f"Generating fingerprints for {symbol.upper()}...")
            
            # Construct the master file path - using absolute path
            project_root = Path(__file__).parent.parent.parent
            master_file = project_root / "backend" / "data" / "historical_data" / f"{symbol}_historical" / f"{symbol}_1m_master_5y.csv"
            
            # Run fingerprint generation using subprocess
            result = subprocess.run([sys.executable, "fingerprint_generator.py", str(master_file)], 
                                  capture_output=True, text=True, cwd=os.path.dirname(__file__))
            
            if result.returncode != 0:
                raise Exception(f"Fingerprint generation failed: {result.stderr}")
            
            logger.info(f"✅ {symbol.upper()} fingerprint generation completed")
            generated_symbols.append(symbol)
            
        except Exception as e:
            logger.error(f"❌ Error generating fingerprints for {symbol.upper()}: {e}")
    
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
    logger.info(f"Fingerprints generated: {len(summary['generated_symbols'])}")
    logger.info(f"Archives created: {len(summary['archived_files'])}")
    logger.info("=" * 60)
    
    return summary_file

def main():
    """Main weekly update function."""
    start_time = time.time()
    
    # Setup logging
    logger, log_file = setup_logging()
    
    logger.info("🌙 WEEKLY DATA UPDATE STARTING")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Log file: {log_file}")
    
    results = {
        'symbols': [],
        'updated_symbols': [],
        'momentum_symbols': [],
        'verification_results': {},
        'archived_files': {},
        'generated_symbols': [],
        'total_duration': 0
    }
    
    try:
        # Step 1: Update symbol datasets
        step_start = log_step(logger, "Symbol dataset updates")
        results['symbols'] = get_symbols()
        results['updated_symbols'] = update_symbol_datasets(logger)
        log_step(logger, "Symbol dataset updates", step_start)
        
        # Step 2: Run momentum generation
        step_start = log_step(logger, "Momentum generation")
        results['momentum_symbols'] = run_momentum_generation(logger, results['updated_symbols'])
        log_step(logger, "Momentum generation", step_start)
        
        # Step 3: Verify data completeness
        step_start = log_step(logger, "Data completeness verification")
        results['verification_results'] = verify_data_completeness(logger, results['momentum_symbols'])
        log_step(logger, "Data completeness verification", step_start)
        
        # Step 4: Archive existing fingerprints
        step_start = log_step(logger, "Fingerprint archiving")
        results['archived_files'] = archive_existing_fingerprints(logger, results['momentum_symbols'])
        log_step(logger, "Fingerprint archiving", step_start)
        
        # Step 5: Generate new fingerprints
        step_start = log_step(logger, "Fingerprint generation")
        results['generated_symbols'] = generate_new_fingerprints(logger, results['momentum_symbols'])
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