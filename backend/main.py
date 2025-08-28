"""
MAIN APPLICATION - UNIVERSAL CENTRALIZED PORT SYSTEM
Uses the single centralized port configuration system.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import json
import asyncio
import time
from datetime import datetime, timedelta
import pytz
import requests
import sqlite3
import psycopg2
from typing import List, Optional, Dict
import fcntl
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import hashlib
import secrets
import hmac

# Import the universal centralized port system
import sys
import os

# Add the project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from backend.util.paths import get_project_root

# Use relative imports to avoid ModuleNotFoundError
from backend.core.port_config import get_port, get_port_info

# Import unified configuration system for database connections
from backend.core.unified_config import UnifiedConfigManager
unified_config = UnifiedConfigManager()

# Get port from centralized system
MAIN_APP_PORT = get_port("main_app")
ACTIVE_TRADE_SUPERVISOR_PORT = get_port("active_trade_supervisor")
print(f"[MAIN] 🚀 Using centralized port: {MAIN_APP_PORT}")
print(f"[MAIN] 🚀 Active Trade Supervisor port: {ACTIVE_TRADE_SUPERVISOR_PORT}")

# Import centralized path utilities
from backend.util.paths import get_data_dir, get_trade_history_dir, get_accounts_data_dir
from backend.account_mode import get_account_mode

# Global set of connected websocket clients for preferences
connected_clients = set()

# Global set of connected websocket clients for database changes
db_change_clients = set()

# Legacy preference path removed - all data now in PostgreSQL

# Global preferences cache
_preferences_cache = None
_cache_timestamp = 0
CACHE_TTL = 1.0  # 1 second cache TTL

# PostgreSQL helper functions for auto trade settings
def update_auto_trade_settings_postgresql(**kwargs):
    """Update auto trade settings in PostgreSQL using UPDATE"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # First, ensure we only have one row
            cursor.execute("DELETE FROM users.auto_trade_settings_0001 WHERE id > 1")
            
            # Check if row exists
            cursor.execute("SELECT COUNT(*) FROM users.auto_trade_settings_0001 WHERE id = 1")
            row_exists = cursor.fetchone()[0] > 0
            
            if row_exists:
                # UPDATE existing row
                set_clauses = []
                values = []
                for key, value in kwargs.items():
                    set_clauses.append(f"{key} = %s")
                    values.append(value)
                
                if set_clauses:
                    query = f"UPDATE users.auto_trade_settings_0001 SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP WHERE id = 1"
                    cursor.execute(query, values)
            else:
                # INSERT new row with defaults
                columns = list(kwargs.keys())
                values = list(kwargs.values())
                placeholders = ['%s'] * len(values)
                
                # Add default values for missing columns
                default_columns = ['id', 'auto_entry', 'auto_stop', 'min_probability', 'min_differential', 'min_time', 'max_time', 'allow_re_entry', 'spike_alert_enabled', 'spike_alert_momentum_threshold', 'spike_alert_cooldown_threshold', 'spike_alert_cooldown_minutes', 'current_probability', 'min_ttc_seconds', 'momentum_spike_enabled', 'momentum_spike_threshold', 'auto_entry_status', 'user_id', 'cooldown_timer']
                default_values = [1, False, False, 95, 0.25, 120, 900, False, True, 36, 30, 15, 40, 60, True, 36, 'disabled', '0001', 0]
                
                # Merge provided values with defaults
                for col, val in zip(columns, values):
                    if col in default_columns:
                        idx = default_columns.index(col)
                        default_values[idx] = val
                
                query = f"INSERT INTO users.auto_trade_settings_0001 ({', '.join(default_columns)}) VALUES ({', '.join(['%s'] * len(default_values))})"
                cursor.execute(query, default_values)
            
            conn.commit()
            print(f"[PostgreSQL] Updated auto trade settings: {kwargs}")
        
        conn.close()
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to update auto trade settings: {e}")

def get_auto_trade_settings_postgresql():
    """Get auto trade settings from PostgreSQL"""
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
                SELECT auto_entry, auto_stop, 
                       min_probability, min_differential, min_time, max_time, allow_re_entry,
                       spike_alert_enabled, spike_alert_momentum_threshold, spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                       current_probability, min_ttc_seconds, momentum_spike_enabled, momentum_spike_threshold
                FROM users.auto_trade_settings_0001 WHERE id = 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    "auto_entry": result[0],
                    "auto_stop": result[1],
                    "min_probability": result[2],
                    "min_differential": float(result[3]) if result[3] else 0.25,
                    "min_time": result[4],
                    "max_time": result[5],
                    "allow_re_entry": result[6],
                    "spike_alert_enabled": result[7],
                    "spike_alert_momentum_threshold": result[8],
                    "spike_alert_cooldown_threshold": result[9],
                    "spike_alert_cooldown_minutes": result[10],
                    "current_probability": result[11],
                    "min_ttc_seconds": result[12],
                    "momentum_spike_enabled": result[13],
                    "momentum_spike_threshold": result[14]
                }
            else:
                return None
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to get auto trade settings: {e}")
        return None

def get_auto_stop_settings_postgresql():
    """Get auto stop settings from PostgreSQL"""
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
                SELECT current_probability, min_ttc_seconds, momentum_spike_enabled, momentum_spike_threshold,
                       verification_period_enabled, verification_period_seconds
                FROM users.auto_trade_settings_0001 WHERE id = 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    "current_probability": result[0],
                    "min_ttc_seconds": result[1],
                    "momentum_spike_enabled": result[2],
                    "momentum_spike_threshold": result[3],
                    "verification_period_enabled": result[4],
                    "verification_period_seconds": result[5]
                }
            else:
                return {
                    "current_probability": 40,
                    "min_ttc_seconds": 60,
                    "momentum_spike_enabled": True,
                    "momentum_spike_threshold": 36,
                    "verification_period_enabled": False,
                    "verification_period_seconds": 15
                }
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to get auto stop settings: {e}")
        return {
            "current_probability": 40,
            "min_ttc_seconds": 60,
            "momentum_spike_enabled": True,
            "momentum_spike_threshold": 36,
            "verification_period_enabled": False,
            "verification_period_seconds": 15
        }

# PostgreSQL helper functions for trade preferences
def update_trade_preferences_postgresql(**kwargs):
    """Update trade preferences in PostgreSQL using UPSERT"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # First, ensure we only have one row
            cursor.execute("DELETE FROM users.trade_preferences_0001 WHERE id > 1")
            
            # Build dynamic UPSERT query
            columns = list(kwargs.keys())
            values = list(kwargs.values())
            placeholders = ['%s'] * len(values)
            
            # Add updated_at to the columns
            columns.append('updated_at')
            placeholders.append('CURRENT_TIMESTAMP')
            
            query = f"""
                INSERT INTO users.trade_preferences_0001 (id, {', '.join(columns)})
                VALUES (1, {', '.join(placeholders)})
                ON CONFLICT (id) DO UPDATE SET
                {', '.join([f"{col} = EXCLUDED.{col}" for col in columns])}
            """
            
            cursor.execute(query, values)
            conn.commit()
            print(f"[PostgreSQL] Updated trade preferences: {kwargs}")
        
        conn.close()
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to update trade preferences: {e}")

def get_trade_preferences_postgresql():
    """Get trade preferences from PostgreSQL"""
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
                SELECT trade_strategy, position_size, multiplier
                FROM users.trade_preferences_0001 WHERE id = 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    "trade_strategy": result[0],
                    "position_size": result[1],
                    "multiplier": result[2]
                }
            else:
                return {
                    "trade_strategy": "Hourly HTC",
                    "position_size": 1,
                    "multiplier": 1
                }
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to get trade preferences: {e}")
        return {
            "trade_strategy": "Hourly HTC",
            "position_size": 1,
            "multiplier": 1
        }

def get_all_preferences_postgresql():
    """Get all preferences from PostgreSQL (combines auto_trade_settings and trade_preferences)"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # Get auto trade settings
            cursor.execute("""
                SELECT auto_entry, auto_stop
                FROM users.auto_trade_settings_0001 WHERE id = 1
            """)
            auto_settings = cursor.fetchone()
            
            # Get trade preferences
            cursor.execute("""
                SELECT trade_strategy, position_size, multiplier
                FROM users.trade_preferences_0001 WHERE id = 1
            """)
            trade_prefs = cursor.fetchone()
            
            conn.close()
            
            # Combine the results
            preferences = {
                "auto_stop": auto_settings[1] if auto_settings else True,  # auto_stop is second column
                "auto_entry": auto_settings[0] if auto_settings else False,  # auto_entry is first column
                "position_size": trade_prefs[1] if trade_prefs else 1,
                "multiplier": trade_prefs[2] if trade_prefs else 1
            }
            
            return preferences
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to get all preferences: {e}")
        return {
            "auto_stop": True,
            "auto_entry": False,
            "diff_mode": False,
            "position_size": 1,
            "multiplier": 1
        }

def get_trade_history_preferences_postgresql():
    """Get trade history preferences from PostgreSQL"""
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
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp
                FROM users.trade_history_preferences_0001 WHERE id = 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    "date_filter": result[0],
                    "start_date": result[1],
                    "end_date": result[2],
                    "win_filter": result[3],
                    "loss_filter": result[4],
                    "contract_9am": result[5],
                    "contract_10am": result[6],
                    "contract_11am": result[7],
                    "contract_12am": result[8],
                    "contract_1pm": result[9],
                    "contract_2pm": result[10],
                    "contract_3pm": result[11],
                    "contract_4pm": result[12],
                    "contract_5pm": result[13],
                    "contract_6pm": result[14],
                    "contract_7pm": result[15],
                    "contract_8pm": result[16],
                    "contract_9pm": result[17],
                    "contract_10pm": result[18],
                    "contract_11pm": result[19],
                    "symbol_btc": result[20],
                    "symbol_eth": result[21],
                    "symbol_spy": result[22],
                    "symbol_ndx": result[23],
                    "symbol_usd_eur": result[24],
                    "strategy_hourly_htc": result[25],
                    "strategy_momentum_scalp": result[26],
                    "strategy_test": result[27],
                    "analysis_interval": result[28],
                    "sort_key": result[29],
                    "sort_asc": result[30],
                    "page_size": result[31],
                    "last_search_timestamp": result[32]
                }
            else:
                return {
                    "date_filter": "TODAY",
                    "start_date": None,
                    "end_date": None,
                    "win_filter": True,
                    "loss_filter": True,
                    "contract_9am": True,
                    "contract_10am": True,
                    "contract_11am": True,
                    "contract_12am": True,
                    "contract_1pm": True,
                    "contract_2pm": True,
                    "contract_3pm": True,
                    "contract_4pm": True,
                    "contract_5pm": True,
                    "contract_6pm": True,
                    "contract_7pm": True,
                    "contract_8pm": True,
                    "contract_9pm": True,
                    "contract_10pm": True,
                    "contract_11pm": True,
                    "symbol_btc": True,
                    "symbol_eth": True,
                    "symbol_spy": True,
                    "symbol_ndx": True,
                    "symbol_usd_eur": True,
                    "strategy_hourly_htc": True,
                    "strategy_momentum_scalp": True,
                    "strategy_test": True,
                    "analysis_interval": "daily",
                    "sort_key": None,
                    "sort_asc": True,
                    "page_size": 50,
                    "last_search_timestamp": int(time.time())
                }
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to get trade history preferences: {e}")
        return {
            "date_filter": "TODAY",
            "start_date": None,
            "end_date": None,
            "win_filter": True,
            "loss_filter": True,
            "contract_9am": True,
            "contract_10am": True,
            "contract_11am": True,
            "contract_12am": True,
            "contract_1pm": True,
            "contract_2pm": True,
            "contract_3pm": True,
            "contract_4pm": True,
            "contract_5pm": True,
            "contract_6pm": True,
            "contract_7pm": True,
            "contract_8pm": True,
            "contract_9pm": True,
            "contract_10pm": True,
            "contract_11pm": True,
            "symbol_btc": True,
            "symbol_eth": True,
            "symbol_spy": True,
            "symbol_ndx": True,
            "symbol_usd_eur": True,
            "strategy_hourly_htc": True,
            "strategy_momentum_scalp": True,
            "strategy_test": True,
            "analysis_interval": "daily",
            "sort_key": None,
            "sort_asc": True,
            "page_size": 50,
            "last_search_timestamp": int(time.time())
        }

def update_trade_history_preferences_postgresql(**kwargs):
    """Update trade history preferences in PostgreSQL using UPSERT"""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            # First, ensure we only have one row
            cursor.execute("DELETE FROM users.trade_history_preferences_0001 WHERE id > 1")
            
            # Build dynamic UPSERT query
            columns = list(kwargs.keys())
            values = list(kwargs.values())
            placeholders = ['%s'] * len(values)
            
            # Add updated_at to the columns
            columns.append('updated_at')
            placeholders.append('CURRENT_TIMESTAMP')
            
            query = f"""
                INSERT INTO users.trade_history_preferences_0001 (id, {', '.join(columns)})
                VALUES (1, {', '.join(placeholders)})
                ON CONFLICT (id) DO UPDATE SET
                {', '.join([f"{col} = EXCLUDED.{col}" for col in columns])}
            """
            
            cursor.execute(query, values)
            conn.commit()
            print(f"[PostgreSQL] Updated trade history preferences: {kwargs}")
        
        conn.close()
    except Exception as e:
        print(f"[PostgreSQL Error] Failed to update trade history preferences: {e}")

