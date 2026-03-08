#!/usr/bin/env python3
"""
One-time backfill script to populate bankroll column in trades table
Matches trades with account balance records based on created_at timestamps
"""

import psycopg2
import psycopg2.extras
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Database connection parameters for remote database
DB_CONFIG = {
    'host': '137.184.224.94',
    'port': 5432,
    'database': 'rec_io_db',
    'user': 'rec_io_user',
    'password': 'rec_io_password'
}

def backfill_trades_bankroll():
    """Backfill bankroll column in trades table using account balance records"""
    
    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("🔍 Starting bankroll backfill for trades table...")
        
        # Get count of trades that need bankroll values
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE bankroll IS NULL AND created_at IS NOT NULL
        """)
        total_trades = cursor.fetchone()[0]
        
        if total_trades == 0:
            print("✅ No trades found that need bankroll values")
            return
        
        print(f"📊 Found {total_trades} trades that need bankroll values")
        
        # Get all trades that need bankroll values
        cursor.execute("""
            SELECT id, created_at, symbol, side, contract 
            FROM users.trades_0001 
            WHERE bankroll IS NULL AND created_at IS NOT NULL
            ORDER BY created_at
        """)
        trades = cursor.fetchall()
        
        updated_count = 0
        skipped_count = 0
        
        for trade in trades:
            trade_id, trade_created_at, symbol, side, contract = trade
            
            # Find the closest account balance record (before or at trade time)
            cursor.execute("""
                SELECT bankroll_current 
                FROM users.account_balance_0001 
                WHERE created_at <= %s 
                ORDER BY created_at DESC 
                LIMIT 1
            """, (trade_created_at,))
            
            result = cursor.fetchone()
            
            if result and result[0] is not None:
                bankroll_value = result[0]
                
                # Update the trade with the bankroll value
                cursor.execute("""
                    UPDATE users.trades_0001 
                    SET bankroll = %s 
                    WHERE id = %s
                """, (bankroll_value, trade_id))
                
                updated_count += 1
                
                if updated_count % 100 == 0:
                    print(f"✅ Updated {updated_count}/{total_trades} trades...")
                    
            else:
                skipped_count += 1
                print(f"⚠️  No bankroll data found for trade {trade_id} at {trade_created_at}")
        
        # Commit all changes
        conn.commit()
        
        print(f"\n🎉 Backfill completed!")
        print(f"✅ Successfully updated: {updated_count} trades")
        print(f"⚠️  Skipped (no bankroll data): {skipped_count} trades")
        print(f"📊 Total processed: {updated_count + skipped_count} trades")
        
        # Verify the results
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 WHERE bankroll IS NOT NULL
        """)
        trades_with_bankroll = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 WHERE bankroll IS NULL
        """)
        trades_without_bankroll = cursor.fetchone()[0]
        
        print(f"\n📈 Final status:")
        print(f"   Trades with bankroll: {trades_with_bankroll}")
        print(f"   Trades without bankroll: {trades_without_bankroll}")
        
    except Exception as e:
        print(f"❌ Error during backfill: {e}")
        if 'conn' in locals():
            conn.rollback()
        raise
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    backfill_trades_bankroll()
