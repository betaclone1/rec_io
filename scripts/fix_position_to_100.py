#!/usr/bin/env python3
"""
Change all trades with position = 1 to position = 100
and adjust PnL accordingly (multiply by 100)
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
    
    # Count trades to update
    cursor.execute("SELECT COUNT(*) FROM users.trades_0001 WHERE position = 1")
    count = cursor.fetchone()[0]
    print(f"Updating {count} trades: position 1 → 100")
    
    # First, multiply PnL by 100 for trades with position = 1
    cursor.execute("""
        UPDATE users.trades_0001
        SET pnl = pnl * 100
        WHERE position = 1 AND pnl IS NOT NULL
    """)
    pnl_updates = cursor.rowcount
    print(f"Updated PnL for {pnl_updates} trades (multiplied by 100)")
    
    # Then change position from 1 to 100
    cursor.execute("""
        UPDATE users.trades_0001
        SET position = 100
        WHERE position = 1
    """)
    position_updates = cursor.rowcount
    print(f"Updated position for {position_updates} trades (1 → 100)")
    
    conn.commit()
    print(f"Complete: Updated {position_updates} trades")
    
except Exception as e:
    conn.rollback()
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    conn.close()