# Authentication system
AUTH_TOKENS_FILE = os.path.join(get_data_dir(), "users", "user_0001", "auth_tokens.json")
DEVICE_TOKENS_FILE = os.path.join(get_data_dir(), "users", "user_0001", "device_tokens.json")

# Authentication settings - can be overridden for local development
AUTH_ENABLED = True  # Force authentication enabled
# Force authentication in production
if os.environ.get("REC_ENVIRONMENT") == "production":
    AUTH_ENABLED = True

def load_auth_tokens():
    """Load authentication tokens from file"""
    try:
        if os.path.exists(AUTH_TOKENS_FILE):
            with open(AUTH_TOKENS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_auth_tokens(tokens):
    """Save authentication tokens to file"""
    try:
        os.makedirs(os.path.dirname(AUTH_TOKENS_FILE), exist_ok=True)
        with open(AUTH_TOKENS_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        print(f"[AUTH] Error saving auth tokens: {e}")

def load_device_tokens():
    """Load device tokens from file"""
    try:
        if os.path.exists(DEVICE_TOKENS_FILE):
            with open(DEVICE_TOKENS_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_device_tokens(tokens):
    """Save device tokens to file"""
    try:
        os.makedirs(os.path.dirname(DEVICE_TOKENS_FILE), exist_ok=True)
        with open(DEVICE_TOKENS_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        print(f"[AUTH] Error saving device tokens: {e}")

def generate_token():
    """Generate a secure authentication token"""
    return secrets.token_urlsafe(32)

def hash_password(password):
    """Hash a password using HMAC-SHA256"""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return salt + hash_obj.hex()

def verify_password(password, hashed):
    """Verify a password against its hash"""
    try:
        salt = hashed[:32]  # First 32 chars are salt
        hash_part = hashed[32:]
        hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return hmac.compare_digest(hash_obj.hex(), hash_part)
    except Exception:
        return False

def get_user_credentials():
    """Get user credentials from PostgreSQL"""
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
                SELECT user_id, first_name, last_name, email, phone, account_type, password_hash
                FROM users.user_info_0001 WHERE user_no = '0001'
            """)
            result = cursor.fetchone()
            if result:
                user_id, first_name, last_name, email, phone, account_type, password_hash = result
                return {
                    "username": user_id,
                    "name": f"{first_name} {last_name}" if first_name and last_name else user_id,
                    "email": email,
                    "phone": phone,
                    "account_type": account_type,
                    "password_hash": password_hash
                }
    except Exception as e:
        print(f"[AUTH] Error loading user credentials from PostgreSQL: {e}")
    
    # Fallback to JSON file for backward compatibility
    try:
        user_info_path = os.path.join(get_data_dir(), "users", "user_0001", "user_info.json")
        if os.path.exists(user_info_path):
            with open(user_info_path, "r") as f:
                user_info = json.load(f)
                return {
                    "username": user_info.get("user_id", "admin"),
                    "password": user_info.get("password", "admin"),  # Plain text fallback
                    "name": user_info.get("name", "Admin User")
                }
    except Exception as e:
        print(f"[AUTH] Error loading user credentials from JSON: {e}")
    
    # Default credentials if nothing works
    return {
        "username": "admin",
        "password": "admin",
        "name": "Admin User"
    }

def verify_password(password, hashed_password):
    """Verify a password against its hash"""
    try:
        # Check if it's a fallback hash (starts with 'fallback_hash_')
        if hashed_password.startswith('fallback_hash_'):
            # Extract the actual password from the fallback hash
            actual_password = hashed_password.replace('fallback_hash_', '')
            return password == actual_password
        
        # Try bcrypt verification
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception as e:
        print(f"[AUTH] Password verification error: {e}")
        return False

def change_password_hash(password):
    """Hash a password for storage"""
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    except ImportError:
        # Fallback to simple hash if bcrypt is not available
        print(f"[AUTH] bcrypt not available, using fallback password hashing")
        return f"fallback_hash_{password}"
    except Exception as e:
        print(f"[AUTH] Password hashing error: {e}")
        return f"fallback_hash_{password}"

def load_preferences():
    global _preferences_cache, _cache_timestamp
    current_time = time.time()
    
    # Return cached version if still valid
    if _preferences_cache is not None and (current_time - _cache_timestamp) < CACHE_TTL:
        return _preferences_cache.copy()
    
    # Load from PostgreSQL
    try:
        prefs = get_all_preferences_postgresql()
        
        # Update cache
        _preferences_cache = prefs
        _cache_timestamp = current_time
        return prefs
    except Exception as e:
        print(f"[Preferences Load Error] {e}")
        # Default preferences
        default_prefs = {"auto_stop": True, "auto_entry": False, "diff_mode": False, "position_size": 1, "multiplier": 1}
        _preferences_cache = default_prefs
        _cache_timestamp = current_time
        return default_prefs

async def save_preferences(prefs):
    global _preferences_cache, _cache_timestamp
    try:
        # Update PostgreSQL
        update_data = {}
        if "auto_stop" in prefs:
            update_data["auto_stop"] = bool(prefs["auto_stop"])
        if "auto_entry" in prefs:
            update_data["auto_entry"] = bool(prefs["auto_entry"])
        if "position_size" in prefs:
            update_data["position_size"] = int(prefs["position_size"])
        if "multiplier" in prefs:
            update_data["multiplier"] = int(prefs["multiplier"])
        
        if update_data:
            # Update auto_trade_settings for auto_stop and auto_entry
            auto_settings = {k: v for k, v in update_data.items() if k in ["auto_stop", "auto_entry"]}
            if auto_settings:
                update_auto_trade_settings_postgresql(**auto_settings)
            
            # Update trade_preferences for position_size and multiplier
            trade_settings = {k: v for k, v in update_data.items() if k in ["position_size", "multiplier"]}
            if trade_settings:
                update_trade_preferences_postgresql(**trade_settings)
        
        # Update cache
        _preferences_cache = prefs.copy()
        _cache_timestamp = time.time()
        print(f"[Preferences] ✅ Updated PostgreSQL: {list(update_data.keys())}")
    except Exception as e:
        print(f"[Preferences Save Error] {e}")

# Broadcast helper function for preferences updates
async def broadcast_preferences_update():
    try:
        data = json.dumps(load_preferences())
        to_remove = set()
        
        # Send to all connected clients concurrently
        tasks = []
        for client in connected_clients:
            task = asyncio.create_task(send_to_client(client, data))
            tasks.append(task)
        
        # Wait for all sends to complete with timeout
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1.0)
        
        # Clean up disconnected clients
        connected_clients.difference_update(to_remove)
    except Exception as e:
        print(f"[Broadcast Preferences Error] {e}")

async def send_to_client(client, data):
    try:
        await client.send_text(data)
    except Exception:
        # Client will be removed in the main function
        pass

# Broadcast helper function for account mode updates
async def broadcast_account_mode(mode: str):
    message = json.dumps({"account_mode": mode})
    to_remove = set()
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    connected_clients.difference_update(to_remove)

# Broadcast helper function for database changes
async def broadcast_db_change(db_name: str, change_data: dict):
    message = json.dumps({
        "type": "db_change",
        "database": db_name,
        "data": change_data,
        "timestamp": datetime.now().isoformat()
    })
    to_remove = set()
    for client in db_change_clients:
        try:
            await client.send_text(message)
        except Exception:
            to_remove.add(client)
    db_change_clients.difference_update(to_remove)

# Create FastAPI app
app = FastAPI(title="Trading System Main App")

# Import universal host system
from backend.util.paths import get_host

# Configure CORS with universal host origins
host = get_host()
origins = [
    f"http://{host}:{MAIN_APP_PORT}",
    f"http://localhost:{MAIN_APP_PORT}",
    f"http://127.0.0.1:{MAIN_APP_PORT}",
    f"https://{host}:{MAIN_APP_PORT}",
    f"https://localhost:{MAIN_APP_PORT}",
    f"https://127.0.0.1:{MAIN_APP_PORT}",
    # Domain-specific origins
    "https://rec-io.com",
    "https://www.rec-io.com",
    "http://rec-io.com",
    "http://www.rec-io.com",
    # Allow access from any device on the local network (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
    "*"  # Allow all origins for local network access
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files with cache busting
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Custom static file handler with cache busting
class CacheBustingStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    async def __call__(self, scope, receive, send):
        # Add cache-busting headers to all static files
        async def send_with_cache_busting(message):
            if message["type"] == "http.response.start":
                message["headers"].extend([
                    (b"cache-control", b"no-cache, no-store, must-revalidate"),
                    (b"pragma", b"no-cache"),
                    (b"expires", b"0")
                ])
            await send(message)
        
        await super().__call__(scope, receive, send_with_cache_busting)

# Mount static files
from backend.util.paths import get_frontend_dir
frontend_dir = get_frontend_dir()

app.mount("/tabs", CacheBustingStaticFiles(directory=f"{frontend_dir}/tabs"), name="tabs")
app.mount("/audio", CacheBustingStaticFiles(directory=f"{frontend_dir}/audio"), name="audio")
app.mount("/js", CacheBustingStaticFiles(directory=f"{frontend_dir}/js"), name="js")
app.mount("/images", CacheBustingStaticFiles(directory=f"{frontend_dir}/images"), name="images")
app.mount("/styles", CacheBustingStaticFiles(directory=f"{frontend_dir}/styles"), name="styles")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "main_app",
        "port": MAIN_APP_PORT,
        "timestamp": datetime.now().isoformat(),
        "port_system": "centralized"
    }

# Port information endpoint
@app.get("/api/ports")
async def get_ports(request: Request):
    """Get all port assignments from centralized system."""
    port_info = get_port_info()
    
    # Get the current request's protocol
    protocol = request.headers.get("x-forwarded-proto", "http")
    if protocol == "https":
        # Update service URLs to use HTTPS
        host = port_info["host"]
        ports = port_info["ports"]
        port_info["service_urls"] = {name: f"https://{host}:{port}" for name, port in ports.items()}
    
    return port_info

# Test endpoint
@app.get("/api/test-health")
async def test_health():
    """Test endpoint to verify routing works."""
    return {"message": "Test health endpoint working"}

# System health endpoint
@app.get("/api/system-health")
async def get_system_health():
    """Get comprehensive system health status."""
    try:
        # Import system monitor
        from backend.system_monitor import SystemMonitor
        
        # Create system monitor instance and generate health report
        monitor = SystemMonitor()
        health_report = monitor.generate_health_report()
        
        # Determine overall system status
        overall_status = "healthy"
        issues = []
        
        # Check supervisor status
        if health_report.get("supervisor_status", {}).get("status") != "running":
            overall_status = "offline"
            issues.append("Supervisor not running")
        
        # Check critical services
        critical_services = ["main_app", "trade_manager", "trade_executor", "active_trade_supervisor"]
        unhealthy_services = []
        
        for service in critical_services:
            service_status = health_report.get("services", {}).get(service, {})
            if service_status.get("status") != "healthy":
                unhealthy_services.append(service)
        
        if unhealthy_services:
            if len(unhealthy_services) >= len(critical_services) // 2:
                overall_status = "offline"
            else:
                overall_status = "degraded"
            issues.append(f"Unhealthy services: {', '.join(unhealthy_services)}")
        
        # Check database health
        db_health = health_report.get("database_health", {})
        if db_health.get("status") != "healthy":
            overall_status = "degraded"
            issues.append("Database issues detected")
        
        return {
            "status": overall_status,
            "issues": issues,
            "timestamp": datetime.now().isoformat(),
            "health_report": health_report
        }
        
    except Exception as e:
        return {
            "status": "offline",
            "issues": [f"System monitor error: {str(e)}"],
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

# WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[WEBSOCKET] ✅ Client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"[WEBSOCKET] ❌ Client disconnected. Total clients: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                # Remove dead connections
                self.active_connections.remove(connection)

manager = ConnectionManager()

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.send_personal_message(f"Message text was: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# WebSocket endpoint for preferences updates
@app.websocket("/ws/preferences")
async def websocket_preferences(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

@app.websocket("/ws/db_changes")
async def websocket_db_changes(websocket: WebSocket):
    await websocket.accept()
    db_change_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        db_change_clients.remove(websocket)

# Serve main index.html
@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the main application or login page based on authentication."""
    print(f"[AUTH] AUTH_ENABLED = {AUTH_ENABLED}")
    if AUTH_ENABLED:
        # Always redirect to login - no direct access to main app
        print(f"[AUTH] Redirecting to login page")
        return RedirectResponse(url="/login")
    else:
        # Local development mode - serve main app directly
        print(f"[AUTH] Serving main app directly (local development)")
        with open(f"{frontend_dir}/index.html", "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )

@app.get("/app", response_class=HTMLResponse)
async def serve_main_app(request: Request):
    """Serve the main application (protected route)."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters (sent by login page)
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    # Serve the main app
    with open(f"{frontend_dir}/index.html", "r") as f:
        content = f.read()
        return HTMLResponse(
            content=content,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

@app.get("/login", response_class=HTMLResponse)
async def serve_login():
    """Serve the login page."""
    try:
        with open(f"{frontend_dir}/login.html", "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Login</h1><p>Login page not found.</p>", status_code=404)

# Serve favicon
@app.get("/favicon.ico")
async def serve_favicon():
    """Serve favicon."""
    from fastapi.responses import FileResponse
    import os
    file_path = os.path.join("frontend", "images", "icons", "fave.ico")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    else:
        return {"error": "Favicon not found"}, 404

# Serve terminal control page
@app.get("/terminal-control.html", response_class=HTMLResponse)
async def serve_terminal_control():
    """Serve terminal control page."""
    import os
    file_path = f"{frontend_dir}/terminal-control.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(content="<h1>Terminal Control not found</h1>", status_code=404)

# Serve log viewer page
@app.get("/log-viewer.html", response_class=HTMLResponse)
async def serve_log_viewer():
    """Serve log viewer page."""
    import os
    file_path = f"{frontend_dir}/log-viewer.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse(content="<h1>Log Viewer not found</h1>", status_code=404)

# Serve CSS files with cache busting
@app.get("/styles/{filename:path}")
async def serve_css(filename: str):
    """Serve CSS files with cache busting headers."""
    file_path = f"{frontend_dir}/styles/{filename}"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Type": "text/css",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="CSS file not found", status_code=404)

# Serve JS files with cache busting
@app.get("/js/{filename:path}")
async def serve_js(filename: str):
    """Serve JS files with cache busting headers."""
    file_path = f"{frontend_dir}/js/{filename}"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Content-Type": "application/javascript",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="JS file not found", status_code=404)

# Serve mobile trade monitor with cache busting
@app.get("/mobile/trade_monitor", response_class=HTMLResponse)
async def serve_mobile_trade_monitor(request: Request):
    """Serve mobile trade monitor with cache busting headers."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/trade_monitor_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile trade monitor not found", status_code=404)

# Serve mobile account manager with cache busting
@app.get("/mobile/account_manager", response_class=HTMLResponse)
async def serve_mobile_account_manager(request: Request):
    """Serve mobile account manager with cache busting headers."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/account_manager_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile account manager not found", status_code=404)

# Serve mobile index with cache busting
@app.get("/mobile", response_class=HTMLResponse)
async def serve_mobile_index(request: Request):
    """Serve mobile index with cache busting headers."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/index.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile index not found", status_code=404)

# Serve mobile index.html directly (for direct access)
@app.get("/mobile/index.html", response_class=HTMLResponse)
async def serve_mobile_index_html(request: Request):
    """Serve mobile index.html directly with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/index.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile index not found", status_code=404)

# Test route for debugging
@app.get("/test-mobile")
async def test_mobile():
    """Test route for debugging mobile routes."""
    return {"message": "Mobile test route works!"}

# Test route for debugging mobile path
@app.get("/mobile/test")
async def test_mobile_path():
    """Test route for debugging mobile path."""
    return {"message": "Mobile path test route works!"}

# Serve mobile user settings with authentication
@app.get("/mobile/user", response_class=HTMLResponse)
async def serve_mobile_user(request: Request):
    """Serve mobile user settings with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/user_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile user settings not found", status_code=404)

# Serve mobile system with authentication
@app.get("/mobile/system", response_class=HTMLResponse)
async def serve_mobile_system(request: Request):
    """Serve mobile system page with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/system_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile system page not found", status_code=404)

# Serve mobile trade history with authentication
@app.get("/mobile/trade_history", response_class=HTMLResponse)
async def serve_mobile_trade_history(request: Request):
    """Serve mobile trade history with authentication."""
    # Check if user is authenticated
    if AUTH_ENABLED:
        # Get token from query parameters
        token = request.query_params.get("token", "")
        device_id = request.query_params.get("deviceId", "")
        
        if not token or not device_id:
            return RedirectResponse(url="/login")
        
        # Verify the token
        try:
            auth_tokens = load_auth_tokens()
            if token not in auth_tokens:
                return RedirectResponse(url="/login")
            
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() >= expires:
                return RedirectResponse(url="/login")
                
        except Exception as e:
            print(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/trade_history_mobile.html"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            return HTMLResponse(
                content=content,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        return HTMLResponse(content="Mobile trade history not found", status_code=404)

def get_ttc_data_from_postgresql() -> Dict[str, Any]:
    """Get TTC data directly from PostgreSQL"""
    try:
        from datetime import datetime, timezone, timedelta
        from zoneinfo import ZoneInfo
        
        # Calculate TTC (time to next hour)
        now_est = datetime.now(ZoneInfo('US/Eastern'))
        next_hour = now_est.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        ttc_seconds = int((next_hour - now_est).total_seconds())
        
        return {
            'ttc_seconds': ttc_seconds,
            'timestamp': now_est.isoformat(),
            'current_time_est': now_est.strftime("%I:%M:%S %p EDT"),
            'next_hour_est': next_hour.strftime("%I:%M:%S %p EDT")
        }
    except Exception as e:
        print(f"Error calculating TTC: {e}")
        return {"error": str(e)}

@app.get("/api/ttc")
async def get_ttc_data():
    """Get time to close data directly from PostgreSQL."""
    return get_ttc_data_from_postgresql()

# Core data endpoint
@app.get("/core")
async def get_core_data():
    """Get core trading data."""
    try:
        # Get current time
        now = datetime.now(pytz.timezone('US/Eastern'))
        date_str = now.strftime("%A, %B %d, %Y")
        time_str = now.strftime("%I:%M:%S %p EDT")
        
        # Get TTC directly from PostgreSQL
        ttc_seconds = 0
        try:
            ttc_data = get_ttc_data_from_postgresql()
            ttc_seconds = ttc_data.get('ttc_seconds', 0)
        except Exception as e:
            print(f"Error getting TTC from PostgreSQL: {e}")
            # Fallback calculation
            close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
            if now.time() >= close_time.time():
                close_time += timedelta(days=1)
            ttc_seconds = int((close_time - now).total_seconds())
        
        # Get BTC price from PostgreSQL live_data
        btc_price = 0
        try:
            # Get the latest price from PostgreSQL live_data.live_price_log_1s_btc
            import psycopg2
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            cursor = conn.cursor()
            cursor.execute("SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
            result = cursor.fetchone()
            conn.close()
            
            if result:
                btc_price = float(result[0])
                print(f"[MAIN] Using PostgreSQL BTC price: ${btc_price:,.2f}")
            else:
                # Fallback to direct API call if no PostgreSQL data
                response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    btc_price = float(data['result']['XXBTZUSD']['c'][0])
                    print(f"[MAIN] Using fallback API BTC price: ${btc_price:,.2f}")
        except Exception as e:
            print(f"Error fetching BTC price from PostgreSQL: {e}")
            # Final fallback to direct API call
            try:
                response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    btc_price = float(data['result']['XXBTZUSD']['c'][0])
                    print(f"[MAIN] Using emergency fallback API BTC price: ${btc_price:,.2f}")
            except Exception as e2:
                print(f"Emergency fallback also failed: {e2}")
        
        # Get momentum data directly from PostgreSQL
        momentum_data = {}
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile
                FROM live_data.live_price_log_1s_btc 
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result:
                momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile = result
                momentum_data = {
                    'weighted_momentum_score': float(momentum) if momentum is not None else 0.0,
                    'delta_1m': float(delta_1m) if delta_1m is not None else None,
                    'delta_2m': float(delta_2m) if delta_2m is not None else None,
                    'delta_3m': float(delta_3m) if delta_3m is not None else None,
                    'delta_4m': float(delta_4m) if delta_4m is not None else None,
                    'delta_15m': float(delta_15m) if delta_15m is not None else None,
                    'delta_30m': float(delta_30m) if delta_30m is not None else None,
                    'momentum_percentile': float(momentum_percentile) if momentum_percentile is not None else None
                }
                print(f"[MAIN] Momentum analysis: {momentum_data.get('weighted_momentum_score', 'N/A'):.4f}%")
            else:
                momentum_data = {
                    'delta_1m': None,
                    'delta_2m': None,
                    'delta_3m': None,
                    'delta_4m': None,
                    'delta_15m': None,
                    'delta_30m': None,
                    'weighted_momentum_score': None
                }
        except Exception as e:
            print(f"Error getting momentum data from PostgreSQL: {e}")
            # Fallback to null momentum data
            momentum_data = {
                'delta_1m': None,
                'delta_2m': None,
                'delta_3m': None,
                'delta_4m': None,
                'delta_15m': None,
                'delta_30m': None,
                'weighted_momentum_score': None
            }
        
        # Get latest database price from PostgreSQL
        latest_db_price = 0
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            with conn.cursor() as cursor:
                cursor.execute("SELECT buy_price FROM users.trades_0001 WHERE test_filter IS NULL OR test_filter = FALSE ORDER BY date DESC, time DESC LIMIT 1")
                result = cursor.fetchone()
                if result:
                    latest_db_price = result[0]
            conn.close()
        except Exception as e:
            print(f"Error getting latest DB price: {e}")
        
        # Get Kraken changes
        kraken_changes = {}
        try:
            response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
            if response.status_code == 200:
                data = response.json()
                ticker = data['result']['XXBTZUSD']
                
                # Calculate changes
                current_price = float(ticker['c'][0])
                for period in ['1h', '3h', '1d']:
                    if period == '1h':
                        old_price = float(ticker['p'][0])  # 24h low as proxy
                    elif period == '3h':
                        old_price = float(ticker['p'][0])  # 24h low as proxy
                    else:  # 1d
                        old_price = float(ticker['p'][0])  # 24h low as proxy
                    
                    change = (current_price - old_price) / old_price
                    kraken_changes[f"change{period}"] = change
        except Exception as e:
            print(f"Error getting Kraken changes: {e}")
        
        # Get Kalshi markets (placeholder)
        kalshi_markets = []
        
        return {
            "date": date_str,
            "time": time_str,
            "ttc_seconds": ttc_seconds,
            "btc_price": btc_price,
            "latest_db_price": latest_db_price,
            "timestamp": datetime.now().isoformat(),
            **momentum_data,  # Include all momentum deltas and weighted score
            "status": "online",
            "volScore": 0,
            "volSpike": 0,
            **kraken_changes,
            "kalshi_markets": kalshi_markets
        }
    except Exception as e:
        print(f"Error in core data: {e}")
        return {"error": str(e)}

# Account mode endpoints
@app.get("/api/get_account_mode")
async def get_account_mode_endpoint():
    """Get current account mode."""
    return {"mode": get_account_mode()}

@app.get("/api/get_kalshi_email")
async def get_kalshi_email_endpoint():
    """Get Kalshi email from credentials file for current account mode."""
    try:
        from backend.account_mode import get_account_mode
        from backend.util.paths import get_kalshi_credentials_dir
        import os
        
        mode = get_account_mode()
        cred_dir = os.path.join(get_kalshi_credentials_dir(), mode)
        auth_file = os.path.join(cred_dir, "kalshi-auth.txt")
        
        if os.path.exists(auth_file):
            # Read the credentials file directly
            with open(auth_file, "r") as f:
                lines = f.readlines()
            
            email = None
            for line in lines:
                if line.startswith("email:"):
                    email = line.split("email:")[1].strip()
                    break
            
            if email:
                # Add "DEMO" suffix for demo mode
                display_email = email if mode == "prod" else f"{email} DEMO"
                return {"email": display_email}
            else:
                return {"email": "No email found in credentials"}
        else:
            return {"email": "No credentials found"}
            
    except Exception as e:
        print(f"Error reading Kalshi credentials: {e}")
        return {"email": "Error reading credentials"}

@app.post("/api/set_account_mode")
async def set_account_mode(mode_data: dict):
    """Set account mode."""
    from backend.account_mode import set_account_mode
    mode = mode_data.get("mode")
    if mode in ["prod", "demo"]:
        set_account_mode(mode)
        return {"status": "success", "mode": mode}
    return {"status": "error", "message": "Invalid mode"}

# Trade data endpoints
@app.get("/trades")
async def get_trades(status: Optional[str] = None):
    """Get trade data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Build query based on status filter
            if status:
                cursor.execute("""
                    SELECT * FROM users.trades_0001 
                    WHERE status = %s 
                    ORDER BY id DESC
                """, (status,))
            else:
                cursor.execute("""
                    SELECT * FROM users.trades_0001 
                    ORDER BY id DESC
                """)
            
            trades = cursor.fetchall()
            
            # Convert RealDictRow objects to regular dictionaries
            result = []
            for trade in trades:
                trade_dict = dict(trade)
                
                # Create a combined timestamp field for frontend compatibility
                if 'date' in trade_dict and 'time' in trade_dict:
                    trade_dict['timestamp'] = f"{trade_dict['date']} {trade_dict['time']}"
                
                # Create a combined price field for frontend compatibility
                if 'buy_price' in trade_dict:
                    trade_dict['price'] = trade_dict['buy_price']
                
                result.append(trade_dict)
            
            conn.close()
            return result
            
    except Exception as e:
        print(f"Error getting trades from PostgreSQL: {e}")
        return []

@app.get("/trades/{trade_id}")
async def get_trade(trade_id: int):
    """Forward trade GET request to trade_manager."""
    try:
        # Get trade_manager port from centralized system
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades/{trade_id}"
        
        print(f"[MAIN] Forwarding trade GET request to trade_manager at {trade_manager_url}")
        
        # Forward the request to trade_manager
        response = requests.get(
            trade_manager_url,
            timeout=10
        )
        
        if response.status_code == 200:
            print(f"[MAIN] ✅ Trade GET request forwarded successfully to trade_manager")
            return response.json()
        else:
            print(f"[MAIN] ❌ Trade GET request forwarding failed: {response.status_code}")
            return {"error": f"Trade manager returned status {response.status_code}"}
            
    except Exception as e:
        print(f"[MAIN] ❌ Error forwarding trade GET request: {e}")
        return {"error": str(e)}

@app.post("/trades")
async def create_trade(trade_data: dict):
    """Forward trade ticket to trade_manager."""
    try:
        # Get trade_manager port from centralized system
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades"
        
        print(f"[MAIN] Forwarding trade ticket to trade_manager at {trade_manager_url}")
        
        # Forward the request to trade_manager
        response = requests.post(
            trade_manager_url,
            json=trade_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 201:
            print(f"[MAIN] ✅ Trade ticket forwarded successfully to trade_manager")
            return response.json()
        else:
            print(f"[MAIN] ❌ Trade ticket forwarding failed: {response.status_code}")
            return {"error": f"Trade manager returned status {response.status_code}"}
            
    except Exception as e:
        print(f"[MAIN] ❌ Error forwarding trade ticket: {e}")
        return {"error": str(e)}

# Additional endpoints for other data
@app.get("/btc_price_changes")
async def get_btc_changes():
    """Get BTC price changes from PostgreSQL live_data.price_change_btc."""
    try:
        import psycopg2
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        cursor = conn.cursor()
        
        # Get latest price changes from the database
        cursor.execute("""
            SELECT change1h, change3h, change1d, timestamp 
            FROM live_data.price_change_btc 
            ORDER BY timestamp DESC 
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            changes = {
                "change1h": float(result[0]) if result[0] is not None else None,
                "change3h": float(result[1]) if result[1] is not None else None,
                "change1d": float(result[2]) if result[2] is not None else None,
                "timestamp": result[3].isoformat() if result[3] else datetime.now(ZoneInfo("America/New_York")).isoformat()
            }
        else:
            changes = {"change1h": None, "change3h": None, "change1d": None, "timestamp": datetime.now(ZoneInfo("America/New_York")).isoformat()}
        
        return changes
        
    except Exception as e:
        print(f"[btc_price_changes API] Error reading from PostgreSQL: {e}")
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": None}

@app.get("/kalshi_market_snapshot")
async def get_kalshi_snapshot():
    """Get Kalshi market snapshot from PostgreSQL."""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            # Get market data from PostgreSQL
            cursor.execute("""
                SELECT 
                    market_ticker,
                    yes_ask,
                    no_ask,
                    volume,
                    event_ticker,
                    strike
                FROM live_data.market_kalshi_btc
                ORDER BY updated_at DESC
            """)
            
            markets_data = cursor.fetchall()
            conn.close()
            
            if not markets_data:
                return {"markets": []}
            
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
        print(f"Error getting Kalshi snapshot from PostgreSQL: {e}")
        return {"markets": []}

# API endpoints for account data
@app.get("/api/account/balance")
async def get_account_balance(mode: str = "prod"):
    """Get account balance from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get the latest account balance
            cursor.execute("""
                SELECT portfolio, positions, timestamp 
                FROM users.account_balance_0001 
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            balance_result = cursor.fetchone()
            
            
            conn.close()
            
            if balance_result:
                portfolio_value = balance_result['portfolio']
                positions_value = balance_result['positions'] if balance_result else 0
                return {
                    "portfolio": portfolio_value,
                    "positions": positions_value
                }
            else:
                return {"portfolio": 0, "positions": 0}
            
    except Exception as e:
        print(f"Error getting account balance from PostgreSQL: {e}")
        return {"portfolio": 0, "positions": 0}

@app.get("/api/account/balance/history")
async def get_account_balance_history(mode: str = "prod", limit: int = 1000):
    """Get historical account balance data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get historical account balance data
            cursor.execute("""
                SELECT portfolio, positions, timestamp 
                FROM users.account_balance_0001 
                ORDER BY timestamp ASC
                LIMIT %s
            """, (limit,))
            balance_results = cursor.fetchall()
            
            conn.close()
            
            # Convert to list of dictionaries
            history_data = []
            for result in balance_results:
                history_data.append({
                    "portfolio": result['portfolio'],
                    "positions": result['positions'],
                    "timestamp": result['timestamp'].isoformat() if result['timestamp'] else None
                })
            
            return {"history": history_data}
            
    except Exception as e:
        print(f"Error getting account balance history from PostgreSQL: {e}")
        return {"history": []}

@app.get("/api/db/fills")
def get_fills():
    """Get fills data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.fills_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            fills = cursor.fetchall()
            
            # Convert RealDictRow objects to regular dictionaries
            fills_list = []
            for fill in fills:
                fill_dict = dict(fill)
                fills_list.append(fill_dict)
            
            conn.close()
            return {"fills": fills_list}
            
    except Exception as e:
        print(f"Error getting fills from PostgreSQL: {e}")
        return {"fills": []}

@app.get("/api/db/positions")
def get_positions():
    """Get positions data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.positions_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            positions = cursor.fetchall()
            
            # Convert RealDictRow objects to regular dictionaries
            positions_list = []
            for position in positions:
                position_dict = dict(position)
                positions_list.append(position_dict)
            
            conn.close()
            return {"positions": positions_list}
            
    except Exception as e:
        print(f"Error getting positions from PostgreSQL: {e}")
        return {"positions": []}

@app.get("/api/db/settlements")
def get_settlements():
    """Get settlements data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.settlements_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            settlements = cursor.fetchall()
            
            # Convert RealDictRow objects to regular dictionaries
            settlements_list = []
            for settlement in settlements:
                settlement_dict = dict(settlement)
                settlements_list.append(settlement_dict)
            
            conn.close()
            return {"settlements": settlements_list}
            
    except Exception as e:
        print(f"Error getting settlements from PostgreSQL: {e}")
        return {"settlements": []}

@app.get("/api/db/system_health")
def get_system_health_from_db():
    """Get current system health from database with real-time capacity data"""
    try:
        import psycopg2
        import psutil
        
        # Get real-time system capacity data
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        memory_total_gb = memory.total / (1024**3)  # Convert bytes to GB
        memory_used_gb = memory.used / (1024**3)
        memory_available_gb = memory.available / (1024**3)
        
        disk_total_gb = disk.total / (1024**3)  # Convert bytes to GB
        disk_used_gb = disk.used / (1024**3)
        disk_free_gb = disk.free / (1024**3)
        
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM system.health_status WHERE id = 1")
            result = cursor.fetchone()
            
            if result:
                return {
                    "overall_status": result[1],
                    "cpu_percent": float(result[2]) if result[2] else None,
                    "memory_percent": float(result[3]) if result[3] else None,
                    "disk_percent": float(result[4]) if result[4] else None,
                    "database_status": result[5],
                    "supervisor_status": result[6],
                    "services_healthy": result[7],
                    "services_total": result[8],
                    "failed_services": result[9] or [],
                    "timestamp": result[11].isoformat() if result[11] else None,
                    # Add real-time capacity data
                    "memory_total_gb": round(memory_total_gb, 1),
                    "memory_used_gb": round(memory_used_gb, 1),
                    "memory_available_gb": round(memory_available_gb, 1),
                    "disk_total_gb": round(disk_total_gb, 1),
                    "disk_used_gb": round(disk_used_gb, 1),
                    "disk_free_gb": round(disk_free_gb, 1)
                }
            else:
                return {"error": "No health data available"}
                
    except Exception as e:
        print(f"[DB SYSTEM HEALTH] Error: {e}")
        return {"error": "Database error"}

@app.get("/api/db/trades")
def get_trades_from_postgresql():
    """Get trades data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get all trades from PostgreSQL
            cursor.execute("""
                SELECT * FROM users.trades_0001 
                ORDER BY id DESC
            """)
            trades = cursor.fetchall()
            
            # Convert RealDictRow objects to regular dictionaries
            trades_list = []
            for trade in trades:
                trade_dict = dict(trade)
                # Ensure all fields are present for frontend compatibility
                trade_dict.update({
                    'id': trade_dict.get('id'),
                    'status': trade_dict.get('status', ''),
                    'date': trade_dict.get('date', ''),
                    'time': trade_dict.get('time', ''),
                    'symbol': trade_dict.get('symbol', 'BTC'),
                    'trade_strategy': trade_dict.get('trade_strategy', ''),
                    'contract': trade_dict.get('contract', ''),
                    'strike': trade_dict.get('strike', ''),
                    'side': trade_dict.get('side', ''),
                    'prob': trade_dict.get('prob'),
                    'diff': trade_dict.get('diff'),
                    'buy_price': trade_dict.get('buy_price'),
                    'sell_price': trade_dict.get('sell_price'),
                    'position': trade_dict.get('position'),
                    'closed_at': trade_dict.get('closed_at'),
                    'fees': trade_dict.get('fees'),
                    'pnl': trade_dict.get('pnl'),
                    'symbol_open': trade_dict.get('symbol_open'),
                    'symbol_close': trade_dict.get('symbol_close'),
                    'momentum': trade_dict.get('momentum'),
                    'win_loss': trade_dict.get('win_loss')
                })
                trades_list.append(trade_dict)
            
            conn.close()
            return {"trades": trades_list}
            
    except Exception as e:
        print(f"Error getting trades from PostgreSQL: {e}")
        return {"trades": []}

# Fingerprint and strike probability endpoints
@app.get("/api/current_fingerprint")
async def get_current_fingerprint():
    """Get current fingerprint information."""
    try:
        from util.probability_calculator import get_probability_calculator
        
        calculator = get_probability_calculator()
        
        fingerprint_info = {
            "symbol": calculator.symbol,
            "current_momentum_bucket": calculator.current_momentum_bucket,
            "last_used_momentum_bucket": calculator.last_used_momentum_bucket,
            "fingerprint": f"{calculator.symbol}_fingerprint_directional_momentum_{calculator.current_momentum_bucket:03d}.csv",
            "fingerprint_file": f"{calculator.symbol}_fingerprint_directional_momentum_{calculator.current_momentum_bucket:03d}.csv",
            "available_buckets": list(calculator.momentum_fingerprints.keys()) if hasattr(calculator, 'momentum_fingerprints') else []
        }
        
        print(f"[FINGERPRINT] Current fingerprint: {fingerprint_info['fingerprint_file']}")
        return fingerprint_info
        
    except Exception as e:
        print(f"Error getting fingerprint: {e}")
        return {"fingerprint": "error", "error": str(e)}

@app.get("/api/momentum")
async def get_current_momentum():
    """Get current momentum score directly from PostgreSQL."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT momentum FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            momentum_score = float(result[0])
            return {
                "status": "ok",
                "momentum_score": momentum_score
            }
        else:
            return {
                "status": "error",
                "momentum_score": 0,
                "error": "No momentum data available"
            }
    except Exception as e:
        print(f"Error getting momentum from PostgreSQL: {e}")
        return {
            "status": "error",
            "momentum_score": 0,
            "error": "Unable to get momentum from PostgreSQL"
        }

@app.get("/api/btc_price")
async def get_btc_price():
    """Get current BTC price directly from PostgreSQL live_data.live_price_log_1s_btc."""
    try:
        import psycopg2
        
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            price = float(result[0])
            return {"price": price, "source": "postgresql_live_data"}
        else:
            return {"price": None, "error": "No price data available"}
            
    except Exception as e:
        print(f"Error getting BTC price from PostgreSQL: {e}")
        return {"price": None, "error": str(e)}

@app.get("/api/momentum_score")
async def get_momentum_score():
    """Get current momentum score for mobile directly from PostgreSQL."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT momentum FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            weighted_score = float(result[0])
            return {"weighted_score": weighted_score}
        else:
            return {"weighted_score": 0, "error": "No momentum data available"}
    except Exception as e:
        print(f"Error getting momentum score: {e}")
        return {"weighted_score": 0, "error": str(e)}

@app.get("/api/strike_table")
async def get_strike_table_mobile():
    """Get strike table data for mobile from PostgreSQL."""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            # Get strike table data from PostgreSQL
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
            conn.close()
            
            if not strikes_data:
                return {"strikes": [], "error": "No strike table data found"}
            
            # Convert to the same format as the JSON file
            strikes = []
            for row in strikes_data:
                strike = {
                    "strike": float(row[0]) if row[0] else None,
                    "buffer": float(row[1]) if row[1] else None,
                    "buffer_pct": float(row[2]) if row[2] else None,
                    "probability": float(row[3]) if row[3] else None,
                    "yes_ask": int(row[4]) if row[4] else None,
                    "no_ask": int(row[5]) if row[5] else None,
                    "volume": int(row[6]) if row[6] else None,
                    "ticker": row[7],
                    "yes_diff": float(row[8]) if row[8] else None,
                    "no_diff": float(row[9]) if row[9] else None,
                    "active_side": row[10]
                }
                strikes.append(strike)
            
            return {"strikes": strikes}
            
    except Exception as e:
        print(f"Error getting strike table from PostgreSQL: {e}")
        return {"strikes": [], "error": str(e)}

# === PREFERENCES API ENDPOINTS ===

@app.post("/api/set_auto_stop")
async def set_auto_stop(request: Request):
    data = await request.json()
    enabled = bool(data.get("enabled", False))
    
    # Return immediate response
    response_data = {"status": "ok", "enabled": enabled}
    
    # Handle file operations asynchronously
    async def update_preferences():
        try:
            # Update PostgreSQL directly (new workflow)
            update_auto_trade_settings_postgresql(auto_stop=enabled)
            
            # Broadcast the update to connected clients
            await broadcast_preferences_update()
        except Exception as e:
            print(f"[Auto Stop Update Error] {e}")
    
    # Start async task without waiting
    import asyncio
    asyncio.create_task(update_preferences())
    
    return response_data

@app.post("/api/set_auto_entry")
async def set_auto_entry(request: Request):
    data = await request.json()
    enabled = bool(data.get("enabled", False))
    
    # Return immediate response
    response_data = {"status": "ok", "enabled": enabled}
    
    # Handle file operations asynchronously
    async def update_preferences():
        try:
            # Update PostgreSQL directly (new workflow)
            update_auto_trade_settings_postgresql(auto_entry=enabled)
            
            # Broadcast the update to connected clients
            await broadcast_preferences_update()
            
            # Trigger auto entry supervisor to reload settings
            try:
                import subprocess
                import sys
                from backend.util.paths import get_dynamic_project_root
                # Import the auto_entry_supervisor module and call reload function
                sys.path.append(get_dynamic_project_root())
                from backend.auto_entry_supervisor import log
                log("[AUTO ENTRY] Settings updated via API - supervisor will reload on next check")
            except Exception as e:
                print(f"[Auto Entry Status Update Error] {e}")
        except Exception as e:
            print(f"[Auto Entry Update Error] {e}")
    
    # Start async task without waiting
    import asyncio
    asyncio.create_task(update_preferences())
    
    return response_data

# Diff mode is now local only - no API endpoint needed

@app.post("/api/set_position_size")
async def set_position_size(request: Request):
    data = await request.json()
    position_size = int(data.get("position_size", 100))
    
    # Update PostgreSQL
    update_trade_preferences_postgresql(position_size=position_size)
    
    # Also update legacy JSON for compatibility during migration
    prefs = load_preferences()
    try:
        prefs["position_size"] = position_size
        await save_preferences(prefs)
        await broadcast_preferences_update()
    except Exception as e:
        print(f"[Set Position Size Error] {e}")
    return {"status": "ok"}

@app.post("/api/set_multiplier")
async def set_multiplier(request: Request):
    data = await request.json()
    multiplier = int(data.get("multiplier", 1))
    
    # Update PostgreSQL
    update_trade_preferences_postgresql(multiplier=multiplier)
    
    # Also update legacy JSON for compatibility during migration
    prefs = load_preferences()
    try:
        prefs["multiplier"] = multiplier
        await save_preferences(prefs)
        await broadcast_preferences_update()
    except Exception as e:
        print(f"[Set Multiplier Error] {e}")
    return {"status": "ok"}

@app.post("/api/update_preferences")
async def update_preferences(request: Request):
    data = await request.json()
    prefs = load_preferences()
    updated = False

    if "position_size" in data:
        try:
            prefs["position_size"] = int(data["position_size"])
            updated = True
        except Exception as e:
            print(f"[Invalid Position Size] {e}")

    if "multiplier" in data:
        try:
            prefs["multiplier"] = int(data["multiplier"])
            updated = True
        except Exception as e:
            print(f"[Invalid Multiplier] {e}")

    if updated:
        await save_preferences(prefs)
        await broadcast_preferences_update()
    return {"status": "ok"}

@app.get("/api/get_preferences")
async def get_preferences():
    """Get current preferences"""
    prefs = load_preferences()
    
    # Add trade strategy from PostgreSQL
    try:
        trade_prefs = get_trade_preferences_postgresql()
        prefs["trade_strategy"] = trade_prefs["trade_strategy"]
    except Exception as e:
        print(f"[Get Preferences Error] Failed to get trade strategy from PostgreSQL: {e}")
        prefs["trade_strategy"] = "Hourly HTC"  # Default fallback
    
    return prefs

# === ACTIVE TRADES PROXY ROUTE ===
@app.get("/api/active_trades")
async def proxy_active_trades():
    """Proxy route to forward active trades requests to the active trade supervisor"""
    try:
        # Forward request to active trade supervisor
        response = requests.get(f"http://localhost:{ACTIVE_TRADE_SUPERVISOR_PORT}/api/active_trades", timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"Active trade supervisor returned status {response.status_code}"}, response.status_code
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to connect to active trade supervisor: {str(e)}"}, 503

# Legacy trade history preferences path removed - all data now in PostgreSQL

def load_trade_history_preferences():
    """Load trade history preferences from PostgreSQL"""
    try:
        return get_trade_history_preferences_postgresql()
    except Exception as e:
        print(f"[Trade History Preferences Load Error] {e}")
        return {
            "date_filter": "TODAY",
            "start_date": None,
            "end_date": None,
            "win_filter": True,
            "loss_filter": True,
            "contract_9am": True,
            "contract_10am": True,
            "contract_11am": True,
            "contract_12am": True,
            "contract_1pm": True,
            "contract_2pm": True,
            "contract_3pm": True,
            "contract_4pm": True,
            "contract_5pm": True,
            "contract_6pm": True,
            "contract_7pm": True,
            "contract_8pm": True,
            "contract_9pm": True,
            "contract_10pm": True,
            "contract_11pm": True,
            "symbol_btc": True,
            "symbol_eth": True,
            "symbol_spy": True,
            "symbol_ndx": True,
            "symbol_usd_eur": True,
            "strategy_hourly_htc": True,
            "strategy_momentum_scalp": True,
            "strategy_test": True,
            "analysis_interval": "daily",
            "sort_key": None,
            "sort_asc": True,
            "page_size": 50,
            "last_search_timestamp": time.time()
        }

def save_trade_history_preferences(preferences):
    """Save trade history preferences to PostgreSQL"""
    try:
        # Prepare data for PostgreSQL
        update_data = {}
        if "date_filter" in preferences:
            update_data["date_filter"] = str(preferences["date_filter"])
        if "start_date" in preferences:
            update_data["start_date"] = preferences["start_date"]
        if "end_date" in preferences:
            update_data["end_date"] = preferences["end_date"]
        if "win_filter" in preferences:
            update_data["win_filter"] = bool(preferences["win_filter"])
        if "loss_filter" in preferences:
            update_data["loss_filter"] = bool(preferences["loss_filter"])
        
        # Contract filters
        contract_fields = [
            "contract_9am", "contract_10am", "contract_11am", "contract_12am",
            "contract_1pm", "contract_2pm", "contract_3pm", "contract_4pm",
            "contract_5pm", "contract_6pm", "contract_7pm", "contract_8pm",
            "contract_9pm", "contract_10pm", "contract_11pm"
        ]
        for field in contract_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])
        
        # Symbol filters
        symbol_fields = ["symbol_btc", "symbol_eth", "symbol_spy", "symbol_ndx", "symbol_usd_eur"]
        for field in symbol_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])
        
        # Strategy filters
        strategy_fields = ["strategy_hourly_htc", "strategy_momentum_scalp", "strategy_test"]
        for field in strategy_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])
        
        # Analysis interval
        if "analysis_interval" in preferences:
            update_data["analysis_interval"] = str(preferences["analysis_interval"])
        
        if "sort_key" in preferences:
            update_data["sort_key"] = preferences["sort_key"]
        if "sort_asc" in preferences:
            update_data["sort_asc"] = bool(preferences["sort_asc"])
        if "page_size" in preferences:
            update_data["page_size"] = int(preferences["page_size"])
        if "last_search_timestamp" in preferences:
            update_data["last_search_timestamp"] = int(preferences["last_search_timestamp"])
        
        if update_data:
            update_trade_history_preferences_postgresql(**update_data)
            print(f"[Trade History Preferences] ✅ Updated PostgreSQL: {list(update_data.keys())}")
    except Exception as e:
        print(f"[Trade History Preferences Save Error] {e}")

