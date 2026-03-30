"""
UNIVERSAL CENTRALIZED PORT CONFIGURATION SYSTEM
Single source of truth for all port assignments.
"""

import json
import os
from typing import Dict, Optional

# Import the universal host system
try:
    from backend.util.paths import get_host, get_service_url
except ImportError as e:
    print(f"Warning: Could not import get_host or get_service_url from backend.util.paths: {e}")
    # Fallback implementations
    def get_host():
        """Fallback host function"""
        return "localhost"
    
    def get_service_url(port: int) -> str:
        """Fallback service URL function"""
        return f"http://localhost:{port}"

# Central port configuration file - now using MASTER_PORT_MANIFEST.json
PORT_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config", "MASTER_PORT_MANIFEST.json")


def _monitor_id_port_offset(monitor_num: int) -> int:
    """
    Map monitor_list numeric id to the small integer used for per-monitor port spacing.

    Default (prod-style): 10012 -> 12 via (monitor_num - 10_000).
    Dev 99xxx range: 99012 -> 12 via (monitor_num - 99_000) so offsets stay small and
    ports do not overflow (unlike subtracting 10_000 from 99012).
    """
    if monitor_num >= 99_000:
        return monitor_num - 99_000
    return monitor_num - 10_000

# Default port assignments (fallback only)
DEFAULT_PORTS = {
    "main_app": 3000,
    "trade_manager": 4000,
    "trade_executor": 8001,
    "active_trade_supervisor": 6000,
    "redis_switchboard": 3010,
    "read_api": 3050,

    "symbol_price_watchdog_btc": 8008,
    "symbol_price_watchdog_eth": 8009,
    "symbol_price_watchdog_sol": 8025,
    "symbol_price_watchdog_xrp": 8026,

    "kalshi_account_sync": 8004,
    "market_watchdog_ws_kalshi_hourly": 8005,
    "strike_table_generator_ws_hourly": 8014,
    "market_watchdog_kalshi_15m": 8031,
    "market_watchdog_ws_kalshi_15m": 8035,
    "strike_table_generator_15m": 8032,
    "strike_table_generator_ws_15m": 8036,
    "auto_entry_supervisor_15m": 8033,
    "active_trade_supervisor_15m": 8034,
}

def ensure_port_config_exists():
    """Ensure the master port manifest exists with default values."""
    if not os.path.exists(PORT_CONFIG_FILE):
        # Create the master manifest with default values
        master_manifest = {
            "system_name": "REC.IO Trading System",
            "created": "2025-01-27",
            "description": "MASTER PORT MANIFEST - Single source of truth for ALL port assignments",
            "core_services": {
                "main_app": {
                    "port": 3000,
                    "description": "Main web application",
                    "status": "RUNNING"
                },
                "trade_manager": {
                    "port": 4000,
                    "description": "Trade management service",
                    "status": "RUNNING"
                },
                "trade_executor": {
                    "port": 8001,
                    "description": "Trade execution service",
                    "status": "RUNNING"
                },
                "active_trade_supervisor": {
                    "port": 6000,
                    "description": "Active trade monitoring",
                    "status": "RUNNING"
                }
            },
            "watchdog_services": {
                "kalshi_account_sync": {
                    "port": 8004,
                    "description": "Kalshi account synchronization",
                    "status": "RUNNING"
                },
                "market_watchdog_ws_kalshi_hourly": {
                    "port": 8005,
                    "description": "Kalshi hourly market WebSocket → live_data.market_kalshi_hourly",
                    "status": "RUNNING"
                },
                "strike_table_generator_ws_hourly": {
                    "port": 8014,
                    "description": "WS/Redis hourly strike generator → live_data.strike_table_hourly",
                    "status": "RUNNING"
                },
                "strike_table_generator_15m": {
                    "port": 8032,
                    "description": "Unified 15m strike table generator (all symbols)",
                    "status": "RUNNING"
                },
                "strike_table_generator_ws_15m": {
                    "port": 8036,
                    "description": "WS/Redis-driven 15m strike table generator (phase 1)",
                    "status": "RUNNING"
                },
                "market_watchdog_kalshi_15m": {
                    "port": 8031,
                    "description": "Consolidated Kalshi 15m market watchdog (all symbols)",
                    "status": "RUNNING"
                },
                "market_watchdog_ws_kalshi_15m": {
                    "port": 8035,
                    "description": "Kalshi 15m market ticker WebSocket watchdog → live_data.market_kalshi_ws_15m",
                    "status": "RUNNING"
                },
                "auto_entry_supervisor_15m": {
                    "port": 8033,
                    "description": "Unified auto entry supervisor for all active 15m monitors",
                    "status": "RUNNING"
                },
                "active_trade_supervisor_15m": {
                    "port": 8034,
                    "description": "Unified active trade supervisor for all active 15m monitors",
                    "status": "RUNNING"
                },
                "monitor_manager": {
                    "port": 8012,
                    "description": "Core monitor management system",
                    "status": "RUNNING"
                }
            },
            "port_ranges": {
                "safe_range_start": 8000,
                "safe_range_end": 9000,
                "description": "Safe port range avoiding system services. Supports up to ~500 monitors (monitor ID 10500) with current allocation scheme"
            },
            "monitor_process_ports": {
                "start_port": 8013,
                "description": "Dynamic port range for monitor-specific processes",
                "auto_entry_supervisor_offset": 0,
                "active_trade_supervisor_offset": 1,
                "note": "Port calculation: start_port + (port_offset * 2) + service_offset; port_offset is (monitor_id - 10000) for 1xxxx ids, (monitor_id - 99000) for 99xxx ids."
            },
            "notes": {
                "avoid_ports": [5000, 7000, 9000, 10000],
                "reason": "These ports conflict with macOS AirPlay, ControlCenter, and other system services"
            }
        }
        
        os.makedirs(os.path.dirname(PORT_CONFIG_FILE), exist_ok=True)
        # Atomic write: write to a temp file then replace
        temp_path = PORT_CONFIG_FILE + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(master_manifest, f, indent=2)
        os.replace(temp_path, PORT_CONFIG_FILE)
        print(f"[PORT_CONFIG] Created master port manifest: {PORT_CONFIG_FILE}")

