"""
MAIN APPLICATION - UNIVERSAL CENTRALIZED PORT SYSTEM
Uses the single centralized port configuration system.
"""

import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import json
import asyncio
from contextlib import asynccontextmanager
import time
from datetime import datetime, timedelta
import pytz
import requests
import sqlite3
import psycopg2
from psycopg2 import sql
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
from backend.core.config.database import get_postgresql_connection, get_database_config
unified_config = UnifiedConfigManager()

# Get port from centralized system
MAIN_APP_PORT = get_port("main_app")
ACTIVE_TRADE_SUPERVISOR_PORT = get_port("active_trade_supervisor")

# Logging: EST, flush, single handler to stdout (supervisor captures)
from zoneinfo import ZoneInfo as _main_tz

def _main_est_formatter():
    class _ESTF(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            from datetime import datetime
            dt = datetime.fromtimestamp(record.created, tz=_main_tz("America/New_York"))
            s = dt.strftime("%Y-%m-%dT%H:%M:%S")
            z = dt.strftime("%z")
            return s + (z[:3] + ":" + z[3:] if len(z) >= 5 else z)
    return _ESTF(fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s")

class _MainFlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

def _configure_main_logging():
    logr = logging.getLogger("main_app")
    if logr.handlers:
        return logr
    import sys
    h = _MainFlushHandler(sys.stdout)
    h.setFormatter(_main_est_formatter())
    logr.addHandler(h)
    logr.setLevel(logging.INFO)
    return logr

_main_logger = _configure_main_logging()
_main_logger.info("Using centralized port %s (ATS port %s)", MAIN_APP_PORT, ACTIVE_TRADE_SUPERVISOR_PORT)

# Import centralized path utilities
from backend.util.paths import get_data_dir, get_trade_history_dir, get_accounts_data_dir
from backend.account_mode import get_account_mode

# Global set of connected websocket clients for preferences
connected_clients = set()

# Global set of connected websocket clients for database changes
db_change_clients = set()

# Global set of connected websocket clients for unified frontend updates


# Legacy preference path removed - all data now in PostgreSQL

# Global preferences cache
_preferences_cache = None
_cache_timestamp = 0
CACHE_TTL = 1.0  # 1 second cache TTL

# LEGACY REMOVED: update_auto_trade_settings_postgresql function - now using strategy_list table directly

# LEGACY REMOVED: get_auto_trade_settings_postgresql function - now using strategy_list table directly

# LEGACY REMOVED: get_auto_stop_settings_postgresql function - now using strategy_list table directly

# Legacy trade_preferences functions removed - all position sizing and strategy now handled by monitor_list table

# Legacy calculate_total_position function removed - position sizing now handled by monitor_list table

# Legacy update_total_position function removed - position sizing now handled by monitor_list table

# Legacy get_trade_preferences_postgresql function removed - all position sizing and strategy now handled by monitor_list table

# LEGACY REMOVED: get_all_preferences_postgresql function - now using strategy-specific endpoints

def get_trade_history_preferences_postgresql():
    """Get trade history preferences from PostgreSQL"""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            select_full = """
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       day_sunday, day_monday, day_tuesday, day_wednesday, day_thursday, day_friday, day_saturday,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp, chart_view, pct_mode,
                       live_filter, paper_filter,
                       COALESCE(strategy_selection, '{}'::jsonb),
                       COALESCE(symbol_selection, '{}'::jsonb)
                FROM users.trade_history_preferences_0001 WHERE id = 1
            """
            select_with_strategy = """
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       day_sunday, day_monday, day_tuesday, day_wednesday, day_thursday, day_friday, day_saturday,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp, chart_view, pct_mode,
                       live_filter, paper_filter,
                       COALESCE(strategy_selection, '{}'::jsonb)
                FROM users.trade_history_preferences_0001 WHERE id = 1
            """
            select_without_strategy = """
                SELECT date_filter, start_date, end_date, win_filter, loss_filter,
                       contract_9am, contract_10am, contract_11am, contract_12am,
                       contract_1pm, contract_2pm, contract_3pm, contract_4pm,
                       contract_5pm, contract_6pm, contract_7pm, contract_8pm,
                       contract_9pm, contract_10pm, contract_11pm,
                       symbol_btc, symbol_eth, symbol_spy, symbol_ndx, symbol_usd_eur,
                       strategy_hourly_htc, strategy_momentum_scalp, strategy_test,
                       day_sunday, day_monday, day_tuesday, day_wednesday, day_thursday, day_friday, day_saturday,
                       analysis_interval, sort_key, sort_asc, page_size, last_search_timestamp, chart_view, pct_mode,
                       live_filter, paper_filter
                FROM users.trade_history_preferences_0001 WHERE id = 1
            """
            result = None
            has_strategy_col = False
            has_symbol_col = False
            try:
                cursor.execute(select_full)
                result = cursor.fetchone()
                has_strategy_col = result is not None and len(result) > 44
                has_symbol_col = result is not None and len(result) > 45
            except psycopg2.ProgrammingError:
                try:
                    cursor.execute(select_with_strategy)
                    result = cursor.fetchone()
                    has_strategy_col = result is not None and len(result) > 44
                except psycopg2.ProgrammingError:
                    cursor.execute(select_without_strategy)
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
                    "day_sunday": result[28],
                    "day_monday": result[29],
                    "day_tuesday": result[30],
                    "day_wednesday": result[31],
                    "day_thursday": result[32],
                    "day_friday": result[33],
                    "day_saturday": result[34],
                    "analysis_interval": result[35],
                    "sort_key": result[36],
                    "sort_asc": result[37],
                    "page_size": result[38],
                    "last_search_timestamp": result[39],
                    "chart_view": result[40],
                    "pct_mode": result[41],
                    "live_filter": result[42] if len(result) > 42 else True,
                    "paper_filter": result[43] if len(result) > 43 else False,
                    "strategy_selection": result[44] if has_strategy_col else {},
                    "symbol_selection": result[45] if has_symbol_col else {}
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
                    "day_sunday": True,
                    "day_monday": True,
                    "day_tuesday": True,
                    "day_wednesday": True,
                    "day_thursday": True,
                    "day_friday": True,
                    "day_saturday": True,
                    "analysis_interval": "daily",
                    "sort_key": None,
                    "sort_asc": True,
                    "page_size": 50,
                    "last_search_timestamp": int(time.time()),
                    "chart_view": "pnl",
                    "live_filter": True,
                    "paper_filter": False,
                    "strategy_selection": {},
                    "symbol_selection": {}
                }
    except Exception as e:
        _main_logger.warning(f"[PostgreSQL Error] Failed to get trade history preferences: {e}")
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
            "last_search_timestamp": int(time.time()),
            "chart_view": "pnl",
            "live_filter": True,
            "paper_filter": False,
            "strategy_selection": {},
            "symbol_selection": {}
        }

def update_trade_history_preferences_postgresql(**kwargs):
    """Update trade history preferences in PostgreSQL using UPSERT"""
    try:
        conn = get_postgresql_connection()
        if not conn:
            return
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
            _main_logger.debug(f"[PostgreSQL] Updated trade history preferences: {kwargs}")
        
        conn.close()
    except Exception as e:
        _main_logger.warning(f"[PostgreSQL Error] Failed to update trade history preferences: {e}")

# Authentication system
AUTH_TOKENS_FILE = os.path.join(get_data_dir(), "users", "user_0001", "auth_tokens.json")
DEVICE_TOKENS_FILE = os.path.join(get_data_dir(), "users", "user_0001", "device_tokens.json")

# Authentication settings - respect environment variable
AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() == "true"
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
        _main_logger.warning(f"[AUTH] Error saving auth tokens: {e}")

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
        _main_logger.warning(f"[AUTH] Error saving device tokens: {e}")

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
        conn = get_postgresql_connection()
        if not conn:
            raise Exception("Database connection failed")
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
        _main_logger.warning(f"[AUTH] Error loading user credentials from PostgreSQL: {e}")
    
    # Fallback to JSON file only when not in production
    if os.getenv("REC_ENVIRONMENT") != "production":
        try:
            user_info_path = os.path.join(get_data_dir(), "users", "user_0001", "user_info.json")
            if os.path.exists(user_info_path):
                with open(user_info_path, "r") as f:
                    user_info = json.load(f)
                    return {
                        "username": user_info.get("user_id", "admin"),
                        "password": user_info.get("password", "admin"),
                        "name": user_info.get("name", "Admin User")
                    }
        except Exception as e:
            _main_logger.warning(f"[AUTH] Error loading user credentials from JSON: {e}")
    
    # Default credentials if nothing works (dev only)
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
        _main_logger.debug(f"[AUTH] Password verification error: {e}")
        return False

def change_password_hash(password):
    """Hash a password for storage. Requires bcrypt; no plaintext fallback."""
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    except ImportError:
        _main_logger.debug(f"[AUTH] bcrypt required for password hashing")
        raise ValueError("bcrypt is required for password hashing")
    except Exception as e:
        _main_logger.debug(f"[AUTH] Password hashing error: {e}")
        raise

def load_preferences():
    global _preferences_cache, _cache_timestamp
    current_time = time.time()
    
    # Return cached version if still valid
    if _preferences_cache is not None and (current_time - _cache_timestamp) < CACHE_TTL:
        return _preferences_cache.copy()
    
    # Load from PostgreSQL - now using strategy-specific endpoints
    try:
        # Default preferences - auto settings now handled by strategy-specific endpoints
        default_prefs = {"diff_mode": False, "position_size": 1, "multiplier": 1}
        
        # Update cache
        _preferences_cache = default_prefs
        _cache_timestamp = current_time
        return default_prefs
    except Exception as e:
        _main_logger.warning(f"[Preferences Load Error] {e}")
        # Default preferences
        default_prefs = {"diff_mode": False, "position_size": 1, "multiplier": 1}
        _preferences_cache = default_prefs
        _cache_timestamp = current_time
        return default_prefs

async def save_preferences(prefs):
    global _preferences_cache, _cache_timestamp
    try:
        # Auto settings now handled by strategy-specific endpoints
        # Only handle non-auto settings here
        
        # Update cache
        _preferences_cache = prefs.copy()
        _cache_timestamp = time.time()
        _main_logger.debug(f"[Preferences] ✅ Updated cache: {list(prefs.keys())}")
    except Exception as e:
        _main_logger.warning(f"[Preferences Save Error] {e}")

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
        _main_logger.warning(f"[Broadcast Preferences Error] {e}")

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

# Lifespan: startup/shutdown (replaces deprecated on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown; use instead of on_event for FastAPI compatibility."""
    _main_logger.info("Main app started on port %s", MAIN_APP_PORT)
    yield
    _main_logger.info("Main app shutting down")

# Create FastAPI app
app = FastAPI(title="Trading System Main App", lifespan=lifespan)

# Import universal host system
from backend.util.paths import get_host