@app.get("/api/get_trade_history_preferences")
async def get_trade_history_preferences():
    """Get trade history preferences"""
    return load_trade_history_preferences()

@app.post("/api/set_trade_history_preferences")
async def set_trade_history_preferences(request: Request):
    """Set trade history preferences"""
    try:
        data = await request.json()
        preferences = load_trade_history_preferences()
        
        # Update preferences with new data
        for key, value in data.items():
            preferences[key] = value
        
        # Update timestamp
        preferences["last_search_timestamp"] = time.time()
        
        # Save preferences
        save_trade_history_preferences(preferences)
        
        return {"status": "ok", "preferences": preferences}
    except Exception as e:
        print(f"[Trade History Preferences Set Error] {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/get_auto_stop")
async def get_auto_stop():
    prefs = load_preferences()
    return {"enabled": prefs.get("auto_stop", True)}

@app.get("/api/get_auto_trade_settings")
async def get_auto_trade_settings():
    """Get auto trade settings from PostgreSQL"""
    settings = get_auto_trade_settings_postgresql()
    if settings is None:
        return {"status": "error", "message": "Failed to retrieve auto trade settings"}
    return settings

@app.get("/api/get_auto_entry_status")
async def get_auto_entry_status():
    """Get current auto entry status and cooldown timer from PostgreSQL"""
    try:
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        with conn.cursor() as cursor:
            cursor.execute("SELECT auto_entry_status, cooldown_timer FROM users.auto_trade_settings_0001 WHERE id = 1")
            result = cursor.fetchone()
            status = result[0] if result else "DISABLED"
            cooldown_timer = result[1] if result and result[1] is not None else 0
            conn.close()
            return {"status": status, "cooldown_timer": cooldown_timer}
    except Exception as e:
        print(f"Error getting auto entry status: {e}")
        return {"status": "DISABLED", "cooldown_timer": 0, "error": str(e)}

