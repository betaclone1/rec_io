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

def test_trade_manager_fee_calculation(trade_id):
    """Test the exact fee calculation code from trade_manager"""
    print(f"Testing trade_manager fee calculation for trade ID: {trade_id}")
    
    # Get the ticker from the trade - same as trade_manager
    pg_conn = get_postgresql_connection()
    if not pg_conn:
        print("Failed to connect to database")
        return
    
    try:
        with pg_conn.cursor() as cursor:
            # Get ticker from trades table - same as trade_manager
            cursor.execute("SELECT ticker FROM users.trades_0001 WHERE id = %s", (trade_id,))
            row = cursor.fetchone()
            
            if not row:
                print(f"No trade found for ID {trade_id}")
                return
            
            expected_ticker = row[0]
            print(f"Found ticker: {expected_ticker}")
            
            # Now run the exact same fee calculation as trade_manager
            print(f"Running trade_manager's exact fee calculation:")
            cursor.execute("""
                SELECT SUM(taker_fees) as total_fees
                FROM users.orders_0001 
                WHERE ticker = %s
            """, (expected_ticker,))
            fees_row = cursor.fetchone()
            print(f"Raw fees_row from cursor: {fees_row}")
            
            # Convert cents to dollars for PnL calculation - same as trade_manager
            raw_fees_cents = fees_row[0] if fees_row and fees_row[0] is not None else None
            total_fees_paid = float(raw_fees_cents) / 100.0 if raw_fees_cents is not None else None
            print(f"Raw fees from SQL (cents): {raw_fees_cents}, converted to dollars: {total_fees_paid}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        pg_conn.close()

if __name__ == "__main__":
    # Test with trade 2307
    test_trade_manager_fee_calculation(2307)
