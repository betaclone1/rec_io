#!/usr/bin/env python3
"""
Active Trade Supervisor - MONITOR-AWARE VERSION

Monitors currently open trades and maintains a standalone database
for active trade management. Gets notified when trade_manager confirms
new open trades and creates corresponding entries in ACTIVE_TRADES.DB.
Supports multiple monitors with monitor-specific configuration.
"""

import os
import json
import time
import threading
import signal
from datetime import datetime, timezone, time as datetime_time, timedelta
from zoneinfo import ZoneInfo
import requests
from typing import Dict, List, Optional, Any
import psycopg2
import sys
# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.core.port_config import get_port
from backend.util.paths import get_host

# Add these functions after the existing imports and before the get_monitor_identifier function

def create_monitor_active_trades_table():
    """Create monitor-specific active trades table when supervisor starts"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Create monitor-specific active trades table
            active_trades_table = f"active_trades_{USER_NUMBER}_{MONITOR_ID}"
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS users.{active_trades_table} (
                    id SERIAL PRIMARY KEY,
                    trade_id INTEGER NOT NULL,
                    ticket_id VARCHAR(50),
                    date DATE,
                    time TIME,
                    strike VARCHAR(50),
                    side VARCHAR(10),
                    buy_price DECIMAL(10,4),
                    position INTEGER,
                    contract VARCHAR(50),
                    ticker VARCHAR(50),
                    symbol VARCHAR(10),
                    market VARCHAR(50),
                    trade_strategy VARCHAR(50),
                    symbol_open DECIMAL(10,2),
                    momentum DECIMAL(5,2),
                    prob DECIMAL(5,2),
                    fees DECIMAL(10,4),
                    diff DECIMAL(10,4),
                    status VARCHAR(20) DEFAULT 'active',
                    current_symbol_price DECIMAL(10,2),
                    current_probability DECIMAL(5,2),
                    buffer_from_entry DECIMAL(10,2),
                    time_since_entry INTEGER,
                    current_close_price DECIMAL(10,4),
                    current_pnl VARCHAR(20),
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        conn.close()
        log(f"[ACTIVE_TRADES] ✅ Created monitor-specific active trades table: {active_trades_table}")
    except Exception as e:
        log(f"[ACTIVE_TRADES] ❌ Error creating active trades table: {e}")

def drop_monitor_active_trades_table():
    """Drop monitor-specific active trades table when supervisor stops"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Drop monitor-specific active trades table
            active_trades_table = f"active_trades_{USER_NUMBER}_{MONITOR_ID}"
            cursor.execute(f"DROP TABLE IF EXISTS users.{active_trades_table}")
            conn.commit()
        conn.close()
        log(f"[ACTIVE_TRADES] ✅ Dropped monitor-specific active trades table: {active_trades_table}")
    except Exception as e:
        log(f"[ACTIVE_TRADES] ❌ Error dropping active trades table: {e}")

def get_monitor_active_trades_table():
    """Get the monitor-specific active trades table name"""
    return f"active_trades_{USER_NUMBER}_{MONITOR_ID}"

# Monitor identification - extract from script name or command line args
def get_monitor_identifier():
    """Extract monitor identifier from script name or command line arguments"""
    script_name = os.path.basename(sys.argv[0])
    
    # Check if script name contains monitor identifier (e.g., active_trade_supervisor_0001_10001)
    if '_' in script_name and script_name.count('_') >= 3:
        parts = script_name.split('_')
        if len(parts) >= 4:
            user_number = parts[-2]  # 0001
            monitor_id = parts[-1]   # 10001
            return f"{user_number}_{monitor_id}"
    
    # Check command line arguments
    if len(sys.argv) > 1:
        return sys.argv[1]  # Use first argument as monitor identifier
    
    # Default to first active monitor if no identifier provided
    raise ValueError("No monitor identifier found in script name")

# Get monitor identifier
MONITOR_IDENTIFIER = get_monitor_identifier()
USER_NUMBER = MONITOR_IDENTIFIER.split('_')[0]
MONITOR_ID = MONITOR_IDENTIFIER.split('_')[1]

print(f"[ACTIVE_TRADE_SUPERVISOR_{MONITOR_IDENTIFIER}] 🚀 Monitor-aware supervisor starting")
print(f"[ACTIVE_TRADE_SUPERVISOR_{MONITOR_IDENTIFIER}] User: {USER_NUMBER}, Monitor: {MONITOR_ID}")