@app.get("/api/get_trade_preferences")
async def get_trade_preferences():
    """Get trade preferences from PostgreSQL"""
    return get_trade_preferences_postgresql()

@app.post("/api/update_trade_preferences")
async def update_trade_preferences(request: Request):
    """Update trade preferences in PostgreSQL"""
    try:
        data = await request.json()
        
        # Update PostgreSQL
        update_trade_preferences_postgresql(**data)
        
        # Also update legacy JSON for compatibility during migration
        prefs = load_preferences()
        if 'trade_strategy' in data:
            prefs['trade_strategy'] = data['trade_strategy']
        if 'position_size' in data:
            prefs['position_size'] = data['position_size']
        if 'multiplier' in data:
            prefs['multiplier'] = data['multiplier']
        
        await save_preferences(prefs)
        await broadcast_preferences_update()
        
        return {"status": "ok", "updated": data}
    except Exception as e:
        print(f"Error updating trade preferences: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/update_auto_entry_settings")
async def update_auto_entry_settings(request: Request):
    """Update auto entry settings in PostgreSQL"""
    data = await request.json()
    
    # Extract auto entry settings
    update_data = {}
    if "min_probability" in data:
        update_data["min_probability"] = int(data["min_probability"])
    if "min_differential" in data:
        update_data["min_differential"] = float(data["min_differential"])
    if "min_time" in data:
        update_data["min_time"] = int(data["min_time"])
    if "max_time" in data:
        update_data["max_time"] = int(data["max_time"])
    if "allow_re_entry" in data:
        update_data["allow_re_entry"] = bool(data["allow_re_entry"])
    if "spike_alert_enabled" in data:
        update_data["spike_alert_enabled"] = bool(data["spike_alert_enabled"])
    if "spike_alert_momentum_threshold" in data:
        update_data["spike_alert_momentum_threshold"] = int(data["spike_alert_momentum_threshold"])
    if "spike_alert_cooldown_threshold" in data:
        update_data["spike_alert_cooldown_threshold"] = int(data["spike_alert_cooldown_threshold"])
    if "spike_alert_cooldown_minutes" in data:
        update_data["spike_alert_cooldown_minutes"] = int(data["spike_alert_cooldown_minutes"])
    
    if update_data:
        update_auto_trade_settings_postgresql(**update_data)
    
    return {"status": "ok", "updated": update_data}

