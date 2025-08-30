#!/usr/bin/env python3
"""
Add dashboard_order column to monitors_list_0001 table

This script adds the dashboard_order column to existing monitors_list_0001 tables
and initializes the order based on the current ID order.
"""

import sys
import os

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.core.config.database import get_postgresql_connection

def add_dashboard_order_column():
    """Add dashboard_order column to monitors_list_0001 table"""
    try:
        conn = get_postgresql_connection()
        if not conn:
            print("❌ Cannot connect to database")
            return False
        
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'users' 
            AND table_name = 'monitors_list_0001' 
            AND column_name = 'dashboard_order'
        """)
        
        if cursor.fetchone():
            print("✅ dashboard_order column already exists")
            return True
        
        # Add the column
        print("🔧 Adding dashboard_order column...")
        cursor.execute("""
            ALTER TABLE users.monitors_list_0001 
            ADD COLUMN dashboard_order INTEGER DEFAULT 0
        """)
        
        # Initialize dashboard_order based on current ID order
        print("🔧 Initializing dashboard_order values...")
        cursor.execute("""
            UPDATE users.monitors_list_0001 
            SET dashboard_order = id 
            WHERE dashboard_order = 0 OR dashboard_order IS NULL
        """)
        
        conn.commit()
        print("✅ Successfully added dashboard_order column and initialized values")
        
        # Verify the update
        cursor.execute("SELECT COUNT(*) FROM users.monitors_list_0001")
        count = cursor.fetchone()[0]
        print(f"📊 Updated {count} monitor records")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error adding dashboard_order column: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    print("🚀 Adding dashboard_order column to monitors_list_0001 table...")
    success = add_dashboard_order_column()
    if success:
        print("✅ Script completed successfully")
    else:
        print("❌ Script failed")
        sys.exit(1)
