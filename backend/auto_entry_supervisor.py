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
import re
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
from backend.util.paths import get_host, get_data_dir, get_service_url, get_trade_history_dir, get_logs_dir

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

_LAST_MONITOR_STATE = {
    "contract": None,
    "weekly_cycle": None,
    "modifier": None,
    "max_pct_exposure": None,
    "applied_multiplier": None,
}

MARKET_TITLE_TODAY_PATTERN = re.compile(r"price today at\s+(\d{1,2})\s*(am|pm)", re.IGNORECASE)
# 15m market title: "BTC price today at 12:45pm" -> capture 12, 45, pm
MARKET_TITLE_TODAY_15M_PATTERN = re.compile(r"price today at\s+(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
MARKET_TITLE_DATE_PATTERN = re.compile(r"price on\s+([A-Za-z]{3})\s+(\d{1,2})\s+at\s+(\d{1,2})\s*(am|pm)", re.IGNORECASE)


def _format_time_label(hour_24: int) -> str:
    if hour_24 == 0:
        return "12am"
    if hour_24 == 12:
        return "12pm"
    if hour_24 > 12:
        return f"{hour_24 - 12}pm"
    return f"{hour_24}am"


def _hour_label_to_hour24(hour_value: int, period: str) -> int:
    period = period.lower()
    if period == "am":
        return 0 if hour_value == 12 else hour_value
    # pm
    return 12 if hour_value == 12 else hour_value + 12


def _resolve_event_time(symbol: str, market_title: Optional[str], event_ticker: Optional[str]) -> tuple[Optional[str], Optional[int]]:
    """Return (contract_label, hour_24) if we can parse a time from the market metadata.
    Contract label is simplified for DB: hourly e.g. 'BTC 2pm', 15m e.g. 'BTC 12:45pm'."""
    now_est = datetime.now(ZoneInfo("America/New_York"))
    time_hour_24 = None
    contract_label = None

    title = market_title or ""

    # 15m: "price today at 12:45pm" -> "BTC 12:45pm"
    match_15m = MARKET_TITLE_TODAY_15M_PATTERN.search(title)
    if match_15m:
        hour_str, minute_str, period = match_15m.groups()
        try:
            hour_val = int(hour_str)
            minute_val = int(minute_str)
            time_hour_24 = _hour_label_to_hour24(hour_val, period)
            time_label = f"{hour_val}:{minute_str}{period.lower()}"
            contract_label = f"{symbol.upper()} {time_label}"
        except Exception:
            pass

    if contract_label is None:
        match = MARKET_TITLE_DATE_PATTERN.search(title)
        if match:
            _, _, hour_str, period = match.groups()
            try:
                hour_val = int(hour_str)
                time_hour_24 = _hour_label_to_hour24(hour_val, period)
            except Exception:
                time_hour_24 = None

    if contract_label is None and time_hour_24 is None:
        match_today = MARKET_TITLE_TODAY_PATTERN.search(title)
        if match_today:
            hour_str, period = match_today.groups()
            try:
                hour_val = int(hour_str)
                time_hour_24 = _hour_label_to_hour24(hour_val, period)
            except Exception:
                time_hour_24 = None

    if contract_label is None and time_hour_24 is None and event_ticker:
        parts = event_ticker.split("-")
        if len(parts) >= 2:
            dt_part = parts[-1]
            if len(dt_part) >= 7:
                hour_part = dt_part[-2:]
                try:
                    hour_val = int(hour_part)
                    time_hour_24 = hour_val
                except Exception:
                    time_hour_24 = None

    if contract_label is None and time_hour_24 is not None:
        contract_label = f"{symbol.upper()} {_format_time_label(time_hour_24)}"
    if contract_label is None:
        return None, time_hour_24
    return contract_label, time_hour_24


def _compute_weekly_cycle(hour_24: Optional[int], reference_dt: Optional[datetime] = None) -> Optional[int]:
    if hour_24 is None:
        return None
    ref = reference_dt or datetime.now(ZoneInfo("America/New_York"))
    ref_est = ref.astimezone(ZoneInfo("America/New_York"))
    hour_idx = 24 if hour_24 == 0 else hour_24
    day_index = (ref_est.weekday() + 1) % 7
    weekly_cycle = day_index * 24 + hour_idx
    if weekly_cycle < 1 or weekly_cycle > 168:
        return None
    return weekly_cycle


def _fetch_performance_modifier(weekly_cycle: int) -> float:
    try:
        import psycopg2
        from psycopg2 import sql

        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        table_identifier = sql.SQL("{}.{}").format(
            sql.Identifier("users"),
            sql.Identifier(f"monitor_cycle_performance_{USER_NUMBER}_{MONITOR_ID}")
        )
        with conn.cursor() as cursor:
            cursor.execute(
                    sql.SQL("SELECT performance_modifier FROM {} WHERE weekly_cycle = %s").format(table_identifier),
                (weekly_cycle,)
            )
            row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return round(float(row[0]), 2)
    except Exception as e:
        log(f"[AUTO ENTRY] ⚠️ Unable to load performance modifier for weekly cycle {weekly_cycle}: {e}")
    return 1.00


def _fetch_max_pct_exposure(weekly_cycle: int) -> float:
    try:
        import psycopg2
        from psycopg2 import sql

        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        table_identifier = sql.SQL("{}.{}").format(
            sql.Identifier("users"),
            sql.Identifier(f"monitor_cycle_performance_{USER_NUMBER}_{MONITOR_ID}")
        )
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT max_pct_exposure FROM {} WHERE weekly_cycle = %s").format(table_identifier),
                (weekly_cycle,)
            )
            row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return round(float(row[0]), 2)
    except Exception as e:
        log(f"[AUTO ENTRY] ⚠️ Unable to load max_pct_exposure for weekly cycle {weekly_cycle}: {e}")
    return 0.25


