#!/usr/bin/env python3
"""
Active Trade Supervisor - MONITOR-AWARE VERSION

Monitors currently open trades and maintains a standalone database
for active trade management. Gets notified when trade_manager confirms
new open trades and creates corresponding entries in ACTIVE_TRADES.DB.
Supports multiple monitors with monitor-specific configuration.
"""

import logging
import os
import json
import time
import threading
import signal
import subprocess
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
from backend.core.config.database import get_postgresql_connection
from backend.util.paths import get_host

# Add these functions after the existing imports and before the get_monitor_identifier function

def create_monitor_active_trades_table():
    """Create monitor-specific active trades table when supervisor starts"""
    try:
        conn = get_postgresql_connection()
        if not conn:
            return
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
                    high_price DECIMAL(10,4),
                    low_price DECIMAL(10,4),
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        conn.close()
        log_debug(f"Created monitor-specific active trades table: {active_trades_table}")
    except Exception as e:
        log(f"[ACTIVE_TRADES] ❌ Error creating active trades table: {e}")

def drop_monitor_active_trades_table():
    """Drop monitor-specific active trades table when supervisor stops"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Drop monitor-specific active trades table
            active_trades_table = f"active_trades_{USER_NUMBER}_{MONITOR_ID}"
            cursor.execute(f"DROP TABLE IF EXISTS users.{active_trades_table}")
            conn.commit()
        conn.close()
        log_debug(f"Dropped monitor-specific active trades table: {active_trades_table}")
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


def _ats_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            dt = datetime.fromtimestamp(record.created, tz=ZoneInfo("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")


class _AtsFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def _configure_ats_logging():
    logr = logging.getLogger("active_trade_supervisor")
    if logr.handlers:
        return logr
    h = _AtsFlushHandler(sys.stdout)
    h.setFormatter(_ats_est_formatter())
    logr.addHandler(h)
    # Default to INFO in normal operation; DEBUG must be explicitly enabled.
    logr.setLevel(logging.INFO)
    return logr


_ats_logger = _configure_ats_logging()
HEARTBEAT_INTERVAL_SEC = 300


def _ats_heartbeat_loop():
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SEC)
        _ats_logger.info("heartbeat")


_ats_hb_thread = threading.Thread(target=_ats_heartbeat_loop, daemon=True)
_ats_hb_thread.start()


_ats_logger.info("Monitor-aware supervisor starting user=%s monitor=%s", USER_NUMBER, MONITOR_ID)

# Get symbol for this monitor (will be updated dynamically)
def get_monitor_symbol():
    """Get the symbol for the current monitor from database"""
    try:
        import psycopg2
        
        conn = get_postgresql_connection()
        if not conn:
            return "BTC", "hourly"
        cursor = conn.cursor()
        
        cursor.execute(f"""
            SELECT symbol, COALESCE(market, 'hourly') FROM users.monitor_list_{USER_NUMBER}
            WHERE id = %s
        """, (MONITOR_ID,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            return result[0].upper(), (result[1] or 'hourly').strip().lower()
        else:
            log_debug(f"No symbol found for monitor {MONITOR_IDENTIFIER}, defaulting to BTC")
            return "BTC", "hourly"
    except Exception as e:
        log(f"[ACTIVE_TRADE_SUPERVISOR] ❌ Error getting monitor symbol: {e}, defaulting to BTC")
        return "BTC", "hourly"

def get_strike_table_name(symbol: str, market: str) -> str:
    """Strike table name from symbol and market (hourly or 15m)."""
    m = (market or 'hourly').strip().lower()
    if m not in ('hourly', '15m'):
        m = 'hourly'
    return f"strike_table_{m}_{symbol.lower()}"

_sym_mkt = get_monitor_symbol()
MONITOR_SYMBOL = _sym_mkt[0] if isinstance(_sym_mkt, tuple) else _sym_mkt
MONITOR_MARKET = _sym_mkt[1] if isinstance(_sym_mkt, tuple) else 'hourly'
_ats_logger.info("Initial symbol=%s market=%s", MONITOR_SYMBOL, MONITOR_MARKET)

def get_current_monitor_symbol_and_market():
    """Get (symbol, market) for this monitor from database. market is 'hourly' or '15m'."""
    global MONITOR_SYMBOL, MONITOR_MARKET
    try:
        conn = get_postgresql_connection()
        if not conn:
            return "BTC", "hourly"
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT symbol, COALESCE(market, 'hourly') FROM users.monitor_list_{USER_NUMBER}
            WHERE id = %s
        """, (MONITOR_ID,))
        result = cursor.fetchone()
        conn.close()
        if result and result[0]:
            sym = result[0].upper()
            mkt = (result[1] or 'hourly').strip().lower()
            if mkt not in ('hourly', '15m'):
                mkt = 'hourly'
            if sym != MONITOR_SYMBOL or mkt != MONITOR_MARKET:
                log_debug(f"Monitor symbol/market: {MONITOR_SYMBOL}/{MONITOR_MARKET} -> {sym}/{mkt}")
                MONITOR_SYMBOL, MONITOR_MARKET = sym, mkt
            return sym, mkt
        return "BTC", "hourly"
    except Exception as e:
        return "BTC", "hourly"

def get_current_monitor_symbol():
    """Get the current symbol for this monitor (dynamic lookup)"""
    sym, _ = get_current_monitor_symbol_and_market()
    return sym

def _get_symbol_and_market_for_strike(symbol: str = None):
    """Resolve (symbol, market) for strike table. Always use this monitor's market (hourly or 15m)."""
    sym, mkt = get_current_monitor_symbol_and_market()
    s = (symbol or sym).upper() if (symbol or sym) else "BTC"
    return s, mkt

# Get port from monitor-specific system
from backend.core.port_config import get_monitor_port, register_monitor_ports

# Register this monitor's ports to ensure consistency
register_monitor_ports(MONITOR_IDENTIFIER)

# Get monitor-specific port
ACTIVE_TRADE_SUPERVISOR_PORT = get_monitor_port("active_trade_supervisor", MONITOR_IDENTIFIER)
_ats_logger.info("Using monitor-specific port: %s", ACTIVE_TRADE_SUPERVISOR_PORT)

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
        log_debug(f"Notifying frontend of automated trade close: {data}")
        
        # Forward the notification to the main app for WebSocket broadcast
        try:
            port = get_port("main_app")
            url = get_service_url(port) + "/api/notify_automated_close"
            response = requests.post(url, json=data, timeout=2)
            if response.ok:
                log_debug(f"Frontend notification sent successfully")
            else:
                log_debug(f"Frontend notification failed: {response.status_code}")
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
    """Stdout log at INFO (use log_debug for plumbing)."""
    _ats_logger.info("%s", message)


def log_debug(message: str):
    """Stdout log at DEBUG for plumbing/repetitive messages."""
    _ats_logger.debug("%s", message)

def get_momentum_percentile_from_postgresql(symbol="BTC"):
    """Get current momentum_5s_avg from live price log for the specified symbol."""
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum_5s_avg FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return float(result[0])
        else:
            return None
    except Exception as e:
        log(f"[MOMENTUM SPIKE] Error getting momentum_5s_avg from PostgreSQL: {e}")
        return None

