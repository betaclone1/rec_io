#!/usr/bin/env python3
"""
Test script to verify trade_manager.py can work with the new database abstraction layer.
This test will verify that the database operations in trade_manager.py can be migrated
to use the new database abstraction layer.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import tempfile
import shutil
import time

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Import the database abstraction layer
from backend.core.database import (
    DatabaseConfig, 
    get_trades_database,
    get_active_trades_database,
    init_all_databases
)

class TestTradeManagerDatabaseMigration(unittest.TestCase):
    """Test trade_manager.py database operations with new abstraction layer."""
    
    def setUp(self):
        """Set up test environment."""
        # Create temporary directory for test databases
        self.test_dir = tempfile.mkdtemp()
        
        # Set up environment variables for testing
        self.original_env = {}
        for key in ['DATABASE_TYPE', 'POSTGRES_HOST', 'POSTGRES_PORT', 'POSTGRES_DB', 
                   'POSTGRES_USER', 'POSTGRES_PASSWORD']:
            if key in os.environ:
                self.original_env[key] = os.environ[key]
        
        # Set test environment
        os.environ['DATABASE_TYPE'] = 'sqlite'  # Use SQLite for testing
        os.environ['POSTGRES_HOST'] = 'localhost'
        os.environ['POSTGRES_PORT'] = '5432'
        os.environ['POSTGRES_DB'] = 'rec_io_db'
        os.environ['POSTGRES_USER'] = 'rec_io_user'
        os.environ['POSTGRES_PASSWORD'] = ''
    
    def tearDown(self):
        """Clean up test environment."""
        # Restore environment variables
        for key, value in self.original_env.items():
            os.environ[key] = value
        
        # Clean up temporary directory
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_database_initialization(self):
        """Test that databases can be initialized."""
        try:
            init_all_databases()
            self.assertTrue(True)  # If we get here, initialization succeeded
        except Exception as e:
            self.fail(f"Database initialization failed: {e}")
    
    def test_trades_database_operations(self):
        """Test basic trades database operations."""
        trades_db = get_trades_database()
        
        # Test table creation
        trades_db.init_database()
        
        # Test table exists
        self.assertTrue(trades_db.table_exists("trades"))
        
        # Test basic insert
        test_trade = {
            'date': '2025-01-27',
            'time': '14:00:00',
            'strike': '50000',
            'side': 'Y',
            'buy_price': 0.85,
            'position': 1,
            'status': 'pending',
            'contract': 'BTC 2pm',
            'ticker': 'BTC-50000-2pm',
            'symbol': 'BTC',
            'exchange': 'kalshi',
            'trade_strategy': 'Hourly HTC',
            'symbol_open': 50000,
            'momentum': '+15',
            'prob': 85.0,
            'volatility': 10,
            'ticket_id': f'TEST-{int(time.time())}-001',
            'entry_method': 'manual'
        }
        
        # Insert test trade
        insert_query = """
            INSERT INTO trades (
                date, time, strike, side, buy_price, position, status,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, volatility, ticket_id, entry_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        insert_params = (
            test_trade['date'], test_trade['time'], test_trade['strike'], 
            test_trade['side'], test_trade['buy_price'], test_trade['position'], 
            test_trade['status'], test_trade['contract'], test_trade['ticker'],
            test_trade['symbol'], test_trade['exchange'], test_trade['trade_strategy'],
            test_trade['symbol_open'], test_trade['momentum'], test_trade['prob'],
            test_trade['volatility'], test_trade['ticket_id'], test_trade['entry_method']
        )
        
        affected_rows = trades_db.execute_update(insert_query, insert_params)
        self.assertEqual(affected_rows, 1)
        
        # Test query
        query = "SELECT * FROM trades WHERE ticket_id = ?"
        results = trades_db.execute_query(query, (test_trade['ticket_id'],))
        
        self.assertEqual(len(results), 1)
        result = results[0]
        
        # Verify key fields
        self.assertEqual(result['ticket_id'], test_trade['ticket_id'])
        self.assertEqual(result['strike'], test_trade['strike'])
        self.assertEqual(result['side'], test_trade['side'])
        self.assertEqual(result['buy_price'], test_trade['buy_price'])
        self.assertEqual(result['position'], test_trade['position'])
        
        # Clean up
        cleanup_query = "DELETE FROM trades WHERE ticket_id = ?"
        trades_db.execute_update(cleanup_query, (test_trade['ticket_id'],))
    
    def test_active_trades_database_operations(self):
        """Test basic active trades database operations."""
        active_trades_db = get_active_trades_database()
        
        # Test table creation
        active_trades_db.init_database()
        
        # Test table exists
        self.assertTrue(active_trades_db.table_exists("active_trades"))
        
        # Test basic insert
        test_active_trade = {
            'trade_id': 1,
            'ticket_id': f'TEST-{int(time.time())}-002',
            'date': '2025-01-27',
            'time': '14:00:00',
            'strike': '50000',
            'side': 'Y',
            'buy_price': 0.85,
            'position': 1,
            'contract': 'BTC 2pm',
            'ticker': 'BTC-50000-2pm',
            'symbol': 'BTC',
            'exchange': 'kalshi',
            'trade_strategy': 'Hourly HTC',
            'symbol_open': 50000.0,
            'momentum': '+15',
            'prob': 85.0,
            'fees': 0.01,
            'diff': '0.15',
            'status': 'active'
        }
        
        # Insert test active trade
        insert_query = """
            INSERT INTO active_trades (
                trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, fees, diff, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        insert_params = (
            test_active_trade['trade_id'], test_active_trade['ticket_id'],
            test_active_trade['date'], test_active_trade['time'], test_active_trade['strike'],
            test_active_trade['side'], test_active_trade['buy_price'], test_active_trade['position'],
            test_active_trade['contract'], test_active_trade['ticker'], test_active_trade['symbol'],
            test_active_trade['exchange'], test_active_trade['trade_strategy'], test_active_trade['symbol_open'],
            test_active_trade['momentum'], test_active_trade['prob'], test_active_trade['fees'],
            test_active_trade['diff'], test_active_trade['status']
        )
        
        affected_rows = active_trades_db.execute_update(insert_query, insert_params)
        self.assertEqual(affected_rows, 1)
        
        # Test query
        query = "SELECT * FROM active_trades WHERE ticket_id = ?"
        results = active_trades_db.execute_query(query, (test_active_trade['ticket_id'],))
        
        self.assertEqual(len(results), 1)
        result = results[0]
        
        # Verify key fields
        self.assertEqual(result['ticket_id'], test_active_trade['ticket_id'])
        self.assertEqual(result['trade_id'], test_active_trade['trade_id'])
        self.assertEqual(result['strike'], test_active_trade['strike'])
        self.assertEqual(result['side'], test_active_trade['side'])
        self.assertEqual(result['status'], test_active_trade['status'])
        
        # Clean up
        cleanup_query = "DELETE FROM active_trades WHERE ticket_id = ?"
        active_trades_db.execute_update(cleanup_query, (test_active_trade['ticket_id'],))
    
    def test_trade_manager_equivalent_operations(self):
        """Test operations equivalent to those in trade_manager.py."""
        trades_db = get_trades_database()
        trades_db.init_database()
        
        # Test equivalent to trade_manager.py insert_trade function
        test_trade = {
            'date': '2025-01-27',
            'time': '14:00:00',
            'strike': '50000',
            'side': 'Y',
            'buy_price': 0.85,
            'position': 1,
            'status': 'pending',
            'contract': 'BTC 2pm',
            'ticker': 'BTC-50000-2pm',
            'symbol': 'BTC',
            'exchange': 'kalshi',
            'trade_strategy': 'Hourly HTC',
            'symbol_open': 50000,
            'momentum': '+15',
            'prob': 85.0,
            'volatility': 10,
            'ticket_id': f'TEST-{int(time.time())}-003',
            'entry_method': 'manual'
        }
        
        # Insert trade (equivalent to insert_trade function)
        insert_query = """
            INSERT INTO trades (
                date, time, strike, side, buy_price, position, status,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, volatility, ticket_id, entry_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        insert_params = (
            test_trade['date'], test_trade['time'], test_trade['strike'], 
            test_trade['side'], test_trade['buy_price'], test_trade['position'], 
            test_trade['status'], test_trade['contract'], test_trade['ticker'],
            test_trade['symbol'], test_trade['exchange'], test_trade['trade_strategy'],
            test_trade['symbol_open'], test_trade['momentum'], test_trade['prob'],
            test_trade['volatility'], test_trade['ticket_id'], test_trade['entry_method']
        )
        
        affected_rows = trades_db.execute_update(insert_query, insert_params)
        self.assertEqual(affected_rows, 1)
        
        # Get the inserted trade ID
        query = "SELECT id FROM trades WHERE ticket_id = ?"
        results = trades_db.execute_query(query, (test_trade['ticket_id'],))
        self.assertEqual(len(results), 1)
        trade_id = results[0]['id']
        
        # Test equivalent to update_trade_status function
        update_query = "UPDATE trades SET status = ? WHERE id = ?"
        affected_rows = trades_db.execute_update(update_query, ('open', trade_id))
        self.assertEqual(affected_rows, 1)
        
        # Verify the update
        query = "SELECT status FROM trades WHERE id = ?"
        results = trades_db.execute_query(query, (trade_id,))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'open')
        
        # Test equivalent to get_trades function
        query = "SELECT id, date, time, strike, side, buy_price, position, status, contract, ticket_id FROM trades WHERE status = 'open'"
        results = trades_db.execute_query(query)
        self.assertGreaterEqual(len(results), 1)
        
        # Find our test trade
        test_trade_found = False
        for result in results:
            if result['ticket_id'] == test_trade['ticket_id']:
                test_trade_found = True
                self.assertEqual(result['status'], 'open')
                break
        
        self.assertTrue(test_trade_found, "Test trade not found in open trades query")
        
        # Clean up
        cleanup_query = "DELETE FROM trades WHERE ticket_id = ?"
        trades_db.execute_update(cleanup_query, (test_trade['ticket_id'],))

if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2) 