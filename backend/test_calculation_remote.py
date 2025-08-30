#!/usr/bin/env python3
"""
Simple test script to run on remote server
"""

import psycopg2
from psycopg2.extras import RealDictCursor

def test_calculation():
    try:
        # Connect to local database (same server)
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        # Get current preferences
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT position_size, multiplier, position_type, total_position 
                FROM users.trade_preferences_0001 WHERE id = 1
            """)
            prefs = cursor.fetchone()
            
            print(f"Current preferences:")
            print(f"  Position Size: {prefs['position_size']}")
            print(f"  Multiplier: {prefs['multiplier']}")
            print(f"  Position Type: {prefs['position_type']}")
            print(f"  Current Total Position: {prefs['total_position']}")
            
            # Get bankroll value
            cursor.execute("""
                SELECT bankroll_current 
                FROM users.account_balance_0001 
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            bankroll_result = cursor.fetchone()
            
            if bankroll_result and bankroll_result['bankroll_current']:
                bankroll_value = float(bankroll_result['bankroll_current']) / 100
                print(f"  Bankroll: ${bankroll_value}")
                
                # Calculate expected total_position
                position_size = prefs['position_size']
                multiplier = float(prefs['multiplier'])
                position_type = prefs['position_type']
                
                if position_type == "percent":
                    # Calculate percentage of bankroll
                    percentage_of_bankroll = (position_size * bankroll_value) / 100
                    total_position = round(percentage_of_bankroll * multiplier)
                    print(f"  Expected calculation: {position_size}% of ${bankroll_value} = ${percentage_of_bankroll}")
                    print(f"  With multiplier {multiplier}: {total_position} contracts")
                else:
                    total_position = round(position_size * multiplier)
                    print(f"  Expected calculation: {position_size} * {multiplier} = {total_position} contracts")
                
                # Update the database
                cursor.execute("""
                    UPDATE users.trade_preferences_0001 
                    SET total_position = %s 
                    WHERE id = 1
                """, (total_position,))
                conn.commit()
                
                print(f"  Updated total_position to: {total_position}")
            else:
                print("  No bankroll value found")
        
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_calculation()