# Get symbol for this monitor (will be updated dynamically)
def get_monitor_symbol():
    """Get the symbol for the current monitor from database"""
    try:
        import psycopg2
        
        # PostgreSQL connection parameters
        postgres_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
            'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
            'password': os.getenv('POSTGRES_PASSWORD', '')
        }
        
        conn = psycopg2.connect(**postgres_config)
        cursor = conn.cursor()
        
        cursor.execute(f"""
            SELECT symbol FROM users.monitor_list_{USER_NUMBER} 
            WHERE id = %s
        """, (MONITOR_ID,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            return result[0].upper()  # Return uppercase (BTC, ETH, etc.)
        else:
            log(f"[ACTIVE_TRADE_SUPERVISOR] ⚠️ No symbol found for monitor {MONITOR_IDENTIFIER}, defaulting to BTC")
            return "BTC"  # Default fallback
    except Exception as e:
        log(f"[ACTIVE_TRADE_SUPERVISOR] ❌ Error getting monitor symbol: {e}, defaulting to BTC")
        return "BTC"  # Default fallback

MONITOR_SYMBOL = get_monitor_symbol()
print(f"[ACTIVE_TRADE_SUPERVISOR_{MONITOR_IDENTIFIER}] 📊 Initial symbol: {MONITOR_SYMBOL}")

def get_current_monitor_symbol():
    """Get the current symbol for this monitor (dynamic lookup)"""
    global MONITOR_SYMBOL
    
    try:
        import psycopg2
        
        # PostgreSQL connection parameters
        postgres_config = {
            'host': os.getenv('POSTGRES_HOST', 'localhost'),
            'port': int(os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
            'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
            'password': os.getenv('POSTGRES_PASSWORD', '')
        }
        
        conn = psycopg2.connect(**postgres_config)
        cursor = conn.cursor()
        
        cursor.execute(f"""
            SELECT symbol FROM users.monitor_list_{USER_NUMBER} 
            WHERE id = %s
        """, (MONITOR_ID,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            new_symbol = result[0].upper()  # Return uppercase (BTC, ETH, etc.)
            
            # Check if symbol has changed
            if new_symbol != MONITOR_SYMBOL:
                log(f"[ACTIVE_TRADE_SUPERVISOR] 🔄 Symbol changed from {MONITOR_SYMBOL} to {new_symbol}")
                MONITOR_SYMBOL = new_symbol
            
            return new_symbol
        else:
            return "BTC"  # Default fallback
    except Exception as e:
        return "BTC"  # Default fallback

# Get port from monitor-specific system
from backend.core.port_config import get_monitor_port, register_monitor_ports

# Register this monitor's ports to ensure consistency
register_monitor_ports(MONITOR_IDENTIFIER)

# Get monitor-specific port
ACTIVE_TRADE_SUPERVISOR_PORT = get_monitor_port("active_trade_supervisor", MONITOR_IDENTIFIER)
print(f"[ACTIVE_TRADE_SUPERVISOR_{MONITOR_IDENTIFIER}] 🚀 Using monitor-specific port: {ACTIVE_TRADE_SUPERVISOR_PORT}")

# Import centralized path utilities
from backend.util.paths import get_project_root, get_data_dir, get_trade_history_dir, get_kalshi_data_dir, get_service_url, get_active_trades_dir



# Import centralized path utilities
from backend.core.config.settings import config
from flask import Flask, request, jsonify
from flask_cors import CORS

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variable to track monitoring thread
monitoring_thread = None
monitoring_thread_lock = threading.Lock()

# Cache for active trades data to reduce frontend load
active_trades_cache = None
active_trades_cache_time = 0
CACHE_DURATION = 2  # Cache for 2 seconds

# Health check endpoint
@app.route("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": f"active_trade_supervisor_{MONITOR_IDENTIFIER}",
        "monitor_identifier": MONITOR_IDENTIFIER,
        "user_number": USER_NUMBER,
        "monitor_id": MONITOR_ID,
        "port": ACTIVE_TRADE_SUPERVISOR_PORT,
        "timestamp": datetime.now().isoformat(),
        "port_system": "centralized"
    }

# Active trades data endpoint (legacy - for backward compatibility)
@app.route("/api/active_trades")
def get_active_trades():
    """Get all active trades for frontend display with caching to prevent backend interference"""
    global active_trades_cache, active_trades_cache_time
    
    try:
        current_time = time.time()
        
        # Check if auto-stop is enabled to determine caching behavior
        auto_stop_enabled = is_auto_stop_enabled()
        
        # If auto-stop is disabled, always return fresh data (no caching)
        if not auto_stop_enabled:
            active_trades = get_all_active_trades()
            return jsonify({
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "active_trades": active_trades,
                "count": len(active_trades),
                "cached": False,
                "auto_stop_enabled": False
            })
        
        # Auto-stop is enabled - use caching to protect critical functionality
        # Return cached data if it's still fresh
        if (active_trades_cache is not None and 
            current_time - active_trades_cache_time < CACHE_DURATION):
            return jsonify({
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "active_trades": active_trades_cache,
                "count": len(active_trades_cache),
                "cached": True,
                "auto_stop_enabled": True
            })
        
        # Fetch fresh data from database
        active_trades = get_all_active_trades()
        
        # Update cache
        active_trades_cache = active_trades
        active_trades_cache_time = current_time
        
        return jsonify({
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "active_trades": active_trades,
            "count": len(active_trades),
            "cached": False,
            "auto_stop_enabled": True
        })
    except Exception as e:
        log(f"❌ Error serving active trades: {e}")
        return jsonify({"error": str(e)}), 500

# Monitor-specific active trades data endpoint
@app.route("/api/active_trades/<monitor_identifier>")
def get_active_trades_for_monitor(monitor_identifier):
    """Get all active trades for a specific monitor"""
    try:
        # Validate monitor identifier format
        if not monitor_identifier or '_' not in monitor_identifier:
            return jsonify({"error": "Invalid monitor identifier format"}), 400
        
        # For now, we'll return the current monitor's data since each supervisor instance
        # only manages its own monitor's data. In the future, this could be enhanced
        # to support cross-monitor data access if needed.
        active_trades = get_all_active_trades()
        
        return jsonify({
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "active_trades": active_trades,
            "count": len(active_trades),
            "monitor_identifier": monitor_identifier,
            "current_monitor": MONITOR_IDENTIFIER
        })
    except Exception as e:
        log(f"❌ Error serving active trades for monitor {monitor_identifier}: {e}")
        return jsonify({"error": str(e)}), 500

# Port information endpoint
@app.route("/api/ports")
def get_ports():
    """Get port information for this service"""
    return {
        "service": f"active_trade_supervisor_{MONITOR_IDENTIFIER}",
        "monitor_identifier": MONITOR_IDENTIFIER,
        "port": ACTIVE_TRADE_SUPERVISOR_PORT,
        "host": get_host()
    }

# Automated trade close notification endpoint
@app.route("/api/notify_automated_close", methods=['POST'])
def notify_automated_close():
    """Notify the frontend that an automated trade close was triggered"""
    try:
        data = request.json
        log(f"[AUTO STOP] 🔔 Notifying frontend of automated trade close: {data}")
        
        # Forward the notification to the main app for WebSocket broadcast
        try:
            port = get_port("main_app")
            url = get_service_url(port) + "/api/notify_automated_close"
            response = requests.post(url, json=data, timeout=2)
            if response.ok:
                log(f"[AUTO STOP] ✅ Frontend notification sent successfully")
            else:
                log(f"[AUTO STOP] ⚠️ Frontend notification failed: {response.status_code}")
        except Exception as e:
            log(f"[AUTO STOP] ❌ Error sending frontend notification: {e}")
        
        return jsonify({"success": True, "message": "Automated trade close notification sent"})
    except Exception as e:
        log(f"[AUTO STOP] ❌ Error in notify_automated_close: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/sync_and_monitor", methods=['POST'])
def sync_and_monitor():
    """Manually trigger sync and monitoring for active trades"""
    try:
        log("🔄 Manual sync and monitor triggered")
        sync_on_demand()
        update_monitoring_on_demand()
        return {"status": "success", "message": "Sync and monitoring completed"}
    except Exception as e:
        log(f"❌ Error in manual sync and monitor: {e}")
        return {"status": "error", "message": str(e)}, 500

def log(message: str):
    """Log messages with timestamp"""
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[ACTIVE_TRADE_SUPERVISOR {timestamp}] {message}")

def get_momentum_percentile_from_postgresql(symbol="BTC"):
    """Get current momentum percentile directly from PostgreSQL for the specified symbol."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum_percentile FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return float(result[0])
        else:
            return None
    except Exception as e:
        log(f"[MOMENTUM SPIKE] Error getting momentum percentile from PostgreSQL: {e}")
        return None

def broadcast_active_trades_change():
    """Broadcast active trades change via WebSocket to main app"""
    try:
        # Get current active trades
        active_trades = get_all_active_trades()
        
        # Send to main app for WebSocket broadcast
        try:
            port = get_port("main_app")
            url = get_service_url(port) + "/api/broadcast_active_trades_change"
            response = requests.post(url, json={
                "active_trades": active_trades,
                "count": len(active_trades),
                "timestamp": datetime.now().isoformat()
            }, timeout=2)
            if response.ok:
                # Broadcast successful
                pass
            else:
                log(f"⚠️ Failed to broadcast active trades change: {response.status_code}")
        except Exception as e:
            log(f"❌ Error broadcasting active trades change: {e}")
            
    except Exception as e:
        log(f"❌ Error in broadcast_active_trades_change: {e}")

def check_for_open_trades():
    """
    Check trades.db for any OPEN trades and add them to active monitoring.
    """
    pass

def check_for_closed_trades():
    """
    Check if any active trades have been closed in trades.db.
    """
    pass

# HTTP endpoints for receiving notifications


@app.route('/api/trade_manager_notification', methods=['POST'])
def handle_trade_manager_notification():
    """Handle direct notifications from trade_manager about trade status changes"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data received"}), 400
        
        trade_id = data.get('trade_id')
        ticket_id = data.get('ticket_id')
        status = data.get('status')
        monitor_identifier = data.get('monitor_identifier')
        
        if not all([trade_id, ticket_id, status]):
            return jsonify({"error": "Missing required fields: trade_id, ticket_id, status"}), 400
        
        # Validate that this notification is for the correct monitor
        if monitor_identifier and monitor_identifier != MONITOR_IDENTIFIER:
            log(f"📡 DIRECT NOTIFICATION: Ignoring notification for different monitor")
            log(f"📡 DIRECT NOTIFICATION: Expected: {MONITOR_IDENTIFIER}, Received: {monitor_identifier}")
            return jsonify({
                "status": "ignored",
                "message": f"Notification for different monitor: {monitor_identifier}",
                "success": True
            }), 200
        
        log(f"📡 DIRECT NOTIFICATION: Received from trade_manager for monitor {MONITOR_IDENTIFIER}")
        log(f"📡 DIRECT NOTIFICATION: Trade ID: {trade_id}, Ticket ID: {ticket_id}, Status: {status}")
        
        success = False
        
        if status == 'pending':
            # Add new pending trade
            success = add_pending_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully added pending trade: {trade_id}")
            else:
                log(f"❌ Failed to add pending trade: {trade_id}")
                
        elif status == 'open':
            # Confirm pending trade as open
            success = confirm_pending_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully confirmed pending trade as open: {trade_id}")
            else:
                log(f"❌ Failed to confirm pending trade as open: {trade_id}")
                
        elif status == 'error':
            # Remove failed trade (any status) from active_trades.db
            success = remove_failed_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully removed failed trade: {trade_id}")
            else:
                log(f"❌ Failed to remove failed trade: {trade_id}")
                
        elif status == 'expired':
            # Remove expired trade from active_trades.db
            success = remove_closed_trade(trade_id)
            if success:
                log(f"✅ Successfully removed expired trade: {trade_id}")
            else:
                log(f"❌ Failed to remove expired trade: {trade_id}")
                
        elif status == 'closing':
            # Update trade status to closing
            success = update_trade_status_to_closing(trade_id)
            if success:
                log(f"✅ Successfully updated trade to closing status: {trade_id}")
            else:
                log(f"❌ Failed to update trade to closing status: {trade_id}")
                
        elif status == 'closed':
            # Remove closed trade from active_trades.db
            success = remove_closed_trade(trade_id)
            if success:
                log(f"✅ Successfully removed closed trade: {trade_id}")
            else:
                log(f"❌ Failed to remove closed trade: {trade_id}")
                
        elif status == 'close_failed':
            # Close order failed - revert to active and immediately retry close
            success = handle_close_failed_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully handled close_failed trade: {trade_id}")
            else:
                log(f"❌ Failed to handle close_failed trade: {trade_id}")
                
        elif status == 'deleted':
            # Remove deleted trade from active_trades.db (same as failed trade)
            success = remove_failed_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully removed deleted trade: {trade_id}")
            else:
                log(f"❌ Failed to remove deleted trade: {trade_id}")
                
        else:
            log(f"⚠️ Unknown status in trade_manager notification: {status}")
            return jsonify({"error": f"Unknown status: {status}"}), 400
        
        return jsonify({
            "status": "success" if success else "error",
            "message": f"Trade {trade_id} {status} notification processed",
            "success": success
        }), 200 if success else 500
        
    except Exception as e:
        log(f"❌ Error handling trade_manager notification: {e}")
        return jsonify({"error": str(e)}), 500

def migrate_database_schema():
    """Migrate the database schema if needed"""
    pass

def init_active_trades_db():
    """Initialize the active trades database"""
    pass

def get_db_connection():
    """Get database connection with appropriate timeout"""
    return get_postgresql_connection()

def get_trades_db_connection():
    """Get connection to the main trades database"""
    return get_postgresql_connection()

def get_postgresql_connection():
    """Get a connection to the PostgreSQL database"""
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

def add_new_active_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Add a new trade to the active trades database when trade_manager confirms it as open.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully added, False otherwise
    """
    try:
        # Get the trade data from PostgreSQL
        conn = get_trades_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, ticket_id, date, time, strike, side, buy_price, position,
                   contract, ticker, symbol, market, trade_strategy, symbol_open,
                   momentum, prob, fees, diff
            FROM users.trades_{USER_NUMBER} 
            WHERE id = %s AND status = 'open'
        """, (trade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            log(f"No open trade found with id {trade_id}")
            return False
            
        # Unpack the row data
        (db_id, ticket_id, date, time, strike, side, buy_price, position,
         contract, ticker, symbol, market, trade_strategy, symbol_open,
         momentum, prob, fees, diff) = row
        
        # Insert into active trades database
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            INSERT INTO users.{active_trades_table} (
                trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, market, trade_strategy, symbol_open,
                momentum, prob, fees, diff
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            trade_id, ticket_id, date, time, strike, side, buy_price, position,
            contract, ticker, symbol, market, trade_strategy, symbol_open,
            momentum, prob, fees, diff
        ))
        
        conn.commit()
        conn.close()
        
        # Log the new open trade with detailed information
        log(f"🆕 NEW OPEN TRADE ADDED TO ACTIVE_TRADES.DB")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   Ticker: {ticker}")
        log(f"   Strike: {strike}")
        log(f"   Side: {side}")
        log(f"   Buy Price: ${buy_price}")
        log(f"   Position: {position}")
        log(f"   Contract: {contract}")
        log(f"   Strategy: {trade_strategy}")
        log(f"   Entry Time: {date} {time}")
        log(f"   Prob: {prob}%")
        log(f"   Diff: {diff}")
        log(f"   Fees: ${fees}")
        log(f"   Symbol Open: ${symbol_open}")
        log(f"   Momentum: {momentum}")

        log(f"   Market: {market}")
        log(f"   Symbol: {symbol}")
        log(f"   ========================================")
        
        # Invalidate cache when new trade is added
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        # Start monitoring loop if this is the first active trade
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE status = 'active'")
        active_count = cursor.fetchone()[0]
        conn.close()
        
        if active_count == 1:  # This is the first active trade
            start_monitoring_loop()
        
        return True
        
    except Exception as e:
        log(f"❌ Error adding new active trade {trade_id}: {e}")
        return False

def add_pending_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Add a new pending trade to the active trades database when trade_manager creates it.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully added, False otherwise
    """
    try:
        # Get the trade data from trades.db
        conn = get_trades_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, ticket_id, date, time, strike, side, buy_price, position,
                   contract, ticker, symbol, market, trade_strategy, symbol_open,
                   momentum, prob, fees, diff
            FROM users.trades_{USER_NUMBER} 
            WHERE id = %s AND status = 'pending'
        """, (trade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            log(f"No pending trade found with id {trade_id}")
            return False
            
        # Unpack the row data
        (db_id, ticket_id, date, time, strike, side, buy_price, position,
         contract, ticker, symbol, market, trade_strategy, symbol_open,
         momentum, prob, fees, diff) = row
        
        # Insert into active trades database with 'pending' status
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            INSERT INTO users.{active_trades_table} (
                trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, market, trade_strategy, symbol_open,
                momentum, prob, fees, diff, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        """, (
            trade_id, ticket_id, date, time, strike, side, buy_price, position,
            contract, ticker, symbol, market, trade_strategy, symbol_open,
            momentum, prob, fees, diff
        ))
        
        conn.commit()
        conn.close()
        
        # Log the new pending trade
        log(f"⏳ NEW PENDING TRADE ADDED TO ACTIVE_TRADES.DB")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   Ticker: {ticker}")
        log(f"   Strike: {strike}")
        log(f"   Side: {side}")
        log(f"   Contract: {contract}")
        log(f"   Strategy: {trade_strategy}")
        log(f"   Entry Time: {date} {time}")
        log(f"   Prob: {prob}%")
        log(f"   Market: {market}")
        log(f"   Symbol: {symbol}")
        log(f"   ========================================")
        
        # Invalidate cache when new trade is added
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        # Start monitoring loop if this is the first active trade
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE status = 'active'")
        active_count = cursor.fetchone()[0]
        conn.close()
        
        if active_count == 1:  # This is the first active trade
            start_monitoring_loop()
        
        return True
        
    except Exception as e:
        log(f"❌ Error adding pending trade {trade_id}: {e}")
        return False

def confirm_pending_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Confirm a pending trade has been filled and update it to 'active' status.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully confirmed, False otherwise
    """
    try:
        # Get the updated trade data from PostgreSQL
        conn = get_trades_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, ticket_id, date, time, strike, side, buy_price, position,
                   contract, ticker, symbol, market, trade_strategy, symbol_open,
                   momentum, prob, fees, diff
            FROM users.trades_{USER_NUMBER} 
            WHERE id = %s AND status = 'open'
        """, (trade_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            log(f"No open trade found with id {trade_id}")
            return False
            
        # Unpack the row data
        (db_id, ticket_id, date, time, strike, side, buy_price, position,
         contract, ticker, symbol, market, trade_strategy, symbol_open,
         momentum, prob, fees, diff) = row
        
        # Update the pending trade in active_trades.db to 'active' status
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            UPDATE users.{active_trades_table}
            SET status = 'active',
                buy_price = %s,
                position = %s,
                fees = %s,
                diff = %s
            WHERE trade_id = %s AND status = 'pending'
        """, (buy_price, position, fees, diff, trade_id))
        
        if cursor.rowcount == 0:
            log(f"No pending trade found in active_trades.db for trade_id {trade_id}")
            conn.close()
            return False
        
        conn.commit()
        conn.close()
        
        # Log the confirmed trade
        log(f"✅ PENDING TRADE CONFIRMED AND ACTIVATED")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   Ticker: {ticker}")
        log(f"   Strike: {strike}")
        log(f"   Side: {side}")
        log(f"   Buy Price: ${buy_price}")
        log(f"   Position: {position}")
        log(f"   Contract: {contract}")
        log(f"   Strategy: {trade_strategy}")
        log(f"   Entry Time: {date} {time}")
        log(f"   Prob: {prob}%")
        log(f"   Diff: {diff}")
        log(f"   Fees: ${fees}")
        log(f"   Symbol Open: ${symbol_open}")
        log(f"   Momentum: {momentum}")
        log(f"   Market: {market}")
        log(f"   Symbol: {symbol}")
        log(f"   ========================================")
        
        # Invalidate cache when trade is confirmed
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        # Start monitoring loop if this is the first active trade
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM users.active_trades_{USER_NUMBER}_{MONITOR_ID} WHERE status = 'active'")
        active_count = cursor.fetchone()[0]
        conn.close()
        
        if active_count == 1:  # This is the first active trade
            start_monitoring_loop()
        
        return True
        
    except Exception as e:
        log(f"❌ Error confirming pending trade {trade_id}: {e}")
        return False

def remove_pending_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Remove a pending trade that failed to fill from active_trades.db.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully removed, False otherwise
    """
    try:
        # Remove the pending trade from active_trades.db
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            DELETE FROM users.{active_trades_table}
            WHERE trade_id = %s AND status = 'pending'
        """, (trade_id,))
        
        if cursor.rowcount == 0:
            log(f"No pending trade found in active_trades.db for trade_id {trade_id}")
            conn.close()
            return False
        
        conn.commit()
        conn.close()
        
        # Log the removed pending trade
        log(f"❌ PENDING TRADE REMOVED (NO FILL)")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   ========================================")
        
        # Invalidate cache when trade is removed
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        return True
        
    except Exception as e:
        log(f"❌ Error removing pending trade {trade_id}: {e}")
        return False

def remove_failed_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Remove a trade that failed (got error status) from active_trades.db.
    
    Args:
        trade_id: The ID from trades.db
        ticket_id: The ticket ID for the trade
        
    Returns:
        bool: True if successfully removed, False otherwise
    """
    try:
        # Remove the failed trade from active_trades.db (any status)
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            DELETE FROM users.{active_trades_table}
            WHERE trade_id = %s
        """, (trade_id,))
        
        if cursor.rowcount == 0:
            log(f"No trade found in active_trades.db for trade_id {trade_id}")
            conn.close()
            return False
        
        conn.commit()
        conn.close()
        
        # Log the removed failed trade
        log(f"❌ FAILED TRADE REMOVED (ERROR STATUS)")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticket ID: {ticket_id}")
        log(f"   ========================================")
        
        # Invalidate cache when trade is removed
        invalidate_active_trades_cache()
        
        # Broadcast active trades change
        broadcast_active_trades_change()
        
        return True
        
    except Exception as e:
        log(f"❌ Error removing failed trade {trade_id}: {e}")
        return False

def remove_closed_trade(trade_id: int) -> bool:
    """
    Remove a trade from active trades when it's closed.
    
    Args:
        trade_id: The ID from trades.db
        
    Returns:
        bool: True if successfully removed, False otherwise
    """
    try:
        # Check if trade exists before trying to remove it
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE trade_id = %s", (trade_id,))
        exists = cursor.fetchone()[0] > 0
        conn.close()
        
        if not exists:
            # Trade doesn't exist, no need to log this as an error
            return True  # Consider this a successful "no-op"
        
        # Remove the trade
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM users.{active_trades_table} WHERE trade_id = %s", (trade_id,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            log(f"🔚 CLOSED TRADE REMOVED FROM ACTIVE_TRADES.DB")
            log(f"   Trade ID: {trade_id}")
            log(f"   ========================================")
            
            # Invalidate cache when trade is removed
            invalidate_active_trades_cache()
            
            # Broadcast active trades change
            broadcast_active_trades_change()
            
            return True
        else:
            log(f"⚠️ No active trade found to remove: id={trade_id}")
            return False
            
    except Exception as e:
        log(f"❌ Error removing closed trade {trade_id}: {e}")
        return False

def update_trade_status_to_closing(trade_id: int) -> bool:
    """
    Update a trade's status to 'closing' in active_trades.db.
    
    Args:
        trade_id: The ID from trades.db
        
    Returns:
        bool: True if successfully updated, False otherwise
    """
    try:
        # Check if trade exists in active_trades.db
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE trade_id = %s", (trade_id,))
        exists = cursor.fetchone()[0] > 0
        conn.close()
        
        if not exists:
            log(f"⚠️ No active trade found to update status: id={trade_id}")
            return False
        
        # Update the trade status to 'closing'
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"UPDATE users.{active_trades_table} SET status = 'closing' WHERE trade_id = %s", (trade_id,))
        updated_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if updated_count > 0:
            log(f"🔄 TRADE STATUS UPDATED TO CLOSING IN ACTIVE_TRADES.DB")
            log(f"   Trade ID: {trade_id}")
            log(f"   ========================================")
            
            # Invalidate cache when trade status changes
            invalidate_active_trades_cache()
            
            # Broadcast active trades change immediately for status change
            broadcast_active_trades_change()
            
            return True
        else:
            log(f"⚠️ No active trade found to update status: id={trade_id}")
            return False
            
    except Exception as e:
        log(f"❌ Error updating trade status to closing {trade_id}: {e}")
        return False

def get_current_symbol_price(symbol: str = None) -> Optional[float]:
    """Get the current price for the specified symbol from the PostgreSQL live_data schema"""
    try:
        # Use current monitor symbol if no symbol specified
        if symbol is None:
            symbol = get_current_monitor_symbol()
        
        # Get PostgreSQL connection
        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL")
            return None
            
        cursor = conn.cursor()
        
        # Map symbol to the appropriate price log table
        table_name = f"live_data.live_price_log_1s_{symbol.lower()}"
            
        cursor.execute(f"SELECT price FROM {table_name} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            price = float(result[0])
            # Only log price every 30 seconds to reduce noise
            current_time = time.time()
            if not hasattr(get_current_symbol_price, 'last_log_time') or current_time - get_current_symbol_price.last_log_time > 30:
                # Only log price occasionally to reduce noise
                get_current_symbol_price.last_log_time = current_time
            return price
        else:
            log(f"⚠️ No {symbol} price found in PostgreSQL database")
            return None
            
    except Exception as e:
        log(f"Error getting current {symbol} price: {e}")
        return None

def get_kalshi_market_snapshot(symbol: str = None) -> Optional[Dict[str, Any]]:
    """Get the latest Kalshi market snapshot data from PostgreSQL"""
    try:
        # Use current monitor symbol if no symbol specified
        if symbol is None:
            symbol = get_current_monitor_symbol()
            
        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL")
            return None
            
        cursor = conn.cursor()
        
        # Get market data from PostgreSQL
        cursor.execute(f"""
            SELECT 
                market_ticker,
                yes_ask,
                no_ask,
                volume,
                event_ticker,
                strike
            FROM live_data.market_kalshi_{symbol.lower()}
            ORDER BY updated_at DESC
        """)
        
        markets_data = cursor.fetchall()
        conn.close()
        
        if not markets_data:
            log("⚠️ No Kalshi market data found in PostgreSQL")
            return None
        
        # Convert to the same format as the JSON file
        markets = []
        for row in markets_data:
            market = {
                "ticker": row[0],  # market_ticker
                "yes_ask": row[1],
                "no_ask": row[2],
                "volume": row[3],
                "event_ticker": row[4],
                "strike": row[5]
            }
            markets.append(market)
        
        # Return in the same format as the JSON file
        return {
            "markets": markets,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        log(f"Error reading Kalshi market snapshot from PostgreSQL: {e}")
        return None

def get_current_closing_price_for_trade(trade_ticker: str, trade_side: str) -> Optional[float]:
    """
    Get the current closing price for a specific trade from Kalshi market snapshot.
    
    Args:
        trade_ticker: The ticker of the trade (e.g., "KXBTCD-25JUL1617-T119499.99" or "KXETHD-25JUL1617-T119499.99")
        trade_side: The side of the trade ("Y" for YES, "N" for NO)
        
    Returns:
        The closing price as a decimal (e.g., 0.94 for 94 cents), or None if not found
    """
    try:
        snapshot_data = get_kalshi_market_snapshot()
        if not snapshot_data or "markets" not in snapshot_data:
            return None
            
        markets = snapshot_data["markets"]
        
        # Find the market that matches the trade ticker
        for market in markets:
            if market.get("ticker") == trade_ticker:
                # For YES trades, we want the NO_ASK (opposite side)
                # For NO trades, we want the YES_ASK (opposite side)
                if trade_side.upper() == "Y":  # YES trade
                    closing_price_cents = market.get("no_ask")
                elif trade_side.upper() == "N":  # NO trade
                    closing_price_cents = market.get("yes_ask")
                else:
                    log(f"⚠️ Unknown trade side: {trade_side}")
                    return None
                
                if closing_price_cents is not None:
                    # Convert from cents to decimal (e.g., 94 -> 0.94)
                    closing_price_decimal = closing_price_cents / 100.0
                    # Only log closing price data occasionally to reduce noise
                    return closing_price_decimal
                else:
                    log(f"⚠️ No closing price found for {trade_ticker} ({trade_side})")
                    return None
        
        log(f"⚠️ Market not found for ticker: {trade_ticker}")
        return None
        
    except Exception as e:
        log(f"Error getting closing price for trade {trade_ticker}: {e}")
        return None

def get_current_probability(strike: float, current_price: float, ttc_seconds: float, momentum_score: Optional[float] = None, symbol: str = None) -> Optional[float]:
    """
    Get the probability for a strike from the PostgreSQL strike table.
    Fallback to the old API if PostgreSQL data is not available.
    """
    try:
        # Use current monitor symbol if no symbol specified
        if symbol is None:
            symbol = get_current_monitor_symbol()
            
        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL for probability lookup")
            return None
            
        cursor = conn.cursor()
        
        # Get probability from PostgreSQL strike table
        cursor.execute(f"""
            SELECT probability 
            FROM live_data.strike_table_{symbol.lower()} 
            WHERE strike = %s
            ORDER BY timestamp DESC 
            LIMIT 1
        """, (strike,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return float(result[0])
        else:
            log(f"⚠️ No probability found in PostgreSQL for strike {strike}")
            
    except Exception as e:
        log(f"⚠️ Probability PostgreSQL exception: {e}")
    
    # Fallback to old API if PostgreSQL fails
    try:
        host = get_host()
        port = get_port("main_app")
        url = f"http://{host}:{port}/api/strike_probabilities"
        payload = {
            "current_price": current_price,
            "ttc_seconds": ttc_seconds,
            "strikes": [strike],
        }
        if momentum_score is not None:
            payload["momentum_score"] = momentum_score
        resp = requests.post(url, json=payload, timeout=1.5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "ok" and data.get("probabilities"):
                return data["probabilities"][0]["prob_within"]
        log(f"⚠️ Probability API error: {resp.status_code} {resp.text}")
    except Exception as e:
        log(f"⚠️ Probability API exception: {e}")
    return None

def update_active_trade_monitoring_data():
    """
    Update monitoring data for all active trades:
    - Current symbol price (live symbol price)
    - Current market ask prices from Kalshi snapshot
    - Buffer from strike (absolute value, negative when crossed)
    - Time since entry
    - Current probability (from probability API)
    """
    try:
        # Get current symbol price for each trade
        # Note: We'll get the price per trade since each trade might have a different symbol
        
        # Get Kalshi market snapshot
        snapshot_data = get_kalshi_market_snapshot()
        if not snapshot_data or "markets" not in snapshot_data:
            log("⚠️ Could not get Kalshi market snapshot, skipping monitoring update")
            return
        
        # Get all active trades
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            SELECT id, trade_id, buy_price, prob, time, date, strike, side, momentum, ticker, symbol
            FROM users.{active_trades_table} 
            WHERE status = 'active'
        """)
        active_trades = cursor.fetchall()
        conn.close()
        
        if not active_trades:
            return
        
        for (active_id, trade_id, buy_price, prob, time_str, date_str, strike, side, momentum, ticker, symbol) in active_trades:
            try:
                # Parse strike price - handle currency formatting
                strike_clean = str(strike).replace('$', '').replace(',', '')
                strike_price = float(strike_clean)
                
                # Get current symbol price for this specific trade
                current_symbol_price = get_current_symbol_price(symbol)
                if current_symbol_price is None:
                    log(f"⚠️ Could not get current {symbol} price for trade {trade_id}, skipping")
                    continue
                
                # Get current market ask price for this specific contract
                current_market_price = get_current_closing_price_for_trade(ticker, side)
                if current_market_price is None:
                    log(f"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping")
                    continue
                
                # Calculate buffer using the actual symbol price difference from strike
                # Buffer = current_symbol_price - strike_price
                # For YES trades: positive buffer when symbol > strike (safe), negative when symbol < strike (dangerous)
                # For NO trades: positive buffer when symbol < strike (safe), negative when symbol > strike (dangerous)
                raw_buffer = current_symbol_price - strike_price
                
                if side.upper() == 'Y':  # YES trade
                    # For YES trades, positive buffer when symbol > strike (safe)
                    buffer_from_strike = raw_buffer
                else:  # NO trade
                    # For NO trades, positive buffer when symbol < strike (safe)
                    # So we need to flip the sign
                    buffer_from_strike = -raw_buffer
                
                # Calculate time since entry
                try:
                    if hasattr(date_str, 'year') and hasattr(time_str, 'hour'):
                        # Handle new date/time objects
                        entry_datetime = datetime.combine(date_str, time_str)
                    else:
                        # Handle legacy text format
                        entry_datetime = datetime.strptime(f"{str(date_str)} {str(time_str)}", "%Y-%m-%d %H:%M:%S")
                    entry_datetime = entry_datetime.replace(tzinfo=ZoneInfo("America/New_York"))
                except Exception as e:
                    log(f"Error calculating entry_datetime for trade {trade_id}: {e}, date_str: {date_str}, time_str: {time_str}")
                    # Use current time as fallback
                    entry_datetime = datetime.now(ZoneInfo("America/New_York"))
                now = datetime.now(ZoneInfo("America/New_York"))
                time_since_entry = int((now - entry_datetime).total_seconds())
                
                # Get unified TTC from master strike table
                ttc_seconds = get_unified_ttc_seconds(symbol)
                
                # Get momentum score if available
                momentum_score = float(momentum) if momentum is not None else None
                
                # Get current probability from API using the current symbol price
                current_probability = get_current_probability(strike_price, current_symbol_price, ttc_seconds, momentum_score, symbol)
                
                # Apply probability logic based on buffer
                # When buffer is positive: use probability as-is (direct passthrough)
                # When buffer is negative: subtract probability from 100
                if current_probability is not None:
                    if buffer_from_strike < 0:
                        # Negative buffer: subtract probability from 100
                        current_probability = 100 - current_probability
                
                # Calculate PnL: 1 - current_close_price - buy_price
                # For YES trades: PnL = 1 - current_close_price - buy_price
                # For NO trades: PnL = 1 - current_close_price - buy_price (same formula)
                # Convert buy_price to float if it's a Decimal
                buy_price_float = float(buy_price) if hasattr(buy_price, '__float__') else buy_price
                pnl = 1 - current_market_price - buy_price_float
                pnl_formatted = f"{pnl:.2f}"  # Format as "0.15" or "-0.08"
                
                # Update the monitoring data
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(f"""
                    UPDATE users.{active_trades_table} 
                    SET current_symbol_price = %s, 
                        current_probability = %s,
                        buffer_from_entry = %s,
                        time_since_entry = %s,
                        current_close_price = %s,
                        current_pnl = %s,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (current_symbol_price, current_probability, buffer_from_strike, time_since_entry, current_market_price, pnl_formatted, active_id))
                conn.commit()
                conn.close()
                
                # Invalidate cache when trade data is updated
                invalidate_active_trades_cache()
                
                # Broadcast active trades change to frontend (throttled for performance - status changes are broadcast immediately)
                if time_since_entry % 1 == 0:  # Broadcast every 1 second to match monitoring frequency
                    broadcast_active_trades_change()
                
                # Only log significant updates (every 60 seconds) to reduce noise
                if time_since_entry % 60 == 0:
                    log(f"📊 MONITORING: Updated trade {trade_id} - {symbol}_price: {current_symbol_price}, market_price: {current_market_price}, buffer: {buffer_from_strike}, prob: {current_probability}, pnl: {pnl_formatted}")
                
            except Exception as e:
                log(f"Error updating monitoring data for trade {trade_id}: {e}")
                
    except Exception as e:
        log(f"Error in update_active_trade_monitoring_data: {e}")

def check_monitoring_failsafe():
    """
    Simple failsafe: Check if monitoring should be running and restart if needed.
    This runs periodically to catch any monitoring loop failures.
    """
    global monitoring_thread
    
    try:
        # Check if there are active trades
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE status = 'active'")
        active_count = cursor.fetchone()[0]
        conn.close()
        
        # If there are active trades but no monitoring thread, restart it
        if active_count > 0:
            with monitoring_thread_lock:
                if monitoring_thread is None or not monitoring_thread.is_alive():
                    log(f"🔄 FAILSAFE: Found {active_count} active trades but monitoring not running, restarting...")
                    start_monitoring_loop()
        
    except Exception as e:
        log(f"❌ Error in monitoring failsafe check: {e}")

def start_monitoring_loop():
    """
    Start monitoring loop when there are active trades.
    This should be called when trades are added to active_trades.
    """
    global monitoring_thread
    
    # Check if monitoring thread is already running
    with monitoring_thread_lock:
        if monitoring_thread is not None and monitoring_thread.is_alive():
            log("📊 MONITORING: Monitoring thread already running, skipping")
            return
    
    def monitoring_worker():
        global monitoring_thread
        log("📊 MONITORING: Starting monitoring loop for active trades")
        auto_stop_triggered_trades = set()
        verification_pending_trades = {}  # trade_id -> (trigger_time, verification_end_time)
        log("🔄 AUTO STOP: Reset auto-stop triggered trades set (clearing any failed attempts)")
        
        try:
            while True:
                # Check if there are still active trades
                conn = get_db_connection()
                cursor = conn.cursor()
                active_trades_table = get_monitor_active_trades_table()
                cursor.execute(f"SELECT * FROM users.{active_trades_table} WHERE status = 'active'")
                columns = [desc[0] for desc in cursor.description]
                active_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
                conn.close()
                
                if not active_trades:
                    log("📊 MONITORING: No more active trades, stopping monitoring loop")
                    break
                
                # Update monitoring data
                update_active_trade_monitoring_data()
                
                # Log monitoring status every 60 seconds
                current_time = time.time()
                if not hasattr(monitoring_worker, 'last_status_log') or current_time - monitoring_worker.last_status_log > 60:
                    log(f"📊 MONITORING: Checking {len(active_trades)} active trades")
                    monitoring_worker.last_status_log = current_time
                
                # Add heartbeat log every 30 seconds to track monitoring health
                if not hasattr(monitoring_worker, 'last_heartbeat') or current_time - monitoring_worker.last_heartbeat > 30:
                    log(f"💓 MONITORING HEARTBEAT: Monitoring loop healthy, {len(active_trades)} active trades")
                    monitoring_worker.last_heartbeat = current_time
                
                # Run failsafe check every 60 seconds
                if not hasattr(monitoring_worker, 'last_failsafe_check') or current_time - monitoring_worker.last_failsafe_check > 60:
                    check_monitoring_failsafe()
                    monitoring_worker.last_failsafe_check = current_time
                
                # === AUTO STOP LOGIC ===
                auto_stop_enabled = is_auto_stop_enabled()
                if auto_stop_enabled:
                    threshold = get_auto_stop_threshold()
                    min_ttc_seconds = get_min_ttc_seconds()
                    verification_enabled = get_verification_period_enabled()
                    verification_seconds = get_verification_period_seconds()
                    current_time = time.time()
                    
                    for trade in active_trades:
                        prob = trade.get('current_probability')
                        trade_id = trade.get('trade_id')
                        ttc_seconds = get_unified_ttc_seconds()
                        
                        # Check if trade is in verification period
                        if trade_id in verification_pending_trades:
                            trigger_time, verification_end_time = verification_pending_trades[trade_id]
                            
                            # Check if verification period has ended
                            if current_time >= verification_end_time:
                                # Verification period ended - check if conditions still met
                                if (
                                    prob is not None and
                                    (isinstance(prob, (int, float)) or hasattr(prob, '__float__')) and
                                    float(prob) < threshold and
                                    trade.get('status') == 'active'
                                ):
                                    # Conditions still met after verification - trigger auto-stop
                                    log(f"[AUTO STOP] ✅ Verification period ended - triggering auto stop for trade {trade_id} (prob={prob}, verification_duration={verification_seconds}s)")
                                    if trigger_auto_stop_close(trade):
                                        auto_stop_triggered_trades.add(trade_id)
                                        del verification_pending_trades[trade_id]
                                    else:
                                        log(f"[AUTO STOP] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                                        del verification_pending_trades[trade_id]
                                else:
                                    # Conditions no longer met - cancel verification
                                    log(f"[AUTO STOP] ❌ Verification period ended - conditions no longer met for trade {trade_id} (prob={prob}, threshold={threshold})")
                                    del verification_pending_trades[trade_id]
                            else:
                                # Still in verification period - just wait, don't check conditions during wait
                                remaining_time = verification_end_time - current_time
                                if not hasattr(monitoring_worker, 'last_verification_log') or current_time - monitoring_worker.last_verification_log > 10:
                                    log(f"[AUTO STOP] ⏳ Trade {trade_id} in verification period - {remaining_time:.1f}s remaining")
                                    monitoring_worker.last_verification_log = current_time
                                continue
                        
                        # Check for new auto-stop conditions
                        # Debug logging for trade 2448
                        if trade_id == 2448:
                            log(f"[AUTO STOP DEBUG] Trade 2448 - prob: {prob}, threshold: {threshold}, status: {trade.get('status')}, in_triggered: {trade_id in auto_stop_triggered_trades}, ttc: {ttc_seconds}, min_ttc: {min_ttc_seconds}")
                        
                        # Debug logging for trade 2448
                        if trade_id == 2448:
                            log(f"[AUTO STOP DEBUG] Trade 2448 conditions - prob_valid: {prob is not None}, prob_type: {type(prob)}, prob_lt_threshold: {float(prob) < threshold if prob is not None else 'N/A'}, status_active: {trade.get('status') == 'active'}, not_triggered: {trade_id not in auto_stop_triggered_trades}, ttc_valid: {ttc_seconds is not None}, ttc_ge_min: {ttc_seconds >= min_ttc_seconds if ttc_seconds is not None else 'N/A'}")
                        
                        auto_stop_conditions_met = (
                            prob is not None and
                            (isinstance(prob, (int, float)) or hasattr(prob, '__float__')) and
                            float(prob) < threshold and
                            trade.get('status') == 'active' and
                            trade_id not in auto_stop_triggered_trades and
                            ttc_seconds is not None and
                            ttc_seconds >= min_ttc_seconds # Respect min_ttc_seconds setting
                        )
                        
                        # Debug logging for trade 2448
                        if trade_id == 2448:
                            log(f"[AUTO STOP DEBUG] Trade 2448 - auto_stop_conditions_met: {auto_stop_conditions_met}")
                        
                        if auto_stop_conditions_met:
                            # Debug logging for trade 2448
                            if trade_id == 2448:
                                log(f"[AUTO STOP DEBUG] Trade 2448 - verification_enabled: {verification_enabled}")
                            
                            if verification_enabled:
                                # Start verification period
                                verification_end_time = current_time + verification_seconds
                                verification_pending_trades[trade_id] = (current_time, verification_end_time)
                                log(f"[AUTO STOP] 🔍 Starting verification period for trade {trade_id} (prob={prob}, threshold={threshold}, verification_duration={verification_seconds}s)")
                            else:
                                # No verification - trigger immediately
                                log(f"[AUTO STOP] Triggering auto stop for trade {trade_id} (prob={prob}, ttc={ttc_seconds}s, min_ttc={min_ttc_seconds}s)")
                                if trigger_auto_stop_close(trade):
                                    auto_stop_triggered_trades.add(trade_id)
                                else:
                                    log(f"[AUTO STOP] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
                        elif (
                            prob is not None and
                            (isinstance(prob, (int, float)) or hasattr(prob, '__float__')) and
                            float(prob) < threshold and
                            trade.get('status') == 'active' and
                            trade_id not in auto_stop_triggered_trades and
                            (ttc_seconds is None or ttc_seconds < min_ttc_seconds)
                        ):
                            log(f"[AUTO STOP] Skipping auto stop for trade {trade_id} - TTC ({ttc_seconds}s) below minimum ({min_ttc_seconds}s)")
                
                # === MOMENTUM SPIKE AUTO-STOPOUT LOGIC ===
                # Get momentum spike settings from monitor's assigned strategy
                try:
                    import psycopg2
                    conn = psycopg2.connect(
                        host="localhost",
                        database="rec_io_db",
                        user="rec_io_user",
                        password="rec_io_password"
                    )
                    with conn.cursor() as cursor:
                        # First get the strategy name for this monitor
                        cursor.execute(f"""
                            SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
                        """, (MONITOR_ID,))
                        monitor_result = cursor.fetchone()
                        
                        if monitor_result and monitor_result[0]:
                            strategy_name = monitor_result[0]
                            
                            # Get momentum spike settings from the monitor
                            cursor.execute("""
                                SELECT momentum_spike_enabled, momentum_spike_threshold
                                FROM users.monitor_list_0001 WHERE id = %s
                            """, (MONITOR_ID,))
                            result = cursor.fetchone()
                            
                            if result:
                                momentum_spike_enabled = result[0]
                                momentum_spike_threshold = result[1]  # Use percentage directly
                            else:
                                momentum_spike_enabled = True
                                momentum_spike_threshold = 35  # Use percentage directly
                                log(f"[MOMENTUM SPIKE] ⚠️ No strategy found: {strategy_name}, using defaults")
                        else:
                            momentum_spike_enabled = True
                            momentum_spike_threshold = 35 / 100.0  # Convert percentage to decimal
                            log(f"[MOMENTUM SPIKE] ⚠️ No strategy assigned to monitor {MONITOR_ID}, using defaults")
                    
                    conn.close()
                    
                    # Only proceed if momentum spike is enabled
                    if momentum_spike_enabled:
                        # Get current momentum percentile directly from PostgreSQL
                        current_momentum = get_momentum_percentile_from_postgresql("BTC")
                        
                        if current_momentum is not None:
                            # Check for momentum spike conditions
                            momentum_spike_triggered = False
                            
                            if current_momentum >= momentum_spike_threshold:  # Positive spike - close all NO trades
                                log(f"[MOMENTUM SPIKE] 🚨 POSITIVE SPIKE DETECTED: {current_momentum:.2f} >= +{momentum_spike_threshold}")
                                log(f"[MOMENTUM SPIKE] Closing all NO trades due to positive momentum spike")
                                
                                for trade in active_trades:
                                    if (trade.get('status') == 'active' and 
                                        trade.get('side', '').upper() in ['N', 'NO'] and
                                        trade.get('trade_id') not in auto_stop_triggered_trades):
                                        
                                        trade_id = trade.get('trade_id')
                                        log(f"[MOMENTUM SPIKE] Triggering close for NO trade {trade_id} (momentum: {current_momentum:.2f})")
                                        
                                        # Cancel any pending verification period for this trade
                                        if trade_id in verification_pending_trades:
                                            log(f"[MOMENTUM SPIKE] Cancelling verification period for trade {trade_id} due to momentum spike")
                                            del verification_pending_trades[trade_id]
                                        
                                        if trigger_auto_stop_close(trade):
                                            auto_stop_triggered_trades.add(trade_id)
                                            momentum_spike_triggered = True
                                        else:
                                            log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
                                
                                if momentum_spike_triggered:
                                    log(f"[MOMENTUM SPIKE] ✅ Closed {len([t for t in active_trades if t.get('side', '').upper() in ['N', 'NO'] and t.get('status') == 'active'])} NO trades due to positive momentum spike")
                                    
                            elif current_momentum <= -momentum_spike_threshold:  # Negative spike - close all YES trades
                                log(f"[MOMENTUM SPIKE] 🚨 NEGATIVE SPIKE DETECTED: {current_momentum:.2f} <= -{momentum_spike_threshold}")
                                log(f"[MOMENTUM SPIKE] Closing all YES trades due to negative momentum spike")
                                
                                for trade in active_trades:
                                    if (trade.get('status') == 'active' and 
                                        trade.get('side', '').upper() in ['Y', 'YES'] and
                                        trade.get('trade_id') not in auto_stop_triggered_trades):
                                        
                                        trade_id = trade.get('trade_id')
                                        log(f"[MOMENTUM SPIKE] Triggering close for YES trade {trade_id} (momentum: {current_momentum:.2f})")
                                        
                                        # Cancel any pending verification period for this trade
                                        if trade_id in verification_pending_trades:
                                            log(f"[MOMENTUM SPIKE] Cancelling verification period for trade {trade_id} due to momentum spike")
                                            del verification_pending_trades[trade_id]
                                        
                                        if trigger_auto_stop_close(trade):
                                            auto_stop_triggered_trades.add(trade_id)
                                            momentum_spike_triggered = True
                                        else:
                                            log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
                                
                                if momentum_spike_triggered:
                                    log(f"[MOMENTUM SPIKE] ✅ Closed {len([t for t in active_trades if t.get('side', '').upper() in ['Y', 'YES'] and t.get('status') == 'active'])} YES trades due to negative momentum spike")
                                
                                # Log momentum monitoring (every 30 seconds to reduce noise)
                                if not hasattr(monitoring_worker, 'last_momentum_log') or current_time - monitoring_worker.last_momentum_log > 30:
                                    log(f"[MOMENTUM SPIKE] Monitoring momentum: {current_momentum:.2f} (threshold: ±{momentum_spike_threshold})")
                                    monitoring_worker.last_momentum_log = current_time
                                    
                except Exception as e:
                    log(f"[MOMENTUM SPIKE] Error in momentum spike logic: {e}")
                
                # Sleep for 1 second
                time.sleep(1)
        
        except Exception as e:
            log(f"🚨 CRITICAL: Monitoring loop crashed with error: {e}")
            log(f"🚨 CRITICAL: Stack trace: {e.__class__.__name__}: {str(e)}")
            
            # Check if there are still active trades that need monitoring
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM users.active_trades_{USER_NUMBER}_{MONITOR_ID} WHERE status = 'active'")
                active_count = cursor.fetchone()[0]
                conn.close()
                
                if active_count > 0:
                    log(f"🚨 CRITICAL: Monitoring loop crashed but {active_count} active trades still need monitoring!")
                    log("🔄 AUTO-RESTART: Attempting to restart monitoring loop in 5 seconds...")
                    
                    # Clear the thread reference so we can restart
                    with monitoring_thread_lock:
                        monitoring_thread = None
                    
                    # Wait 5 seconds then restart
                    time.sleep(5)
                    start_monitoring_loop()
                    return
                else:
                    log("📊 MONITORING: No active trades, monitoring loop can safely stop")
            except Exception as restart_error:
                log(f"🚨 CRITICAL: Failed to check for active trades during restart: {restart_error}")
                log(f"🚨 CRITICAL: Restart stack trace: {restart_error.__class__.__name__}: {str(restart_error)}")
        

        
        # Clear the global monitoring thread reference when done
        with monitoring_thread_lock:
            monitoring_thread = None
        log("📊 MONITORING: Monitoring thread finished")
    
    # Start monitoring in a separate thread
    with monitoring_thread_lock:
        monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
        monitoring_thread.start()
        log("📊 MONITORING: Monitoring thread started")

def update_monitoring_on_demand():
    """
    Update monitoring data on demand (called by other scripts when needed)
    """
    update_active_trade_monitoring_data()

def invalidate_active_trades_cache():
    """Invalidate the active trades cache to force fresh data on next request"""
    global active_trades_cache, active_trades_cache_time
    active_trades_cache = None
    active_trades_cache_time = 0



def get_all_active_trades() -> List[Dict[str, Any]]:
    """Get all currently active, pending, and closing trades"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            SELECT * FROM users.{active_trades_table} WHERE status IN ('active', 'pending', 'closing')
        """)
        
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        
        result = []
        for row in rows:
            trade_dict = dict(zip(columns, row))
            # Convert any datetime objects to ISO strings and Decimal objects to float
            for key, value in trade_dict.items():
                if hasattr(value, 'isoformat'):
                    trade_dict[key] = value.isoformat()
                elif hasattr(value, '__float__'):  # Handle Decimal objects
                    trade_dict[key] = float(value)
            result.append(trade_dict)
        
        return result
        
    except Exception as e:
        log(f"Error getting active trades: {e}")
        return []

def sync_with_trades_db():
    """
    Sync active trades database with main trades.db to ensure consistency.
    This should be called on demand to catch any missed updates.
    """
    try:
        # Get all open trades from PostgreSQL
        conn = get_trades_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT id FROM users.trades_{USER_NUMBER} WHERE status = 'open' AND monitor = %s", (f"mon_{USER_NUMBER}_{MONITOR_ID}",))
        open_trade_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # Get all active trade IDs
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"SELECT trade_id FROM users.{active_trades_table} WHERE status = 'active'")
        active_trade_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # Find trades that should be active but aren't
        missing_trades = set(open_trade_ids) - set(active_trade_ids)
        for trade_id in missing_trades:
            log(f"🔄 SYNC: Found missing active trade: {trade_id}, adding...")
            add_new_active_trade(trade_id, "SYNC")  # Use "SYNC" as ticket_id for auto-added trades
        
        # Find trades that are active but should be closed
        closed_trades = set(active_trade_ids) - set(open_trade_ids)
        for trade_id in closed_trades:
            log(f"🔄 SYNC: Found closed trade still in active: {trade_id}, removing...")
            remove_closed_trade(trade_id)
            
        if missing_trades or closed_trades:
            log(f"Sync complete: added {len(missing_trades)}, removed {len(closed_trades)}")
        else:
            log("Sync complete: no changes needed")
            
    except Exception as e:
        log(f"Error in sync_with_trades_db: {e}")

def sync_on_demand():
    """
    Sync on demand (called by other scripts when needed)
    """
    sync_with_trades_db()

def start_event_driven_supervisor():
    """Start the event-driven active trade supervisor with HTTP server"""
    log("🚀 Starting event-driven active trade supervisor")
    log("📡 Waiting for trade notifications...")
    

    
    # Check if there are already active trades and start monitoring if needed
    conn = get_db_connection()
    cursor = conn.cursor()
    active_trades_table = get_monitor_active_trades_table()
    cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE status = 'active'")
    active_count = cursor.fetchone()[0]
    conn.close()
    
    if active_count > 0:
        log(f"📊 MONITORING: Found {active_count} existing active trades, starting monitoring")
        start_monitoring_loop()
    
    # Start HTTP server in a separate thread
    def start_http_server():
        try:
            host = "0.0.0.0"  # Listen on all interfaces for mobile access
            port = ACTIVE_TRADE_SUPERVISOR_PORT
            log(f"🌐 Starting HTTP server on {host}:{port}")
            app.run(host=host, port=port, debug=False, use_reloader=False)
        except Exception as e:
            log(f"❌ Error starting HTTP server: {e}")
    
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    # Keep the process alive with brute force failsafe
    try:
        while True:
            # BRUTE FORCE FAILSAFE: Check database every 10 seconds for active trades
            # If there are active trades but no monitoring thread, restart it
            conn = get_db_connection()
            cursor = conn.cursor()
            active_trades_table = get_monitor_active_trades_table()
            cursor.execute(f"SELECT COUNT(*) FROM users.{active_trades_table} WHERE status = 'active'")
            active_count = cursor.fetchone()[0]
            conn.close()
            
            # Check if monitoring thread is alive
            monitoring_thread_alive = False
            with monitoring_thread_lock:
                if monitoring_thread is not None and monitoring_thread.is_alive():
                    monitoring_thread_alive = True
            
            # If there are active trades but no monitoring thread, restart it
            if active_count > 0 and not monitoring_thread_alive:
                log(f"🚨 BRUTE FORCE FAILSAFE: Found {active_count} active trades but monitoring thread is dead!")
                log("🔄 BRUTE FORCE FAILSAFE: Restarting monitoring loop...")
                start_monitoring_loop()
            
            # Log failsafe status every 5 minutes (30 iterations)
            if not hasattr(start_event_driven_supervisor, 'failsafe_log_counter'):
                start_event_driven_supervisor.failsafe_log_counter = 0
            start_event_driven_supervisor.failsafe_log_counter += 1
            
            if start_event_driven_supervisor.failsafe_log_counter >= 30:  # Every 5 minutes
                log(f"🛡️ BRUTE FORCE FAILSAFE: Health check - {active_count} active trades, monitoring thread alive: {monitoring_thread_alive}")
                start_event_driven_supervisor.failsafe_log_counter = 0
            
            # Sleep for 10 seconds (much more frequent than the old 60 seconds)
            time.sleep(10)
            
            # Run existing failsafe check every 60 seconds (6 iterations)
            if not hasattr(start_event_driven_supervisor, 'failsafe_counter'):
                start_event_driven_supervisor.failsafe_counter = 0
            start_event_driven_supervisor.failsafe_counter += 1
            
            if start_event_driven_supervisor.failsafe_counter >= 6:  # Every 60 seconds
                check_monitoring_failsafe()
                start_event_driven_supervisor.failsafe_counter = 0
                
    except KeyboardInterrupt:
        log("🛑 Active trade supervisor stopped by user")
    except Exception as e:
        log(f"❌ Error in supervisor: {e}")

def is_auto_stop_enabled():
    """Check if AUTO STOP is enabled by checking auto_trade boolean in monitor_list"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db", 
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # Check auto_trade boolean from the specific monitor's row in monitor_list
            cursor.execute(f"SELECT auto_trade FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                auto_trade_enabled = result[0]
                return auto_trade_enabled
            else:
                log(f"[AUTO STOP] No monitor found with ID {MONITOR_ID} in monitor_list")
                return False
    except Exception as e:
        log(f"[AUTO STOP] Error reading auto_trade from monitor_list: {e}")
        return False

def trigger_auto_stop_close(trade):
    """Trigger a close for the given trade using the same payload as manual close."""
    """Returns True if close was successful, False otherwise."""
    import requests
    import random
    # Generate unique ticket ID
    ticket_id = f"TICKET-{{random.getrandbits(32):x}}-{{int(time.time() * 1000)}}"
    # Invert side
    side = trade['side']
    inverted_side = 'N' if side.upper() in ['Y', 'YES'] else 'Y' if side.upper() in ['N', 'NO'] else side
    # Use current market price for symbol_close and buy_price
    sell_price = trade.get('current_close_price')
    symbol_close = trade.get('current_symbol_price')
    if sell_price is None or symbol_close is None:
        log(f"[AUTO STOP] Skipping close for trade {trade['trade_id']} due to missing price data.")
        return False
    
    # Convert Decimal objects to float for JSON serialization
    sell_price_float = float(sell_price) if hasattr(sell_price, '__float__') else sell_price
    symbol_close_float = float(symbol_close) if hasattr(symbol_close, '__float__') else symbol_close
    
    payload = {
        'ticket_id': ticket_id,
        'intent': 'close',
        'ticker': trade['ticker'],
        'side': inverted_side,
        'count': trade['position'],
        'action': 'close',
        'type': 'market',
        'time_in_force': 'IOC',
        'buy_price': sell_price_float,
        'symbol_close': symbol_close_float,
        'close_method': 'auto'
    }
    try:
        port = get_port('main_app')
        url = get_service_url(port) + "/trades"
        resp = requests.post(url, json=payload, timeout=3)
        if resp.status_code == 201 or resp.status_code == 200:
            log(f"[AUTO STOP] Triggered AUTO STOP close for trade {trade['trade_id']} (prob={trade.get('current_probability')})")
            
            from backend.util.trade_logger import log_trade_event
            
            # Log to PostgreSQL instead of text file
            log_message = f"CLOSE | {trade.get('ticker', 'Unknown')} | {trade.get('strike')} | {trade.get('side')} | {trade.get('position')} | {sell_price} | {trade.get('current_probability')} | {trade.get('current_pnl', 'Unknown')}"
            log_trade_event(ticket_id, log_message, service="active_trade_supervisor")
            
            # Notify frontend of automated trade close for audio/visual alerts
            try:
                # Convert Decimal objects to float for JSON serialization
                buy_price_float = float(trade.get('buy_price')) if hasattr(trade.get('buy_price'), '__float__') else trade.get('buy_price')
                probability_float = float(trade.get('current_probability')) if hasattr(trade.get('current_probability'), '__float__') else trade.get('current_probability')
                
                notification_data = {
                    "type": "automated_trade_closed",
                    "trade_id": trade['trade_id'],
                    "ticker": trade['ticker'],
                    "strike": trade['strike'],
                    "side": trade['side'],
                    "buy_price": buy_price_float,
                    "sell_price": sell_price_float,
                    "position": trade['position'],
                    "probability": probability_float,
                    "pnl": trade.get('current_pnl'),
                    "timestamp": datetime.now().isoformat()
                }
                
                # Call our own notification endpoint
                notification_url = get_service_url(ACTIVE_TRADE_SUPERVISOR_PORT) + "/api/notify_automated_close"
                notification_response = requests.post(notification_url, json=notification_data, timeout=2)
                if notification_response.ok:
                    log(f"[AUTO STOP] 🔔 Frontend notification sent for automated trade close")
                else:
                    log(f"[AUTO STOP] ⚠️ Frontend notification failed: {notification_response.status_code}")
            except Exception as e:
                log(f"[AUTO STOP] ❌ Error sending frontend notification: {e}")
            
            return True
        else:
            log(f"[AUTO STOP] Failed to trigger close for trade {trade['trade_id']}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        log(f"[AUTO STOP] Exception posting close for trade {trade['trade_id']}: {e}")
        return False

def handle_close_failed_trade(trade_id: int, ticket_id: str) -> bool:
    """
    Handle a trade that failed to close (e.g., due to insufficient volume).
    Reverts the trade to 'active' status and immediately retries the close order.
    """
    try:
        # Get the trade data from active_trades.db
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            SELECT trade_id, ticker, strike, side, position, buy_price, current_close_price, current_symbol_price, current_probability, current_pnl
            FROM users.{active_trades_table} 
            WHERE trade_id = %s
        """, (trade_id,))
        trade_data = cursor.fetchone()
        conn.close()

        if not trade_data:
            log(f"⚠️ Trade with ID {trade_id} not found in active_trades.db.")
            return False

        trade_id_db, ticker, strike, side, position, buy_price, current_close_price, current_symbol_price, current_probability, current_pnl = trade_data

        # Revert to active status
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE users.{active_trades_table}
            SET status = 'active',
                current_close_price = NULL,
                current_pnl = NULL,
                last_updated = CURRENT_TIMESTAMP
            WHERE trade_id = %s
        """, (trade_id,))
        conn.commit()
        conn.close()

        log(f"🔄 CLOSE FAILED - REVERTING TO ACTIVE STATUS")
        log(f"   Trade ID: {trade_id}")
        log(f"   Ticker: {ticker}")
        log(f"   ========================================")
        
        invalidate_active_trades_cache()
        broadcast_active_trades_change()

        # Construct trade dictionary for trigger_auto_stop_close
        trade_dict = {
            'trade_id': trade_id,
            'ticker': ticker,
            'strike': strike,
            'side': side,
            'position': position,
            'buy_price': buy_price,
            'current_close_price': current_close_price,
            'current_symbol_price': current_symbol_price,
            'current_probability': current_probability,
            'current_pnl': current_pnl
        }

        # Immediately retry the close order
        log(f"🚀 IMMEDIATELY RETRYING CLOSE ORDER FOR TRADE {trade_id}")
        trigger_auto_stop_close(trade_dict)
        return True

    except Exception as e:
        log(f"❌ Error handling close_failed trade {trade_id}: {e}")
        return False

# Auto stop settings now read directly from monitor_list_0001 table

def get_auto_stop_threshold():
    """Get auto stop probability threshold from monitor's assigned strategy"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db", 
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log(f"[AUTO STOP] No monitor found with ID {MONITOR_ID}")
                return 40
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log(f"[AUTO STOP] No strategy assigned to monitor {MONITOR_ID}")
                return 40
            
            # Get the threshold from the monitor
            cursor.execute("""
                SELECT current_probability FROM users.monitor_list_0001 WHERE id = %s
            """, (MONITOR_ID,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                threshold = result[0]
                return threshold
            else:
                log(f"[AUTO STOP] No strategy found with name: {strategy_name}")
                return 40
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading threshold from strategy: {e}")
        return 40

def get_unified_ttc_seconds(symbol: str = None):
    """Get unified TTC from master strike table"""
    try:
        # Use current monitor symbol if no symbol specified
        if symbol is None:
            symbol = get_current_monitor_symbol()
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT ttc_seconds FROM live_data.strike_table_{symbol.lower()} LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return int(result[0])
        else:
            log(f"[AUTO STOP] Warning: No TTC data from master strike table, using fallback calculation")
            # Fallback to simple calculation
            now = datetime.now(ZoneInfo("America/New_York"))
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            return max(1, int((next_hour - now).total_seconds()))
            
    except Exception as e:
        log(f"[AUTO STOP] Error reading TTC from master strike table: {e}")
        # Fallback to simple calculation
        now = datetime.now(ZoneInfo("America/New_York"))
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return max(1, int((next_hour - now).total_seconds()))

def get_min_ttc_seconds():
    """Get the minimum TTC seconds setting from monitor's assigned strategy"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db", 
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log(f"[AUTO STOP] No monitor found with ID {MONITOR_ID}")
                return 60
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log(f"[AUTO STOP] No strategy assigned to monitor {MONITOR_ID}")
                return 60
            
            # Get the min_ttc_seconds from the monitor
            cursor.execute("""
                SELECT min_ttc_seconds FROM users.monitor_list_0001 WHERE id = %s
            """, (MONITOR_ID,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                min_ttc = result[0]
                return min_ttc
            else:
                log(f"[AUTO STOP] No strategy found with name: {strategy_name}")
                return 60
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading min_ttc_seconds from strategy: {e}")
        return 60

def get_verification_period_enabled():
    """Get the verification period enabled setting from monitor's assigned strategy"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db", 
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log(f"[AUTO STOP] No monitor found with ID {MONITOR_ID}")
                return False
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log(f"[AUTO STOP] No strategy assigned to monitor {MONITOR_ID}")
                return False
            
            # Get the verification_period_enabled from the monitor
            cursor.execute("""
                SELECT verification_period_enabled FROM users.monitor_list_0001 WHERE id = %s
            """, (MONITOR_ID,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                enabled = result[0]
                return enabled
            else:
                log(f"[AUTO STOP] No strategy found with name: {strategy_name}")
                return False
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading verification_period_enabled from strategy: {e}")
        return False

def get_verification_period_seconds():
    """Get the verification period seconds setting from monitor's assigned strategy"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db", 
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log(f"[AUTO STOP] No monitor found with ID {MONITOR_ID}")
                return 15
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log(f"[AUTO STOP] No strategy assigned to monitor {MONITOR_ID}")
                return 15
            
            # Get the verification_period_seconds from the monitor
            cursor.execute("""
                SELECT verification_period_seconds FROM users.monitor_list_0001 WHERE id = %s
            """, (MONITOR_ID,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                seconds = result[0]
                return seconds
            else:
                log(f"[AUTO STOP] No strategy found with name: {strategy_name}")
                return 15
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading verification_period_seconds from strategy: {e}")
        return 15

# Signal handlers for graceful shutdown
def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    log(f"🛑 Received signal {signum}, shutting down gracefully...")
    drop_monitor_active_trades_table()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    # Create monitor-specific active trades table on startup
    create_monitor_active_trades_table()
    
    # Sync with existing trades on startup
    sync_on_demand()
    
    # Start the event-driven supervisor
    start_event_driven_supervisor() 