#!/usr/bin/env python3

"""
Add win_streak_threshold column to monitor_list tables

This script adds the win_streak_threshold column (INTEGER) to all existing monitor_list_XXXX tables
and sets the default value to 22 for all existing monitors.
"""

import psycopg2
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def get_db_connection():
    """Get PostgreSQL database connection"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return None

def get_all_monitor_list_tables():
    """Find all monitor_list tables in the database"""
    conn = get_db_connection()
    if not conn:
        return []
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'users' 
                AND table_name LIKE 'monitor_list_%'
                ORDER BY table_name
            """)
            tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        return tables
    except Exception as e:
        print(f"❌ Error getting monitor_list tables: {e}")
        if conn:
            conn.close()
        return []

def add_win_streak_threshold_column(table_name):
    """Add win_streak_threshold column to a specific monitor_list table"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cursor:
            # Check if column already exists
            cursor.execute(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'users' 
                AND table_name = %s 
                AND column_name = 'win_streak_threshold'
            """, (table_name,))
            
            if cursor.fetchone():
                print(f"✓ Column win_streak_threshold already exists in {table_name}")
                conn.close()
                return True
            
            # Add the column with default value of 22
            cursor.execute(f"""
                ALTER TABLE users.{table_name}
                ADD COLUMN win_streak_threshold INTEGER DEFAULT 22
            """)
            
            # Update all existing rows to have the value 22
            cursor.execute(f"""
                UPDATE users.{table_name}
                SET win_streak_threshold = 22
                WHERE win_streak_threshold IS NULL
            """)
            
            conn.commit()
            print(f"✅ Added win_streak_threshold column to {table_name} and set default value to 22")
        
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error adding column to {table_name}: {e}")
        if conn:
            conn.close()
        return False

def main():
    print("=" * 60)
    print("Adding win_streak_threshold column to monitor_list tables")
    print("=" * 60)
    print()
    
    # Get all monitor_list tables
    tables = get_all_monitor_list_tables()
    
    if not tables:
        print("❌ No monitor_list tables found")
        return 1
    
    print(f"Found {len(tables)} monitor_list table(s):")
    for table in tables:
        print(f"  - {table}")
    print()
    
    # Add column to each table
    success_count = 0
    for table in tables:
        if add_win_streak_threshold_column(table):
            success_count += 1
    
    print()
    print("=" * 60)
    print(f"Migration complete: {success_count}/{len(tables)} tables updated")
    print("=" * 60)
    
    return 0 if success_count == len(tables) else 1

if __name__ == "__main__":
    sys.exit(main())

