#!/usr/bin/env python3
"""
SPX Data Processor
Processes monthly SPX CSV files and combines them into a single spx_price_history table
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

def create_spx_table(conn):
    """Create the spx_price_history table in historical_data schema"""
    cursor = conn.cursor()
    
    # Create table with same structure as BTC/ETH tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS historical_data.spx_price_history (
            timestamp TIMESTAMP WITHOUT TIME ZONE PRIMARY KEY,
            open NUMERIC(20,8),
            high NUMERIC(20,8),
            low NUMERIC(20,8),
            close NUMERIC(20,8),
            volume NUMERIC(20,8),
            momentum NUMERIC(10,4),
            momentum_percentile NUMERIC(5,1)
        );
    """)
    
    # Create indexes
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS unique_spx_price_history_timestamp 
        ON historical_data.spx_price_history (timestamp);
    """)
    
    conn.commit()
    print("✅ Created spx_price_history table")

def process_spx_csv(file_path):
    """Process a single SPX CSV file and return cleaned DataFrame"""
    print(f"📊 Processing: {os.path.basename(file_path)}")
    
    try:
        # Read CSV
        df = pd.read_csv(file_path)
        
        # Remove any footer rows (like "Downloaded from Barchart.com...")
        df = df[df['Time'].str.contains(r'^\d{4}-\d{2}-\d{2}', na=False)]
        
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
        
        # Filter out after-hours data (anything after 16:00)
        df_clean = df_clean[df_clean['timestamp'].dt.time <= pd.Timestamp('16:00:00').time()]
        
        print(f"   📈 Processed {len(df_clean)} records from {df_clean['timestamp'].min()} to {df_clean['timestamp'].max()}")
        
        return df_clean
        
    except Exception as e:
        print(f"❌ Error processing {file_path}: {e}")
        return None

def insert_spx_data(conn, df):
    """Insert SPX data into database"""
    if df is None or len(df) == 0:
        return 0
    
    cursor = conn.cursor()
    
    # Use INSERT ... ON CONFLICT DO NOTHING to handle duplicates
    insert_query = """
        INSERT INTO historical_data.spx_price_history 
        (timestamp, open, high, low, close, volume, momentum, momentum_percentile)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (timestamp) DO NOTHING
    """
    
    # Convert DataFrame to list of tuples
    data_tuples = [tuple(row) for row in df.to_numpy()]
    
    # Execute batch insert
    cursor.executemany(insert_query, data_tuples)
    rows_inserted = cursor.rowcount
    
    conn.commit()
    print(f"   💾 Inserted {rows_inserted} new records")
    
    return rows_inserted

def main():
    """Main processing function"""
    print("🚀 Starting SPX Data Processing")
    print("=" * 50)
    
    # Get database connection
    conn = get_db_connection()
    if not conn:
        return False
    
    # Create SPX table
    create_spx_table(conn)
    
    # Find all SPX CSV files
    spx_files = glob.glob("/Users/ericwais1/rec_io_local/2_0/SPX_HISTORICAL/*.csv")
    spx_files.sort()  # Process in order
    
    print(f"📁 Found {len(spx_files)} SPX CSV files")
    
    total_records = 0
    
    for file_path in spx_files:
        # Process CSV file
        df = process_spx_csv(file_path)
        
        # Insert into database
        if df is not None:
            records_inserted = insert_spx_data(conn, df)
            total_records += records_inserted
    
    # Get final statistics
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM historical_data.spx_price_history")
    count, min_date, max_date = cursor.fetchone()
    
    print("=" * 50)
    print("✅ SPX Data Processing Complete")
    print(f"📊 Total records in database: {count:,}")
    print(f"📅 Date range: {min_date} to {max_date}")
    print(f"📈 New records added: {total_records:,}")
    
    conn.close()
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
