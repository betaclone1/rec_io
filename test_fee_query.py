#!/usr/bin/env python3

import psycopg2
from psycopg2.extras import RealDictCursor

def get_postgresql_connection():
    """Get a connection to the PostgreSQL database - same as trade_manager"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return None

def test_fee_query(ticker):
    """Test the exact same fee query code from trade_manager"""
    print(f"Testing fee query for ticker: {ticker}")
    
    # First, let's see what orders exist for this ticker
    pg_conn = get_postgresql_connection()
    if not pg_conn:
        print("Failed to connect to database")
        return
    
    try:
        with pg_conn.cursor() as cursor:
            # Check what orders exist
            cursor.execute("SELECT id, action, side, taker_fees, created_time FROM users.orders_0001 WHERE ticker = %s ORDER BY created_time", (ticker,))
            orders = cursor.fetchall()
            print(f"Found {len(orders)} orders for ticker {ticker}:")
            for order in orders:
                print(f"  Order {order[0]}: {order[1]} {order[2]}, fees: {order[3]} cents, time: {order[4]}")
            
            # Now run the exact same query as trade_manager
            print(f"\nRunning trade_manager's exact query:")
            cursor.execute("""
                SELECT SUM(taker_fees) as total_fees
                FROM users.orders_0001 
                WHERE ticker = %s
            """, (ticker,))
            fees_row = cursor.fetchone()
            print(f"Raw fees_row from cursor: {fees_row}")
            
            # Convert cents to dollars for PnL calculation - same as trade_manager
            raw_fees_cents = fees_row[0] if fees_row and fees_row[0] is not None else None
            total_fees_paid = float(raw_fees_cents) / 100.0 if raw_fees_cents is not None else None
            print(f"Raw fees from SQL (cents): {raw_fees_cents}, converted to dollars: {total_fees_paid}")
            
            # Also test the direct SQL query
            print(f"\nDirect SQL query result:")
            cursor.execute("SELECT SUM(taker_fees) as total_fees FROM users.orders_0001 WHERE ticker = %s", (ticker,))
            direct_result = cursor.fetchone()
            print(f"Direct query result: {direct_result}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        pg_conn.close()

if __name__ == "__main__":
    # Test with the ticker from trade 2307
    test_fee_query("KXBTCD-25AUG2517-T110749.99")
    
    # Also test with trade 2306 (correct ticker)
    print("\n" + "="*50)
    test_fee_query("KXBTCD-25AUG2516-T111249.99")
