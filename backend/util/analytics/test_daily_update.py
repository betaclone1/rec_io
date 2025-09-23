#!/usr/bin/env python3
"""
Test Daily Update Script
Runs a minimal test of the daily update process
"""

import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Add the util directory to the path so we can import our modules
sys.path.append(os.path.dirname(__file__))

def setup_test_logging():
    """Setup logging for the test."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"daily_update_test_{timestamp}.log"
    
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

def test_database_connection():
    """Test database connection."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='localhost',
            database='rec_io_db',
            user='rec_io_user',
            password='rec_io_password',
            connect_timeout=10
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False

def test_imports():
    """Test that all required modules can be imported."""
    try:
        from symbol_data_fetch_pg import update_existing_db
        from momentum_generator_pg import fill_missing_momentum_in_db
        from symbol_profiler import SymbolProfiler
        return True
    except Exception as e:
        print(f"Import failed: {e}")
        return False

def main():
    """Main test function."""
    logger, log_file = setup_test_logging()
    
    logger.info("🧪 Starting daily update test")
    logger.info(f"Log file: {log_file}")
    
    # Test 1: Database connection
    logger.info("🔍 Test 1: Database connection")
    if test_database_connection():
        logger.info("✅ Database connection successful")
    else:
        logger.error("❌ Database connection failed")
        return False
    
    # Test 2: Module imports
    logger.info("🔍 Test 2: Module imports")
    if test_imports():
        logger.info("✅ All modules imported successfully")
    else:
        logger.error("❌ Module import failed")
        return False
    
    # Test 3: Run actual daily update with test mode
    logger.info("🔍 Test 3: Running daily update in test mode")
    try:
        # Import and run the daily update script
        from daily_update import main as daily_update_main
        
        # Set up arguments for test mode
        sys.argv = ['test_daily_update.py', '--symbols', 'BTC', '--test']
        
        logger.info("🚀 Starting daily update test run...")
        success = daily_update_main()
        
        if success:
            logger.info("✅ Daily update test completed successfully")
        else:
            logger.error("❌ Daily update test failed")
            
        return success
        
    except Exception as e:
        logger.error(f"❌ Daily update test failed with exception: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
