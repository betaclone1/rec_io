#!/usr/bin/env python3
"""
Migration script to rename live price log tables from old naming convention
to new naming convention: live_price_log_1s_<symbol>

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

# Add backend to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

def get_postgres_connection():
    """Get a PostgreSQL connection"""
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=int(os.getenv('POSTGRES_PORT', '5432')),
        database=os.getenv('POSTGRES_DB', 'rec_io_db'),
        user=os.getenv('POSTGRES_USER', 'rec_io_user'),
        password=os.getenv('POSTGRES_PASSWORD', '')
    )

def create_new_tables():
    """Create new tables with the new naming convention"""
    print("🔧 Creating new tables with updated naming convention...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Create new BTC table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_btc (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4)
            );
        """)
        
        # Create new ETH table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.live_price_log_1s_eth (
                timestamp TEXT PRIMARY KEY,
                price DECIMAL(10,2),
                one_minute_avg DECIMAL(10,2),
                momentum DECIMAL(10,4),
                delta_1m DECIMAL(10,4),
                delta_2m DECIMAL(10,4),
                delta_3m DECIMAL(10,4),
                delta_4m DECIMAL(10,4),
                delta_15m DECIMAL(10,4),
                delta_30m DECIMAL(10,4)
            );
        """)
        
        # Create indexes for new tables
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_price_log_1s_btc_timestamp ON live_data.live_price_log_1s_btc(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_live_price_log_1s_eth_timestamp ON live_data.live_price_log_1s_eth(timestamp);")
        
        conn.commit()
        print("✅ New tables created successfully")
        
    except Exception as e:
        print(f"❌ Error creating new tables: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def migrate_btc_data():
    """Migrate data from btc_price_log to live_price_log_1s_btc"""
    print("🔄 Migrating BTC price data...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check if old table exists and has data
        cursor.execute("SELECT COUNT(*) FROM live_data.btc_price_log")
        old_count = cursor.fetchone()[0]
        print(f"📊 Found {old_count} records in old BTC table")
        
        if old_count == 0:
            print("⚠️ No data to migrate for BTC")
            return
        
        # Migrate data with proper column mapping
        cursor.execute("""
            INSERT INTO live_data.live_price_log_1s_btc 
            (timestamp, price, one_minute_avg, momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m)
            SELECT 
                timestamp,
                price,
                one_minute_avg,
                momentum,
                delta_1m,
                delta_2m,
                delta_3m,
                delta_4m,
                delta_15m,
                delta_30m
            FROM live_data.btc_price_log
            ON CONFLICT (timestamp) DO UPDATE SET
                price = EXCLUDED.price,
                one_minute_avg = EXCLUDED.one_minute_avg,
                momentum = EXCLUDED.momentum,
                delta_1m = EXCLUDED.delta_1m,
                delta_2m = EXCLUDED.delta_2m,
                delta_3m = EXCLUDED.delta_3m,
                delta_4m = EXCLUDED.delta_4m,
                delta_15m = EXCLUDED.delta_15m,
                delta_30m = EXCLUDED.delta_30m
        """)
        
        # Verify migration
        cursor.execute("SELECT COUNT(*) FROM live_data.live_price_log_1s_btc")
        new_count = cursor.fetchone()[0]
        
        conn.commit()
        print(f"✅ BTC data migration complete: {new_count} records migrated")
        
    except Exception as e:
        print(f"❌ Error migrating BTC data: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def migrate_eth_data():
    """Migrate data from eth_price_log to live_price_log_1s_eth"""
    print("🔄 Migrating ETH price data...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check if old table exists and has data
        cursor.execute("SELECT COUNT(*) FROM live_data.eth_price_log")
        old_count = cursor.fetchone()[0]
        print(f"📊 Found {old_count} records in old ETH table")
        
        if old_count == 0:
            print("⚠️ No data to migrate for ETH")
            return
        
        # Migrate data - ETH table has simpler schema
        cursor.execute("""
            INSERT INTO live_data.live_price_log_1s_eth 
            (timestamp, price, one_minute_avg, momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m)
            SELECT 
                timestamp::text,
                price,
                price as one_minute_avg,  -- Use price as fallback
                NULL as momentum,
                NULL as delta_1m,
                NULL as delta_2m,
                NULL as delta_3m,
                NULL as delta_4m,
                NULL as delta_15m,
                NULL as delta_30m
            FROM live_data.eth_price_log
            ON CONFLICT (timestamp) DO UPDATE SET
                price = EXCLUDED.price,
                one_minute_avg = EXCLUDED.one_minute_avg
        """)
        
        # Verify migration
        cursor.execute("SELECT COUNT(*) FROM live_data.live_price_log_1s_eth")
        new_count = cursor.fetchone()[0]
        
        conn.commit()
        print(f"✅ ETH data migration complete: {new_count} records migrated")
        
    except Exception as e:
        print(f"❌ Error migrating ETH data: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def verify_migration():
    """Verify that the migration was successful"""
    print("🔍 Verifying migration...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check BTC data
        cursor.execute("SELECT COUNT(*) FROM live_data.btc_price_log")
        old_btc_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM live_data.live_price_log_1s_btc")
        new_btc_count = cursor.fetchone()[0]
        
        # Check ETH data
        cursor.execute("SELECT COUNT(*) FROM live_data.eth_price_log")
        old_eth_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM live_data.live_price_log_1s_eth")
        new_eth_count = cursor.fetchone()[0]
        
        print(f"📊 Migration verification:")
        print(f"   BTC: {old_btc_count} → {new_btc_count} records")
        print(f"   ETH: {old_eth_count} → {new_eth_count} records")
        
        if new_btc_count >= old_btc_count and new_eth_count >= old_eth_count:
            print("✅ Migration verification successful")
            return True
        else:
            print("❌ Migration verification failed")
            return False
            
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def main():
    parser = argparse.ArgumentParser(description='Migrate live price log tables to new naming convention')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--drop-old', action='store_true', help='Drop old tables after successful migration (DANGEROUS)')
    
    args = parser.parse_args()
    
    print("🚀 Starting live price table migration...")
    print(f"   Dry run: {args.dry_run}")
    print(f"   Drop old tables: {args.drop_old}")
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        verify_migration()
        return
    
    try:
        # Step 1: Create new tables
        create_new_tables()
        
        # Step 2: Migrate data
        migrate_btc_data()
        migrate_eth_data()
        
        # Step 3: Verify migration
        if verify_migration():
            print("🎉 Migration completed successfully!")
            
            if args.drop_old:
                print("⚠️ WARNING: Dropping old tables...")
                # Uncomment the following lines when ready to drop old tables
                # conn = get_postgres_connection()
                # cursor = conn.cursor()
                # cursor.execute("DROP TABLE IF EXISTS live_data.btc_price_log")
                # cursor.execute("DROP TABLE IF EXISTS live_data.eth_price_log")
                # conn.commit()
                # cursor.close()
                # conn.close()
                # print("✅ Old tables dropped")
            else:
                print("💡 Old tables preserved. Use --drop-old to remove them when ready.")
        else:
            print("❌ Migration verification failed. Please check the data manually.")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
