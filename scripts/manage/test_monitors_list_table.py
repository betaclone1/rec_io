#!/usr/bin/env python3
"""
Test script for monitor_list_0001 table creation and sample data insertion
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

from core.config.database import get_postgresql_connection, init_database

def test_monitors_list_table():
    """Test the monitor_list_0001 table creation and add sample data"""
    
    print("🔧 Testing monitor_list_0001 table creation...")
    
    # Initialize database (this will create the table)
    success, message = init_database()
    if not success:
        print(f"❌ Database initialization failed: {message}")
        return False
    
    print("✅ Database initialized successfully")
    
    # Connect to database
    conn = get_postgresql_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return False
    
    cursor = conn.cursor()
    
    try:
        # Test table creation
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'users' 
                AND table_name = 'monitor_list_0001'
            );
        """)
        
        table_exists = cursor.fetchone()[0]
        if not table_exists:
            print("❌ monitor_list_0001 table does not exist")
            return False
        
        print("✅ monitor_list_0001 table exists")
        
        # Test sequence creation
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.sequences 
                WHERE sequence_schema = 'users' 
                AND sequence_name = 'monitor_list_0001_id_seq'
            );
        """)
        
        sequence_exists = cursor.fetchone()[0]
        if not sequence_exists:
            print("❌ monitor_list_0001_id_seq sequence does not exist")
            return False
        
        print("✅ monitor_list_0001_id_seq sequence exists")
        
        # Check current sequence value
        cursor.execute("SELECT last_value FROM users.monitor_list_0001_id_seq;")
        current_value = cursor.fetchone()[0]
        print(f"✅ Current sequence value: {current_value}")
        
        # Insert sample data
        sample_monitors = [
            {
                'name': 'BTC Momentum Monitor',
                'symbol': 'BTC',
                'strategy': 'momentum_based',
                'auto_trade': True,
                'auto_trade_status': 'active',
                'trades': 15,
                'win_loss': 73.3,
                'ret_pct': 12.5,
                'pnl': 1250.50,
                'bankroll_allotment': 25.0,
                'status': 'active'
            },
            {
                'name': 'ETH Breakout Monitor',
                'symbol': 'ETH',
                'strategy': 'breakout_strategy',
                'auto_trade': False,
                'auto_trade_status': 'inactive',
                'trades': 8,
                'win_loss': 62.5,
                'ret_pct': 8.2,
                'pnl': 820.00,
                'bankroll_allotment': 15.0,
                'status': 'active'
            },
            {
                'name': 'BTC Scalping Monitor',
                'symbol': 'BTC',
                'strategy': 'scalping',
                'auto_trade': True,
                'auto_trade_status': 'paused',
                'trades': 32,
                'win_loss': 68.8,
                'ret_pct': 18.7,
                'pnl': 1870.25,
                'bankroll_allotment': 30.0,
                'status': 'active'
            }
        ]
        
        for monitor in sample_monitors:
            cursor.execute("""
                INSERT INTO users.monitor_list_0001 (
                    name, symbol, strategy, auto_trade, auto_trade_status,
                    trades, win_loss, ret_pct, pnl, bankroll_allotment, status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) RETURNING id;
            """, (
                monitor['name'], monitor['symbol'], monitor['strategy'],
                monitor['auto_trade'], monitor['auto_trade_status'],
                monitor['trades'], monitor['win_loss'], monitor['ret_pct'],
                monitor['pnl'], monitor['bankroll_allotment'], monitor['status']
            ))
            
            monitor_id = cursor.fetchone()[0]
            print(f"✅ Inserted monitor '{monitor['name']}' with ID: {monitor_id}")
        
        # Verify data insertion
        cursor.execute("SELECT COUNT(*) FROM users.monitors_list_0001;")
        count = cursor.fetchone()[0]
        print(f"✅ Total monitors in table: {count}")
        
        # Show all monitors
        cursor.execute("""
            SELECT id, name, symbol, strategy, auto_trade, auto_trade_status,
                   trades, win_loss, ret_pct, pnl, bankroll_allotment, status
            FROM users.monitors_list_0001
            ORDER BY id;
        """)
        
        monitors = cursor.fetchall()
        print("\n📊 Current monitors in table:")
        print("-" * 80)
        for monitor in monitors:
            print(f"ID: {monitor[0]}, Name: {monitor[1]}, Symbol: {monitor[2]}, "
                  f"Strategy: {monitor[3]}, Auto Trade: {monitor[4]}, "
                  f"Status: {monitor[5]}, Trades: {monitor[6]}, "
                  f"Win/Loss: {monitor[7]}%, Return: {monitor[8]}%, "
                  f"PnL: ${monitor[9]}, Bankroll: {monitor[10]}%")
        
        conn.commit()
        print("\n✅ monitors_list_0001 table test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error during test: {e}")
        conn.rollback()
        return False
    
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    success = test_monitors_list_table()
    sys.exit(0 if success else 1)