def _apply_performance_based_multiplier(multiplier_value: float, position_size: Optional[int], position_type: Optional[str]) -> None:
    """Apply performance-based multiplier by reusing monitor_manager position update endpoint."""
    if multiplier_value is None:
        return

    try:
        position_size_val = int(position_size) if position_size is not None else 1
        position_type_val = (position_type or "contracts").lower()
        port = get_port("main")
        url = f"http://localhost:{port}/api/update_monitor_position"
        monitor_id_value = int(MONITOR_ID)
        payload = {
            "monitor_id": monitor_id_value,
            "position_size": position_size_val,
            "position_type": position_type_val,
            "multiplier": float(multiplier_value),
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            log(f"[AUTO ENTRY] ⚠️ Failed to apply performance-based multiplier {multiplier_value} (status {response.status_code}): {response.text}")
        else:
            _LAST_MONITOR_STATE["applied_multiplier"] = float(multiplier_value)
    except Exception as exc:
        log(f"[AUTO ENTRY] ⚠️ Error applying performance-based multiplier {multiplier_value}: {exc}")


def update_monitor_current_state(strike_table_data: Dict[str, Any]) -> None:
    """Update monitor_list with the current contract, weekly cycle, and performance modifier."""
    symbol = (strike_table_data or {}).get("symbol") or MONITOR_SYMBOL or "BTC"
    market_title = (strike_table_data or {}).get("market_title")
    event_ticker = (strike_table_data or {}).get("event_ticker")

    contract_label, hour_24 = _resolve_event_time(symbol, market_title, event_ticker)
    if not contract_label or hour_24 is None:
        return

    weekly_cycle = _compute_weekly_cycle(hour_24)
    if weekly_cycle is None:
        return

    performance_modifier = _fetch_performance_modifier(weekly_cycle)
    max_pct_exposure = _fetch_max_pct_exposure(weekly_cycle)
    position_size = None
    position_type = None
    performance_based_allocation = False
    existing_multiplier = None

    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT performance_based_allocation, position_size, position_type, multiplier
                FROM users.monitor_list_{USER_NUMBER}
                WHERE id = %s
                """,
                (MONITOR_ID,)
            )
            settings_row = cursor.fetchone()
            if settings_row:
                performance_based_allocation = bool(settings_row[0])
                position_size = settings_row[1]
                position_type = settings_row[2]
                existing_multiplier = settings_row[3]
                if existing_multiplier is not None:
                    try:
                        _LAST_MONITOR_STATE["applied_multiplier"] = float(existing_multiplier)
                    except (TypeError, ValueError):
                        pass

            cursor.execute(
                f"""
                UPDATE users.monitor_list_{USER_NUMBER}
                SET current_contract = %s,
                    current_weekly_cycle = %s,
                    current_performance_modifier = %s,
                    current_max_pct_exposure = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (contract_label, weekly_cycle, performance_modifier,
                 max_pct_exposure, MONITOR_ID)
            )
        conn.commit()
        conn.close()

        _LAST_MONITOR_STATE["contract"] = contract_label
        _LAST_MONITOR_STATE["weekly_cycle"] = weekly_cycle
        _LAST_MONITOR_STATE["modifier"] = performance_modifier
        _LAST_MONITOR_STATE["max_pct_exposure"] = max_pct_exposure

        if performance_based_allocation:
            new_multiplier = round(float(performance_modifier), 2)
            current_applied = _LAST_MONITOR_STATE.get("applied_multiplier")
            existing_multiplier_value = None
            try:
                if existing_multiplier is not None:
                    existing_multiplier_value = float(existing_multiplier)
            except (TypeError, ValueError):
                existing_multiplier_value = None

            needs_update = False
            if existing_multiplier_value is None:
                needs_update = True
            elif abs(existing_multiplier_value - new_multiplier) > 0.0009:
                needs_update = True
            elif current_applied is None or abs(current_applied - new_multiplier) > 0.0009:
                needs_update = True

            if needs_update:
                _apply_performance_based_multiplier(new_multiplier, position_size, position_type)
            else:
                _LAST_MONITOR_STATE["applied_multiplier"] = new_multiplier
    except Exception as e:
        log(f"[AUTO ENTRY] ⚠️ Unable to update monitor current state: {e}")
    except Exception as e:
        log(f"[AUTO ENTRY] ⚠️ Unable to update monitor current state: {e}")

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
            SELECT symbol, COALESCE(market, 'hourly') FROM users.monitor_list_{USER_NUMBER} 
            WHERE id = %s
        """, (MONITOR_ID,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            return result[0].upper(), (result[1] or 'hourly').strip().lower()  # (symbol, market)
        else:
            log(f"[AUTO_ENTRY_SUPERVISOR] ⚠️ No symbol found for monitor {MONITOR_IDENTIFIER}, defaulting to BTC")
            return "BTC", "hourly"
    except Exception as e:
        log(f"[AUTO_ENTRY_SUPERVISOR] ❌ Error getting monitor symbol: {e}, defaulting to BTC")
        return "BTC", "hourly"

def get_strike_table_name(symbol: str, market: str) -> str:
    """Strike table name from symbol and market (hourly or 15m)."""
    m = (market or 'hourly').strip().lower()
    if m not in ('hourly', '15m'):
        m = 'hourly'
    return f"strike_table_{m}_{symbol.lower()}"

# Get the symbol and market for this monitor (will be updated dynamically)
_monitor_symbol_market = get_monitor_symbol()
MONITOR_SYMBOL = _monitor_symbol_market[0] if isinstance(_monitor_symbol_market, tuple) else _monitor_symbol_market
MONITOR_MARKET = _monitor_symbol_market[1] if isinstance(_monitor_symbol_market, tuple) else 'hourly'
print(f"[AUTO_ENTRY_SUPERVISOR_{MONITOR_IDENTIFIER}] 📊 Initial symbol: {MONITOR_SYMBOL}, market: {MONITOR_MARKET}")

def get_current_monitor_symbol_and_market():
    """Get (symbol, market) for this monitor from database. market is 'hourly' or '15m'."""
    global MONITOR_SYMBOL, MONITOR_MARKET
    try:
        import psycopg2
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
                log(f"[AUTO_ENTRY_SUPERVISOR] 🔄 Monitor symbol/market: {MONITOR_SYMBOL}/{MONITOR_MARKET} -> {sym}/{mkt}")
                MONITOR_SYMBOL, MONITOR_MARKET = sym, mkt
            return sym, mkt
        return "BTC", "hourly"
    except Exception as e:
        return "BTC", "hourly"

def get_current_monitor_symbol():
    """Get the current symbol for this monitor (dynamic lookup)"""
    sym, _ = get_current_monitor_symbol_and_market()
    return sym

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

# Track if Momentum Breakout has entered trades for current cycle
momentum_breakout_trades_entered = False
momentum_breakout_last_contract = None  # Track the contract we entered trades for

momentum_contain_trades_entered = False
momentum_contain_last_contract = None  # Track the contract we entered trades for

# State tracking for logging reduction



# Database-based state management functions (PRIMARY SYSTEM)
def save_auto_entry_state_to_db(state):
    """Save auto entry state to production database"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
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
            host=os.getenv('POSTGRES_HOST', 'localhost'),
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
                
                # Calculate remaining time based on timestamp (can go negative to show elapsed time)
                spike_alert_active = False
                remaining_minutes = None
                
                if cooldown_start_time:
                    now = datetime.now(ZoneInfo("America/New_York"))
                    time_elapsed = (now - cooldown_start_time).total_seconds()
                    total_cooldown_seconds = cooldown_minutes * 60
                    remaining_seconds = total_cooldown_seconds - time_elapsed  # Can be negative
                    
                    # Spike alert is only active when timer is positive (within cooldown period)
                    if remaining_seconds > 0:
                        spike_alert_active = True
                        remaining_minutes = remaining_seconds / 60
                    else:
                        # Timer has expired or gone negative - spike alert inactive, but keep tracking elapsed time
                        remaining_minutes = remaining_seconds / 60  # Negative value shows elapsed time
                    
                    # Always update cooldown_timer (even when negative) to show time since last spike
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
                
                state = {
                    "user_id": "user_0001",
                    "monitor_id": "default",
                    "enabled": False,
                    "scanning_active": False,
                    "spike_alert_active": spike_alert_active,
                    "spike_alert_start_time": cooldown_start_time.isoformat() if cooldown_start_time else None,  # Always track, even when inactive
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
    
    # Just print to stdout - supervisor will capture this to .out.log
    # Use flush to ensure real-time logging
    print(log_message, flush=True)

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
        
        cooldown_str = f"{cooldown_timer}s" if cooldown_timer is not None else "None"  # Can be negative to show elapsed time
        
        log(f"💓 HEARTBEAT | Auto Trade: {auto_trade_enabled} | Symbol: {current_symbol} | Momentum: {momentum_str} | Cooldown: {cooldown_str}")
        
    except Exception as e:
        log(f"💓 HEARTBEAT | Error getting status: {e}")

# Legacy auto_entry_state.json functionality removed - now using PostgreSQL for all state management

def get_current_momentum(symbol="BTC"):
    """Get current momentum_5s_avg from live price log for specified symbol"""
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
        
        # Get momentum_5s_avg from live price log (symbol's live data stream)
        cursor.execute(f"""
            SELECT momentum_5s_avg FROM live_data.live_price_log_1s_{symbol.lower()} 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_5s_avg = float(result[0])
            return momentum_5s_avg
        else:
            return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum for {symbol}: {e}")
        return None

def get_momentum_30s_avg(symbol="BTC"):
    """Get current momentum_30s_avg from live price log for specified symbol"""
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
        
        # Get momentum_30s_avg from live price log (symbol's live data stream)
        cursor.execute(f"""
            SELECT momentum_30s_avg FROM live_data.live_price_log_1s_{symbol.lower()} 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_30s_avg = float(result[0])
            return momentum_30s_avg
        else:
            return None
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum_30s_avg for {symbol}: {e}")
        return None

def get_momentum_percentile(symbol="BTC"):
    """Get current momentum_percentile from live price log for specified symbol"""
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
        
        # Get momentum_percentile from live price log (symbol's live data stream)
        cursor.execute(f"""
            SELECT momentum_percentile FROM live_data.live_price_log_1s_{symbol.lower()} 
            ORDER BY timestamp DESC 
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
        log(f"[AUTO ENTRY MOMENTUM] Error getting momentum_percentile for {symbol}: {e}")
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
        
        # CRITICAL: Use the spike_alert_active from loaded state (which is based on cooldown timer)
        # This ensures Reverse HTC only activates when cooldown timer is actually positive
        spike_alert_active_from_db = state["spike_alert_active"]
        
        if spike_detected and not spike_alert_active_from_db:
            # SPIKE DETECTED - Enter spike alert mode (only if cooldown timer is not already active)
            state["spike_alert_active"] = True
            state["spike_alert_start_time"] = now.isoformat()
            state["spike_alert_momentum_value"] = current_momentum
            state["spike_alert_recovery_countdown"] = cooldown_minutes
            
            # Start cooldown period in database (timestamp-based)
            start_cooldown_period_in_db()
            
            log(f"[SPIKE ALERT] 🚨 SPIKE DETECTED! Momentum: {current_momentum:.2f} (threshold: ±{spike_threshold})")
            log(f"[SPIKE ALERT] Auto entry PAUSED for {cooldown_minutes} minutes")
        
        elif spike_alert_active_from_db:
            if recovery_conditions_met:
                # Check if recovery duration has passed
                if state["spike_alert_start_time"]:
                    spike_start = datetime.fromisoformat(state["spike_alert_start_time"])
                    time_in_recovery = (now - spike_start).total_seconds() / 60
                    
                    if time_in_recovery >= cooldown_minutes:
                        # RECOVERY COMPLETE - Exit spike alert mode (but keep cooldown_start_time for tracking)
                        state["spike_alert_active"] = False
                        state["spike_alert_momentum_value"] = None
                        state["spike_alert_recovery_countdown"] = None
                        # Note: spike_alert_start_time remains set in DB (cooldown_start_time) for tracking elapsed time
                        
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
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Update the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                f"UPDATE users.monitor_list_{USER_NUMBER} SET cooldown_start_time = NOW(), updated_at = CURRENT_TIMESTAMP WHERE id = %s",
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
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            # Reset the monitor in monitor_list (now single source of truth for cooldown)
            cursor.execute(
                f"UPDATE users.monitor_list_{USER_NUMBER} SET cooldown_start_time = NULL, cooldown_timer = 0, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
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
            host=os.getenv('POSTGRES_HOST', 'localhost'),
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
    """Determine the current auto entry status based on conditions - routes to strategy-specific logic"""
    try:
        strategy = get_trade_strategy()
        
        if strategy == "Momentum Scalp":
            return determine_auto_entry_status_momentum_scalp()
        elif strategy == "Momentum Reversal":
            return determine_auto_entry_status_momentum_reversal()
        elif strategy == "Reverse HTC":
            return determine_auto_entry_status_reverse_htc()
        elif strategy == "Momentum Breakout":
            return determine_auto_entry_status_momentum_breakout()
        elif strategy == "Momentum Contain":
            return determine_auto_entry_status_momentum_contain()
        else:
            # Default to Hourly HTC (including fallback)
            return determine_auto_entry_status_hourly_htc()
    except Exception as e:
        log(f"[AUTO ENTRY] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_hourly_htc():
    """Determine the current auto entry status for Hourly HTC strategy"""
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (no longer pauses - uses prob_adj instead)
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        
        # Note: spike_alert_active no longer causes PAUSED status - monitor continues with adjusted probability
        
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
        log(f"[AUTO ENTRY HTC] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_scalp():
    """Determine the current auto entry status for Momentum Scalp strategy"""
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time", "min_probability", "momentum_scalp_entry_threshold"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # LAYER 1: Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if not ttc_within_window:
            return "INACTIVE"
        
        # LAYER 2: Check if momentum spike is detected
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        if momentum_threshold is None:
            return "DISABLED"  # Missing momentum threshold
        
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            return "INACTIVE"  # Cannot determine momentum
        
        # Check if momentum is above threshold (positive) or below -threshold (negative)
        momentum_spike_detected = (current_momentum >= momentum_threshold) or (current_momentum <= -momentum_threshold)
        
        if not momentum_spike_detected:
            return "INACTIVE"
        
        # Both layers pass - monitor is ACTIVE
        return "ACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY MS] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_reversal():
    """Determine the current auto entry status for Momentum Reversal strategy"""
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time", "min_probability", "momentum_scalp_entry_threshold"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # LAYER 1: Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if not ttc_within_window:
            return "INACTIVE"
        
        # LAYER 2: Check if momentum spike is detected
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        if momentum_threshold is None:
            return "DISABLED"  # Missing momentum threshold
        
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            return "INACTIVE"  # Cannot determine momentum
        
        # Check if momentum is above threshold (positive) or below -threshold (negative)
        momentum_spike_detected = (current_momentum >= momentum_threshold) or (current_momentum <= -momentum_threshold)
        
        if not momentum_spike_detected:
            return "INACTIVE"
        
        # Both layers pass - monitor is ACTIVE
        return "ACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY MR] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_reverse_htc():
    """Determine the current auto entry status for Reverse HTC strategy
    
    Reverse HTC activates when momentum spike is detected (opposite of Hourly HTC).
    It trades during the cooldown period when Hourly HTC would be paused.
    """
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (REQUIRED for Reverse HTC to activate)
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        
        if not spike_alert_active:
            return "INACTIVE"  # Reverse HTC only activates during momentum spikes
        
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
        log(f"[AUTO ENTRY REVERSE HTC] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_breakout():
    """Determine the current auto entry status for Momentum Breakout strategy
    
    Momentum Breakout activates when momentum spike is detected (same as Reverse HTC).
    It uses the same activation logic but with simplified entry criteria.
    """
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (REQUIRED for Momentum Breakout to activate)
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        
        if not spike_alert_active:
            return "INACTIVE"  # Momentum Breakout only activates during momentum spikes
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
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
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Error determining status: {e}")
        return "DISABLED"

def determine_auto_entry_status_momentum_contain():
    """Determine the current auto entry status for Momentum Contain strategy
    
    Momentum Contain activates when momentum spike is detected (same as Momentum Breakout).
    It uses the same activation logic but with flipped trade sides (contrarian strategy).
    """
    try:
        # Check if auto trade is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        if not auto_trade_enabled:
            return "DISABLED"
        
        # Check if service is healthy
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not service_healthy:
            return "DISABLED"  # Service not running
        
        # Check if spike alert is active (REQUIRED for Momentum Contain to activate)
        spike_alert_active = auto_entry_indicator_state.get("spike_alert_active", False)
        
        if not spike_alert_active:
            return "INACTIVE"  # Momentum Contain only activates during momentum spikes
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        
        if missing_settings:
            return "DISABLED"  # Missing required settings
        
        # Check if TTC is within window
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        current_ttc = get_current_ttc()
        ttc_within_window = min_time <= current_ttc <= max_time
        
        if not ttc_within_window:
            return "INACTIVE"
        
        # Check if cooldown timer is within activation window
        min_cooldown_timer = settings.get("min_cooldown_timer")
        max_cooldown_timer = settings.get("max_cooldown_timer")
        
        # If both min and max are NULL, skip the check (no restriction)
        if min_cooldown_timer is None and max_cooldown_timer is None:
            return "ACTIVE"
        
        # Get cooldown_timer from database
        cooldown_timer = None
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
                cooldown_timer = result[0] if result and result[0] is not None else None
            conn.close()
        except Exception as e:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error getting cooldown timer: {e}")
        
        # If cooldown_timer is NULL, cannot determine - return INACTIVE
        if cooldown_timer is None:
            return "INACTIVE"
        
        # Check if cooldown_timer is within the activation window
        # If min is set, cooldown_timer must be >= min (not too close to spike)
        if min_cooldown_timer is not None and cooldown_timer < min_cooldown_timer:
            return "INACTIVE"  # Too close to momentum spike
        
        # If max is set, cooldown_timer must be <= max (not too far after spike)
        if max_cooldown_timer is not None and cooldown_timer > max_cooldown_timer:
            return "INACTIVE"  # Too far after spike regime has ended
        
        # All checks passed - cooldown timer is within window
        return "ACTIVE"
            
    except Exception as e:
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error determining status: {e}")
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
                    SELECT min_probability, max_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
                           spike_alert_enabled, spike_alert_momentum_threshold, 
                           spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                           min_volume, momentum_scalp_entry_threshold, min_ask, max_ask, max_price_spread, prob_adj,
                           min_cooldown_timer, max_cooldown_timer
                    FROM users.monitor_list_0001 WHERE id = %s
                """, (MONITOR_IDENTIFIER.split('_')[1],))
                strategy_result = cursor.fetchone()
                
                if strategy_result:
                    settings = {
                        "min_probability": float(strategy_result[0]) if strategy_result[0] is not None else 95.0,
                        "max_probability": float(strategy_result[1]) if strategy_result[1] is not None else 100.0,
                        "min_differential": float(strategy_result[2]),
                        "max_differential": float(strategy_result[3]) if strategy_result[3] is not None else None,
                        "min_time": strategy_result[4],
                        "max_time": strategy_result[5],
                        "allow_re_entry": strategy_result[6],
                        "spike_alert_enabled": strategy_result[7],
                        "spike_alert_momentum_threshold": strategy_result[8],
                        "spike_alert_cooldown_threshold": strategy_result[9],
                        "spike_alert_cooldown_minutes": strategy_result[10],
                        "min_volume": strategy_result[11],  # From monitor min_volume
                        "momentum_scalp_entry_threshold": float(strategy_result[12]) if strategy_result[12] is not None else None,
                        "min_ask": float(strategy_result[13]) if strategy_result[13] is not None else 0.0000,
                        "max_ask": float(strategy_result[14]) if strategy_result[14] is not None else 0.9800,
                        "max_price_spread": float(strategy_result[15]) if strategy_result[15] is not None else 0.0300,
                        "prob_adj": float(strategy_result[16]) if strategy_result[16] is not None else 5.00,
                        "min_cooldown_timer": strategy_result[17] if strategy_result[17] is not None else None,
                        "max_cooldown_timer": strategy_result[18] if strategy_result[18] is not None else None
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
    """Get current TTC from unified TTC endpoint (requires market: hourly or 15m)."""
    try:
        port = get_port("main_app")
        current_symbol, current_market = get_current_monitor_symbol_and_market()
        if not current_market or current_market not in ("hourly", "15m"):
            return 0
        url = f"http://localhost:{port}/api/unified_ttc/{current_symbol.lower()}?market={current_market}"
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
    """Get current master strike table data from PostgreSQL (uses monitor symbol + market)."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            current_symbol, current_market = get_current_monitor_symbol_and_market()
            table_name = get_strike_table_name(current_symbol, current_market)
            # Hourly: ttc_hourly/probability_hourly; 15m: ttc_15m/probability_15m (same column set).
            ttc_column = "ttc_15m" if current_market == "15m" else "ttc_hourly"
            prob_column = "probability_15m" if current_market == "15m" else "probability_hourly"
            cursor.execute(f"""
                SELECT
                    symbol,
                    current_price,
                    {ttc_column},
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status
                FROM live_data.{table_name}
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
                    {prob_column},
                    yes_ask,
                    no_ask,
                    yes_ask_dollars,
                    no_ask_dollars,
                    volume,
                    ticker,
                    yes_diff,
                    no_diff,
                    active_side,
                    yes_price_spread,
                    no_price_spread
                FROM live_data.{table_name}
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
                    "yes_ask_dollars": strike_row[6],
                    "no_ask_dollars": strike_row[7],
                    "volume": int(strike_row[8]) if strike_row[8] else None,
                    "ticker": strike_row[9],
                    "yes_diff": float(strike_row[10]) if strike_row[10] else None,
                    "no_diff": float(strike_row[11]) if strike_row[11] else None,
                    "active_side": strike_row[12],
                    "yes_price_spread": float(strike_row[13]) if strike_row[13] is not None else None,
                    "no_price_spread": float(strike_row[14]) if strike_row[14] is not None else None
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
    conn = None
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

def get_current_multiplier():
    """Get current multiplier value for this monitor."""
    conn = None
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT multiplier FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result and result[0] is not None:
                multiplier_value = float(result[0])
                log(f"[AUTO ENTRY] Multiplier loaded from monitor {MONITOR_ID}: {multiplier_value}")
                return multiplier_value
            else:
                log(f"[AUTO ENTRY] No multiplier found for monitor {MONITOR_ID} - defaulting to 1.0")
                return 1.0
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading multiplier from monitor {MONITOR_ID}: {e}")
        return 1.0
    finally:
        if conn:
            conn.close()

def get_loss_prevention_state():
    """Get loss_prevention state from monitor-specific configuration"""
    conn = None
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT loss_prevention FROM users.monitor_list_0001 WHERE id = %s", (MONITOR_ID,))
            result = cursor.fetchone()
            if result:
                loss_prevention = result[0]
                log(f"[AUTO ENTRY] Loss prevention state loaded from monitor {MONITOR_ID}: {loss_prevention}")
                return loss_prevention
            else:
                log(f"[AUTO ENTRY] No monitor configuration found for monitor {MONITOR_ID}")
                return "off"  # Default to off if not found
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading loss_prevention from monitor {MONITOR_ID}: {e}")
        return "off"  # Default to off on error
    finally:
        if conn:
            conn.close()

def get_trade_strategy():
    """Get trade strategy from monitor-specific configuration"""
    conn = None
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
                return trade_strategy
            else:
                return "Hourly HTC"  # Default fallback
    except Exception as e:
        log(f"[AUTO ENTRY] Error loading trade strategy from monitor {MONITOR_ID}: {e}")
        return "Hourly HTC"  # Default fallback
    finally:
        if conn:
            conn.close()

def get_bankroll_allotment():
    """Get bankroll allotment total from monitor-specific configuration"""
    conn = None
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
        
        # Get contract name in same simplified form as hourly (e.g. "BTC 2pm", "BTC 12:45pm" for 15m)
        strike_table_data = get_master_strike_table_data()
        current_symbol = get_current_monitor_symbol()
        contract_label, _ = _resolve_event_time(
            current_symbol,
            strike_table_data.get("market_title") if strike_table_data else None,
            strike_table_data.get("event_ticker") if strike_table_data else None,
        )
        contract_name = contract_label or (strike_table_data.get("market_title") if strike_table_data else None) or f"{current_symbol} Market"
        
        # Get position size from trade preferences
        position_size = get_position_size()
        if position_size is None:
            log(f"[AUTO ENTRY] ❌ Cannot trigger trade - no valid position size found")
            return False
        
        # Check loss prevention state and override position size if needed
        loss_prevention = get_loss_prevention_state()
        if loss_prevention == "one_contract":
            log(f"[AUTO ENTRY] 🛡️ Loss prevention active - overriding position size from {position_size} to 1 contract")
            position_size = 1
        else:
            log(f"[AUTO ENTRY] Loss prevention is '{loss_prevention}' - using configured position size: {position_size}")
        
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
        
        # Get paper_trade setting from monitor config
        paper_trade = False
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=os.getenv('POSTGRES_HOST', 'localhost'),
                database=os.getenv('POSTGRES_DB', 'rec_io_db'),
                user=os.getenv('POSTGRES_USER', 'rec_io_user'),
                password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
            )
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT paper_trade FROM users.monitor_list_{USER_NUMBER} WHERE id = %s", (MONITOR_ID,))
                result = cursor.fetchone()
                if result and result[0] is not None:
                    paper_trade = bool(result[0])
            conn.close()
        except Exception as e:
            log(f"[AUTO ENTRY] ⚠️ Could not get paper_trade setting: {e}, defaulting to False")
        
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
            "prob": strike_data.get("probability"),
            "diff": strike_data.get("diff"),
            "buy_price": strike_data.get("buy_price"),
            "position": position_size,
            "monitor": f"mon_0001_{MONITOR_ID}",
            "bankroll_allotment_total": bankroll_allotment,
            "entry_method": "auto_entry",
            "loss_prevention": loss_prevention == "one_contract",
            "multiplier": get_current_multiplier(),
            "paper_trade": paper_trade
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

def has_bracket_for_cycle(contract: Optional[str] = None, strike_tier: Optional[int] = None) -> bool:
    """Check if a bracket exists for the current cycle (contract/date).
    
    A bracket is defined as: one Y trade and one N trade with strikes within 2 strike tiers of each other.
    This function queries trades_0001 for open/pending trades from this monitor with the same contract.
    
    Args:
        contract: The contract label (e.g., "BTC 12pm"). If None, uses _LAST_MONITOR_STATE["contract"].
        strike_tier: The strike tier spacing (e.g., 250 for BTC, 50 for ETH). If None, tries to get from strike table data.
    
    Returns:
        True if a bracket exists (Y and N trades within 2 strike tiers), False otherwise.
    """
    try:
        import psycopg2
        
        # Get contract from parameter or from state
        if contract is None:
            contract = _LAST_MONITOR_STATE.get("contract")
        
        if not contract:
            # No contract available, can't check bracket
            return False
        
        # Get strike_tier if not provided
        if strike_tier is None:
            # Try to get from strike table data
            strike_table_data = get_master_strike_table_data()
            if strike_table_data and strike_table_data.get("strike_tier"):
                try:
                    strike_tier = int(strike_table_data["strike_tier"])
                except (ValueError, TypeError):
                    strike_tier = None
        
        if strike_tier is None or strike_tier <= 0:
            # Can't determine bracket distance without strike tier
            log(f"[AUTO ENTRY REVERSE HTC] ⚠️ Cannot check bracket - strike_tier not available")
            return False
        
        # Calculate bracket distance: 2 strikes = 2 * strike_tier
        bracket_distance = 2 * strike_tier
        
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        cursor = conn.cursor()
        
        # Get current monitor identifier
        current_monitor = f"mon_0001_{MONITOR_ID}"
        
        # Query trades_0001 table for open/pending trades from this monitor with the same contract
        cursor.execute("""
            SELECT id, strike, side, status, contract, date
            FROM users.trades_0001 
            WHERE status IN ('open', 'pending')
              AND monitor = %s
              AND contract = %s
        """, (current_monitor, contract))
        
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            return False
        
        # Parse strikes and separate by side
        yes_trades = []
        no_trades = []
        
        # Helper function to parse strike value (e.g., "$50,000" -> 50000)
        def parse_strike(strike_str: str) -> Optional[float]:
            if not strike_str:
                return None
            # Remove $ and commas, then convert to float
            cleaned = strike_str.replace('$', '').replace(',', '').strip()
            try:
                return float(cleaned)
            except (ValueError, TypeError):
                return None
        
        for trade in trades:
            trade_id, strike_str, side, status, trade_contract, trade_date = trade
            
            # Normalize side
            normalized_side = str(side).upper()
            if normalized_side in ['Y', 'YES']:
                strike_value = parse_strike(strike_str)
                if strike_value is not None:
                    yes_trades.append(strike_value)
            elif normalized_side in ['N', 'NO']:
                strike_value = parse_strike(strike_str)
                if strike_value is not None:
                    no_trades.append(strike_value)
        
        # Check if we have at least one Y and one N trade
        if not yes_trades or not no_trades:
            return False
        
        # Check if any Y and N trades are within bracket_distance of each other
        for yes_strike in yes_trades:
            for no_strike in no_trades:
                strike_diff = abs(yes_strike - no_strike)
                if strike_diff <= bracket_distance:
                    # Bracket found
                    return True
        
        # No bracket found
        return False
        
    except Exception as e:
        log(f"[AUTO ENTRY REVERSE HTC] ⚠️ Error checking bracket: {e}")
        # On error, allow trading (fail open)
        return False

def is_strike_already_traded(strike_data):
    """Check if we already have an open or pending trade on this strike by querying trades_0001 table directly.
    Only blocks new trades if there's an existing trade from the SAME MONITOR on the same strike/side."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            database=os.getenv('POSTGRES_DB', 'rec_io_db'),
            user=os.getenv('POSTGRES_USER', 'rec_io_user'),
            password=os.getenv('POSTGRES_PASSWORD', 'rec_io_password')
        )
        cursor = conn.cursor()
        
        # Get current monitor identifier
        current_monitor = f"mon_0001_{MONITOR_ID}"
        
        # Query trades_0001 table directly for open/pending trades with ticker AND same monitor
        cursor.execute("""
            SELECT id, ticker, side, status, monitor 
            FROM users.trades_0001 
            WHERE status IN ('open', 'pending')
        """)
        
        trades = cursor.fetchall()
        conn.close()
        
        ticker = strike_data.get('ticker')
        side = strike_data.get('side')
        
        # Don't log every check - only log when we find a match
        for trade in trades:
            trade_id, trade_ticker, trade_side, trade_status, trade_monitor = trade
            
            # Only check trades from the same monitor
            if trade_monitor != current_monitor:
                continue
            
            # Normalize side comparison (Y = yes, N = no)
            normalized_trade_side = str(trade_side).upper()
            normalized_strike_side = side.upper() if side else ''
            
            # Handle Y/YES and N/NO mapping
            if normalized_trade_side == 'Y' and normalized_strike_side == 'YES':
                normalized_trade_side = 'YES'
            elif normalized_trade_side == 'N' and normalized_strike_side == 'NO':
                normalized_trade_side = 'NO'
            
            # Compare ticker and side
            if (trade_ticker == ticker and 
                normalized_trade_side == normalized_strike_side):
                log(f"⚠️ Found {trade_status} trade (ID: {trade_id}) on {strike_data.get('strike', 'unknown')} {side} from same monitor {current_monitor}")
                return True
        
        # Don't log when no match found - this happens constantly and creates spam
        return False
    except Exception as e:
        log(f"Error checking trades_0001 table: {e}")
        return False

def check_auto_entry_conditions():
    """Check if auto entry conditions are met and trigger trades - routes to strategy-specific logic"""
    try:
        # ALWAYS check spike alert conditions first (even during closed hours) to monitor momentum spikes
        check_spike_alert_conditions()
        
        # MARKET HOURS CHECK: Kalshi markets closed 00:00-08:00 EST
        # Skip trade entry during closed hours, but spike monitoring continues above
        # COMMENTED OUT: Time restriction disabled - auto_entry_supervisor can now find entries during these hours
        # now_est = datetime.now(ZoneInfo("America/New_York"))
        # current_hour = now_est.hour
        # if 0 <= current_hour < 8:  # Between midnight and 8am EST
        #     return  # Skip trade entry checks during closed hours (spike monitoring already done)
        
        strategy = get_trade_strategy()
        
        if strategy == "Momentum Scalp":
            check_auto_entry_conditions_momentum_scalp()
        elif strategy == "Momentum Reversal":
            check_auto_entry_conditions_momentum_reversal()
        elif strategy == "Reverse HTC":
            check_auto_entry_conditions_reverse_htc()
        elif strategy == "Momentum Breakout":
            check_auto_entry_conditions_momentum_breakout()
        elif strategy == "Momentum Contain":
            check_auto_entry_conditions_momentum_contain()
        else:
            # Default to Hourly HTC (including fallback)
            check_auto_entry_conditions_hourly_htc()
    except Exception as e:
        import traceback
        log(f"[AUTO ENTRY] ❌ Error checking entry conditions: {e}")
        log(f"[AUTO ENTRY] ❌ Traceback: {traceback.format_exc()}")

def check_auto_entry_conditions_hourly_htc():
    """Check if auto entry conditions are met and trigger trades for Hourly HTC strategy"""
    global auto_entry_indicator_state
    
    try:
        # Get strike table data directly (no watchlist needed)
        
        # Check spike alert conditions first
        check_spike_alert_conditions()

        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)

        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (no longer blocks - uses prob_adj to adjust probability instead)
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
        required_settings = ["min_time", "max_time", "min_probability", "max_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY] ❌ Missing required settings: {missing_settings}")
            log(f"[AUTO ENTRY] Cannot proceed without complete settings configuration")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        base_min_probability = settings["min_probability"]
        max_probability = settings["max_probability"]
        min_differential = settings["min_differential"]
        
        # Apply prob_adj adjustment during spike alert cooldown
        prob_adj = settings.get("prob_adj", 5.00)  # Default to 5.00 if not set
        if spike_alert_active:
            min_probability = base_min_probability + prob_adj
            log(f"[AUTO ENTRY] 📊 Using adjusted probability: {base_min_probability:.2f} + {prob_adj:.2f} = {min_probability:.2f}% (spike cooldown active)")
        else:
            min_probability = base_min_probability
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window
        # Note: spike_alert_active no longer blocks scanning - it adjusts probability instead
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window)
        
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
            # Log occasionally when TTC is outside window
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_ttc_log'):
                check_auto_entry_conditions_hourly_htc.last_ttc_log = 0
            if current_time - check_auto_entry_conditions_hourly_htc.last_ttc_log >= 300:  # Log every 5 minutes
                log(f"[AUTO ENTRY] ⏸️ TTC outside window: {current_ttc}s (window: {min_time}-{max_time}s)")
                check_auto_entry_conditions_hourly_htc.last_ttc_log = current_time
            return
        
        # Note: spike_alert_active no longer blocks trades - probability is adjusted instead (see min_probability calculation above)
        
        if not strike_table_data:
            # Log occasionally if strike table data is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_strike_table_log'):
                check_auto_entry_conditions_hourly_htc.last_strike_table_log = 0
            if current_time - check_auto_entry_conditions_hourly_htc.last_strike_table_log >= 60:  # Log every 60 seconds
                log(f"[AUTO ENTRY] ⚠️ No strike table data available")
                check_auto_entry_conditions_hourly_htc.last_strike_table_log = current_time
            return
        
        if "strikes" not in strike_table_data:
            # Log occasionally if strikes array is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_strikes_missing_log'):
                check_auto_entry_conditions_hourly_htc.last_strikes_missing_log = 0
            if current_time - check_auto_entry_conditions_hourly_htc.last_strikes_missing_log >= 60:  # Log every 60 seconds
                log(f"[AUTO ENTRY] ⚠️ Strike table data missing 'strikes' array")
                check_auto_entry_conditions_hourly_htc.last_strikes_missing_log = current_time
            return
        
        # Log that we're scanning strikes (only log occasionally to avoid spam)
        import time
        current_time = time.time()
        if not hasattr(check_auto_entry_conditions_hourly_htc, 'last_scan_log'):
            check_auto_entry_conditions_hourly_htc.last_scan_log = 0
        if current_time - check_auto_entry_conditions_hourly_htc.last_scan_log >= 60:  # Log every 60 seconds
            strike_count = len(strike_table_data.get("strikes", []))
            prob_display = f"{min_probability:.2f}-{max_probability}%"
            if spike_alert_active:
                prob_display += f" (adjusted: {base_min_probability:.2f}+{prob_adj:.2f})"
            log(f"[AUTO ENTRY] 🔍 Scanning {strike_count} strikes | TTC: {current_ttc}s | Window: {min_time}-{max_time}s | Prob: {prob_display}")
            check_auto_entry_conditions_hourly_htc.last_scan_log = current_time
        
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
                
                # STEP 3: Check probability window (min_probability <= prob <= max_probability)
                prob = strike.get('probability')
                if prob is None or prob < min_probability or prob > max_probability:
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
                        continue
                
                # STEP 5: Check volume threshold
                min_volume = settings.get("min_volume", 1000)
                volume = strike.get('volume', 0)
                if volume is None or volume < min_volume:
                    continue
                
                # STEP 6: Check max ask price threshold using _dollars values
                max_ask = settings.get("max_ask", 0.9800)  # Default in dollars
                yes_ask_dollars = strike.get('yes_ask_dollars')
                no_ask_dollars = strike.get('no_ask_dollars')
                if not yes_ask_dollars or not no_ask_dollars:
                    continue
                # Convert _dollars to cents for comparison
                yes_ask_cents = float(yes_ask_dollars) * 100
                no_ask_cents = float(no_ask_dollars) * 100
                max_ask_price = max(yes_ask_cents, no_ask_cents)
                # Convert max_ask from dollars to cents if it's less than 1 (indicating dollars format)
                # Otherwise assume it's already in cents (legacy support)
                max_ask_cents = max_ask * 100 if max_ask < 1 else max_ask
                if max_ask_price > max_ask_cents:
                    continue
                
                # STEP 5: Determine buy price based on active_side using subpenny precision
                if active_side == 'yes':
                    side = 'yes'
                    # Use yes_ask_dollars directly (no conversion needed)
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        log(f"⚠️ Missing yes_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(yes_ask_dollars)
                elif active_side == 'no':
                    side = 'no'
                    # Use no_ask_dollars directly (no conversion needed)
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        log(f"⚠️ Missing no_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(no_ask_dollars)
                else:
                    continue
                
                # STEP 6: Get diff value for the active side
                diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                
                # STEP 7: Prepare strike data for trade trigger
                strike_data = {
                    'strike': f"${int(strike.get('strike')):,}",
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob,
                    'diff': diff
                }
                
                # STEP 8: Check if strike is already traded
                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY] ⏸️ Skipping {strike_key} - already has open/pending trade")
                    continue
                
                # STEP 9: Trigger the trade
                log(f"[AUTO ENTRY] 🚀 TRIGGERING TRADE | {strike_key} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Ticker: {strike.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY] ✅ TRADE SUCCESSFUL | {strike_key} | Trade triggered and sent to trade_manager")
                else:
                    log(f"[AUTO ENTRY] ❌ TRADE FAILED | {strike_key} | Failed to trigger trade")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY HTC] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY HTC] Error checking auto entry conditions: {e}")

def check_auto_entry_conditions_reverse_htc():
    """Check if auto entry conditions are met and trigger trades for Reverse HTC strategy
    
    Reverse HTC activates when momentum spike is detected (opposite of Hourly HTC).
    It uses the same entry logic as Hourly HTC but enters with the OPPOSITE side.
    """
    global auto_entry_indicator_state
    
    try:
        # Get strike table data directly (no watchlist needed)
        
        # Check spike alert conditions first
        check_spike_alert_conditions()

        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)

        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (REQUIRED for Reverse HTC to activate)
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
        required_settings = ["min_time", "max_time", "min_probability", "max_probability", "min_differential"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY REVERSE HTC] ❌ Missing required settings: {missing_settings}")
            log(f"[AUTO ENTRY REVERSE HTC] Cannot proceed without complete settings configuration")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_probability = settings["min_probability"]
        max_probability = settings["max_probability"]
        min_differential = settings["min_differential"]
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window + spike alert active (REQUIRED for Reverse HTC)
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          spike_alert_active)  # SPIKE ALERT REQUIRED for Reverse HTC
        
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
            # Log occasionally when TTC is outside window
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_ttc_log'):
                check_auto_entry_conditions_reverse_htc.last_ttc_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_ttc_log >= 300:  # Log every 5 minutes
                log(f"[AUTO ENTRY REVERSE HTC] ⏸️ TTC outside window: {current_ttc}s (window: {min_time}-{max_time}s)")
                check_auto_entry_conditions_reverse_htc.last_ttc_log = current_time
            return
        
        # SPIKE ALERT CHECK - Reverse HTC REQUIRES spike alert to be active
        if not spike_alert_active:
            log(f"[AUTO ENTRY REVERSE HTC] ⏸️ SPIKE ALERT NOT ACTIVE - Reverse HTC requires momentum spike to activate")
            return
        
        # BRACKET CHECK - Reverse HTC should only enter trades until a bracket is formed
        # A bracket is: one Y trade and one N trade with strikes within 2 strike tiers of each other
        # Use contract_label from _LAST_MONITOR_STATE (same format as what trade_manager stores after truncation)
        current_contract = _LAST_MONITOR_STATE.get("contract")
        strike_tier = strike_table_data.get("strike_tier") if strike_table_data else None
        if strike_tier:
            try:
                strike_tier = int(strike_tier)
            except (ValueError, TypeError):
                strike_tier = None
        
        if has_bracket_for_cycle(current_contract, strike_tier):
            # Log occasionally to avoid spam
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_bracket_log'):
                check_auto_entry_conditions_reverse_htc.last_bracket_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_bracket_log >= 300:  # Log every 5 minutes
                bracket_distance = 2 * strike_tier if strike_tier else "unknown"
                log(f"[AUTO ENTRY REVERSE HTC] ⏸️ BRACKET FORMED - No further entries for cycle {current_contract} (bracket distance: {bracket_distance})")
                check_auto_entry_conditions_reverse_htc.last_bracket_log = current_time
            return
        
        if not strike_table_data:
            # Log occasionally if strike table data is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_strike_table_log'):
                check_auto_entry_conditions_reverse_htc.last_strike_table_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_strike_table_log >= 60:  # Log every 60 seconds
                log(f"[AUTO ENTRY REVERSE HTC] ⚠️ No strike table data available")
                check_auto_entry_conditions_reverse_htc.last_strike_table_log = current_time
            return
        
        if "strikes" not in strike_table_data:
            # Log occasionally if strikes array is missing
            import time
            current_time = time.time()
            if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_strikes_missing_log'):
                check_auto_entry_conditions_reverse_htc.last_strikes_missing_log = 0
            if current_time - check_auto_entry_conditions_reverse_htc.last_strikes_missing_log >= 60:  # Log every 60 seconds
                log(f"[AUTO ENTRY REVERSE HTC] ⚠️ Strike table data missing 'strikes' array")
                check_auto_entry_conditions_reverse_htc.last_strikes_missing_log = current_time
            return
        
        # Log that we're scanning strikes (only log occasionally to avoid spam)
        import time
        current_time = time.time()
        if not hasattr(check_auto_entry_conditions_reverse_htc, 'last_scan_log'):
            check_auto_entry_conditions_reverse_htc.last_scan_log = 0
        if current_time - check_auto_entry_conditions_reverse_htc.last_scan_log >= 60:  # Log every 60 seconds
            strike_count = len(strike_table_data.get("strikes", []))
            log(f"[AUTO ENTRY REVERSE HTC] 🔍 Scanning {strike_count} strikes | TTC: {current_ttc}s | Window: {min_time}-{max_time}s | Prob: {min_probability}-{max_probability}% | SPIKE ACTIVE")
            check_auto_entry_conditions_reverse_htc.last_scan_log = current_time
        
        # Process each strike ONCE
        processed_strikes = set()  # Prevent duplicate processing
        
        for i, strike in enumerate(strike_table_data["strikes"]):
            try:
                # Use active_side for strike_key generation (EXACT SAME AS HOURLY HTC)
                active_side = strike.get('active_side')
                if not active_side:
                    continue
                    
                strike_key = f"{strike.get('strike')}-{active_side}"
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                
                processed_strikes.add(strike_key)
                
                # STEP 1: ATOMIC cooldown check (EXACT SAME AS HOURLY HTC)
                if not can_trade_strike(strike_key):
                    continue
                
                # STEP 1.5: BRACKET CHECK BEFORE EACH TRADE - Prevent entering if bracket already exists
                # Check bracket before triggering trade to prevent third entry
                # Use current_contract (set at function start) which matches database format
                if current_contract and has_bracket_for_cycle(current_contract, strike_tier):
                    bracket_distance = 2 * strike_tier if strike_tier else "unknown"
                    log(f"[AUTO ENTRY REVERSE HTC] ⏸️ BRACKET EXISTS - Skipping strike {strike_key} for cycle {current_contract} (bracket distance: {bracket_distance})")
                    continue  # Skip this strike if bracket already exists
                
                # STEP 2: Check if we already have an active trade on this strike
                # REVERSE HTC: Check opposite side (since we'll be trading opposite side)
                opposite_side = 'no' if active_side == 'yes' else 'yes'
                strike_data_for_check = {
                    'strike': strike.get('strike'),
                    'side': opposite_side,
                    'ticker': strike.get('ticker')
                }
                
                if is_strike_already_traded(strike_data_for_check):
                    continue
                
                # STEP 3: Check probability window (EXACT SAME AS HOURLY HTC)
                prob = strike.get('probability')
                if prob is None or prob < min_probability or prob > max_probability:
                    continue
                
                # STEP 4: Check differential threshold (EXACT SAME AS HOURLY HTC)
                if min_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff < (min_differential - 0.5):
                        continue
                
                # STEP 4.5: Check max differential threshold (EXACT SAME AS HOURLY HTC)
                max_differential = settings.get("max_differential")
                if max_differential is not None:
                    diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                    if diff is None or diff > max_differential:
                        continue
                
                # STEP 5: Check volume threshold (EXACT SAME AS HOURLY HTC)
                min_volume = settings.get("min_volume", 1000)
                volume = strike.get('volume', 0)
                if volume is None or volume < min_volume:
                    continue
                
                # STEP 6: Check max ask price threshold (EXACT SAME AS HOURLY HTC)
                max_ask = settings.get("max_ask", 0.9800)  # Default in dollars
                yes_ask_dollars = strike.get('yes_ask_dollars')
                no_ask_dollars = strike.get('no_ask_dollars')
                if not yes_ask_dollars or not no_ask_dollars:
                    continue
                # Convert _dollars to cents for comparison
                yes_ask_cents = float(yes_ask_dollars) * 100
                no_ask_cents = float(no_ask_dollars) * 100
                max_ask_price = max(yes_ask_cents, no_ask_cents)
                # Convert max_ask from dollars to cents if it's less than 1 (indicating dollars format)
                # Otherwise assume it's already in cents (legacy support)
                max_ask_cents = max_ask * 100 if max_ask < 1 else max_ask
                if max_ask_price > max_ask_cents:
                    continue
                
                # STEP 7: Determine buy price based on active_side (EXACT SAME AS HOURLY HTC)
                if active_side == 'yes':
                    side = 'yes'
                    # Use yes_ask_dollars directly (no conversion needed)
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        log(f"⚠️ Missing yes_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(yes_ask_dollars)
                elif active_side == 'no':
                    side = 'no'
                    # Use no_ask_dollars directly (no conversion needed)
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        log(f"⚠️ Missing no_ask_dollars for strike {strike.get('strike')}, skipping")
                        continue
                    buy_price = float(no_ask_dollars)
                else:
                    continue
                
                # STEP 8: Get diff value for the active side (EXACT SAME AS HOURLY HTC)
                diff = strike.get('yes_diff') if active_side == 'yes' else strike.get('no_diff')
                
                # REVERSE HTC: ONLY DIFFERENCE - flip the side when submitting the order
                # (opposite_side was already calculated at Step 2)
                opposite_buy_price = float(strike.get('no_ask_dollars') if opposite_side == 'no' else strike.get('yes_ask_dollars'))
                opposite_diff = strike.get('no_diff') if opposite_side == 'no' else strike.get('yes_diff')
                
                # STEP 9: Prepare strike data for trade trigger (using OPPOSITE side - ONLY DIFFERENCE)
                strike_data = {
                    'strike': f"${int(strike.get('strike')):,}",
                    'side': opposite_side,
                    'ticker': strike.get('ticker'),
                    'buy_price': opposite_buy_price,
                    'probability': prob,
                    'diff': opposite_diff
                }
                
                # STEP 10: Trigger the trade (with opposite side - ONLY DIFFERENCE)
                log(f"[AUTO ENTRY REVERSE HTC] 🚀 TRIGGERING TRADE (OPPOSITE SIDE) | {strike_key} | Active Side: {active_side} → Trading: {opposite_side} | Prob: {prob}% | Buy Price: ${opposite_buy_price:.2f} | Ticker: {strike.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY REVERSE HTC] ✅ TRADE SUCCESSFUL | {strike_key} | Trade triggered and sent to trade_manager")
                else:
                    log(f"[AUTO ENTRY REVERSE HTC] ❌ TRADE FAILED | {strike_key} | Failed to trigger trade")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY REVERSE HTC] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY REVERSE HTC] Error checking auto entry conditions: {e}")

def check_auto_entry_conditions_momentum_breakout():
    """Check if auto entry conditions are met and trigger trades for Momentum Breakout strategy
    
    Momentum Breakout activates when momentum spike is detected (same as Reverse HTC).
    When activated, it immediately opens TWO trades:
    - YES trade at strike immediately above the money line
    - NO trade at strike immediately below the money line
    Uses strike_tier to find the correct strikes.
    After entering these two trades, it opens no more trades and holds until expiration.
    """
    global momentum_breakout_trades_entered, momentum_breakout_last_contract
    global auto_entry_indicator_state
    
    try:
        # Get strike table data
        check_spike_alert_conditions()
        
        strike_table_data = get_master_strike_table_data()
        
        # Failsafe: Skip 5pm cycles (daily 5pm cycles are excluded)
        # Check hour_24 directly (17 = 5pm) - most reliable method
        if strike_table_data:
            symbol = (strike_table_data or {}).get("symbol") or MONITOR_SYMBOL or "BTC"
            market_title = (strike_table_data or {}).get("market_title")
            event_ticker = (strike_table_data or {}).get("event_ticker")
            
            # Resolve the hour directly to check for 5pm (hour_24 == 17)
            _, hour_24 = _resolve_event_time(symbol, market_title, event_ticker)
            if hour_24 == 17:  # 5pm in 24-hour format
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ Skipping 5pm cycle (hour_24={hour_24})")
                return
            
            # Also check contract label and market_title as additional failsafe
            current_contract = _LAST_MONITOR_STATE.get("contract")
            contract_to_check = current_contract or market_title or ""
            if contract_to_check and "5pm" in contract_to_check.lower():
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ Skipping 5pm cycle (contract check): {contract_to_check}")
                return
            
            update_monitor_current_state(strike_table_data)
        
        # Get current contract from monitor state (after update)
        current_contract = _LAST_MONITOR_STATE.get("contract")
        
        # Reset trades_entered flag when a new cycle starts (contract changes)
        if current_contract and current_contract != momentum_breakout_last_contract:
            momentum_breakout_trades_entered = False
            if momentum_breakout_last_contract:
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] 🔄 New cycle detected: {momentum_breakout_last_contract} → {current_contract} - resetting entry flag")
            momentum_breakout_last_contract = current_contract
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (REQUIRED for Momentum Breakout to activate)
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
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window + spike alert active
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          spike_alert_active)
        
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
        
        # SPIKE ALERT CHECK - Momentum Breakout REQUIRES spike alert to be active
        if not spike_alert_active:
            return
        
        # If we've already entered trades for this spike activation, do nothing
        if momentum_breakout_trades_entered:
            return
        
        if not strike_table_data:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ No strike table data available")
            return
        
        current_price = strike_table_data.get("current_price")
        strike_tier = strike_table_data.get("strike_tier")
        
        if not current_price or not strike_tier:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Missing current_price or strike_tier")
            return
        
        try:
            strike_tier = int(strike_tier)
        except (ValueError, TypeError):
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Invalid strike_tier: {strike_tier}")
            return
        
        # Find the actual available strikes from the strike table
        # We need the strike immediately above and immediately below the current price
        strikes = strike_table_data.get("strikes", [])
        strike_above_data = None
        strike_below_data = None
        
        # Find the closest strike above current price (>= current_price)
        closest_above = None
        closest_above_distance = float('inf')
        
        # Find the closest strike below current price (<= current_price)
        closest_below = None
        closest_below_distance = float('inf')
        
        for strike in strikes:
            strike_value = strike.get("strike")
            if strike_value is None:
                continue
            
            # Check if this strike is above the current price
            if strike_value >= current_price:
                distance = strike_value - current_price
                if distance < closest_above_distance:
                    closest_above_distance = distance
                    closest_above = strike
            
            # Check if this strike is below the current price
            if strike_value <= current_price:
                distance = current_price - strike_value
                if distance < closest_below_distance:
                    closest_below_distance = distance
                    closest_below = strike
        
        strike_above_data = closest_above
        strike_below_data = closest_below
        
        # Log the found strikes for debugging
        above_strike = strike_above_data.get('strike') if strike_above_data else None
        below_strike = strike_below_data.get('strike') if strike_below_data else None
        below_str = f"${below_strike:,.0f}" if below_strike else "N/A"
        above_str = f"${above_strike:,.0f}" if above_strike else "N/A"
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] 🎯 Current price: ${current_price:,.2f}, Strike tier: ${strike_tier:,}, Found below: {below_str}, Found above: {above_str}")
        
        # Check if we already have active trades on these strikes
        if strike_above_data:
            strike_above_key = f"{strike_above_data.get('strike')}-yes"
            strike_data_for_check = {
                'strike': strike_above_data.get('strike'),
                'side': 'yes',
                'ticker': strike_above_data.get('ticker')
            }
            if is_strike_already_traded(strike_data_for_check):
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ YES trade already exists at strike ${strike_above_data.get('strike'):,.0f}")
                momentum_breakout_trades_entered = True
                return
        
        if strike_below_data:
            strike_below_key = f"{strike_below_data.get('strike')}-no"
            strike_data_for_check = {
                'strike': strike_below_data.get('strike'),
                'side': 'no',
                'ticker': strike_below_data.get('ticker')
            }
            if is_strike_already_traded(strike_data_for_check):
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⏸️ NO trade already exists at strike ${strike_below_data.get('strike'):,.0f}")
                momentum_breakout_trades_entered = True
                return
        
        # Enter the two trades
        trades_entered = 0
        
        # Enter YES trade at strike above
        if strike_above_data:
            yes_ask_dollars = strike_above_data.get('yes_ask_dollars')
            if yes_ask_dollars:
                strike_data = {
                    'strike': f"${int(strike_above_data.get('strike')):,}",
                    'side': 'yes',
                    'ticker': strike_above_data.get('ticker'),
                    'buy_price': float(yes_ask_dollars),
                    'probability': strike_above_data.get('probability'),
                    'diff': strike_above_data.get('yes_diff')
                }
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] 🚀 TRIGGERING YES TRADE | Strike: ${strike_above_data.get('strike'):,.0f} | Buy Price: ${float(yes_ask_dollars):.2f} | Ticker: {strike_above_data.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ✅ YES TRADE SUCCESSFUL | Strike: ${strike_above_data.get('strike'):,.0f}")
                    trades_entered += 1
                else:
                    log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ YES TRADE FAILED | Strike: ${strike_above_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Missing yes_ask_dollars for strike above ${strike_above_data.get('strike'):,.0f}")
        else:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Could not find strike above money line (current price: ${current_price:,.2f})")
        
        # Enter NO trade at strike below
        if strike_below_data:
            no_ask_dollars = strike_below_data.get('no_ask_dollars')
            if no_ask_dollars:
                strike_data = {
                    'strike': f"${int(strike_below_data.get('strike')):,}",
                    'side': 'no',
                    'ticker': strike_below_data.get('ticker'),
                    'buy_price': float(no_ask_dollars),
                    'probability': strike_below_data.get('probability'),
                    'diff': strike_below_data.get('no_diff')
                }
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] 🚀 TRIGGERING NO TRADE | Strike: ${strike_below_data.get('strike'):,.0f} | Buy Price: ${float(no_ask_dollars):.2f} | Ticker: {strike_below_data.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ✅ NO TRADE SUCCESSFUL | Strike: ${strike_below_data.get('strike'):,.0f}")
                    trades_entered += 1
                else:
                    log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ NO TRADE FAILED | Strike: ${strike_below_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Missing no_ask_dollars for strike below ${strike_below_data.get('strike'):,.0f}")
        else:
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ⚠️ Could not find strike below money line (current price: ${current_price:,.2f})")
        
        # Mark trades as entered if at least one trade was successful
        if trades_entered > 0:
            momentum_breakout_trades_entered = True
            # Update last contract to current contract to track which cycle we entered trades for
            if current_contract:
                momentum_breakout_last_contract = current_contract
            log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ✅ Entered {trades_entered} trade(s) for cycle {current_contract} - will hold until expiration")
        
    except Exception as e:
        import traceback
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Error checking auto entry conditions: {e}")
        log(f"[AUTO ENTRY MOMENTUM BREAKOUT] ❌ Traceback: {traceback.format_exc()}")

def check_auto_entry_conditions_momentum_contain():
    """Check if auto entry conditions are met and trigger trades for Momentum Contain strategy
    
    Momentum Contain activates when momentum spike is detected (same as Momentum Breakout).
    When activated, it immediately opens TWO trades with FLIPPED SIDES compared to Momentum Breakout:
    - NO trade at strike immediately above the money line (contrarian to Breakout)
    - YES trade at strike immediately below the money line (contrarian to Breakout)
    Uses strike_tier to find the correct strikes.
    After entering these two trades, it opens no more trades and holds until expiration.
    """
    global momentum_contain_trades_entered, momentum_contain_last_contract
    global auto_entry_indicator_state
    
    try:
        # Get strike table data
        check_spike_alert_conditions()
        
        strike_table_data = get_master_strike_table_data()
        
        # Failsafe: Skip 5pm cycles (daily 5pm cycles are excluded)
        # Check hour_24 directly (17 = 5pm) - most reliable method
        if strike_table_data:
            symbol = (strike_table_data or {}).get("symbol") or MONITOR_SYMBOL or "BTC"
            market_title = (strike_table_data or {}).get("market_title")
            event_ticker = (strike_table_data or {}).get("event_ticker")
            
            # Resolve the hour directly to check for 5pm (hour_24 == 17)
            _, hour_24 = _resolve_event_time(symbol, market_title, event_ticker)
            if hour_24 == 17:  # 5pm in 24-hour format
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Skipping 5pm cycle (hour_24={hour_24})")
                return
            
            # Also check contract label and market_title as additional failsafe
            current_contract = _LAST_MONITOR_STATE.get("contract")
            contract_to_check = current_contract or market_title or ""
            if contract_to_check and "5pm" in contract_to_check.lower():
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Skipping 5pm cycle (contract check): {contract_to_check}")
                return
            
            update_monitor_current_state(strike_table_data)
        
        # Get current contract from monitor state (after update)
        current_contract = _LAST_MONITOR_STATE.get("contract")
        
        # Reset trades_entered flag when a new cycle starts (contract changes)
        if current_contract and current_contract != momentum_contain_last_contract:
            momentum_contain_trades_entered = False
            if momentum_contain_last_contract:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] 🔄 New cycle detected: {momentum_contain_last_contract} → {current_contract} - resetting entry flag")
            momentum_contain_last_contract = current_contract
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        # Check if spike alert is active (REQUIRED for Momentum Contain to activate)
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
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        required_settings = ["min_time", "max_time"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Determine if scanning is actually active
        # Scanning is active if: auto_trade enabled + service healthy + TTC in window + spike alert active
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          spike_alert_active)
        
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
        
        # SPIKE ALERT CHECK - Momentum Contain REQUIRES spike alert to be active
        if not spike_alert_active:
            return
        
        # COOLDOWN TIMER CHECK - Validate cooldown_timer is within activation window
        # This prevents entry when cooldown_timer is outside min/max parameters
        min_cooldown_timer = settings.get("min_cooldown_timer")
        max_cooldown_timer = settings.get("max_cooldown_timer")
        
        # If either min or max is set, check cooldown_timer is within window
        if min_cooldown_timer is not None or max_cooldown_timer is not None:
            # Get cooldown_timer from database
            cooldown_timer = None
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
                    cooldown_timer = result[0] if result and result[0] is not None else None
                conn.close()
            except Exception as e:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error getting cooldown timer: {e}")
            
            # If cooldown_timer is NULL, cannot determine - skip entry
            if cooldown_timer is None:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ cooldown_timer is NULL - skipping entry")
                return
            
            # Check if cooldown_timer is within the activation window
            # If min is set, cooldown_timer must be >= min (not too close to spike)
            if min_cooldown_timer is not None and cooldown_timer < min_cooldown_timer:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ cooldown_timer ({cooldown_timer}) < min_cooldown_timer ({min_cooldown_timer}) - too close to momentum spike - skipping entry")
                return
            
            # If max is set, cooldown_timer must be <= max (not too far after spike)
            if max_cooldown_timer is not None and cooldown_timer > max_cooldown_timer:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ cooldown_timer ({cooldown_timer}) > max_cooldown_timer ({max_cooldown_timer}) - too far after spike regime has ended - skipping entry")
                return
        
        # If we've already entered trades for this spike activation, do nothing
        if momentum_contain_trades_entered:
            return
        
        if not strike_table_data:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ No strike table data available")
            return
        
        current_price = strike_table_data.get("current_price")
        strike_tier = strike_table_data.get("strike_tier")
        
        if not current_price or not strike_tier:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing current_price or strike_tier")
            return
        
        try:
            strike_tier = int(strike_tier)
        except (ValueError, TypeError):
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Invalid strike_tier: {strike_tier}")
            return
        
        # Find the actual available strikes from the strike table
        # We need the strike immediately above and immediately below the current price
        strikes = strike_table_data.get("strikes", [])
        strike_above_data = None
        strike_below_data = None
        
        # Find the closest strike above current price (>= current_price)
        closest_above = None
        closest_above_distance = float('inf')
        
        # Find the closest strike below current price (<= current_price)
        closest_below = None
        closest_below_distance = float('inf')
        
        for strike in strikes:
            strike_value = strike.get("strike")
            if strike_value is None:
                continue
            
            # Check if this strike is above the current price
            if strike_value >= current_price:
                distance = strike_value - current_price
                if distance < closest_above_distance:
                    closest_above_distance = distance
                    closest_above = strike
            
            # Check if this strike is below the current price
            if strike_value <= current_price:
                distance = current_price - strike_value
                if distance < closest_below_distance:
                    closest_below_distance = distance
                    closest_below = strike
        
        strike_above_data = closest_above
        strike_below_data = closest_below
        
        # Log the found strikes for debugging
        above_strike = strike_above_data.get('strike') if strike_above_data else None
        below_strike = strike_below_data.get('strike') if strike_below_data else None
        below_str = f"${below_strike:,.0f}" if below_strike else "N/A"
        above_str = f"${above_strike:,.0f}" if above_strike else "N/A"
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] 🎯 Current price: ${current_price:,.2f}, Strike tier: ${strike_tier:,}, Found below: {below_str}, Found above: {above_str}")
        
        # Check if we already have active trades on these strikes (FLIPPED SIDES from Breakout)
        # Momentum Contain: NO at strike above, YES at strike below
        if strike_above_data:
            strike_data_for_check = {
                'strike': strike_above_data.get('strike'),
                'side': 'no',  # FLIPPED: Breakout uses 'yes' here
                'ticker': strike_above_data.get('ticker')
            }
            if is_strike_already_traded(strike_data_for_check):
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ NO trade already exists at strike ${strike_above_data.get('strike'):,.0f}")
                momentum_contain_trades_entered = True
                return
        
        if strike_below_data:
            strike_data_for_check = {
                'strike': strike_below_data.get('strike'),
                'side': 'yes',  # FLIPPED: Breakout uses 'no' here
                'ticker': strike_below_data.get('ticker')
            }
            if is_strike_already_traded(strike_data_for_check):
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ YES trade already exists at strike ${strike_below_data.get('strike'):,.0f}")
                momentum_contain_trades_entered = True
                return
        
        # VALIDATION CHECKS: Volume, Momentum, and Ask Price checks before entering trades
        # Get required settings
        min_volume = settings.get("min_volume", 1000)
        min_ask = settings.get("min_ask", 0.0000)
        max_ask = settings.get("max_ask", 0.9800)
        cooldown_threshold = settings.get("spike_alert_cooldown_threshold")
        
        # VOLUME CHECK: Ensure both strikes meet minimum volume requirement
        if not strike_above_data or not strike_below_data:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Missing strike data - cannot perform volume check")
            return
        
        volume_above = strike_above_data.get('volume', 0) or 0
        volume_below = strike_below_data.get('volume', 0) or 0
        
        if volume_above < min_volume:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike above volume ({volume_above}) below minimum ({min_volume}) - skipping entry")
            return
        
        if volume_below < min_volume:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike below volume ({volume_below}) below minimum ({min_volume}) - skipping entry")
            return
        
        # MOMENTUM CHECK: Both 30s average and current momentum_percentile must be below cooldown threshold
        current_symbol = get_current_monitor_symbol()
        momentum_30s_avg = get_momentum_30s_avg(current_symbol)
        if momentum_30s_avg is None:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Cannot determine momentum_30s_avg - skipping entry")
            return
        
        momentum_percentile = get_momentum_percentile(current_symbol)
        if momentum_percentile is None:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Cannot determine momentum_percentile - skipping entry")
            return
        
        if cooldown_threshold is None:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing spike_alert_cooldown_threshold setting - skipping entry")
            return
        
        abs_momentum_30s = abs(momentum_30s_avg)
        abs_momentum_percentile = abs(momentum_percentile)
        
        # Both must be below threshold to allow entry
        if abs_momentum_30s >= cooldown_threshold:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ 30s average momentum ({momentum_30s_avg:.2f}, abs: {abs_momentum_30s:.2f}) still above cooldown threshold ({cooldown_threshold:.2f}) - skipping entry")
            return
        
        if abs_momentum_percentile >= cooldown_threshold:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Current momentum_percentile ({momentum_percentile:.2f}, abs: {abs_momentum_percentile:.2f}) still above cooldown threshold ({cooldown_threshold:.2f}) - skipping entry")
            return
        
        # ASK PRICE CHECK: Ensure both legs have ask prices within min_ask and max_ask range
        no_ask_dollars_above = strike_above_data.get('no_ask_dollars')
        yes_ask_dollars_below = strike_below_data.get('yes_ask_dollars')
        
        if not no_ask_dollars_above:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Missing no_ask_dollars for strike above - skipping entry")
            return
        
        if not yes_ask_dollars_below:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Missing yes_ask_dollars for strike below - skipping entry")
            return
        
        try:
            no_ask_price_above = float(no_ask_dollars_above)
            yes_ask_price_below = float(yes_ask_dollars_below)
        except (ValueError, TypeError):
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Invalid ask price data - skipping entry")
            return
        
        # Check NO ask price at strike above
        if no_ask_price_above < min_ask or no_ask_price_above > max_ask:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike above NO ask (${no_ask_price_above:.4f}) outside range [{min_ask:.4f}, {max_ask:.4f}] - skipping entry")
            return
        
        # Check YES ask price at strike below
        if yes_ask_price_below < min_ask or yes_ask_price_below > max_ask:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⏸️ Strike below YES ask (${yes_ask_price_below:.4f}) outside range [{min_ask:.4f}, {max_ask:.4f}] - skipping entry")
            return
        
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ All checks passed | Above: vol={volume_above}>={min_volume}, NO ask=${no_ask_price_above:.4f} in [{min_ask:.4f}, {max_ask:.4f}] | Below: vol={volume_below}>={min_volume}, YES ask=${yes_ask_price_below:.4f} in [{min_ask:.4f}, {max_ask:.4f}] | Momentum 30s: {momentum_30s_avg:.2f} (abs: {abs_momentum_30s:.2f}) < {cooldown_threshold:.2f}, Momentum %ile: {momentum_percentile:.2f} (abs: {abs_momentum_percentile:.2f}) < {cooldown_threshold:.2f}")
        
        # Enter the two trades (FLIPPED SIDES from Momentum Breakout)
        trades_entered = 0
        
        # Enter NO trade at strike above (FLIPPED: Breakout enters YES here)
        if strike_above_data:
            no_ask_dollars = strike_above_data.get('no_ask_dollars')
            if no_ask_dollars:
                strike_data = {
                    'strike': f"${int(strike_above_data.get('strike')):,}",
                    'side': 'no',  # FLIPPED: Breakout uses 'yes' here
                    'ticker': strike_above_data.get('ticker'),
                    'buy_price': float(no_ask_dollars),
                    'probability': strike_above_data.get('probability'),
                    'diff': strike_above_data.get('no_diff')
                }
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] 🚀 TRIGGERING NO TRADE | Strike: ${strike_above_data.get('strike'):,.0f} | Buy Price: ${float(no_ask_dollars):.2f} | Ticker: {strike_above_data.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ NO TRADE SUCCESSFUL | Strike: ${strike_above_data.get('strike'):,.0f}")
                    trades_entered += 1
                else:
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ NO TRADE FAILED | Strike: ${strike_above_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing no_ask_dollars for strike above ${strike_above_data.get('strike'):,.0f}")
        else:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Could not find strike above money line (current price: ${current_price:,.2f})")
        
        # Enter YES trade at strike below (FLIPPED: Breakout enters NO here)
        if strike_below_data:
            yes_ask_dollars = strike_below_data.get('yes_ask_dollars')
            if yes_ask_dollars:
                strike_data = {
                    'strike': f"${int(strike_below_data.get('strike')):,}",
                    'side': 'yes',  # FLIPPED: Breakout uses 'no' here
                    'ticker': strike_below_data.get('ticker'),
                    'buy_price': float(yes_ask_dollars),
                    'probability': strike_below_data.get('probability'),
                    'diff': strike_below_data.get('yes_diff')
                }
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] 🚀 TRIGGERING YES TRADE | Strike: ${strike_below_data.get('strike'):,.0f} | Buy Price: ${float(yes_ask_dollars):.2f} | Ticker: {strike_below_data.get('ticker')}")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ YES TRADE SUCCESSFUL | Strike: ${strike_below_data.get('strike'):,.0f}")
                    trades_entered += 1
                else:
                    log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ YES TRADE FAILED | Strike: ${strike_below_data.get('strike'):,.0f}")
            else:
                log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Missing yes_ask_dollars for strike below ${strike_below_data.get('strike'):,.0f}")
        else:
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ⚠️ Could not find strike below money line (current price: ${current_price:,.2f})")
        
        # Mark trades as entered if at least one trade was successful
        if trades_entered > 0:
            momentum_contain_trades_entered = True
            # Update last contract to current contract to track which cycle we entered trades for
            if current_contract:
                momentum_contain_last_contract = current_contract
            log(f"[AUTO ENTRY MOMENTUM CONTAIN] ✅ Entered {trades_entered} trade(s) for cycle {current_contract} - will hold until expiration")
        
    except Exception as e:
        import traceback
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Error checking auto entry conditions: {e}")
        log(f"[AUTO ENTRY MOMENTUM CONTAIN] ❌ Traceback: {traceback.format_exc()}")

def check_auto_entry_conditions_momentum_scalp():
    """Check if auto entry conditions are met and trigger trades for Momentum Scalp strategy"""
    global auto_entry_indicator_state
    
    try:
        # Get strike table data
        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not auto_trade_enabled:
            auto_entry_indicator_state.update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": 0,
                "last_updated": datetime.now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_volume", "momentum_scalp_entry_threshold", "min_ask", "max_ask"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MS] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_volume = settings.get("min_volume", 1000)
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        min_ask = settings.get("min_ask", 0.0000)
        max_ask = settings.get("max_ask", 0.9800)
        max_price_spread = settings.get("max_price_spread", 0.0300)
        
        if momentum_threshold is None:
            log(f"[AUTO ENTRY MS] ❌ Missing momentum_scalp_entry_threshold")
            return
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Get current momentum
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            # Update indicator state
            auto_entry_indicator_state.update({
                "enabled": True,
                "ttc_within_window": ttc_within_window,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": current_ttc,
                "min_time": min_time,
                "max_time": max_time,
                "last_updated": datetime.now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Determine momentum direction
        if current_momentum >= momentum_threshold:
            momentum_direction = "UP"
        elif current_momentum <= -momentum_threshold:
            momentum_direction = "DOWN"
        else:
            momentum_direction = None
        
        # Determine if scanning is active (TTC in window AND momentum spike detected)
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          momentum_direction is not None)
        
        # Update indicator state for frontend
        auto_entry_indicator_state.update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": False,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": datetime.now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        # Must be within time window AND have momentum spike to proceed
        if not ttc_within_window or momentum_direction is None:
            return
        
        if not strike_table_data or "strikes" not in strike_table_data:
            return
        
        # Filter strikes based on momentum direction
        # UP momentum -> look at active_side='yes'
        # DOWN momentum -> look at active_side='no'
        eligible_strikes = []
        for strike in strike_table_data["strikes"]:
            active_side = strike.get('active_side')
            if not active_side:
                continue
            
            # Filter by momentum direction
            if momentum_direction == "UP" and active_side != 'yes':
                continue
            if momentum_direction == "DOWN" and active_side != 'no':
                continue
            
            # Filter by volume
            volume = strike.get('volume', 0)
            if volume is None or volume < min_volume:
                continue
            
            # Filter by ask price window (min_ask <= ask_dollars <= max_ask)
            # For YES side: check yes_ask_dollars
            # For NO side: check no_ask_dollars
            if active_side == 'yes':
                ask_dollars = strike.get('yes_ask_dollars')
            elif active_side == 'no':
                ask_dollars = strike.get('no_ask_dollars')
            else:
                continue
            
            if ask_dollars is None:
                continue
            
            # Convert to float and check against min/max ask window
            try:
                ask_price = float(ask_dollars)
                if ask_price < min_ask or ask_price > max_ask:
                    continue
            except (ValueError, TypeError):
                continue
            
            # Filter by price spread (must be <= max_price_spread)
            if active_side == 'yes':
                price_spread = strike.get('yes_price_spread')
            elif active_side == 'no':
                price_spread = strike.get('no_price_spread')
            else:
                continue
            
            if price_spread is None:
                continue
            
            try:
                spread_value = float(price_spread)
                if spread_value > max_price_spread:
                    continue
            except (ValueError, TypeError):
                continue
            
            eligible_strikes.append(strike)
        
        # Sort by probability (highest to lowest)
        eligible_strikes.sort(key=lambda x: x.get('probability', 0), reverse=True)
        
        # Process eligible strikes
        processed_strikes = set()
        for strike in eligible_strikes:
            try:
                active_side = strike.get('active_side')
                strike_key = f"{strike.get('strike')}-{active_side}"
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                processed_strikes.add(strike_key)
                
                # Check cooldown
                if not can_trade_strike(strike_key):
                    continue
                
                # Check if already traded
                strike_data_for_check = {
                    'strike': strike.get('strike'),
                    'side': active_side
                }
                if is_strike_already_traded(strike_data_for_check):
                    continue
                
                # Prepare strike data
                prob = strike.get('probability')
                if active_side == 'yes':
                    side = 'yes'
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        continue
                    buy_price = float(yes_ask_dollars)
                elif active_side == 'no':
                    side = 'no'
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        continue
                    buy_price = float(no_ask_dollars)
                else:
                    continue
                
                strike_data = {
                    'strike': f"${int(strike.get('strike')):,}",
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob
                }
                
                # Check if strike is already traded
                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY MS] ⏸️ Skipping {strike_key} - already has open/pending trade")
                    continue
                
                # Trigger the trade
                log(f"[AUTO ENTRY MS] 🚀 TRIGGERING TRADE | {strike_key} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Momentum: {current_momentum:.2f} ({momentum_direction})")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MS] ✅ TRADE SUCCESSFUL | {strike_key}")
                else:
                    log(f"[AUTO ENTRY MS] ❌ TRADE FAILED | {strike_key}")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY MS] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY MS] Error checking auto entry conditions: {e}")

def check_auto_entry_conditions_momentum_reversal():
    """Check if auto entry conditions are met and trigger trades for Momentum Reversal strategy"""
    global auto_entry_indicator_state
    
    try:
        # Get strike table data
        strike_table_data = get_master_strike_table_data()
        if strike_table_data:
            update_monitor_current_state(strike_table_data)
        
        # Check if AUTO TRADE is enabled for this monitor
        auto_trade_enabled = is_auto_trade_enabled()
        
        # Check if service is healthy (monitoring thread is running)
        service_healthy = monitoring_thread is not None and monitoring_thread.is_alive()
        
        if not auto_trade_enabled:
            auto_entry_indicator_state.update({
                "enabled": False,
                "ttc_within_window": False,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": 0,
                "last_updated": datetime.now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Get auto entry settings
        settings = get_auto_entry_settings()
        
        # Check if all required settings exist
        required_settings = ["min_time", "max_time", "min_volume", "momentum_scalp_entry_threshold", "min_ask", "max_ask"]
        missing_settings = [setting for setting in required_settings if setting not in settings]
        if missing_settings:
            log(f"[AUTO ENTRY MR] ❌ Missing required settings: {missing_settings}")
            return
        
        min_time = settings["min_time"]
        max_time = settings["max_time"]
        min_volume = settings.get("min_volume", 1000)
        momentum_threshold = settings.get("momentum_scalp_entry_threshold")
        min_ask = settings.get("min_ask", 0.0000)
        max_ask = settings.get("max_ask", 0.9800)
        max_price_spread = settings.get("max_price_spread", 0.0300)
        
        if momentum_threshold is None:
            log(f"[AUTO ENTRY MR] ❌ Missing momentum_scalp_entry_threshold")
            return
        
        # Get current TTC
        current_ttc = get_current_ttc()
        
        # Check if TTC is within the time window
        ttc_within_window = min_time <= current_ttc <= max_time
        
        # Get current momentum
        current_symbol = get_current_monitor_symbol()
        current_momentum = get_current_momentum(current_symbol)
        
        if current_momentum is None:
            # Update indicator state
            auto_entry_indicator_state.update({
                "enabled": True,
                "ttc_within_window": ttc_within_window,
                "scanning_active": False,
                "service_healthy": service_healthy,
                "spike_alert_active": False,
                "current_ttc": current_ttc,
                "min_time": min_time,
                "max_time": max_time,
                "last_updated": datetime.now().isoformat()
            })
            broadcast_auto_entry_indicator_change()
            return
        
        # Determine momentum direction
        if current_momentum >= momentum_threshold:
            momentum_direction = "UP"
        elif current_momentum <= -momentum_threshold:
            momentum_direction = "DOWN"
        else:
            momentum_direction = None
        
        # Determine if scanning is active (TTC in window AND momentum spike detected)
        scanning_active = (auto_trade_enabled and 
                          service_healthy and 
                          ttc_within_window and
                          momentum_direction is not None)
        
        # Update indicator state for frontend
        auto_entry_indicator_state.update({
            "enabled": True,
            "ttc_within_window": ttc_within_window,
            "scanning_active": scanning_active,
            "service_healthy": service_healthy,
            "spike_alert_active": False,
            "current_ttc": current_ttc,
            "min_time": min_time,
            "max_time": max_time,
            "last_updated": datetime.now().isoformat()
        })
        
        # Broadcast indicator state change
        broadcast_auto_entry_indicator_change()
        
        # Must be within time window AND have momentum spike to proceed
        if not ttc_within_window or momentum_direction is None:
            return
        
        if not strike_table_data or "strikes" not in strike_table_data:
            return
        
        # Filter strikes based on momentum direction
        # UP momentum -> look at active_side='yes'
        # DOWN momentum -> look at active_side='no'
        eligible_strikes = []
        for strike in strike_table_data["strikes"]:
            active_side = strike.get('active_side')
            if not active_side:
                continue
            
            # Filter by momentum direction
            if momentum_direction == "UP" and active_side != 'yes':
                continue
            if momentum_direction == "DOWN" and active_side != 'no':
                continue
            
            # Filter by volume
            volume = strike.get('volume', 0)
            if volume is None or volume < min_volume:
                continue
            
            # Filter by ask price window (min_ask <= ask_dollars <= max_ask)
            # For YES side: check yes_ask_dollars
            # For NO side: check no_ask_dollars
            if active_side == 'yes':
                ask_dollars = strike.get('yes_ask_dollars')
            elif active_side == 'no':
                ask_dollars = strike.get('no_ask_dollars')
            else:
                continue
            
            if ask_dollars is None:
                continue
            
            # Convert to float and check against min/max ask window
            try:
                ask_price = float(ask_dollars)
                if ask_price < min_ask or ask_price > max_ask:
                    continue
            except (ValueError, TypeError):
                continue
            
            # Filter by price spread (must be <= max_price_spread)
            if active_side == 'yes':
                price_spread = strike.get('yes_price_spread')
            elif active_side == 'no':
                price_spread = strike.get('no_price_spread')
            else:
                continue
            
            if price_spread is None:
                continue
            
            try:
                spread_value = float(price_spread)
                if spread_value > max_price_spread:
                    continue
            except (ValueError, TypeError):
                continue
            
            eligible_strikes.append(strike)
        
        # Sort by probability (highest to lowest)
        eligible_strikes.sort(key=lambda x: x.get('probability', 0), reverse=True)
        
        # Process eligible strikes
        processed_strikes = set()
        for strike in eligible_strikes:
            try:
                active_side = strike.get('active_side')
                strike_key = f"{strike.get('strike')}-{active_side}"
                
                # Prevent duplicate processing
                if strike_key in processed_strikes:
                    continue
                processed_strikes.add(strike_key)
                
                # Check cooldown
                if not can_trade_strike(strike_key):
                    continue
                
                # Check if already traded
                strike_data_for_check = {
                    'strike': strike.get('strike'),
                    'side': active_side
                }
                if is_strike_already_traded(strike_data_for_check):
                    continue
                
                # Prepare strike data - MOMENTUM REVERSAL: SWAP THE SIDE
                prob = strike.get('probability')
                if active_side == 'yes':
                    # Found YES ticker -> submit NO order (REVERSAL)
                    side = 'no'
                    no_ask_dollars = strike.get('no_ask_dollars')
                    if not no_ask_dollars:
                        continue
                    buy_price = float(no_ask_dollars)
                elif active_side == 'no':
                    # Found NO ticker -> submit YES order (REVERSAL)
                    side = 'yes'
                    yes_ask_dollars = strike.get('yes_ask_dollars')
                    if not yes_ask_dollars:
                        continue
                    buy_price = float(yes_ask_dollars)
                else:
                    continue
                
                strike_data = {
                    'strike': f"${int(strike.get('strike')):,}",
                    'side': side,
                    'ticker': strike.get('ticker'),
                    'buy_price': buy_price,
                    'probability': prob
                }
                
                # Check if strike is already traded (check with swapped side)
                if is_strike_already_traded(strike_data):
                    log(f"[AUTO ENTRY MR] ⏸️ Skipping {strike_key} - already has open/pending trade")
                    continue
                
                # Trigger the trade
                log(f"[AUTO ENTRY MR] 🚀 TRIGGERING REVERSAL TRADE | {strike_key} -> {side.upper()} | Prob: {prob}% | Buy Price: ${buy_price:.2f} | Momentum: {current_momentum:.2f} ({momentum_direction})")
                if trigger_auto_entry_trade(strike_data):
                    log(f"[AUTO ENTRY MR] ✅ TRADE SUCCESSFUL | {strike_key} -> {side.upper()}")
                else:
                    log(f"[AUTO ENTRY MR] ❌ TRADE FAILED | {strike_key} -> {side.upper()}")
                    # Remove from cooldown if trade failed
                    if strike_key in last_trade_times:
                        del last_trade_times[strike_key]
                
            except Exception as e:
                log(f"[AUTO ENTRY MR] Error processing strike {strike.get('strike')}: {e}")
                
    except Exception as e:
        log(f"[AUTO ENTRY MR] Error checking auto entry conditions: {e}")

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
                import traceback
                log(f"❌ Error in monitoring worker: {e}")
                log(f"❌ Traceback: {traceback.format_exc()}")
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