# Configure CORS with universal host origins
host = get_host()
_explicit_origins = [
    f"http://{host}:{MAIN_APP_PORT}",
    f"http://localhost:{MAIN_APP_PORT}",
    f"http://127.0.0.1:{MAIN_APP_PORT}",
    f"https://{host}:{MAIN_APP_PORT}",
    f"https://localhost:{MAIN_APP_PORT}",
    f"https://127.0.0.1:{MAIN_APP_PORT}",
    "https://rec-io.com",
    "https://www.rec-io.com",
    "http://rec-io.com",
    "http://www.rec-io.com",
]
origins = _explicit_origins if os.getenv("REC_ENVIRONMENT") == "production" else _explicit_origins + ["*"]

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
        _main_logger.debug(f"[WEBSOCKET] ✅ Client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        _main_logger.debug(f"[WEBSOCKET] ❌ Client disconnected. Total clients: {len(self.active_connections)}")

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
        connected_clients.discard(websocket)

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
    _main_logger.debug(f"[AUTH] AUTH_ENABLED = {AUTH_ENABLED}")
    if AUTH_ENABLED:
        # Always redirect to login - no direct access to main app
        _main_logger.debug(f"[AUTH] Redirecting to login page")
        return RedirectResponse(url="/login")
    else:
        # Local development mode - serve main app directly
        _main_logger.debug(f"[AUTH] Serving main app directly (local development)")
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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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

# Serve mobile dashboard with cache busting
@app.get("/mobile/dashboard", response_class=HTMLResponse)
async def serve_mobile_dashboard(request: Request):
    """Serve mobile dashboard with cache busting headers."""
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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
            return RedirectResponse(url="/login")
    
    file_path = f"{frontend_dir}/mobile/dashboard_mobile.html"
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
        return HTMLResponse(content="Mobile dashboard not found", status_code=404)

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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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

# Test route for monitor history display
@app.get("/test_monitor_history_display.html", response_class=HTMLResponse)
async def serve_test_monitor_history_display():
    """Serve the test page for monitor history display."""
    file_path = f"{frontend_dir}/test_monitor_history_display.html"
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
        return HTMLResponse(content="Test page not found", status_code=404)

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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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
            _main_logger.warning(f"[AUTH] Error verifying token: {e}")
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
        _main_logger.warning(f"Error calculating TTC: {e}")
        return {"error": str(e)}

@app.get("/api/ttc")
async def get_ttc_data():
    """Get time to close data directly from PostgreSQL."""
    return get_ttc_data_from_postgresql()

# Core data endpoint
@app.get("/core")
async def get_core_data(symbol: str = "BTC"):
    """Get core trading data for specified symbol."""
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
            _main_logger.warning(f"Error getting TTC from PostgreSQL: {e}")
            # Fallback calculation
            close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)
            if now.time() >= close_time.time():
                close_time += timedelta(days=1)
            ttc_seconds = int((close_time - now).total_seconds())
        
        # Get BTC price from PostgreSQL live_data
        btc_price = 0
        try:
            # Get the latest price from PostgreSQL live_data.live_price_log_1s_btc
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT price FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1")
            result = cursor.fetchone()
            conn.close()
            
            if result:
                btc_price = float(result[0])
                _main_logger.debug(f"[MAIN] Using PostgreSQL BTC price: ${btc_price:,.2f}")
            else:
                # Fallback to direct API call if no PostgreSQL data
                response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    btc_price = float(data['result']['XXBTZUSD']['c'][0])
                    _main_logger.debug(f"[MAIN] Using fallback API BTC price: ${btc_price:,.2f}")
        except Exception as e:
            _main_logger.warning(f"Error fetching BTC price from PostgreSQL: {e}")
            # Final fallback to direct API call
            try:
                response = requests.get("https://api.kraken.com/0/public/Ticker?pair=BTCUSD", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    btc_price = float(data['result']['XXBTZUSD']['c'][0])
                    _main_logger.debug(f"[MAIN] Using emergency fallback API BTC price: ${btc_price:,.2f}")
            except Exception as e2:
                _main_logger.warning(f"Emergency fallback also failed: {e2}")
        
        # Get momentum data directly from PostgreSQL
        momentum_data = {}
        try:
            conn = get_postgresql_connection()
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg,
                       move_1m, move_2m, move_3m, move_4m, movement, movement_percentile
                FROM live_data.live_price_log_1s_{symbol.lower()}
                ORDER BY timestamp DESC
                LIMIT 1
            """)
            result = cursor.fetchone()
            conn.close()
            
            if result:
                (momentum, delta_1m, delta_2m, delta_3m, delta_4m, delta_15m, delta_30m, momentum_percentile, momentum_5s_avg,
                 move_1m, move_2m, move_3m, move_4m, movement, movement_percentile) = result
                momentum_data = {
                    'weighted_momentum_score': float(momentum) if momentum is not None else 0.0,
                    'delta_1m': float(delta_1m) if delta_1m is not None else None,
                    'delta_2m': float(delta_2m) if delta_2m is not None else None,
                    'delta_3m': float(delta_3m) if delta_3m is not None else None,
                    'delta_4m': float(delta_4m) if delta_4m is not None else None,
                    'delta_15m': float(delta_15m) if delta_15m is not None else None,
                    'delta_30m': float(delta_30m) if delta_30m is not None else None,
                    'momentum_percentile': float(momentum_percentile) if momentum_percentile is not None else None,
                    'momentum_5s_avg': float(momentum_5s_avg) if momentum_5s_avg is not None else None,
                    'move_1m': float(move_1m) if move_1m is not None else None,
                    'move_2m': float(move_2m) if move_2m is not None else None,
                    'move_3m': float(move_3m) if move_3m is not None else None,
                    'move_4m': float(move_4m) if move_4m is not None else None,
                    'movement': float(movement) if movement is not None else None,
                    'movement_percentile': float(movement_percentile) if movement_percentile is not None else None,
                }
                _main_logger.debug(f"[MAIN] Momentum analysis: {momentum_data.get('weighted_momentum_score', 'N/A'):.4f}%")
            else:
                momentum_data = {
                    'delta_1m': None,
                    'delta_2m': None,
                    'delta_3m': None,
                    'delta_4m': None,
                    'delta_15m': None,
                    'delta_30m': None,
                    'weighted_momentum_score': None,
                    'move_1m': None, 'move_2m': None, 'move_3m': None, 'move_4m': None,
                    'movement': None, 'movement_percentile': None,
                }
        except Exception as e:
            _main_logger.warning(f"Error getting momentum data from PostgreSQL: {e}")
            momentum_data = {
                'delta_1m': None,
                'delta_2m': None,
                'delta_3m': None,
                'delta_4m': None,
                'delta_15m': None,
                'delta_30m': None,
                'weighted_momentum_score': None,
                'move_1m': None, 'move_2m': None, 'move_3m': None, 'move_4m': None,
                'movement': None, 'movement_percentile': None,
            }
        
        # Get latest database price from PostgreSQL
        latest_db_price = 0
        try:
            conn = get_postgresql_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT buy_price FROM users.trades_0001 WHERE test_filter IS NULL OR test_filter = FALSE ORDER BY date DESC, time DESC LIMIT 1")
                result = cursor.fetchone()
                if result:
                    latest_db_price = result[0]
            conn.close()
        except Exception as e:
            _main_logger.warning(f"Error getting latest DB price: {e}")
        
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
            _main_logger.warning(f"Error getting Kraken changes: {e}")
        
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
        _main_logger.warning(f"Error in core data: {e}")
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
        _main_logger.warning(f"Error reading Kalshi credentials: {e}")
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
        conn = get_postgresql_connection()
        
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
        _main_logger.warning(f"Error getting trades from PostgreSQL: {e}")
        return []

@app.get("/trades/{trade_id}")
async def get_trade(trade_id: int):
    """Forward trade GET request to trade_manager."""
    try:
        # Get trade_manager port from centralized system
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades/{trade_id}"
        
        _main_logger.debug(f"[MAIN] Forwarding trade GET request to trade_manager at {trade_manager_url}")
        
        # Forward the request to trade_manager
        response = requests.get(
            trade_manager_url,
            timeout=10
        )
        
        if response.status_code == 200:
            _main_logger.debug(f"[MAIN] ✅ Trade GET request forwarded successfully to trade_manager")
            return response.json()
        else:
            _main_logger.warning(f"[MAIN] ❌ Trade GET request forwarding failed: {response.status_code}")
            return {"error": f"Trade manager returned status {response.status_code}"}
            
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error forwarding trade GET request: {e}")
        return {"error": str(e)}

@app.post("/trades")
async def create_trade(trade_data: dict):
    """Forward trade ticket to trade_manager."""
    try:
        # Get trade_manager port from centralized system
        trade_manager_port = get_port("trade_manager")
        trade_manager_url = f"http://{get_host()}:{trade_manager_port}/trades"
        
        _main_logger.debug(f"[MAIN] Forwarding trade ticket to trade_manager at {trade_manager_url}")
        
        # Forward the request to trade_manager
        response = requests.post(
            trade_manager_url,
            json=trade_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 201:
            _main_logger.debug(f"[MAIN] ✅ Trade ticket forwarded successfully to trade_manager")
            return response.json()
        else:
            _main_logger.warning(f"[MAIN] ❌ Trade ticket forwarding failed: {response.status_code}")
            return {"error": f"Trade manager returned status {response.status_code}"}
            
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error forwarding trade ticket: {e}")
        return {"error": str(e)}

# Additional endpoints for other data
@app.get("/btc_price_changes")
async def get_btc_changes():
    """Get BTC price changes from PostgreSQL live_data.price_change_btc."""
    try:
        import psycopg2
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        conn = get_postgresql_connection()
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
        _main_logger.warning(f"[btc_price_changes API] Error reading from PostgreSQL: {e}")
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": None}

@app.get("/eth_price_changes")
async def get_eth_changes():
    """Get ETH price changes from PostgreSQL live_data.price_change_eth."""
    try:
        import psycopg2
        from datetime import datetime
        from zoneinfo import ZoneInfo
        
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        
        # Get latest price changes from the database
        cursor.execute("""
            SELECT change1h, change3h, change1d, timestamp 
            FROM live_data.price_change_eth 
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
        _main_logger.warning(f"[eth_price_changes API] Error reading from PostgreSQL: {e}")
        return {"change1h": None, "change3h": None, "change1d": None, "timestamp": None}

@app.get("/kalshi_market_snapshot")
async def get_kalshi_snapshot():
    """Get Kalshi market snapshot from PostgreSQL."""
    try:
        import psycopg2
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
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
                FROM live_data.market_kalshi_hourly_btc
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
        _main_logger.warning(f"Error getting Kalshi snapshot from PostgreSQL: {e}")
        return {"markets": []}

# API endpoints for account data
@app.post("/api/account/sync")
async def trigger_account_sync():
    """Trigger a full account retrieval cycle from kalshi_account_sync (balance, subaccounts, account history). Runs in background; returns immediately."""
    import threading
    def _run_sync():
        try:
            from backend.kalshi_account_sync_ws import sync_balance
            sync_balance()
        except Exception as e:
            _main_logger.warning(f"account/sync: sync_balance failed: {e}")
    threading.Thread(target=_run_sync, daemon=True).start()
    return {"ok": True}

@app.get("/api/account/balance")
async def get_account_balance(mode: str = "prod"):
    """Get account balance from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get the latest account balance
            cursor.execute("""
                SELECT portfolio, positions, bankroll_current, timestamp 
                FROM users.account_balance_0001 
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            balance_result = cursor.fetchone()
            
            
            conn.close()
            
            if balance_result:
                portfolio_value = balance_result['portfolio']
                positions_value = balance_result['positions'] if balance_result else 0
                bankroll_current = balance_result['bankroll_current'] if balance_result else 0
                return {
                    "portfolio": portfolio_value,
                    "positions": positions_value,
                    "bankroll_current": bankroll_current
                }
            else:
                return {"portfolio": 0, "positions": 0, "bankroll_current": 0}
            
    except Exception as e:
        _main_logger.warning(f"Error getting account balance from PostgreSQL: {e}")
        return {"portfolio": 0, "positions": 0}

@app.get("/api/subaccounts")
async def get_subaccounts():
    """Get subaccounts (users.subaccounts_0001) for display. Balances in cents."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = get_postgresql_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT id, subaccount, balance, base_value, realized_pnl, realized_pnl_pct,
                       target_pnl__pct, transfer_amt, automatic_transfers
                FROM users.subaccounts_0001
                ORDER BY id
            """)
            rows = cursor.fetchall()
        conn.close()
        return {"subaccounts": [dict(r) for r in rows]}
    except Exception as e:
        _main_logger.warning(f"Error getting subaccounts from PostgreSQL: {e}")
        return {"subaccounts": []}

@app.patch("/api/subaccounts/automatic-transfers")
async def update_subaccount_automatic_transfers(request: Request):
    """Set automatic_transfers for a subaccount by name. Body: { \"subaccount\": \"Master Trading Bankroll\", \"automatic_transfers\": true }."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        automatic = payload.get("automatic_transfers")
        if subaccount_name is None or automatic is None:
            return {"ok": False, "error": "subaccount and automatic_transfers required"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users.subaccounts_0001 SET automatic_transfers = %s WHERE subaccount = %s",
                (bool(automatic), subaccount_name)
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error updating subaccount automatic_transfers: {e}")
        return {"ok": False, "error": str(e)}

@app.patch("/api/subaccounts/transfer-settings")
async def update_subaccount_transfer_settings(request: Request):
    """Set target_pnl__pct and/or transfer_amt for a subaccount. Body: { \"subaccount\": \"Master Trading Bankroll\", \"target_pnl__pct\": 0.115, \"transfer_amt\": 0.10 } (fractions)."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        target_pct = payload.get("target_pnl__pct")
        transfer_amt = payload.get("transfer_amt")
        if subaccount_name is None:
            return {"ok": False, "error": "subaccount required"}
        if target_pct is None and transfer_amt is None:
            return {"ok": False, "error": "at least one of target_pnl__pct or transfer_amt required"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            if target_pct is not None and transfer_amt is not None:
                cursor.execute(
                    "UPDATE users.subaccounts_0001 SET target_pnl__pct = %s, transfer_amt = %s WHERE subaccount = %s",
                    (float(target_pct), float(transfer_amt), subaccount_name)
                )
            elif target_pct is not None:
                cursor.execute(
                    "UPDATE users.subaccounts_0001 SET target_pnl__pct = %s WHERE subaccount = %s",
                    (float(target_pct), subaccount_name)
                )
            else:
                cursor.execute(
                    "UPDATE users.subaccounts_0001 SET transfer_amt = %s WHERE subaccount = %s",
                    (float(transfer_amt), subaccount_name)
                )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error updating subaccount transfer settings: {e}")
        return {"ok": False, "error": str(e)}


@app.patch("/api/subaccounts/base-value")
async def update_subaccount_base_value(request: Request):
    """Set base_value (cents) for a subaccount. Body: { \"subaccount\": \"Master Trading Bankroll\", \"base_value\": 84329 } (base_value in cents)."""
    try:
        payload = await request.json()
        subaccount_name = payload.get("subaccount")
        base_value = payload.get("base_value")
        if subaccount_name is None:
            return {"ok": False, "error": "subaccount required"}
        if base_value is None:
            return {"ok": False, "error": "base_value required"}
        try:
            base_value_int = int(base_value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "base_value must be an integer (cents)"}
        if base_value_int < 0:
            return {"ok": False, "error": "base_value must be non-negative"}
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users.subaccounts_0001 SET base_value = %s WHERE subaccount = %s",
                (base_value_int, subaccount_name)
            )
            conn.commit()
            if cursor.rowcount == 0:
                conn.close()
                return {"ok": False, "error": "subaccount not found"}
        conn.close()
        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error updating subaccount base_value: {e}")
        return {"ok": False, "error": str(e)}


@app.post("/api/subaccounts/initiate-transfer")
async def initiate_transfer(request: Request):
    """
    Manual internal transfer between subaccounts (e.g. MTB → Cash Transfer).
    Body: { "from": "Master Trading Bankroll", "to": "Cash Transfer", "amount": 100 } (amount in dollars).
    Inserts into users.transfers_0001 (initiated=manual), updates subaccounts balances, then triggers
    kalshi_account_sync (sync_balance) to poll Kalshi and update account_balance.
    """
    try:
        payload = await request.json()
        from_name = payload.get("from")
        to_name = payload.get("to")
        amount_dollars = payload.get("amount")
        if not from_name or not to_name:
            return {"ok": False, "error": "from and to required"}
        if from_name == "PRIMARY" or to_name == "PRIMARY":
            return {"ok": False, "error": "PRIMARY cannot be from or to"}
        if from_name == "External" or to_name == "External":
            return {"ok": False, "error": "External transfers not supported yet"}
        if from_name == to_name:
            return {"ok": False, "error": "from and to must differ"}
        try:
            amount_val = float(amount_dollars)
        except (TypeError, ValueError):
            return {"ok": False, "error": "amount must be a number"}
        if amount_val <= 0:
            return {"ok": False, "error": "amount must be positive"}
        amount_cents = int(round(amount_val * 100))

        import psycopg2
        from zoneinfo import ZoneInfo
        from datetime import datetime
        EST = ZoneInfo("America/New_York")
        transfer_timestamp_est = datetime.now(EST).strftime("%Y-%m-%d %H:%M:%S")

        conn = get_postgresql_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT balance FROM users.subaccounts_0001 WHERE subaccount = %s",
                    (from_name,)
                )
                row = cursor.fetchone()
                if not row:
                    return {"ok": False, "error": f"subaccount not found: {from_name}"}
                from_balance = int(row[0]) if row[0] is not None else 0
                if from_balance < amount_cents:
                    return {"ok": False, "error": f"insufficient balance in {from_name}"}
                cursor.execute(
                    "SELECT 1 FROM users.subaccounts_0001 WHERE subaccount = %s",
                    (to_name,)
                )
                if not cursor.fetchone():
                    return {"ok": False, "error": f"subaccount not found: {to_name}"}

                cursor.execute("""
                    INSERT INTO users.transfers_0001 (timestamp, type, "from", "to", amount, initiated)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (transfer_timestamp_est, "internal", from_name, to_name, amount_cents, "manual"))
                cursor.execute(
                    "UPDATE users.subaccounts_0001 SET balance = balance - %s WHERE subaccount = %s",
                    (amount_cents, from_name)
                )
                cursor.execute(
                    "UPDATE users.subaccounts_0001 SET balance = balance + %s WHERE subaccount = %s",
                    (amount_cents, to_name)
                )
                conn.commit()
        finally:
            conn.close()

        # Notify frontend so Account Information panel refreshes immediately (subaccounts + transfers table)
        await broadcast_db_change("subaccounts", {"source": "initiate_transfer"})
        await broadcast_db_change("transfers", {"source": "initiate_transfer"})

        # Trigger kalshi_account_sync (sync_balance) in background: poll Kalshi, update subaccounts/account_balance, notify
        def _run_sync():
            try:
                from backend.kalshi_account_sync_ws import sync_balance
                sync_balance()
            except Exception as e:
                _main_logger.warning(f"initiate-transfer: sync_balance failed: {e}")

        import threading
        threading.Thread(target=_run_sync, daemon=True).start()

        return {"ok": True}
    except Exception as e:
        _main_logger.warning(f"Error initiating transfer: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/api/monitor/bankroll")
async def get_monitor_bankroll(monitor_id: str):
    """Get monitor-specific bankroll allotment from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get monitor-specific bankroll allotment
            cursor.execute("""
                SELECT bankroll_allotment_total, name, symbol
                FROM users.monitor_list_0001 
                WHERE id = %s
            """, (monitor_id,))
            monitor_result = cursor.fetchone()
            
            conn.close()
            
            if monitor_result:
                bankroll_allotment = monitor_result['bankroll_allotment_total'] or 0
                return {
                    "monitor_id": monitor_id,
                    "bankroll_allotment_total": bankroll_allotment,
                    "name": monitor_result['name'],
                    "symbol": monitor_result['symbol']
                }
            else:
                return {"monitor_id": monitor_id, "bankroll_allotment_total": 0, "name": "Unknown", "symbol": "BTC"}
            
    except Exception as e:
        _main_logger.warning(f"Error getting monitor bankroll from PostgreSQL: {e}")
        return {"monitor_id": monitor_id, "bankroll_allotment_total": 0, "name": "Unknown", "symbol": "BTC"}

@app.get("/api/account/balance/history")
async def get_account_balance_history(mode: str = "prod", limit: int = 1000):
    """Get historical account balance data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Get historical account balance data
            cursor.execute("""
                SELECT portfolio, positions, updated_at 
                FROM users.account_balance_0001 
                ORDER BY updated_at ASC
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
                    "timestamp": result['updated_at'].isoformat() if result['updated_at'] else None
                })
            
            return {"history": history_data}
            
    except Exception as e:
        _main_logger.warning(f"Error getting account balance history from PostgreSQL: {e}")
        return {"history": []}

