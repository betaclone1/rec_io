#!/usr/bin/env python3
"""
Simple database connection test
"""

import sys
import os

# Add project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from backend.core.unified_config import UnifiedConfigManager

def test_db_connection():
    """Test database connection"""
    try:
        config = UnifiedConfigManager()
        db_config = config.get_database_config()
        print(f"Database config: {db_config}")
        
        import psycopg2
        # Convert config to psycopg2 format
        psycopg2_config = db_config.copy()
        if 'name' in psycopg2_config:
            psycopg2_config['database'] = psycopg2_config.pop('name')
        conn = psycopg2.connect(**psycopg2_config)
        print("✅ Database connection successful")
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT bankroll_current FROM users.account_balance_0001 WHERE id = 1")
            result = cursor.fetchone()
            print(f"Bankroll: {result}")
            
            cursor.execute("SELECT position_size, position_type, multiplier FROM users.trade_preferences_0001 WHERE id = 1")
            result = cursor.fetchone()
            print(f"Position settings: {result}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False

if __name__ == "__main__":
    test_db_connection()
