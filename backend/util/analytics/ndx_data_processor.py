#!/usr/bin/env python3
"""
NDX Data Processor
Processes monthly NDX (IUXX) CSV files and combines them into a single ndx_price_history table
"""

import pandas as pd
import psycopg2
import os
import glob
from datetime import datetime
import sys

def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(
            host='localhost',
            database='rec_io_db',
            user='rec_io_user',
            password='rec_io_password'
        )
        return conn
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return None

def create_ndx_table(conn):
    """Create the ndx_price_history table in historical_data schema"""
    cursor = conn.cursor()
    
    # Create table with same structure as BTC/ETH/SPX tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_data.ndx_price_history (
            timestamp TIMESTAMP PRIMARY KEY,
            open NUMERIC(20,8),
            high NUMERIC(20,8),
            low NUMERIC(20,8),
            close NUMERIC(20,8),
            volume NUMERIC(20,8),
            momentum NUMERIC(10,2),
            momentum_percentile NUMERIC(10,2)
        )
    """)
    
    # Add comment to document timezone
    cursor.execute("""
        COMMENT ON TABLE historical_data.ndx_price_history IS 
        'NDX (IUXX) price history data with timestamps in East Coast (America/New_York) timezone'
    """)
    
    # Create unique index on timestamp
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS unique_ndx_price_history_timestamp 
        ON historical_data.ndx_price_history (timestamp)
    """)
    
    conn.commit()
    print("✅ NDX price history table created/verified")

def process_ndx_files():
    """Process all NDX CSV files and combine into single table"""
    
    # Connect to database
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        # Create table
        create_ndx_table(conn)
        
        # Clear existing data
        cursor = conn.cursor()
        cursor.execute("DELETE FROM historical_data.ndx_price_history")
        conn.commit()
        print("🗑️ Cleared existing NDX data")
        
        # Find all NDX CSV files (from project root)
        # Go up 3 levels from backend/util/analytics to project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        ndx_path = os.path.join(project_root, "NDX_HISTORICAL", "*.csv")
        csv_files = glob.glob(ndx_path)
        csv_files.sort()
        
        print(f"📁 Found {len(csv_files)} NDX CSV files")
        
        total_processed = 0
        
        for csv_file in csv_files:
            print(f"📊 Processing: {os.path.basename(csv_file)}")
            
            try:
                # Read CSV file and filter out footer lines
                df = pd.read_csv(csv_file)
                
                # Remove footer lines (contain "Downloaded from Barchart.com")
                df = df[~df['Time'].astype(str).str.contains('Downloaded', na=False)]
                
                if df.empty:
                    print(f"   ⚠️ Empty file: {csv_file}")
                    continue
                
                # Clean and rename columns
                df_clean = pd.DataFrame()
                df_clean['timestamp'] = pd.to_datetime(df['Time'].str.strip('"'))
                df_clean['open'] = pd.to_numeric(df['Open'], errors='coerce')
                df_clean['high'] = pd.to_numeric(df['High'], errors='coerce')
                df_clean['low'] = pd.to_numeric(df['Low'], errors='coerce')
                df_clean['close'] = pd.to_numeric(df['Last'], errors='coerce')  # Map 'Last' to 'close'
                df_clean['volume'] = pd.to_numeric(df['Volume'], errors='coerce')
                
                # Set momentum fields to NULL for now (will be calculated later)
                df_clean['momentum'] = None
                df_clean['momentum_percentile'] = None
                
                # Remove any rows with invalid data
                df_clean = df_clean.dropna(subset=['timestamp', 'open', 'high', 'low', 'close'])
                
                # Apply after-hours filtering (09:30-16:00 only)
                df_clean = df_clean[
                    (df_clean['timestamp'].dt.time >= pd.Timestamp('09:30:00').time()) &
                    (df_clean['timestamp'].dt.time <= pd.Timestamp('16:00:00').time())
                ]
                
                if df_clean.empty:
                    print(f"   ⚠️ No valid data after filtering: {csv_file}")
                    continue
                
                print(f"   📈 Processed {len(df_clean)} records from {df_clean['timestamp'].min()} to {df_clean['timestamp'].max()}")
                
                # Insert into database
                for _, row in df_clean.iterrows():
                    try:
                        cursor.execute("""
                            INSERT INTO historical_data.ndx_price_history 
                            (timestamp, open, high, low, close, volume, momentum, momentum_percentile)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (timestamp) DO NOTHING
                        """, (
                            row['timestamp'],
                            float(row['open']),
                            float(row['high']),
                            float(row['low']),
                            float(row['close']),
                            float(row['volume']),
                            None,
                            None
                        ))
                    except Exception as e:
                        print(f"   ❌ Error inserting row {row['timestamp']}: {e}")
                        continue
                
                # Commit this file's data
                conn.commit()
                
                # Count records added
                cursor.execute("SELECT COUNT(*) FROM historical_data.ndx_price_history")
                current_count = cursor.fetchone()[0]
                new_records = current_count - total_processed
                total_processed = current_count
                
                print(f"   💾 Inserted {new_records} new records")
                
            except Exception as e:
                print(f"   ❌ Error processing {csv_file}: {e}")
                continue
        
        # Final verification
        cursor.execute("""
            SELECT 
                COUNT(*) as total_records,
                MIN(timestamp) as earliest,
                MAX(timestamp) as latest,
                MIN(close) as min_price,
                MAX(close) as max_price
            FROM historical_data.ndx_price_history
        """)
        
        result = cursor.fetchone()
        total_records, earliest, latest, min_price, max_price = result
        
        print("==================================================")
        print("✅ NDX Data Processing Complete")
        print(f"📊 Total records in database: {total_records:,}")
        print(f"📅 Date range: {earliest} to {latest}")
        print(f"💰 Price range: ${min_price:,.2f} to ${max_price:,.2f}")
        print(f"📈 New records added: {total_processed:,}")
        print("==================================================")
        
    except Exception as e:
        print(f"❌ Error in NDX processing: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("🚀 Starting NDX Data Processing")
    print("==================================================")
    process_ndx_files()