def get_port(service_name: str) -> int:
    """Get the port for a specific service from master manifest."""
    ensure_port_config_exists()
    
    try:
        with open(PORT_CONFIG_FILE, 'r') as f:
            manifest = json.load(f)
        
        # Check core_services first
        if service_name in manifest.get("core_services", {}):
            return manifest["core_services"][service_name]["port"]
        
        # Check watchdog_services
        if service_name in manifest.get("watchdog_services", {}):
            return manifest["watchdog_services"][service_name]["port"]
        
        raise ValueError(f"Service '{service_name}' not found in master manifest")
    except Exception as e:
        print(f"[PORT_CONFIG] Error reading master manifest: {e}")
        # Fallback to default
        return DEFAULT_PORTS.get(service_name, 3000)

def get_service_url(service_name: str, endpoint: str = "") -> str:
    """Get the full URL for a service endpoint using universal host system."""
    port = get_port(service_name)
    host = get_host()
    return f"http://{host}:{port}{endpoint}"

def list_all_ports() -> Dict[str, int]:
    """Get all port assignments from master manifest."""
    ensure_port_config_exists()
    
    try:
        with open(PORT_CONFIG_FILE, 'r') as f:
            manifest = json.load(f)
        
        ports = {}
        
        # Extract ports from core_services
        for service_name, service_config in manifest.get("core_services", {}).items():
            ports[service_name] = service_config["port"]
        
        # Extract ports from watchdog_services
        for service_name, service_config in manifest.get("watchdog_services", {}).items():
            ports[service_name] = service_config["port"]
        
        return ports
    except Exception as e:
        print(f"[PORT_CONFIG] Error reading master manifest: {e}")
        return DEFAULT_PORTS

