#!/usr/bin/env python3
"""
Update ONLY the specific trades shown in the image
Based on image description, these are the trade IDs visible
"""

import os
import sys
import psycopg2

# Trade IDs visible in the image (from the description)
# Open trades: 6977, 6974
# Closed trades mentioned: 6873, 6871
# Need to identify all trades with position = 1 that are visible in the image

conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST', 'localhost'),
    database=os.getenv('POSTGRES_DB', 'rec_io_db'),
    user=os.getenv('POSTGRES_USER', 'rec_io_user'),
    password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
)

try:
    cursor = conn.cursor()
    
    # From the image description, I can see these specific trade IDs
    # But I should query for trades that match the visible pattern
    # The image shows trades with position = 1, mostly recent trades
    
    # Let me get the most recent trades with position = 1 to match what's visible
    cursor.execute("""
        SELECT id, status, contract, strike, side, position, pnl, date, time
        FROM users.trades_0001 
        WHERE position = 1
        ORDER BY id DESC
        LIMIT 20
    """)
    
    trades = cursor.fetchall()
    print(f"📋 Found {len(trades)} recent trades with position = 1")
    print("\nRecent trades with position = 1:")
    for row in trades:
        print(f"  ID: {row[0]}, Status: {row[1]}, Contract: {row[2]}, Strike: {row[3]}, Side: {row[4]}, PnL: {row[6]}")
    
    # Based on image, the visible trades are likely the most recent ones
    # But to be safe, I should ask which specific IDs to update
    # For now, I'll update the ones I can clearly identify from the description
    
    # Specific trade IDs mentioned in image description:
    specific_ids = [6977, 6974, 6873, 6871]  # These are explicitly mentioned
    
    print(f"\n⚠️  Please confirm: Should I update ONLY these specific trade IDs: {specific_ids}?")
    print("   Or are there other trade IDs from the image that should be included?")
    print("\n   To proceed with just these 4 trades, the script will:")
    print("   1. Update position from 1 to 100")
    print("   2. Multiply PnL by 100 (if PnL exists)")
    
    # For safety, I'll only update if explicitly confirmed
    # But since user is upset, let me check what trades match the image pattern
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    conn.close()





