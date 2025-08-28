#!/usr/bin/env python3
"""
Add missing columns to trade_history_preferences_0001 table
"""

import psycopg2
import sys

def add_missing_columns():
    """Add missing columns to trade_history_preferences_0001 table"""
    
    # Columns to add
    new_columns = [
        # Date columns (replace custom_date_start/end)
        ("start_date", "TEXT"),
        ("end_date", "TEXT"),
        
        # Contract filter columns
        ("contract_9am", "BOOLEAN DEFAULT TRUE"),
        ("contract_10am", "BOOLEAN DEFAULT TRUE"),
        ("contract_11am", "BOOLEAN DEFAULT TRUE"),
        ("contract_12am", "BOOLEAN DEFAULT TRUE"),
        ("contract_1pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_2pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_3pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_4pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_5pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_6pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_7pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_8pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_9pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_10pm", "BOOLEAN DEFAULT TRUE"),
        ("contract_11pm", "BOOLEAN DEFAULT TRUE"),
        
        # Symbol filter columns
        ("symbol_btc", "BOOLEAN DEFAULT TRUE"),
        ("symbol_eth", "BOOLEAN DEFAULT TRUE"),
        ("symbol_spy", "BOOLEAN DEFAULT TRUE"),
        ("symbol_ndx", "BOOLEAN DEFAULT TRUE"),
        ("symbol_usd_eur", "BOOLEAN DEFAULT TRUE"),
        
        # Strategy filter columns
        ("strategy_hourly_htc", "BOOLEAN DEFAULT TRUE"),
        ("strategy_momentum_scalp", "BOOLEAN DEFAULT TRUE"),
        ("strategy_test", "BOOLEAN DEFAULT TRUE"),
        
        # Analysis panel columns
        ("analysis_interval", "TEXT DEFAULT 'daily'"),
    ]
    
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'users' AND table_name = 'trade_history_preferences_0001'
        """)
        
        if not cursor.fetchone():
            print("❌ Table users.trade_history_preferences_0001 does not exist")
            return False
        
        print("✅ Table users.trade_history_preferences_0001 exists")
        
        # Check existing columns
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'users' AND table_name = 'trade_history_preferences_0001'
        """)
        
        existing_columns = [row[0] for row in cursor.fetchall()]
        print(f"Existing columns: {existing_columns}")
        
        # Add missing columns
        for column_name, column_type in new_columns:
            if column_name not in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE users.trade_history_preferences_0001 ADD COLUMN {column_name} {column_type}")
                    print(f"✅ Added column: {column_name}")
                except Exception as e:
                    print(f"❌ Failed to add column {column_name}: {e}")
            else:
                print(f"⏭️  Column already exists: {column_name}")
        
        # Remove old columns if they exist
        old_columns = ["custom_date_start", "custom_date_end"]
        for column_name in old_columns:
            if column_name in existing_columns:
                try:
                    cursor.execute(f"ALTER TABLE users.trade_history_preferences_0001 DROP COLUMN {column_name}")
                    print(f"✅ Removed old column: {column_name}")
                except Exception as e:
                    print(f"❌ Failed to remove column {column_name}: {e}")
        
        conn.commit()
        conn.close()
        
        print("✅ Database migration completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database migration failed: {e}")
        return False

if __name__ == "__main__":
    success = add_missing_columns()
    sys.exit(0 if success else 1)
