#!/usr/bin/env python3
"""
Database Setup Verification Script
Verifies that all required schemas, tables, and columns exist.
"""

import psycopg2
import sys

def verify_database_setup():
    """Verify all database components are properly set up."""
    
    required_schemas = ['users', 'live_data', 'system']
    required_tables = {
        'users': ['trades_0001', 'active_trades_0001', 'auto_trade_settings_0001', 
                 'trade_preferences_0001', 'trade_history_preferences_0001'],
        'live_data': ['live_price_log_1s_btc', 'live_price_log_1s_eth'],
        'system': ['health_status']
    }
    required_columns = {
        'users.trades_0001': ['test_filter'],
        'users.trade_preferences_0001': ['trade_strategy']
    }
    
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        cursor = conn.cursor()
        
        # Verify schemas
        for schema in required_schemas:
            cursor.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s", (schema,))
            if not cursor.fetchone():
                print(f"❌ Missing schema: {schema}")
                return False
            print(f"✅ Schema exists: {schema}")
        
        # Verify tables
        for schema, tables in required_tables.items():
            for table in tables:
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_name = %s", (schema, table))
                if not cursor.fetchone():
                    print(f"❌ Missing table: {schema}.{table}")
                    return False
                print(f"✅ Table exists: {schema}.{table}")
        
        # Verify columns
        for table, columns in required_columns.items():
            schema, table_name = table.split('.')
            for column in columns:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND column_name = %s", (schema, table_name, column))
                if not cursor.fetchone():
                    print(f"❌ Missing column: {table}.{column}")
                    return False
                print(f"✅ Column exists: {table}.{column}")
        
        conn.close()
        print("✅ Database setup verification completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database verification failed: {e}")
        return False

if __name__ == "__main__":
    success = verify_database_setup()
    sys.exit(0 if success else 1)