@app.post("/api/update_auto_stop_settings")
async def update_auto_stop_settings(request: Request):
    """Update auto stop settings in PostgreSQL"""
    data = await request.json()
    
    # Extract auto stop settings
    update_data = {}
    if "current_probability" in data:
        update_data["current_probability"] = int(data["current_probability"])
    if "min_ttc_seconds" in data:
        update_data["min_ttc_seconds"] = int(data["min_ttc_seconds"])
    if "momentum_spike_enabled" in data:
        update_data["momentum_spike_enabled"] = bool(data["momentum_spike_enabled"])
    if "momentum_spike_threshold" in data:
        update_data["momentum_spike_threshold"] = int(data["momentum_spike_threshold"])
    
    if update_data:
        update_auto_trade_settings_postgresql(**update_data)
    
    return {"status": "ok", "updated": update_data}

import os
# Legacy auto stop settings path removed - all data now in PostgreSQL

# Legacy auto stop settings functions removed - all data now in PostgreSQL

@app.get("/api/get_auto_stop_settings")
async def get_auto_stop_settings():
    return get_auto_stop_settings_postgresql()

@app.post("/api/set_auto_stop_settings")
async def set_auto_stop_settings(request: Request):
    data = await request.json()
    
    # Update PostgreSQL database
    try:
        update_data = {}
        if "current_probability" in data:
            update_data["current_probability"] = int(data["current_probability"])
        if "min_ttc_seconds" in data:
            update_data["min_ttc_seconds"] = int(data["min_ttc_seconds"])
        if "momentum_spike_enabled" in data:
            update_data["momentum_spike_enabled"] = bool(data["momentum_spike_enabled"])
        if "momentum_spike_threshold" in data:
            update_data["momentum_spike_threshold"] = int(data["momentum_spike_threshold"])
        if "verification_period_enabled" in data:
            update_data["verification_period_enabled"] = bool(data["verification_period_enabled"])
        if "verification_period_seconds" in data:
            update_data["verification_period_seconds"] = int(data["verification_period_seconds"])
        
        if update_data:
            update_auto_trade_settings_postgresql(**update_data)
            print(f"[Auto Stop Settings] ✅ Updated PostgreSQL: {list(update_data.keys())}")
    except Exception as e:
        print(f"[Auto Stop Settings] ❌ PostgreSQL Update Error: {e}")
    
    # Return updated settings from PostgreSQL
    updated_settings = get_auto_stop_settings_postgresql()
    return {"status": "ok", **updated_settings}