def get_monitor_port(service_name: str, monitor_identifier: str) -> int:
    """
    Get port for a specific monitor instance.
    Scalable port assignment that works for dozens of monitors on any server.
    
    Args:
        service_name: Either 'active_trade_supervisor' or 'auto_entry_supervisor'
        monitor_identifier: Monitor identifier like '0001_10009'
        
    Returns:
        Port number for the monitor-specific service
    """
    ensure_port_config_exists()
    
    try:
        with open(PORT_CONFIG_FILE, 'r') as f:
            manifest = json.load(f)
        
        # Get port range configuration
        port_range = manifest.get("monitor_process_ports", {})
        start_port = port_range.get("start_port", 8013)
        
        # Get safe port range from port_ranges (server-agnostic maximum)
        port_ranges = manifest.get("port_ranges", {})
        safe_range_end = port_ranges.get("safe_range_end", 65535)  # Use system max if not specified
        
        # Parse monitor identifier (e.g., "0001_10009")
        if '_' not in monitor_identifier:
            raise ValueError(f"Invalid monitor identifier format: {monitor_identifier}")
        
        user_number, monitor_id = monitor_identifier.split('_')
        
        # Check if this monitor already has assigned ports in the manifest
        monitor_instances = manifest.get("monitor_instances", {})
        if monitor_identifier in monitor_instances:
            assigned_ports = monitor_instances[monitor_identifier]
            if service_name in assigned_ports:
                return assigned_ports[service_name]
        
        # Calculate port offset based on monitor ID (supports dev 99xxx ids; see _monitor_id_port_offset)
        try:
            monitor_num = int(monitor_id)
            port_offset = _monitor_id_port_offset(monitor_num)
        except ValueError:
            raise ValueError(f"Invalid monitor ID format: {monitor_id}")
        
        # Apply service-specific offset
        if service_name == "active_trade_supervisor":
            service_offset = port_range.get("active_trade_supervisor_offset", 1)
        elif service_name == "auto_entry_supervisor":
            service_offset = port_range.get("auto_entry_supervisor_offset", 0)
        else:
            raise ValueError(f"Unknown monitor service: {service_name}")
        
        # Calculate final port: start_port + (offset * 2) + service_offset
        # Monitor 10002 (offset=2): 8013 + (2*2) + 0 = 8013, 8013 + (2*2) + 1 = 8014
        # Monitor 10009 (offset=9): 8013 + (9*2) + 0 = 8031, 8013 + (9*2) + 1 = 8032
        # Monitor 10019 (offset=19): 8013 + (19*2) + 1 = 8052
        # Monitor 10020 (offset=20): 8013 + (20*2) + 1 = 8054
        final_port = start_port + (port_offset * 2) + service_offset
        
        # Validate port is within safe system range (server-agnostic)
        if final_port > safe_range_end:
            raise ValueError(
                f"Port {final_port} exceeds safe port range (max: {safe_range_end}). "
                f"Monitor ID {monitor_id} is too high for current port allocation scheme. "
                f"Consider adjusting start_port or safe_range_end in manifest."
            )
        
        # Warn if approaching safe range limit (for monitoring/debugging)
        if final_port > safe_range_end - 100:
            print(f"[PORT_CONFIG] Warning: Port {final_port} is approaching safe range limit ({safe_range_end})")
        
        return final_port
        
    except (json.JSONDecodeError, IOError) as e:
        # Manifest is corrupted or unreadable - try to recreate it
        print(f"[PORT_CONFIG] Error reading manifest (may be corrupted): {e}")
        print(f"[PORT_CONFIG] Attempting to recreate manifest from defaults...")
        
        # Backup corrupted manifest if it exists
        if os.path.exists(PORT_CONFIG_FILE):
            import shutil
            from datetime import datetime
            backup_path = f"{PORT_CONFIG_FILE}.corrupted_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                shutil.copy2(PORT_CONFIG_FILE, backup_path)
                print(f"[PORT_CONFIG] Backed up corrupted manifest to: {backup_path}")
            except Exception as backup_error:
                print(f"[PORT_CONFIG] Warning: Could not backup corrupted manifest: {backup_error}")
        
        # Recreate manifest - ensure_port_config_exists() only creates if missing,
        # so we need to remove the corrupted file first
        try:
            if os.path.exists(PORT_CONFIG_FILE):
                os.remove(PORT_CONFIG_FILE)
            ensure_port_config_exists()
            # Now try to read the recreated manifest
            with open(PORT_CONFIG_FILE, 'r') as f:
                manifest = json.load(f)
            
            # Extract configuration from recreated manifest
            port_range = manifest.get("monitor_process_ports", {})
            start_port = port_range.get("start_port", 8013)
            
            if service_name == "active_trade_supervisor":
                service_offset = port_range.get("active_trade_supervisor_offset", 1)
            elif service_name == "auto_entry_supervisor":
                service_offset = port_range.get("auto_entry_supervisor_offset", 0)
            else:
                raise ValueError(f"Unknown monitor service: {service_name}")
            
            # Parse monitor identifier
            if '_' not in monitor_identifier:
                raise ValueError(f"Invalid monitor identifier format: {monitor_identifier}")
            
            user_number, monitor_id = monitor_identifier.split('_')
            try:
                monitor_num = int(monitor_id)
                port_offset = _monitor_id_port_offset(monitor_num)
            except ValueError:
                raise ValueError(f"Invalid monitor ID format: {monitor_id}")
            
            final_port = start_port + (port_offset * 2) + service_offset
            print(f"[PORT_CONFIG] Successfully recreated manifest and calculated port {final_port}")
            return final_port
            
        except Exception as recreate_error:
            # If recreation fails, use the same defaults from ensure_port_config_exists()
            print(f"[PORT_CONFIG] Could not recreate manifest: {recreate_error}")
            print(f"[PORT_CONFIG] Using defaults matching ensure_port_config_exists() configuration")
            
            # These defaults match what ensure_port_config_exists() creates
            start_port = 8013
            if service_name == "active_trade_supervisor":
                service_offset = 1
            elif service_name == "auto_entry_supervisor":
                service_offset = 0
            else:
                raise ValueError(f"Unknown monitor service: {service_name}")
            
            # Parse monitor identifier
            if '_' not in monitor_identifier:
                raise ValueError(f"Invalid monitor identifier format: {monitor_identifier}")
            
            user_number, monitor_id = monitor_identifier.split('_')
            try:
                monitor_num = int(monitor_id)
                port_offset = _monitor_id_port_offset(monitor_num)
            except ValueError:
                raise ValueError(f"Invalid monitor ID format: {monitor_id}")
            
            final_port = start_port + (port_offset * 2) + service_offset
            print(f"[PORT_CONFIG] Calculated port {final_port} using system defaults")
            return final_port
    
    except Exception as e:
        # Any other exception - this should not happen in normal operation
        print(f"[PORT_CONFIG] Unexpected error calculating monitor port: {e}")
        raise

