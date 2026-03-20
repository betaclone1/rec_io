#!/usr/bin/env python3
"""
Migration script to rename strike table from old naming convention
to new naming convention: strike_table_<symbol>

This script:
1. Creates new table with the new naming convention
2. Migrates existing data from old table to new table
3. Verifies the migration was successful
4. Provides option to drop old table (commented out for safety)
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

def create_new_strike_table():
    """Create new strike table with the updated naming convention"""
    print("🔧 Creating new strike table with updated naming convention...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Create new strike table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS live_data.strike_table_btc (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT now(),
                symbol VARCHAR(10),
                current_price DECIMAL(10,2),
                ttc_seconds INTEGER,
                broker VARCHAR(20),
                event_ticker VARCHAR(50),
                market_title TEXT,
                strike_tier INTEGER,
                market_status VARCHAR(20),
                strike INTEGER,
                buffer DECIMAL(10,2),
                buffer_pct DECIMAL(5,2),
                probability DECIMAL(5,2),
                yes_ask DECIMAL(5,2),
                no_ask DECIMAL(5,2),
                yes_diff DECIMAL(5,2),
                no_diff DECIMAL(5,2),
                volume INTEGER,
                ticker VARCHAR(50),
                active_side VARCHAR(10),
                momentum_weighted_score DECIMAL(5,3),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
            );
        """)
        
        # Create index for new table
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_strike_table_btc_lookup ON live_data.strike_table_btc (timestamp, symbol, current_price);")
        
        conn.commit()
        print("✅ New strike table created successfully")
        
    except Exception as e:
        print(f"❌ Error creating new strike table: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def migrate_strike_table_data():
    """Migrate data from btc_strike_table to strike_table_btc"""
    print("🔄 Migrating strike table data...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check if old table exists and has data
        cursor.execute("SELECT COUNT(*) FROM live_data.btc_strike_table")
        old_count = cursor.fetchone()[0]
        print(f"📊 Found {old_count} records in old strike table")
        
        if old_count == 0:
            print("⚠️ No data to migrate for strike table")
            return
        
        # Migrate data
        cursor.execute("""
            INSERT INTO live_data.strike_table_btc 
            (timestamp, symbol, current_price, ttc_seconds, broker, event_ticker, market_title, 
             strike_tier, market_status, strike, buffer, buffer_pct, probability, yes_ask, 
             no_ask, yes_diff, no_diff, volume, ticker, active_side, momentum_weighted_score, created_at)
            SELECT timestamp, symbol, current_price, ttc_seconds, broker, event_ticker, market_title,
                   strike_tier, market_status, strike, buffer, buffer_pct, probability, yes_ask,
                   no_ask, yes_diff, no_diff, volume, ticker, active_side, momentum_weighted_score, created_at
            FROM live_data.btc_strike_table
            ON CONFLICT DO NOTHING
        """)
        
        # Verify migration
        cursor.execute("SELECT COUNT(*) FROM live_data.strike_table_btc")
        new_count = cursor.fetchone()[0]
        
        conn.commit()
        print(f"✅ Strike table data migration complete: {new_count} records migrated")
        
    except Exception as e:
        print(f"❌ Error migrating strike table data: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def verify_strike_table_migration():
    """Verify that the strike table migration was successful"""
    print("🔍 Verifying strike table migration...")
    
    conn = get_postgres_connection()
    cursor = conn.cursor()
    
    try:
        # Check old table data
        cursor.execute("SELECT COUNT(*) FROM live_data.btc_strike_table")
        old_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM live_data.strike_table_btc")
        new_count = cursor.fetchone()[0]
        
        print(f"📊 Strike table migration verification:")
        print(f"   Old table: {old_count} records")
        print(f"   New table: {new_count} records")
        
        if new_count >= old_count:
            print("✅ Strike table migration verification successful")
            return True
        else:
            print("❌ Strike table migration verification failed")
            return False
            
    except Exception as e:
        print(f"❌ Error during strike table verification: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def main():
    parser = argparse.ArgumentParser(description='Migrate strike table to new naming convention')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--drop-old', action='store_true', help='Drop old table after successful migration (DANGEROUS)')
    
    args = parser.parse_args()
    
    print("🚀 Starting strike table migration...")
    print(f"   Dry run: {args.dry_run}")
    print(f"   Drop old table: {args.drop_old}")
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        verify_strike_table_migration()
        return
    
    try:
        # Step 1: Create new table
        create_new_strike_table()
        
        # Step 2: Migrate data
        migrate_strike_table_data()
        
        # Step 3: Verify migration
        if verify_strike_table_migration():
            print("🎉 Strike table migration completed successfully!")
            
            if args.drop_old:
                print("⚠️ WARNING: Dropping old strike table...")
                # Uncomment the following lines when ready to drop old table
                # conn = get_postgres_connection()
                # cursor = conn.cursor()
                # cursor.execute("DROP TABLE IF EXISTS live_data.btc_strike_table")
                # conn.commit()
                # cursor.close()
                # conn.close()
                # print("✅ Old strike table dropped")
            else:
                print("💡 Old strike table preserved. Use --drop-old to remove it when ready.")
        else:
            print("❌ Strike table migration verification failed. Please check the data manually.")
            
    except Exception as e:
        print(f"❌ Strike table migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
