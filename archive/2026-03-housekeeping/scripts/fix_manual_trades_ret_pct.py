#!/usr/bin/env python3
"""
Fix script to populate ret_pct column for manual trades that are missing it
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

def fix_manual_trades_ret_pct():
    """Fix ret_pct column for manual trades that are missing it"""
    
    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        print("🔍 Starting ret_pct fix for closed trades (manual and auto)...")
        print("📋 Formula: ret_pct = (pnl / (bankroll/100.0)) * 100")
        
        # Get count of closed trades that need ret_pct values (manual and auto)
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE status = 'closed' AND close_method IN ('manual', 'auto') AND ret_pct IS NULL 
            AND pnl IS NOT NULL AND bankroll IS NOT NULL
        """)
        total_trades = cursor.fetchone()[0]
        
        if total_trades == 0:
            print("✅ No closed trades found that need ret_pct values")
            return
        
        print(f"📊 Found {total_trades} closed trades that need ret_pct values")
        
        # Get all closed trades that need ret_pct values
        cursor.execute("""
            SELECT id, pnl, bankroll, ticker, close_method
            FROM users.trades_0001 
            WHERE status = 'closed' AND close_method IN ('manual', 'auto') AND ret_pct IS NULL 
            AND pnl IS NOT NULL AND bankroll IS NOT NULL
            ORDER BY created_at
        """)
        trades = cursor.fetchall()
        
        updated_count = 0
        skipped_count = 0
        
        for trade in trades:
            trade_id, pnl, bankroll, ticker, close_method = trade
            
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
            
            if updated_count % 10 == 0:
                print(f"✅ Updated {updated_count}/{total_trades} trades...")
            
            # Show first few updates for verification
            if updated_count <= 5:
                print(f"   Trade {trade_id} ({ticker}): PnL=${pnl}, Bankroll={bankroll} cents (${bankroll/100:.2f}) -> ret_pct={ret_pct:.5f}%")
        
        # Commit all changes
        conn.commit()
        
        print(f"\n🎉 Fix completed!")
        print(f"✅ Successfully updated: {updated_count} closed trades")
        print(f"⚠️  Skipped: {skipped_count} trades")
        print(f"📊 Total processed: {updated_count + skipped_count} trades")
        
        # Verify the results
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE status = 'closed' AND close_method IN ('manual', 'auto') AND ret_pct IS NOT NULL
        """)
        closed_trades_with_ret_pct = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE status = 'closed' AND close_method IN ('manual', 'auto') AND ret_pct IS NULL
        """)
        closed_trades_without_ret_pct = cursor.fetchone()[0]
        
        print(f"\n📈 Final status for closed trades:")
        print(f"   Closed trades with ret_pct: {closed_trades_with_ret_pct}")
        print(f"   Closed trades without ret_pct: {closed_trades_without_ret_pct}")
        
        # Show sample of updated trades
        cursor.execute("""
            SELECT id, ticker, pnl, bankroll, ret_pct, close_method, created_at
            FROM users.trades_0001 
            WHERE status = 'closed' AND close_method IN ('manual', 'auto') AND ret_pct IS NOT NULL
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        sample_trades = cursor.fetchall()
        
        print(f"\n📋 Sample of updated closed trades:")
        for trade in sample_trades:
            trade_id, ticker, pnl, bankroll, ret_pct, close_method, created_at = trade
            print(f"   Trade {trade_id} ({ticker}): PnL=${pnl}, Bankroll=${bankroll/100:.2f}, ret_pct={ret_pct:.5f}%, method={close_method}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    fix_manual_trades_ret_pct()