# Legacy auto entry settings path removed - all data now in PostgreSQL

# Legacy auto entry settings functions removed - all data now in PostgreSQL

@app.get("/api/get_auto_entry_settings")
async def get_auto_entry_settings():
    return get_auto_trade_settings_postgresql()

@app.post("/api/set_auto_entry_settings")
async def set_auto_entry_settings(request: Request):
    data = await request.json()
    
    # Update PostgreSQL database
    try:
        update_data = {}
        if "min_probability" in data:
            update_data["min_probability"] = int(data["min_probability"])
        if "min_differential" in data:
            update_data["min_differential"] = float(data["min_differential"])
        if "min_time" in data:
            update_data["min_time"] = int(data["min_time"])
        if "max_time" in data:
            update_data["max_time"] = int(data["max_time"])
        if "allow_re_entry" in data:
            update_data["allow_re_entry"] = bool(data["allow_re_entry"])
        if "spike_alert_enabled" in data:
            update_data["spike_alert_enabled"] = bool(data["spike_alert_enabled"])
        if "spike_alert_momentum_threshold" in data:
            update_data["spike_alert_momentum_threshold"] = int(data["spike_alert_momentum_threshold"])
        if "spike_alert_cooldown_threshold" in data:
            update_data["spike_alert_cooldown_threshold"] = int(data["spike_alert_cooldown_threshold"])
        if "spike_alert_cooldown_minutes" in data:
            update_data["spike_alert_cooldown_minutes"] = int(data["spike_alert_cooldown_minutes"])
        
        if update_data:
            update_auto_trade_settings_postgresql(**update_data)
            print(f"[Auto Entry Settings] ✅ Updated PostgreSQL: {list(update_data.keys())}")
    except Exception as e:
        print(f"[Auto Entry Settings] ❌ PostgreSQL Update Error: {e}")
    
    # Return updated settings from PostgreSQL
    updated_settings = get_auto_trade_settings_postgresql()
    if updated_settings is None:
        return {"status": "error", "message": "Failed to retrieve auto trade settings"}
    return {"status": "ok", **updated_settings}

@app.post("/api/trigger_open_trade")
async def trigger_open_trade(request: Request):
    """Trigger trade opening directly via the trade_manager service."""
    try:
        data = await request.json()
        strike = data.get("strike")
        side = data.get("side")
        ticker = data.get("ticker")
        buy_price = data.get("buy_price")
        prob = data.get("prob")
        symbol_open = data.get("symbol_open")
        momentum = data.get("momentum")
        contract = data.get("contract")
        symbol = data.get("symbol")
        position = data.get("position")
        trade_strategy = data.get("trade_strategy")
        
        print(f"[TRIGGER OPEN TRADE] Received request: strike={strike}, side={side}, ticker={ticker}, buy_price={buy_price}, prob={prob}, symbol_open={symbol_open}, momentum={momentum}")
        
        # Forward the request directly to the trade_manager service
        trade_manager_port = get_port("trade_manager")
        from backend.util.paths import get_host
        trade_manager_host = get_host()
        trade_manager_url = f"http://{trade_manager_host}:{trade_manager_port}/trades"
        
        # Create the exact same payload that trade_initiator would create
        import uuid
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        # Generate unique ticket ID (same format as trade_initiator)
        ticket_id = f"TICKET-{uuid.uuid4().hex[:9]}-{int(datetime.now().timestamp() * 1000)}"
        
        # Get current time in Eastern Time (same as trade_initiator)
        now = datetime.now(ZoneInfo("America/New_York"))
        eastern_date = now.strftime('%Y-%m-%d')
        eastern_time = now.strftime('%H:%M:%S')
        
        # Convert side format (yes/no to Y/N) - same as trade_initiator
        converted_side = side
        if side == "yes":
            converted_side = "Y"
        elif side == "no":
            converted_side = "N"
        
        # Prepare the trade data exactly like trade_initiator does
        trade_data = {
            "ticket_id": ticket_id,
            "status": "pending",
            "date": eastern_date,
            "time": eastern_time,
            "symbol": symbol or "BTC",
            "market": "Kalshi",
            "trade_strategy": trade_strategy or "Hourly HTC",
            "contract": contract or "BTC Market",
            "strike": strike,
            "side": converted_side,
            "ticker": ticker,
            "buy_price": buy_price,
            "position": position or 1,
            "symbol_open": symbol_open,
            "symbol_close": None,
            "momentum": momentum,
            "prob": prob,
            "win_loss": None,
            "entry_method": data.get("entry_method", "manual")
        }
        
        # Send request directly to trade_manager
        response = requests.post(trade_manager_url, json=trade_data, timeout=10)
        
        if response.status_code == 201:
            result = response.json()
            print(f"[TRIGGER OPEN TRADE] Trade initiated successfully: {result}")
            return {
                "status": "success",
                "message": "Trade initiated successfully",
                "trade_data": result
            }
        else:
            print(f"[TRIGGER OPEN TRADE] Trade initiation failed: {response.status_code} - {response.text}")
            return {
                "status": "error",
                "message": f"Trade initiation failed: {response.status_code}",
                "details": response.text
            }
        
    except Exception as e:
        print(f"[TRIGGER OPEN TRADE] Error: {e}")
        return {"status": "error", "message": str(e)}



@app.get("/frontend-changes")
def frontend_changes():
    """Get the latest modification time of frontend files for cache busting."""
    import os
    latest = 0
    for root, dirs, files in os.walk("frontend"):
        for f in files:
            path = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(path)
                if mtime > latest:
                    latest = mtime
            except Exception:
                pass
    return {"last_modified": latest}

@app.get("/api/live_probabilities")
async def get_live_probabilities():
    """Get live probabilities from PostgreSQL strike table"""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            # Get probability data from PostgreSQL strike table
            cursor.execute("""
                SELECT 
                    strike,
                    probability
                FROM live_data.strike_table_btc
                ORDER BY strike
            """)
            
            probabilities_data = cursor.fetchall()
            conn.close()
            
            if not probabilities_data:
                return {"error": "No probability data found"}
            
            # Convert to the same format as the JSON file
            probabilities = []
            for row in probabilities_data:
                prob_data = {
                    "strike": float(row[0]) if row[0] else None,
                    "prob_within": float(row[1]) if row[1] else None
                }
                probabilities.append(prob_data)
            
            return {
                "probabilities": probabilities,
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        return {"error": f"Error loading live probabilities from PostgreSQL: {str(e)}"}

def safe_read_json(filepath: str, timeout: float = 0.1):
    """Read JSON data with file locking to prevent race conditions"""
    try:
        with open(filepath, 'r') as f:
            # Try to acquire a shared lock with timeout
            fcntl.flock(f.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (IOError, OSError) as e:
        # If locking fails, fall back to normal read (rare)
        print(f"Warning: File locking failed for {filepath}: {e}")
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as read_error:
            print(f"Error reading JSON from {filepath}: {read_error}")
            return None

@app.get("/api/strike_tables/{symbol}")
async def get_strike_table(symbol: str):
    """Get strike table data for a specific symbol from PostgreSQL"""
    try:
        import psycopg2
        
        # Convert symbol to lowercase for consistency
        symbol_lower = symbol.lower()
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            # Get header data
            cursor.execute(f"""
                SELECT 
                    symbol,
                    current_price,
                    ttc_seconds,
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status,
                    momentum_weighted_score
                FROM live_data.strike_table_{symbol_lower}
                LIMIT 1
            """)
            
            header_data = cursor.fetchone()
            
            if not header_data:
                return {"error": f"No strike table data found for {symbol}"}
            
            # Get all strike rows
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
                FROM live_data.strike_table_{symbol_lower}
                ORDER BY strike
            """)
            
            strikes_data = cursor.fetchall()
            conn.close()
            
            # Build response in the same format as JSON
            response = {
                "symbol": header_data[0],
                "current_price": float(header_data[1]) if header_data[1] else None,
                "ttc": int(header_data[2]) if header_data[2] else None,
                "event_ticker": header_data[3],
                "market_title": header_data[4],
                "strike_tier": header_data[5],
                "market_status": header_data[6],
                "momentum": {
                    "weighted_score": float(header_data[7]) if header_data[7] else 0.0
                },
                "strikes": []
            }
            
            for row in strikes_data:
                strike = {
                    "strike": float(row[0]) if row[0] else None,
                    "buffer": float(row[1]) if row[1] else None,
                    "buffer_pct": float(row[2]) if row[2] else None,
                    "probability": float(row[3]) if row[3] else None,
                    "yes_ask": int(row[4]) if row[4] else None,
                    "no_ask": int(row[5]) if row[5] else None,
                    "volume": int(row[6]) if row[6] else None,
                    "ticker": row[7],
                    "yes_diff": float(row[8]) if row[8] else None,
                    "no_diff": float(row[9]) if row[9] else None,
                    "active_side": row[10]
                }
                response["strikes"].append(strike)
            
            return response
            
    except Exception as e:
        return {"error": f"Error loading strike table for {symbol} from PostgreSQL: {str(e)}"}

@app.get("/api/postgresql/strike_table/{symbol}")
async def get_postgresql_strike_table(symbol: str):
    """Get strike table data from PostgreSQL for a specific symbol"""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            # Get the latest strike table data from PostgreSQL
            cursor.execute(f"""
                SELECT 
                    symbol,
                    current_price,
                    ttc_seconds,
                    momentum_weighted_score,
                    market_title,
                    timestamp
                FROM live_data.strike_table_{symbol.lower()} 
                LIMIT 1
            """)
            
            header_data = cursor.fetchone()
            
            if not header_data:
                return {"error": f"No strike table data found for {symbol}"}
            
            # Get all strike rows
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
                FROM live_data.strike_table_{symbol.lower()} 
                ORDER BY strike
            """)
            
            strikes_data = cursor.fetchall()
            
            # Calculate momentum bucket from momentum_weighted_score
            momentum_score = float(header_data[3]) if header_data[3] else 0
            momentum_bucket = round(momentum_score * 100)
            
            # Format the response
            response = {
                "symbol": header_data[0],
                "current_price": float(header_data[1]) if header_data[1] else None,
                "ttc_seconds": int(header_data[2]) if header_data[2] else None,
                "momentum_weighted_score": momentum_score,
                "momentum_bucket": momentum_bucket,
                "market_title": header_data[4],
                "timestamp": header_data[5].isoformat() if header_data[5] else None,
                "strikes": []
            }
            
            # Add strike data
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
        print(f"Error getting PostgreSQL strike table for {symbol}: {str(e)}")
        return {"error": f"Error loading PostgreSQL strike table for {symbol}: {str(e)}"}

@app.get("/api/watchlist/{symbol}")
async def get_watchlist(symbol: str):
    """Get watchlist data for a specific symbol from PostgreSQL"""
    try:
        import psycopg2
        
        # Convert symbol to lowercase for consistency
        symbol_lower = symbol.lower()
        
        # Connect to PostgreSQL using unified configuration
        db_config = unified_config.get_database_config()
        conn = psycopg2.connect(
            host=db_config.get('host', 'localhost'),
            database=db_config.get('name', 'rec_io_db'),
            user=db_config.get('user', 'rec_io_user'),
            password=db_config.get('password', 'rec_io_password')
        )
        
        with conn.cursor() as cursor:
            # Get header data
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
                FROM live_data.watchlist_{symbol_lower}
                LIMIT 1
            """)
            
            header_data = cursor.fetchone()
            
            if not header_data:
                return {"error": f"No watchlist data found for {symbol}"}
            
            # Get all strike rows
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
                FROM live_data.watchlist_{symbol_lower}
                ORDER BY probability DESC
            """)
            
            strikes_data = cursor.fetchall()
            conn.close()
            
            # Build response in the same format as JSON
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
            
            for row in strikes_data:
                strike = {
                    "strike": float(row[0]) if row[0] else None,
                    "buffer": float(row[1]) if row[1] else None,
                    "buffer_pct": float(row[2]) if row[2] else None,
                    "probability": float(row[3]) if row[3] else None,
                    "yes_ask": int(row[4]) if row[4] else None,
                    "no_ask": int(row[5]) if row[5] else None,
                    "yes_diff": float(row[6]) if row[6] else None,
                    "no_diff": float(row[7]) if row[7] else None,
                    "volume": int(row[8]) if row[8] else None,
                    "ticker": row[9],
                    "active_side": row[10]
                }
                response["strikes"].append(strike)
            
            return response
            
    except Exception as e:
        return {"error": f"Error loading watchlist for {symbol} from PostgreSQL: {str(e)}"}

