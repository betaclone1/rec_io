#!/usr/bin/env python3
"""
Auto Entry Supervisor - SIMPLIFIED VERSION

Monitors watchlist data and triggers automated trades when criteria are met.
Uses atomic operations to prevent rapid-fire trades.
"""

import os
import json
import time
import threading
import requests
import random
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Any
from flask import Flask, request, jsonify
from flask_cors import CORS

# Import the universal centralized port system
from backend.core.port_config import get_port
from backend.util.paths import get_host, get_data_dir, get_service_url, get_trade_history_dir

# Get port from centralized system
AUTO_ENTRY_SUPERVISOR_PORT = get_port("auto_entry_supervisor")
print(f"[AUTO_ENTRY_SUPERVISOR] 🚀 Using centralized port: {AUTO_ENTRY_SUPERVISOR_PORT}")

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

# Track previous state to detect changes
previous_indicator_state = None

# SPIKE ALERT constants - NO DEFAULTS, must get from settings
# These will be loaded from auto_entry_settings.json

def log(message: str):
    """Log messages with timestamp"""
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[AUTO_ENTRY_SUPERVISOR {timestamp}] {message}")
    
    # Also write to a dedicated log file for easy tailing
    try:
        from backend.util.paths import get_project_root
        log_dir = os.path.join(get_project_root(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "auto_entry_supervisor.log")
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception as e:
        print(f"Error writing to log file: {e}")

def get_auto_entry_state_path():
    """Get the path to the monitor-specific auto entry state file"""
    return os.path.join(get_data_dir(), "users", "user_0001", "monitors", "auto_entry_state.json")

def load_auto_entry_state():
    """Load monitor-specific auto entry state from JSON file"""
    try:
        state_path = get_auto_entry_state_path()
        if os.path.exists(state_path):
            with open(state_path, "r") as f:
                state = json.load(f)
                log(f"[AUTO ENTRY STATE] Loaded state from {state_path}")
                return state
        else:
            log(f"[AUTO ENTRY STATE] State file not found at {state_path}, using defaults")
            return None
    except Exception as e:
        log(f"[AUTO ENTRY STATE] Error loading state: {e}")
        return None

def save_auto_entry_state(state):
    """Save monitor-specific auto entry state to JSON file"""
    try:
        state_path = get_auto_entry_state_path()
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        
        # Ensure timestamp is updated
        state["last_updated"] = datetime.now(ZoneInfo("America/New_York")).isoformat()
        
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
        
        log(f"[AUTO ENTRY STATE] Saved state to {state_path}")
        return True
    except Exception as e:
        log(f"[AUTO ENTRY STATE] Error saving state: {e}")
        return False

def get_current_momentum():
    """Get current BTC momentum directly from PostgreSQL"""
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
        
        cursor.execute("""
            SELECT momentum FROM live_data.live_price_log_1s_btc 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_score = float(result[0])
            log(f"[AUTO ENTRY MOMENTUM] Current momentum: {momentum_score:.2f}")
            return momentum_score
        else:
            log(f"[AUTO ENTRY MOMENTUM] No momentum data available")
            return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum: {e}")
        return None

def check_spike_alert_conditions():
    """Check if spike alert conditions are met and update state accordingly"""
    global auto_entry_indicator_state
    
    try:
        # Get current momentum
        current_momentum = get_current_momentum()
        if current_momentum is None:
            return
        
        # Update current momentum in state
        auto_entry_indicator_state["current_momentum"] = current_momentum
        
        # Load current state from file
        state = load_auto_entry_state()
        if state is None:
            # Initialize default state
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
        
        # Update current momentum in loaded state
        state["current_momentum"] = current_momentum
        
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
        spike_threshold = settings["spike_alert_momentum_threshold"] / 100.0  # Convert percentage to decimal
        cooldown_threshold = settings["spike_alert_cooldown_threshold"] / 100.0  # Convert percentage to decimal
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
            
            # Save updated state
            save_auto_entry_state(state)
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
            
            # Set initial cooldown timer in seconds
            cooldown_seconds = cooldown_minutes * 60
            update_cooldown_timer_in_db(cooldown_seconds)
            
            log(f"[SPIKE ALERT] 🚨 SPIKE DETECTED! Momentum: {current_momentum:.2f} (threshold: ±{spike_threshold})")
            log(f"[SPIKE ALERT] Auto entry PAUSED for {cooldown_minutes} minutes ({cooldown_seconds} seconds)")
            
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
                        
                        # Reset cooldown timer to 0
                        update_cooldown_timer_in_db(0)
                        
                        log(f"[SPIKE ALERT] ✅ RECOVERY COMPLETE! Auto entry RESUMED")
                        log(f"[SPIKE ALERT] Recovery time: {time_in_recovery:.1f} minutes")
                    else:
                        # Still in recovery period - update countdown in seconds
                        remaining_minutes = cooldown_minutes - time_in_recovery
                        remaining_seconds = max(0, int(remaining_minutes * 60))
                        state["spike_alert_recovery_countdown"] = remaining_minutes
                        
                        # Update cooldown timer in database
                        update_cooldown_timer_in_db(remaining_seconds)
                        
                        log(f"[SPIKE ALERT] ⏳ Recovery in progress: {remaining_minutes:.1f} minutes ({remaining_seconds} seconds) remaining")
                else:
                    # Reset recovery countdown if start time is missing
                    state["spike_alert_recovery_countdown"] = cooldown_minutes
            else:
                # Still in spike conditions - reset recovery timer
                state["spike_alert_start_time"] = now.isoformat()
                state["spike_alert_recovery_countdown"] = cooldown_minutes
                
                # Reset cooldown timer to full duration
                cooldown_seconds = cooldown_minutes * 60
                update_cooldown_timer_in_db(cooldown_seconds)
                
                log(f"[SPIKE ALERT] ⚠️ Still in spike conditions: {current_momentum:.2f} - resetting timer to {cooldown_minutes} minutes")
        
        # Update global state for frontend
        auto_entry_indicator_state.update({
            "spike_alert_active": state["spike_alert_active"],
            "spike_alert_start_time": state["spike_alert_start_time"],
            "spike_alert_momentum_value": state["spike_alert_momentum_value"],
            "spike_alert_recovery_countdown": state["spike_alert_recovery_countdown"],
            "current_momentum": state["current_momentum"]
        })
        
        # Save updated state
        save_auto_entry_state(state)
        
    except Exception as e:
        log(f"[SPIKE ALERT] Error checking spike conditions: {e}")

def update_cooldown_timer_in_db(seconds):
    """Update cooldown_timer in the database"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users.auto_trade_settings_0001 SET cooldown_timer = %s, updated_at = NOW() WHERE id = 1",
                (seconds,)
            )
            conn.commit()
        conn.close()
        log(f"[AUTO ENTRY] ✅ Updated cooldown_timer to {seconds} seconds in database")
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error updating cooldown_timer: {e}")

def update_auto_entry_status_in_db(status):
    """Update auto_entry_status in the database"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users.auto_trade_settings_0001 SET auto_entry_status = %s, updated_at = NOW() WHERE id = 1",
                (status,)
            )
            conn.commit()
        conn.close()
        log(f"[AUTO ENTRY] ✅ Updated auto_entry_status to '{status}' in database")
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error updating auto_entry_status: {e}")

def determine_auto_entry_status():
    """Determine the current auto entry status based on conditions"""
    try:
        # Check if auto entry is enabled
        auto_entry_enabled = is_auto_entry_enabled()
        
        if not auto_entry_enabled:
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
        update_auto_entry_status_in_db(new_status)
        
        # Get cooldown timer from database
        cooldown_timer = 0
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT cooldown_timer FROM users.auto_trade_settings_0001 WHERE id = 1")
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
        
        log(f"[AUTO ENTRY DEBUG] 🔍 Checking indicator state change:")
        log(f"[AUTO ENTRY DEBUG]   Current status: {new_status}, cooldown: {cooldown_timer}")
        log(f"[AUTO ENTRY DEBUG]   Previous: {previous_indicator_state}")
        
        # Check if state has actually changed (compare with previous)
        current_state_key = (new_status, cooldown_timer)
        if previous_indicator_state == current_state_key:
            log(f"[AUTO ENTRY DEBUG]   No change detected, skipping broadcast")
            return  # No change, don't broadcast
        
        # Update previous state
        previous_indicator_state = current_state_key
        log(f"[AUTO ENTRY DEBUG]   State changed, broadcasting...")
        
        # Send to main app for WebSocket broadcast
        try:
            port = get_port("main_app")
            url = f"http://localhost:{port}/api/broadcast_auto_entry_indicator"
            response = requests.post(url, json=broadcast_data, timeout=2)
            if response.ok:
                log(f"[AUTO ENTRY] ✅ Auto entry indicator change broadcasted: status={new_status}, cooldown={cooldown_timer}")
            else:
                log(f"[AUTO ENTRY] ⚠️ Failed to broadcast indicator change: {response.status_code}")
        except Exception as e:
            log(f"[AUTO ENTRY] ❌ Error broadcasting indicator change: {e}")
            
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error in broadcast_auto_entry_indicator_change: {e}")

def is_auto_entry_enabled():
    """Check if AUTO ENTRY is enabled in PostgreSQL"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db", 
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT auto_entry FROM users.auto_trade_settings_0001 WHERE id = 1")
            result = cursor.fetchone()
            return result[0] if result else False
    except Exception as e:
        log(f"[AUTO ENTRY] Error reading from PostgreSQL: {e}")
        return False

def get_auto_entry_settings():
    """Get auto entry settings from PostgreSQL - NO DEFAULTS"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db", 
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT min_probability, min_differential, min_time, max_time, allow_re_entry,
                       spike_alert_enabled, spike_alert_momentum_threshold, 
                       spike_alert_cooldown_threshold, spike_alert_cooldown_minutes
                FROM users.auto_trade_settings_0001 WHERE id = 1
            """)
            result = cursor.fetchone()
            if result:
                settings = {
                    "min_probability": result[0],
                    "min_differential": float(result[1]),
                    "min_time": result[2],
                    "max_time": result[3],
                    "allow_re_entry": result[4],
                    "spike_alert_enabled": result[5],
                    "spike_alert_momentum_threshold": result[6],
                    "spike_alert_cooldown_threshold": result[7],
                    "spike_alert_cooldown_minutes": result[8],
                    "watchlist_min_volume": 1000,  # Default value
                    "watchlist_max_ask": 98  # Default value
                }
                log(f"[AUTO ENTRY] Loaded settings from PostgreSQL")
                return settings
            else:
                log(f"[AUTO ENTRY] No settings found in PostgreSQL")
                return {}
    except Exception as e:
        log(f"[AUTO ENTRY] Error reading settings from PostgreSQL: {e}")
        return {}

