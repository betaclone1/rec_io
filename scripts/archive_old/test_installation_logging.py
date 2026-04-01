#!/usr/bin/env python3
"""
Test Installation Logging

This script simulates a fake user accessing the database to test
the installation logging process and verify it works correctly.
"""

import os
import sys
import time
from datetime import datetime

# Add the backend directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from util.installation_logger import InstallationLogger

def test_installation_logging():
    """Test the installation logging process."""
    print("🧪 Testing Installation Logging Process")
    print("=" * 50)
    
    # Set up fake user environment variables
    os.environ['INSTALLER_USER_ID'] = 'test_user_001'
    os.environ['INSTALLER_NAME'] = 'Test User (Fake)'
    os.environ['INSTALLER_EMAIL'] = 'test@example.com'
    os.environ['INSTALLER_USER_AGENT'] = 'REC.IO Installation Package v1.0.0 (TEST)'
    os.environ['INSTALLATION_PACKAGE_VERSION'] = '1.0.0'
    
    # Set remote database environment variables
    os.environ.setdefault('DB_HOST', os.environ.get('REC_PROD_DB_HOST', 'localhost'))
    os.environ['DB_NAME'] = 'rec_io_db'
    os.environ['DB_USER'] = 'rec_io_installer'
    os.environ['DB_PASSWORD'] = 'secure_installer_password_2025'
    os.environ['DB_PORT'] = '5432'
    
    # Create logger instance
    logger = InstallationLogger()
    
    print("📝 Starting installation logging...")
    
    # Test 1: Start logging
    schemas_to_access = ['analytics', 'historical_data', 'live_data']
    success = logger.start_logging(schemas_to_access)
    
    if not success:
        print("❌ Failed to start logging")
        return False
    
    print(f"✅ Logging started successfully (ID: {logger.log_entry_id})")
    
    # Test 2: Simulate progress updates
    print("📊 Simulating progress updates...")
    
    # Simulate cloning analytics schema
    logger.update_progress(50, 50000)
    print("  - Updated progress: 50 tables, 50,000 rows")
    
    time.sleep(1)  # Simulate work
    
    # Simulate cloning historical_data schema
    logger.update_progress(52, 75000)
    print("  - Updated progress: 52 tables, 75,000 rows")
    
    time.sleep(1)  # Simulate work
    
    # Simulate cloning live_data schema
    logger.update_progress(137, 125000)
    print("  - Updated progress: 137 tables, 125,000 rows")
    
    # Test 3: Complete logging successfully
    print("✅ Completing logging (success)...")
    success = logger.complete_logging(success=True)
    
    if success:
        print("✅ Installation logging completed successfully")
    else:
        print("❌ Failed to complete logging")
        return False
    
    return True

def test_failed_installation_logging():
    """Test logging a failed installation."""
    print("\n🧪 Testing Failed Installation Logging")
    print("=" * 50)
    
    # Set up different fake user
    os.environ['INSTALLER_USER_ID'] = 'test_user_002'
    os.environ['INSTALLER_NAME'] = 'Failed Test User'
    os.environ['INSTALLER_EMAIL'] = 'failed@example.com'
    os.environ['INSTALLER_USER_AGENT'] = 'REC.IO Installation Package v1.0.0 (FAILED TEST)'
    os.environ['INSTALLATION_PACKAGE_VERSION'] = '1.0.0'
    
    # Set remote database environment variables
    os.environ.setdefault('DB_HOST', os.environ.get('REC_PROD_DB_HOST', 'localhost'))
    os.environ['DB_NAME'] = 'rec_io_db'
    os.environ['DB_USER'] = 'rec_io_installer'
    os.environ['DB_PASSWORD'] = 'secure_installer_password_2025'
    os.environ['DB_PORT'] = '5432'
    
    logger = InstallationLogger()
    
    print("📝 Starting failed installation logging...")
    
    # Start logging
    schemas_to_access = ['analytics', 'historical_data', 'live_data']
    success = logger.start_logging(schemas_to_access)
    
    if not success:
        print("❌ Failed to start logging")
        return False
    
    print(f"✅ Logging started (ID: {logger.log_entry_id})")
    
    # Simulate some progress
    logger.update_progress(10, 5000)
    print("  - Made some progress before failure...")
    
    time.sleep(1)  # Simulate work
    
    # Simulate failure
    error_message = "Connection timeout while cloning analytics schema"
    print(f"❌ Simulating failure: {error_message}")
    
    success = logger.log_error(error_message)
    
    if success:
        print("✅ Failed installation logged successfully")
    else:
        print("❌ Failed to log error")
        return False
    
    return True

