#!/usr/bin/env python3
"""
Database Connection Test Script
Tests PostgreSQL connection and required schemas
"""

import psycopg2
import sys
from datetime import datetime

def test_database_connection():
    """Test database connection and required schemas."""
    print("🔍 Testing PostgreSQL database connection...")
    
    try:
        # Test connection
        conn = psycopg2.connect(
            host='localhost',
            database='rec_io_db',
            user='rec_io_user',
            password='rec_io_password',
            connect_timeout=10
        )
        print("✅ Database connection successful")
        
        cursor = conn.cursor()
        
        # Test basic query
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]
        print(f"✅ PostgreSQL version: {version}")
        
        # Check required schemas
        cursor.execute("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name IN ('historical_data', 'analytics', 'work_progress')
            ORDER BY schema_name
        """)
        
        schemas = [row[0] for row in cursor.fetchall()]
        required_schemas = ['historical_data', 'analytics', 'work_progress']
        
        print(f"✅ Found schemas: {schemas}")
        
        missing_schemas = [s for s in required_schemas if s not in schemas]
        if missing_schemas:
            print(f"❌ Missing schemas: {missing_schemas}")
            
            # Create missing schemas
            for schema in missing_schemas:
                try:
                    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                    print(f"✅ Created schema: {schema}")
                except Exception as e:
                    print(f"❌ Failed to create schema {schema}: {e}")
        else:
            print("✅ All required schemas exist")
        
        # Check for symbol tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'historical_data'
            AND table_name LIKE '%_price_history'
            ORDER BY table_name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        print(f"✅ Found price history tables: {tables}")
        
        # Test table access
        if tables:
            test_table = tables[0]
            cursor.execute(f"SELECT COUNT(*) FROM historical_data.{test_table}")
            count = cursor.fetchone()[0]
            print(f"✅ Test table {test_table} has {count} rows")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("🎉 Database test completed successfully!")
        return True
        
    except psycopg2.OperationalError as e:
        print(f"❌ Database connection failed: {e}")
        print("💡 Check if PostgreSQL is running: sudo systemctl status postgresql")
        return False
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

def main():
    """Main test function."""
    print("=" * 60)
    print("🗄️  POSTGRESQL DATABASE CONNECTION TEST")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    
    success = test_database_connection()
    
    print()
    print("=" * 60)
    if success:
        print("✅ ALL TESTS PASSED - Database is ready for daily updates")
    else:
        print("❌ TESTS FAILED - Fix database issues before running daily updates")
    print("=" * 60)
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
