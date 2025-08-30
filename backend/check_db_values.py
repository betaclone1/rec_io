#!/usr/bin/env python3
"""
Script to check current values in trade_preferences_0001 table
"""

import psycopg2

def check_db_values():
    try:
        # Connect to the remote database
        conn = psycopg2.connect(
            host="137.184.224.94",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, trade_strategy, position_size, multiplier, position_type, total_position 
                FROM users.trade_preferences_0001
            """)
            results = cursor.fetchall()
            
            print("Current values in trade_preferences_0001:")
            for row in results:
                print(f"Row {row[0]}:")
                print(f"  Strategy: {row[1]}")
                print(f"  Position Size: {row[2]}")
                print(f"  Multiplier: {row[3]} (type: {type(row[3])})")
                print(f"  Position Type: {row[4]}")
                print(f"  Total Position: {row[5]}")
                print()
                
                # Calculate what it should be
                position_size = row[2]
                multiplier = float(row[3])
                position_type = row[4]
                
                if position_type == "percent":
                    # For percent mode, we need bankroll value
                    print(f"  Position Type is 'percent' - need bankroll value for calculation")
                    print(f"  Current calculation would be: {position_size} * {multiplier} = {position_size * multiplier}")
                else:
                    # For contracts mode
                    expected = round(position_size * multiplier)
                    print(f"  Expected total_position: {position_size} * {multiplier} = {expected}")
                    print(f"  Actual total_position: {row[5]}")
                    print(f"  Match: {'Yes' if expected == row[5] else 'No'}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_db_values()
