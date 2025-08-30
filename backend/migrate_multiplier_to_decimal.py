#!/usr/bin/env python3
"""
Migration script to change multiplier column from INTEGER to DECIMAL(3,2)
This allows storing decimal values like 0.50, 1.00, 2.00
"""

import psycopg2
import sys

def migrate_multiplier_column():
    try:
        # Connect to the remote database
        conn = psycopg2.connect(
            host="137.184.224.94",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            print("Starting multiplier column migration...")
            
            # First, backup current multiplier values
            cursor.execute("SELECT id, multiplier FROM users.trade_preferences_0001")
            current_values = cursor.fetchall()
            print(f"Found {len(current_values)} rows to migrate")
            
            # Alter the column type to DECIMAL(3,2)
            print("Altering multiplier column to DECIMAL(3,2)...")
            cursor.execute("""
                ALTER TABLE users.trade_preferences_0001 
                ALTER COLUMN multiplier TYPE DECIMAL(3,2)
            """)
            
            # Update existing values to have 2 decimal places
            print("Updating existing values to 2 decimal places...")
            for row_id, multiplier in current_values:
                # Convert integer to decimal with 2 places
                decimal_multiplier = float(multiplier)
                cursor.execute("""
                    UPDATE users.trade_preferences_0001 
                    SET multiplier = %s 
                    WHERE id = %s
                """, (decimal_multiplier, row_id))
                print(f"Updated row {row_id}: {multiplier} -> {decimal_multiplier}")
            
            # Set default value to 1.00
            cursor.execute("""
                ALTER TABLE users.trade_preferences_0001 
                ALTER COLUMN multiplier SET DEFAULT 1.00
            """)
            
            conn.commit()
            print("Migration completed successfully!")
            
            # Verify the changes
            cursor.execute("SELECT id, multiplier FROM users.trade_preferences_0001")
            new_values = cursor.fetchall()
            print("\nVerification - Current values:")
            for row_id, multiplier in new_values:
                print(f"Row {row_id}: {multiplier} (type: {type(multiplier)})")
        
        conn.close()
        
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    migrate_multiplier_column()
