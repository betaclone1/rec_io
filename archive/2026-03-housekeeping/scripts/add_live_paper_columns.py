#!/usr/bin/env python3
"""
Add LIVE and PAPER columns to trade_history_preferences_0001 table
"""

import psycopg2
import sys

def add_live_paper_columns():
    """Add live_filter and paper_filter columns to trade_history_preferences_0001 table"""
    
    new_columns = [
        ("live_filter", "BOOLEAN DEFAULT TRUE"),
        ("paper_filter", "BOOLEAN DEFAULT FALSE"),
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
        
        conn.commit()
        conn.close()
        
        print("✅ Database migration completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database migration failed: {e}")
        return False

if __name__ == "__main__":
    success = add_live_paper_columns()
    sys.exit(0 if success else 1)
