#!/usr/bin/env python3
"""
Backfill script to populate ret_pct column with calculated return percentages
Formula: ret_pct = (pnl / (bankroll/100.0)) * 100
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

def backfill_trades_ret_pct():
    """Backfill ret_pct column with calculated return percentages"""
    
    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("🔍 Starting ret_pct backfill for trades table...")
        print("📋 Formula: ret_pct = (pnl / (bankroll/100.0)) * 100")
        
        # Get count of trades that need ret_pct values
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE ret_pct IS NULL AND pnl IS NOT NULL AND bankroll IS NOT NULL
        """)
        total_trades = cursor.fetchone()[0]
        
        if total_trades == 0:
            print("✅ No trades found that need ret_pct values")
            return
        
        print(f"📊 Found {total_trades} trades that need ret_pct values")
        
        # Get all trades that need ret_pct values
        cursor.execute("""
            SELECT id, pnl, bankroll, symbol, side
            FROM users.trades_0001 
            WHERE ret_pct IS NULL AND pnl IS NOT NULL AND bankroll IS NOT NULL
            ORDER BY created_at
        """)
        trades = cursor.fetchall()
        
        updated_count = 0
        skipped_count = 0
        
        for trade in trades:
            trade_id, pnl, bankroll, symbol, side = trade
            
            if bankroll == 0:
                skipped_count += 1
                print(f"⚠️  Skipping trade {trade_id}: bankroll is 0")
                continue
            
            # Calculate ret_pct: (pnl / (bankroll/100.0)) * 100
            ret_pct = (pnl / (bankroll / 100.0)) * 100
            
            # Update the trade with the calculated ret_pct value
            cursor.execute("""
                UPDATE users.trades_0001 
                SET ret_pct = %s 
                WHERE id = %s
            """, (ret_pct, trade_id))
            
            updated_count += 1
            
            if updated_count % 100 == 0:
                print(f"✅ Updated {updated_count}/{total_trades} trades...")
            
            # Show first few updates for verification
            if updated_count <= 5:
                print(f"   Trade {trade_id}: PnL={pnl}, Bankroll={bankroll} cents (${bankroll/100:.2f}) -> ret_pct={ret_pct:.5f}")
        
        # Commit all changes
        conn.commit()
        
        print(f"\n🎉 Backfill completed!")
        print(f"✅ Successfully updated: {updated_count} trades")
        print(f"⚠️  Skipped: {skipped_count} trades")
        print(f"📊 Total processed: {updated_count + skipped_count} trades")
        
        # Verify the results
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 WHERE ret_pct IS NOT NULL
        """)
        trades_with_ret_pct = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 WHERE ret_pct IS NULL
        """)
        trades_without_ret_pct = cursor.fetchone()[0]
        
        print(f"\n📈 Final status:")
        print(f"   Trades with ret_pct: {trades_with_ret_pct}")
        print(f"   Trades without ret_pct: {trades_without_ret_pct}")
        
        # Show sample of updated trades
        cursor.execute("""
            SELECT id, pnl, bankroll, ret_pct, (pnl / (bankroll/100.0)) * 100 as verification
            FROM users.trades_0001 
            WHERE ret_pct IS NOT NULL 
            ORDER BY created_at DESC 
            LIMIT 10
        """)
        sample_trades = cursor.fetchall()
        
        print(f"\n📋 Sample of updated trades:")
        for trade in sample_trades:
            trade_id, pnl, bankroll, ret_pct, verification = trade
            print(f"   Trade {trade_id}: PnL=${pnl}, Bankroll={bankroll} cents (${bankroll/100:.2f}) -> ret_pct={ret_pct:.5f}")
        
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
    backfill_trades_ret_pct()
