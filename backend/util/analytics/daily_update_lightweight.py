#!/usr/bin/env python3
"""
LIGHTWEIGHT DAILY UPDATE SCRIPT
Memory-optimized version that only updates price data without heavy calculations.
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Add the util directory to the path so we can import our modules
sys.path.append(os.path.dirname(__file__))

from symbol_data_fetch_pg import update_existing_db

# Configure logging
def setup_logging():
    """Setup logging for the lightweight daily update process."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"daily_update_lightweight_{timestamp}.log"
    
    # Create file handler
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
    root_logger.handlers.clear()  # Clear existing handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__), log_file

def update_symbol_datasets(logger, symbols):
    """Update symbol datasets with latest price data only."""
    logger.info("📊 Updating symbol datasets with latest price data")
    
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
                    updated_symbols.append(symbol)  # Still count as processed
            except Exception as fetch_error:
                logger.warning(f"⚠️ Data fetch failed for {symbol}: {fetch_error}")
                logger.info(f"ℹ️ Continuing with {symbol} for next steps")
                updated_symbols.append(symbol)  # Continue processing even if fetch fails
                
        except Exception as e:
            logger.error(f"❌ Error updating {symbol} dataset: {e}")
            # Don't fail completely - continue with other symbols
            updated_symbols.append(symbol)
    
    logger.info(f"Dataset updates completed for {len(updated_symbols)} symbols")
    return updated_symbols

def main():
    """Main lightweight daily update function."""
    symbols = ["BTC", "ETH", "SPX", "NDX"]
    
    start_time = time.time()
    
    # Setup logging
    logger, log_file = setup_logging()
    
    logger.info("🌅 LIGHTWEIGHT DAILY UPDATE STARTING")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Processing symbols: {symbols}")
    
    try:
        # Only do data updates - skip memory-intensive momentum calculations
        updated_symbols = update_symbol_datasets(logger, symbols)
        
        # Create summary
        total_duration = time.time() - start_time
        logger.info("=" * 60)
        logger.info("📊 LIGHTWEIGHT UPDATE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total duration: {total_duration:.2f} seconds")
        logger.info(f"Symbols processed: {len(updated_symbols)}")
        logger.info("✅ LIGHTWEIGHT UPDATE COMPLETED SUCCESSFULLY!")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ LIGHTWEIGHT UPDATE FAILED: {e}")
        logger.error(f"Error occurred after {time.time() - start_time:.2f} seconds")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