@app.get("/api/unified_ttc/{symbol}")
async def get_unified_ttc(symbol: str):
    """Get unified TTC data for a specific symbol from strike table"""
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
                SELECT ttc_seconds, event_ticker, market_title, market_status
                FROM live_data.strike_table_btc
                WHERE market_status = 'active'
                ORDER BY ttc_seconds ASC
                LIMIT 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result and result[0] is not None:
                ttc_seconds = int(result[0])
                return {
                    "ttc_seconds": ttc_seconds,
                    "event_ticker": result[1],
                    "market_title": result[2],
                    "market_status": result[3],
                    "symbol": symbol.upper()
                }
            else:
                return {
                    "ttc_seconds": 0,
                    "event_ticker": None,
                    "market_title": None,
                    "market_status": "no_active_markets",
                    "symbol": symbol.upper()
                }
    except Exception as e:
        return {"error": f"Error getting unified TTC: {str(e)}"}

@app.get("/api/failure_detector_status")
async def get_failure_detector_status():
    """Get the current status of the cascading failure detector."""
    try:
        from backend.cascading_failure_detector import CascadingFailureDetector
        detector = CascadingFailureDetector()
        return detector.generate_status_report()
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/auto_entry_indicator")
async def get_auto_entry_indicator():
    """Proxy endpoint to get auto entry indicator state from auto_entry_supervisor"""
    try:
        from backend.core.port_config import get_port
        port = get_port("auto_entry_supervisor")
        # Use localhost for internal service communication
        url = f"http://localhost:{port}/api/auto_entry_indicator"
        response = requests.get(url, timeout=2)
        if response.ok:
            return response.json()
        else:
            return {"error": f"Auto entry supervisor returned {response.status_code}"}
    except Exception as e:
        return {"error": f"Error getting auto entry indicator: {str(e)}"}

# Log event endpoint
from backend.util.trade_logger import log_trade_event, get_trade_logs

@app.get("/api/trade_logs")
async def get_trade_logs_endpoint(ticket_id: str = None, service: str = None, limit: int = 100):
    """Get trade logs from PostgreSQL"""
    try:
        logs = get_trade_logs(ticket_id=ticket_id, service=service, limit=limit)
        return {"status": "ok", "logs": logs}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/historical_price_data")
