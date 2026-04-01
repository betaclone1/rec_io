#!/usr/bin/env python3

import sys
import os
# Add the project root to the Python path
from backend.util.paths import get_project_root
if get_project_root() not in sys.path:
    sys.path.insert(0, get_project_root())

import psycopg2
from psycopg2.extras import RealDictCursor
import time
from datetime import datetime, timedelta
import pytz

from backend.core.time_eastern import merge_psycopg2_connect_kwargs

EST = pytz.timezone("America/New_York")

# Database configuration
DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
    'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
    'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
    'password': os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
}

def connect_database():
    """Connect to PostgreSQL database"""
    try:
        connection = psycopg2.connect(**merge_psycopg2_connect_kwargs(DB_CONFIG))
        return connection
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Database connection failed: {e}")
        return None

def get_previous_hour_event_ticker():
    """Get the event ticker for the previous hour"""
    try:
        now = datetime.now(EST)
        previous_hour = now - timedelta(hours=1)
        
        # Format: KXBTCD-25AUG0319 (25AUG = Aug 25, 0319 = 03:19 hour)
        # For previous hour, we need to calculate the correct ticker
        hour = previous_hour.hour
        day = previous_hour.day
        month = previous_hour.month
        year = previous_hour.year
        
        # Format: KXBTCD-25AUG0319
        # 25AUG = Aug 25, 0319 = 03:19 hour
        month_name = previous_hour.strftime("%b").upper()
        event_ticker = f"KXBTCD-{day:02d}{month_name}{year}{hour:02d}"
        
        return event_ticker
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error calculating previous hour ticker: {e}")
        return None

def create_historical_schema():
    """Create historical_data schema if it doesn't exist"""
    try:
        connection = connect_database()
        if not connection:
            return False
            
        cursor = connection.cursor()
        cursor.execute("CREATE SCHEMA IF NOT EXISTS historical_data")
        connection.commit()
        connection.close()
        
        print(f"[{datetime.now(EST)}] ✅ Historical schema ready")
        return True
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error creating historical schema: {e}")
        if 'connection' in locals():
            connection.rollback()
            connection.close()
        return False

def archive_strikes_data(event_ticker):
    """Archive strikes data to historical table"""
    try:
        connection = connect_database()
        if not connection:
            return False
            
        cursor = connection.cursor()
        
        # Create historical table name (replace hyphens with underscores)
        historical_table = f"historical_data.{event_ticker.lower().replace('-', '_')}_strikes"
        
        # Check if historical table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'historical_data' 
                AND table_name = %s
            )
        """, (f"{event_ticker.lower().replace('-', '_')}_strikes",))
        
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            # Create historical table with same structure
            cursor.execute(f"""
                CREATE TABLE {historical_table} AS 
                SELECT * FROM live_data.btc_live_strikes 
                WHERE event_ticker = %s
            """, (event_ticker,))
            
            print(f"[{datetime.now(EST)}] ✅ Created historical table: {historical_table}")
        else:
            # Table exists, just copy data
            cursor.execute(f"""
                INSERT INTO {historical_table} 
                SELECT * FROM live_data.btc_live_strikes 
                WHERE event_ticker = %s
            """, (event_ticker,))
            
            print(f"[{datetime.now(EST)}] ✅ Copied data to existing table: {historical_table}")
        
        # Delete from live table
        cursor.execute("""
            DELETE FROM live_data.btc_live_strikes 
            WHERE event_ticker = %s
        """, (event_ticker,))
        
        connection.commit()
        connection.close()
        
        print(f"[{datetime.now(EST)}] ✅ Archived strikes data for {event_ticker}")
        return True
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error archiving strikes data: {e}")
        if 'connection' in locals():
            connection.rollback()
            connection.close()
        return False

def archive_header_data(event_ticker):
    """Archive header data to historical table"""
    try:
        connection = connect_database()
        if not connection:
            return False
            
        cursor = connection.cursor()
        
        # Create historical table name (replace hyphens with underscores)
        historical_table = f"historical_data.{event_ticker.lower().replace('-', '_')}_header"
        
        # Check if historical table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'historical_data' 
                AND table_name = %s
            )
        """, (f"{event_ticker.lower().replace('-', '_')}_header",))
        
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            # Create historical table with same structure
            cursor.execute(f"""
                CREATE TABLE {historical_table} AS 
                SELECT * FROM live_data.btc_live_header 
                WHERE event_ticker = %s
            """, (event_ticker,))
            
            print(f"[{datetime.now(EST)}] ✅ Created historical table: {historical_table}")
        else:
            # Table exists, just copy data
            cursor.execute(f"""
                INSERT INTO {historical_table} 
                SELECT * FROM live_data.btc_live_header 
                WHERE event_ticker = %s
            """, (event_ticker,))
            
            print(f"[{datetime.now(EST)}] ✅ Copied data to existing table: {historical_table}")
        
        # Delete from live table
        cursor.execute("""
            DELETE FROM live_data.btc_live_header 
            WHERE event_ticker = %s
        """, (event_ticker,))
        
        connection.commit()
        connection.close()
        
        print(f"[{datetime.now(EST)}] ✅ Archived header data for {event_ticker}")
        return True
        
    except Exception as e:
        print(f"[{datetime.now(EST)}] ❌ Error archiving header data: {e}")
        if 'connection' in locals():
            connection.rollback()
            connection.close()
        return False

def main():
    print(f"[{datetime.now(EST)}] 🚀 Starting Hourly Data Archiver")
    
    # Create historical schema
    if not create_historical_schema():
        print(f"[{datetime.now(EST)}] ❌ Failed to create historical schema")
        return
    
    # Get previous hour event ticker
    event_ticker = get_previous_hour_event_ticker()
    if not event_ticker:
        print(f"[{datetime.now(EST)}] ❌ Failed to get previous hour ticker")
        return
    
    print(f"[{datetime.now(EST)}] 📊 Archiving data for: {event_ticker}")
    
    # Archive strikes data
    if archive_strikes_data(event_ticker):
        print(f"[{datetime.now(EST)}] ✅ Strikes archived successfully")
    else:
        print(f"[{datetime.now(EST)}] ❌ Failed to archive strikes")
    
    # Archive header data
    if archive_header_data(event_ticker):
        print(f"[{datetime.now(EST)}] ✅ Header archived successfully")
    else:
        print(f"[{datetime.now(EST)}] ❌ Failed to archive header")
    
    print(f"[{datetime.now(EST)}] 🎯 Hourly data archiving completed")

if __name__ == "__main__":
    main() 