def get_current_ttc():
    """Get current TTC from unified TTC endpoint"""
    try:
        port = get_port("main_app")
        url = f"http://localhost:{port}/api/unified_ttc/btc"
        response = requests.get(url, timeout=2)
        if response.ok:
            data = response.json()
            ttc = data.get("ttc_seconds", 0)
            return ttc
        else:
            log(f"[AUTO ENTRY] TTC request failed: {response.status_code}")
    except Exception as e:
        log(f"[AUTO ENTRY] Error fetching TTC: {e}")
    return 0

def get_strike_table_path():
    """Get the path to the master strike table JSON file"""
    return os.path.join(get_data_dir(), "live_data", "markets", "kalshi", "strike_tables", "strike_table_btc.json")

def get_watchlist_path():
    """Get the path to the watchlist JSON file"""
    return os.path.join(get_data_dir(), "live_data", "markets", "kalshi", "strike_tables", "btc_watchlist.json")

def get_master_strike_table_data():
    """Get current master strike table data from PostgreSQL"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    symbol,
                    current_price,
                    ttc_seconds,
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status
                FROM live_data.strike_table_btc
                LIMIT 1
            """)
            header_data = cursor.fetchone()
            if not header_data:
                log(f"[WATCHLIST] No strike table data found in PostgreSQL")
                return None
            cursor.execute("""
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
                FROM live_data.strike_table_btc
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

def generate_watchlist_from_strike_table():
    """Generate watchlist by filtering the master strike table based on auto entry settings"""
    try:
        # Get master strike table data
        strike_table_data = get_master_strike_table_data()
        if not strike_table_data or "strikes" not in strike_table_data:
            log(f"[WATCHLIST] No master strike table data available")
            return False
        
        btc_price = strike_table_data.get("current_price")
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
        
        log(f"[WATCHLIST] Filtering with settings: min_prob={min_probability}, min_diff={min_differential}, min_vol={min_volume}, max_ask={max_ask}")
        
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
            is_above_money_line = strike.get("strike", 0) > btc_price
            
            # Get the active button's differential
            active_diff = no_diff if is_above_money_line else yes_diff
            
            # Check if at least one side meets the differential requirement
            yes_diff_ok = yes_diff >= min_differential
            no_diff_ok = no_diff >= min_differential
            at_least_one_diff_ok = yes_diff_ok or no_diff_ok
            
            # Apply filter criteria from auto entry settings
            volume_ok = volume >= min_volume
            probability_ok = probability > min_probability
            ask_ok = max_ask_price <= max_ask
            
            if (volume_ok and probability_ok and ask_ok and at_least_one_diff_ok):
                filtered_strikes.append(strike)
        
        # Sort by probability (highest to lowest)
        filtered_strikes.sort(key=lambda x: x.get("probability", 0), reverse=True)
        
        # Create watchlist output
        watchlist_output = {
            "symbol": "BTC",
            "current_price": btc_price,
            "ttc": ttc_seconds,
            "broker": "Kalshi",
            "event_ticker": market_data.get("event_ticker"),
            "market_title": market_data.get("event_title"),
            "strike_tier": market_data.get("strike_tier"),
            "market_status": market_data.get("market_status"),
            "last_updated": datetime.now().isoformat(),
            "strikes": filtered_strikes
        }
        
        # Write watchlist to PostgreSQL
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            with conn.cursor() as cursor:
                # Clear existing watchlist data
                cursor.execute("DELETE FROM live_data.watchlist_btc")
                # Insert filtered strikes into watchlist table
                for strike in filtered_strikes:
                    cursor.execute("""
                        INSERT INTO live_data.watchlist_btc (
                            symbol, current_price, ttc_seconds, broker, event_ticker,
                            market_title, strike_tier, market_status, strike, buffer,
                            buffer_pct, probability, yes_ask, no_ask, yes_diff, no_diff,
                            volume, ticker, active_side
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        "BTC", btc_price, ttc_seconds, "Kalshi", market_data.get("event_ticker"),
                        market_data.get("event_title"), market_data.get("strike_tier"),
                        market_data.get("market_status"), strike.get("strike"), strike.get("buffer"),
                        strike.get("buffer_pct"), strike.get("probability"), strike.get("yes_ask"),
                        strike.get("no_ask"), strike.get("yes_diff"), strike.get("no_diff"),
                        strike.get("volume"), strike.get("ticker"), strike.get("active_side")
                    ))
                conn.commit()
                conn.close()
                log(f"[WATCHLIST] Generated watchlist with {len(filtered_strikes)} filtered strikes in PostgreSQL")
                return True
        except Exception as e:
            log(f"[WATCHLIST] Error writing to PostgreSQL: {e}")
            return False
        
    except Exception as e:
        log(f"[WATCHLIST] Error generating watchlist: {e}")
        return False