@app.get("/api/db/fills")
def get_fills():
    """Get fills data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.fills_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            fills = cursor.fetchall()
            
            # Convert RealDictRow to dict; prefer _fp for count (rounded for display)
            fills_list = []
            for fill in fills:
                fill_dict = dict(fill)
                if fill_dict.get("count_fp") is not None:
                    try:
                        fill_dict["count"] = int(round(float(fill_dict["count_fp"])))
                    except (TypeError, ValueError):
                        pass
                fills_list.append(fill_dict)
            
            conn.close()
            return {"fills": fills_list}
            
    except Exception as e:
        _main_logger.warning(f"Error getting fills from PostgreSQL: {e}")
        return {"fills": []}

@app.get("/api/db/positions")
def get_positions():
    """Get positions data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.positions_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            positions = cursor.fetchall()
            
            # Convert to dict; prefer _fp for position/total_traded (rounded for display)
            positions_list = []
            for position in positions:
                position_dict = dict(position)
                if position_dict.get("position_fp") is not None:
                    try:
                        position_dict["position"] = int(round(float(position_dict["position_fp"])))
                    except (TypeError, ValueError):
                        pass
                if position_dict.get("total_traded_fp") is not None:
                    try:
                        position_dict["total_traded"] = int(round(float(position_dict["total_traded_fp"])))
                    except (TypeError, ValueError):
                        pass
                positions_list.append(position_dict)
            
            conn.close()
            return {"positions": positions_list}
            
    except Exception as e:
        _main_logger.warning(f"Error getting positions from PostgreSQL: {e}")
        return {"positions": []}

@app.get("/api/db/settlements")
def get_settlements():
    """Get settlements data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM users.settlements_0001 
                ORDER BY id DESC 
                LIMIT 100
            """)
            settlements = cursor.fetchall()
            
            # Convert to dict; prefer _fp for yes_count/no_count (rounded for display)
            settlements_list = []
            for settlement in settlements:
                settlement_dict = dict(settlement)
                if settlement_dict.get("yes_count_fp") is not None:
                    try:
                        settlement_dict["yes_count"] = int(round(float(settlement_dict["yes_count_fp"])))
                    except (TypeError, ValueError):
                        pass
                if settlement_dict.get("no_count_fp") is not None:
                    try:
                        settlement_dict["no_count"] = int(round(float(settlement_dict["no_count_fp"])))
                    except (TypeError, ValueError):
                        pass
                settlements_list.append(settlement_dict)
            
            conn.close()
            return {"settlements": settlements_list}
            
    except Exception as e:
        _main_logger.warning(f"Error getting settlements from PostgreSQL: {e}")
        return {"settlements": []}


@app.get("/api/db/transfers")
def get_transfers():
    """Get transfer history from users.transfers_0001 (internal/external transfer log)."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = get_postgresql_connection()

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("""
                SELECT id, timestamp, type, "from", "to", amount, initiated, status
                FROM users.transfers_0001
                ORDER BY id DESC
                LIMIT 100
            """)
            rows = cursor.fetchall()

        transfers_list = [dict(r) for r in rows]
        conn.close()
        return {"transfers": transfers_list}

    except Exception as e:
        _main_logger.warning(f"Error getting transfers from PostgreSQL: {e}")
        return {"transfers": []}


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
        
        conn = get_postgresql_connection()
        
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
        _main_logger.debug(f"[DB SYSTEM HEALTH] Error: {e}")
        return {"error": "Database error"}

@app.get("/api/db/trades")
def get_trades_from_postgresql():
    """Get trades data from PostgreSQL database."""
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
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
        _main_logger.warning(f"Error getting trades from PostgreSQL: {e}")
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
        
        _main_logger.debug(f"[FINGERPRINT] Current fingerprint: {fingerprint_info['fingerprint_file']}")
        return fingerprint_info
        
    except Exception as e:
        _main_logger.warning(f"Error getting fingerprint: {e}")
        return {"fingerprint": "error", "error": str(e)}

@app.get("/api/momentum")
async def get_current_momentum(symbol: str = "BTC"):
    """Get current momentum score directly from PostgreSQL for specified symbol."""
    try:
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute(f"SELECT momentum FROM live_data.live_price_log_1s_{symbol.lower()} ORDER BY timestamp DESC LIMIT 1")
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
        _main_logger.warning(f"Error getting momentum from PostgreSQL: {e}")
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
        
        conn = get_postgresql_connection()
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
        _main_logger.warning(f"Error getting BTC price from PostgreSQL: {e}")
        return {"price": None, "error": str(e)}

@app.get("/api/eth_price")
async def get_eth_price():
    """Get current ETH price directly from PostgreSQL live_data.live_price_log_1s_eth."""
    try:
        import psycopg2
        
        conn = get_postgresql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM live_data.live_price_log_1s_eth ORDER BY timestamp DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            price = float(result[0])
            return {"price": price, "source": "postgresql_live_data"}
        else:
            return {"price": None, "error": "No price data available"}
            
    except Exception as e:
        _main_logger.warning(f"Error getting ETH price from PostgreSQL: {e}")
        return {"price": None, "error": str(e)}

@app.get("/api/momentum_score")
async def get_momentum_score():
    """Get current momentum score for mobile directly from PostgreSQL."""
    try:
        conn = get_postgresql_connection()
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
        _main_logger.warning(f"Error getting momentum score: {e}")
        return {"weighted_score": 0, "error": str(e)}

def _strike_table_name(symbol: str, market: str) -> str:
    """Build strike table name from symbol and market. Market must be 'hourly' or '15m'."""
    s = (symbol or "btc").lower()
    m = (market or "").strip().lower()
    if m not in ("hourly", "15m"):
        raise ValueError("market must be 'hourly' or '15m'")
    return f"strike_table_{m}_{s}"


@app.get("/api/strike_table")
async def get_strike_table_mobile(request: Request):
    """Get strike table data for mobile. Query params: symbol, market (required: hourly or 15m)."""
    try:
        import psycopg2
        symbol = (request.query_params.get("symbol") or "btc").lower()
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"strikes": [], "error": "market required (hourly or 15m)"}
        table_name = _strike_table_name(symbol, market)
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Get strike table data from PostgreSQL
            cursor.execute(f"""
                SELECT 
                    strike,
                    buffer,
                    buffer_pct,
                    probability,
                    yes_ask,
                    no_ask,
                    yes_ask_dollars,
                    no_ask_dollars,
                    volume,
                    ticker,
                    yes_diff,
                    no_diff,
                    active_side
                    FROM live_data.{table_name}
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
                    "yes_ask_dollars": row[6],
                    "no_ask_dollars": row[7],
                    "volume": int(row[8]) if row[8] else None,
                    "ticker": row[9],
                    "yes_diff": float(row[10]) if row[10] else None,
                    "no_diff": float(row[11]) if row[11] else None,
                    "active_side": row[12]
                }
                strikes.append(strike)
            
            return {"strikes": strikes}
            
    except Exception as e:
        _main_logger.warning(f"Error getting strike table from PostgreSQL: {e}")
        return {"strikes": [], "error": str(e)}

# === PREFERENCES API ENDPOINTS ===

# LEGACY REMOVED: /api/set_auto_stop endpoint - no longer used, auto stop now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/set_auto_entry endpoint - no longer used, auto entry now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_stop endpoint - no longer used, auto stop now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_entry endpoint - no longer used, auto entry now controlled by auto_trade in monitor_list

# Diff mode is now local only - no API endpoint needed

# Legacy position sizing endpoints removed - all position sizing now handled by monitor_list table

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
            _main_logger.debug(f"[Invalid Position Size] {e}")

    if "multiplier" in data:
        try:
            prefs["multiplier"] = float(data["multiplier"])
            updated = True
        except Exception as e:
            _main_logger.debug(f"[Invalid Multiplier] {e}")

    if updated:
        await save_preferences(prefs)
        await broadcast_preferences_update()
    return {"status": "ok"}

# Legacy /api/get_preferences endpoint removed - position sizing and strategy now handled by monitor_list table

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
        _main_logger.debug(f"[Trade History Preferences Load Error] {e}")
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
            "last_search_timestamp": time.time(),
            "pct_mode": False
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
        if "live_filter" in preferences:
            update_data["live_filter"] = bool(preferences["live_filter"])
        if "paper_filter" in preferences:
            update_data["paper_filter"] = bool(preferences["paper_filter"])
        
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
        
        # Strategy filters (legacy fixed keys; dynamic strategy_selection from strategy_list)
        strategy_fields = ["strategy_hourly_htc", "strategy_momentum_scalp", "strategy_test"]
        for field in strategy_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])
        if "strategy_selection" in preferences and isinstance(preferences["strategy_selection"], dict):
            update_data["strategy_selection"] = json.dumps(preferences["strategy_selection"])
        if "symbol_selection" in preferences and isinstance(preferences["symbol_selection"], dict):
            update_data["symbol_selection"] = json.dumps(preferences["symbol_selection"])

        # Day filters
        day_fields = ["day_sunday", "day_monday", "day_tuesday", "day_wednesday", "day_thursday", "day_friday", "day_saturday"]
        for field in day_fields:
            if field in preferences:
                update_data[field] = bool(preferences[field])
        
        # Analysis interval
        if "analysis_interval" in preferences:
            update_data["analysis_interval"] = str(preferences["analysis_interval"])
        
        # Chart view
        if "chart_view" in preferences:
            update_data["chart_view"] = str(preferences["chart_view"])
        
        # Percent mode
        if "pct_mode" in preferences:
            update_data["pct_mode"] = bool(preferences["pct_mode"])
        
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
            _main_logger.debug(f"[Trade History Preferences] ✅ Updated PostgreSQL: {list(update_data.keys())}")
    except Exception as e:
        _main_logger.debug(f"[Trade History Preferences Save Error] {e}")

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
        _main_logger.debug(f"[Trade History Preferences Set Error] {e}")
        return {"status": "error", "message": str(e)}

# LEGACY REMOVED: /api/get_auto_stop endpoint - no longer used, auto stop now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_entry endpoint - no longer used, auto entry now controlled by auto_trade in monitor_list

# LEGACY REMOVED: /api/get_auto_trade_settings endpoint - now using strategy-specific endpoints

# LEGACY REMOVED: /api/get_auto_entry_status endpoint - now using auto_trade_status system

@app.post("/api/notify_auto_trade_status_change")
async def notify_auto_trade_status_change(request: Request):
    """Notify frontend of auto trade status change via WebSocket"""
    try:
        data = await request.json()
        monitor_id = data.get("monitor_id")
        auto_trade_status = data.get("auto_trade_status")
        
        if not monitor_id or not auto_trade_status:
            return {"status": "error", "message": "Missing monitor_id or auto_trade_status"}
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "auto_trade_status_change",
            "data": {
                "monitor_id": monitor_id,
                "auto_trade_status": auto_trade_status
            }
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Auto trade status change broadcasted to {len(connected_clients)} clients")
        return {"status": "ok", "message": "Auto trade status change notification sent"}
    except Exception as e:
        _main_logger.warning(f"Error in notify_auto_trade_status_change: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/notify_cooldown_timer_change")
async def notify_cooldown_timer_change(request: Request):
    """Notify frontend of cooldown timer change via WebSocket"""
    try:
        data = await request.json()
        monitor_id = data.get("monitor_id")
        cooldown_timer = data.get("cooldown_timer")
        
        if not monitor_id or cooldown_timer is None:
            return {"status": "error", "message": "Missing monitor_id or cooldown_timer"}
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "cooldown_timer_change",
            "data": {
                "monitor_id": monitor_id,
                "cooldown_timer": cooldown_timer
            }
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Cooldown timer change broadcasted to {len(connected_clients)} clients")
        return {"status": "ok", "message": "Cooldown timer change notification sent"}
    except Exception as e:
        _main_logger.warning(f"Error in notify_cooldown_timer_change: {e}")
        return {"status": "error", "message": str(e)}

# Legacy /api/get_trade_preferences endpoint removed - position sizing and strategy now handled by monitor_list table

# Legacy /api/update_trade_preferences endpoint removed - position sizing and strategy now handled by monitor_list table

# LEGACY REMOVED: /api/update_auto_entry_settings endpoint - now using /api/set_auto_entry_settings

# LEGACY REMOVED: /api/update_auto_stop_settings endpoint - now using /api/set_auto_entry_settings

import os
# Legacy auto stop settings path removed - all data now in PostgreSQL

# Legacy auto stop settings functions removed - all data now in PostgreSQL

# LEGACY REMOVED: /api/get_auto_stop_settings and /api/set_auto_stop_settings endpoints - now using /api/set_auto_entry_settings

# Legacy auto entry settings path removed - all data now in PostgreSQL

# Legacy auto entry settings functions removed - all data now in PostgreSQL

