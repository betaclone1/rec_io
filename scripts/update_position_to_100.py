#!/usr/bin/env python3
"""
Update trades where position = 1 to position = 100
and adjust PnL accordingly (multiply by 100)
"""

import os
import sys
import psycopg2

# Database connection
conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST', 'localhost'),
    database=os.getenv('POSTGRES_DB', 'rec_io_db'),
    user=os.getenv('POSTGRES_USER', 'rec_io_user'),
    password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
)

try:
    cursor = conn.cursor()
    
    # First, check how many trades will be affected
    cursor.execute("""
        SELECT COUNT(*) as trades_to_update, 
               COUNT(CASE WHEN pnl IS NOT NULL THEN 1 END) as trades_with_pnl
        FROM users.trades_0001 
        WHERE position = 1
    """)
    result = cursor.fetchone()
    trades_to_update = result[0]
    trades_with_pnl = result[1]
    
    print(f"📊 Found {trades_to_update} trades with position = 1")
    print(f"📊 {trades_with_pnl} of these have PnL values to adjust")
    
    if trades_to_update == 0:
        print("✅ No trades to update")
        conn.close()
        sys.exit(0)
    
    # Proceed with update (user requested this change)
    print(f"\n🔄 Updating {trades_to_update} trades...")
    
    # Update position from 1 to 100 AND PnL in a single transaction
    # First, update PnL for trades that will be changed (multiply by 100)
    cursor.execute("""
        UPDATE users.trades_0001
        SET pnl = pnl * 100
        WHERE position = 1 AND pnl IS NOT NULL
    """)
    pnl_updates = cursor.rowcount
    print(f"✅ Updated {pnl_updates} trades: PnL multiplied by 100 (for trades with position = 1)")
    
    # Then update position from 1 to 100
    cursor.execute("""
        UPDATE users.trades_0001
        SET position = 100
        WHERE position = 1
    """)
    position_updates = cursor.rowcount
    print(f"✅ Updated {position_updates} trades: position 1 → 100")
    
    # Commit the changes
    conn.commit()
    print(f"\n✅ Successfully updated {position_updates} trades")
    
    # Show a sample of updated trades
    cursor.execute("""
        SELECT id, status, contract, strike, side, position, pnl, win_loss
        FROM users.trades_0001 
        WHERE position = 100
        ORDER BY id DESC
        LIMIT 10
    """)
    print("\n📋 Sample of updated trades:")
    print("-" * 100)
    for row in cursor.fetchall():
        print(f"ID: {row[0]}, Status: {row[1]}, Contract: {row[2]}, Strike: {row[3]}, Side: {row[4]}, Position: {row[5]}, PnL: {row[6]}, W/L: {row[7]}")
    
except Exception as e:
    conn.rollback()
    print(f"❌ Error updating trades: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    conn.close()

