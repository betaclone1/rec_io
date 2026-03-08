#!/usr/bin/env python3
"""
Fix PnL calculation: PnL should be (sell_price - buy_price) * position
Not the old PnL multiplied by 100
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
    
    # Recalculate PnL correctly: (sell_price - buy_price) * position
    # Only for closed trades where we have both buy_price and sell_price
    cursor.execute("""
        UPDATE users.trades_0001
        SET pnl = (sell_price - buy_price) * position
        WHERE status = 'closed' 
        AND buy_price IS NOT NULL 
        AND sell_price IS NOT NULL
        AND position IS NOT NULL
    """)
    closed_updates = cursor.rowcount
    print(f"Recalculated PnL for {closed_updates} closed trades")
    
    # For open trades, PnL should be NULL or calculated differently
    # But if there's a current market value, we'd need that
    # For now, just set open trade PnL to NULL if it exists
    cursor.execute("""
        UPDATE users.trades_0001
        SET pnl = NULL
        WHERE status = 'open' 
        AND pnl IS NOT NULL
    """)
    open_updates = cursor.rowcount
    print(f"Cleared PnL for {open_updates} open trades (should be NULL until closed)")
    
    conn.commit()
    print(f"Complete: Fixed PnL calculations")
    
except Exception as e:
    conn.rollback()
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    conn.close()





