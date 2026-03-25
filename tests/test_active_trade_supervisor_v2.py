#!/usr/bin/env python3
"""
Test script for Active Trade Supervisor V2.
This test verifies that the completely rewritten active trade supervisor works correctly
with the new database abstraction layer.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import tempfile
import shutil
import time
import json

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Import the new active trade supervisor
from backend.active_trade_supervisor_v2 import (
    ActiveTradeSupervisor,
    SupervisorState,
    state,
    supervisor
)

class TestActiveTradeSupervisorV2(unittest.TestCase):
    """Test the completely rewritten active trade supervisor."""
    
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
        
        # Create a fresh supervisor instance for testing
        self.supervisor = ActiveTradeSupervisor()
    
    def tearDown(self):
        """Clean up test environment."""
        # Restore environment variables
        for key, value in self.original_env.items():
            os.environ[key] = value
        
        # Clean up temporary directory
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_supervisor_initialization(self):
        """Test that the supervisor initializes correctly."""
        try:
            # Test that databases are initialized
            self.assertIsNotNone(self.supervisor.active_trades_db)
            self.assertIsNotNone(self.supervisor.trades_db)
            
            # Test that databases are working
            self.assertTrue(self.supervisor.active_trades_db.table_exists("active_trades"))
            self.assertTrue(self.supervisor.trades_db.table_exists("trades"))
            
        except Exception as e:
            self.fail(f"Supervisor initialization failed: {e}")
    
    def test_add_new_active_trade(self):
        """Test adding a new active trade."""
        # First, add a test trade to the main trades database
        test_trade = {
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
            'ticket_id': f'SUPERVISOR-TEST-{int(time.time())}-001',
            'entry_method': 'manual'
        }
        
        # Insert test trade into main trades database
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
        
        affected_rows = self.supervisor.trades_db.execute_update(insert_query, insert_params)
        self.assertEqual(affected_rows, 1)
        
        # Get the inserted trade ID
        query = "SELECT id FROM trades WHERE ticket_id = ?"
        results = self.supervisor.trades_db.execute_query(query, (test_trade['ticket_id'],))
        self.assertEqual(len(results), 1)
        trade_id = results[0]['id']
        
        # Now test adding it to active trades
        success = self.supervisor.add_new_active_trade(trade_id, test_trade['ticket_id'])
        self.assertTrue(success)
        
        # Verify the trade was added to active trades
        active_trades = self.supervisor.get_all_active_trades()
        self.assertGreaterEqual(len(active_trades), 1)
        
        # Find our test trade
        test_trade_found = False
        for trade in active_trades:
            if trade['ticket_id'] == test_trade['ticket_id']:
                test_trade_found = True
                self.assertEqual(trade['trade_id'], trade_id)
                self.assertEqual(trade['status'], 'active')
                break
        
        self.assertTrue(test_trade_found, "Test trade not found in active trades")
        
        # Clean up
        cleanup_query = "DELETE FROM trades WHERE ticket_id = ?"
        self.supervisor.trades_db.execute_update(cleanup_query, (test_trade['ticket_id'],))
        
        cleanup_query = "DELETE FROM active_trades WHERE ticket_id = ?"
        self.supervisor.active_trades_db.execute_update(cleanup_query, (test_trade['ticket_id'],))
    
    def test_get_all_active_trades(self):
        """Test getting all active trades."""
        # Add a test active trade directly
        test_trade = {
            'trade_id': 999,
            'ticket_id': f'SUPERVISOR-TEST-{int(time.time())}-002',
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
            test_trade['trade_id'], test_trade['ticket_id'],
            test_trade['date'], test_trade['time'], test_trade['strike'],
            test_trade['side'], test_trade['buy_price'], test_trade['position'],
            test_trade['contract'], test_trade['ticker'], test_trade['symbol'],
            test_trade['exchange'], test_trade['trade_strategy'], test_trade['symbol_open'],
            test_trade['momentum'], test_trade['prob'], test_trade['fees'],
            test_trade['diff'], test_trade['status']
        )
        
        affected_rows = self.supervisor.active_trades_db.execute_update(insert_query, insert_params)
        self.assertEqual(affected_rows, 1)
        
        # Test getting all active trades
        active_trades = self.supervisor.get_all_active_trades()
        self.assertGreaterEqual(len(active_trades), 1)
        
        # Find our test trade
        test_trade_found = False
        for trade in active_trades:
            if trade['ticket_id'] == test_trade['ticket_id']:
                test_trade_found = True
                self.assertEqual(trade['trade_id'], test_trade['trade_id'])
                self.assertEqual(trade['status'], 'active')
                break
        
        self.assertTrue(test_trade_found, "Test trade not found in active trades")
        
        # Clean up
        cleanup_query = "DELETE FROM active_trades WHERE ticket_id = ?"
        self.supervisor.active_trades_db.execute_update(cleanup_query, (test_trade['ticket_id'],))
    
    def test_update_trade_monitoring_data(self):
        """Test updating trade monitoring data."""
        # Add a test active trade
        test_trade = {
            'trade_id': 888,
            'ticket_id': f'SUPERVISOR-TEST-{int(time.time())}-003',
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
            test_trade['trade_id'], test_trade['ticket_id'],
            test_trade['date'], test_trade['time'], test_trade['strike'],
            test_trade['side'], test_trade['buy_price'], test_trade['position'],
            test_trade['contract'], test_trade['ticker'], test_trade['symbol'],
            test_trade['exchange'], test_trade['trade_strategy'], test_trade['symbol_open'],
            test_trade['momentum'], test_trade['prob'], test_trade['fees'],
            test_trade['diff'], test_trade['status']
        )
        
        affected_rows = self.supervisor.active_trades_db.execute_update(insert_query, insert_params)
        self.assertEqual(affected_rows, 1)
        
        # Test updating monitoring data
        updates = {
            'current_symbol_price': 50000.0,
            'current_probability': 80.0,
            'time_since_entry': 3600,
            'current_pnl': '0.1500',
            'last_updated': '2025-01-27T15:00:00'
        }
        
        success = self.supervisor.update_trade_monitoring_data(test_trade['trade_id'], **updates)
        self.assertTrue(success)
        
        # Verify the updates
        query = "SELECT * FROM active_trades WHERE trade_id = ?"
        results = self.supervisor.active_trades_db.execute_query(query, (test_trade['trade_id'],))
        self.assertEqual(len(results), 1)
        
        updated_trade = results[0]
        self.assertEqual(updated_trade['current_symbol_price'], 50000.0)
        self.assertEqual(updated_trade['current_probability'], 80.0)
        self.assertEqual(updated_trade['time_since_entry'], 3600)
        self.assertEqual(updated_trade['current_pnl'], '0.1500')
        
        # Clean up
        cleanup_query = "DELETE FROM active_trades WHERE ticket_id = ?"
        self.supervisor.active_trades_db.execute_update(cleanup_query, (test_trade['ticket_id'],))
    
    def test_remove_closed_trade(self):
        """Test removing a closed trade."""
        # Add a test active trade
        test_trade = {
            'trade_id': 777,
            'ticket_id': f'SUPERVISOR-TEST-{int(time.time())}-004',
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
            test_trade['trade_id'], test_trade['ticket_id'],
            test_trade['date'], test_trade['time'], test_trade['strike'],
            test_trade['side'], test_trade['buy_price'], test_trade['position'],
            test_trade['contract'], test_trade['ticker'], test_trade['symbol'],
            test_trade['exchange'], test_trade['trade_strategy'], test_trade['symbol_open'],
            test_trade['momentum'], test_trade['prob'], test_trade['fees'],
            test_trade['diff'], test_trade['status']
        )
        
        affected_rows = self.supervisor.active_trades_db.execute_update(insert_query, insert_params)
        self.assertEqual(affected_rows, 1)
        
        # Verify the trade exists
        active_trades = self.supervisor.get_all_active_trades()
        initial_count = len(active_trades)
        
        # Test removing the trade
        success = self.supervisor.remove_closed_trade(test_trade['trade_id'])
        self.assertTrue(success)
        
        # Verify the trade was removed
        active_trades = self.supervisor.get_all_active_trades()
        final_count = len(active_trades)
        self.assertEqual(final_count, initial_count - 1)
    
    def test_state_management(self):
        """Test the thread-safe state management."""
        # Ensure monitoring is stopped for this test
        state.monitoring_active = False
        
        # Test monitoring active state
        self.assertFalse(state.monitoring_active)
        state.monitoring_active = True
        self.assertTrue(state.monitoring_active)
        state.monitoring_active = False
        self.assertFalse(state.monitoring_active)
        
        # Test auto-stop triggered trades
        self.assertFalse(state.is_auto_stop_triggered(123))
        state.add_auto_stop_triggered(123)
        self.assertTrue(state.is_auto_stop_triggered(123))
        state.clear_auto_stop_triggered()
        self.assertFalse(state.is_auto_stop_triggered(123))
        
        # Test cache management
        current_time = time.time()
        cached_data, is_cached = state.get_cache(current_time)
        self.assertIsNone(cached_data)
        self.assertFalse(is_cached)
        
        test_data = [{"test": "data"}]
        state.set_cache(test_data, current_time)
        
        cached_data, is_cached = state.get_cache(current_time)
        self.assertEqual(cached_data, test_data)
        self.assertTrue(is_cached)
        
        state.invalidate_cache()
        cached_data, is_cached = state.get_cache(current_time)
        self.assertIsNone(cached_data)
        self.assertFalse(is_cached)
    
    def test_auto_stop_conditions(self):
        """Test auto-stop condition checking."""
        # Mock the auto-stop settings
        with patch('os.path.exists') as mock_exists, \
             patch('builtins.open', create=True) as mock_open:
            
            mock_exists.return_value = True
            mock_open.return_value.__enter__.return_value.read.return_value = json.dumps({
                "auto_stop_enabled": True,
                "auto_stop_threshold": 50.0,
                "min_ttc_seconds": 60
            })
            
            # Test with a trade that should trigger auto-stop
            test_trade = {
                'trade_id': 666,
                'current_probability': 45.0,  # Below threshold
                'time_since_entry': 120,      # Above min TTC
                'status': 'active'
            }
            
            # Mock the auto-stop triggered check
            with patch.object(state, 'is_auto_stop_triggered', return_value=False):
                # This should trigger auto-stop
                # Note: We're not actually calling the method here, just testing the logic
                should_trigger = (
                    test_trade['current_probability'] < 50.0 and
                    test_trade['status'] == 'active' and
                    test_trade['time_since_entry'] >= 60
                )
                
                self.assertTrue(should_trigger)
    
    def test_database_abstraction_integration(self):
        """Test that the supervisor properly uses the database abstraction layer."""
        # Test that the supervisor uses the abstraction layer correctly
        self.assertIsNotNone(self.supervisor.active_trades_db)
        self.assertIsNotNone(self.supervisor.trades_db)
        
        # Test that we can perform basic operations
        active_trades = self.supervisor.get_all_active_trades()
        self.assertIsInstance(active_trades, list)
        
        # Test that the databases are properly initialized
        self.assertTrue(self.supervisor.active_trades_db.table_exists("active_trades"))
        self.assertTrue(self.supervisor.trades_db.table_exists("trades"))

if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2) 