def get_monitor_service_url(service_name: str, monitor_identifier: str, endpoint: str = "") -> str:
    """Get full URL for monitor-specific service."""
    port = get_monitor_port(service_name, monitor_identifier)
    host = get_host()
    return f"http://{host}:{port}{endpoint}"

def register_monitor_ports(monitor_identifier: str) -> Dict[str, int]:
    """
    Register and return port assignments for a monitor.
    This ensures consistent port assignment across the system.
    """
    ports = {
        "auto_entry_supervisor": get_monitor_port("auto_entry_supervisor", monitor_identifier),
        "active_trade_supervisor": get_monitor_port("active_trade_supervisor", monitor_identifier)
    }
    
    # Update manifest with assigned ports
    try:
        with open(PORT_CONFIG_FILE, "r") as f:
            manifest = json.load(f)

        if "monitor_instances" not in manifest:
            manifest["monitor_instances"] = {}

        manifest["monitor_instances"][monitor_identifier] = ports

        # Atomic write: write updated manifest to a temp file then replace
        temp_path = PORT_CONFIG_FILE + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(temp_path, PORT_CONFIG_FILE)

        print(f"[PORT_CONFIG] Registered ports for monitor {monitor_identifier}: {ports}")
        
    except Exception as e:
        print(f"[PORT_CONFIG] Error registering monitor ports: {e}")
    
    return ports


def monitor_suffix_uses_unified_15m_pool(monitor_suffix: str) -> bool:
    """True when this monitor should use the unified 15m AES/ATS ports (market = 15m)."""
    if "_" not in monitor_suffix:
        return False
    user_number, monitor_id = monitor_suffix.split("_", 1)
    conn = None
    try:
        from backend.core.config.database import get_postgresql_connection

        conn = get_postgresql_connection()
        if not conn:
            return False
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT LOWER(TRIM(COALESCE(NULLIF(TRIM(market), ''), 'hourly')))
                FROM users.monitor_list_{user_number}
                WHERE id = %s
                """,
                (monitor_id,),
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                return False
            return str(row[0]).strip() == "15m"
    except Exception:
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_active_trade_supervisor_http_port_for_monitor_suffix(monitor_suffix: str) -> int:
    if monitor_suffix_uses_unified_15m_pool(monitor_suffix):
        return get_port("active_trade_supervisor_15m")
    return get_monitor_port("active_trade_supervisor", monitor_suffix)


def get_auto_entry_supervisor_http_port_for_monitor_suffix(monitor_suffix: str) -> int:
    if monitor_suffix_uses_unified_15m_pool(monitor_suffix):
        return get_port("auto_entry_supervisor_15m")
    return get_monitor_port("auto_entry_supervisor", monitor_suffix)


def get_port_info() -> Dict:
    """Get comprehensive port information for API endpoints using universal host system."""
    try:
        # Try to use unified configuration first
        from backend.core.unified_config import unified_config
        host = unified_config.get('runtime.system_host', 'localhost')
    except ImportError:
        # Fallback to old method
        host = "localhost"
    
    ports = list_all_ports()
    return {
        "ports": ports,
        "service_urls": {name: f"http://{host}:{port}" for name, port in ports.items()},
        "config_file": PORT_CONFIG_FILE,
        "host": host
    } 