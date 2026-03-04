#!/usr/bin/env python3
"""
URGENT: Rollback the position update that was incorrectly applied to all trades
"""

import os
import sys
import psycopg2

conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST', 'localhost'),
    database=os.getenv('POSTGRES_DB', 'rec_io_db'),
    user=os.getenv('POSTGRES_USER', 'rec_io_user'),
    password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
)

try:
    cursor = conn.cursor()
    
    print("🔄 ROLLING BACK ALL CHANGES...")
    
    # First, divide PnL by 100 for all trades with position = 100 that have PnL
    # This reverses the PnL multiplication
    cursor.execute("""
        UPDATE users.trades_0001
        SET pnl = pnl / 100
        WHERE position = 100 AND pnl IS NOT NULL
    """)
    pnl_rollback = cursor.rowcount
    print(f"✅ Rolled back PnL for {pnl_rollback} trades (divided by 100)")
    
    # Now change position back from 100 to 1 for all trades
    cursor.execute("""
        UPDATE users.trades_0001
        SET position = 1
        WHERE position = 100
    """)
    position_rollback = cursor.rowcount
    print(f"✅ Rolled back position for {position_rollback} trades (100 → 1)")
    
    conn.commit()
    print(f"\n✅ ROLLBACK COMPLETE: Reversed changes to {position_rollback} trades")
    
except Exception as e:
    conn.rollback()
    print(f"❌ Error during rollback: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    conn.close()