def get_watchlist_data():
    """Get current watchlist data from PostgreSQL"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    symbol,
                    current_price,
                    ttc_seconds,
                    broker,
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status
                FROM live_data.watchlist_btc
                LIMIT 1
            """)
            header_data = cursor.fetchone()
            if not header_data:
                log(f"[AUTO ENTRY] No watchlist data found in PostgreSQL")
                return None
            cursor.execute("""
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
                FROM live_data.watchlist_btc
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
    """Get position size from PostgreSQL trade preferences including multiplier"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT position_size, multiplier FROM users.trade_preferences_0001 WHERE id = 1")
            result = cursor.fetchone()
            if result:
                position_size = result[0]
                multiplier = result[1]
                total_position = position_size * multiplier
                log(f"[AUTO ENTRY] Loaded position size from PostgreSQL: {position_size} * {multiplier} = {total_position}")
                return total_position
            else:
                log(f"[AUTO ENTRY] No trade preferences found in PostgreSQL")
                return None
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading position size from PostgreSQL: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_trade_strategy():
    """Get trade strategy from PostgreSQL trade preferences"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT trade_strategy FROM users.trade_preferences_0001 WHERE id = 1")
            result = cursor.fetchone()
            if result:
                trade_strategy = result[0]
                log(f"[AUTO ENTRY] Loaded trade strategy from PostgreSQL: {trade_strategy}")
                return trade_strategy
            else:
                log(f"[AUTO ENTRY] No trade preferences found in PostgreSQL")
                return "Hourly HTC"  # Default fallback
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading trade strategy from PostgreSQL: {e}")
        return "Hourly HTC"  # Default fallback
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
        
        # Get contract name from watchlist market_title
        watchlist_data = get_watchlist_data()
        contract_name = watchlist_data.get("market_title", "BTC Market") if watchlist_data else "BTC Market"
        
        # Get position size from trade preferences
        position_size = get_position_size()
        if position_size is None:
            log(f"[AUTO ENTRY] ❌ Cannot trigger trade - no valid position size found")
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
        
        # Get current BTC price for symbol_open from main app API
        try:
            main_port = get_port("main_app")
            btc_url = f"http://localhost:{main_port}/api/btc_price"
            btc_response = requests.get(btc_url, timeout=2)
            if btc_response.ok:
                btc_data = btc_response.json()
                symbol_open = btc_data.get("price")
            else:
                symbol_open = None
        except Exception as e:
            log(f"[AUTO ENTRY] ⚠️ Could not get BTC price: {e}")
            symbol_open = None
        
        # Get trade strategy from PostgreSQL
        trade_strategy = get_trade_strategy()
        
        # Prepare the trade data exactly like trade_initiator does
        trade_payload = {
            "ticket_id": ticket_id,
            "status": "pending",
            "date": eastern_date,
            "time": eastern_time,
            "symbol": "BTC",
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
            "entry_method": "auto"
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
                log(f"[AUTO ENTRY] ❌ Error sending WebSocket notification: {e}")
            
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
            log(f"[AUTO ENTRY DEBUG] ⏸️ Skipping {strike_key} - traded {time_since_last_trade:.1f}s ago (cooldown: {TRADE_COOLDOWN}s)")
            return False
    
    # ATOMIC: Add to cooldown immediately
    last_trade_times[strike_key] = current_time
    log(f"[AUTO ENTRY DEBUG] ✅ {strike_key} passed cooldown check - added to cooldown")
    return True

def is_strike_already_traded(strike_data):
    """Check if we already have an active or pending trade on this strike"""
    try:
        # Get active trades from the active_trade_supervisor
        port = get_port("active_trade_supervisor")
        url = f"http://localhost:{port}/api/active_trades"
        response = requests.get(url, timeout=2)
        
        if not response.ok:
            log(f"[AUTO ENTRY] ⚠️ Failed to get active trades: {response.status_code}")
            return False
            
        response_data = response.json()
        active_trades = response_data.get('active_trades', [])
        log(f"[AUTO ENTRY DEBUG] 🔍 Checking {len(active_trades)} trades (active/pending) for strike {strike_data.get('strike')} {strike_data.get('side')}")
        
        for trade in active_trades:
            # Check if this trade is for the same strike
            trade_strike = trade.get('strike', '')
            trade_side = trade.get('side', '')
            trade_status = trade.get('status', 'active')  # Default to 'active' for backward compatibility
            
            # Extract strike number from trade_strike (e.g., "$117,500" -> "117500")
            if trade_strike.startswith('$'):
                trade_strike_num = trade_strike.replace('$', '').replace(',', '')
            else:
                trade_strike_num = trade_strike
            
            # Normalize side comparison (Y = yes, N = no)
            normalized_trade_side = trade_side.upper()
            normalized_strike_side = strike_data.get('side', '').upper()
            
            # Handle Y/YES and N/NO mapping
            if normalized_trade_side == 'Y' and normalized_strike_side == 'YES':
                normalized_trade_side = 'YES'
            elif normalized_trade_side == 'N' and normalized_strike_side == 'NO':
                normalized_trade_side = 'NO'
            
            # Compare strike numbers and sides
            if (trade_strike_num == str(strike_data.get('strike')) and 
                normalized_trade_side == normalized_strike_side):
                log(f"[AUTO ENTRY] ⚠️ Found {trade_status} trade on {strike_data.get('strike')} {strike_data.get('side')}")
                return True
        
        log(f"[AUTO ENTRY DEBUG] ✅ No active or pending trades found for {strike_data.get('strike')} {strike_data.get('side')}")
        return False
    except Exception as e:
        log(f"[AUTO ENTRY] Error checking active trades: {e}")
        return False

def check_auto_entry_conditions():
    """SIMPLIFIED: Check if auto entry conditions are met and trigger trades"""
    global auto_entry_indicator_state
    
    try:
        # ALWAYS generate watchlist first (regardless of scanning status)
        watchlist_generated = generate_watchlist_from_strike_table()
        if not watchlist_generated:
            log(f"[AUTO ENTRY] Failed to generate watchlist")
        
        # Check spike alert conditions first
        check_spike_alert_conditions()
        
        # Check if AUTO ENTRY is enabled
        auto_entry_enabled = is_auto_entry_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (blocks all trades)
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        
        if not auto_entry_enabled:
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
        # Scanning is active if: enabled + service healthy + TTC in window + no blocking conditions (including spike alert)
        scanning_active = (auto_entry_enabled and 
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
        
        # Get watchlist data
        watchlist_data = get_watchlist_data()
        if not watchlist_data or "strikes" not in watchlist_data:
            return
        
        # Process each strike ONCE
        processed_strikes = set()  # Prevent duplicate processing
        
        for i, strike in enumerate(watchlist_data["strikes"]):
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
                    log(f"[AUTO ENTRY DEBUG] 📈 Strike differential: {diff} (min required: {min_differential})")
                    if diff is None or diff < (min_differential - 0.5):
                        log(f"[AUTO ENTRY DEBUG] ⏸️ Skipping {strike_key} - differential {diff} below threshold {min_differential}")
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
                    'strike': f"${strike.get('strike'):,}",
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob
                }
                
                # STEP 7: Trigger the trade
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY] ✅ Trade triggered for {strike_key}")
                else:
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
    
    # Only log if we actually cleaned up something
    if keys_to_remove:
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
        while True:
            try:
                check_count += 1
                
                # Only log every 100 checks (reduces logging by 99%)
                if check_count % 100 == 0:
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
        enabled = is_auto_entry_enabled()
        
        return {
            "status": "healthy" if service_healthy else "unhealthy",
            "service": "auto_entry_supervisor",
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
            "service": "auto_entry_supervisor",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# Auto entry status endpoint
@app.route("/api/auto_entry_status")
def get_auto_entry_status():
    """Get current auto entry status"""
    try:
        enabled = is_auto_entry_enabled()
        settings = get_auto_entry_settings()
        current_ttc = get_current_ttc()
        
        return jsonify({
            "enabled": enabled,
            "settings": settings,
            "current_ttc": current_ttc,
            "cooldown_entries_count": len(last_trade_times),
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        enabled = is_auto_entry_enabled()
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

def start_event_driven_supervisor():
    """Start the event-driven auto entry supervisor"""
    log("🚀 Starting Auto Entry Supervisor (SIMPLIFIED)")
    
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