def get_momentum_5s_avg_from_postgresql(symbol="BTC"):
    """Get current momentum_5s_avg directly from PostgreSQL for the specified symbol."""
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum_5s_avg FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return float(result[0])
        else:
            return None
    except Exception as e:
        log(f"[MOMENTUM SPIKE] Error getting momentum_5s_avg from PostgreSQL: {e}")
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
            return jsonify({"error": "No data received", "success": False}), 200
        
        trade_id = data.get('trade_id')
        ticket_id = data.get('ticket_id')
        status = data.get('status')
        monitor_identifier = data.get('monitor_identifier')
        
        if not all([trade_id, ticket_id, status]):
            return jsonify({
                "error": "Missing required fields: trade_id, ticket_id, status",
                "success": False
            }), 200
        
        # Validate that this notification is for the correct monitor
        if monitor_identifier and monitor_identifier != MONITOR_IDENTIFIER:
            log(f"📡 DIRECT NOTIFICATION: Ignoring notification for different monitor")
            log(f"📡 DIRECT NOTIFICATION: Expected: {MONITOR_IDENTIFIER}, Received: {monitor_identifier}")
            return jsonify(
                {
                    "status": "ignored",
                    "message": f"Notification for different monitor: {monitor_identifier}",
                    "success": True,
                }
            ), 200
        
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
            # Try to confirm pending trade first, if that fails, add as new active trade
            success = confirm_pending_trade(trade_id, ticket_id)
            if success:
                log(f"✅ Successfully confirmed pending trade as open: {trade_id}")
            else:
                # Trade was created directly as 'open', add it as new active trade
                success = add_new_active_trade(trade_id, ticket_id)
                if success:
                    log(f"✅ Successfully added new active trade: {trade_id}")
                else:
                    log(f"❌ Failed to add new active trade: {trade_id}")
                
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
            return jsonify(
                {"error": f"Unknown status: {status}", "success": False}
            ), 200

        # Always return 200 to trade_manager; surface failures in the JSON payload and logs
        return jsonify(
            {
                "status": "success" if success else "error",
                "message": f"Trade {trade_id} {status} notification processed",
                "success": success,
            }
        ), 200

    except Exception as e:
        log(f"❌ Error handling trade_manager notification: {e}")
        # Do not propagate HTTP 500 back to trade_manager; report error in payload instead
        return jsonify({"status": "error", "error": str(e), "success": False}), 200

def migrate_database_schema():
    """Migrate the database schema if needed"""
    pass

def init_active_trades_db():
    """Initialize the active trades database"""
    pass

def get_db_connection():
    """Get database connection with appropriate timeout (uses centralized config)."""
    return get_postgresql_connection()

