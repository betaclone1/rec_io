#!/usr/bin/env python3
"""
Migration script to add total_position column to trade_preferences_0001 table
This column will store the calculated total contracts based on position_size, position_type, and multiplier
"""

import psycopg2
import sys

def add_total_position_column():
    try:
        # Connect to the remote database
        conn = psycopg2.connect(
            host="137.184.224.94",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            print("Adding total_position column to trade_preferences_0001...")
            
            # Add the total_position column with default value 1
            cursor.execute("""
                ALTER TABLE users.trade_preferences_0001 
                ADD COLUMN total_position INTEGER DEFAULT 1
            """)
            
            # Update existing rows to have a default total_position value
            cursor.execute("""
                UPDATE users.trade_preferences_0001 
                SET total_position = position_size * multiplier 
                WHERE total_position IS NULL
            """)
            
            conn.commit()
            print("Total position column added successfully!")
            
            # Verify the changes
            cursor.execute("""
                SELECT id, trade_strategy, position_size, multiplier, position_type, total_position 
                FROM users.trade_preferences_0001
            """)
            results = cursor.fetchall()
            print("\nVerification - Current table structure:")
            for row in results:
                print(f"Row {row[0]}: strategy='{row[1]}', size={row[2]}, multiplier={row[3]}, type='{row[4]}', total={row[5]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    add_total_position_column()
