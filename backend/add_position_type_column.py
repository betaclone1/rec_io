#!/usr/bin/env python3
"""
Migration script to add position_type column to trade_preferences_0001 table
This column will store either 'percent' or 'contracts'
"""

import psycopg2
import sys

def add_position_type_column():
    try:
        # Connect to the remote database
        conn = psycopg2.connect(
            host="137.184.224.94",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            print("Adding position_type column to trade_preferences_0001...")
            
            # Add the position_type column with default value 'contracts'
            cursor.execute("""
                ALTER TABLE users.trade_preferences_0001 
                ADD COLUMN position_type VARCHAR(10) DEFAULT 'contracts'
            """)
            
            # Update existing rows to have 'contracts' as the default
            cursor.execute("""
                UPDATE users.trade_preferences_0001 
                SET position_type = 'contracts' 
                WHERE position_type IS NULL
            """)
            
            conn.commit()
            print("Position type column added successfully!")
            
            # Verify the changes
            cursor.execute("""
                SELECT id, trade_strategy, position_size, multiplier, position_type 
                FROM users.trade_preferences_0001
            """)
            results = cursor.fetchall()
            print("\nVerification - Current table structure:")
            for row in results:
                print(f"Row {row[0]}: strategy='{row[1]}', size={row[2]}, multiplier={row[3]}, type='{row[4]}'")
        
        conn.close()
        
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    add_position_type_column()
