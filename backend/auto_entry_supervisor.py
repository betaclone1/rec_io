#!/usr/bin/env python3
"""
Auto Entry Supervisor - MONITOR-AWARE VERSION

Monitors strike table data directly and triggers automated trades when criteria are met.
Uses atomic operations to prevent rapid-fire trades.
Supports multiple monitors with monitor-specific configuration.

PRIMARY GATE: Now uses auto_trade boolean from monitor_list table instead of 
auto_entry from auto_trade_settings. Each monitor controls its own auto entry 
supervisor via the auto_trade toggle switch.
"""

import os
import json
import time
import threading
import requests
import random
import sys
import signal
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Any
from flask import Flask, request, jsonify
from flask_cors import CORS

# Add the project root to Python path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the universal centralized port system
from backend.core.port_config import get_port, get_monitor_port, register_monitor_ports
from backend.util.paths import get_host, get_data_dir, get_service_url, get_trade_history_dir

# Add these functions after the existing imports and before the get_monitor_identifier function

def create_monitor_watchlist_table_DELETED():
    """Create monitor-specific watchlist table when supervisor starts"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Create monitor-specific watchlist table
            watchlist_table = f"watchlist_{USER_NUMBER}_{MONITOR_ID}"
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS live_data.{watchlist_table} (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(10),
                    current_price DECIMAL(10,2),
                    ttc_seconds INTEGER,
                    broker VARCHAR(20),
                    event_ticker VARCHAR(50),
                    market_title VARCHAR(200),
                    strike_tier VARCHAR(20),
                    market_status VARCHAR(20),
                    strike DECIMAL(10,2),
                    buffer DECIMAL(10,2),
                    buffer_pct DECIMAL(5,2),
                    probability DECIMAL(5,2),
                    yes_ask INTEGER,
                    no_ask INTEGER,
                    yes_diff INTEGER,
                    no_diff INTEGER,
                    volume INTEGER,
                    ticker VARCHAR(50),
                    active_side VARCHAR(10),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()
        conn.close()
        log(f"[WATCHLIST] ✅ Created monitor-specific watchlist table: {watchlist_table}")
    except Exception as e:
        log(f"[WATCHLIST] ❌ Error creating watchlist table: {e}")

def drop_monitor_watchlist_table_DELETED():
    """Drop monitor-specific watchlist table when supervisor stops"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Drop monitor-specific watchlist table
            watchlist_table = f"watchlist_{USER_NUMBER}_{MONITOR_ID}"
            cursor.execute(f"DROP TABLE IF EXISTS live_data.{watchlist_table}")
            conn.commit()
        conn.close()
        log(f"[WATCHLIST] ✅ Dropped monitor-specific watchlist table: {watchlist_table}")
    except Exception as e:
        log(f"[WATCHLIST] ❌ Error dropping watchlist table: {e}")

# Monitor identification - extract from script name or command line args
def get_monitor_identifier():
    """Extract monitor identifier from script name or command line arguments"""
    script_name = os.path.basename(sys.argv[0])
    
    # Check if script name contains monitor identifier (e.g., auto_entry_supervisor_0001_10001)
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

print(f"[AUTO_ENTRY_SUPERVISOR_{MONITOR_IDENTIFIER}] 🚀 Monitor-aware supervisor starting")
print(f"[AUTO_ENTRY_SUPERVISOR_{MONITOR_IDENTIFIER}] User: {USER_NUMBER}, Monitor: {MONITOR_ID}")

# Get symbol for this monitor
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
            log(f"[AUTO_ENTRY_SUPERVISOR] ⚠️ No symbol found for monitor {MONITOR_IDENTIFIER}, defaulting to BTC")
            return "BTC"  # Default fallback
    except Exception as e:
        log(f"[AUTO_ENTRY_SUPERVISOR] ❌ Error getting monitor symbol: {e}, defaulting to BTC")
        return "BTC"  # Default fallback

# Get the symbol for this monitor (will be updated dynamically)
MONITOR_SYMBOL = get_monitor_symbol()
print(f"[AUTO_ENTRY_SUPERVISOR_{MONITOR_IDENTIFIER}] 📊 Initial symbol: {MONITOR_SYMBOL}")

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
                log(f"[AUTO_ENTRY_SUPERVISOR] 🔄 Symbol changed from {MONITOR_SYMBOL} to {new_symbol}")
                MONITOR_SYMBOL = new_symbol
            
            return new_symbol
        else:
            return "BTC"  # Default fallback
    except Exception as e:
        return "BTC"  # Default fallback

# Get port from monitor-specific system
# Register this monitor's ports to ensure consistency
register_monitor_ports(MONITOR_IDENTIFIER)

# Get monitor-specific port
AUTO_ENTRY_SUPERVISOR_PORT = get_monitor_port("auto_entry_supervisor", MONITOR_IDENTIFIER)
print(f"[AUTO_ENTRY_SUPERVISOR_{MONITOR_IDENTIFIER}] 🚀 Using monitor-specific port: {AUTO_ENTRY_SUPERVISOR_PORT}")

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global variable to track monitoring thread
monitoring_thread = None
monitoring_thread_lock = threading.Lock()

# SIMPLIFIED: Track last trade time per strike (atomic)
last_trade_times = {}  # strike_key -> timestamp

# Cooldown period (seconds)
TRADE_COOLDOWN = 10

# Global state for auto entry indicator (for frontend display)
auto_entry_indicator_state = {
    "enabled": False,
    "ttc_within_window": False,
    "scanning_active": False,  # NEW: True system-wide scanning status
    "service_healthy": False,  # NEW: Service health status
    "spike_alert_active": False,  # NEW: SPIKE ALERT state
    "spike_alert_start_time": None,  # NEW: When spike was detected
    "spike_alert_momentum_value": None,  # NEW: Momentum value when spike detected
    "spike_alert_recovery_countdown": None,  # NEW: Minutes until recovery
    "current_momentum": None,  # NEW: Current momentum value
    "current_ttc": 0,
    "min_time": 0,
    "max_time": 3600,
    "last_updated": None
}

# Track previous settings for change detection
previous_settings = None
previous_auto_trade_status = None

# Track previous state to detect changes
previous_indicator_state = None

# State tracking for logging reduction



