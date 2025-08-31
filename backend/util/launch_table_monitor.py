#!/usr/bin/env python3
"""
Table Monitor Launcher

Easy launcher for PostgreSQL table monitoring tools.
Automatically sets up environment and launches the appropriate tool.

Usage:
    python launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web
    python launch_table_monitor.py --schema public --table trades --mode terminal
"""

import argparse
import os
import sys
import subprocess
from pathlib import Path

def setup_environment():
    """Set up the environment for the monitoring tools."""
    # Get the project root
    project_root = Path(__file__).parent.parent.parent
    os.chdir(project_root)
    
    # Set up Python path
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    # Set default environment variables if not already set
    env_vars = {
        'POSTGRES_HOST': 'localhost',
        'POSTGRES_PORT': '5432',
        'POSTGRES_DB': 'rec_io_db',
        'POSTGRES_USER': 'rec_io_user',
        'POSTGRES_PASSWORD': '',
    }
    
    for key, default_value in env_vars.items():
        if key not in os.environ:
            os.environ[key] = default_value

def launch_terminal_watcher(schema, table, poll_interval):
    """Launch the terminal-based table watcher."""
    script_path = Path(__file__).parent / "live_table_watcher.py"
    
    cmd = [
        sys.executable,
        str(script_path),
        "--schema", schema,
        "--table", table,
        "--poll-interval", str(poll_interval)
    ]
    
    print(f"🚀 Launching Terminal Watcher...")
    print(f"📊 Schema: {schema}")
    print(f"📋 Table: {table}")
    print(f"⏱️  Poll Interval: {poll_interval}s")
    print(f"🛑 Press Ctrl+C to stop")
    print()
    
    subprocess.run(cmd)

def launch_web_viewer(schema, table, port, poll_interval):
    """Launch the web-based table viewer."""
    script_path = Path(__file__).parent / "live_table_viewer.py"
    
    cmd = [
        sys.executable,
        str(script_path),
        "--schema", schema,
        "--table", table,
        "--port", str(port),
        "--poll-interval", str(poll_interval)
    ]
    
    print(f"🚀 Launching Web Viewer...")
    print(f"📊 Schema: {schema}")
    print(f"📋 Table: {table}")
    print(f"🌐 Web Interface: http://localhost:{port}")
    print(f"⏱️  Poll Interval: {poll_interval}s")
    print(f"🛑 Press Ctrl+C to stop")
    print()
    
    subprocess.run(cmd)

def main():
    """Main launcher function."""
    parser = argparse.ArgumentParser(
        description="Launch PostgreSQL table monitoring tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Web-based viewer (recommended for development)
  python launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web
  
  # Terminal-based watcher
  python launch_table_monitor.py --schema public --table trades --mode terminal
  
  # Custom port and polling interval
  python launch_table_monitor.py --schema live_data --table live_price_log_1s_btc --mode web --port 8081 --poll-interval 2.0
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
        '--mode',
        choices=['web', 'terminal'],
        default='web',
        help='Monitoring mode: web (recommended) or terminal'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='Web server port (default: 8080, only used in web mode)'
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
        print("❌ Poll interval must be at least 0.1 seconds")
        sys.exit(1)
    
    if args.port < 1 or args.port > 65535:
        print("❌ Port must be between 1 and 65535")
        sys.exit(1)
    
    # Set up environment
    setup_environment()
    
    # Launch the appropriate tool
    if args.mode == 'web':
        launch_web_viewer(args.schema, args.table, args.port, args.poll_interval)
    else:
        launch_terminal_watcher(args.schema, args.table, args.poll_interval)

if __name__ == "__main__":
    main() 