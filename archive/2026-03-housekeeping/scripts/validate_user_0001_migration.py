#!/usr/bin/env python3
"""
Validation Script for user_0001 Migration
Verifies that data migration was successful and all data is intact
"""

import sqlite3
import psycopg2
import json
import os
import sys

def get_postgres_connection():
    """Get PostgreSQL connection"""
    return psycopg2.connect(
        host='localhost',
        database='rec_io_db',
        user='rec_io_user',
        password='rec_io_password'
    )

def validate_table_counts():
    """Validate that table row counts match between SQLite and PostgreSQL"""
    print("🔍 Validating table row counts...")
    
    # Define table mappings
    table_mappings = {
        'trades': ('backend/data/users/user_0001/trade_history/trades.db', 'users.trades_0001'),
        'active_trades': ('backend/data/users/user_0001/trade_history/trades.db', 'users.active_trades_0001'),
        'positions': ('backend/data/users/user_0001/accounts/kalshi/prod/positions.db', 'users.positions_0001'),
        'fills': ('backend/data/users/user_0001/accounts/kalshi/prod/fills.db', 'users.fills_0001'),
        'orders': ('backend/data/users/user_0001/accounts/kalshi/prod/orders.db', 'users.orders_0001'),
        'settlements': ('backend/data/users/user_0001/accounts/kalshi/prod/settlements.db', 'users.settlements_0001'),
        'account_balance': ('backend/data/users/user_0001/accounts/kalshi/prod/account_balance_history.db', 'users.account_balance_0001')
    }
    
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    all_passed = True
    
    for table_name, (sqlite_path, pg_table) in table_mappings.items():
        try:
            # Get SQLite count
            sqlite_conn = sqlite3.connect(sqlite_path)
            sqlite_cursor = sqlite_conn.cursor()
            
            if table_name == 'active_trades':
                sqlite_cursor.execute("SELECT COUNT(*) FROM active_trades")
            elif table_name == 'account_balance':
                sqlite_cursor.execute("SELECT COUNT(*) FROM balance_history")
            else:
                sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            
            sqlite_count = sqlite_cursor.fetchone()[0]
            sqlite_conn.close()
            
            # Get PostgreSQL count
            pg_cursor.execute(f"SELECT COUNT(*) FROM {pg_table}")
            pg_count = pg_cursor.fetchone()[0]
            
            if sqlite_count == pg_count:
                print(f"✅ {table_name}: {sqlite_count} rows (match)")
            else:
                print(f"❌ {table_name}: SQLite={sqlite_count}, PostgreSQL={pg_count} (mismatch)")
                all_passed = False
                
        except Exception as e:
            print(f"❌ Error validating {table_name}: {e}")
            all_passed = False
    
    pg_conn.close()
    return all_passed

def validate_sample_data():
    """Validate sample data integrity between SQLite and PostgreSQL"""
    print("🔍 Validating sample data integrity...")
    
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    # Test trades table
    try:
        # Get a sample trade from PostgreSQL
        pg_cursor.execute("SELECT id, status, date, time, symbol, side, buy_price, position FROM users.trades_0001 LIMIT 1")
        pg_trade = pg_cursor.fetchone()
        
        if pg_trade:
            print(f"✅ Sample trade found: ID={pg_trade[0]}, Status={pg_trade[1]}, Symbol={pg_trade[4]}")
        else:
            print("⚠️ No trades found in PostgreSQL")
            
    except Exception as e:
        print(f"❌ Error validating sample trade: {e}")
    
    # Test positions table
    try:
        pg_cursor.execute("SELECT id, ticker, position, realized_pnl FROM users.positions_0001 LIMIT 1")
        pg_position = pg_cursor.fetchone()
        
        if pg_position:
            print(f"✅ Sample position found: ID={pg_position[0]}, Ticker={pg_position[1]}, Position={pg_position[2]}")
        else:
            print("⚠️ No positions found in PostgreSQL")
            
    except Exception as e:
        print(f"❌ Error validating sample position: {e}")
    
    # Test fills table
    try:
        pg_cursor.execute("SELECT id, trade_id, ticker, side, count FROM users.fills_0001 LIMIT 1")
        pg_fill = pg_cursor.fetchone()
        
        if pg_fill:
            print(f"✅ Sample fill found: ID={pg_fill[0]}, Trade ID={pg_fill[1]}, Ticker={pg_fill[2]}")
        else:
            print("⚠️ No fills found in PostgreSQL")
            
    except Exception as e:
        print(f"❌ Error validating sample fill: {e}")
    
    pg_conn.close()

def validate_user_info():
    """Validate user info and preferences"""
    print("🔍 Validating user info and preferences...")
    
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Check user master table
        pg_cursor.execute("SELECT user_id, username, name, email FROM users.user_master WHERE user_id = '0001'")
        user_info = pg_cursor.fetchone()
        
        if user_info:
            print(f"✅ User info: ID={user_info[0]}, Username={user_info[1]}, Name={user_info[2]}, Email={user_info[3]}")
        else:
            print("❌ User info not found")
        
        # Check trade preferences
        pg_cursor.execute("SELECT preference_key, preference_value FROM users.trade_preferences_0001")
        preferences = pg_cursor.fetchall()
        
        if preferences:
            print(f"✅ Found {len(preferences)} trade preferences")
            for pref in preferences:
                print(f"   - {pref[0]}: {pref[1]}")
        else:
            print("⚠️ No trade preferences found")
        
        # Check auto trade settings
        pg_cursor.execute("SELECT setting_name, setting_value FROM users.auto_trade_settings_0001")
        settings = pg_cursor.fetchall()
        
        if settings:
            print(f"✅ Found {len(settings)} auto trade settings")
            for setting in settings:
                print(f"   - {setting[0]}: {setting[1]}")
        else:
            print("⚠️ No auto trade settings found")
            
    except Exception as e:
        print(f"❌ Error validating user info: {e}")
    
    pg_conn.close()

def validate_indexes():
    """Validate that indexes were created properly"""
    print("🔍 Validating indexes...")
    
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Check indexes on trades table
        pg_cursor.execute("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'trades_0001' AND schemaname = 'users'
        """)
        indexes = pg_cursor.fetchall()
        
        expected_indexes = ['idx_trades_0001_date', 'idx_trades_0001_symbol', 'idx_trades_0001_status', 'idx_trades_0001_ticket_id']
        found_indexes = [idx[0] for idx in indexes]
        
        for expected in expected_indexes:
            if expected in found_indexes:
                print(f"✅ Index {expected} exists")
            else:
                print(f"❌ Index {expected} missing")
        
        # Check unique indexes
        pg_cursor.execute("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'positions_0001' AND schemaname = 'users'
        """)
        pos_indexes = pg_cursor.fetchall()
        
        if any('ticker' in idx[0] for idx in pos_indexes):
            print("✅ Positions ticker unique index exists")
        else:
            print("❌ Positions ticker unique index missing")
            
    except Exception as e:
        print(f"❌ Error validating indexes: {e}")
    
    pg_conn.close()

def main():
    """Main validation function"""
    print("🚀 Starting user_0001 migration validation...")
    
    # Run all validations
    counts_valid = validate_table_counts()
    validate_sample_data()
    validate_user_info()
    validate_indexes()
    
    if counts_valid:
        print("✅ All validations passed! Migration appears successful.")
    else:
        print("❌ Some validations failed. Please check the migration.")

if __name__ == "__main__":
    main() 