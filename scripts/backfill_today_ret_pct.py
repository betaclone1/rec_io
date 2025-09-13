#!/usr/bin/env python3
"""
Backfill script to populate ret_pct column for trades from today
Formula: ret_pct = (pnl / (bankroll/100.0)) * 100
Targets: Remote database at 137.184.224.94
"""

import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
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

def backfill_today_ret_pct():
    """Backfill ret_pct column for trades from today"""
    
    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Get today's date in EST (assuming trades are stored in EST)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        print(f"🔍 Starting ret_pct backfill for trades from today: {today}")
        print(f"📋 Formula: ret_pct = (pnl / (bankroll/100.0)) * 100")
        
        # Get count of trades from today that need ret_pct values
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE DATE(date) = %s 
            AND ret_pct IS NULL 
            AND pnl IS NOT NULL 
            AND bankroll IS NOT NULL
        """, (today,))
        total_trades = cursor.fetchone()[0]
        
        if total_trades == 0:
            print("✅ No trades from today found that need ret_pct values")
            
            # Check if there are any trades from today at all
            cursor.execute("""
                SELECT COUNT(*) FROM users.trades_0001 
                WHERE DATE(date) = %s
            """, (today,))
            today_total = cursor.fetchone()[0]
            print(f"📊 Total trades from today: {today_total}")
            
            # Check breakdown of today's trades
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN ret_pct IS NOT NULL THEN 1 END) as with_ret_pct,
                    COUNT(CASE WHEN ret_pct IS NULL THEN 1 END) as without_ret_pct,
                    COUNT(CASE WHEN pnl IS NOT NULL THEN 1 END) as with_pnl,
                    COUNT(CASE WHEN bankroll IS NOT NULL THEN 1 END) as with_bankroll
                FROM users.trades_0001 
                WHERE DATE(date) = %s
            """, (today,))
            breakdown = cursor.fetchone()
            print(f"📊 Breakdown of today's trades:")
            print(f"   Total: {breakdown[0]}")
            print(f"   With ret_pct: {breakdown[1]}")
            print(f"   Without ret_pct: {breakdown[2]}")
            print(f"   With PnL: {breakdown[3]}")
            print(f"   With bankroll: {breakdown[4]}")
            return
        
        print(f"📊 Found {total_trades} trades from today that need ret_pct values")
        
        # Get all trades from today that need ret_pct values
        cursor.execute("""
            SELECT id, pnl, bankroll, symbol, side, ticker, status, date, time
            FROM users.trades_0001 
            WHERE DATE(date) = %s 
            AND ret_pct IS NULL 
            AND pnl IS NOT NULL 
            AND bankroll IS NOT NULL
            ORDER BY id
        """, (today,))
        trades = cursor.fetchall()
        
        updated_count = 0
        skipped_count = 0
        
        for trade in trades:
            trade_id, pnl, bankroll, symbol, side, ticker, status, date, time = trade
            
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
        
        print(f"\n🎉 Backfill completed!")
        print(f"✅ Successfully updated: {updated_count} trades")
        print(f"⚠️  Skipped: {skipped_count} trades")
        print(f"📊 Total processed: {updated_count + skipped_count} trades")
        
        # Verify the results for today
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE DATE(date) = %s AND ret_pct IS NOT NULL
        """, (today,))
        trades_with_ret_pct = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM users.trades_0001 
            WHERE DATE(date) = %s AND ret_pct IS NULL
        """, (today,))
        trades_without_ret_pct = cursor.fetchone()[0]
        
        print(f"\n📊 Final status for today's trades:")
        print(f"   Trades with ret_pct: {trades_with_ret_pct}")
        print(f"   Trades without ret_pct: {trades_without_ret_pct}")
        
        # Show sample of updated trades for verification
        cursor.execute("""
            SELECT id, pnl, bankroll, ret_pct, (pnl / (bankroll/100.0)) * 100 as verification
            FROM users.trades_0001 
            WHERE DATE(date) = %s AND ret_pct IS NOT NULL
            ORDER BY id DESC
            LIMIT 5
        """, (today,))
        
        print(f"\n🔍 Sample verification of updated trades:")
        for trade in cursor.fetchall():
            trade_id, pnl, bankroll, ret_pct, verification = trade
            print(f"   Trade {trade_id}: PnL=${pnl}, Bankroll={bankroll} cents (${bankroll/100:.2f}) -> ret_pct={ret_pct:.5f}% (verification: {verification:.5f}%)")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error during backfill: {e}")
        try:
            conn.close()
        except:
            pass

if __name__ == "__main__":
    backfill_today_ret_pct()