# Database-based state management functions (PRIMARY SYSTEM)
def save_auto_entry_state_to_db(state):
    """Save auto entry state to production database"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='137.184.224.94',  # PRODUCTION SERVER
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # LEGACY REMOVED: auto_entry_status updates - now using auto_trade_status only
            # Update only cooldown and timestamp fields
            
            conn.commit()
        conn.close()
    except Exception as e:
        log(f"[AUTO ENTRY STATE DB] Error saving state to production database: {e}")

def load_auto_entry_state_from_db():
    """Load auto entry state from production database (timestamp-based cooldown)"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='137.184.224.94',  # PRODUCTION SERVER
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Get monitor's strategy and cooldown state
            cursor.execute("""
                SELECT strategy, cooldown_start_time, cooldown_timer, updated_at 
                FROM users.monitor_list_0001 WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if monitor_result:
                strategy_name, cooldown_start_time, cooldown_timer, updated_at = monitor_result
                
                # Get cooldown settings and time parameters from monitor
                cursor.execute("""
                    SELECT spike_alert_cooldown_minutes, min_time, max_time
                    FROM users.monitor_list_0001 WHERE id = %s
                """, (MONITOR_IDENTIFIER.split('_')[1],))
                strategy_result = cursor.fetchone()
                
                if strategy_result:
                    cooldown_minutes, min_time, max_time = strategy_result
                
                # Calculate remaining time based on timestamp
                spike_alert_active = False
                remaining_minutes = None
                
                if cooldown_start_time:
                    now = datetime.now(ZoneInfo("America/New_York"))
                    time_elapsed = (now - cooldown_start_time).total_seconds()
                    total_cooldown_seconds = cooldown_minutes * 60
                    remaining_seconds = max(0, total_cooldown_seconds - time_elapsed)
                    
                    if remaining_seconds > 0:
                        spike_alert_active = True
                        remaining_minutes = remaining_seconds / 60
                        
                        # Update cooldown_timer with calculated remaining seconds (monitor_list is now single source of truth)
                        cursor.execute(
                            "UPDATE users.monitor_list_0001 SET cooldown_timer = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                            (int(remaining_seconds), MONITOR_ID)
                        )
                        
                        conn.commit()
                        
                        # Notify frontend of cooldown timer change
                        try:
                            port = get_port("main_app")
                            url = f"http://localhost:{port}/api/notify_cooldown_timer_change"
                            # Send full monitor ID format that dashboard expects (mon_0001_10002) - lowercase
                            full_monitor_id = f"mon_{USER_NUMBER}_{MONITOR_ID}"
                            response = requests.post(url, json={
                                "monitor_id": full_monitor_id,
                                "cooldown_timer": int(remaining_seconds)
                            }, timeout=2)
                            if response.ok:
                                log(f"[AUTO ENTRY] ✅ Cooldown timer change notification sent: monitor_id={full_monitor_id}, timer={remaining_seconds}")
                            else:
                                log(f"[AUTO ENTRY] ⚠️ Failed to send cooldown timer notification: {response.status_code}")
                        except Exception as e:
                            log(f"[AUTO ENTRY] ❌ Error sending cooldown timer notification: {e}")
                    else:
                        # Cooldown has expired, clear the start time (monitor_list is now single source of truth)
                        cursor.execute(
                            "UPDATE users.monitor_list_0001 SET cooldown_start_time = NULL, cooldown_timer = 0, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                            (MONITOR_ID,)
                        )
                        
                        conn.commit()
                
                state = {
                    "user_id": "user_0001",
                    "monitor_id": "default",
                    "enabled": False,
                    "scanning_active": False,
                    "spike_alert_active": spike_alert_active,
                    "spike_alert_start_time": cooldown_start_time.isoformat() if spike_alert_active and cooldown_start_time else None,
                    "spike_alert_momentum_value": None,  # Not stored in DB
                    "spike_alert_recovery_countdown": remaining_minutes,
                    "current_momentum": None,
                    "current_ttc": 0,
                    "min_time": min_time,
                    "max_time": max_time,
                    "last_updated": updated_at.isoformat() if updated_at else None
                }

                return state
        conn.close()
    except Exception as e:
        log(f"[AUTO ENTRY STATE DB] Error loading state from production database: {e}")
    
    return None


# LEGACY REMOVED: previous_auto_entry_status - now using auto_trade_status only

# SPIKE ALERT constants - NO DEFAULTS, must get from settings
# These will be loaded from auto_entry_settings.json

def log(message: str):
    """Log messages with timestamp and monitor identifier"""
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[AUTO_ENTRY_SUPERVISOR_{MONITOR_IDENTIFIER} {timestamp}] {message}"
    
    # Print to console (for existing functionality)
    print(log_message)
    
    # Also write to log file
    try:
        log_file_path = f"/opt/rec_io_server/logs/auto_entry_supervisor_{MONITOR_IDENTIFIER}.log"
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(log_message + "\n")
    except Exception as e:
        # Don't break the system if logging fails
        print(f"[LOGGING ERROR] Failed to write to log file: {e}")

def log_heartbeat():
    """Log heartbeat every 5 minutes with system status"""
    try:
        # Get current system status
        auto_trade_enabled = is_auto_trade_enabled()
        current_symbol = get_current_monitor_symbol()
        
        # Get current momentum
        current_momentum = get_current_momentum(current_symbol)
        momentum_str = f"{current_momentum:.2f}" if current_momentum is not None else "N/A"
        
        # Get cooldown status
        cooldown_timer = 0
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.getenv('POSTGRES_HOST', 'localhost'),
                database=os.getenv('POSTGRES_DB', 'rec_io_db'),
                user=os.getenv('POSTGRES_USER', 'rec_io_user'),
                password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT cooldown_timer FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
                result = cursor.fetchone()
                cooldown_timer = result[0] if result and result[0] is not None else 0
            conn.close()
        except Exception:
            cooldown_timer = 0
        
        cooldown_str = f"{cooldown_timer}s" if cooldown_timer > 0 else "None"
        
        log(f"💓 HEARTBEAT | Auto Trade: {auto_trade_enabled} | Symbol: {current_symbol} | Momentum: {momentum_str} | Cooldown: {cooldown_str}")
        
    except Exception as e:
        log(f"💓 HEARTBEAT | Error getting status: {e}")

# Legacy auto_entry_state.json functionality removed - now using PostgreSQL for all state management

def get_current_momentum(symbol="BTC"):
    """Get current momentum percentile from strike table for specified symbol"""
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
        
        # Get momentum percentile from strike table (same value across all rows)
        cursor.execute(f"""
            SELECT momentum_percentile FROM live_data.strike_table_{symbol.lower()} 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_percentile = float(result[0])
            return momentum_percentile
        else:
            return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum for {symbol}: {e}")
        return None

def check_spike_alert_conditions():
    """Check if spike alert conditions are met and update state accordingly"""
    global auto_entry_indicator_state
    
    try:
        # Get current momentum for this monitor's symbol
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        if current_momentum is None:
            return
        
        # Update current momentum in state
        auto_entry_indicator_state["current_momentum"] = current_momentum
        
        # Load current state from database (PHASE 2: Replaced JSON with DB)
        state = load_auto_entry_state_from_db()
        if state is None:
            # Initialize state if file not found (should ideally not happen if load_auto_entry_state handles defaults)
            state = {
                "user_id": "user_0001",
                "monitor_id": "default",
                "enabled": False,
                "scanning_active": False,
                "spike_alert_active": False,
                "spike_alert_start_time": None,
                "spike_alert_momentum_value": None,
                "spike_alert_recovery_countdown": None,
                "current_momentum": current_momentum,
                "current_ttc": 0,
                "min_time": 0,
                "max_time": 3600,
                "last_updated": None
            }
        
        # Get spike alert settings from auto entry settings - NO DEFAULTS
        settings = get_auto_entry_settings()
        
        # Check if all required spike alert settings exist
        required_settings = [
            "spike_alert_enabled",
            "spike_alert_momentum_threshold", 
            "spike_alert_cooldown_threshold",
            "spike_alert_cooldown_minutes"
        ]
        
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[SPIKE ALERT] ❌ Missing required settings: {missing_settings}")
            log(f"[SPIKE ALERT] Cannot proceed without complete settings configuration")
            return
        
        spike_alert_enabled = settings["spike_alert_enabled"]
        spike_threshold = settings["spike_alert_momentum_threshold"]  # Already in percentile (0-100)
        cooldown_threshold = settings["spike_alert_cooldown_threshold"]  # Already in percentile (0-100)
        cooldown_minutes = settings["spike_alert_cooldown_minutes"]
        
        # Skip spike alert if disabled
        if not spike_alert_enabled:
            # Reset any active spike alert
            if state["spike_alert_active"]:
                state["spike_alert_active"] = False
                state["spike_alert_start_time"] = None
                state["spike_alert_momentum_value"] = None
                state["spike_alert_recovery_countdown"] = None
                log(f"[SPIKE ALERT] Disabled - clearing any active spike alert")
            
            # Update global state for frontend
            auto_entry_indicator_state.update({
                "spike_alert_active": False,
                "spike_alert_start_time": None,
                "spike_alert_momentum_value": None,
                "spike_alert_recovery_countdown": None,
                "current_momentum": state["current_momentum"]
            })
            
            # Save updated state to database (PHASE 2: Replaced JSON with DB)
            save_auto_entry_state_to_db(state)
            return
        
        # Check for spike detection using settings
        spike_detected = (current_momentum >= spike_threshold or 
                         current_momentum <= -spike_threshold)
        
        # Check for recovery conditions using settings
        recovery_conditions_met = (current_momentum < cooldown_threshold and 
                                  current_momentum > -cooldown_threshold)
        
        now = datetime.now(ZoneInfo("America/New_York"))
        
        if spike_detected and not state["spike_alert_active"]:
            # SPIKE DETECTED - Enter spike alert mode
            state["spike_alert_active"] = True
            state["spike_alert_start_time"] = now.isoformat()
            state["spike_alert_momentum_value"] = current_momentum
            state["spike_alert_recovery_countdown"] = cooldown_minutes
            
            # Start cooldown period in database (timestamp-based)
            start_cooldown_period_in_db()
            
            log(f"[SPIKE ALERT] 🚨 SPIKE DETECTED! Momentum: {current_momentum:.2f} (threshold: ±{spike_threshold})")
            log(f"[SPIKE ALERT] Auto entry PAUSED for {cooldown_minutes} minutes")
            
        elif state["spike_alert_active"]:
            if recovery_conditions_met:
                # Check if recovery duration has passed
                if state["spike_alert_start_time"]:
                    spike_start = datetime.fromisoformat(state["spike_alert_start_time"])
                    time_in_recovery = (now - spike_start).total_seconds() / 60
                    
                    if time_in_recovery >= cooldown_minutes:
                        # RECOVERY COMPLETE - Exit spike alert mode
                        state["spike_alert_active"] = False
                        state["spike_alert_start_time"] = None
                        state["spike_alert_momentum_value"] = None
                        state["spike_alert_recovery_countdown"] = None
                        
                        # Reset cooldown period in database
                        reset_cooldown_period_in_db()
                        
                        log(f"[SPIKE ALERT] ✅ RECOVERY COMPLETE! Auto entry RESUMED")
                        log(f"[SPIKE ALERT] Recovery time: {time_in_recovery:.1f} minutes")
                    else:
                        # Still in recovery period - calculate remaining time
                        remaining_minutes = cooldown_minutes - time_in_recovery
                        state["spike_alert_recovery_countdown"] = remaining_minutes
                        
                        log(f"[SPIKE ALERT] ⏳ Recovery in progress: {remaining_minutes:.1f} minutes remaining")
                else:
                    # Reset recovery countdown if start time is missing
                    state["spike_alert_recovery_countdown"] = cooldown_minutes
            else:
                # Still in spike conditions - reset recovery timer
                state["spike_alert_start_time"] = now.isoformat()
                state["spike_alert_recovery_countdown"] = cooldown_minutes
                
                # Reset cooldown period in database
                start_cooldown_period_in_db()
                
                log(f"[SPIKE ALERT] ⚠️ Still in spike conditions: {current_momentum:.2f} - resetting timer to {cooldown_minutes} minutes")
        
        # Update current momentum in loaded state
        state["current_momentum"] = current_momentum
        
        # Update global state for frontend
        auto_entry_indicator_state.update({
            "spike_alert_active": state["spike_alert_active"],
            "spike_alert_start_time": state["spike_alert_start_time"],
            "spike_alert_momentum_value": state["spike_alert_momentum_value"],
            "spike_alert_recovery_countdown": state["spike_alert_recovery_countdown"],
            "current_momentum": state["current_momentum"]
        })
        
        # Save updated state to database (PHASE 2: Replaced JSON with DB)
        save_auto_entry_state_to_db(state)
        
    except Exception as e:
        log(f"[SPIKE ALERT] Error checking spike conditions: {e}")

def start_cooldown_period_in_db():
    """Start a new cooldown period in the database (uses existing spike_alert_cooldown_minutes setting)"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='137.184.224.94',  # PRODUCTION SERVER
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Update the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                "UPDATE users.monitor_list_0001 SET cooldown_start_time = NOW(), updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (MONITOR_ID,)
            )
            
            conn.commit()
        conn.close()
        log(f"[AUTO ENTRY] ✅ Started cooldown period in production database")
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error starting cooldown period: {e}")

def reset_cooldown_period_in_db():
    """Reset/clear the cooldown period in the database"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='137.184.224.94',  # PRODUCTION SERVER
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Reset the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                "UPDATE users.monitor_list_0001 SET cooldown_start_time = NULL, cooldown_timer = 0, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (MONITOR_ID,)
            )
            
            conn.commit()
        conn.close()
        log(f"[AUTO ENTRY] ✅ Reset cooldown period in production database")
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error resetting cooldown period: {e}")

