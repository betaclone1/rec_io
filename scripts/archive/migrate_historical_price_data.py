#!/usr/bin/env python3
"""
Historical Price Data Migration Script
Migrates 5-year master price histories from CSV to PostgreSQL
"""

import csv
import psycopg2
from datetime import datetime
import sys
import os

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_postgresql_connection():
    """Get PostgreSQL connection"""
    try:
        return psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None

def migrate_historical_price_data(symbol, csv_file_path):
    """
    Migrate historical price data from CSV to PostgreSQL
    
    Args:
        symbol: The symbol (BTC, ETH, etc.)
        csv_file_path: Path to the CSV file
    """
    print(f"🔄 Starting migration for {symbol} from {csv_file_path}")
    
    # Connect to PostgreSQL
    conn = get_postgresql_connection()
    if not conn:
        print(f"❌ Failed to connect to PostgreSQL")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Determine table name based on symbol
        table_name = f"{symbol.lower()}_price_history"
        
        # Count existing records for this table
        cursor.execute(f"SELECT COUNT(*) FROM historical_data.{table_name}")
        existing_count = cursor.fetchone()[0]
        print(f"📊 Found {existing_count} existing records for {symbol}")
        
        # Read CSV file
        print(f"📖 Reading CSV file: {csv_file_path}")
        with open(csv_file_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Prepare batch insert
            batch_size = 10000
            batch_data = []
            total_imported = 0
            
            for row in reader:
                try:
                    # Parse timestamp
                    timestamp = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S')
                    
                    # Parse numeric values
                    open_price = float(row['open']) if row['open'] else None
                    high_price = float(row['high']) if row['high'] else None
                    low_price = float(row['low']) if row['low'] else None
                    close_price = float(row['close']) if row['close'] else None
                    volume = float(row['volume']) if row['volume'] else None
                    momentum = float(row['momentum']) if row['momentum'] else None
                    
                    # Add to batch
                    batch_data.append((
                        timestamp,
                        open_price,
                        high_price,
                        low_price,
                        close_price,
                        volume,
                        momentum
                    ))
                    
                    # Execute batch when full
                    if len(batch_data) >= batch_size:
                        cursor.executemany(f"""
                            INSERT INTO historical_data.{table_name} 
                            (timestamp, open, high, low, close, volume, momentum)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (timestamp) DO NOTHING
                        """, batch_data)
                        
                        conn.commit()
                        total_imported += len(batch_data)
                        print(f"✅ Imported batch of {len(batch_data)} records for {symbol} (Total: {total_imported})")
                        batch_data = []
                        
                except Exception as e:
                    print(f"⚠️ Error processing row: {row} - {e}")
                    continue
            
            # Insert remaining batch
            if batch_data:
                cursor.executemany(f"""
                    INSERT INTO historical_data.{table_name} 
                    (timestamp, open, high, low, close, volume, momentum)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (timestamp) DO NOTHING
                """, batch_data)
                conn.commit()
                total_imported += len(batch_data)
                print(f"✅ Imported final batch of {len(batch_data)} records for {symbol}")
            
            print(f"🎉 Migration completed for {symbol}: {total_imported} records imported")
            
            # Verify final count
            cursor.execute(f"SELECT COUNT(*) FROM historical_data.{table_name}")
            final_count = cursor.fetchone()[0]
            print(f"📊 Final count for {symbol}: {final_count} records")
            
            return True
            
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def main():
    """Main migration function"""
    print("🚀 Starting Historical Price Data Migration")
    print("=" * 50)
    
    # Define migration tasks
    migrations = [
        {
            'symbol': 'BTC',
            'csv_path': 'backend/data/historical_data/btc_historical/btc_1m_master_5y.csv'
        },
        {
            'symbol': 'ETH', 
            'csv_path': 'backend/data/historical_data/eth_historical/eth_1m_master_5y.csv'
        }
    ]
    
    # Execute migrations
    for migration in migrations:
        symbol = migration['symbol']
        csv_path = migration['csv_path']
        
        if not os.path.exists(csv_path):
            print(f"❌ CSV file not found: {csv_path}")
            continue
            
        print(f"\n📈 Migrating {symbol} data...")
        success = migrate_historical_price_data(symbol, csv_path)
        
        if success:
            print(f"✅ {symbol} migration completed successfully")
        else:
            print(f"❌ {symbol} migration failed")
    
    print("\n🎉 Historical Price Data Migration Complete!")

if __name__ == "__main__":
    main()
