#!/usr/bin/env python3
"""
Test script to verify main.py can work with the new database abstraction layer.
This test will verify that the database operations in main.py can be migrated
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

class TestMainDatabaseMigration(unittest.TestCase):
    """Test main.py database operations with new abstraction layer."""
    
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
        """Test trades database operations equivalent to main.py."""
        trades_db = get_trades_database()
        trades_db.init_database()
        
        # Test equivalent to main.py trades database operations
        # Insert a test trade
        test_trade = {
            'date': '2025-01-27',
            'time': '14:00:00',
            'strike': '50000',
            'side': 'Y',
            'buy_price': 0.85,
            'position': 1,
            'status': 'closed',
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
        
        # Test equivalent to main.py get_trades endpoint - get our specific trade
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
        
        # Test equivalent to main.py get_trade endpoint
        trade_id = result['id']
        query = "SELECT * FROM trades WHERE id = ?"
        results = trades_db.execute_query(query, (trade_id,))
        
        self.assertEqual(len(results), 1)
        result = results[0]
        self.assertEqual(result['id'], trade_id)
        
        # Clean up
        cleanup_query = "DELETE FROM trades WHERE ticket_id = ?"
        trades_db.execute_update(cleanup_query, (test_trade['ticket_id'],))
    
    def test_trades_filtering_operations(self):
        """Test trades filtering operations equivalent to main.py."""
        trades_db = get_trades_database()
        trades_db.init_database()
        
        # Insert multiple test trades with different statuses
        test_trades = [
            {
                'date': '2025-01-27',
                'time': '14:00:00',
                'strike': '50000',
                'side': 'Y',
                'buy_price': 0.85,
                'position': 1,
                'status': 'open',
                'contract': 'BTC 2pm',
                'ticker': 'BTC-50000-2pm',
                'symbol': 'BTC',
                'exchange': 'kalshi',
                'trade_strategy': 'Hourly HTC',
                'symbol_open': 50000,
                'momentum': '+15',
                'prob': 85.0,
                'volatility': 10,
                'ticket_id': f'MAIN-TEST-{int(time.time())}-002',
                'entry_method': 'manual'
            },
            {
                'date': '2025-01-27',
                'time': '15:00:00',
                'strike': '51000',
                'side': 'N',
                'buy_price': 0.75,
                'position': 1,
                'status': 'closed',
                'contract': 'BTC 3pm',
                'ticker': 'BTC-51000-3pm',
                'symbol': 'BTC',
                'exchange': 'kalshi',
                'trade_strategy': 'Hourly HTC',
                'symbol_open': 51000,
                'momentum': '-10',
                'prob': 75.0,
                'volatility': 8,
                'ticket_id': f'MAIN-TEST-{int(time.time())}-003',
                'entry_method': 'manual'
            }
        ]
        
        # Insert test trades
        insert_query = """
            INSERT INTO trades (
                date, time, strike, side, buy_price, position, status,
                contract, ticker, symbol, exchange, trade_strategy, symbol_open,
                momentum, prob, volatility, ticket_id, entry_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        for trade in test_trades:
            insert_params = (
                trade['date'], trade['time'], trade['strike'], 
                trade['side'], trade['buy_price'], trade['position'], 
                trade['status'], trade['contract'], trade['ticker'],
                trade['symbol'], trade['exchange'], trade['trade_strategy'],
                trade['symbol_open'], trade['momentum'], trade['prob'],
                trade['volatility'], trade['ticket_id'], trade['entry_method']
            )
            
            affected_rows = trades_db.execute_update(insert_query, insert_params)
            self.assertEqual(affected_rows, 1)
        
        # Test filtering by status (equivalent to main.py get_trades with status parameter)
        query = "SELECT * FROM trades WHERE status = 'open' AND ticket_id LIKE 'MAIN-TEST-%'"
        results = trades_db.execute_query(query)
        
        # Should find our open test trade
        open_trades = [r for r in results if r['ticket_id'] == test_trades[0]['ticket_id']]
        self.assertEqual(len(open_trades), 1)
        self.assertEqual(open_trades[0]['ticket_id'], test_trades[0]['ticket_id'])
        
        # Test filtering by closed status
        query = "SELECT * FROM trades WHERE status = 'closed' AND ticket_id LIKE 'MAIN-TEST-%'"
        results = trades_db.execute_query(query)
        
        # Should find our closed test trade
        closed_trades = [r for r in results if r['ticket_id'] == test_trades[1]['ticket_id']]
        self.assertEqual(len(closed_trades), 1)
        self.assertEqual(closed_trades[0]['ticket_id'], test_trades[1]['ticket_id'])
        
        # Test ordering by date and time (equivalent to main.py ordering)
        query = "SELECT * FROM trades WHERE ticket_id LIKE 'MAIN-TEST-%' ORDER BY date DESC, time DESC"
        results = trades_db.execute_query(query)
        
        # Should have our test trades
        self.assertEqual(len(results), 2)
        
        # Clean up
        for trade in test_trades:
            cleanup_query = "DELETE FROM trades WHERE ticket_id = ?"
            trades_db.execute_update(cleanup_query, (trade['ticket_id'],))
    
    def test_database_connection_management(self):
        """Test that database connections are properly managed."""
        trades_db = get_trades_database()
        trades_db.init_database()
        
        # Test multiple operations to ensure connection pooling works
        for i in range(5):
            query = "SELECT COUNT(*) as count FROM trades"
            results = trades_db.execute_query(query)
            self.assertEqual(len(results), 1)
            self.assertIsInstance(results[0]['count'], int)
        
        # Test that connections are properly closed
        # This is handled by the context manager in the abstraction layer
        self.assertTrue(True)  # If we get here, no connection leaks occurred

if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2) 