async def get_historical_price_data(symbol: str = "BTC", limit: int = 1000, start_date: str = None, end_date: str = None):
    """Get historical price data from PostgreSQL"""
    try:
        import psycopg2
        from datetime import datetime
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        # Build query
        query = """
            SELECT timestamp, open_price, high_price, low_price, close_price, volume, momentum
            FROM live_data.historical_price_data 
            WHERE symbol = %s
        """
        params = [symbol.upper()]
        
        # Add date filters if provided
        if start_date:
            query += " AND timestamp >= %s"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= %s"
            params.append(end_date)
        
        query += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)
        
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            
        conn.close()
        
        # Format results
        data = []
        for row in results:
            data.append({
                "timestamp": row[0].isoformat() if row[0] else None,
                "open": float(row[1]) if row[1] else None,
                "high": float(row[2]) if row[2] else None,
                "low": float(row[3]) if row[3] else None,
                "close": float(row[4]) if row[4] else None,
                "volume": float(row[5]) if row[5] else None,
                "momentum": float(row[6]) if row[6] else None
            })
        
        return {
            "status": "ok",
            "symbol": symbol.upper(),
            "count": len(data),
            "data": data
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/log_event")
async def log_event(request: Request):
    """Log trade events to PostgreSQL instead of text files"""
    try:
        data = await request.json()
        ticket_id = data.get("ticket_id", "UNKNOWN")
        message = data.get("message", "No message provided")

        # Log to PostgreSQL
        log_trade_event(ticket_id, message, service="main")

        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/notify_automated_trade")
async def notify_automated_trade(request: Request):
    """Receive automated trade notification and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        print(f"[MAIN] 🔔 Received automated trade notification: {data}")
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "automated_trade_triggered",
            "data": data
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        print(f"[MAIN] ✅ Automated trade notification broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Notification broadcasted"}
        
    except Exception as e:
        print(f"[MAIN] ❌ Error handling automated trade notification: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/notify_automated_close")
async def notify_automated_close(request: Request):
    """Receive automated trade close notification and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        print(f"[MAIN] 🔔 Received automated trade close notification: {data}")
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "automated_trade_closed",
            "data": data
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        print(f"[MAIN] ✅ Automated trade close notification broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Close notification broadcasted"}
        
    except Exception as e:
        print(f"[MAIN] ❌ Error handling automated trade close notification: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/broadcast_auto_entry_indicator")
async def broadcast_auto_entry_indicator(request: Request):
    """Receive auto entry indicator change and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        print(f"[MAIN] 🔔 Received auto entry indicator change: {data}")
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "auto_entry_indicator_change",
            "data": data
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        print(f"[MAIN] ✅ Auto entry indicator change broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Indicator change broadcasted"}
        
    except Exception as e:
        print(f"[MAIN] ❌ Error handling auto entry indicator change: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/broadcast_active_trades_change")
async def broadcast_active_trades_change(request: Request):
    """Receive active trades change and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        print(f"[MAIN] 🔔 Received active trades change: {data.get('count', 0)} trades")
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "active_trades_change",
            "data": data
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                print(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        print(f"[MAIN] ✅ Active trades change broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Active trades change broadcasted"}
        
    except Exception as e:
        print(f"[MAIN] ❌ Error handling active trades change: {e}")
        return {"success": False, "error": str(e)}

# Momentum and fingerprint now consolidated in strike table - no separate broadcast endpoints needed

@app.post("/api/notify_db_change")
async def notify_db_change(request: Request):
    """Handle database change notifications from kalshi_account_sync"""
    try:
        data = await request.json()
        db_name = data.get("db_name")
        timestamp = data.get("timestamp")
        change_data = data.get("change_data", {})
        
        print(f"📡 Received DB change notification: {db_name} at {timestamp}")
        
        # Broadcast to all connected WebSocket clients
        await broadcast_db_change(db_name, {
            "timestamp": timestamp,
            "change_data": change_data
        })
        
        return {"status": "ok", "message": f"Notification sent for {db_name}"}
    except Exception as e:
        print(f"❌ Error handling DB change notification: {e}")
        return {"status": "error", "message": str(e)}

# Authentication endpoints
@app.post("/api/auth/login")
async def login(request: Request):
    """Handle user login"""
    try:
        data = await request.json()
        username = data.get("username", "")
        password = data.get("password", "")
        remember_device = data.get("rememberDevice", False)
        
        # Get user credentials
        credentials = get_user_credentials()
        
        # Check credentials
        if username == credentials["username"]:
            # Check if we have a hashed password (PostgreSQL) or plain text (JSON fallback)
            if "password_hash" in credentials:
                # PostgreSQL authentication with hashed password
                if verify_password(password, credentials["password_hash"]):
                    auth_success = True
                else:
                    auth_success = False
            else:
                # JSON fallback with plain text password
                if password == credentials["password"]:
                    auth_success = True
                else:
                    auth_success = False
            
            if auth_success:
                # Generate authentication token
                token = generate_token()
                device_id = f"device_{secrets.token_hex(8)}"
                
                # Store token
                auth_tokens = load_auth_tokens()
                auth_tokens[token] = {
                    "username": username,
                    "created": datetime.now().isoformat(),
                    "expires": (datetime.now() + timedelta(days=30)).isoformat() if remember_device else (datetime.now() + timedelta(hours=24)).isoformat()
                }
                save_auth_tokens(auth_tokens)
                
                # Store device token if remember device
                if remember_device:
                    device_tokens = load_device_tokens()
                    device_tokens[device_id] = {
                        "username": username,
                        "token": token,
                        "created": datetime.now().isoformat(),
                        "expires": (datetime.now() + timedelta(days=365)).isoformat()
                    }
                    save_device_tokens(device_tokens)
                
                print(f"[AUTH] User {username} logged in successfully")
                return {
                    "success": True,
                    "token": token,
                    "deviceId": device_id,
                    "username": username,
                    "name": credentials["name"]
                }
            else:
                print(f"[AUTH] Failed login attempt for username: {username}")
                return {
                    "success": False,
                    "error": "Invalid username or password"
                }
        else:
            print(f"[AUTH] Failed login attempt for username: {username}")
            return {
                "success": False,
                "error": "Invalid username or password"
            }
    except Exception as e:
        print(f"[AUTH] Login error: {e}")
        return {
            "success": False,
            "error": "Authentication error"
        }

@app.post("/api/auth/verify")
async def verify_auth(request: Request):
    """Verify authentication token"""
    try:
        data = await request.json()
        token = data.get("token", "")
        device_id = data.get("deviceId", "")
        
        # Check for local development bypass
        if token.startswith("local_dev_"):
            return {"authenticated": True, "username": "local_dev", "name": "Local Development"}
        
        # Check auth tokens
        auth_tokens = load_auth_tokens()
        if token in auth_tokens:
            token_data = auth_tokens[token]
            expires = datetime.fromisoformat(token_data["expires"])
            
            if datetime.now() < expires:
                return {
                    "authenticated": True,
                    "username": token_data["username"],
                    "name": get_user_credentials()["name"]
                }
        
        # Check device tokens
        device_tokens = load_device_tokens()
        if device_id in device_tokens:
            device_data = device_tokens[device_id]
            expires = datetime.fromisoformat(device_data["expires"])
            
            if datetime.now() < expires:
                return {
                    "authenticated": True,
                    "username": device_data["username"],
                    "name": get_user_credentials()["name"]
                }
        
        return {"authenticated": False}
    except Exception as e:
        print(f"[AUTH] Verification error: {e}")
        return {"authenticated": False}

@app.post("/api/auth/logout")
async def logout(request: Request):
    """Handle user logout"""
    try:
        data = await request.json()
        token = data.get("token", "")
        device_id = data.get("deviceId", "")
        
        # Remove auth token
        auth_tokens = load_auth_tokens()
        if token in auth_tokens:
            del auth_tokens[token]
            save_auth_tokens(auth_tokens)
        
        # Remove device token
        device_tokens = load_device_tokens()
        if device_id in device_tokens:
            del device_tokens[device_id]
            save_device_tokens(device_tokens)
        
        print(f"[AUTH] User logged out successfully")
        return {"success": True}
    except Exception as e:
        print(f"[AUTH] Logout error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/user/info")
async def get_user_info():
    """Get current user information from database"""
    try:
        # Get user credentials from database
        credentials = get_user_credentials()
        
        return {
            "user_id": credentials.get("username"),
            "name": credentials.get("name"),
            "email": credentials.get("email"),
            "phone": credentials.get("phone"),
            "account_type": credentials.get("account_type")
        }
    except Exception as e:
        print(f"[USER INFO] Error getting user info: {e}")
        return {"error": "Failed to get user information"}

@app.post("/api/user/change-password")
async def change_password(request: Request):
    """Change user password"""
    try:
        data = await request.json()
        current_password = data.get("currentPassword", "")
        new_password = data.get("newPassword", "")
        
        # Get current password hash
        credentials = get_user_credentials()
        if not credentials or not credentials.get("password_hash"):
            return {"success": False, "error": "User not found"}
        
        # Verify current password
        if not verify_password(current_password, credentials["password_hash"]):
            return {"success": False, "error": "Current password is incorrect"}
        
        # Hash new password
        new_hash = change_password_hash(new_password)
        
        # Update in PostgreSQL
        import psycopg2
        conn = psycopg2.connect(host="localhost", database="rec_io_db", user="rec_io_user", password="rec_io_password")
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE users.user_info_0001 
                SET password_hash = %s
                WHERE user_no = '0001'
            """, (new_hash,))
            conn.commit()
        
        return {"success": True, "message": "Password updated successfully"}
    except Exception as e:
        print(f"[AUTH] Error changing password: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/system/health")
async def get_system_health():
    """Get current system health status from database"""
    try:
        import psycopg2
        
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM system.health_status WHERE id = 1")
            result = cursor.fetchone()
            
            if result:
                # Unpack the result (adjust column order as needed)
                id, overall_status, cpu_percent, memory_percent, disk_percent, \
                database_status, supervisor_status, services_healthy, services_total, \
                failed_services, health_details, timestamp = result
                
                return {
                    "overall_status": overall_status,
                    "cpu_percent": float(cpu_percent) if cpu_percent else None,
                    "memory_percent": float(memory_percent) if memory_percent else None,
                    "disk_percent": float(disk_percent) if disk_percent else None,
                    "database_status": database_status,
                    "supervisor_status": supervisor_status,
                    "services_healthy": services_healthy,
                    "services_total": services_total,
                    "failed_services": failed_services or [],
                    "timestamp": timestamp.isoformat() if timestamp else None
                }
            else:
                return {"error": "No health data available"}
                
    except Exception as e:
        print(f"[SYSTEM HEALTH] Error getting system health: {e}")
        return {"error": "Failed to get system health information"}

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Called when the application starts."""
    print(f"[MAIN] 🚀 Main app started on centralized port {MAIN_APP_PORT}")

@app.on_event("shutdown")
async def shutdown_event():
    """Called when the application shuts down."""
    print("[MAIN] 🛑 Main app shutting down")
    # No port release needed for static ports

@app.post("/api/admin/supervisor-status")
async def get_supervisor_status():
    """Execute supervisorctl status command and return output"""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root, get_supervisorctl_path, get_supervisor_config_path
        
        # Get dynamic paths
        project_dir = get_dynamic_project_root()
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()
        
        # Change to the project directory
        os.chdir(project_dir)
        
        # Set up environment
        env = os.environ.copy()
        
        # Execute the supervisorctl command with dynamic paths
        result = subprocess.run(
            [supervisorctl_path, "-c", supervisor_config_path, "status"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            cwd=project_dir
        )
        
        # supervisorctl returns non-zero exit codes when any process is stopped
        # but the output is still valid, so we should return success if we got output
        if result.stdout.strip():
            return {
                "success": True,
                "output": result.stdout
            }
        else:
            return {
                "success": False,
                "error": f"Command failed with return code {result.returncode}",
                "output": result.stderr
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Command timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/admin/execute-restart")
async def execute_restart():
    """Execute the restart script in background"""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root
        
        # Get dynamic project directory
        project_dir = get_dynamic_project_root()
        os.chdir(project_dir)
        
        # Set up environment with proper PATH
        env = os.environ.copy()
        # Add common paths for both macOS and Ubuntu
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
        
        # Execute the restart script in background (don't wait for it)
        subprocess.Popen(
            ["/bin/bash", "./scripts/restart"],
            cwd=project_dir,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        # Return immediately - the script will run in background
        return {
            "success": True,
            "message": "Restart script initiated in background"
        }
            
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/admin/execute-command")
async def execute_command(request: dict):
    """Execute arbitrary command at project level"""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root, get_supervisorctl_path, get_supervisor_config_path
        
        command = request.get("command", "")
        if not command:
            return {"success": False, "error": "No command provided"}
        
        # Get dynamic project directory and supervisor paths
        project_dir = get_dynamic_project_root()
        supervisorctl_path = get_supervisorctl_path()
        supervisor_config_path = get_supervisor_config_path()
        
        os.chdir(project_dir)
        
        # Set up environment with proper PATH
        env = os.environ.copy()
        # Add common paths for both macOS and Ubuntu
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
        
        # Check if this is a supervisorctl command
        if command.startswith('supervisorctl'):
            # Parse the supervisorctl command
            parts = command.split()
            if len(parts) >= 2:
                action = parts[1]  # restart, status, etc.
                if len(parts) >= 3:
                    script_name = parts[2]  # script name
                    # Execute with proper supervisor configuration
                    result = subprocess.run(
                        [supervisorctl_path, "-c", supervisor_config_path, action, script_name],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=env,
                        cwd=project_dir
                    )
                else:
                    # No script name specified (e.g., "supervisorctl status")
                    result = subprocess.run(
                        [supervisorctl_path, "-c", supervisor_config_path, action],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env=env,
                        cwd=project_dir
                    )
            else:
                return {"success": False, "error": "Invalid supervisorctl command"}
        else:
            # Execute other commands normally
            # Use longer timeout for backup operations
            timeout = 300 if 'package_user_data.sh' in command else 30
            
            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=project_dir
            )
        
        if result.returncode == 0:
            return {"success": True, "output": result.stdout}
        else:
            return {"success": False, "error": f"Command failed with return code {result.returncode}", "output": result.stderr}
            
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 5 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/admin/get-log-stream")
async def get_log_stream(request: dict):
    """Stream log output for a specific script."""
    from fastapi.responses import StreamingResponse
    import subprocess
    import os
    
    script_name = request.get("script", "")
    log_type = request.get("logType", "out")
    
    if not script_name:
        return {"success": False, "error": "No script name provided"}
    
    # Determine log file path based on script name and type
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    if log_type == "combined":
        # For combined view, we'll need to handle multiple files
        log_files = []
        for suffix in [".out.log", ".err.log", ".log"]:
            potential_file = f"logs/{script_name}{suffix}"
            if os.path.exists(os.path.join(project_dir, potential_file)):
                log_files.append(potential_file)
        
        if not log_files:
            return {"success": False, "error": f"No log files found for {script_name}"}
        
        # Use the first available file for now (we can enhance this later)
        log_file = log_files[0]
    else:
        # For specific log types
        log_file = f"logs/{script_name}.{log_type}.log"
        if not os.path.exists(os.path.join(project_dir, log_file)):
            # Fallback to .log if specific type doesn't exist
            log_file = f"logs/{script_name}.log"
        
        # For auto_entry_supervisor, prioritize the dedicated .log file over .out.log
        if script_name == "auto_entry_supervisor" and log_type == "out":
            dedicated_log = f"logs/{script_name}.log"
            if os.path.exists(os.path.join(project_dir, dedicated_log)):
                log_file = dedicated_log
    
    if not os.path.exists(os.path.join(project_dir, log_file)):
        return {"success": False, "error": f"Log file not found: {log_file}"}
    
    def generate_log_stream():
        try:
            # Set up environment with proper PATH
            env = os.environ.copy()
            env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
            
            # First, get the last 100 lines of the log file
            try:
                result = subprocess.run(
                    ["/usr/bin/tail", "-n", "100", log_file],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=project_dir,
                    env=env
                )
                if result.returncode == 0 and result.stdout:
                    # Send the last 100 lines first
                    yield "=== Last 100 lines of log ===\n"
                    yield result.stdout
                    yield "\n=== Live tail starting ===\n"
            except Exception as e:
                yield f"Warning: Could not read existing log content: {str(e)}\n"
                yield "=== Starting live tail ===\n"
            
            # Start tail -f process with unbuffered output for real-time streaming
            process = subprocess.Popen(
                ["stdbuf", "-oL", "/usr/bin/tail", "-f", log_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=project_dir,
                env=env,
                bufsize=0  # Unbuffered
            )
            
            # Stream live output with immediate flushing
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                yield line
                # Force flush to ensure immediate transmission
                import sys
                if hasattr(sys.stdout, 'flush'):
                    sys.stdout.flush()
            
        except Exception as e:
            yield f"Error: {str(e)}\n"
        finally:
            if 'process' in locals():
                process.terminate()
    
    return StreamingResponse(
        generate_log_stream(),
        media_type="text/plain",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

@app.post("/api/admin/create-backup")
async def create_backup():
    """Create a database backup using the package_user_data.sh script."""
    try:
        import subprocess
        import os
        from backend.util.paths import get_dynamic_project_root
        
        # Get project directory
        project_dir = get_dynamic_project_root()
        
        # Set up environment with proper PATH
        env = os.environ.copy()
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin'
        
        # Execute the backup script
        result = subprocess.run(
            ['bash', 'scripts/package_user_data.sh'],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minutes timeout for backup
            env=env,
            cwd=project_dir
        )
        
        if result.returncode == 0:
            # Parse the output to find the backup file
            output = result.stdout
            backup_match = output.find('user_data_package_')
            if backup_match != -1:
                # Extract the backup filename from the output
                lines = output.split('\n')
                for line in lines:
                    if 'user_data_package_' in line and '.tar.gz' in line:
                        backup_file = line.strip()
                        if backup_file.endswith('.tar.gz'):
                            backup_path = os.path.join(project_dir, 'backup', backup_file)
                            if os.path.exists(backup_path):
                                return {
                                    "success": True, 
                                    "output": output,
                                    "backup_file": backup_file,
                                    "backup_path": backup_path
                                }
            
            return {"success": True, "output": output}
        else:
            return {
                "success": False, 
                "error": f"Backup script failed with return code {result.returncode}",
                "output": result.stderr
            }
            
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Backup timed out after 2 minutes"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/admin/download-file")
async def download_file(request: dict):
    """Download a file from the server."""
    try:
        import os
        from fastapi.responses import FileResponse
        from pathlib import Path
        
        file_path = request.get("file_path", "")
        if not file_path:
            return {"success": False, "error": "No file path provided"}
        
        # Security check: ensure the file is within the project directory
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_path = os.path.abspath(file_path)
        
        if not file_path.startswith(project_dir):
            return {"success": False, "error": "Access denied: File path outside project directory"}
        
        if not os.path.exists(file_path):
            return {"success": False, "error": "File not found"}
        
        if not os.path.isfile(file_path):
            return {"success": False, "error": "Path is not a file"}
        
        # Return the file for download
        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type='application/octet-stream'
        )
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/admin/download-file")
async def download_file_get(file: str):
    """Download a file from the server via GET request."""
    try:
        import os
        from fastapi.responses import FileResponse
        from pathlib import Path
        
        if not file:
            return {"success": False, "error": "No file name provided"}
        
        # Security check: ensure the file is within the backup directory
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        backup_dir = os.path.join(project_dir, 'backup')
        file_path = os.path.join(backup_dir, file)
        file_path = os.path.abspath(file_path)
        
        # Ensure the file is within the backup directory
        if not file_path.startswith(backup_dir):
            return {"success": False, "error": "Access denied: File path outside backup directory"}
        
        if not os.path.exists(file_path):
            return {"success": False, "error": "File not found"}
        
        if not os.path.isfile(file_path):
            return {"success": False, "error": "Path is not a file"}
        
        # Return the file for download
        return FileResponse(
            path=file_path,
            filename=file,
            media_type='application/octet-stream'
        )
        
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/portfolio/current")
async def get_current_portfolio():
    """Get the current portfolio value from PostgreSQL"""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT portfolio
                FROM users.account_balance_0001 
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            
            result = cursor.fetchone()
            
        conn.close()
        
        if result:
            portfolio_value = float(result[0]) / 100  # Convert cents to dollars
            return {
                "status": "ok",
                "portfolio": portfolio_value
            }
        else:
            return {
                "status": "error",
                "message": "No portfolio data found"
            }
        
    except Exception as e:
        print(f"Error getting current portfolio: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/portfolio/history")
async def get_portfolio_history(period: str = "1m"):
    """Get historical portfolio data from PostgreSQL for charting"""
    try:
        import psycopg2
        from datetime import datetime, timedelta
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
        
        # Calculate time range based on period
        now = datetime.now()
        if period == "1d":
            # For 1D, start at 05:00 on current day
            today_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
            
            # Get the last value before 05:00 today to use as starting point
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT timestamp, portfolio
                    FROM users.account_balance_0001 
                    WHERE timestamp < %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (today_5am.strftime('%Y-%m-%d %H:%M:%S'),))
                
                last_before_5am = cursor.fetchone()
            
            # Get all data from 05:00 today onwards
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT timestamp, portfolio
                    FROM users.account_balance_0001 
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (today_5am.strftime('%Y-%m-%d %H:%M:%S'),))
                
                results = cursor.fetchall()
            
            # If we have a last value before 5am, prepend it to the results
            if last_before_5am:
                results = [last_before_5am] + list(results)
                
        elif period == "1w":
            start_time = now - timedelta(weeks=1)
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT timestamp, portfolio
                    FROM users.account_balance_0001 
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                
                results = cursor.fetchall()
        elif period == "1m":
            start_time = now - timedelta(days=30)
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT timestamp, portfolio
                    FROM users.account_balance_0001 
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                
                results = cursor.fetchall()
        elif period == "1y":
            start_time = now - timedelta(days=365)
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT timestamp, portfolio
                    FROM users.account_balance_0001 
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                
                results = cursor.fetchall()
        else:  # "All"
            start_time = datetime(2020, 1, 1)  # Default start date
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT timestamp, portfolio
                    FROM users.account_balance_0001 
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                
                results = cursor.fetchall()
            
        conn.close()
        
        # Format results for charting
        data = []
        for row in results:
            timestamp, portfolio = row
            data.append({
                "timestamp": timestamp if timestamp else None,
                "portfolio": float(portfolio) / 100 if portfolio else 0  # Convert cents to dollars
            })
        
        return {
            "status": "ok",
            "period": period,
            "count": len(data),
            "data": data
        }
        
    except Exception as e:
        print(f"Error getting portfolio history: {e}")
        return {"status": "error", "message": str(e)}

# Main entry point
if __name__ == "__main__":
    print(f"[MAIN] 🚀 Launching app on centralized port {MAIN_APP_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=MAIN_APP_PORT)