def get_trades_db_connection():
    """Get connection to the main trades database"""
    return get_postgresql_connection()

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
        # Initialize high_price and low_price to buy_price for active trades
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            INSERT INTO users.{active_trades_table} (
                trade_id, ticket_id, date, time, strike, side, buy_price, position,
                contract, ticker, symbol, market, trade_strategy, symbol_open,
                momentum, prob, fees, diff, high_price, low_price
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            trade_id, ticket_id, date, time, strike, side, buy_price, position,
            contract, ticker, symbol, market, trade_strategy, symbol_open,
            momentum, prob, fees, diff, buy_price, buy_price
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
        # Initialize high_price and low_price to buy_price when trade becomes active
        conn = get_db_connection()
        cursor = conn.cursor()
        active_trades_table = get_monitor_active_trades_table()
        cursor.execute(f"""
            UPDATE users.{active_trades_table}
            SET status = 'active',
                buy_price = %s,
                position = %s,
                fees = %s,
                diff = %s,
                high_price = %s,
                low_price = %s
            WHERE trade_id = %s AND status = 'pending'
        """, (buy_price, position, fees, diff, buy_price, buy_price, trade_id))
        
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

def get_kalshi_market_snapshot(symbol: str = None, market: str = None) -> Optional[Dict[str, Any]]:
    """Get the latest Kalshi market snapshot data from PostgreSQL.
    Uses monitor's symbol and market so 15m monitors read from market_kalshi_15m_* (required for
    closing price lookup and auto-stop); hourly monitors read from market_kalshi_hourly_*."""
    try:
        # Use current monitor symbol and market if not specified
        if symbol is None or market is None:
            sym, mkt = get_current_monitor_symbol_and_market()
            if symbol is None:
                symbol = sym
            if market is None:
                market = mkt or "hourly"
        market = (market or "hourly").strip().lower()
        if market not in ("hourly", "15m"):
            market = "hourly"
        table_suffix = f"15m_{symbol.lower()}" if market == "15m" else f"hourly_{symbol.lower()}"
        table_name = f"market_kalshi_{table_suffix}"
            
        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL")
            return None
            
        cursor = conn.cursor()
        
        # Get market data from PostgreSQL (hourly or 15m table per monitor)
        cursor.execute(f"""
            SELECT 
                market_ticker,
                yes_ask,
                no_ask,
                yes_ask_dollars,
                no_ask_dollars,
                volume,
                event_ticker,
                strike
            FROM live_data.{table_name}
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
                "yes_ask_dollars": row[3],
                "no_ask_dollars": row[4],
                "volume": row[5],
                "event_ticker": row[6],
                "strike": row[7]
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
                # Use _dollars values for subpenny precision, fallback to cent conversion
                if trade_side.upper() == "Y":  # YES trade
                    closing_price_dollars = market.get("no_ask_dollars")
                    closing_price_cents = market.get("no_ask")
                elif trade_side.upper() == "N":  # NO trade
                    closing_price_dollars = market.get("yes_ask_dollars")
                    closing_price_cents = market.get("yes_ask")
                else:
                    log(f"⚠️ Unknown trade side: {trade_side}")
                    return None
                
                # Use _dollars values directly (no fallback to cents)
                if closing_price_dollars is not None:
                    # Use subpenny precision directly (no conversion needed)
                    closing_price_decimal = float(closing_price_dollars)
                    return closing_price_decimal
                else:
                    log(f"⚠️ No closing price (_dollars) found for {trade_ticker} ({trade_side})")
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
        sym, mkt = _get_symbol_and_market_for_strike(symbol)
        table_name = get_strike_table_name(sym, mkt)
        conn = get_postgresql_connection()
        if not conn:
            log("⚠️ Failed to connect to PostgreSQL for probability lookup")
            return None
            
        cursor = conn.cursor()
        
        # Get probability from PostgreSQL strike table (hourly: probability_hourly; 15m: probability_15m)
        prob_col = "probability_15m" if mkt == "15m" else "probability_hourly"
        cursor.execute(f"""
            SELECT {prob_col}
            FROM live_data.{table_name}
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
            SELECT id, trade_id, buy_price, prob, time, date, strike, side, momentum, ticker, symbol, high_price, low_price
            FROM users.{active_trades_table} 
            WHERE status = 'active'
        """)
        active_trades = cursor.fetchall()
        conn.close()
        
        if not active_trades:
            return
        
        for (active_id, trade_id, buy_price, prob, time_str, date_str, strike, side, momentum, ticker, symbol, current_high_price, current_low_price) in active_trades:
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
                
                # Convert current_market_price (sell price) to position value for high/low tracking
                # current_market_price is the opposite side's ask (what you can sell for)
                # Position value = 1 - sell_price (the value of the position you own)
                # Example: If you bought YES at $0.90 and sell price is $0.10, position value = $1.00 - $0.10 = $0.90
                position_value = 1 - current_market_price
                
                # Compare and determine new high_price and low_price
                # If high_price or low_price is NULL (shouldn't happen for active trades, but handle gracefully),
                # initialize to buy_price. Otherwise compare with position_value
                if current_high_price is None:
                    current_high_price = buy_price_float
                if current_low_price is None:
                    current_low_price = buy_price_float
                
                # high_price should be the maximum of current_high_price and position_value
                new_high_price = max(float(current_high_price), position_value)
                # low_price should be the minimum of current_low_price and position_value
                new_low_price = min(float(current_low_price), position_value)
                
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
                        high_price = %s,
                        low_price = %s,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (current_symbol_price, current_probability, buffer_from_strike, time_since_entry, current_market_price, pnl_formatted, new_high_price, new_low_price, active_id))
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
    Bulletproof failsafe: Check if monitoring should be running and restart if needed.
    First attempts thread restart, then escalates to process restart if that fails.
    """
    global monitoring_thread
    
    # Track restart attempts to prevent infinite loops
    if not hasattr(check_monitoring_failsafe, 'restart_attempts'):
        check_monitoring_failsafe.restart_attempts = {}
        check_monitoring_failsafe.last_process_restart = 0
        check_monitoring_failsafe.process_restart_cooldown = 300  # 5 minutes between process restarts
    
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
                thread_alive = False
                try:
                    thread_alive = monitoring_thread is not None and monitoring_thread.is_alive()
                except Exception as e:
                    log(f"⚠️ FAILSAFE: Thread object corrupted ({e}), forcing cleanup")
                    monitoring_thread = None
                    thread_alive = False
                
                if not thread_alive:
                    log(f"🔄 FAILSAFE: Found {active_count} active trades but monitoring not running")
                    
                    # Step 1: Try thread restart first (quick recovery)
                    log("🔄 FAILSAFE: Attempting thread restart...")
                    thread_restart_succeeded = False
                    try:
                        start_monitoring_loop()
                        
                        # Verify thread restart succeeded
                        time.sleep(1)  # Give thread time to start
                        with monitoring_thread_lock:
                            if monitoring_thread is not None:
                                try:
                                    if monitoring_thread.is_alive():
                                        log("✅ FAILSAFE: Thread restart succeeded and verified")
                                        thread_restart_succeeded = True
                                        # Reset restart attempts on success
                                        check_monitoring_failsafe.restart_attempts = {}
                                except Exception as e:
                                    log(f"⚠️ FAILSAFE: Thread verification failed ({e}), escalating to process restart")
                    except Exception as e:
                        log(f"❌ FAILSAFE: Thread restart failed ({e}), escalating to process restart")
                        import traceback
                        log(f"❌ FAILSAFE: Thread restart stack trace: {traceback.format_exc()}")
                    
                    # Step 2: Thread restart failed or verification failed - restart entire process
                    if not thread_restart_succeeded:
                        current_time = time.time()
                        time_since_last_restart = current_time - check_monitoring_failsafe.last_process_restart
                        
                        if time_since_last_restart < check_monitoring_failsafe.process_restart_cooldown:
                            log(f"⏳ FAILSAFE: Process restart on cooldown ({int(check_monitoring_failsafe.process_restart_cooldown - time_since_last_restart)}s remaining)")
                            return
                        
                        log(f"🚨 CRITICAL FAILSAFE: Thread restart failed, restarting entire process!")
                        log(f"🚨 CRITICAL: {active_count} active trades are UNPROTECTED - process restart required!")
                        
                        # Restart this process via supervisorctl
                        restart_active_trade_supervisor_process()
                        
                        # Update cooldown
                        check_monitoring_failsafe.last_process_restart = current_time
        
    except Exception as e:
        log(f"❌ CRITICAL: Failsafe check itself failed: {e}")
        import traceback
        log(f"❌ CRITICAL: Failsafe stack trace: {traceback.format_exc()}")
        # Even the failsafe failed - try process restart as last resort
        try:
            restart_active_trade_supervisor_process()
        except Exception as restart_error:
            log(f"❌ CATASTROPHIC: Process restart also failed: {restart_error}")

def restart_active_trade_supervisor_process():
    """
    Restart the entire active_trade_supervisor process via supervisorctl.
    This will cause this process to exit and supervisor will restart it.
    """
    try:
        from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
        
        service_name = f"active_trade_supervisor_{MONITOR_IDENTIFIER}"
        
        log(f"🔄 PROCESS RESTART: Restarting {service_name} via supervisorctl...")
        log(f"🚨 CRITICAL: Process restart initiated due to monitoring failure")
        
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()
        
        # Restart the service
        result = subprocess.run(
            [supervisorctl_path, "-c", supervisor_config_path, "restart", service_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            log(f"✅ PROCESS RESTART: Successfully initiated restart of {service_name}")
            log(f"✅ PROCESS RESTART: Supervisor output: {result.stdout}")
            
            # Give supervisor time to restart the process
            time.sleep(2)
            
            # This process will be terminated by supervisor, so we can exit
            log("🔄 PROCESS RESTART: Process restart initiated, supervisor will handle termination")
        else:
            log(f"❌ PROCESS RESTART: Failed to restart {service_name}")
            log(f"❌ PROCESS RESTART: Return code: {result.returncode}")
            log(f"❌ PROCESS RESTART: stderr: {result.stderr}")
            log(f"❌ PROCESS RESTART: stdout: {result.stdout}")
            
            # If supervisorctl fails, try alternative: exit and let supervisor auto-restart
            log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
            sys.exit(1)  # Exit with error code, supervisor will restart
            
    except subprocess.TimeoutExpired:
        log(f"❌ PROCESS RESTART: Timeout waiting for supervisorctl")
        # Fall back to exit
        log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
        sys.exit(1)
    except Exception as e:
        log(f"❌ PROCESS RESTART: Exception during restart: {e}")
        import traceback
        log(f"❌ PROCESS RESTART: Stack trace: {traceback.format_exc()}")
        # Fall back to exit
        log("🔄 PROCESS RESTART: Falling back to process exit (supervisor will auto-restart)")
        sys.exit(1)

def start_monitoring_loop():
    """
    Start monitoring loop when there are active trades.
    This should be called when trades are added to active_trades.
    """
    global monitoring_thread
    
    # Clean up any corrupted state first
    try:
        with monitoring_thread_lock:
            if monitoring_thread is not None:
                try:
                    if not monitoring_thread.is_alive():
                        log("🧹 CLEANUP: Clearing dead thread reference")
                        monitoring_thread = None
                except Exception as e:
                    log(f"🧹 CLEANUP: Thread object corrupted ({e}), forcing cleanup")
                    monitoring_thread = None
    except Exception as e:
        log(f"⚠️ Cleanup check failed: {e}")
    
    # Check if monitoring thread is already running
    with monitoring_thread_lock:
        if monitoring_thread is not None:
            try:
                if monitoring_thread.is_alive():
                    log("📊 MONITORING: Monitoring thread already running, skipping")
                    return
            except Exception as e:
                log(f"⚠️ Thread object corrupted ({e}), clearing and continuing")
                monitoring_thread = None
    
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
                
                # Refetch active_trades after update to get fresh current_probability values for auto-stop
                conn = get_db_connection()
                cursor = conn.cursor()
                active_trades_table = get_monitor_active_trades_table()
                cursor.execute(f"SELECT * FROM users.{active_trades_table} WHERE status = 'active'")
                columns = [desc[0] for desc in cursor.description]
                active_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
                conn.close()
                
                # Log monitoring status every 60 seconds
                current_time = time.time()
                if not hasattr(monitoring_worker, 'last_status_log') or current_time - monitoring_worker.last_status_log > 60:
                    log_debug(f"MONITORING: Checking {len(active_trades)} active trades")
                    monitoring_worker.last_status_log = current_time
                
                # Add heartbeat log every 30 seconds to track monitoring health
                if not hasattr(monitoring_worker, 'last_heartbeat') or current_time - monitoring_worker.last_heartbeat > 30:
                    log_debug(f"MONITORING HEARTBEAT: Monitoring loop healthy, {len(active_trades)} active trades")
                    monitoring_worker.last_heartbeat = current_time
                
                # Run failsafe check every 60 seconds
                if not hasattr(monitoring_worker, 'last_failsafe_check') or current_time - monitoring_worker.last_failsafe_check > 60:
                    check_monitoring_failsafe()
                    monitoring_worker.last_failsafe_check = current_time
                
                # === AUTO STOP LOGIC ===
                auto_stop_enabled = is_auto_stop_enabled()
                if auto_stop_enabled:
                    check_auto_stop_conditions(active_trades, auto_stop_triggered_trades, verification_pending_trades)
                
                # === MOMENTUM SPIKE AUTO-STOPOUT LOGIC ===
                # Skip momentum spike logic for Momentum Scalp and Momentum Reversal monitors
                strategy = get_trade_strategy()
                if strategy != "Momentum Scalp" and strategy != "Momentum Reversal":
                    # Get momentum spike settings from monitor's assigned strategy
                    try:
                        import psycopg2
                        conn = get_postgresql_connection()
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
                                    log_debug(f"No strategy found: {strategy_name}, using defaults")
                            else:
                                momentum_spike_enabled = True
                                momentum_spike_threshold = 35  # Use percentage directly
                                log_debug(f"No strategy assigned to monitor {MONITOR_ID}, using defaults")
                        
                        conn.close()
                        
                        # Only proceed if momentum spike is enabled
                        if momentum_spike_enabled:
                            # Get verification settings (same as probability-based auto stop)
                            verification_enabled = get_verification_period_enabled()
                            verification_seconds = get_verification_period_seconds()
                            current_time = time.time()
                            
                            # Get current momentum (use 5s average from live price log to smooth noise)
                            current_momentum = get_momentum_5s_avg_from_postgresql(get_current_monitor_symbol())
                            
                            if current_momentum is not None:
                                # Refresh active trades
                                conn = get_db_connection()
                                cursor = conn.cursor()
                                active_trades_table = get_monitor_active_trades_table()
                                cursor.execute(f"SELECT * FROM users.{active_trades_table} WHERE status = 'active'")
                                columns = [desc[0] for desc in cursor.description]
                                refreshed_active_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
                                conn.close()
                                
                                # Determine which trades are affected by current momentum
                                positive_spike = current_momentum >= momentum_spike_threshold
                                negative_spike = current_momentum <= -momentum_spike_threshold
                                
                                if positive_spike:  # Positive spike - close all NO trades
                                    # Filter eligible NO trades
                                    eligible_trades = [t for t in refreshed_active_trades 
                                                       if t.get('status') == 'active' 
                                                       and t.get('side', '').upper() in ['N', 'NO']
                                                       and t.get('trade_id') not in auto_stop_triggered_trades]
                                    
                                    successful_closes = 0
                                    for trade in eligible_trades:
                                        trade_id = trade.get('trade_id')
                                        
                                        # Check if trade is in verification period
                                        if trade_id in verification_pending_trades:
                                            trigger_time, verification_end_time = verification_pending_trades[trade_id]
                                            
                                            # Check if verification period has ended
                                            if current_time >= verification_end_time:
                                                # Verification period ended - re-check current momentum to verify spike conditions still met
                                                current_momentum_after_verification = get_momentum_5s_avg_from_postgresql(get_current_monitor_symbol())
                                                if current_momentum_after_verification is not None:
                                                    spike_still_active = current_momentum_after_verification >= momentum_spike_threshold
                                                    if spike_still_active:
                                                        # Conditions still met after verification - trigger auto-stop
                                                        log_debug(f"[MOMENTUM SPIKE] Verification period ended - triggering auto stop for NO trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: +{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                        if trigger_auto_stop_close(trade):
                                                            auto_stop_triggered_trades.add(trade_id)
                                                            del verification_pending_trades[trade_id]
                                                            successful_closes += 1
                                                        else:
                                                            log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                                                            del verification_pending_trades[trade_id]
                                                    else:
                                                        # Conditions no longer met - cancel verification
                                                        log(f"[MOMENTUM SPIKE] ❌ Verification period ended - conditions no longer met for NO trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: +{momentum_spike_threshold})")
                                                        del verification_pending_trades[trade_id]
                                                else:
                                                    # Could not get momentum - cancel verification to retry
                                                    log(f"[MOMENTUM SPIKE] ⚠️ Verification period ended but could not get current momentum for NO trade {trade_id}, cancelling verification")
                                                    del verification_pending_trades[trade_id]
                                            else:
                                                # Still in verification period - just wait, don't check conditions during wait
                                                remaining_time = verification_end_time - current_time
                                                if not hasattr(monitoring_worker, 'last_momentum_verification_log') or current_time - monitoring_worker.last_momentum_verification_log > 10:
                                                    log_debug(f"NO trade {trade_id} in verification period - {remaining_time:.1f}s remaining (momentum: {current_momentum:.2f})")
                                                    monitoring_worker.last_momentum_verification_log = current_time
                                                continue
                                        else:
                                            # Not in verification period - check if spike conditions are met
                                            if positive_spike:
                                                if verification_enabled:
                                                    # Start verification period
                                                    verification_end_time = current_time + verification_seconds
                                                    verification_pending_trades[trade_id] = (current_time, verification_end_time)
                                                    log_debug(f"Starting verification period for NO trade {trade_id} (momentum: {current_momentum:.2f}, threshold: +{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                else:
                                                    # No verification - trigger immediately
                                                    log(f"[MOMENTUM SPIKE] 🚨 POSITIVE SPIKE - Triggering close for NO trade {trade_id} (momentum: {current_momentum:.2f})")
                                                    if trigger_auto_stop_close(trade):
                                                        auto_stop_triggered_trades.add(trade_id)
                                                        successful_closes += 1
                                                    else:
                                                        log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
                                    
                                    if successful_closes > 0:
                                        log(f"[MOMENTUM SPIKE] ✅ Closed {successful_closes} NO trades due to positive momentum spike")
                                        
                                elif negative_spike:  # Negative spike - close all YES trades
                                    # Filter eligible YES trades
                                    eligible_trades = [t for t in refreshed_active_trades 
                                                       if t.get('status') == 'active' 
                                                       and t.get('side', '').upper() in ['Y', 'YES']
                                                       and t.get('trade_id') not in auto_stop_triggered_trades]
                                    
                                    successful_closes = 0
                                    for trade in eligible_trades:
                                        trade_id = trade.get('trade_id')
                                        
                                        # Check if trade is in verification period
                                        if trade_id in verification_pending_trades:
                                            trigger_time, verification_end_time = verification_pending_trades[trade_id]
                                            
                                            # Check if verification period has ended
                                            if current_time >= verification_end_time:
                                                # Verification period ended - re-check current momentum to verify spike conditions still met
                                                current_momentum_after_verification = get_momentum_5s_avg_from_postgresql(get_current_monitor_symbol())
                                                if current_momentum_after_verification is not None:
                                                    spike_still_active = current_momentum_after_verification <= -momentum_spike_threshold
                                                    if spike_still_active:
                                                        # Conditions still met after verification - trigger auto-stop
                                                        log_debug(f"[MOMENTUM SPIKE] Verification period ended - triggering auto stop for YES trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: -{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                        if trigger_auto_stop_close(trade):
                                                            auto_stop_triggered_trades.add(trade_id)
                                                            del verification_pending_trades[trade_id]
                                                            successful_closes += 1
                                                        else:
                                                            log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                                                            del verification_pending_trades[trade_id]
                                                    else:
                                                        # Conditions no longer met - cancel verification
                                                        log(f"[MOMENTUM SPIKE] ❌ Verification period ended - conditions no longer met for YES trade {trade_id} (momentum: {current_momentum_after_verification:.2f}, threshold: -{momentum_spike_threshold})")
                                                        del verification_pending_trades[trade_id]
                                                else:
                                                    # Could not get momentum - cancel verification to retry
                                                    log(f"[MOMENTUM SPIKE] ⚠️ Verification period ended but could not get current momentum for YES trade {trade_id}, cancelling verification")
                                                    del verification_pending_trades[trade_id]
                                            else:
                                                # Still in verification period - just wait, don't check conditions during wait
                                                remaining_time = verification_end_time - current_time
                                                if not hasattr(monitoring_worker, 'last_momentum_verification_log') or current_time - monitoring_worker.last_momentum_verification_log > 10:
                                                    log_debug(f"YES trade {trade_id} in verification period - {remaining_time:.1f}s remaining (momentum: {current_momentum:.2f})")
                                                    monitoring_worker.last_momentum_verification_log = current_time
                                                continue
                                        else:
                                            # Not in verification period - check if spike conditions are met
                                            if negative_spike:
                                                if verification_enabled:
                                                    # Start verification period
                                                    verification_end_time = current_time + verification_seconds
                                                    verification_pending_trades[trade_id] = (current_time, verification_end_time)
                                                    log_debug(f"Starting verification period for YES trade {trade_id} (momentum: {current_momentum:.2f}, threshold: -{momentum_spike_threshold}, verification_duration={verification_seconds}s)")
                                                else:
                                                    # No verification - trigger immediately
                                                    log(f"[MOMENTUM SPIKE] 🚨 NEGATIVE SPIKE - Triggering close for YES trade {trade_id} (momentum: {current_momentum:.2f})")
                                                    if trigger_auto_stop_close(trade):
                                                        auto_stop_triggered_trades.add(trade_id)
                                                        successful_closes += 1
                                                    else:
                                                        log(f"[MOMENTUM SPIKE] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
                                    
                                    if successful_closes > 0:
                                        log(f"[MOMENTUM SPIKE] ✅ Closed {successful_closes} YES trades due to negative momentum spike")
                                
                                # Log momentum monitoring (every 30 seconds to reduce noise)
                                if not hasattr(monitoring_worker, 'last_momentum_log') or current_time - monitoring_worker.last_momentum_log > 30:
                                    log_debug(f"[MOMENTUM SPIKE] Monitoring momentum: {current_momentum:.2f} (threshold: ±{momentum_spike_threshold})")
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
    
    # Start monitoring in a separate thread WITH EXCEPTION HANDLING
    with monitoring_thread_lock:
        try:
            monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
            monitoring_thread.start()
            
            # Verify thread actually started
            if not monitoring_thread.is_alive():
                raise RuntimeError("Thread failed to start after start() call")
            
            log("📊 MONITORING: Monitoring thread started and verified alive")
            
        except Exception as e:
            log(f"❌ CRITICAL: Failed to start monitoring thread: {e}")
            log(f"❌ CRITICAL: Exception type: {type(e).__name__}")
            import traceback
            log(f"❌ CRITICAL: Stack trace: {traceback.format_exc()}")
            # Clear thread reference on failure
            monitoring_thread = None
            raise  # Re-raise to let caller know it failed

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
    if not conn:
        log("❌ Failed to connect to PostgreSQL; cannot start event-driven supervisor")
        sys.exit(1)
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
                
                # Try thread restart first
                thread_restart_succeeded = False
                try:
                    log("🔄 BRUTE FORCE FAILSAFE: Attempting thread restart...")
                    start_monitoring_loop()
                    time.sleep(1)  # Give thread time to start
                    
                    # Verify
                    with monitoring_thread_lock:
                        if monitoring_thread is not None:
                            try:
                                if monitoring_thread.is_alive():
                                    log("✅ BRUTE FORCE FAILSAFE: Thread restart succeeded and verified")
                                    thread_restart_succeeded = True
                            except Exception as e:
                                log(f"⚠️ BRUTE FORCE FAILSAFE: Thread verification failed ({e})")
                    
                except Exception as e:
                    log(f"❌ BRUTE FORCE FAILSAFE: Thread restart exception: {e}")
                    import traceback
                    log(f"❌ BRUTE FORCE FAILSAFE: Stack trace: {traceback.format_exc()}")
                
                # If thread restart failed, restart process
                if not thread_restart_succeeded:
                    log("🚨 BRUTE FORCE FAILSAFE: Thread restart failed, restarting process...")
                    try:
                        restart_active_trade_supervisor_process()
                    except Exception as e:
                        log(f"❌ BRUTE FORCE FAILSAFE: Process restart failed: {e}")
            
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
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Check auto_trade boolean from the specific monitor's row in monitor_list
            cursor.execute(f"SELECT auto_trade FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                auto_trade_enabled = result[0]
                return auto_trade_enabled
            else:
                log_debug(f"No monitor found with ID {MONITOR_ID} in monitor_list")
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
    # Get current_close_price (opposite side's ask) and convert to actual sell_price
    # current_close_price is the opposite side's ask, so sell_price = 1 - current_close_price
    current_close_price = trade.get('current_close_price')
    symbol_close = trade.get('current_symbol_price')
    if current_close_price is None or symbol_close is None:
        log(f"[AUTO STOP] Skipping close for trade {trade['trade_id']} due to missing price data.")
        return False
    
    # Convert current_close_price (opposite side's ask) to actual sell_price
    # For both YES and NO trades: sell_price = 1 - opposite_side_ask
    sell_price = 1.0 - float(current_close_price) if hasattr(current_close_price, '__float__') else 1.0 - current_close_price
    
    # Convert Decimal objects to float for JSON serialization
    sell_price_float = float(sell_price) if hasattr(sell_price, '__float__') else sell_price
    symbol_close_float = float(symbol_close) if hasattr(symbol_close, '__float__') else symbol_close
    
    position_val = trade.get('position', 1)
    payload = {
        'id': trade['trade_id'],  # Include the specific trade_id from active_trades table
        'ticket_id': ticket_id,
        'intent': 'close',
        'ticker': trade['ticker'],
        'side': inverted_side,
        'count': position_val,
        'count_fp': f"{float(position_val):.2f}",
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
                    log_debug(f"Frontend notification sent for automated trade close")
                else:
                    log(f"[AUTO STOP] ⚠️ Frontend notification failed: {notification_response.status_code}")
            except Exception as e:
                log(f"[AUTO STOP] ❌ Error sending frontend notification: {e}")
            
            return True
        else:
            log(f"[AUTO STOP] Failed to trigger close for trade {trade['trade_id']}: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        # Check if this is a timeout exception
        is_timeout = 'timeout' in str(e).lower() or 'timed out' in str(e).lower()
        
        if is_timeout:
            # For timeout exceptions, check if the trade status changed to "closing" or "closed"
            # This indicates the request was processed even though the response timed out
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                active_trades_table = get_monitor_active_trades_table()
                cursor.execute(f"SELECT status FROM users.{active_trades_table} WHERE trade_id = %s", (trade['trade_id'],))
                result = cursor.fetchone()
                conn.close()
                
                if result and result[0] in ['closing', 'closed']:
                    # Trade status changed, so the close request was processed successfully
                    log(f"[AUTO STOP] ⚠️ Request timeout for trade {trade['trade_id']}, but trade status is '{result[0]}' - treating as success")
                    return True
            except Exception as db_check_error:
                log(f"[AUTO STOP] ⚠️ Timeout for trade {trade['trade_id']}, but could not verify status: {db_check_error}")
        
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

def get_trade_strategy():
    """Get trade strategy from monitor-specific configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                trade_strategy = result[0]
                return trade_strategy
            else:
                log(f"[AUTO STOP] No monitor configuration found for monitor {MONITOR_ID}")
                return "Hourly HTC"  # Default fallback
    except Exception as e:
        log(f"[AUTO STOP] Error loading trade strategy from monitor {MONITOR_ID}: {e}")
        return "Hourly HTC"  # Default fallback
    finally:
        if conn:
            conn.close()

def get_momentum_scalp_trailing_stop_amount():
    """Get momentum scalp trailing stop amount from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT momentum_scalp_trailing_stop_amount FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No trailing stop amount found for monitor {MONITOR_ID}, using default 0.10")
                return 0.10  # Default 10% trailing stop
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading trailing stop amount: {e}")
        return 0.10  # Default fallback

def get_momentum_scalp_profit_target():
    """Get momentum scalp profit target from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT momentum_scalp_profit_target FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No profit target found for monitor {MONITOR_ID}, using default 0.50")
                return 0.50  # Default 50% profit target
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading profit target: {e}")
        return 0.50  # Default fallback

def get_max_profit():
    """Get max_profit from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT max_profit FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No max_profit found for monitor {MONITOR_ID}, using default 0.9900")
                return 0.9900  # Default 99% max profit
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading max_profit: {e}")
        return 0.9900  # Default fallback

def get_momentum_scalp_entry_threshold():
    """Get momentum scalp entry threshold from monitor configuration"""
    try:
        import psycopg2
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT momentum_scalp_entry_threshold FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            conn.close()
            if result and result[0] is not None:
                return float(result[0])
            else:
                log_debug(f"No momentum_scalp_entry_threshold found for monitor {MONITOR_ID}, using default 35.0")
                return 35.0  # Default threshold
    except Exception as e:
        log(f"[AUTO STOP MS] Error reading momentum_scalp_entry_threshold: {e}")
        return 35.0  # Default fallback

def get_auto_stop_threshold():
    """Get auto stop probability threshold from monitor's assigned strategy"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {MONITOR_ID}")
                return 40
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {MONITOR_ID}")
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
                log_debug(f"No strategy found with name: {strategy_name}")
                return 40
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading threshold from strategy: {e}")
        return 40

def get_unified_ttc_seconds(symbol: str = None):
    """Get unified TTC from master strike table (uses monitor symbol+market when symbol is None)."""
    try:
        sym, mkt = _get_symbol_and_market_for_strike(symbol)
        table_name = get_strike_table_name(sym, mkt)
        conn = get_db_connection()
        cursor = conn.cursor()
        # Hourly strike tables use ttc_hourly; 15m strike tables use ttc_15m.
        ttc_column = "ttc_15m" if mkt == "15m" else "ttc_hourly"
        cursor.execute(f"SELECT {ttc_column} FROM live_data.{table_name} LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return int(result[0])
        else:
            log_debug(f"No TTC data from master strike table, using fallback calculation")
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
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {MONITOR_ID}")
                return 60
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {MONITOR_ID}")
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
                log_debug(f"No strategy found with name: {strategy_name}")
                return 60
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading min_ttc_seconds from strategy: {e}")
        return 60

def get_verification_period_enabled():
    """Get the verification period enabled setting from monitor's assigned strategy"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {MONITOR_ID}")
                return False
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {MONITOR_ID}")
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
                log_debug(f"No strategy found with name: {strategy_name}")
                return False
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading verification_period_enabled from strategy: {e}")
        return False

def get_verification_period_seconds():
    """Get the verification period seconds setting from monitor's assigned strategy"""
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # First get the strategy name for this monitor
            cursor.execute(f"""
                SELECT strategy FROM users.monitor_list_{USER_NUMBER} WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                log_debug(f"No monitor found with ID {MONITOR_ID}")
                return 15
            
            strategy_name = monitor_result[0]
            if not strategy_name:
                log_debug(f"No strategy assigned to monitor {MONITOR_ID}")
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
                log_debug(f"No strategy found with name: {strategy_name}")
                return 15
                
    except Exception as e:
        log(f"[AUTO STOP] Error reading verification_period_seconds from strategy: {e}")
        return 15

def check_auto_stop_conditions(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Router function to check auto-stop conditions based on monitor's strategy.
    Routes to strategy-specific auto-stop logic.
    """
    strategy = get_trade_strategy()
    
    if strategy == "Momentum Scalp":
        check_auto_stop_conditions_momentum_scalp(active_trades, auto_stop_triggered_trades, verification_pending_trades)
    elif strategy == "Momentum Reversal":
        check_auto_stop_conditions_momentum_reversal(active_trades, auto_stop_triggered_trades, verification_pending_trades)
    elif strategy == "Reverse HTC":
        # Reverse HTC uses the same auto-stop logic as Hourly HTC
        check_auto_stop_conditions_hourly_htc(active_trades, auto_stop_triggered_trades, verification_pending_trades)
    else:
        # Default to Hourly HTC (fallback for any other strategy or missing strategy)
        check_auto_stop_conditions_hourly_htc(active_trades, auto_stop_triggered_trades, verification_pending_trades)

def check_auto_stop_conditions_hourly_htc(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Check auto-stop conditions for Hourly HTC strategy.
    This is the original auto-stop logic - DO NOT MODIFY.
    """
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
                    log(f"[AUTO STOP HTC] ✅ Verification period ended - triggering auto stop for trade {trade_id} (prob={prob}, verification_duration={verification_seconds}s)")
                    if trigger_auto_stop_close(trade):
                        auto_stop_triggered_trades.add(trade_id)
                        del verification_pending_trades[trade_id]
                    else:
                        log(f"[AUTO STOP HTC] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                        del verification_pending_trades[trade_id]
                else:
                    # Conditions no longer met - cancel verification
                    log(f"[AUTO STOP HTC] ❌ Verification period ended - conditions no longer met for trade {trade_id} (prob={prob}, threshold={threshold})")
                    del verification_pending_trades[trade_id]
            else:
                # Still in verification period - just wait, don't check conditions during wait
                remaining_time = verification_end_time - current_time
                if not hasattr(check_auto_stop_conditions_hourly_htc, 'last_verification_log') or current_time - check_auto_stop_conditions_hourly_htc.last_verification_log > 10:
                    log_debug(f"Trade {trade_id} in verification period - {remaining_time:.1f}s remaining")
                    check_auto_stop_conditions_hourly_htc.last_verification_log = current_time
                continue
        
        # Check for new auto-stop conditions
        # Debug logging for trade 2448
        if trade_id == 2448:
            log_debug(f"Trade {trade_id} - prob: {prob}, threshold: {threshold}, status: {trade.get('status')}, in_triggered: {trade_id in auto_stop_triggered_trades}, ttc: {ttc_seconds}, min_ttc: {min_ttc_seconds}")
        
        # Debug logging for trade 2448
        if trade_id == 2448:
            log_debug(f"Trade {trade_id} conditions - prob_valid: {prob is not None}, prob_type: {type(prob)}, prob_lt_threshold: {float(prob) < threshold if prob is not None else 'N/A'}, status_active: {trade.get('status') == 'active'}, not_triggered: {trade_id not in auto_stop_triggered_trades}, ttc_valid: {ttc_seconds is not None}, ttc_ge_min: {ttc_seconds >= min_ttc_seconds if ttc_seconds is not None else 'N/A'}")
        
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
            log_debug(f"Trade {trade_id} - auto_stop_conditions_met: {auto_stop_conditions_met}")
        
        if auto_stop_conditions_met:
            # Debug logging for trade 2448
            if trade_id == 2448:
                log(f"[AUTO STOP HTC DEBUG] Trade 2448 - verification_enabled: {verification_enabled}")
            
            if verification_enabled:
                # Start verification period
                verification_end_time = current_time + verification_seconds
                verification_pending_trades[trade_id] = (current_time, verification_end_time)
                log(f"[AUTO STOP HTC] 🔍 Starting verification period for trade {trade_id} (prob={prob}, threshold={threshold}, verification_duration={verification_seconds}s)")
            else:
                # No verification - trigger immediately
                log(f"[AUTO STOP HTC] Triggering auto stop for trade {trade_id} (prob={prob}, ttc={ttc_seconds}s, min_ttc={min_ttc_seconds}s)")
                if trigger_auto_stop_close(trade):
                    auto_stop_triggered_trades.add(trade_id)
                else:
                    log(f"[AUTO STOP HTC] ❌ Auto stop failed for trade {trade_id}, will retry on next check")
        elif (
            prob is not None and
            (isinstance(prob, (int, float)) or hasattr(prob, '__float__')) and
            float(prob) < threshold and
            trade.get('status') == 'active' and
            trade_id not in auto_stop_triggered_trades and
            (ttc_seconds is None or ttc_seconds < min_ttc_seconds)
        ):
            log(f"[AUTO STOP HTC] Skipping auto stop for trade {trade_id} - TTC ({ttc_seconds}s) below minimum ({min_ttc_seconds}s)")

def check_auto_stop_conditions_momentum_scalp(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Check auto-stop conditions for Momentum Scalp strategy.
    Uses trailing stop and profit target logic instead of probability-based stops.
    """
    trailing_stop_amount = get_momentum_scalp_trailing_stop_amount()
    profit_target = get_momentum_scalp_profit_target()
    max_profit = get_max_profit()
    momentum_threshold = get_momentum_scalp_entry_threshold()
    current_time = time.time()
    
    # Get current momentum percentile for the monitor's symbol
    symbol = get_current_monitor_symbol()
    current_momentum_percentile = get_momentum_percentile_from_postgresql(symbol)
    
    for trade in active_trades:
        trade_id = trade.get('trade_id')
        current_close_price = trade.get('current_close_price')
        high_price = trade.get('high_price')
        buy_price = trade.get('buy_price')
        
        # Skip if required data is missing
        if current_close_price is None or high_price is None or buy_price is None:
            continue
        
        # Convert to float if needed
        try:
            current_close_price = float(current_close_price) if hasattr(current_close_price, '__float__') else current_close_price
            high_price = float(high_price) if hasattr(high_price, '__float__') else high_price
            buy_price = float(buy_price) if hasattr(buy_price, '__float__') else buy_price
        except (ValueError, TypeError):
            log(f"[AUTO STOP MS] ⚠️ Invalid price data for trade {trade_id}, skipping")
            continue
        
        # Calculate current position value: 1 - current_close_price
        current_position_value = 1.0 - current_close_price
        
        # Calculate profit target threshold: buy_price + profit_target (relative offset)
        profit_target_threshold = buy_price + profit_target
        
        # PRIORITY 1: Max profit check - immediate close, bypasses verification
        if trade.get('status') == 'active' and trade_id not in auto_stop_triggered_trades:
            if current_position_value >= max_profit:
                log(f"[AUTO STOP MS] 🚨 MAX PROFIT REACHED - Immediate close for trade {trade_id}")
                log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Max profit: {max_profit:.4f}")
                if trigger_auto_stop_close(trade):
                    auto_stop_triggered_trades.add(trade_id)
                    # Remove from verification if it was pending
                    if trade_id in verification_pending_trades:
                        del verification_pending_trades[trade_id]
                    continue
                else:
                    log(f"[AUTO STOP MS] ❌ Max profit auto stop failed for trade {trade_id}, will retry on next check")
                    continue
        
        # Check if trade is in verification period
        if trade_id in verification_pending_trades:
            trigger_time, verification_end_time = verification_pending_trades[trade_id]
            
            # Check if verification period has ended
            if current_time >= verification_end_time:
                # Re-check conditions after verification period
                trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
                # Profit target only triggers if momentum has fallen below threshold
                profit_target_triggered = False
                if current_position_value >= profit_target_threshold:
                    if current_momentum_percentile is not None:
                        # Only trigger if momentum is below threshold (absolute value check for both positive and negative)
                        if abs(current_momentum_percentile) < abs(momentum_threshold):
                            profit_target_triggered = True
                    else:
                        # If momentum data unavailable, don't trigger profit target
                        log(f"[AUTO STOP MS] ⚠️ Momentum data unavailable for trade {trade_id}, skipping profit target check")
                
                if trailing_stop_triggered or profit_target_triggered:
                    # Conditions still met after verification - trigger auto-stop
                    reason = "trailing stop" if trailing_stop_triggered else "profit target"
                    log(f"[AUTO STOP MS] ✅ Verification period ended - triggering auto stop for trade {trade_id} ({reason})")
                    log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    if current_momentum_percentile is not None:
                        log(f"[AUTO STOP MS]   Current momentum: {current_momentum_percentile:.2f}, Threshold: {momentum_threshold:.2f}")
                    if trigger_auto_stop_close(trade):
                        auto_stop_triggered_trades.add(trade_id)
                        del verification_pending_trades[trade_id]
                    else:
                        log(f"[AUTO STOP MS] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                        del verification_pending_trades[trade_id]
                else:
                    # Conditions no longer met - cancel verification
                    log(f"[AUTO STOP MS] ❌ Verification period ended - conditions no longer met for trade {trade_id}")
                    log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    if current_momentum_percentile is not None:
                        log(f"[AUTO STOP MS]   Current momentum: {current_momentum_percentile:.2f}, Threshold: {momentum_threshold:.2f} (momentum still above threshold, profit target not triggered)")
                    del verification_pending_trades[trade_id]
            else:
                # Still in verification period - just wait
                remaining_time = verification_end_time - current_time
                if not hasattr(check_auto_stop_conditions_momentum_scalp, 'last_verification_log') or current_time - check_auto_stop_conditions_momentum_scalp.last_verification_log > 10:
                    log(f"[AUTO STOP MS] ⏳ Trade {trade_id} in verification period - {remaining_time:.1f}s remaining")
                    check_auto_stop_conditions_momentum_scalp.last_verification_log = current_time
                continue
        
        # Check for new auto-stop conditions
        # Condition 1: Trailing stop - position value has dropped by trailing_stop_amount from high
        trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
        
        # Condition 2: Profit target - position value has reached or exceeded profit target threshold (buy_price + profit_target offset)
        # BUT only triggers if momentum has fallen below threshold
        profit_target_triggered = False
        if current_position_value >= profit_target_threshold:
            if current_momentum_percentile is not None:
                # Only trigger if momentum is below threshold (absolute value check for both positive and negative)
                if abs(current_momentum_percentile) < abs(momentum_threshold):
                    profit_target_triggered = True
            else:
                # If momentum data unavailable, don't trigger profit target
                log(f"[AUTO STOP MS] ⚠️ Momentum data unavailable for trade {trade_id}, skipping profit target check")
        
        auto_stop_conditions_met = (
            trade.get('status') == 'active' and
            trade_id not in auto_stop_triggered_trades and
            (trailing_stop_triggered or profit_target_triggered)
        )
        
        if auto_stop_conditions_met:
            reason = "trailing stop" if trailing_stop_triggered else "profit target"
            log(f"[AUTO STOP MS] 🎯 Triggering auto stop for trade {trade_id} ({reason})")
            log(f"[AUTO STOP MS]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
            if current_momentum_percentile is not None:
                log(f"[AUTO STOP MS]   Current momentum: {current_momentum_percentile:.2f}, Threshold: {momentum_threshold:.2f}")
            
            if trigger_auto_stop_close(trade):
                auto_stop_triggered_trades.add(trade_id)
            else:
                log(f"[AUTO STOP MS] ❌ Auto stop failed for trade {trade_id}, will retry on next check")

def check_auto_stop_conditions_momentum_reversal(active_trades, auto_stop_triggered_trades, verification_pending_trades):
    """
    Check auto-stop conditions for Momentum Reversal strategy.
    Uses trailing stop and profit target logic - NO momentum checks.
    Trade immediately goes into profit taking and stop loss monitoring mode.
    """
    trailing_stop_amount = get_momentum_scalp_trailing_stop_amount()
    profit_target = get_momentum_scalp_profit_target()
    max_profit = get_max_profit()
    current_time = time.time()
    
    for trade in active_trades:
        trade_id = trade.get('trade_id')
        current_close_price = trade.get('current_close_price')
        high_price = trade.get('high_price')
        buy_price = trade.get('buy_price')
        
        # Skip if required data is missing
        if current_close_price is None or high_price is None or buy_price is None:
            continue
        
        # Convert to float if needed
        try:
            current_close_price = float(current_close_price) if hasattr(current_close_price, '__float__') else current_close_price
            high_price = float(high_price) if hasattr(high_price, '__float__') else high_price
            buy_price = float(buy_price) if hasattr(buy_price, '__float__') else buy_price
        except (ValueError, TypeError):
            log(f"[AUTO STOP MR] ⚠️ Invalid price data for trade {trade_id}, skipping")
            continue
        
        # Calculate current position value: 1 - current_close_price
        current_position_value = 1.0 - current_close_price
        
        # Calculate profit target threshold: buy_price + profit_target (relative offset)
        profit_target_threshold = buy_price + profit_target
        
        # PRIORITY 1: Max profit check - immediate close, bypasses verification
        if trade.get('status') == 'active' and trade_id not in auto_stop_triggered_trades:
            if current_position_value >= max_profit:
                log(f"[AUTO STOP MR] 🚨 MAX PROFIT REACHED - Immediate close for trade {trade_id}")
                log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Max profit: {max_profit:.4f}")
                if trigger_auto_stop_close(trade):
                    auto_stop_triggered_trades.add(trade_id)
                    # Remove from verification if it was pending
                    if trade_id in verification_pending_trades:
                        del verification_pending_trades[trade_id]
                    continue
                else:
                    log(f"[AUTO STOP MR] ❌ Max profit auto stop failed for trade {trade_id}, will retry on next check")
                    continue
        
        # Check if trade is in verification period
        if trade_id in verification_pending_trades:
            trigger_time, verification_end_time = verification_pending_trades[trade_id]
            
            # Check if verification period has ended
            if current_time >= verification_end_time:
                # Re-check conditions after verification period
                trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
                # Profit target triggers immediately when reached (NO momentum check)
                profit_target_triggered = current_position_value >= profit_target_threshold
                
                if trailing_stop_triggered or profit_target_triggered:
                    # Conditions still met after verification - trigger auto-stop
                    reason = "trailing stop" if trailing_stop_triggered else "profit target"
                    log(f"[AUTO STOP MR] ✅ Verification period ended - triggering auto stop for trade {trade_id} ({reason})")
                    log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    if trigger_auto_stop_close(trade):
                        auto_stop_triggered_trades.add(trade_id)
                        del verification_pending_trades[trade_id]
                    else:
                        log(f"[AUTO STOP MR] ❌ Auto stop failed for trade {trade_id} after verification, will retry on next check")
                        del verification_pending_trades[trade_id]
                else:
                    # Conditions no longer met - cancel verification
                    log(f"[AUTO STOP MR] ❌ Verification period ended - conditions no longer met for trade {trade_id}")
                    log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
                    del verification_pending_trades[trade_id]
            else:
                # Still in verification period - just wait
                remaining_time = verification_end_time - current_time
                if not hasattr(check_auto_stop_conditions_momentum_reversal, 'last_verification_log') or current_time - check_auto_stop_conditions_momentum_reversal.last_verification_log > 10:
                    log(f"[AUTO STOP MR] ⏳ Trade {trade_id} in verification period - {remaining_time:.1f}s remaining")
                    check_auto_stop_conditions_momentum_reversal.last_verification_log = current_time
                continue
        
        # Check for new auto-stop conditions
        # Condition 1: Trailing stop - position value has dropped by trailing_stop_amount from high
        trailing_stop_triggered = current_position_value <= (high_price - trailing_stop_amount)
        
        # Condition 2: Profit target - position value has reached or exceeded profit target threshold (buy_price + profit_target offset)
        # NO momentum check - triggers immediately when reached
        profit_target_triggered = current_position_value >= profit_target_threshold
        
        auto_stop_conditions_met = (
            trade.get('status') == 'active' and
            trade_id not in auto_stop_triggered_trades and
            (trailing_stop_triggered or profit_target_triggered)
        )
        
        if auto_stop_conditions_met:
            reason = "trailing stop" if trailing_stop_triggered else "profit target"
            log(f"[AUTO STOP MR] 🎯 Triggering auto stop for trade {trade_id} ({reason})")
            log(f"[AUTO STOP MR]   Position value: {current_position_value:.4f}, Buy price: {buy_price:.4f}, High: {high_price:.4f}, Trailing stop threshold: {high_price - trailing_stop_amount:.4f}, Profit target threshold: {profit_target_threshold:.4f} (buy_price {buy_price:.4f} + offset {profit_target:.4f})")
            
            if trigger_auto_stop_close(trade):
                auto_stop_triggered_trades.add(trade_id)
            else:
                log(f"[AUTO STOP MR] ❌ Auto stop failed for trade {trade_id}, will retry on next check")

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