@app.get("/api/get_auto_entry_settings")
async def get_auto_entry_settings(monitor_id: str = None):
    """Get auto entry and auto stop settings for a specific monitor from monitor_list table"""
    if not monitor_id:
        return {"status": "error", "message": "Monitor ID required"}
    
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Get settings directly from monitor_list table
            cursor.execute("""
                SELECT min_probability, max_probability, min_differential, max_differential, min_time, max_time, allow_re_entry,
                       spike_alert_enabled, spike_alert_momentum_threshold, 
                       spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                       current_probability, min_ttc_seconds, momentum_spike_enabled, 
                       momentum_spike_threshold, verification_period_enabled, verification_period_seconds,
                       min_volume, win_streak_threshold, performance_based_allocation,
                       momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, momentum_scalp_profit_target,
                       min_ask, max_ask, loss_prevention_toggle, max_price_spread, prob_adj,
                       min_cooldown_timer, max_cooldown_timer
                FROM users.monitor_list_0001 WHERE id = %s
            """, (monitor_id,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                return {
                    "min_probability": float(result[0]) if result[0] is not None else 95.00,
                    "max_probability": float(result[1]) if result[1] is not None else 100.00,
                    "min_differential": float(result[2]) if result[2] else 0.25,
                    "max_differential": float(result[3]) if result[3] is not None else None,
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
                    "momentum_spike_threshold": result[14],
                    "verification_period_enabled": result[15],
                    "verification_period_seconds": result[16],
                    "min_volume": result[17],
                    "win_streak_threshold": result[18],
                    "performance_based_allocation": result[19],
                    "momentum_scalp_entry_threshold": float(result[20]) if result[20] is not None else None,
                    "momentum_scalp_trailing_stop_amount": float(result[21]) if result[21] is not None else None,
                    "momentum_scalp_profit_target": float(result[22]) if result[22] is not None else None,
                    "min_ask": float(result[23]) if result[23] is not None else 0.0000,
                    "max_ask": float(result[24]) if result[24] is not None else 0.9800,
                    "loss_prevention_toggle": bool(result[25]) if result[25] is not None else True,
                    "max_price_spread": float(result[26]) if result[26] is not None else 0.0300,
                    "prob_adj": float(result[27]) if result[27] is not None else 5.00,
                    "min_cooldown_timer": result[28] if result[28] is not None else None,
                    "max_cooldown_timer": result[29] if result[29] is not None else None
                }
            else:
                return {"status": "error", "message": f"Monitor not found: {monitor_id}"}
                
    except Exception as e:
        _main_logger.debug(f"[Auto Entry Settings] ❌ Error getting monitor settings: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/set_auto_entry_settings")
async def set_auto_entry_settings(request: Request):
    data = await request.json()
    
    monitor_id = data.get("monitor_id")
    if not monitor_id:
        return {"status": "error", "message": "Monitor ID required"}
    
    try:
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Check if monitor exists
            cursor.execute("""
                SELECT id FROM users.monitor_list_0001 WHERE id = %s
            """, (monitor_id,))
            monitor_result = cursor.fetchone()
            
            if not monitor_result:
                return {"status": "error", "message": f"Monitor not found: {monitor_id}"}
            
            # Build update fields and values
            update_fields = []
            update_values = []
            
            # Auto entry parameters
            if "min_probability" in data:
                update_fields.append("min_probability = %s")
                update_values.append(float(data["min_probability"]))
            if "max_probability" in data:
                update_fields.append("max_probability = %s")
                update_values.append(float(data["max_probability"]))
            if "min_differential" in data:
                update_fields.append("min_differential = %s")
                update_values.append(float(data["min_differential"]))
            if "max_differential" in data:
                update_fields.append("max_differential = %s")
                update_values.append(float(data["max_differential"]) if data["max_differential"] is not None else None)
            if "min_volume" in data:
                update_fields.append("min_volume = %s")
                update_values.append(int(data["min_volume"]))
            if "min_time" in data:
                update_fields.append("min_time = %s")
                update_values.append(int(data["min_time"]))
            if "max_time" in data:
                update_fields.append("max_time = %s")
                update_values.append(int(data["max_time"]))
            if "allow_re_entry" in data:
                update_fields.append("allow_re_entry = %s")
                update_values.append(bool(data["allow_re_entry"]))
            if "win_streak_threshold" in data:
                update_fields.append("win_streak_threshold = %s")
                update_values.append(int(data["win_streak_threshold"]))
            if "spike_alert_enabled" in data:
                update_fields.append("spike_alert_enabled = %s")
                update_values.append(bool(data["spike_alert_enabled"]))
            if "spike_alert_momentum_threshold" in data:
                update_fields.append("spike_alert_momentum_threshold = %s")
                update_values.append(int(data["spike_alert_momentum_threshold"]))
            if "spike_alert_cooldown_threshold" in data:
                update_fields.append("spike_alert_cooldown_threshold = %s")
                update_values.append(int(data["spike_alert_cooldown_threshold"]))
            if "spike_alert_cooldown_minutes" in data:
                update_fields.append("spike_alert_cooldown_minutes = %s")
                update_values.append(int(data["spike_alert_cooldown_minutes"]))
            
            # Auto stop parameters
            if "current_probability" in data:
                update_fields.append("current_probability = %s")
                update_values.append(int(data["current_probability"]))
            if "min_ttc_seconds" in data:
                update_fields.append("min_ttc_seconds = %s")
                update_values.append(int(data["min_ttc_seconds"]))
            if "momentum_spike_enabled" in data:
                update_fields.append("momentum_spike_enabled = %s")
                update_values.append(bool(data["momentum_spike_enabled"]))
            if "momentum_spike_threshold" in data:
                update_fields.append("momentum_spike_threshold = %s")
                update_values.append(int(data["momentum_spike_threshold"]))
            if "verification_period_enabled" in data:
                update_fields.append("verification_period_enabled = %s")
                update_values.append(bool(data["verification_period_enabled"]))
            if "verification_period_seconds" in data:
                update_fields.append("verification_period_seconds = %s")
                update_values.append(int(data["verification_period_seconds"]))
            if "performance_based_allocation" in data:
                update_fields.append("performance_based_allocation = %s")
                update_values.append(bool(data["performance_based_allocation"]))
            
            # Momentum Scalp specific parameters
            if "momentum_scalp_entry_threshold" in data:
                update_fields.append("momentum_scalp_entry_threshold = %s")
                update_values.append(float(data["momentum_scalp_entry_threshold"]))
            if "momentum_scalp_trailing_stop_amount" in data:
                update_fields.append("momentum_scalp_trailing_stop_amount = %s")
                update_values.append(float(data["momentum_scalp_trailing_stop_amount"]))
            if "momentum_scalp_profit_target" in data:
                update_fields.append("momentum_scalp_profit_target = %s")
                update_values.append(float(data["momentum_scalp_profit_target"]))
            if "min_ask" in data:
                update_fields.append("min_ask = %s")
                update_values.append(float(data["min_ask"]))
            if "max_ask" in data:
                update_fields.append("max_ask = %s")
                update_values.append(float(data["max_ask"]))
            if "loss_prevention_toggle" in data:
                update_fields.append("loss_prevention_toggle = %s")
                update_values.append(bool(data["loss_prevention_toggle"]))
            if "max_price_spread" in data:
                update_fields.append("max_price_spread = %s")
                update_values.append(float(data["max_price_spread"]))
            if "prob_adj" in data:
                update_fields.append("prob_adj = %s")
                update_values.append(float(data["prob_adj"]))
            if "min_cooldown_timer" in data:
                update_fields.append("min_cooldown_timer = %s")
                update_values.append(int(data["min_cooldown_timer"]) if data["min_cooldown_timer"] is not None else None)
            if "max_cooldown_timer" in data:
                update_fields.append("max_cooldown_timer = %s")
                update_values.append(int(data["max_cooldown_timer"]) if data["max_cooldown_timer"] is not None else None)
            
            if update_fields:
                # Update the monitor in monitor_list table
                query = f"UPDATE users.monitor_list_0001 SET {', '.join(update_fields)} WHERE id = %s"
                update_values.append(monitor_id)
                cursor.execute(query, update_values)
                
                _main_logger.debug(f"[Auto Entry & Auto Stop Settings] ✅ Updated monitor {monitor_id}: {list(data.keys())}")
                
                # Return the updated settings
                cursor.execute("""
                    SELECT min_probability, min_differential, min_time, max_time, allow_re_entry,
                           spike_alert_enabled, spike_alert_momentum_threshold, 
                           spike_alert_cooldown_threshold, spike_alert_cooldown_minutes,
                           current_probability, min_ttc_seconds, momentum_spike_enabled, 
                           momentum_spike_threshold, verification_period_enabled, verification_period_seconds,
                           min_volume, win_streak_threshold, performance_based_allocation,
                           momentum_scalp_entry_threshold, momentum_scalp_trailing_stop_amount, momentum_scalp_profit_target
                    FROM users.monitor_list_0001 WHERE id = %s
                """, (monitor_id,))
                updated_result = cursor.fetchone()
                
                if updated_result:
                    updated_settings = {
                        "min_probability": updated_result[0],
                        "min_differential": float(updated_result[1]),
                        "min_time": updated_result[2],
                        "max_time": updated_result[3],
                        "allow_re_entry": updated_result[4],
                        "spike_alert_enabled": updated_result[5],
                        "spike_alert_momentum_threshold": updated_result[6],
                        "spike_alert_cooldown_threshold": updated_result[7],
                        "spike_alert_cooldown_minutes": updated_result[8],
                        "current_probability": updated_result[9],
                        "min_ttc_seconds": updated_result[10],
                        "momentum_spike_enabled": updated_result[11],
                        "momentum_spike_threshold": updated_result[12],
                        "verification_period_enabled": updated_result[13],
                        "verification_period_seconds": updated_result[14],
                        "min_volume": updated_result[15],
                        "win_streak_threshold": updated_result[16],
                        "performance_based_allocation": updated_result[17],
                        "momentum_scalp_entry_threshold": float(updated_result[18]) if updated_result[18] is not None else None,
                        "momentum_scalp_trailing_stop_amount": float(updated_result[19]) if updated_result[19] is not None else None,
                        "momentum_scalp_profit_target": float(updated_result[20]) if updated_result[20] is not None else None
                    }
                    conn.commit()
                    conn.close()
                    return {"status": "ok", **updated_settings}
                else:
                    return {"status": "error", "message": "Failed to retrieve updated settings"}
            else:
                return {"status": "error", "message": "No valid fields to update"}
                
    except Exception as e:
        _main_logger.debug(f"[Auto Entry Settings] ❌ Error updating strategy: {e}")
        return {"status": "error", "message": str(e)}

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
        paper_trade = data.get("paper_trade", False)
        
        _main_logger.debug(f"[TRIGGER OPEN TRADE] Received request: strike={strike}, side={side}, ticker={ticker}, buy_price={buy_price}, prob={prob}, symbol_open={symbol_open}, momentum={momentum}, paper_trade={paper_trade}")
        
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
        
        # Get current monitor information from the request - NO FALLBACKS
        monitor = data.get("monitor")
        if not monitor:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Error: No monitor specified in trade data")
            return {"status": "error", "message": "Monitor must be specified"}
        
        # Extract monitor ID from monitor string (e.g., "mon_0001_10001" -> "10001")
        monitor_id = monitor.split('_')[-1] if monitor and '_' in monitor else None
        if not monitor_id:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Error: Invalid monitor format: {monitor}")
            return {"status": "error", "message": "Invalid monitor format"}
        
        # Get bankroll_allotment_total from monitor configuration
        bankroll_allotment_total = None
        try:
            import psycopg2
            conn = get_postgresql_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT bankroll_allotment_total FROM users.monitor_list_0001 WHERE id = %s", (monitor_id,))
                result = cursor.fetchone()
                if result:
                    bankroll_allotment_total = result[0]
                    _main_logger.debug(f"[TRIGGER OPEN TRADE] Bankroll allotment loaded from monitor {monitor_id}: {bankroll_allotment_total}")
                else:
                    _main_logger.debug(f"[TRIGGER OPEN TRADE] No monitor configuration found for monitor {monitor_id}")
                    return {"status": "error", "message": "Monitor configuration not found"}
        except Exception as e:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Error loading bankroll allotment from monitor {monitor_id}: {e}")
            return {"status": "error", "message": f"Failed to load monitor configuration: {e}"}
        finally:
            if conn:
                conn.close()
        
        # Prepare the trade data exactly like trade_initiator does (count_fp for full-chain consistency)
        position_val = position or 1
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
            "position": position_val,
            "count_fp": f"{float(position_val):.2f}",
            "symbol_open": symbol_open,
            "symbol_close": None,
            "momentum": momentum,
            "prob": prob,
            "diff": data.get("diff"),  # Add diff from request
            "win_loss": None,
            "entry_method": data.get("entry_method", "manual"),
            "monitor": monitor,  # Add monitor field
            "bankroll_allotment_total": bankroll_allotment_total,
            "paper_trade": paper_trade  # Add paper_trade from request
        }
        
        # Send request directly to trade_manager
        response = requests.post(trade_manager_url, json=trade_data, timeout=10)
        
        if response.status_code == 201:
            result = response.json()
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Trade initiated successfully: {result}")
            return {
                "status": "success",
                "message": "Trade initiated successfully",
                "trade_data": result
            }
        else:
            _main_logger.debug(f"[TRIGGER OPEN TRADE] Trade initiation failed: {response.status_code} - {response.text}")
            return {
                "status": "error",
                "message": f"Trade initiation failed: {response.status_code}",
                "details": response.text
            }
        
    except Exception as e:
        _main_logger.debug(f"[TRIGGER OPEN TRADE] Error: {e}")
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
async def get_live_probabilities(request: Request):
    """Get live probabilities. Query params: symbol, market (required: hourly or 15m)."""
    try:
        import psycopg2
        symbol = (request.query_params.get("symbol") or "btc").lower()
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)"}
        table_name = _strike_table_name(symbol, market)
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Get probability data from PostgreSQL strike table
            cursor.execute(f"""
                SELECT 
                    strike,
                    probability
                    FROM live_data.{table_name}
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
        _main_logger.debug(f"Warning: File locking failed for {filepath}: {e}")
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as read_error:
            _main_logger.warning(f"Error reading JSON from {filepath}: {read_error}")
            return None

@app.get("/api/strike_tables/{symbol}")
async def get_strike_table(symbol: str, request: Request):
    """Get strike table data. Query param: market (required: hourly or 15m)."""
    try:
        import psycopg2
        
        # Convert symbol to lowercase for consistency (used for error messages/logs)
        symbol_lower = symbol.lower()
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)"}
        table_name = _strike_table_name(symbol, market)
        ttc_col = "ttc_15m" if market == "15m" else "ttc_hourly"
        prob_col = "probability_15m" if market == "15m" else "probability_hourly"
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT 
                    symbol,
                    current_price,
                    {ttc_col},
                    event_ticker,
                    market_title,
                    strike_tier,
                    market_status,
                    momentum_percentile
                    FROM live_data.{table_name}
                LIMIT 1
            """)
            header_data = cursor.fetchone()
            if not header_data:
                return {"error": f"No strike table data found for {symbol}"}
            cursor.execute(f"""
                SELECT 
                    strike,
                    buffer,
                    buffer_pct,
                    {prob_col},
                    yes_ask,
                    no_ask,
                    yes_ask_dollars,
                    no_ask_dollars,
                    volume,
                    ticker,
                    yes_diff,
                    no_diff,
                    active_side
                    FROM live_data.{table_name}
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
async def get_postgresql_strike_table(symbol: str, request: Request):
    """Get strike table data. Query param: market (required: hourly or 15m)."""
    try:
        import psycopg2
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)"}
        table_name = _strike_table_name(symbol, market)
        ttc_column = "ttc_15m" if market == "15m" else "ttc_hourly"
        prob_column = "probability_15m" if market == "15m" else "probability_hourly"
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Get the latest strike table data from PostgreSQL
            cursor.execute(f"""
                SELECT 
                    symbol,
                    current_price,
                    {ttc_column},
                    momentum_percentile,
                    market_title,
                    timestamp
                FROM live_data.{table_name}
                LIMIT 1
            """)
            header_data = cursor.fetchone()
            if not header_data:
                return {"error": f"No strike table data found for {symbol}"}
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
                    active_side
                    FROM live_data.{table_name}
                ORDER BY strike
            """)
            
            strikes_data = cursor.fetchall()
            
            # Calculate momentum bucket from momentum_percentile
            momentum_percentile = float(header_data[3]) if header_data[3] else 0
            momentum_bucket = round(momentum_percentile)
            
            # Format the response
            response = {
                "symbol": header_data[0],
                "current_price": float(header_data[1]) if header_data[1] else None,
                "ttc_seconds": int(header_data[2]) if header_data[2] else None,
                "momentum_percentile": momentum_percentile,
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
                    "yes_ask_dollars": strike_row[6],
                    "no_ask_dollars": strike_row[7],
                    "volume": int(strike_row[8]) if strike_row[8] else None,
                    "ticker": strike_row[9],
                    "yes_diff": float(strike_row[10]) if strike_row[10] else None,
                    "no_diff": float(strike_row[11]) if strike_row[11] else None,
                    "active_side": strike_row[12]
                }
                response["strikes"].append(strike_data)
            
            conn.close()
            return response
            
    except Exception as e:
        _main_logger.warning(f"Error getting PostgreSQL strike table for {symbol}: {str(e)}")
        return {"error": f"Error loading PostgreSQL strike table for {symbol}: {str(e)}"}

