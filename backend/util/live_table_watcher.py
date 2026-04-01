#!/usr/bin/env python3
"""
Live PostgreSQL Table Watcher

A lightweight CLI tool to monitor PostgreSQL tables in real-time.
Perfect for watching data flow during database migrations.

Usage:
    python live_table_watcher.py --schema live_data --table live_price_log_1s_btc
    python live_table_watcher.py --schema public --table trades --poll-interval 2.0
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import psycopg2
from psycopg2.extras import RealDictCursor
import signal
import threading

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

from backend.core.time_eastern import merge_psycopg2_connect_kwargs

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

class TableWatcher:
    """Real-time PostgreSQL table watcher."""
    
    def __init__(self, schema: str, table: str, poll_interval: float = 1.0):
        self.schema = schema
        self.table = table
        self.poll_interval = poll_interval
        self.connection_params = self._get_connection_params()
        self.previous_hash = None
        self.previous_count = 0
        self.previous_data = []
        self.running = True
        self.start_time = datetime.now()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _get_connection_params(self) -> Dict[str, str]:
        """Get database connection parameters from environment or defaults."""
        return {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': os.getenv('POSTGRES_PORT', '5432'),
            'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
            'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
            'password': os.getenv('POSTGRES_PASSWORD', ''),
        }
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n{Colors.YELLOW}🛑 Shutting down table watcher...{Colors.END}")
        self.running = False
    
    def _get_connection(self):
        """Create a database connection."""
        try:
            conn = psycopg2.connect(**merge_psycopg2_connect_kwargs(self.connection_params))
            return conn
        except psycopg2.Error as e:
            print(f"{Colors.RED}❌ Database connection failed: {e}{Colors.END}")
            return None
    
    def _get_table_schema(self) -> Optional[List[Dict[str, Any]]]:
        """Get the table schema to understand the structure."""
        conn = self._get_connection()
        if not conn:
            return None
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                query = """
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns 
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                """
                cursor.execute(query, (self.schema, self.table))
                return cursor.fetchall()
        except psycopg2.Error as e:
            print(f"{Colors.RED}❌ Error getting table schema: {e}{Colors.END}")
            return None
        finally:
            conn.close()
    
    def _get_table_data(self) -> Tuple[Optional[List[Dict[str, Any]]], Optional[int]]:
        """Get current table data and row count."""
        conn = self._get_connection()
        if not conn:
            return None, None
        
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get row count
                count_query = f"SELECT COUNT(*) FROM {self.schema}.{self.table}"
                cursor.execute(count_query)
                count_result = cursor.fetchone()
                count = list(count_result.values())[0] if count_result else 0
                
                # Get all data (limit to last 1000 rows for performance)
                data_query = f"SELECT * FROM {self.schema}.{self.table} ORDER BY 1 DESC LIMIT 1000"
                cursor.execute(data_query)
                data = cursor.fetchall()
                
                # Convert Decimal types to float for JSON serialization
                processed_data = []
                for row in data:
                    processed_row = {}
                    for key, value in row.items():
                        if hasattr(value, 'quantize'):  # Decimal type
                            processed_row[key] = float(value)
                        else:
                            processed_row[key] = value
                    processed_data.append(processed_row)
                
                return processed_data, count
        except psycopg2.Error as e:
            print(f"{Colors.RED}❌ Error querying table: {e}{Colors.END}")
            return None, None
        finally:
            conn.close()
    
    def _calculate_hash(self, data: List[Dict[str, Any]]) -> str:
        """Calculate a hash of the table data for change detection."""
        if not data:
            return hashlib.md5(b"").hexdigest()
        
        # Convert data to a consistent string representation
        data_str = json.dumps(data, default=str, sort_keys=True)
        return hashlib.md5(data_str.encode()).hexdigest()
    
    def _format_row(self, row: Dict[str, Any]) -> str:
        """Format a row for display."""
        formatted = []
        for key, value in row.items():
            if value is None:
                formatted.append(f"{key}: NULL")
            elif isinstance(value, (int, float)):
                formatted.append(f"{key}: {value}")
            else:
                # Truncate long string values
                str_value = str(value)
                if len(str_value) > 50:
                    str_value = str_value[:47] + "..."
                formatted.append(f"{key}: {str_value}")
        return " | ".join(formatted)
    
    def _detect_changes(self, current_data: List[Dict[str, Any]], 
                       previous_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Detect changes between current and previous data."""
        changes = {
            'inserted': [],
            'updated': [],
            'deleted': []
        }
        
        if not previous_data:
            # First run, all current data is new
            changes['inserted'] = current_data
            return changes
        
        # Simple change detection based on row count and hash
        # For more sophisticated change detection, you'd need a primary key
        current_hash = self._calculate_hash(current_data)
        previous_hash = self._calculate_hash(previous_data)
        
        if current_hash != previous_hash:
            # Hash changed, assume there are changes
            # This is a simplified approach - for production you'd want more sophisticated detection
            if len(current_data) > len(previous_data):
                # More rows - likely insertions
                changes['inserted'] = current_data[:len(current_data) - len(previous_data)]
            elif len(current_data) < len(previous_data):
                # Fewer rows - likely deletions
                changes['deleted'] = previous_data[:len(previous_data) - len(current_data)]
            else:
                # Same count but different hash - likely updates
                changes['updated'] = current_data[:5]  # Show first 5 rows as "updated"
        
        return changes
    
    def _print_header(self):
        """Print the watcher header."""
        print(f"{Colors.BOLD}{Colors.CYAN}")
        print("=" * 80)
        print(f"🔍 LIVE TABLE WATCHER")
        print(f"📊 Schema: {self.schema}")
        print(f"📋 Table: {self.table}")
        print(f"⏱️  Poll Interval: {self.poll_interval}s")
        print(f"🕐 Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        print(f"{Colors.END}")
    
    def _print_status(self, count: int, hash_value: str, changes: Dict[str, List[Dict[str, Any]]]):
        """Print current status and changes."""
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Status line
        status_line = f"{Colors.BLUE}[{timestamp}] {Colors.END}"
        status_line += f"{Colors.BOLD}Rows: {count}{Colors.END} | "
        status_line += f"Hash: {hash_value[:8]}... | "
        
        # Change indicators
        if changes['inserted']:
            status_line += f"{Colors.GREEN}📥 +{len(changes['inserted'])}{Colors.END} "
        if changes['updated']:
            status_line += f"{Colors.YELLOW}🔄 ~{len(changes['updated'])}{Colors.END} "
        if changes['deleted']:
            status_line += f"{Colors.RED}📤 -{len(changes['deleted'])}{Colors.END} "
        
        if not any(changes.values()):
            status_line += f"{Colors.CYAN}✨ No changes{Colors.END}"
        
        print(status_line)
        
        # Print detailed changes
        if changes['inserted']:
            print(f"{Colors.GREEN}📥 INSERTED ROWS:{Colors.END}")
            for row in changes['inserted'][:3]:  # Show first 3
                print(f"  {Colors.GREEN}+{Colors.END} {self._format_row(row)}")
            if len(changes['inserted']) > 3:
                print(f"  {Colors.GREEN}... and {len(changes['inserted']) - 3} more{Colors.END}")
        
        if changes['updated']:
            print(f"{Colors.YELLOW}🔄 UPDATED ROWS:{Colors.END}")
            for row in changes['updated'][:3]:  # Show first 3
                print(f"  {Colors.YELLOW}~{Colors.END} {self._format_row(row)}")
            if len(changes['updated']) > 3:
                print(f"  {Colors.YELLOW}... and {len(changes['updated']) - 3} more{Colors.END}")
        
        if changes['deleted']:
            print(f"{Colors.RED}📤 DELETED ROWS:{Colors.END}")
            for row in changes['deleted'][:3]:  # Show first 3
                print(f"  {Colors.RED}-{Colors.END} {self._format_row(row)}")
            if len(changes['deleted']) > 3:
                print(f"  {Colors.RED}... and {len(changes['deleted']) - 3} more{Colors.END}")
        
        if any(changes.values()):
            print()  # Empty line after changes
    
    def watch(self):
        """Main watching loop."""
        self._print_header()
        
        # Get initial table schema
        schema_info = self._get_table_schema()
        if not schema_info:
            print(f"{Colors.RED}❌ Could not get table schema. Exiting.{Colors.END}")
            return
        
        print(f"{Colors.CYAN}📋 Table Schema:{Colors.END}")
        for col in schema_info[:5]:  # Show first 5 columns
            print(f"  {col['column_name']}: {col['data_type']}")
        if len(schema_info) > 5:
            print(f"  ... and {len(schema_info) - 5} more columns")
        print()
        
        # Main watching loop
        while self.running:
            try:
                # Get current data
                current_data, current_count = self._get_table_data()
                
                if current_data is None:
                    print(f"{Colors.RED}❌ Failed to get table data. Retrying...{Colors.END}")
                    time.sleep(self.poll_interval)
                    continue
                
                # Calculate current hash
                current_hash = self._calculate_hash(current_data)
                
                # Detect changes
                changes = self._detect_changes(current_data, self.previous_data)
                
                # Print status
                self._print_status(current_count, current_hash, changes)
                
                # Update previous state
                self.previous_data = current_data
                self.previous_hash = current_hash
                self.previous_count = current_count
                
                # Wait for next poll
                time.sleep(self.poll_interval)
                
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}🛑 Interrupted by user{Colors.END}")
                break
            except Exception as e:
                print(f"{Colors.RED}❌ Unexpected error: {e}{Colors.END}")
                import traceback
                traceback.print_exc()
                time.sleep(self.poll_interval)
        
        # Print final summary
        runtime = datetime.now() - self.start_time
        print(f"\n{Colors.CYAN}📊 Final Summary:{Colors.END}")
        print(f"  Runtime: {runtime}")
        print(f"  Final Row Count: {self.previous_count}")
        print(f"  Final Hash: {self.previous_hash[:8]}...")

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Live PostgreSQL table watcher for monitoring data flow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
      python live_table_watcher.py --schema live_data --table live_price_log_1s_btc
  python live_table_watcher.py --schema public --table trades --poll-interval 2.0
  
Environment Variables:
  POSTGRES_HOST=localhost
  POSTGRES_PORT=5432
  POSTGRES_DB=rec_io_db
  POSTGRES_USER=rec_io_user
  POSTGRES_PASSWORD=
        """
    )
    
    parser.add_argument(
        '--schema',
        required=True,
        help='Database schema name (e.g., live_data, public)'
    )
    
    parser.add_argument(
        '--table',
        required=True,
        help='Table name to watch (e.g., live_price_log_1s_btc, trades)'
    )
    
    parser.add_argument(
        '--poll-interval',
        type=float,
        default=1.0,
        help='Polling interval in seconds (default: 1.0)'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.poll_interval < 0.1:
        print(f"{Colors.RED}❌ Poll interval must be at least 0.1 seconds{Colors.END}")
        sys.exit(1)
    
    # Create and start watcher
    watcher = TableWatcher(
        schema=args.schema,
        table=args.table,
        poll_interval=args.poll_interval
    )
    
    try:
        watcher.watch()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}🛑 Watcher stopped{Colors.END}")

if __name__ == "__main__":
    main() 