# Legacy function for backward compatibility (will be removed)
def update_cooldown_timer_in_db(seconds):
    """Update cooldown_timer in the database (LEGACY - will be removed)"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host='137.184.224.94',  # PRODUCTION SERVER
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Update the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                "UPDATE users.monitor_list_0001 SET cooldown_timer = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (seconds, MONITOR_ID)
            )
            
            conn.commit()
        conn.close()
        log(f"[AUTO ENTRY] ✅ Updated cooldown_timer to {seconds} seconds in production database (LEGACY)")
        
        # Notify frontend of cooldown timer change
        try:
            port = get_port("main_app")
            url = f"http://localhost:{port}/api/notify_cooldown_timer_change"
            # Send full monitor ID format that dashboard expects (mon_0001_10002) - lowercase
            full_monitor_id = f"mon_{USER_NUMBER}_{MONITOR_ID}"
            response = requests.post(url, json={
                "monitor_id": full_monitor_id,
                "cooldown_timer": seconds
            }, timeout=2)
            if response.ok:
                log(f"[AUTO ENTRY] ✅ Cooldown timer change notification sent: monitor_id={full_monitor_id}, timer={seconds}")
            else:
                log(f"[AUTO ENTRY] ⚠️ Failed to send cooldown timer notification: {response.status_code}")
        except Exception as e:
            log(f"[AUTO ENTRY] ❌ Error sending cooldown timer notification: {e}")
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error updating cooldown_timer: {e}")

def update_auto_entry_status_in_db(status):
    """Update auto trade status in the monitor_list table"""
    global previous_auto_trade_status
    try:
        # Only log if status actually changed
        if previous_auto_trade_status != status:
            log(f"[AUTO ENTRY] 🔄 STATUS CHANGE | Monitor {MONITOR_ID} | {previous_auto_trade_status} → {status}")
            previous_auto_trade_status = status
        
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Update the monitor's auto_trade_status field (this is what the frontend reads)
            cursor.execute(
                "UPDATE users.monitor_list_0001 SET auto_trade_status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (status, MONITOR_ID)
            )
            conn.commit()
        conn.close()
        # Only log actual status changes, not every update
        pass
        
        # Send WebSocket notification that the database has been updated
        try:
            port = get_port("main_app")
            url = f"http://localhost:{port}/api/notify_auto_trade_status_change"
            # Send full monitor ID format that dashboard expects (mon_0001_10002) - lowercase
            full_monitor_id = f"mon_{USER_NUMBER}_{MONITOR_ID}"
            response = requests.post(url, json={
                "monitor_id": full_monitor_id,
                "auto_trade_status": status
            }, timeout=2)
            if not response.ok:
                log(f"[AUTO ENTRY] ⚠️ Failed to send WebSocket notification: {response.status_code}")
        except Exception as e:
            # Don't log connection errors every second - they're expected when main app is down
            pass
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error updating auto_trade_status in database: {e}")

def determine_auto_entry_status():
    """Determine the current auto entry status based on conditions"""
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (blocks all trades)
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        
        if spike_alert_active:
            return "PAUSED"  # Spike alert active
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time", "min_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if ttc_within_window:
            return "ACTIVE"
        else:
            return "INACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error determining status: {e}")
        return "DISABLED"

def broadcast_auto_entry_indicator_change():
    """Broadcast auto entry indicator state change via WebSocket to main app"""
    global auto_entry_indicator_state, previous_indicator_state
    
    try:
        # Determine and update database status first
        new_status = determine_auto_entry_status()
        
        # Update the database with the new status
        update_auto_entry_status_in_db(new_status)
        
        # Get cooldown timer from database
        cooldown_timer = 0
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.getenv('POSTGRES_HOST', 'localhost'),
                database=os.getenv('POSTGRES_DB', 'rec_io_db'),
                user=os.getenv('POSTGRES_USER', 'rec_io_user'),
                password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT cooldown_timer FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
                result = cursor.fetchone()
                cooldown_timer = result[0] if result and result[0] is not None else 0
            conn.close()
        except Exception as e:
            log(f"[AUTO ENTRY] ❌ Error getting cooldown timer: {e}")
        
        # Create broadcast data with database status
        broadcast_data = {
            "status": new_status,
            "cooldown_timer": cooldown_timer,
            "enabled": auto_entry_indicator_state["enabled"],
            "ttc_within_window": auto_entry_indicator_state["ttc_within_window"],
            "scanning_active": auto_entry_indicator_state["scanning_active"],
            "service_healthy": auto_entry_indicator_state["service_healthy"],
            "spike_alert_active": auto_entry_indicator_state["spike_alert_active"],
            "spike_alert_start_time": auto_entry_indicator_state["spike_alert_start_time"],
            "spike_alert_momentum_value": auto_entry_indicator_state["spike_alert_momentum_value"],
            "spike_alert_recovery_countdown": auto_entry_indicator_state["spike_alert_recovery_countdown"],
            "current_momentum": auto_entry_indicator_state["current_momentum"]
        }
        
        # Check if state has actually changed (compare with previous)
        current_state_key = (new_status, cooldown_timer)
        if previous_indicator_state == current_state_key:
            return  # No change, don't broadcast
        
        # Update previous state
        previous_indicator_state = current_state_key
        log(f"[AUTO ENTRY DEBUG]   State changed, broadcasting...")
        
        # COMMENTED OUT: Legacy auto_entry_indicator_change WebSocket notification - now using auto_trade_status_change only
        # try:
        #     port = get_port("main_app")
        #     url = f"http://localhost:{port}/api/broadcast_auto_entry_indicator"
        #     response = requests.post(url, json=broadcast_data, timeout=2)
        #     if response.ok:
        #         log(f"[AUTO ENTRY] ✅ Auto entry indicator change broadcasted: status={new_status}, cooldown={cooldown_timer}")
        #     else:
        #         log(f"[AUTO ENTRY] ⚠️ Failed to broadcast indicator change: {response.status_code}")
        # except Exception as e:
        #     log(f"[AUTO ENTRY] ❌ Error broadcasting indicator change: {e}")
        
        # ALSO send auto_trade_status_change notification to the new WebSocket channel
        try:
            port = get_port("main_app")
            url = f"http://localhost:{port}/api/notify_auto_trade_status_change"
            # Send full monitor ID format that dashboard expects (mon_0001_10002) - lowercase
            full_monitor_id = f"mon_{USER_NUMBER}_{MONITOR_ID}"
            response = requests.post(url, json={
                "monitor_id": full_monitor_id,
                "auto_trade_status": new_status
            }, timeout=2)
            if response.ok:
                log(f"[AUTO ENTRY] ✅ Auto trade status change notification sent: monitor_id={full_monitor_id}, status={new_status}")
            else:
                log(f"[AUTO ENTRY] ⚠️ Failed to send auto trade status notification: {response.status_code}")
        except Exception as e:
            log(f"[AUTO ENTRY] ❌ Error sending auto trade status notification: {e}")
            
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error in broadcast_auto_entry_indicator_change: {e}")

def is_auto_trade_enabled():
    """Check if AUTO ENTRY is enabled by checking auto_trade boolean in monitor_list"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'), 
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Check auto_trade boolean from the specific monitor's row in monitor_list
            cursor.execute("SELECT auto_trade FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                auto_trade_enabled = result[0]
                # Only log status changes, not every check
                return auto_trade_enabled
            else:
                log(f"[AUTO ENTRY] No monitor found with ID {MONITOR_ID} in monitor_list")
                return False
    except Exception as e:
        log(f"[AUTO ENTRY] Error reading auto_trade from monitor_list: {e}")
        return False

def get_auto_entry_settings():
    """Get auto entry settings from monitor's assigned strategy"""
    global previous_settings
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'), 
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Get monitor's strategy
            cursor.execute("""
                SELECT strategy FROM users.monitor_list_0001 WHERE id = %s
            """, (MONITOR_ID,))
            monitor_result = cursor.fetchone()
            
            if monitor_result:
                strategy_name = monitor_result[0]
                
                # Get monitor parameters
                cursor.execute("""
                    SELECT min_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
                           spike_alert_enabled, spike_alert_momentum_threshold, 
                           spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                           min_volume
                    FROM users.monitor_list_0001 WHERE id = %s
                """, (MONITOR_IDENTIFIER.split('_')[1],))
                strategy_result = cursor.fetchone()
                
                if strategy_result:
                    settings = {
                        "min_probability": strategy_result[0],
                        "min_differential": float(strategy_result[1]),
                        "max_differential": float(strategy_result[2]) if strategy_result[2] is not None else None,
                        "min_time": strategy_result[3],
                        "max_time": strategy_result[4],
                        "allow_re_entry": strategy_result[5],
                        "spike_alert_enabled": strategy_result[6],
                        "spike_alert_momentum_threshold": strategy_result[7],
                        "spike_alert_cooldown_threshold": strategy_result[8],
                        "spike_alert_cooldown_minutes": strategy_result[9],
                        "min_volume": strategy_result[10],  # From monitor min_volume
                        "max_ask": 98  # Default value
                    }
                    
                    # Check for settings changes
                    if previous_settings is not None:
                        changed_settings = []
                        for key, value in settings.items():
                            if key not in previous_settings or previous_settings[key] != value:
                                changed_settings.append(f"{key}: {previous_settings.get(key, 'None')} → {value}")
                        
                        if changed_settings:
                            log(f"[AUTO ENTRY] 🔧 SETTINGS CHANGED | Monitor {MONITOR_IDENTIFIER} | Changes: {'; '.join(changed_settings)}")
                    
                    previous_settings = settings.copy()
                    # Only log settings loading on first load or when settings change
                    if previous_settings is None:
                        log(f"[AUTO ENTRY] ✅ Loaded settings from monitor: {MONITOR_IDENTIFIER}")
                    return settings
                else:
                    log(f"[AUTO ENTRY] No monitor found with ID: {MONITOR_IDENTIFIER.split('_')[1]}")
                    return {}
            else:
                log(f"[AUTO ENTRY] No monitor found with ID: {MONITOR_ID}")
                return {}
    except Exception as e:
        log(f"[AUTO ENTRY] Error reading settings from strategy: {e}")
        return {}

def get_current_ttc():
    """Get current TTC from unified TTC endpoint"""
    try:
        port = get_port("main_app")
        current_symbol = get_current_monitor_symbol()
        url = f"http://localhost:{port}/api/unified_ttc/{current_symbol.lower()}"
        response = requests.get(url, timeout=2)
        if response.ok:
            data = response.json()
            ttc = data.get("ttc_seconds", 0)
            return ttc
        else:
            # Don't log TTC request failures - they're expected when main app is down
            return 0
    except Exception as e:
        # Don't log connection errors every second - they're expected when main app is down
        return 0

def get_strike_table_path():
    """Get the path to the master strike table JSON file"""
    current_symbol = get_current_monitor_symbol()
    return os.path.join(get_data_dir(), "live_data", "markets", "kalshi", "strike_tables", f"strike_table_{current_symbol.lower()}.json")

def get_watchlist_path_DELETED():
    """Get the path to the watchlist JSON file"""
    current_symbol = get_current_monitor_symbol()
    return os.path.join(get_data_dir(), "live_data", "markets", "kalshi", "strike_tables", f"{current_symbol.lower()}_watchlist.json")

def get_master_strike_table_data():
    """Get current master strike table data from PostgreSQL"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            current_symbol = get_current_monitor_symbol()
            cursor.execute(f"""
                SELECT
                    symbol,
                    current_price,
                    ttc_seconds,
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status
                FROM live_data.strike_table_{current_symbol.lower()}
                LIMIT 1
            """)
            header_data = cursor.fetchone()
            if not header_data:
                log(f"[WATCHLIST] No strike table data found in PostgreSQL")
                return None
            cursor.execute(f"""
                SELECT
                    strike,
                    buffer,
                    buffer_pct,
                    probability,
                    yes_ask,
                    no_ask,
                    volume,
                    ticker,
                    yes_diff,
                    no_diff,
                    active_side
                FROM live_data.strike_table_{current_symbol.lower()}
                ORDER BY strike
            """)
            strikes_data = cursor.fetchall()
            response = {
                "symbol": header_data[0],
                "current_price": float(header_data[1]) if header_data[1] else None,
                "ttc": int(header_data[2]) if header_data[2] else None,
                "event_ticker": header_data[3],
                "market_title": header_data[4],
                "strike_tier": header_data[5],
                "market_status": header_data[6],
                "strikes": []
            }
            for strike_row in strikes_data:
                strike_data = {
                    "strike": float(strike_row[0]) if strike_row[0] else None,
                    "buffer": float(strike_row[1]) if strike_row[1] else None,
                    "buffer_pct": float(strike_row[2]) if strike_row[2] else None,
                    "probability": float(strike_row[3]) if strike_row[3] else None,
                    "yes_ask": int(strike_row[4]) if strike_row[4] else None,
                    "no_ask": int(strike_row[5]) if strike_row[5] else None,
                    "volume": int(strike_row[6]) if strike_row[6] else None,
                    "ticker": strike_row[7],
                    "yes_diff": float(strike_row[8]) if strike_row[8] else None,
                    "no_diff": float(strike_row[9]) if strike_row[9] else None,
                    "active_side": strike_row[10]
                }
                response["strikes"].append(strike_data)
            conn.close()
            return response
    except Exception as e:
        log(f"[WATCHLIST] Error reading master strike table data from PostgreSQL: {e}")
        return None

def generate_watchlist_from_strike_table_DELETED():
    """Generate watchlist by filtering the master strike table based on auto entry settings"""
    try:
        # Get master strike table data
        strike_table_data = get_master_strike_table_data()
        if not strike_table_data or "strikes" not in strike_table_data:
            log(f"[WATCHLIST] No master strike table data available")
            return False
        
        current_price = strike_table_data.get("current_price")
        ttc_seconds = strike_table_data.get("ttc")
        strikes = strike_table_data["strikes"]
        market_data = {
            "event_ticker": strike_table_data.get("event_ticker"),
            "event_title": strike_table_data.get("market_title"),
            "strike_tier": strike_table_data.get("strike_tier"),
            "market_status": strike_table_data.get("market_status")
        }
        
        # Load auto entry settings for filter parameters
        settings = get_auto_entry_settings()
        if not settings:
            log(f"[WATCHLIST] No auto entry settings available")
            return False
        
        min_volume = settings.get("watchlist_min_volume", 1000)
        max_ask = settings.get("watchlist_max_ask", 98)
        min_probability = settings.get("min_probability", 0) - 5  # Subtract 5 from min_probability
        min_differential = settings.get("min_differential", 0) - 3  # Subtract 3 from min_differential
        max_differential = settings.get("max_differential", None)  # No default, use None if not set
        
        # Check if settings have changed
        max_diff_str = f", max_diff={max_differential}" if max_differential is not None else ""
        current_settings = f"min_prob={min_probability}, min_diff={min_differential}{max_diff_str}, min_vol={min_volume}, max_ask={max_ask}"
        global previous_watchlist_settings
        if previous_watchlist_settings != current_settings:
            log(f"[WATCHLIST] Filtering with settings: {current_settings}")
            previous_watchlist_settings = current_settings
        
        # Filter strikes for watchlist
        filtered_strikes = []
        for strike in strikes:
            volume = strike.get("volume")
            probability = strike.get("probability")
            yes_ask = strike.get("yes_ask")
            no_ask = strike.get("no_ask")
            yes_diff = strike.get("yes_diff")
            no_diff = strike.get("no_diff")
            
            if (volume is None or probability is None or 
                yes_ask is None or no_ask is None or
                yes_diff is None or no_diff is None):
                continue
            
            # Get the higher of yes_ask and no_ask
            max_ask_price = max(yes_ask, no_ask)
            
            # Determine which side would be the active buy button
            is_above_money_line = strike.get("strike", 0) > current_price
            
            # Get the active button's differential
            active_diff = no_diff if is_above_money_line else yes_diff
            
            # Check if at least one side meets the differential requirement
            yes_diff_ok = yes_diff >= min_differential
            no_diff_ok = no_diff >= min_differential
            at_least_one_diff_ok = yes_diff_ok or no_diff_ok
            
            # Check max_differential constraint on active side
            max_diff_ok = True  # Default to True if max_differential is not set
            if max_differential is not None:
                # Check the active side's differential against max_differential
                if is_above_money_line:
                    # Above money line: active side is NO
                    max_diff_ok = no_diff <= max_differential
                else:
                    # Below money line: active side is YES
                    max_diff_ok = yes_diff <= max_differential
            
            # Apply filter criteria from auto entry settings
            volume_ok = volume >= min_volume
            probability_ok = probability > min_probability
            ask_ok = max_ask_price <= max_ask
            
            if (volume_ok and probability_ok and ask_ok and at_least_one_diff_ok and max_diff_ok):
                filtered_strikes.append(strike)
        
        # Sort by probability (highest to lowest)
        filtered_strikes.sort(key=lambda x: x.get("probability", 0), reverse=True)
        
        # Create watchlist output
        current_symbol = get_current_monitor_symbol()
        watchlist_output = {
            "symbol": current_symbol,
            "current_price": current_price,
            "ttc": ttc_seconds,
            "broker": "Kalshi",
            "event_ticker": market_data.get("event_ticker"),
            "market_title": market_data.get("event_title"),
            "strike_tier": market_data.get("strike_tier"),
            "market_status": market_data.get("market_status"),
            "last_updated": datetime.now().isoformat(),
            "strikes": filtered_strikes
        }
        
        # Write watchlist to PostgreSQL using monitor-specific table
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.getenv('POSTGRES_HOST', 'localhost'),
                database=os.getenv('POSTGRES_DB', 'rec_io_db'),
                user=os.getenv('POSTGRES_USER', 'rec_io_user'),
                password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
            )
            with conn.cursor() as cursor:
                # Use monitor-specific watchlist table
                watchlist_table = f"watchlist_{USER_NUMBER}_{MONITOR_ID}"
                
                # Clear existing watchlist data for this monitor
                cursor.execute(f"DELETE FROM live_data.{watchlist_table}")
                
                # Insert filtered strikes into monitor-specific watchlist table
                for strike in filtered_strikes:
                    cursor.execute(f"""
                        INSERT INTO live_data.{watchlist_table} (
                            symbol, current_price, ttc_seconds, broker, event_ticker,
                            market_title, strike_tier, market_status, strike, buffer,
                            buffer_pct, probability, yes_ask, no_ask, yes_diff, no_diff,
                            volume, ticker, active_side
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        current_symbol, current_price, ttc_seconds, "Kalshi", market_data.get("event_ticker"),
                        market_data.get("event_title"), market_data.get("strike_tier"),
                        market_data.get("market_status"), strike.get("strike"), strike.get("buffer"),
                        strike.get("buffer_pct"), strike.get("probability"), strike.get("yes_ask"),
                        strike.get("no_ask"), strike.get("yes_diff"), strike.get("no_diff"),
                        strike.get("volume"), strike.get("ticker"), strike.get("active_side")
                    ))
                conn.commit()
                conn.close()
                return True
        except Exception as e:
            log(f"[WATCHLIST] Error writing to PostgreSQL: {e}")
            return False
        
    except Exception as e:
        log(f"[WATCHLIST] Error generating watchlist: {e}")
        return False