@app.get("/api/watchlist/{monitor_name}")
async def get_watchlist(monitor_name: str):
    """Get watchlist data for a specific monitor from PostgreSQL"""
    try:
        import psycopg2
        import re
        
        # Extract the numeric part from monitor name (e.g., "mon_0001_10002" -> "0001_10002")
        # The table name format is watchlist_0001_10002, not watchlist_mon_0001_10002
        table_suffix = monitor_name
        if monitor_name.startswith('mon_'):
            table_suffix = monitor_name[4:]  # Remove "mon_" prefix
        
        # Connect to PostgreSQL using centralized config
        conn = get_postgresql_connection()
        if not conn:
            return {"error": "Database unavailable"}
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
                FROM live_data.watchlist_{table_suffix}
                LIMIT 1
            """)
            
            header_data = cursor.fetchone()
            
            if not header_data:
                return {"error": f"No watchlist data found for monitor {monitor_name}"}
            
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
                FROM live_data.watchlist_{table_suffix}
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
        return {"error": f"Error loading watchlist for monitor {monitor_name} from PostgreSQL: {str(e)}"}

@app.get("/api/active_trades/{monitor_name}")
async def get_active_trades_for_monitor(monitor_name: str):
    """Get active trades data for a specific monitor from PostgreSQL"""
    try:
        import psycopg2
        import re
        
        # Extract the numeric part from monitor name (e.g., "mon_0001_10002" -> "0001_10002")
        # The table name format is active_trades_0001_10002, not active_trades_mon_0001_10002
        table_suffix = monitor_name
        if monitor_name.startswith('mon_'):
            table_suffix = monitor_name[4:]  # Remove "mon_" prefix
        
        # Connect to PostgreSQL using centralized config
        conn = get_postgresql_connection()
        if not conn:
            return {"error": "Database unavailable"}
        with conn.cursor() as cursor:
            # Get all active trades for this monitor
            cursor.execute(f"""
                SELECT 
                    trade_id, ticket_id, date, time, strike, side, buy_price, position,
                    contract, ticker, symbol, market, trade_strategy, symbol_open,
                    momentum, prob, fees, diff, status, current_symbol_price,
                    current_probability, buffer_from_entry, time_since_entry,
                    current_close_price, current_pnl, last_updated, created_at
                FROM users.active_trades_{table_suffix}
                WHERE status IN ('active', 'pending', 'closing')
                ORDER BY created_at DESC
            """)
            
            trades_data = cursor.fetchall()
            conn.close()
            
            # Build response
            active_trades = []
            for row in trades_data:
                trade = {
                    "trade_id": row[0],
                    "ticket_id": row[1],
                    "date": row[2].isoformat() if row[2] else None,
                    "time": str(row[3]) if row[3] else None,
                    "strike": str(row[4]) if row[4] else None,
                    "side": row[5],
                    "buy_price": float(row[6]) if row[6] else None,
                    "position": int(row[7]) if row[7] else None,
                    "contract": row[8],
                    "ticker": row[9],
                    "symbol": row[10],
                    "market": row[11],
                    "trade_strategy": row[12],
                    "symbol_open": float(row[13]) if row[13] else None,
                    "momentum": float(row[14]) if row[14] else None,
                    "prob": float(row[15]) if row[15] else None,
                    "fees": float(row[16]) if row[16] else None,
                    "diff": float(row[17]) if row[17] else None,
                    "status": row[18],
                    "current_symbol_price": float(row[19]) if row[19] else None,
                    "current_probability": float(row[20]) if row[20] else None,
                    "buffer_from_entry": float(row[21]) if row[21] else None,
                    "time_since_entry": int(row[22]) if row[22] else None,
                    "current_close_price": float(row[23]) if row[23] else None,
                    "current_pnl": row[24],
                    "last_updated": row[25].isoformat() if row[25] else None,
                    "created_at": row[26].isoformat() if row[26] else None
                }
                active_trades.append(trade)
            
            return {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                "active_trades": active_trades,
                "count": len(active_trades),
                "monitor_identifier": monitor_name
            }
            
    except Exception as e:
        return {"error": f"Error loading active trades for monitor {monitor_name} from PostgreSQL: {str(e)}"}

@app.get("/api/unified_ttc/{symbol}")
async def get_unified_ttc(symbol: str, request: Request):
    """Get unified TTC data. Query param: market (required: hourly or 15m)."""
    try:
        import psycopg2
        market = (request.query_params.get("market") or "").strip().lower()
        if market not in ("hourly", "15m"):
            return {"error": "market required (hourly or 15m)", "ttc_seconds": 0}
        table_name = _strike_table_name(symbol, market)
        conn = get_postgresql_connection()
        with conn.cursor() as cursor:
            # Hourly tables use ttc_hourly; 15m tables use ttc_15m.
            ttc_column = "ttc_15m" if market == "15m" else "ttc_hourly"
            cursor.execute(f"""
                SELECT {ttc_column}, event_ticker, market_title, market_status
                    FROM live_data.{table_name}
                WHERE market_status = 'active'
                ORDER BY {ttc_column} ASC
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
        conn = get_postgresql_connection()
        
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
        _main_logger.debug(f"[MAIN] 🔔 Received automated trade notification: {data}")
        
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
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Automated trade notification broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Notification broadcasted"}
        
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error handling automated trade notification: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/notify_automated_close")
async def notify_automated_close(request: Request):
    """Receive automated trade close notification and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        _main_logger.debug(f"[MAIN] 🔔 Received automated trade close notification: {data}")
        
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
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Automated trade close notification broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Close notification broadcasted"}
        
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error handling automated trade close notification: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/broadcast_auto_entry_indicator")
async def broadcast_auto_entry_indicator(request: Request):
    """Receive auto entry indicator change and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        _main_logger.debug(f"[MAIN] 🔔 Received auto entry indicator change: {data}")
        
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
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Auto entry indicator change broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Indicator change broadcasted"}
        
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error handling auto entry indicator change: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/broadcast_active_trades_change")
async def broadcast_active_trades_change(request: Request):
    """Receive active trades change and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        _main_logger.debug(f"[MAIN] 🔔 Received active trades change: {data.get('count', 0)} trades")
        
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
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Active trades change broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Active trades change broadcasted"}
        
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error handling active trades change: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/broadcast_monitor_total_position")
async def broadcast_monitor_total_position(request: Request):
    """Receive monitor total position update and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        _main_logger.debug(f"[MAIN] 🔔 Received monitor total position update: {data}")
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "monitor_total_position_updated",
            "monitor_id": data.get("monitor_id"),
            "total_position": data.get("total_position")
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Monitor total position update broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Monitor total position update broadcasted"}
        
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error handling monitor total position update: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/broadcast_monitor_list_update")
async def broadcast_monitor_list_update(request: Request):
    """Receive monitor list update and broadcast to frontend via WebSocket"""
    try:
        data = await request.json()
        _main_logger.debug(f"[MAIN] 🔔 Received monitor list update: {data}")
        _main_logger.debug(f"[MAIN] 🔔 Connected WebSocket clients: {len(connected_clients)}")
        
        # Broadcast to all connected WebSocket clients
        message = {
            "type": "monitor_list_updated",
            "message": data.get("message", "Monitor list has been updated")
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                _main_logger.warning(f"Error sending to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[MAIN] ✅ Monitor list update broadcasted to {len(connected_clients)} clients")
        return {"success": True, "message": "Monitor list update broadcasted"}
        
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error handling monitor list update: {e}")
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
        
        _main_logger.debug(f"📡 Received DB change notification: {db_name} at {timestamp}")
        
        # Broadcast to all connected WebSocket clients
        await broadcast_db_change(db_name, {
            "timestamp": timestamp,
            "change_data": change_data
        })
        
        return {"status": "ok", "message": f"Notification sent for {db_name}"}
    except Exception as e:
        _main_logger.debug(f"❌ Error handling DB change notification: {e}")
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
                
                _main_logger.debug(f"[AUTH] User {username} logged in successfully")
                return {
                    "success": True,
                    "token": token,
                    "deviceId": device_id,
                    "username": username,
                    "name": credentials["name"]
                }
            else:
                _main_logger.debug(f"[AUTH] Failed login attempt for username: {username}")
                return {
                    "success": False,
                    "error": "Invalid username or password"
                }
        else:
            _main_logger.debug(f"[AUTH] Failed login attempt for username: {username}")
            return {
                "success": False,
                "error": "Invalid username or password"
            }
    except Exception as e:
        _main_logger.debug(f"[AUTH] Login error: {e}")
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
        
        # Local development bypass only when not in production
        if token.startswith("local_dev_") and os.getenv("REC_ENVIRONMENT") != "production":
            return {"authenticated": True, "username": "local_dev", "name": "Local Development"}
        
        # Check auth tokens only (device token alone is not enough for verify)
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
        
        return {"authenticated": False}
    except Exception as e:
        _main_logger.debug(f"[AUTH] Verification error: {e}")
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
        
        _main_logger.debug(f"[AUTH] User logged out successfully")
        return {"success": True}
    except Exception as e:
        _main_logger.debug(f"[AUTH] Logout error: {e}")
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
        _main_logger.debug(f"[USER INFO] Error getting user info: {e}")
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
        conn = get_postgresql_connection()
        if not conn:
            return {"success": False, "error": "Database unavailable"}
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE users.user_info_0001 
                SET password_hash = %s
                WHERE user_no = '0001'
            """, (new_hash,))
            conn.commit()
        
        return {"success": True, "message": "Password updated successfully"}
    except Exception as e:
        _main_logger.warning(f"[AUTH] Error changing password: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/system/health")
async def get_system_health():
    """Get current system health status from database"""
    try:
        import psycopg2
        
        conn = get_postgresql_connection()
        
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
        _main_logger.debug(f"[SYSTEM HEALTH] Error getting system health: {e}")
        return {"error": "Failed to get system health information"}

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
        
        env = os.environ.copy()
        # Only restrict PATH for non-backup commands so supervisorctl etc. use a minimal PATH
        if 'package_user_data.sh' not in command:
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
            timeout = 300 if 'package_user_data.sh' in command else 30
            # Backup script: run with PATH that can find pg_dump (IDE/launcher often don't have it)
            if 'package_user_data.sh' in command:
                import shlex
                run_cmd = ['/bin/bash', '-l', '-c', f'cd {shlex.quote(project_dir)} && {command}']
                backup_env = env.copy()
                extra_paths = '/opt/homebrew/bin:/usr/local/bin:/usr/bin'
                backup_env['PATH'] = (backup_env.get('PATH') or '') + ':' + extra_paths
                result = subprocess.run(
                    run_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=project_dir,
                    env=backup_env,
                )
            else:
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
            err_detail = (result.stderr or "").strip() or (result.stdout or "").strip()
            err_msg = f"Command failed with return code {result.returncode}"
            if err_detail:
                err_msg += f". {err_detail[:500]}"
            return {"success": False, "error": err_msg, "output": result.stderr or result.stdout}
            
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
                ["tail", "-f", log_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=project_dir,
                env=env,
                bufsize=1  # Line buffered
            )
            
            # Stream live output with immediate flushing
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                # Send each line immediately with proper encoding
                yield line.encode('utf-8').decode('utf-8')
            
        except Exception as e:
            yield f"Error: {str(e)}\n"
        finally:
            if 'process' in locals():
                process.terminate()
    
    return StreamingResponse(
        generate_log_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked"
        }
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
            ['bash', 'scripts/backup/package_user_data.sh'],
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
            # Allow filename-only for backup files (resolved under project/backup)
            file_name = request.get("file", "").strip()
            if file_name:
                project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                file_path = os.path.join(project_dir, "backup", file_name)
            else:
                return {"success": False, "error": "No file path or file name provided"}
        if file_path:
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
        conn = get_postgresql_connection()
        
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
        _main_logger.warning(f"Error getting current portfolio: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/portfolio/history")
async def get_portfolio_history(period: str = "1m"):
    """Get historical portfolio data from PostgreSQL for charting"""
    try:
        import psycopg2
        from datetime import datetime, timedelta
        
        # Connect to PostgreSQL
        conn = get_postgresql_connection()
        
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
        _main_logger.warning(f"Error getting portfolio history: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/bankroll/history")
async def get_bankroll_history(period: str = "1m"):
    """Get historical MTB base value from account_balance for Bankroll chart. Uses mtb_base_value with fallback to bankroll_current (cents to dollars)."""
    try:
        import psycopg2
        from datetime import datetime, timedelta

        conn = get_postgresql_connection()
        # One value per row: prefer mtb_base_value, fallback to bankroll_current for older rows
        select_val = "COALESCE(mtb_base_value, bankroll_current)"
        now = datetime.now()
        if period == "1d":
            today_5am = now.replace(hour=5, minute=0, second=0, microsecond=0)
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT timestamp, {select_val}
                    FROM users.account_balance_0001
                    WHERE timestamp < %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (today_5am.strftime('%Y-%m-%d %H:%M:%S'),))
                last_before_5am = cursor.fetchone()
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT timestamp, {select_val}
                    FROM users.account_balance_0001
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (today_5am.strftime('%Y-%m-%d %H:%M:%S'),))
                results = cursor.fetchall()
            if last_before_5am:
                results = [last_before_5am] + list(results)
        elif period == "1w":
            start_time = now - timedelta(weeks=1)
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT timestamp, {select_val}
                    FROM users.account_balance_0001
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                results = cursor.fetchall()
        elif period == "1m":
            start_time = now - timedelta(days=30)
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT timestamp, {select_val}
                    FROM users.account_balance_0001
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                results = cursor.fetchall()
        elif period == "1y":
            start_time = now - timedelta(days=365)
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT timestamp, {select_val}
                    FROM users.account_balance_0001
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                results = cursor.fetchall()
        else:  # "all"
            start_time = datetime(2020, 1, 1)
            with conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT timestamp, {select_val}
                    FROM users.account_balance_0001
                    WHERE timestamp >= %s
                    ORDER BY timestamp ASC
                """, (start_time.strftime('%Y-%m-%d %H:%M:%S'),))
                results = cursor.fetchall()

        conn.close()

        data = []
        for row in results:
            timestamp, value_cents = row
            data.append({
                "timestamp": timestamp if timestamp else None,
                "bankroll": float(value_cents) / 100 if value_cents is not None else 0  # cents to dollars
            })

        return {
            "status": "ok",
            "period": period,
            "count": len(data),
            "data": data
        }

    except Exception as e:
        _main_logger.warning(f"Error getting bankroll history: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/pnl/history")
