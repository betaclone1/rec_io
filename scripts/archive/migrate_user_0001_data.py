#!/usr/bin/env python3
"""
Data Migration Script for user_0001
Migrates existing SQLite data to PostgreSQL user_0001 tables
"""

import sqlite3
import psycopg2
import json
import os
from datetime import datetime
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def get_postgres_connection():
    """Get PostgreSQL connection"""
    return psycopg2.connect(
        host='localhost',
        database='rec_io_db',
        user='rec_io_user',
        password='rec_io_password'
    )

def migrate_trades():
    """Migrate trades data from SQLite to PostgreSQL"""
    print("🔄 Migrating trades data...")
    
    # Connect to SQLite
    sqlite_path = "backend/data/users/user_0001/trade_history/trades.db"
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all trades from SQLite
        sqlite_cursor.execute("SELECT * FROM trades")
        trades = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(trades)} trades to migrate")
        
        # Get column names
        sqlite_cursor.execute("PRAGMA table_info(trades)")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        
        # Insert into PostgreSQL with proper data type handling
        for trade in trades:
            # Create a dictionary of column names and values
            trade_dict = dict(zip(columns, trade))
            
            # Handle ticket_id as text instead of integer
            if 'ticket_id' in trade_dict and trade_dict['ticket_id'] is not None:
                trade_dict['ticket_id'] = str(trade_dict['ticket_id'])
            
            # Build INSERT query dynamically
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO users.trades_0001 ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (id) DO NOTHING
            """
            
            # Convert values to proper types
            values = []
            for i, col in enumerate(columns):
                val = trade[i]
                if col == 'ticket_id' and val is not None:
                    values.append(str(val))
                else:
                    values.append(val)
            
            pg_cursor.execute(query, values)
        
        pg_conn.commit()
        print(f"✅ Successfully migrated {len(trades)} trades")
        
    except Exception as e:
        print(f"❌ Error migrating trades: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

def migrate_active_trades():
    """Migrate active trades data from SQLite to PostgreSQL"""
    print("🔄 Migrating active trades data...")
    
    # Connect to SQLite
    sqlite_path = "backend/data/users/user_0001/trade_history/trades.db"
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all active trades from SQLite
        sqlite_cursor.execute("SELECT * FROM active_trades")
        active_trades = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(active_trades)} active trades to migrate")
        
        # Get column names
        sqlite_cursor.execute("PRAGMA table_info(active_trades)")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        
        # Insert into PostgreSQL
        for trade in active_trades:
            # Create a dictionary of column names and values
            trade_dict = dict(zip(columns, trade))
            
            # Build INSERT query dynamically
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO users.active_trades_0001 ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (id) DO NOTHING
            """
            
            pg_cursor.execute(query, trade)
        
        pg_conn.commit()
        print(f"✅ Successfully migrated {len(active_trades)} active trades")
        
    except Exception as e:
        print(f"❌ Error migrating active trades: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

def migrate_positions():
    """Migrate positions data from SQLite to PostgreSQL"""
    print("🔄 Migrating positions data...")
    
    # Connect to SQLite
    sqlite_path = "backend/data/users/user_0001/accounts/kalshi/prod/positions.db"
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all positions from SQLite
        sqlite_cursor.execute("SELECT * FROM positions")
        positions = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(positions)} positions to migrate")
        
        # Get column names
        sqlite_cursor.execute("PRAGMA table_info(positions)")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        
        # Insert into PostgreSQL
        for position in positions:
            # Create a dictionary of column names and values
            position_dict = dict(zip(columns, position))
            
            # Build INSERT query dynamically
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO users.positions_0001 ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (id) DO NOTHING
            """
            
            pg_cursor.execute(query, position)
        
        pg_conn.commit()
        print(f"✅ Successfully migrated {len(positions)} positions")
        
    except Exception as e:
        print(f"❌ Error migrating positions: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

def migrate_fills():
    """Migrate fills data from SQLite to PostgreSQL"""
    print("🔄 Migrating fills data...")
    
    # Connect to SQLite
    sqlite_path = "backend/data/users/user_0001/accounts/kalshi/prod/fills.db"
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all fills from SQLite
        sqlite_cursor.execute("SELECT * FROM fills")
        fills = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(fills)} fills to migrate")
        
        # Get column names
        sqlite_cursor.execute("PRAGMA table_info(fills)")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        
        # Insert into PostgreSQL with proper boolean handling
        for fill in fills:
            # Create a dictionary of column names and values
            fill_dict = dict(zip(columns, fill))
            
            # Convert is_taker to proper boolean
            if 'is_taker' in fill_dict and fill_dict['is_taker'] is not None:
                fill_dict['is_taker'] = bool(fill_dict['is_taker'])
            
            # Build INSERT query dynamically
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO users.fills_0001 ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (trade_id) DO NOTHING
            """
            
            # Convert values to proper types
            values = []
            for i, col in enumerate(columns):
                val = fill[i]
                if col == 'is_taker' and val is not None:
                    values.append(bool(val))
                else:
                    values.append(val)
            
            pg_cursor.execute(query, values)
        
        pg_conn.commit()
        print(f"✅ Successfully migrated {len(fills)} fills")
        
    except Exception as e:
        print(f"❌ Error migrating fills: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

def migrate_orders():
    """Migrate orders data from SQLite to PostgreSQL"""
    print("🔄 Migrating orders data...")
    
    # Connect to SQLite
    sqlite_path = "backend/data/users/user_0001/accounts/kalshi/prod/orders.db"
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all orders from SQLite
        sqlite_cursor.execute("SELECT * FROM orders")
        orders = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(orders)} orders to migrate")
        
        # Get column names
        sqlite_cursor.execute("PRAGMA table_info(orders)")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        
        # Insert into PostgreSQL
        for order in orders:
            # Create a dictionary of column names and values
            order_dict = dict(zip(columns, order))
            
            # Build INSERT query dynamically
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO users.orders_0001 ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (order_id) DO NOTHING
            """
            
            pg_cursor.execute(query, order)
        
        pg_conn.commit()
        print(f"✅ Successfully migrated {len(orders)} orders")
        
    except Exception as e:
        print(f"❌ Error migrating orders: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

def migrate_settlements():
    """Migrate settlements data from SQLite to PostgreSQL"""
    print("🔄 Migrating settlements data...")
    
    # Connect to SQLite
    sqlite_path = "backend/data/users/user_0001/accounts/kalshi/prod/settlements.db"
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all settlements from SQLite
        sqlite_cursor.execute("SELECT * FROM settlements")
        settlements = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(settlements)} settlements to migrate")
        
        # Get column names
        sqlite_cursor.execute("PRAGMA table_info(settlements)")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        
        # Insert into PostgreSQL
        for settlement in settlements:
            # Create a dictionary of column names and values
            settlement_dict = dict(zip(columns, settlement))
            
            # Build INSERT query dynamically
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO users.settlements_0001 ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (id) DO NOTHING
            """
            
            pg_cursor.execute(query, settlement)
        
        pg_conn.commit()
        print(f"✅ Successfully migrated {len(settlements)} settlements")
        
    except Exception as e:
        print(f"❌ Error migrating settlements: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

def migrate_account_balance():
    """Migrate account balance data from SQLite to PostgreSQL"""
    print("🔄 Migrating account balance data...")
    
    # Connect to SQLite
    sqlite_path = "backend/data/users/user_0001/accounts/kalshi/prod/account_balance_history.db"
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = get_postgres_connection()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get all balance history from SQLite
        sqlite_cursor.execute("SELECT * FROM balance_history")
        balance_records = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(balance_records)} balance records to migrate")
        
        # Get column names
        sqlite_cursor.execute("PRAGMA table_info(balance_history)")
        columns = [col[1] for col in sqlite_cursor.fetchall()]
        
        # Insert into PostgreSQL
        for record in balance_records:
            # Create a dictionary of column names and values
            record_dict = dict(zip(columns, record))
            
            # Build INSERT query dynamically
            columns_str = ', '.join(columns)
            placeholders = ', '.join(['%s'] * len(columns))
            
            query = f"""
                INSERT INTO users.account_balance_0001 ({columns_str})
                VALUES ({placeholders})
                ON CONFLICT (id) DO NOTHING
            """
            
            pg_cursor.execute(query, record)
        
        pg_conn.commit()
        print(f"✅ Successfully migrated {len(balance_records)} balance records")
        
    except Exception as e:
        print(f"❌ Error migrating account balance: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

def main():
    """Main migration function"""
    print("🚀 Starting user_0001 data migration...")
    
    # Run all migrations
    migrate_trades()
    migrate_active_trades()
    migrate_positions()
    migrate_fills()
    migrate_orders()
    migrate_settlements()
    migrate_account_balance()
    
    print("✅ User_0001 data migration completed!")

if __name__ == "__main__":
    main() 