def get_watchlist_data_DELETED():
    """Get current watchlist data from monitor-specific PostgreSQL table"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Use monitor-specific watchlist table
            watchlist_table = f"watchlist_{USER_NUMBER}_{MONITOR_ID}"
            cursor.execute(f"""
                SELECT
                    symbol,
                    current_price,
                    ttc_seconds,
                    broker,
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status
                FROM live_data.{watchlist_table}
                LIMIT 1
            """)
            header_data = cursor.fetchone()
            if not header_data:
                # No watchlist data - this is normal when no strikes meet filter criteria
                return None
            cursor.execute(f"""
                SELECT
                    strike,
                    buffer,
                    buffer_pct,
                    probability,
                    yes_ask,
                    no_ask,
                    yes_diff,
                    no_diff,
                    volume,
                    ticker,
                    active_side
                FROM live_data.{watchlist_table}
                ORDER BY probability DESC
            """)
            strikes_data = cursor.fetchall()
            response = {
                "symbol": header_data[0],
                "current_price": float(header_data[1]) if header_data[1] else None,
                "ttc": int(header_data[2]) if header_data[2] else None,
                "broker": header_data[3],
                "event_ticker": header_data[4],
                "market_title": header_data[5],
                "strike_tier": header_data[6],
                "market_status": header_data[7],
                "strikes": []
            }
            for strike_row in strikes_data:
                strike_data = {
                    "strike": float(strike_row[0]) if strike_row[0] else None,
                    "buffer": float(strike_row[1]) if strike_row[1] else None,
                    "buffer_pct": float(strike_row[2]) if strike_row[2] else None,
                    "probability": float(strike_row[3]) if strike_row[3] else None,
                    "yes_ask": int(strike_row[4]) if strike_row[4] else None,
                    "no_ask": int(strike_row[5]) if strike_row[5] else None,
                    "yes_diff": float(strike_row[6]) if strike_row[6] else None,
                    "no_diff": float(strike_row[7]) if strike_row[7] else None,
                    "volume": int(strike_row[8]) if strike_row[8] else None,
                    "ticker": strike_row[9],
                    "active_side": strike_row[10]
                }
                response["strikes"].append(strike_data)
            conn.close()
            return response
    except Exception as e:
        log(f"[AUTO ENTRY] Error reading watchlist data from PostgreSQL: {e}")
        return None

def get_position_size():
    """Get total position size from monitor-specific configuration"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT total_position FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                total_position = result[0]
                log(f"[AUTO ENTRY] Total position loaded from monitor {MONITOR_ID}: {total_position}")
                return total_position
            else:
                log(f"[AUTO ENTRY] No monitor configuration found for monitor {MONITOR_ID}")
                return None
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading total position from monitor {MONITOR_ID}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_trade_strategy():
    """Get trade strategy from monitor-specific configuration"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT strategy FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                trade_strategy = result[0]
                log(f"[AUTO ENTRY] Trade strategy loaded from monitor {MONITOR_ID}: {trade_strategy}")
                return trade_strategy
            else:
                log(f"[AUTO ENTRY] No monitor configuration found for monitor {MONITOR_ID}")
                return "Hourly HTC"  # Default fallback
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading trade strategy from monitor {MONITOR_ID}: {e}")
        return "Hourly HTC"  # Default fallback
    finally:
        if conn:
            conn.close()

def get_bankroll_allotment():
    """Get bankroll allotment total from monitor-specific configuration"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT bankroll_allotment_total FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                bankroll_allotment = result[0]
                log(f"[AUTO ENTRY] Bankroll allotment loaded from monitor {MONITOR_ID}: {bankroll_allotment}")
                return bankroll_allotment
            else:
                log(f"[AUTO ENTRY] No monitor configuration found for monitor {MONITOR_ID}")
                return None
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading bankroll allotment from monitor {MONITOR_ID}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def trigger_auto_entry_trade(strike_data):
    """Trigger a buy trade by calling the trade_manager service directly"""
    import requests
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    log(f"[AUTO ENTRY] 🟢 Triggered AUTO ENTRY for strike: {strike_data.get('strike')} {strike_data.get('side')}")
    
    try:
        port = get_port("trade_manager")
        url = f"http://localhost:{port}/trades"
        
        # Get contract name from strike table market_title
        strike_table_data = get_master_strike_table_data()
        current_symbol = get_current_monitor_symbol()
        contract_name = strike_table_data.get("market_title", f"{current_symbol} Market") if strike_table_data else f"{current_symbol} Market"
        
        # Get position size from trade preferences
        position_size = get_position_size()
        if position_size is None:
            log(f"[AUTO ENTRY] ❌ Cannot trigger trade - no valid position size found")
            return False
        
        # Get bankroll allotment from monitor configuration
        bankroll_allotment = get_bankroll_allotment()
        if bankroll_allotment is None:
            log(f"[AUTO ENTRY] ❌ Cannot trigger trade - no valid bankroll allotment found")
            return False
        
        # Create the exact same payload that trade_initiator would create
        # Generate unique ticket ID (same format as trade_initiator)
        ticket_id = f"TICKET-{uuid.uuid4().hex[:9]}-{int(datetime.now().timestamp() * 1000)}"
        
        # Get current time in Eastern Time (same as trade_initiator)
        now = datetime.now(ZoneInfo("America/New_York"))
        eastern_date = now.strftime('%Y-%m-%d')
        eastern_time = now.strftime('%H:%M:%S')
        
        # Convert side format (yes/no to Y/N) - same as trade_initiator
        side = strike_data.get("side")
        converted_side = side
        if side == "yes":
            converted_side = "Y"
        elif side == "no":
            converted_side = "N"
        
        # Get current price for symbol_open from main app API
        try:
            main_port = get_port("main_app")
            price_url = f"http://localhost:{main_port}/api/{current_symbol.lower()}_price"
            price_response = requests.get(price_url, timeout=2)
            if price_response.ok:
                price_data = price_response.json()
                symbol_open = price_data.get("price")
            else:
                symbol_open = None
        except Exception as e:
            log(f"[AUTO ENTRY] ⚠️ Could not get {current_symbol} price: {e}")
            symbol_open = None
        
        # Get trade strategy from PostgreSQL
        trade_strategy = get_trade_strategy()
        
        # Prepare the trade data exactly like trade_initiator does
        trade_payload = {
            "ticket_id": ticket_id,
            "status": "pending",
            "date": eastern_date,
            "time": eastern_time,
            "symbol": current_symbol,
            "market": "Kalshi",
            "trade_strategy": trade_strategy,
            "contract": contract_name,
            "strike": strike_data.get("strike"),
            "side": converted_side,
            "ticker": strike_data.get("ticker"),
            "buy_price": strike_data.get("buy_price"),
            "position": position_size,
            "symbol_open": symbol_open,
            "symbol_close": None,
            "momentum": None,  # Will be filled by trade_manager
            "prob": strike_data.get("probability"),
            "win_loss": None,
            "entry_method": "auto",
            "monitor": f"mon_0001_{MONITOR_ID}",  # Add monitor identifier
            "bankroll_allotment_total": bankroll_allotment
        }
        
        log(f"[AUTO ENTRY] 📤 Sending trade to trade_manager: {trade_payload}")
        
        response = requests.post(url, json=trade_payload, timeout=10)
        
        if response.status_code == 201:
            result = response.json()
            log(f"[AUTO ENTRY] ✅ Trade initiated successfully via trade_manager: {result}")
            
            from backend.util.trade_logger import log_trade_event
            
            # Log to PostgreSQL instead of text file
            log_message = f"ENTRY | {contract_name} | {strike_data.get('strike')} | {strike_data.get('side')} | {position_size} | {strike_data.get('buy_price')} | {strike_data.get('probability')}"
            log_trade_event(ticket_id, log_message, service="auto_entry_supervisor")
            
            # Send WebSocket notification to frontend for audio/popup alerts
            try:
                main_port = get_port("main_app")
                main_url = f"http://localhost:{main_port}/api/notify_automated_trade"
                notification_data = {
                    "strike": strike_data.get("strike"),
                    "side": strike_data.get("side"),
                    "ticker": strike_data.get("ticker"),
                    "buy_price": strike_data.get("buy_price"),
                    "probability": strike_data.get("probability"),
                    "contract": contract_name,
                    "position": position_size,
                    "entry_method": "auto"
                }
                notification_response = requests.post(main_url, json=notification_data, timeout=2)
                if notification_response.ok:
                    log(f"[AUTO ENTRY] ✅ WebSocket notification sent successfully")
                else:
                    log(f"[AUTO ENTRY] ⚠️ WebSocket notification failed: {notification_response.status_code}")
            except Exception as e:
                # Don't log connection errors every second - they're expected when main app is down
                pass
            
            return True
        else:
            log(f"[AUTO ENTRY] ❌ Trade initiation failed: {response.status_code} - {response.text}")
            return False
        
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error initiating trade via trade_manager: {e}")
        return False