async def get_pnl_history(period: str = "1m"):
    """Get cumulative PnL from trades_0001 for charting. Only counts trades where test_filter and paper_trade are FALSE.
    Returns time series starting at $0 for the selected window (1d=24h, 1w=7d, 1m=30d, 1y=365d, all)."""
    try:
        import psycopg2
        from datetime import datetime, timedelta

        conn = get_postgresql_connection()

        now = datetime.now()
        start_time = None
        if period == "1d":
            start_time = now - timedelta(hours=24)
        elif period == "1w":
            start_time = now - timedelta(days=7)
        elif period == "1m":
            start_time = now - timedelta(days=30)
        elif period == "1y":
            start_time = now - timedelta(days=365)
        else:  # "all"
            start_time = datetime(2020, 1, 1)

        start_date_sql = start_time.strftime("%Y-%m-%d")

        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COALESCE(
                    CASE WHEN closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE NULL END,
                    created_at
                ) AS ts, pnl
                FROM users.trades_0001
                WHERE (test_filter IS NULL OR test_filter = FALSE)
                  AND (paper_trade IS NULL OR paper_trade = FALSE)
                  AND LOWER(TRIM(status)) IN ('closed', 'settled')
                  AND pnl IS NOT NULL
                  AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN (closed_at::timestamptz)::date ELSE created_at::date END) >= %s::date
                ORDER BY ts ASC
            """, (start_date_sql,))
            rows = cursor.fetchall()

        conn.close()

        # Build cumulative series starting at $0
        data = []
        cumulative = 0.0
        # First point: start of window at $0
        data.append({"timestamp": start_date_sql + "T00:00:00", "pnl": 0.0})
        for (ts, pnl) in rows:
            pnl_val = float(pnl) if pnl is not None else 0.0
            cumulative += pnl_val
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            data.append({"timestamp": ts_str, "pnl": round(cumulative, 2)})

        return {
            "status": "ok",
            "period": period,
            "count": len(data),
            "data": data,
            "total_pnl": round(cumulative, 2)
        }

    except Exception as e:
        _main_logger.warning(f"Error getting PnL history: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/performance/realized")
async def get_performance_realized():
    """Realized PnL to-date for Day/Week/Month/Year: current period from period start through now,
    and prev_pnl for the same-length window in the previous period (e.g. yesterday 00:00–18:00 vs today 00:00–18:00).
    Only trades where paper_trade and test_filter are FALSE. All times America/New_York."""
    try:
        import psycopg2
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        conn = get_postgresql_connection()
        with conn.cursor() as tz_cur:
            tz_cur.execute("SET TIME ZONE 'America/New_York'")
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)
        today = now.date()

        # Period starts (00:00:00 Eastern, timezone-aware)
        def et_start(y, m, d):
            return datetime(y, m, d, 0, 0, 0, tzinfo=eastern)

        day_start = et_start(today.year, today.month, today.day)
        days_since_sunday = (today.weekday() + 1) % 7
        sunday = today - timedelta(days=days_since_sunday)
        week_start = et_start(sunday.year, sunday.month, sunday.day)
        month_start = et_start(today.year, today.month, 1)
        year_start = et_start(today.year, 1, 1)

        # Previous period starts (same calendar window, prior period)
        yesterday = today - timedelta(days=1)
        prev_sunday = sunday - timedelta(days=7)
        prev_month_first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        prev_year_first = today.replace(month=1, day=1, year=today.year - 1)

        prev_day_start = et_start(yesterday.year, yesterday.month, yesterday.day)
        prev_week_start = et_start(prev_sunday.year, prev_sunday.month, prev_sunday.day)
        prev_month_start = et_start(prev_month_first.year, prev_month_first.month, prev_month_first.day)
        prev_year_start = et_start(prev_year_first.year, prev_year_first.month, prev_year_first.day)

        periods = [
            ("day", day_start, prev_day_start),
            ("week", week_start, prev_week_start),
            ("month", month_start, prev_month_start),
            ("year", year_start, prev_year_start),
        ]

        result = {}
        with conn.cursor() as cursor:
            for key, period_start, prev_start in periods:
                # Current period: [period_start, now] (to-date)
                period_end = now
                cursor.execute("""
                    SELECT COALESCE(SUM(pnl), 0), COALESCE(SUM(ret_pct), 0), COALESCE(SUM(ret_pct_base), 0)
                    FROM users.trades_0001
                    WHERE (test_filter IS NULL OR test_filter = FALSE)
                      AND (paper_trade IS NULL OR paper_trade = FALSE)
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) >= %s
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) <= %s
                """, (period_start, period_end))
                row = cursor.fetchone()
                pnl = float(row[0]) if row and row[0] is not None else 0.0
                ret_pct_sum = float(row[1]) if row and row[1] is not None else None
                ret_pct_base_sum = float(row[2]) if row and row[2] is not None else None

                # Previous period: same-length window (prev_start through prev_start + (now - period_start))
                duration = period_end - period_start
                prev_end = prev_start + duration
                cursor.execute("""
                    SELECT COALESCE(SUM(pnl), 0)
                    FROM users.trades_0001
                    WHERE (test_filter IS NULL OR test_filter = FALSE)
                      AND (paper_trade IS NULL OR paper_trade = FALSE)
                      AND LOWER(TRIM(status)) IN ('closed', 'settled')
                      AND pnl IS NOT NULL
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) >= %s
                      AND (CASE WHEN closed_at IS NOT NULL AND closed_at ~ '^\\d{4}-\\d{2}-\\d{2}' THEN closed_at::timestamptz ELSE created_at END) <= %s
                """, (prev_start, prev_end))
                prev_row = cursor.fetchone()
                prev_pnl = float(prev_row[0]) if prev_row and prev_row[0] is not None else 0.0

                ret_pct = round(ret_pct_sum, 2) if ret_pct_sum is not None else None
                ret_pct_base = round(ret_pct_base_sum, 2) if ret_pct_base_sum is not None else None
                result[key] = {"pnl": round(pnl, 2), "ret_pct": ret_pct, "ret_pct_base": ret_pct_base, "prev_pnl": round(prev_pnl, 2)}

        conn.close()
        return {"status": "ok", "periods": result}

    except Exception as e:
        _main_logger.warning(f"Error getting performance realized: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/dashboard/preferences")
async def get_dashboard_preferences(mode: str = "prod"):
    """Get dashboard preferences for the current user"""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT portfolio_chart_view, monitor_view_mode, monitor_sort_by, allocation_view, portfolio_view
                FROM users.dashboard_preferences_0001 
                WHERE user_id = 1
            """)
            result = cursor.fetchone()
            
        conn.close()
        
        if result:
            return {
                "status": "ok",
                "portfolio_chart_view": result[0],
                "monitor_view_mode": result[1] if result[1] else "tile",
                "monitor_sort_by": result[2] if result[2] else "name",
                "allocation_view": result[3] if result[3] else "pie",
                "portfolio_view": result[4] if result[4] else "portfolio"
            }
        else:
            return {
                "status": "ok",
                "portfolio_chart_view": "all",
                "monitor_view_mode": "tile",
                "monitor_sort_by": "name",
                "allocation_view": "pie",
                "portfolio_view": "portfolio"
            }
            
    except Exception as e:
        _main_logger.warning(f"Error getting dashboard preferences: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/dashboard/preferences")
