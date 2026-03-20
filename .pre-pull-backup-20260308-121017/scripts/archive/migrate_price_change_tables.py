#!/usr/bin/env python3
"""
Migration script to rename price change tables from old naming convention
to new naming convention: price_change_<symbol>

This script:
1. Creates new tables with the new naming convention
2. Migrates existing data from old tables to new tables
3. Verifies the migration was successful
4. Provides option to drop old tables (commented out for safety)
"""

import os
import sys
import psycopg2
from datetime import datetime
import argparse

def get_postgres_connection():
    """Get a PostgreSQL connection"""
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=int(os.getenv('POSTGRES_PORT', '5432')),
        database=os.getenv('POSTGRES_DB', 'rec_io_db'),
        user=os.getenv('POSTGRES_USER', 'rec_io_user'),
        password=os.getenv('POSTGRES_PASSWORD', '')
    )

def create_new_price_change_tables():
    """Create new price change tables with the updated naming convention"""
    print("🔧 Creating new price change tables with updated naming convention...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Create new BTC price change table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_btc (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Create new ETH price change table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.price_change_eth (
                id SERIAL PRIMARY KEY,
                change1h DECIMAL(10,6),
                change3h DECIMAL(10,6),
                change1d DECIMAL(10,6),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.commit()
        print("✅ New price change tables created successfully")
        
    except Exception as e:
        print(f"❌ Error creating new price change tables: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def migrate_btc_price_change_data():
    """Migrate data from btc_price_change to price_change_btc"""
    print("🔄 Migrating BTC price change data...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check if old table exists and has data
        cursor.execute("SELECT COUNT(*) FROM live_data.btc_price_change")
        old_count = cursor.fetchone()[0]
        print(f"📊 Found {old_count} records in old BTC price change table")
        
        if old_count == 0:
            print("⚠️ No data to migrate for BTC price change")
            return
        
        # Migrate data
        cursor.execute("""
            INSERT INTO live_data.price_change_btc 
            (change1h, change3h, change1d, timestamp)
            SELECT change1h, change3h, change1d, timestamp
            FROM live_data.btc_price_change
            ON CONFLICT DO NOTHING
        """)
        
        # Verify migration
        cursor.execute("SELECT COUNT(*) FROM live_data.price_change_btc")
        new_count = cursor.fetchone()[0]
        
        conn.commit()
        print(f"✅ BTC price change data migration complete: {new_count} records migrated")
        
    except Exception as e:
        print(f"❌ Error migrating BTC price change data: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def migrate_eth_price_change_data():
    """Migrate data from eth_price_change to price_change_eth"""
    print("🔄 Migrating ETH price change data...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check if old table exists and has data
        cursor.execute("SELECT COUNT(*) FROM live_data.eth_price_change")
        old_count = cursor.fetchone()[0]
        print(f"📊 Found {old_count} records in old ETH price change table")
        
        if old_count == 0:
            print("⚠️ No data to migrate for ETH price change")
            return
        
        # Migrate data
        cursor.execute("""
            INSERT INTO live_data.price_change_eth 
            (change1h, change3h, change1d, timestamp)
            SELECT change1h, change3h, change1d, timestamp
            FROM live_data.eth_price_change
            ON CONFLICT DO NOTHING
        """)
        
        # Verify migration
        cursor.execute("SELECT COUNT(*) FROM live_data.price_change_eth")
        new_count = cursor.fetchone()[0]
        
        conn.commit()
        print(f"✅ ETH price change data migration complete: {new_count} records migrated")
        
    except Exception as e:
        print(f"❌ Error migrating ETH price change data: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def verify_price_change_migration():
    """Verify that the price change migration was successful"""
    print("🔍 Verifying price change migration...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check BTC price change data
        cursor.execute("SELECT COUNT(*) FROM live_data.btc_price_change")
        old_btc_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM live_data.price_change_btc")
        new_btc_count = cursor.fetchone()[0]
        
        # Check ETH price change data
        cursor.execute("SELECT COUNT(*) FROM live_data.eth_price_change")
        old_eth_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM live_data.price_change_eth")
        new_eth_count = cursor.fetchone()[0]
        
        print(f"📊 Price change migration verification:")
        print(f"   BTC: {old_btc_count} → {new_btc_count} records")
        print(f"   ETH: {old_eth_count} → {new_eth_count} records")
        
        if new_btc_count >= old_btc_count and new_eth_count >= old_eth_count:
            print("✅ Price change migration verification successful")
            return True
        else:
            print("❌ Price change migration verification failed")
            return False
            
    except Exception as e:
        print(f"❌ Error during price change verification: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def main():
    parser = argparse.ArgumentParser(description='Migrate price change tables to new naming convention')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--drop-old', action='store_true', help='Drop old tables after successful migration (DANGEROUS)')
    
    args = parser.parse_args()
    
    print("🚀 Starting price change table migration...")
    print(f"   Dry run: {args.dry_run}")
    print(f"   Drop old tables: {args.drop_old}")
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        verify_price_change_migration()
        return
    
    try:
        # Step 1: Create new tables
        create_new_price_change_tables()
        
        # Step 2: Migrate data
        migrate_btc_price_change_data()
        migrate_eth_price_change_data()
        
        # Step 3: Verify migration
        if verify_price_change_migration():
            print("🎉 Price change migration completed successfully!")
            
            if args.drop_old:
                print("⚠️ WARNING: Dropping old price change tables...")
                # Uncomment the following lines when ready to drop old tables
                # conn = get_postgres_connection()
                # cursor = conn.cursor()
                # cursor.execute("DROP TABLE IF EXISTS live_data.btc_price_change")
                # cursor.execute("DROP TABLE IF EXISTS live_data.eth_price_change")
                # conn.commit()
                # cursor.close()
                # conn.close()
                # print("✅ Old price change tables dropped")
            else:
                print("💡 Old price change tables preserved. Use --drop-old to remove them when ready.")
        else:
            print("❌ Price change migration verification failed. Please check the data manually.")
            
    except Exception as e:
        print(f"❌ Price change migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
