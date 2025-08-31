#!/usr/bin/env python3
"""
Live PostgreSQL Table Viewer

A web-based real-time table viewer for monitoring PostgreSQL data flow.
Similar to Xcode's JSON viewer but for database tables.

Usage:
    python live_table_viewer.py --schema live_data --table live_price_log_1s_btc --port 8080
    python live_table_viewer.py --schema public --table trades --port 8081
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
import aiohttp
from aiohttp import web
import signal
import threading
from pathlib import Path

class LiveTableViewer:
    """Web-based real-time PostgreSQL table viewer."""
    
    def __init__(self, schema: str, table: str, port: int = 8080, poll_interval: float = 1.0):
        self.schema = schema
        self.table = table
        self.port = port
        self.poll_interval = poll_interval
        self.connection_params = self._get_connection_params()
        self.previous_data = []
        self.previous_count = 0
        self.start_time = datetime.now()
        self.running = True
        
        # Setup signal handlers
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
        print(f"\n🛑 Shutting down live table viewer...")
        self.running = False
    
    def _get_connection(self):
        """Create a database connection."""
        try:
            conn = psycopg2.connect(**self.connection_params)
            return conn
        except psycopg2.Error as e:
            print(f"❌ Database connection failed: {e}")
            return None
    
    def _get_table_schema(self) -> Optional[List[Dict[str, Any]]]:
        """Get the table schema."""
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
            print(f"❌ Error getting table schema: {e}")
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
            print(f"❌ Error querying table: {e}")
            return None, None
        finally:
            conn.close()
    
    def _detect_changes(self, current_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Detect changes between current and previous data."""
        changes = {
            'inserted': [],
            'updated': [],
            'deleted': []
        }
        
        if not self.previous_data:
            # First run, all current data is new
            changes['inserted'] = current_data
            return changes
        
        # Simple change detection based on row count
        if len(current_data) > len(self.previous_data):
            # More rows - likely insertions
            changes['inserted'] = current_data[:len(current_data) - len(self.previous_data)]
        elif len(current_data) < len(self.previous_data):
            # Fewer rows - likely deletions
            changes['deleted'] = self.previous_data[:len(self.previous_data) - len(current_data)]
        else:
            # Same count but different data - likely updates
            changes['updated'] = current_data[:5]  # Show first 5 rows as "updated"
        
        return changes
    
    def _generate_html(self) -> str:
        """Generate the HTML interface."""
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Table Viewer - {self.schema}.{self.table}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1e1e1e;
            color: #ffffff;
            overflow: hidden;
        }}
        
        .header {{
            background: #2d2d2d;
            padding: 15px 20px;
            border-bottom: 1px solid #404040;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .header h1 {{
            font-size: 18px;
            font-weight: 600;
            color: #ffffff;
        }}
        
        .status {{
            display: flex;
            gap: 20px;
            font-size: 14px;
            color: #cccccc;
        }}
        
        .status-item {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        
        .status-indicator {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #4CAF50;
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
            100% {{ opacity: 1; }}
        }}
        
        .main-content {{
            display: flex;
            height: calc(100vh - 60px);
        }}
        
        .sidebar {{
            width: 300px;
            background: #2d2d2d;
            border-right: 1px solid #404040;
            padding: 20px;
            overflow-y: auto;
        }}
        
        .content {{
            flex: 1;
            padding: 20px;
            overflow-y: auto;
        }}
        
        .section {{
            margin-bottom: 25px;
        }}
        
        .section h3 {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 10px;
            color: #ffffff;
            border-bottom: 1px solid #404040;
            padding-bottom: 5px;
        }}
        
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            font-size: 13px;
        }}
        
        .info-item {{
            background: #3d3d3d;
            padding: 8px 12px;
            border-radius: 4px;
        }}
        
        .info-label {{
            color: #888888;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .info-value {{
            color: #ffffff;
            font-weight: 500;
            margin-top: 2px;
        }}
        
        .changes {{
            background: #2d2d2d;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 15px;
        }}
        
        .change-type {{
            margin-bottom: 15px;
        }}
        
        .change-type h4 {{
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        .change-count {{
            background: #4CAF50;
            color: white;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
        }}
        
        .change-count.deleted {{
            background: #f44336;
        }}
        
        .change-count.updated {{
            background: #ff9800;
        }}
        
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            background: #2d2d2d;
            border-radius: 6px;
            overflow: hidden;
        }}
        
        .data-table th {{
            background: #404040;
            color: #ffffff;
            font-weight: 600;
            text-align: left;
            padding: 12px 15px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .data-table td {{
            padding: 10px 15px;
            border-bottom: 1px solid #404040;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 11px;
        }}
        
        .data-table tr:hover {{
            background: #3d3d3d;
        }}
        
        .data-table tr:last-child td {{
            border-bottom: none;
        }}
        
        .value-null {{
            color: #888888;
            font-style: italic;
        }}
        
        .value-number {{
            color: #4CAF50;
        }}
        
        .value-string {{
            color: #2196F3;
        }}
        
        .value-boolean {{
            color: #FF9800;
        }}
        
        .auto-refresh {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #4CAF50;
            color: white;
            padding: 10px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        }}
        
        .loading {{
            display: flex;
            align-items: center;
            justify-content: center;
            height: 200px;
            color: #888888;
            font-size: 14px;
        }}
        
        .spinner {{
            width: 20px;
            height: 20px;
            border: 2px solid #404040;
            border-top: 2px solid #4CAF50;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 10px;
        }}
        
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔍 Live Table Viewer</h1>
        <div class="status">
            <div class="status-item">
                <div class="status-indicator"></div>
                <span>Live</span>
            </div>
            <div class="status-item">
                <span id="row-count">0</span> rows
            </div>
            <div class="status-item">
                <span id="last-update">--</span>
            </div>
        </div>
    </div>
    
    <div class="main-content">
        <div class="sidebar">
            <div class="section">
                <h3>📊 Table Info</h3>
                <div class="info-grid">
                    <div class="info-item">
                        <div class="info-label">Schema</div>
                        <div class="info-value">{self.schema}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Table</div>
                        <div class="info-value">{self.table}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Port</div>
                        <div class="info-value">{self.port}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">Poll Interval</div>
                        <div class="info-value">{self.poll_interval}s</div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h3>🔄 Recent Changes</h3>
                <div id="changes-container">
                    <div class="loading">
                        <div class="spinner"></div>
                        <span>Loading...</span>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="content">
            <div class="section">
                <h3>📋 Table Data</h3>
                <div id="data-container">
                    <div class="loading">
                        <div class="spinner"></div>
                        <span>Loading data...</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="auto-refresh">
        🔄 Auto-refresh every {self.poll_interval}s
    </div>
    
    <script>
        let lastData = null;
        let lastChanges = null;
        
        function formatValue(value) {{
            if (value === null || value === undefined) {{
                return '<span class="value-null">null</span>';
            }}
            if (typeof value === 'number') {{
                return '<span class="value-number">' + value + '</span>';
            }}
            if (typeof value === 'boolean') {{
                return '<span class="value-boolean">' + value + '</span>';
            }}
            if (typeof value === 'string') {{
                return '<span class="value-string">"' + value + '"</span>';
            }}
            return '<span class="value-string">' + JSON.stringify(value) + '</span>';
        }}
        
        function updateData(data, changes) {{
            // Update row count
            document.getElementById('row-count').textContent = data.length;
            document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
            
            // Update changes
            if (changes && (changes.inserted.length > 0 || changes.updated.length > 0 || changes.deleted.length > 0)) {{
                const changesHtml = `
                    <div class="changes">
                        ${{changes.inserted.length > 0 ? `
                            <div class="change-type">
                                <h4>📥 Inserted <span class="change-count">${{changes.inserted.length}}</span></h4>
                                <div class="data-table">
                                    <table>
                                        <thead>
                                            <tr>${{Object.keys(changes.inserted[0] || {{}}).map(key => `<th>${{key}}</th>`).join('')}}</tr>
                                        </thead>
                                        <tbody>
                                            ${{changes.inserted.slice(0, 3).map(row => `
                                                <tr>${{Object.values(row).map(value => `<td>${{formatValue(value)}}</td>`).join('')}}</tr>
                                            `).join('')}}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        ` : ''}}
                        ${{changes.updated.length > 0 ? `
                            <div class="change-type">
                                <h4>🔄 Updated <span class="change-count updated">${{changes.updated.length}}</span></h4>
                                <div class="data-table">
                                    <table>
                                        <thead>
                                            <tr>${{Object.keys(changes.updated[0] || {{}}).map(key => `<th>${{key}}</th>`).join('')}}</tr>
                                        </thead>
                                        <tbody>
                                            ${{changes.updated.slice(0, 3).map(row => `
                                                <tr>${{Object.values(row).map(value => `<td>${{formatValue(value)}}</td>`).join('')}}</tr>
                                            `).join('')}}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        ` : ''}}
                        ${{changes.deleted.length > 0 ? `
                            <div class="change-type">
                                <h4>📤 Deleted <span class="change-count deleted">${{changes.deleted.length}}</span></h4>
                                <div class="data-table">
                                    <table>
                                        <thead>
                                            <tr>${{Object.keys(changes.deleted[0] || {{}}).map(key => `<th>${{key}}</th>`).join('')}}</tr>
                                        </thead>
                                        <tbody>
                                            ${{changes.deleted.slice(0, 3).map(row => `
                                                <tr>${{Object.values(row).map(value => `<td>${{formatValue(value)}}</td>`).join('')}}</tr>
                                            `).join('')}}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        ` : ''}}
                    </div>
                `;
                document.getElementById('changes-container').innerHTML = changesHtml;
            }}
            
            // Update main data table
            if (data && data.length > 0) {{
                const columns = Object.keys(data[0]);
                const dataHtml = `
                    <div class="data-table">
                        <table>
                            <thead>
                                <tr>${{columns.map(col => `<th>${{col}}</th>`).join('')}}</tr>
                            </thead>
                            <tbody>
                                ${{data.slice(0, 50).map(row => `
                                    <tr>${{columns.map(col => `<td>${{formatValue(row[col])}}</td>`).join('')}}</tr>
                                `).join('')}}
                            </tbody>
                        </table>
                    </div>
                `;
                document.getElementById('data-container').innerHTML = dataHtml;
            }} else {{
                document.getElementById('data-container').innerHTML = '<div class="loading">No data available</div>';
            }}
        }}
        
        async function fetchData() {{
            try {{
                const response = await fetch('/api/data');
                const data = await response.json();
                
                const changesResponse = await fetch('/api/changes');
                const changes = await changesResponse.json();
                
                updateData(data.data, changes.changes);
            }} catch (error) {{
                console.error('Error fetching data:', error);
            }}
        }}
        
        // Initial load
        fetchData();
        
        // Auto-refresh
        setInterval(fetchData, {int(self.poll_interval * 1000)});
    </script>
</body>
</html>
        """
    
    async def handle_index(self, request):
        """Handle the main page."""
        return web.Response(text=self._generate_html(), content_type='text/html')
    
    async def handle_data(self, request):
        """Handle data API endpoint."""
        data, count = self._get_table_data()
        if data is None:
            return web.json_response({'error': 'Failed to get data'}, status=500)
        
        return web.json_response({
            'data': data,
            'count': count,
            'timestamp': datetime.now().isoformat()
        })
    
    async def handle_changes(self, request):
        """Handle changes API endpoint."""
        data, count = self._get_table_data()
        if data is None:
            return web.json_response({'error': 'Failed to get data'}, status=500)
        
        changes = self._detect_changes(data)
        
        # Update previous data
        self.previous_data = data
        self.previous_count = count
        
        return web.json_response({
            'changes': changes,
            'timestamp': datetime.now().isoformat()
        })
    
    async def start_server(self):
        """Start the web server."""
        app = web.Application()
        
        # Add routes
        app.router.add_get('/', self.handle_index)
        app.router.add_get('/api/data', self.handle_data)
        app.router.add_get('/api/changes', self.handle_changes)
        
        # Start server
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', self.port)
        await site.start()
        
        print(f"🚀 Live Table Viewer started!")
        print(f"📊 Monitoring: {self.schema}.{self.table}")
        print(f"🌐 Web Interface: http://localhost:{self.port}")
        print(f"⏱️  Poll Interval: {self.poll_interval}s")
        print(f"🛑 Press Ctrl+C to stop")
        
        # Keep server running
        while self.running:
            await asyncio.sleep(1)
        
        await runner.cleanup()

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Web-based live PostgreSQL table viewer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
      python live_table_viewer.py --schema live_data --table live_price_log_1s_btc
  python live_table_viewer.py --schema public --table trades --port 8081 --poll-interval 2.0
  
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
        '--port',
        type=int,
        default=8080,
        help='Web server port (default: 8080)'
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
    
    # Create and start viewer
    viewer = LiveTableViewer(
        schema=args.schema,
        table=args.table,
        port=args.port,
        poll_interval=args.poll_interval
    )
    
    try:
        asyncio.run(viewer.start_server())
    except KeyboardInterrupt:
        print(f"\n🛑 Viewer stopped")

if __name__ == "__main__":
    main() 