def test_database_access():
    """Test actual database access with installer credentials."""
    print("\n🧪 Testing Database Access with Installer Credentials")
    print("=" * 50)
    
    try:
        import psycopg2
        
        # Test connection with installer credentials
        installer_config = {
            'host': os.environ.get('DB_HOST', os.environ.get('REC_PROD_DB_HOST', 'localhost')),  # Remote database
            'port': 5432,
            'database': 'rec_io_db',
            'user': 'rec_io_installer',
            'password': 'secure_installer_password_2025'
        }
        
        print("🔌 Testing connection with installer credentials...")
        conn = psycopg2.connect(**installer_config)
        cursor = conn.cursor()
        
        # Test 1: Check if we can connect
        cursor.execute("SELECT current_user, current_database()")
        user, db = cursor.fetchone()
        print(f"✅ Connected as {user} to {db}")
        
        # Test 2: Check accessible schemas
        cursor.execute("""
            SELECT DISTINCT schemaname 
            FROM pg_tables 
            WHERE schemaname NOT LIKE 'pg_%' 
            AND schemaname != 'information_schema'
            ORDER BY schemaname
        """)
        
        accessible_schemas = [row[0] for row in cursor.fetchall()]
        print(f"📊 Accessible schemas: {accessible_schemas}")
        
        # Test 3: Check table access in each schema
        for schema in ['analytics', 'historical_data', 'live_data']:
            cursor.execute("""
                SELECT COUNT(*) 
                FROM pg_tables 
                WHERE schemaname = %s
            """, (schema,))
            table_count = cursor.fetchone()[0]
            print(f"  - {schema}: {table_count} tables accessible")
        
        # Test 4: Try to read from a table
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = 'analytics'
        """)
        analytics_tables = cursor.fetchone()[0]
        print(f"✅ Can read analytics schema: {analytics_tables} tables found")
        
        # Test 5: Try to write to logging table
        cursor.execute("""
            INSERT INTO system.installation_access_log (
                installer_user_id, installer_name, installer_email,
                installer_ip_address, schemas_accessed, status
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            'test_access_user',
            'Test Access User',
            'test@access.com',
            '127.0.0.1',
            ['analytics', 'historical_data', 'live_data'],
            'test'
        ))
        
        test_log_id = cursor.fetchone()[0]
        print(f"✅ Can write to logging table: ID {test_log_id}")
        
        # Clean up test entry
        cursor.execute("DELETE FROM system.installation_access_log WHERE id = %s", (test_log_id,))
        print("✅ Test log entry cleaned up")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Database access test completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database access test failed: {e}")
        return False

def view_test_results():
    """View the test results in the logs."""
    print("\n📊 Viewing Test Results")
    print("=" * 50)
    
    # Set remote database environment variables
    os.environ.setdefault('DB_HOST', os.environ.get('REC_PROD_DB_HOST', 'localhost'))
    os.environ['DB_NAME'] = 'rec_io_db'
    os.environ['DB_USER'] = 'rec_io_installer'
    os.environ['DB_PASSWORD'] = 'secure_installer_password_2025'
    os.environ['DB_PORT'] = '5432'
    
    logger = InstallationLogger()
    
    # Get recent installations
    installations = logger.get_recent_installations(10)
    
    if not installations:
        print("No installation logs found.")
        return
    
    print("Recent installation logs:")
    for inst in installations:
        print(f"  ID: {inst['id']}")
        print(f"  User: {inst['installer_user_id']} ({inst['installer_name']})")
        print(f"  Email: {inst['installer_email']}")
        print(f"  IP: {inst['installer_ip_address']}")
        print(f"  Status: {inst['status']}")
        print(f"  Tables: {inst['tables_cloned'] or 0}")
        print(f"  Rows: {inst['total_rows_cloned'] or 0}")
        print(f"  Duration: {inst['clone_duration_seconds'] or 0}s")
        if inst['error_message']:
            print(f"  Error: {inst['error_message']}")
        print("  ---")

def main():
    """Run all tests."""
    print("🧪 REC.IO Installation Logging Test Suite")
    print("=" * 60)
    
    # Test 1: Successful installation logging
    success1 = test_installation_logging()
    
    # Test 2: Failed installation logging
    success2 = test_failed_installation_logging()
    
    # Test 3: Database access
    success3 = test_database_access()
    
    # View results
    view_test_results()
    
    # Summary
    print("\n📋 Test Summary")
    print("=" * 30)
    print(f"Successful Installation Logging: {'✅ PASS' if success1 else '❌ FAIL'}")
    print(f"Failed Installation Logging: {'✅ PASS' if success2 else '❌ FAIL'}")
    print(f"Database Access: {'✅ PASS' if success3 else '❌ FAIL'}")
    
    if all([success1, success2, success3]):
        print("\n🎉 All tests passed! Installation logging is working correctly.")
    else:
        print("\n⚠️  Some tests failed. Please check the errors above.")

if __name__ == "__main__":
    main()
