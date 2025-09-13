#!/usr/bin/env python3
"""
Corrected one-time backfill script to populate bankroll column in trades table
Uses bankroll_current and portfolio columns from account_balance table
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

def backfill_trades_bankroll_corrected():
    """Backfill bankroll column in trades table using correct columns"""
    
    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("🔍 Starting corrected bankroll backfill for trades table...")
        print("📋 Using: bankroll_current (preferred) → portfolio (fallback)")
        
        # First, let's reset all bankroll values to NULL so we can do a clean backfill
        cursor.execute("""
            UPDATE users.trades_0001 
            SET bankroll = NULL 
            WHERE created_at IS NOT NULL
        """)
        reset_count = cursor.fetchone()[0] if cursor.rowcount else 0
        print(f"🔄 Reset {cursor.rowcount} trades to NULL bankroll values")
        
        # Get count of trades that need bankroll values
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE bankroll IS NULL AND created_at IS NOT NULL
        """)
        total_trades = cursor.fetchone()[0]
        
        print(f"📊 Found {total_trades} trades that need bankroll values")
        
        # Get the earliest available portfolio record as fallback
        cursor.execute("""
            SELECT portfolio, created_at FROM users.account_balance_0001 
            WHERE portfolio IS NOT NULL 
            ORDER BY created_at ASC 
            LIMIT 1
        """)
        earliest_portfolio = cursor.fetchone()
        
        if earliest_portfolio:
            fallback_portfolio = earliest_portfolio[0]
            fallback_time = earliest_portfolio[1]
            print(f"🔄 Using fallback portfolio: {fallback_portfolio} (from {fallback_time})")
        else:
            print("❌ No fallback portfolio available")
            return
        
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
            
            # First try to find bankroll_current (preferred)
            cursor.execute("""
                SELECT bankroll_current 
                FROM users.account_balance_0001 
                WHERE created_at <= %s AND bankroll_current IS NOT NULL
                ORDER BY created_at DESC 
                LIMIT 1
            """, (trade_created_at,))
            
            result = cursor.fetchone()
            
            if result and result[0] is not None:
                # Use bankroll_current if available
                bankroll_value = result[0]
                source = "bankroll_current"
            else:
                # Try to find portfolio column
                cursor.execute("""
                    SELECT portfolio 
                    FROM users.account_balance_0001 
                    WHERE created_at <= %s AND portfolio IS NOT NULL
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, (trade_created_at,))
                
                result = cursor.fetchone()
                
                if result and result[0] is not None:
                    bankroll_value = result[0]
                    source = "portfolio"
                else:
                    # Use fallback portfolio for trades before any account balance records
                    bankroll_value = fallback_portfolio
                    source = f"fallback_portfolio (earliest: {fallback_time})"
            
            # Update the trade with the bankroll value
            cursor.execute("""
                UPDATE users.trades_0001 
                SET bankroll = %s 
                WHERE id = %s
            """, (bankroll_value, trade_id))
            
            updated_count += 1
            
            if updated_count % 100 == 0:
                print(f"✅ Updated {updated_count}/{total_trades} trades...")
            
            # Show first few updates for verification
            if updated_count <= 5:
                print(f"   Trade {trade_id}: {bankroll_value} (from {source})")
        
        # Commit all changes
        conn.commit()
        
        print(f"\n🎉 Backfill completed!")
        print(f"✅ Successfully updated: {updated_count} trades")
        print(f"⚠️  Skipped: {skipped_count} trades")
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
        
        # Show sample of updated trades
        cursor.execute("""
            SELECT id, created_at, symbol, bankroll 
            FROM users.trades_0001 
            WHERE bankroll IS NOT NULL 
            ORDER BY created_at 
            LIMIT 10
        """)
        sample_trades = cursor.fetchall()
        
        print(f"\n📋 Sample of updated trades:")
        for trade in sample_trades:
            trade_id, created_at, symbol, bankroll = trade
            print(f"   Trade {trade_id}: {symbol} at {created_at} -> Bankroll: {bankroll}")
        
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
    backfill_trades_bankroll_corrected()