async def save_dashboard_preferences(request: Request):
    """Save dashboard preferences for the current user"""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        
        data = await request.json()
        _main_logger.debug(f"[DASHBOARD PREFERENCES] Received data: {data}")
        portfolio_chart_view = data.get("portfolio_chart_view", "all")
        monitor_view_mode = data.get("monitor_view_mode", "tile")
        monitor_sort_by = data.get("monitor_sort_by", "name")
        allocation_view = data.get("allocation_view", "pie")
        portfolio_view = data.get("portfolio_view", "portfolio")
        if portfolio_view not in ("bankroll", "portfolio", "pnl"):
            portfolio_view = "portfolio"
        _main_logger.debug(f"[DASHBOARD PREFERENCES] Extracted values: portfolio_chart_view={portfolio_chart_view}, monitor_view_mode={monitor_view_mode}, monitor_sort_by={monitor_sort_by}, allocation_view={allocation_view}, portfolio_view={portfolio_view}")
        
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO users.dashboard_preferences_0001 (user_id, portfolio_chart_view, monitor_view_mode, monitor_sort_by, allocation_view, portfolio_view, updated_at)
                VALUES (1, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) 
                DO UPDATE SET 
                    portfolio_chart_view = EXCLUDED.portfolio_chart_view,
                    monitor_view_mode = EXCLUDED.monitor_view_mode,
                    monitor_sort_by = EXCLUDED.monitor_sort_by,
                    allocation_view = EXCLUDED.allocation_view,
                    portfolio_view = EXCLUDED.portfolio_view,
                    updated_at = CURRENT_TIMESTAMP
            """, (portfolio_chart_view, monitor_view_mode, monitor_sort_by, allocation_view, portfolio_view))
            
        conn.commit()
        conn.close()
        
        _main_logger.debug(f"[DASHBOARD PREFERENCES] Successfully saved preferences to database")
        return {
            "status": "ok",
            "message": "Preferences saved successfully"
        }
            
    except Exception as e:
        _main_logger.warning(f"Error saving dashboard preferences: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/total_position")
async def get_total_position():
    """Get total_position from first row of monitor_list_0001"""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        
        with conn.cursor() as cursor:
            cursor.execute("SELECT total_position FROM users.monitor_list_0001 ORDER BY id LIMIT 1")
            result = cursor.fetchone()
            
        conn.close()
        
        if result and result[0] is not None:
            return {"total_position": result[0]}
        else:
            return {"total_position": 0}
            
    except Exception as e:
        return {"total_position": 0}

@app.get("/api/monitors")
async def get_monitors(user_id: str = "user_0001"):
    """Get monitors list for the specified user"""
    try:
        from backend.core.config.database import get_postgresql_connection
        conn = get_postgresql_connection()
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT 
                    id,
                    name,
                    symbol,
                    strategy,
                    auto_trade,
                    auto_trade_status,
                    trades,
                    win_loss,
                    ret_pct,
                    pnl,
                    bankroll_allotment_pct,
                    status,
                    dashboard_order,
                    win_streak,
                    loss_prevention,
                    created,
                    cooldown_timer,
                    current_contract,
                    current_weekly_cycle,
                    current_performance_modifier,
                    current_max_pct_exposure,
                    performance_based_allocation,
                    paper_trade,
                    market
                FROM users.monitor_list_{user_number}
                WHERE status != 'ARCHIVED'
                ORDER BY dashboard_order, id
            """)
            
            results = cursor.fetchall()
            
        conn.close()
        
        # Transform database results to frontend format
        monitors = []
        for row in results:
            (
                monitor_id,
                name,
                symbol,
                strategy,
                auto_trade,
                auto_trade_status,
                trades,
                win_loss,
                ret_pct,
                pnl,
                bankroll_allotment_pct,
                status,
                dashboard_order,
                win_streak,
                loss_prevention,
                created,
                cooldown_timer,
                current_contract,
                current_weekly_cycle,
                current_performance_modifier,
                current_max_pct_exposure,
                performance_based_allocation,
                paper_trade,
                market,
            ) = row
            
            # Calculate uptime from created timestamp
            from datetime import datetime
            uptime_str = "0d 0h 0m"
            if created:
                now = datetime.now()
                if isinstance(created, str):
                    created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                else:
                    created_dt = created
                
                # Handle timezone if needed
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.now().tzinfo)
                
                diff = now - created_dt.replace(tzinfo=None)
                days = diff.days
                hours = diff.seconds // 3600
                minutes = (diff.seconds % 3600) // 60
                uptime_str = f"{days}d {hours}h {minutes}m"
            
            # Format data for frontend - use exact database values
            formatted_monitor = {
                "id": f"mon_{user_number}_{monitor_id}",
                "symbol": symbol,
                "strategy": strategy,  # Use exact database value
                "status": status,
                "autoTrade": auto_trade,
                "trades": trades,
                "winRate": f"{win_loss}%" if win_loss is not None else "0%",
                "return": f"{ret_pct}%" if ret_pct is not None else "0%",
                "pnl": f"${pnl:,.0f}" if pnl is not None else "$0",
                "uptime": uptime_str,
                "name": name,  # Use exact database value
                "bankroll_allotment": bankroll_allotment_pct,
                "auto_trade_status": auto_trade_status,
                "dashboard_order": dashboard_order or 0,
                "win_streak": win_streak or 0,
                "loss_prevention": loss_prevention,
                "cooldown_timer": cooldown_timer or 0,
                "current_contract": current_contract,
                "current_weekly_cycle": current_weekly_cycle,
                "current_performance_modifier": current_performance_modifier,
                "current_max_pct_exposure": current_max_pct_exposure,
                "performance_based_allocation": performance_based_allocation,
                "paper_trade": paper_trade or False,
                "market": (market or "").strip().lower() if market else None,
            }
            monitors.append(formatted_monitor)
        
        # Add the NEW_MONITOR entry
        monitors.append({
            "id": "NEW_MONITOR",
            "symbol": "+",
            "strategy": "NEW MONITOR",
            "status": "new",
            "autoTrade": False,
            "trades": "",
            "winRate": "",
            "return": "",
            "pnl": "",
            "uptime": "",
            "name": "NEW_MONITOR",
            "bankroll_allotment": 0,
            "auto_trade_status": "inactive"
        })
        
        return {
            "status": "ok",
            "user_id": user_id,
            "count": len(monitors) - 1,  # Exclude NEW_MONITOR from count
            "monitors": monitors
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/symbols")
async def get_symbols():
    """Get available symbols for the symbol picker dropdown"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT symbol
            FROM live_data.symbols_list
            ORDER BY symbol
        """)
        
        results = cursor.fetchall()
        conn.close()
        
        symbols = []
        for row in results:
            symbol = row[0]
            symbols.append(symbol)
        
        return {
            "status": "ok",
            "count": len(symbols),
            "symbols": symbols
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/monitor/{monitor_id}")
async def get_monitor_details(monitor_id: int, user_id: str = "user_0001"):
    """Get details for a specific monitor"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, name, symbol, strategy, position_size, multiplier, total_position, position_type, bankroll_allotment_total, auto_trade, paper_trade, market
            FROM users.monitor_list_{user_number}
            WHERE id = %s AND status = 'active'
        """, (monitor_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            monitor_id, name, symbol, strategy, position_size, multiplier, total_position, position_type, bankroll_allotment_total, auto_trade, paper_trade, market = result
            mkt = (market or "").strip().lower()
            if mkt not in ("hourly", "15m"):
                mkt = None
            return {
                "status": "ok",
                "monitor": {
                    "id": monitor_id,
                    "name": name,
                    "symbol": symbol,
                    "strategy": strategy,
                    "position_size": position_size,
                    "multiplier": multiplier,
                    "total_position": total_position,
                    "position_type": position_type,
                    "bankroll_allotment_total": bankroll_allotment_total,
                    "auto_trade": auto_trade,
                    "paper_trade": paper_trade or False,
                    "market": mkt,
                }
            }
        else:
            return {
                "status": "error",
                "message": "Monitor not found"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/monitor/{monitor_id}/update")
async def update_monitor_details(monitor_id: int, request: dict, user_id: str = "user_0001"):
    """Update details for a specific monitor"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        # Get update data from request
        symbol = request.get("symbol")
        strategy = request.get("strategy")
        position_size = request.get("position_size")
        multiplier = request.get("multiplier")
        total_position = request.get("total_position")
        position_type = request.get("position_type")
        
        if not symbol and not strategy and position_size is None and multiplier is None and total_position is None and position_type is None:
            return {
                "status": "error",
                "message": "No fields to update"
            }
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        
        # Build update query dynamically
        update_fields = []
        values = []
        
        if symbol is not None:
            update_fields.append("symbol = %s")
            values.append(symbol)
        
        if strategy is not None:
            update_fields.append("strategy = %s")
            values.append(strategy)
        
        if position_size is not None:
            update_fields.append("position_size = %s")
            values.append(position_size)
        
        if multiplier is not None:
            update_fields.append("multiplier = %s")
            values.append(multiplier)
        
        if total_position is not None:
            update_fields.append("total_position = %s")
            values.append(total_position)
        
        if position_type is not None:
            update_fields.append("position_type = %s")
            values.append(position_type)
        
        values.append(monitor_id)
        
        query = f"""
            UPDATE users.monitor_list_{user_number}
            SET {', '.join(update_fields)}
            WHERE id = %s AND status = 'active'
        """
        
        cursor.execute(query, values)
        
        if cursor.rowcount == 0:
            conn.close()
            return {
                "status": "error",
                "message": "Monitor not found or no changes made"
            }
        
        conn.commit()
        conn.close()
        
        return {
            "status": "ok",
            "message": "Monitor updated successfully"
        }
            
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/monitors/names")
async def get_monitor_names(user_id: str = "user_0001"):
    """Get just the monitor names for the monitor picker dropdown"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, name, symbol, market
            FROM users.monitor_list_{user_number}
            WHERE status = 'active'
            ORDER BY name
        """)
        results = cursor.fetchall()
        conn.close()
        monitors = []
        for row in results:
            monitor_id, name, symbol, market = row
            mkt = (market or "").strip().lower() if market else None
            if mkt not in ("hourly", "15m"):
                mkt = None
            monitors.append({
                "id": monitor_id,
                "name": name,
                "symbol": symbol,
                "market": mkt
            })
        
        return {
            "status": "ok",
            "user_id": user_id,
            "count": len(monitors),
            "monitors": monitors
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/trades/monitors")
async def get_trade_monitors(user_id: str = "user_0001"):
    """Get monitor names from the trades table for trade history filtering"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT DISTINCT monitor
            FROM users.trades_{user_number}
            WHERE monitor IS NOT NULL AND monitor != ''
            ORDER BY monitor
        """)
        
        results = cursor.fetchall()
        conn.close()
        
        # Transform to simple format for dropdown
        monitors = []
        for row in results:
            monitor_name = row[0]
            monitors.append({
                "name": monitor_name
            })
        
        return {
            "status": "ok",
            "user_id": user_id,
            "count": len(monitors),
            "monitors": monitors
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/monitors/allocation")
async def get_monitors_allocation(user_id: str = "user_0001"):
    """Get bankroll allocation data for active monitors"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        with conn.cursor() as cursor:
            # Get active monitors with their bankroll allocations
            cursor.execute(f"""
                SELECT 
                    id,
                    name,
                    symbol,
                    strategy,
                    bankroll_allotment_pct,
                    bankroll_allotment_total,
                    status
                FROM users.monitor_list_{user_number}
                WHERE status = 'active' AND bankroll_allotment_total > 0
                ORDER BY bankroll_allotment_total DESC, id
            """)
            
            monitor_results = cursor.fetchall()
            
            # Get total bankroll from account_balance (stored in cents)
            cursor.execute(f"""
                SELECT bankroll_current, portfolio
                FROM users.account_balance_{user_number}
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            
            balance_result = cursor.fetchone()
            bankroll_value = balance_result[0] if balance_result and balance_result[0] else 0
            portfolio_value = balance_result[1] if balance_result and balance_result[1] else 0
            
            # Use bankroll_current if available, otherwise portfolio (both in cents)
            total_bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value
            total_bankroll_dollars = total_bankroll_cents / 100  # Convert cents to dollars
            
        conn.close()
        
        # Transform database results to frontend format
        allocations = []
        for row in monitor_results:
            monitor_id, name, symbol, strategy, bankroll_allotment_pct, bankroll_allotment_total, status = row
            
            # bankroll_allotment_pct is in decimal (0.99 = 99%)
            # bankroll_allotment_total is in cents (219653 = $2,196.53)
            percentage = float(bankroll_allotment_pct) * 100  # Convert decimal to percentage
            dollar_amount = float(bankroll_allotment_total) / 100  # Convert cents to dollars
            
            allocations.append({
                "id": f"mon_{user_number}_{monitor_id}",
                "name": name,
                "symbol": symbol,
                "strategy": strategy,
                "bankroll_pct": round(percentage, 2),
                "dollar_amount": round(dollar_amount, 2),
                "total_bankroll": total_bankroll_dollars
            })
        
        return {
            "status": "ok",
            "allocations": allocations,
            "total_bankroll": total_bankroll_dollars
        }
        
    except Exception as e:
        _main_logger.warning(f"Error getting monitors allocation: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/monitors/allocation/update")
async def update_monitors_allocation(request: dict):
    """Update bankroll allocation percentages for monitors"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        user_id = request.get("user_id", "user_0001")
        updates = request.get("updates", [])
        
        if not updates:
            return {"status": "error", "message": "No updates provided"}
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        with conn.cursor() as cursor:
            # Get current total bankroll to calculate new dollar amounts
            cursor.execute(f"""
                SELECT bankroll_current, portfolio
                FROM users.account_balance_{user_number}
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            
            balance_result = cursor.fetchone()
            bankroll_value = balance_result[0] if balance_result and balance_result[0] else 0
            portfolio_value = balance_result[1] if balance_result and balance_result[1] else 0
            
            # Use bankroll_current if available, otherwise portfolio (both in cents)
            total_bankroll_cents = bankroll_value if bankroll_value > 0 else portfolio_value
            
            # Update each monitor's allocation
            for update in updates:
                monitor_id = update.get("id", "").replace(f"mon_{user_number}_", "")
                new_percentage = update.get("percentage", 0)
                
                if not monitor_id or new_percentage < 0:
                    continue
                
                # Convert percentage to decimal (99% -> 0.99)
                new_decimal = new_percentage / 100
                
                # Calculate new dollar amount in cents
                new_dollar_amount_cents = int(total_bankroll_cents * new_decimal)
                
                # Update the monitor's allocation
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET 
                        bankroll_allotment_pct = %s,
                        bankroll_allotment_total = %s
                    WHERE id = %s AND status = 'active'
                """, (new_decimal, new_dollar_amount_cents, monitor_id))
                
                # CRITICAL: Recalculate total_position after allotment change
                # Get current monitor settings for calculation
                cursor.execute(f"""
                    SELECT position_size, position_type, multiplier, current_max_pct_exposure 
                    FROM users.monitor_list_{user_number} 
                    WHERE id = %s
                """, (monitor_id,))
                
                pos_result = cursor.fetchone()
                if pos_result:
                    position_size, position_type, multiplier, current_max_pct_exposure = pos_result
                    
                    multiplier_value = float(multiplier or 0)
                    max_pct_cap = None
                    try:
                        if current_max_pct_exposure is not None:
                            max_pct_cap = float(current_max_pct_exposure)
                    except (TypeError, ValueError):
                        max_pct_cap = None
                    
                    if multiplier_value == 0:
                        new_total_position = 1
                    elif position_type == 'percent':
                        # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                        allotment_dollars = new_dollar_amount_cents / 100
                        base_pct = (position_size or 0) / 100.0
                        effective_pct = base_pct * multiplier_value
                        if max_pct_cap is not None and max_pct_cap > 0:
                            effective_pct = min(effective_pct, max_pct_cap)
                        new_total_position = int(round(allotment_dollars * effective_pct))
                        if new_total_position < 1:
                            new_total_position = 1
                    else:
                        # For contracts: position_size * multiplier
                        new_total_position = int(position_size * multiplier_value)
                    
                    # Update total_position
                    cursor.execute(f"""
                        UPDATE users.monitor_list_{user_number} 
                        SET total_position = %s 
                        WHERE id = %s
                    """, (new_total_position, monitor_id))
                    
                    _main_logger.debug(f"Updated monitor {monitor_id}: {new_percentage}% (${new_dollar_amount_cents/100:.2f}) -> total_position: {new_total_position}")
                    
                    # Send WebSocket notification to frontend about total_position update
                    try:
                        import requests
                        requests.post('http://localhost:3000/api/broadcast_monitor_total_position', json={
                            'monitor_id': monitor_id,
                            'total_position': new_total_position,
                            'multiplier': multiplier_value
                        }, timeout=1)
                    except Exception as e:
                        _main_logger.debug(f"Failed to send total_position update notification: {str(e)}")
                else:
                    _main_logger.debug(f"Updated monitor {monitor_id}: {new_percentage}% (${new_dollar_amount_cents/100:.2f}) - no position data found")
        
        conn.commit()
        conn.close()
        
        return {
            "status": "ok",
            "message": f"Updated {len(updates)} monitor allocations"
        }
        
    except Exception as e:
        _main_logger.warning(f"Error updating monitors allocation: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/monitors/update-order")
async def update_monitors_order(request: dict):
    """Update the dashboard order of monitors"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        user_id = request.get("user_id", "user_0001")
        monitor_orders = request.get("monitor_orders", [])
        
        if not monitor_orders:
            return {"status": "error", "message": "No monitor orders provided"}
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        cursor = conn.cursor()
        
        # Update each monitor's dashboard_order
        for order_data in monitor_orders:
            monitor_id = order_data.get("monitor_id")
            new_order = order_data.get("order")
            
            if monitor_id and new_order is not None:
                # Extract the numeric ID from the monitor_id (e.g., mon_0001_10001 -> 10001 or MON_0001_10001 -> 10001)
                if "_" in monitor_id and (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")):
                    numeric_id = monitor_id.split("_")[-1]
                else:
                    numeric_id = monitor_id
                
                _main_logger.debug(f"[MONITOR ORDER] Updating monitor {monitor_id} -> numeric_id: {numeric_id}, order: {new_order}")
                
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET dashboard_order = %s
                    WHERE id = %s
                """, (new_order, numeric_id))
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "message": "Monitor order updated successfully"}
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/toggle-auto-trade")
async def toggle_auto_trade(request: dict):
    """Toggle auto_trade boolean value for a specific monitor"""
    try:
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        auto_trade = request.get("auto_trade")
        user_id = request.get("user_id", "user_0001")
        
        if not monitor_id or auto_trade is None:
            return {"status": "error", "message": "Missing monitor_id or auto_trade parameter"}
        
        # Extract user number and monitor ID from monitor_id
        # Handle multiple formats: MON_0001_10001, mon_0001_10001, or just 10001
        if (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")) and "_" in monitor_id:
            parts = monitor_id.split("_")
            if len(parts) >= 3:
                user_number = parts[1]
                db_monitor_id = parts[2]
            else:
                return {"status": "error", "message": "Invalid monitor ID format"}
        elif monitor_id.isdigit():
            # Handle numeric ID format (e.g., "10010")
            user_number = "0001"  # Default user number
            db_monitor_id = monitor_id
        else:
            return {"status": "error", "message": "Invalid monitor ID format"}
        
        # Update the database directly
        try:
            from backend.core.config.database import get_postgresql_connection
            conn = get_postgresql_connection()
            
            with conn.cursor() as cursor:
                # Update ONLY auto_trade boolean - do NOT change auto_trade_status
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET auto_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (auto_trade, db_monitor_id))
                
                if cursor.rowcount == 0:
                    conn.close()
                    return {"status": "error", "message": "Monitor not found"}
                
            conn.commit()
            conn.close()
            
            _main_logger.debug(f"[MAIN] ✅ Updated monitor {monitor_id} auto_trade to {auto_trade}")
            
        except Exception as e:
            _main_logger.warning(f"[MAIN] ❌ Error updating database: {e}")
            return {"status": "error", "message": f"Database error: {str(e)}"}
        
        # Broadcast the auto trade toggle to all connected WebSocket clients
        try:
            message = {
                "type": "auto_trade_toggled",
                "monitor_id": monitor_id,
                "auto_trade": auto_trade,
                "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}"
            }
            
            _main_logger.debug(f"[MAIN] 🔔 Broadcasting auto trade toggle: {message}")
            _main_logger.debug(f"[MAIN] 🔔 Connected WebSocket clients: {len(connected_clients)}")
            
            # Send to preferences WebSocket clients
            for websocket in connected_clients.copy():
                try:
                    await websocket.send_text(json.dumps(message))
                    _main_logger.debug(f"[MAIN] ✅ Message sent to WebSocket client")
                except Exception as e:
                    _main_logger.warning(f"Error sending to WebSocket client: {e}")
                    connected_clients.discard(websocket)
            
            _main_logger.debug(f"[MAIN] ✅ Auto trade toggle broadcasted to {len(connected_clients)} WebSocket clients")
        except Exception as e:
            _main_logger.debug(f"[MAIN] ⚠️ Warning: Failed to broadcast auto trade toggle: {e}")
        
        return {"status": "ok", "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}"}
        
    except Exception as e:
        _main_logger.warning(f"Error in toggle auto trade: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/toggle-paper-trade")
async def toggle_paper_trade(request: Request):
    """Toggle paper_trade boolean value for a specific monitor"""
    try:
        # Extract parameters from request body
        data = await request.json()
        monitor_id = data.get("monitor_id")
        paper_trade = data.get("paper_trade")
        user_id = data.get("user_id", "user_0001")
        
        if not monitor_id or paper_trade is None:
            return {"status": "error", "message": "Missing monitor_id or paper_trade parameter"}
        
        # Extract user number and monitor ID from monitor_id
        # Handle multiple formats: MON_0001_10001, mon_0001_10001, or just 10001
        if (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")) and "_" in monitor_id:
            parts = monitor_id.split("_")
            if len(parts) >= 3:
                user_number = parts[1]
                db_monitor_id = parts[2]
            else:
                return {"status": "error", "message": "Invalid monitor ID format"}
        elif monitor_id.isdigit():
            # Handle numeric ID format (e.g., "10010")
            user_number = "0001"  # Default user number
            db_monitor_id = monitor_id
        else:
            return {"status": "error", "message": "Invalid monitor ID format"}
        
        # Update the database directly
        try:
            from backend.core.config.database import get_postgresql_connection
            conn = get_postgresql_connection()
            
            with conn.cursor() as cursor:
                # Update paper_trade boolean
                cursor.execute(f"""
                    UPDATE users.monitor_list_{user_number}
                    SET paper_trade = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (paper_trade, db_monitor_id))
                
                if cursor.rowcount == 0:
                    conn.close()
                    return {"status": "error", "message": "Monitor not found"}
                
            conn.commit()
            conn.close()
            
            _main_logger.debug(f"[MAIN] ✅ Updated monitor {monitor_id} paper_trade to {paper_trade}")
            
            # Broadcast the change to all connected WebSocket clients
            message = {
                "type": "paper_trade_toggled",
                "monitor_id": monitor_id,  # Keep original format (MON_0001_10001)
                "paper_trade": paper_trade
            }
            
            # Send to preferences WebSocket clients
            for websocket in connected_clients.copy():
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    _main_logger.warning(f"Error sending paper_trade update to WebSocket client: {e}")
                    connected_clients.discard(websocket)
            
            _main_logger.debug(f"[MAIN] ✅ Paper trade change broadcasted to {len(connected_clients)} clients")
            
            return {"status": "ok", "message": "Paper trade updated successfully"}
            
        except Exception as e:
            _main_logger.warning(f"[MAIN] ❌ Error updating database: {e}")
            return {"status": "error", "message": f"Database error: {str(e)}"}
            
    except Exception as e:
        _main_logger.warning(f"[MAIN] ❌ Error toggling paper trade: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/update_monitor_position")
async def update_monitor_position(request: Request):
    """Proxy endpoint to forward monitor position updates to monitor_manager"""
    try:
        data = await request.json()
        monitor_id = data.get("monitor_id")
        position_size = data.get("position_size")
        position_type = data.get("position_type")
        multiplier = data.get("multiplier")
        
        if monitor_id is None or position_size is None or position_type is None or multiplier is None:
            return {"error": "Missing required fields"}
        
        _main_logger.debug(f"[PROXY] Forwarding to monitor_manager: {data}")
        
        # Forward to monitor_manager
        response = requests.post(
            f"http://localhost:{get_port('monitor_manager')}/api/update_monitor_position",
            json=data,
            timeout=30
        )
        
        _main_logger.debug(f"[PROXY] Monitor manager response: {response.status_code}")
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"Monitor manager returned status {response.status_code}"}, response.status_code
            
    except Exception as e:
        _main_logger.debug(f"[PROXY] Error: {e}")
        return {"error": str(e)}, 500

@app.post("/api/monitor/archive")
async def archive_monitor(request: dict):
    """Archive a monitor by setting auto_trade to FALSE and status to ARCHIVED"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")
        user_id = request.get("user_id", "user_0001")
        
        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}
        
        # Extract user number and monitor ID from monitor_id
        # Handle multiple formats: MON_0001_10001, mon_0001_10001, or just 10001
        if (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")) and "_" in monitor_id:
            parts = monitor_id.split("_")
            if len(parts) >= 3:
                user_number = parts[1]
                db_monitor_id = parts[2]
            else:
                return {"status": "error", "message": "Invalid monitor ID format"}
        elif monitor_id.isdigit():
            # Handle numeric ID format (e.g., "10010")
            user_number = "0001"  # Default user number
            db_monitor_id = monitor_id
        else:
            return {"status": "error", "message": "Invalid monitor ID format"}
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        with conn.cursor() as cursor:
            # First, set auto_trade to FALSE to stop trading
            cursor.execute(f"""
                UPDATE users.monitor_list_{user_number}
                SET auto_trade = FALSE
                WHERE id = %s
            """, (db_monitor_id,))
            
            if cursor.rowcount == 0:
                conn.close()
                return {"status": "error", "message": "Monitor not found"}
            
            # Then, set status to ARCHIVED to hide from dashboard
            cursor.execute(f"""
                UPDATE users.monitor_list_{user_number}
                SET status = 'ARCHIVED'
                WHERE id = %s
            """, (db_monitor_id,))

            performance_table = f"monitor_cycle_performance_{user_number}_{db_monitor_id}"
            cursor.execute(
                "SELECT to_regclass(%s)",
                (f"users.{performance_table}",)
            )
            table_exists = cursor.fetchone()[0]

            if table_exists:
                cursor.execute("CREATE SCHEMA IF NOT EXISTS archive")
                cursor.execute(
                    "SELECT to_regclass(%s)",
                    (f"archive.{performance_table}",)
                )
                archived_exists = cursor.fetchone()[0]
                if archived_exists:
                    cursor.execute(
                        sql.SQL("DROP TABLE {}.{}")
                        .format(sql.Identifier("archive"), sql.Identifier(performance_table))
                    )

                cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} SET SCHEMA archive")
                    .format(sql.Identifier("users"), sql.Identifier(performance_table))
                )
            
        conn.commit()
        conn.close()
        
        _main_logger.debug(f"[ARCHIVE] Monitor {monitor_name} (ID: {monitor_id}) archived successfully")
        
        # Broadcast monitor list update to all connected WebSocket clients
        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "archived"
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                _main_logger.warning(f"Error sending monitor list update to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[ARCHIVE] ✅ Monitor list update broadcasted to {len(connected_clients)} clients")
        
        return {"status": "ok", "message": f"Monitor {monitor_name} archived successfully"}
        
    except Exception as e:
        _main_logger.warning(f"Error archiving monitor: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/deactivate")
async def deactivate_monitor(request: dict):
    """Turn off a monitor: status = 'inactive' (stops AES/ATS scripts); also set auto_trade FALSE and auto_trade_status 'off' for UI/auto-trading."""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")
        user_id = request.get("user_id", "user_0001")
        
        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}
        
        # Extract user number and monitor ID from monitor_id
        # Handle multiple formats: MON_0001_10001, mon_0001_10001, or just 10001
        if (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")) and "_" in monitor_id:
            parts = monitor_id.split("_")
            if len(parts) >= 3:
                user_number = parts[1]
                db_monitor_id = parts[2]
            else:
                return {"status": "error", "message": "Invalid monitor ID format"}
        elif monitor_id.isdigit():
            # Handle numeric ID format (e.g., "10010")
            user_number = "0001"  # Default user number
            db_monitor_id = monitor_id
        else:
            return {"status": "error", "message": "Invalid monitor ID format"}
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        with conn.cursor() as cursor:
            # status = 'inactive' → AES/ATS for this monitor are torn down. auto_trade/auto_trade_status are for auto-trading only.
            cursor.execute(f"""
                UPDATE users.monitor_list_{user_number}
                SET auto_trade = FALSE, status = 'inactive', auto_trade_status = 'off'
                WHERE id = %s
            """, (db_monitor_id,))
            
            if cursor.rowcount == 0:
                conn.close()
                return {"status": "error", "message": "Monitor not found"}
            
        conn.commit()
        conn.close()
        
        _main_logger.debug(f"[DEACTIVATE] Monitor {monitor_name} (ID: {monitor_id}) deactivated successfully")

        # Trigger an immediate monitor process sync so AES/ATS for this monitor
        # are torn down promptly. Try monitor_manager HTTP first; then always run
        # sync in-process so teardown happens even if monitor_manager is unreachable.
        try:
            import requests
            from backend.core.port_config import get_port

            monitor_manager_port = get_port("monitor_manager")
            sync_resp = requests.post(
                f"http://localhost:{monitor_manager_port}/api/sync_monitor_processes",
                json={"source": "main_app_deactivate", "monitor_id": monitor_id},
                timeout=10,
            )
            if not sync_resp.ok:
                _main_logger.warning(
                    f"[DEACTIVATE] ⚠️ sync_monitor_processes returned {sync_resp.status_code}: {sync_resp.text}"
                )
        except Exception as e:
            _main_logger.warning(f"[DEACTIVATE] ⚠️ Failed to trigger monitor process sync via HTTP: {e}")

        # Always run sync in-process so AES/ATS are torn down regardless of monitor_manager.
        try:
            import subprocess
            from backend.util.paths import get_project_root, get_supervisorctl_path, get_supervisor_config_path

            proot = get_project_root()
            gen_script = os.path.join(proot, "scripts", "config", "generate_unified_supervisor_config.py")
            if os.path.isfile(gen_script):
                env = os.environ.copy()
                env.setdefault("PYTHONPATH", proot)
                env.setdefault("REC_PROJECT_ROOT", proot)
                r0 = subprocess.run(
                    [sys.executable, gen_script],
                    cwd=proot,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r0.returncode != 0:
                    _main_logger.warning(f"[DEACTIVATE] ⚠️ generate_unified_supervisor_config failed: {r0.stderr or r0.stdout}")
                else:
                    ctl = get_supervisorctl_path()
                    cfg = get_supervisor_config_path()
                    for cmd in ["reread", "update"]:
                        r = subprocess.run([ctl, "-c", cfg, cmd], cwd=proot, capture_output=True, text=True, timeout=10)
                        if r.returncode != 0:
                            _main_logger.warning(f"[DEACTIVATE] ⚠️ supervisorctl {cmd} failed: {r.stderr or r.stdout}")
                            break
                    else:
                        _main_logger.debug("[DEACTIVATE] In-process monitor process sync completed")
            else:
                _main_logger.warning(f"[DEACTIVATE] ⚠️ generate script not found: {gen_script}")
        except Exception as e:
            _main_logger.warning(f"[DEACTIVATE] ⚠️ In-process monitor process sync failed: {e}")

        # Broadcast monitor list update to all connected WebSocket clients
        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "deactivated"
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                _main_logger.warning(f"Error sending monitor list update to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[DEACTIVATE] ✅ Monitor list update broadcasted to {len(connected_clients)} clients")
        
        return {"status": "ok", "message": f"Monitor {monitor_name} deactivated successfully"}
        
    except Exception as e:
        _main_logger.warning(f"Error deactivating monitor: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/monitor/activate")
async def activate_monitor(request: dict):
    """Turn on a monitor: status = 'active' so AES/ATS script iterations are started. Does not change auto_trade/auto_trade_status."""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        # Extract parameters from request body
        monitor_id = request.get("monitor_id")
        monitor_name = request.get("monitor_name")
        user_id = request.get("user_id", "user_0001")
        
        if not monitor_id or not monitor_name:
            return {"status": "error", "message": "Missing monitor_id or monitor_name parameter"}
        
        # Extract user number and monitor ID from monitor_id
        # Handle multiple formats: MON_0001_10001, mon_0001_10001, or just 10001
        if (monitor_id.startswith("MON_") or monitor_id.startswith("mon_")) and "_" in monitor_id:
            parts = monitor_id.split("_")
            if len(parts) >= 3:
                user_number = parts[1]
                db_monitor_id = parts[2]
            else:
                return {"status": "error", "message": "Invalid monitor ID format"}
        elif monitor_id.isdigit():
            # Handle numeric ID format (e.g., "10010")
            user_number = "0001"  # Default user number
            db_monitor_id = monitor_id
        else:
            return {"status": "error", "message": "Invalid monitor ID format"}
        
        conn = get_postgresql_connection()
        if not conn:
            return {"status": "error", "message": "Database connection failed"}
        
        with conn.cursor() as cursor:
            # Set status to 'active' to activate the monitor
            cursor.execute(f"""
                UPDATE users.monitor_list_{user_number}
                SET status = 'active'
                WHERE id = %s
            """, (db_monitor_id,))
            
            if cursor.rowcount == 0:
                conn.close()
                return {"status": "error", "message": "Monitor not found"}
            
        conn.commit()
        conn.close()
        
        _main_logger.debug(f"[ACTIVATE] Monitor {monitor_name} (ID: {monitor_id}) activated successfully")

        # Trigger sync so AES/ATS for this monitor are spun up. Try monitor_manager HTTP first;
        # then always run sync in-process so spawn happens even if monitor_manager is unreachable.
        try:
            import requests
            from backend.core.port_config import get_port

            monitor_manager_port = get_port("monitor_manager")
            sync_resp = requests.post(
                f"http://localhost:{monitor_manager_port}/api/sync_monitor_processes",
                json={"source": "main_app_activate", "monitor_id": monitor_id},
                timeout=10,
            )
            if not sync_resp.ok:
                _main_logger.warning(
                    f"[ACTIVATE] ⚠️ sync_monitor_processes returned {sync_resp.status_code}: {sync_resp.text}"
                )
        except Exception as e:
            _main_logger.warning(f"[ACTIVATE] ⚠️ Failed to trigger monitor process sync via HTTP: {e}")

        # Always run sync in-process so AES/ATS are spawned regardless of monitor_manager.
        try:
            import subprocess
            from backend.util.paths import get_project_root, get_supervisorctl_path, get_supervisor_config_path

            proot = get_project_root()
            gen_script = os.path.join(proot, "scripts", "config", "generate_unified_supervisor_config.py")
            if os.path.isfile(gen_script):
                env = os.environ.copy()
                env.setdefault("PYTHONPATH", proot)
                env.setdefault("REC_PROJECT_ROOT", proot)
                r0 = subprocess.run(
                    [sys.executable, gen_script],
                    cwd=proot,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r0.returncode != 0:
                    _main_logger.warning(f"[ACTIVATE] ⚠️ generate_unified_supervisor_config failed: {r0.stderr or r0.stdout}")
                else:
                    ctl = get_supervisorctl_path()
                    cfg = get_supervisor_config_path()
                    for cmd in ["reread", "update"]:
                        r = subprocess.run([ctl, "-c", cfg, cmd], cwd=proot, capture_output=True, text=True, timeout=10)
                        if r.returncode != 0:
                            _main_logger.warning(f"[ACTIVATE] ⚠️ supervisorctl {cmd} failed: {r.stderr or r.stdout}")
                            break
                    else:
                        _main_logger.debug("[ACTIVATE] In-process monitor process sync completed")
            else:
                _main_logger.warning(f"[ACTIVATE] ⚠️ generate script not found: {gen_script}")
        except Exception as e:
            _main_logger.warning(f"[ACTIVATE] ⚠️ In-process monitor process sync failed: {e}")

        # Broadcast monitor list update to all connected WebSocket clients
        message = {
            "type": "monitor_list_updated",
            "monitor_id": monitor_id,
            "action": "activated"
        }
        
        # Send to preferences WebSocket clients
        for websocket in connected_clients.copy():
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                _main_logger.warning(f"Error sending monitor list update to WebSocket client: {e}")
                connected_clients.discard(websocket)
        
        _main_logger.debug(f"[ACTIVATE] ✅ Monitor list update broadcasted to {len(connected_clients)} clients")
        
        return {"status": "ok", "message": f"Monitor {monitor_name} activated successfully"}
        
    except Exception as e:
        _main_logger.warning(f"Error activating monitor: {e}")
        return {"status": "error", "message": str(e)}



@app.get("/api/strategies")
async def get_strategies(user_id: str = "user_0001"):
    """Get available strategies for the strategy picker dropdown"""
    try:
        from backend.core.config.database import get_postgresql_connection
        
        user_number = user_id.replace("user_", "")
        
        conn = get_postgresql_connection()
        if not conn:
            return {
                "status": "error",
                "message": "Database connection failed"
            }
        
        cursor = conn.cursor()
        # Table creation is now handled in database.py init_database()
        # Just ensure it exists (will be created/updated by init_database if needed)
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'users' 
                AND table_name = 'strategy_list_0001'
            )
        """)
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            # If table doesn't exist, it will be created by init_database on next run
            # For now, create minimal version
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users.strategy_list_0001 (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL UNIQUE,
                    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Check if table has any data, if not insert default strategies
        cursor.execute("SELECT COUNT(*) FROM users.strategy_list_0001")
        count = cursor.fetchone()[0]
        
        if count == 0:
            # Insert default strategies
            default_strategies = [
                'Hourly HTC',
                'Reverse HTC',
                'Momentum Scalp',
                'Momentum Breakout',
                'Momentum Contain',
                'Test Strategy',
                'Daily HTC',
                'Scalp Strategy'
            ]
            for strategy in default_strategies:
                cursor.execute("""
                    INSERT INTO users.strategy_list_0001 (name) 
                    VALUES (%s) 
                    ON CONFLICT (name) DO NOTHING
                """, (strategy,))
        
        # Now get all strategies and which have default=TRUE (for trade history Reset)
        try:
            cursor.execute("""
                SELECT name, "default"
                FROM users.strategy_list_0001
                ORDER BY id
            """)
            results = cursor.fetchall()
            strategies = [str(row[0]) if row[0] else "" for row in results]
            default_strategy_names = [str(row[0]) for row in results if row[0] and row[1]]
        except psycopg2.ProgrammingError:
            cursor.execute("""
                SELECT name
                FROM users.strategy_list_0001
                ORDER BY id
            """)
            results = cursor.fetchall()
            strategies = [str(row[0]) if row[0] else "" for row in results]
            default_strategy_names = list(strategies)
        conn.commit()
        conn.close()
        
        return {
            "status": "ok",
            "strategies": strategies,
            "default_strategy_names": default_strategy_names
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/api/monitor/create")
async def create_monitor(request: dict):
    """Create a new monitor - delegates to monitor_manager"""
    try:
        import requests
        from backend.core.port_config import get_port
        
        # Forward the request to monitor_manager
        monitor_manager_port = get_port("monitor_manager")
        response = requests.post(
            f"http://localhost:{monitor_manager_port}/api/monitor/create",
            json=request,
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"status": "error", "message": f"Monitor manager error: {response.text}"}
            
    except Exception as e:
        _main_logger.warning(f"Error forwarding monitor creation: {e}")
        return {"status": "error", "message": str(e)}

# Main entry point
if __name__ == "__main__":
    _main_logger.debug(f"[MAIN] 🚀 Launching app on centralized port {MAIN_APP_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=MAIN_APP_PORT)