def can_trade_strike(strike_key):
    """ATOMIC: Check if we can trade this strike (cooldown check)"""
    current_time = time.time()
    
    if strike_key in last_trade_times:
        time_since_last_trade = current_time - last_trade_times[strike_key]
        if time_since_last_trade < TRADE_COOLDOWN:
            # Skipping {strike_key} - traded {time_since_last_trade:.1f}s ago (cooldown: {TRADE_COOLDOWN}s)
            return False
    
    # ATOMIC: Add to cooldown immediately
    last_trade_times[strike_key] = current_time
            # {strike_key} passed cooldown check - added to cooldown
    return True

def is_strike_already_traded(strike_data):
    """Check if we already have an open or pending trade on this strike by querying trades_0001 table directly"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        cursor = conn.cursor()
        
        # Query trades_0001 table directly for open/pending trades with ticker
        cursor.execute("""
            SELECT id, ticker, side, status 
            FROM users.trades_0001 
            WHERE status IN ('open', 'pending')
        """)
        
        trades = cursor.fetchall()
        conn.close()
        
        # Checking {len(trades)} trades (open/pending) for ticker {strike_data.get('ticker')} {strike_data.get('side')}
        
        for trade in trades:
            trade_id, trade_ticker, trade_side, trade_status = trade
            
            # Normalize side comparison (Y = yes, N = no)
            normalized_trade_side = str(trade_side).upper()
            normalized_strike_side = strike_data.get('side', '').upper()
            
            # Handle Y/YES and N/NO mapping
            if normalized_trade_side == 'Y' and normalized_strike_side == 'YES':
                normalized_trade_side = 'YES'
            elif normalized_trade_side == 'N' and normalized_strike_side == 'NO':
                normalized_trade_side = 'NO'
            
            # Compare ticker and side
            if (trade_ticker == strike_data.get('ticker') and 
                normalized_trade_side == normalized_strike_side):
                log(f"[AUTO ENTRY] ⚠️ Found {trade_status} trade (ID: {trade_id}) on {strike_data.get('strike')} {strike_data.get('side')}")
                return True
        
        # No open or pending trades found for {strike_data.get('strike')} {strike_data.get('side')}
        return False
    except Exception as e:
        log(f"[AUTO ENTRY] Error checking trades_0001 table: {e}")
        return False

def check_auto_entry_conditions():
    """SIMPLIFIED: Check if auto entry conditions are met and trigger trades"""
    global auto_entry_indicator_state
    
    try:
        # Get strike table data directly (no watchlist needed)
        
        # Check spike alert conditions first
        check_spike_alert_conditions()
        

        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (blocks all trades)
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        
        if not auto_trade_enabled:
            auto_entry_indicator_state.update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": spike_alert_active,
                "current_ttc": 0,
                "last_updated": datetime.now().isoformat()
            })
            # Broadcast indicator state change
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings - NO DEFAULTS
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY] ❌ Missing required settings: {missing_settings}")
            log(f"[AUTO ENTRY] Cannot proceed without complete settings configuration")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_probability = settings["min_probability"]
        min_differential = settings["min_differential"]
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window + no blocking conditions (including spike alert)
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          not spike_alert_active)  # SPIKE ALERT blocks scanning
        
        # Update indicator state for frontend
        auto_entry_indicator_state.update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": spike_alert_active,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": datetime.now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        if not ttc_within_window:
            return
        
        # SPIKE ALERT CHECK - Block all trades if spike alert is active
        if spike_alert_active:
            log(f"[AUTO ENTRY] ⏸️ SPIKE ALERT ACTIVE - Skipping all trade processing")
            return
        
        # Get strike table data directly
        strike_table_data = get_master_strike_table_data()
        if not strike_table_data or "strikes" not in strike_table_data:
            return
        
        # Process each strike ONCE
        processed_strikes = set()  # Prevent duplicate processing
        
        for i, strike in enumerate(strike_table_data["strikes"]):
            try:
                # Use active_side for strike_key generation
                active_side = strike.get('active_side')
                if not active_side:
                    continue
                    
                strike_key = f"{strike.get('strike')}-{active_side}"
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                
                processed_strikes.add(strike_key)
                
                # STEP 1: ATOMIC cooldown check
                if not can_trade_strike(strike_key):
                    continue
                
                # STEP 2: Check if we already have an active trade on this strike
                strike_data_for_check = {
                    'strike': strike.get('strike'),
                    'side': active_side
                }
                
                if is_strike_already_traded(strike_data_for_check):
                    continue
                
                # STEP 3: Check probability threshold
                prob = strike.get('probability')
                if prob is None or prob < min_probability:
                    continue
                
                # STEP 4: Check differential threshold (if applicable)
                if min_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff < (min_differential - 0.5):
                        continue
                
                # STEP 4.5: Check max differential threshold (if applicable)
                max_differential = settings.get("max_differential")
                if max_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff > max_differential:
                        # Skipping {strike_key} - differential {diff} above max threshold {max_differential}
                        continue
                
                # STEP 5: Check volume threshold
                min_volume = settings.get("min_volume", 1000)
                volume = strike.get('volume', 0)
                if volume is None or volume < min_volume:
                    continue
                
                # STEP 6: Check max ask price threshold
                max_ask = settings.get("max_ask", 98)
                yes_ask = strike.get('yes_ask', 0)
                no_ask = strike.get('no_ask', 0)
                if yes_ask is None or no_ask is None:
                    continue
                max_ask_price = max(yes_ask, no_ask)
                if max_ask_price > max_ask:
                    continue
                
                # STEP 5: Determine buy price based on active_side
                if active_side == 'yes':
                    side = 'yes'
                    buy_price = strike.get('yes_ask', 0) / 100.0  # Convert cents to decimal
                elif active_side == 'no':
                    side = 'no'
                    buy_price = strike.get('no_ask', 0) / 100.0  # Convert cents to decimal
                else:
                    continue
                
                # STEP 6: Prepare strike data for trade trigger
                strike_data = {
                    'strike': f"${int(strike.get('strike')):,}",
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob
                }
                
                # STEP 7: Check if strike is already traded
                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY] ⏸️ Skipping {strike_key} - already has open/pending trade")
                    continue
                
                # STEP 8: Trigger the trade
                log(f"[AUTO ENTRY] 🚀 TRIGGERING TRADE | {strike_key} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Ticker: {strike.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY] ✅ TRADE SUCCESSFUL | {strike_key} | Trade triggered and sent to trade_manager")
                else:
                    log(f"[AUTO ENTRY] ❌ TRADE FAILED | {strike_key} | Failed to trigger trade")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY] Error checking auto entry conditions: {e}")

def cleanup_old_cooldowns():
    """Clean up old cooldown entries"""
    current_time = time.time()
    keys_to_remove = []
    
    for strike_key, last_trade_time in last_trade_times.items():
        if current_time - last_trade_time >= TRADE_COOLDOWN:
            keys_to_remove.append(strike_key)
    
    for key in keys_to_remove:
        del last_trade_times[key]
    
            # Only log if we actually cleaned up something (and only if significant)
        if len(keys_to_remove) > 20:
            log(f"[AUTO ENTRY] Cleaned up {len(keys_to_remove)} old cooldowns")

def start_monitoring_loop():
    """Start the monitoring loop for auto entry conditions"""
    global monitoring_thread
    
    def monitoring_worker():
        global monitoring_thread
        log("📊 MONITORING: Starting auto entry monitoring loop")
        
        # Broadcast initial state immediately on startup
        log("📊 MONITORING: Broadcasting initial auto entry state")
        check_auto_entry_conditions()
        
        check_count = 0
        last_heartbeat = time.time()
        while True:
            try:
                check_count += 1
                current_time = time.time()
                
                # Heartbeat every 5 minutes (300 seconds)
                if current_time - last_heartbeat >= 300:
                    log_heartbeat()
                    last_heartbeat = current_time
                
                # Only log every 1000 checks (reduces logging by 99.9%)
                if check_count % 1000 == 0:
                    log(f"[AUTO ENTRY] Check #{check_count} - continuing monitoring...")
                
                # Clean up old cooldowns first
                cleanup_old_cooldowns()
                
                # Check auto entry conditions
                check_auto_entry_conditions()
                
                # Sleep for 1 second
                time.sleep(1)
                
            except Exception as e:
                log(f"❌ Error in monitoring worker: {e}")
                time.sleep(5)  # Wait longer on error
        
        # Clear the global monitoring thread reference when done
        with monitoring_thread_lock:
            monitoring_thread = None
        log("📊 MONITORING: Auto entry monitoring thread finished")
    
    # Start monitoring in a separate thread
    with monitoring_thread_lock:
        monitoring_thread = threading.Thread(target=monitoring_worker, daemon=True)
        monitoring_thread.start()
        log("📊 MONITORING: Auto entry monitoring thread started")

# Health check endpoint
@app.route("/health")
def health_check():
    """Health check endpoint."""
    try:
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        enabled = is_auto_trade_enabled()
        
        return {
            "status": "healthy" if service_healthy else "unhealthy",
            "service": f"auto_entry_supervisor_{MONITOR_IDENTIFIER}",
            "monitor_identifier": MONITOR_IDENTIFIER,
            "user_number": USER_NUMBER,
            "monitor_id": MONITOR_ID,
            "port": AUTO_ENTRY_SUPERVISOR_PORT,
            "timestamp": datetime.now().isoformat(),
            "port_system": "centralized",
            "monitoring_thread_alive": service_healthy,
            "auto_entry_enabled": enabled,
            "scanning_active": auto_entry_indicator_state.get("scanning_active", False),
            "spike_alert_active": auto_entry_indicator_state.get("spike_alert_active", False),
            "current_momentum": auto_entry_indicator_state.get("current_momentum", None)
        }
    except Exception as e:
        return {
            "status": "error",
            "service": f"auto_entry_supervisor_{MONITOR_IDENTIFIER}",
            "monitor_identifier": MONITOR_IDENTIFIER,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# LEGACY REMOVED: /api/auto_entry_status endpoint - now using auto_trade_status system

# Auto entry indicator endpoint (for frontend display)
@app.route("/api/auto_entry_indicator")
def get_auto_entry_indicator():
    """Get current auto entry indicator state"""
    return jsonify(auto_entry_indicator_state)

# Detailed scanning status endpoint (for debugging/monitoring)
@app.route("/api/auto_entry_scanning_status")
def get_auto_entry_scanning_status():
    """Get detailed scanning status information"""
    try:
        enabled = is_auto_trade_enabled()
        settings = get_auto_entry_settings()
        current_ttc = get_current_ttc()
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Calculate scanning status
        ttc_within_window = settings["min_time"] <= current_ttc <= settings["max_time"]
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        scanning_active = enabled and service_healthy and ttc_within_window and not spike_alert_active
        
        return jsonify({
            "enabled": enabled,
            "service_healthy": service_healthy,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "spike_alert_active": spike_alert_active,
            "current_momentum": auto_entry_indicator_state.get("current_momentum", None),
            "spike_alert_recovery_countdown": auto_entry_indicator_state.get("spike_alert_recovery_countdown", None),
            "current_ttc": current_ttc,
            "settings": settings,
            "spike_alert_settings": {
                "enabled": settings.get("spike_alert_enabled"),
                "momentum_threshold": settings.get("spike_alert_momentum_threshold"),
                "cooldown_threshold": settings.get("spike_alert_cooldown_threshold"),
                "cooldown_minutes": settings.get("spike_alert_cooldown_minutes")
            },
            "cooldown_entries_count": len(last_trade_times),
            "monitoring_thread_alive": service_healthy,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Automated trade notification endpoint
@app.route("/api/notify_automated_trade", methods=['POST'])
def notify_automated_trade():
    """Notify the frontend that an automated trade was triggered"""
    try:
        data = request.json
        log(f"[AUTO ENTRY] 🔔 Notifying frontend of automated trade: {data}")
        
        # Forward the notification to the main app for WebSocket broadcast
        try:
            port = get_port("main_app")
            url = f"http://localhost:{port}/api/notify_automated_trade"
            response = requests.post(url, json=data, timeout=2)
            if response.ok:
                log(f"[AUTO ENTRY] ✅ Frontend notification sent successfully")
            else:
                log(f"[AUTO ENTRY] ⚠️ Frontend notification failed: {response.status_code}")
        except Exception as e:
            log(f"[AUTO ENTRY] ❌ Error sending frontend notification: {e}")
        
        return jsonify({"success": True, "message": "Automated trade notification sent"})
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error in notify_automated_trade: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# Port information endpoint
@app.route("/api/ports")
def get_ports():
    """Get all port assignments from centralized system."""
    from backend.core.port_config import get_port_info
    return get_port_info()

# Spike alert settings endpoint
@app.route("/api/spike_alert_settings", methods=['GET', 'POST'])
def spike_alert_settings():
    """Get or update spike alert settings"""
    try:
        if request.method == 'GET':
            settings = get_auto_entry_settings()
            return jsonify({
                "spike_alert_enabled": settings.get("spike_alert_enabled"),
                "spike_alert_momentum_threshold": settings.get("spike_alert_momentum_threshold"),
                "spike_alert_cooldown_threshold": settings.get("spike_alert_cooldown_threshold"),
                "spike_alert_cooldown_minutes": settings.get("spike_alert_cooldown_minutes")
            })
        else:
            # POST - Update settings
            data = request.json
            settings_path = os.path.join(get_data_dir(), "users", "user_0001", "preferences", "auto_entry_settings.json")
            
            # Load current settings
            if os.path.exists(settings_path):
                with open(settings_path, "r") as f:
                    settings = json.load(f)
            else:
                settings = {}
            
            # Update with new values
            if "spike_alert_enabled" in data:
                settings["spike_alert_enabled"] = data["spike_alert_enabled"]
            if "spike_alert_momentum_threshold" in data:
                settings["spike_alert_momentum_threshold"] = data["spike_alert_momentum_threshold"]
            if "spike_alert_cooldown_threshold" in data:
                settings["spike_alert_cooldown_threshold"] = data["spike_alert_cooldown_threshold"]
            if "spike_alert_cooldown_minutes" in data:
                settings["spike_alert_cooldown_minutes"] = data["spike_alert_cooldown_minutes"]
            
            # Save updated settings
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
            
            log(f"[SPIKE ALERT SETTINGS] Updated: {data}")
            return jsonify({"success": True, "message": "Spike alert settings updated"})
            
    except Exception as e:
        log(f"[SPIKE ALERT SETTINGS] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    log(f"🛑 Received signal {signum}, shutting down gracefully...")
    sys.exit(0)

def start_event_driven_supervisor():
    """Start the event-driven auto entry supervisor"""
    log(f"🚀 Starting Auto Entry Supervisor for Monitor {MONITOR_IDENTIFIER}")
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    
    # Start monitoring loop
    start_monitoring_loop()
    
    # Start HTTP server
    def start_http_server():
        try:
            host = "localhost"  # Use localhost for internal service communication
            port = AUTO_ENTRY_SUPERVISOR_PORT
            log(f"🌐 Starting HTTP server on {host}:{port}")
            
            # Broadcast initial state immediately when server starts
            log("🌐 Broadcasting initial auto entry state on server startup")
            check_auto_entry_conditions()
            
            app.run(host=host, port=port, debug=False, use_reloader=False)
        except Exception as e:
            log(f"❌ Error starting HTTP server: {e}")
    
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    # Keep the process alive but don't loop
    try:
        while True:
            # Just keep the process running, no active polling
            time.sleep(60)  # Sleep for 1 minute, just to keep alive
    except KeyboardInterrupt:
        log("🛑 Auto entry supervisor stopped by user")
    except Exception as e:
        log(f"❌ Error in supervisor: {e}")



if __name__ == "__main__":
    # Start the event-driven supervisor
    start_event_driven_supervisor() 