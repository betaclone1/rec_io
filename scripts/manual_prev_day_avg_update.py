#!/usr/bin/env python3
"""
Manual script to run the daily prev_day_avg update for all symbols.
This replicates what the daily thread does at 00:05 EST.
"""

import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.symbol_price_watchdog import (
    SYMBOL_CONFIG,
    get_postgres_connection,
    update_prev_day_avg_for_symbol
)

def main():
    """Run prev_day_avg update for all symbols."""
    # Calculate yesterday's date range in EST
    now = datetime.now(ZoneInfo("America/New_York"))
    today_str = now.strftime("%Y-%m-%d")
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    yesterday_dt = today_dt - timedelta(days=1)
    yesterday_start = yesterday_dt.strftime("%Y-%m-%d") + "T00:00:00"
    yesterday_end = today_str + "T00:00:00"
    
    print(f"🕐 Running manual prev_day_avg update for yesterday: {yesterday_start} to {yesterday_end}")
    
    # Get DB connection
    conn = get_postgres_connection()
    if not conn:
        print("❌ Failed to get DB connection")
        return
    
    cursor = conn.cursor()
    
    # Update each symbol
    for symbol in SYMBOL_CONFIG.keys():
        print(f"\n📊 Processing {symbol}...")
        table_name = SYMBOL_CONFIG[symbol]["table_name"]
        try:
            update_prev_day_avg_for_symbol(symbol, cursor, table_name, yesterday_start, yesterday_end)
            print(f"✅ {symbol} update completed")
        except Exception as e:
            print(f"⚠️ {symbol} update failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Commit all updates
    conn.commit()
    cursor.close()
    conn.close()
    
    print("\n✅ Manual prev_day_avg update completed for all symbols")

if __name__ == "__main__":
    main()
