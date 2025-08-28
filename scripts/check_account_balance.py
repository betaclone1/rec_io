#!/usr/bin/env python3
"""
Script to check latest entries in account_balance table
"""

import psycopg2
from psycopg2.extras import RealDictCursor

def get_remote_connection():
    """Connect to the remote PostgreSQL database"""
    try:
        conn = psycopg2.connect(
            host="137.184.224.94",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password",
            port=5432
        )
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to remote database: {e}")
        return None

def check_latest_entries(conn):
    """Check the latest 10 entries in account_balance table"""
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT id, balance, exposure, positions, portfolio, bankroll_current, bankroll_prev, timestamp
                FROM users.account_balance_0001 
                ORDER BY id DESC 
                LIMIT 10
            """)
            entries = cursor.fetchall()
            
            print("📊 Latest 10 entries in account_balance_0001 table:")
            print("-" * 80)
            for entry in entries:
                print(f"ID: {entry['id']}")
                print(f"  Balance: {entry['balance']}")
                print(f"  Exposure: {entry['exposure']}")
                print(f"  Positions: {entry['positions']}")
                print(f"  Portfolio: {entry['portfolio']}")
                print(f"  Bankroll Current: {entry['bankroll_current']}")
                print(f"  Bankroll Prev: {entry['bankroll_prev']}")
                print(f"  Timestamp: {entry['timestamp']}")
                print("-" * 40)
            
            return entries
    except Exception as e:
        print(f"❌ Error checking entries: {e}")
        return None

def main():
    """Main function"""
    print("🔍 Checking latest account balance entries...")
    
    conn = get_remote_connection()
    if not conn:
        return
    
    try:
        entries = check_latest_entries(conn)
        if entries:
            print(f"✅ Found {len(entries)} entries")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
