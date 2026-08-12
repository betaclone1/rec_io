"""
UNIVERSAL CENTRALIZED PORT CONFIGURATION SYSTEM
Single source of truth for all port assignments.
"""

import json
import logging
import os
from typing import Dict, List, Optional

_port_cfg_logger = logging.getLogger(__name__)


def default_pool_user_number() -> str:
    """Trading slot from ``REC_USER_NO`` / ``REC_POOL_USER_NUMBER``, else tail of ``REC_DEFAULT_USER_SCHEMA``."""
    u = (os.environ.get("REC_USER_NO") or os.environ.get("REC_POOL_USER_NUMBER") or "").strip()
    if u:
        if u.isdigit() and len(u) <= 4:
            u = u.zfill(4)
        return u
    schema = (os.environ.get("REC_DEFAULT_USER_SCHEMA") or "").strip()
    if schema.lower().startswith("users_") and len(schema) > len("users_"):
        tail = schema.split("_", 1)[-1].strip()
        if tail.isdigit() and len(tail) <= 4:
            return tail.zfill(4)
    raise RuntimeError(
        "Set REC_USER_NO, REC_POOL_USER_NUMBER, or REC_DEFAULT_USER_SCHEMA (users_<slot>) "
        "so the process can resolve the trading slot."
    )


def pool_user_for_unified_aes_ats(active_monitors: Optional[List] = None) -> Optional[str]:
    """
    Supervisor program suffix for pool AES/ATS: auto_entry_supervisor_<id> / active_trade_supervisor_<id>.
    Prefer distinct user_number values from monitor rows. Returns None if the list is empty
    (caller should fall back to ``REC_POOL_USER_NUMBER`` / ``default_pool_user_number()``).
    """
    if not active_monitors:
        return None
    ids = sorted(
        {
            str(m.get("user_number") or "").strip()
            for m in active_monitors
            if str(m.get("user_number") or "").strip()
        }
    )
    if not ids:
        return None
    if len(ids) > 1:
        _port_cfg_logger.warning(
            "Multiple user_numbers among active monitors (%s); using %s for pool AES/ATS supervisor names "
            "(supervisor generator should pass monitors for one tenant only)",
            ids,
            ids[0],
        )
    return ids[0]


def unified_auto_entry_supervisor_service_name() -> str:
    return f"auto_entry_supervisor_{default_pool_user_number()}"


def unified_active_trade_supervisor_service_name() -> str:
    return f"active_trade_supervisor_{default_pool_user_number()}"


# Supervisord program names use REC_POOL_USER_NUMBER; get_port("trade_manager") still works via resolution.
_USER_SCOPED_PORT_BASES = frozenset(
    {
        "trade_manager",
        "trade_executor",
        "kalshi_account_sync",
        "monitor_manager",
        "auto_entry_supervisor",
        "active_trade_supervisor",
    }
)


def user_scoped_service_name(base: str) -> str:
    """Supervisor + manifest key suffix for user-level trading services (e.g. trade_manager_0001)."""
    return f"{base}_{default_pool_user_number()}"


def _resolve_user_scoped_port_key(service_name: str) -> str:
    if service_name in _USER_SCOPED_PORT_BASES:
        return user_scoped_service_name(service_name)
    return service_name


# Map supervisord program name → script file under backend/ (for duplicate-process detection).
_USER_SCOPED_SCRIPT = {
    "trade_manager": "trade_manager.py",
    "trade_executor": "trade_executor.py",
    "monitor_manager": "monitor_manager.py",
    "kalshi_account_sync": "kalshi_account_sync_ws.py",
}


def supervisor_program_script_filename(supervisor_program_name: str) -> str:
    """Resolve backend script filename for a supervisord program name."""
    import re

    m = re.match(
        r"^(trade_manager|trade_executor|monitor_manager|kalshi_account_sync)_(\d+)$",
        supervisor_program_name,
    )
    if m:
        base = m.group(1)
        return _USER_SCOPED_SCRIPT.get(base, f"{base}.py")
    return f"{supervisor_program_name}.py"


def _resolve_legacy_unified_port_key(service_name: str) -> str:
    """Map old *_unified manifest keys to user-suffixed names."""
    if service_name == "auto_entry_supervisor_unified":
        return unified_auto_entry_supervisor_service_name()
    if service_name == "active_trade_supervisor_unified":
        return unified_active_trade_supervisor_service_name()
    return service_name

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

    Slot-prefixed ids: numeric id is ``<slot> * 10_000 + offset`` with a small ``offset``
    (e.g. 10012 -> 12, 20012 -> 12, 650001 -> 1). Implemented as ``monitor_num - (monitor_num // 10_000) * 10_000``.

    Legacy local-dev band 99000–99999: offset = ``monitor_num - 99_000`` (existing rows).
    """
    if 99_000 <= monitor_num < 100_000:
        return monitor_num - 99_000
    hi = (monitor_num // 10_000) * 10_000
    return monitor_num - hi

# Default port assignments (fallback only)
DEFAULT_PORTS = {
    "main_app": 3000,
    "trade_manager": 4000,
    "trade_executor": 8001,
    "active_trade_supervisor": 6000,
    "redis_switchboard": 3010,
    "read_api": 3050,

    "cfbenchmarks_price_watchdog": 8008,

    "kalshi_account_sync": 8004,
    "market_watchdog_ws_kalshi_hourly": 8005,
    "strike_table_generator_ws_hourly": 8014,
    "market_watchdog_kalshi_15m": 8031,
    "market_watchdog_ws_kalshi_15m": 8035,
    "strike_table_generator_15m": 8032,
    "strike_table_generator_ws_15m": 8036,
    "auto_entry_supervisor_15m": 8033,
    "active_trade_supervisor_15m": 8034,
    "auto_entry_supervisor_0001": 8033,
    "active_trade_supervisor_0001": 8034,
    "auto_entry_supervisor_0001_btc15m_exp_scalp": 8039,
    "active_trade_supervisor_0001_btc15m_exp_scalp": 8041,
    "auto_entry_supervisor_hourly": 8037,
    "active_trade_supervisor_hourly": 8038,
    "trade_manager_0001": 4000,
    "trade_executor_0001": 8001,
    "kalshi_account_sync_0001": 8004,
    "monitor_manager_0001": 8012,
    "trade_manager_0002": 4010,
    "trade_executor_0002": 8011,
    "kalshi_account_sync_0002": 8014,
    "monitor_manager_0002": 8022,
    "auto_entry_supervisor_0002": 8043,
    "active_trade_supervisor_0002": 8044,
    "auto_entry_supervisor_0002_btc15m_exp_scalp": 8045,
    "active_trade_supervisor_0002_btc15m_exp_scalp": 8046,
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
                "trade_manager_0001": {
                    "port": 4000,
                    "description": "Trade management service (user 0001)",
                    "status": "RUNNING"
                },
                "trade_executor_0001": {
                    "port": 8001,
                    "description": "Trade execution service (user 0001)",
                    "status": "RUNNING"
                },
                "active_trade_supervisor": {
                    "port": 6000,
                    "description": "Active trade monitoring",
                    "status": "RUNNING"
                }
            },
            "watchdog_services": {
                "kalshi_account_sync_0001": {
                    "port": 8004,
                    "description": "Kalshi account synchronization (user 0001)",
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
                "auto_entry_supervisor_0001": {
                    "port": 8033,
                    "description": "Pool auto entry supervisor for user 0001 (all active 15m and hourly-pool monitors, single process)",
                    "status": "RUNNING"
                },
                "active_trade_supervisor_0001": {
                    "port": 8034,
                    "description": "Pool active trade supervisor for user 0001 (all active 15m and hourly-pool monitors, single process)",
                    "status": "RUNNING"
                },
                "auto_entry_supervisor_hourly": {
                    "port": 8037,
                    "description": "Unified auto entry supervisor for all active hourly monitors",
                    "status": "RUNNING"
                },
                "active_trade_supervisor_hourly": {
                    "port": 8038,
                    "description": "Unified active trade supervisor for all active hourly monitors",
                    "status": "RUNNING"
                },
                "monitor_manager_0001": {
                    "port": 8012,
                    "description": "Core monitor management system (user 0001)",
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
                "note": "Port calculation: start_port + (port_offset * 2) + service_offset; port_offset from monitor_id via _monitor_id_port_offset (slot*10000+offset ids; legacy 99xxx supported)."
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
    _normalize_manifest_user_scoped_keys()


def _normalize_manifest_user_scoped_keys() -> None:
    """
    Runtime guardrail: enforce suffixed keys for user-scoped services.

    This prevents regressions when a stale/legacy manifest (with unsuffixed keys like
    ``trade_executor``) lands on a host. The function is idempotent and safe to call
    on every startup.
    """
    try:
        with open(PORT_CONFIG_FILE, "r") as f:
            manifest = json.load(f)
    except Exception:
        return

    try:
        slot = default_pool_user_number()
    except Exception:
        # No pool context in this process; skip normalization rather than crashing callers.
        return
    changed = False

    core = manifest.get("core_services")
    if isinstance(core, dict):
        for base in ("trade_manager", "trade_executor", "active_trade_supervisor"):
            if base in core:
                suffixed = f"{base}_{slot}"
                if suffixed not in core:
                    core[suffixed] = core[base]
                del core[base]
                changed = True

    watch = manifest.get("watchdog_services")
    if isinstance(watch, dict):
        for base in ("kalshi_account_sync", "monitor_manager", "kalshi_lifecycle_consumer"):
            if base in watch:
                suffixed = f"{base}_{slot}"
                if suffixed not in watch:
                    watch[suffixed] = watch[base]
                del watch[base]
                changed = True
        # Canonical runtime aliases used by process code.
        if "market_watchdog_ws_kalshi_hourly" not in watch:
            src = watch.get("kalshi_market_watchdog_hourly_btc")
            if isinstance(src, dict):
                watch["market_watchdog_ws_kalshi_hourly"] = {
                    "port": src.get("port", 8005),
                    "description": "Kalshi hourly market WebSocket watchdog",
                    "status": src.get("status", "RUNNING"),
                }
                changed = True
        if "market_watchdog_ws_kalshi_15m" not in watch:
            src = watch.get("kalshi_market_watchdog_15m_btc")
            if isinstance(src, dict):
                watch["market_watchdog_ws_kalshi_15m"] = {
                    "port": src.get("port", 8035),
                    "description": "Kalshi 15m market ticker WebSocket watchdog",
                    "status": src.get("status", "RUNNING"),
                }
                changed = True

    if not changed:
        return
    try:
        temp_path = PORT_CONFIG_FILE + ".tmp"
        with open(temp_path, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(temp_path, PORT_CONFIG_FILE)
        print(
            "[PORT_CONFIG] Normalized legacy manifest keys to suffixed user-scoped keys "
            f"(slot {slot})"
        )
    except Exception as e:
        print(f"[PORT_CONFIG] Could not persist manifest normalization: {e}")

def get_port(service_name: str) -> int:
    """Get the port for a specific service from master manifest."""
    ensure_port_config_exists()
    service_name = _resolve_legacy_unified_port_key(service_name)
    service_name = _resolve_user_scoped_port_key(service_name)

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
            from backend.core.time_eastern import now_est

            backup_path = f"{PORT_CONFIG_FILE}.corrupted_{now_est().strftime('%Y%m%d_%H%M%S')}"
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


def _monitor_suffix_tenant_slot(monitor_suffix: str) -> Optional[str]:
    """4-digit slot from ``<user>_<monitor_id>`` for tenant-scoped DB reads."""
    if "_" not in monitor_suffix:
        return None
    user_number, _ = monitor_suffix.split("_", 1)
    u = user_number.strip()
    if u.isdigit() and len(u) <= 4:
        return u.zfill(4)
    return None


def monitor_suffix_uses_unified_15m_pool(monitor_suffix: str) -> bool:
    """True when this monitor should use the unified 15m AES/ATS ports (market = 15m)."""
    if "_" not in monitor_suffix:
        return False
    tenant_slot = _monitor_suffix_tenant_slot(monitor_suffix)
    if not tenant_slot:
        return False
    user_number, monitor_id = monitor_suffix.split("_", 1)
    conn = None
    try:
        from backend.core.config.database import get_postgresql_connection

        conn = get_postgresql_connection(tenant_user_no=tenant_slot)
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


def monitor_suffix_uses_unified_hourly_pool(monitor_suffix: str) -> bool:
    """True when this monitor uses the hourly unified ladder (normalized market is not 15m)."""
    if "_" not in monitor_suffix:
        return False
    tenant_slot = _monitor_suffix_tenant_slot(monitor_suffix)
    if not tenant_slot:
        return False
    user_number, monitor_id = monitor_suffix.split("_", 1)
    conn = None
    try:
        from backend.core.config.database import get_postgresql_connection

        conn = get_postgresql_connection(tenant_user_no=tenant_slot)
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
            return str(row[0]).strip() != "15m"
    except Exception:
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def monitor_suffix_uses_unified_aes_ats_pool(monitor_suffix: str) -> bool:
    """True when this monitor is served by the single unified AES/ATS processes (15m or non-15m ladder)."""
    return monitor_suffix_uses_unified_15m_pool(monitor_suffix) or monitor_suffix_uses_unified_hourly_pool(
        monitor_suffix
    )


def get_active_trade_supervisor_http_port_for_monitor_suffix(monitor_suffix: str) -> int:
    if monitor_suffix_uses_unified_aes_ats_pool(monitor_suffix):
        return get_port(unified_active_trade_supervisor_service_name())
    return get_monitor_port("active_trade_supervisor", monitor_suffix)


def get_auto_entry_supervisor_http_port_for_monitor_suffix(monitor_suffix: str) -> int:
    if monitor_suffix_uses_unified_aes_ats_pool(monitor_suffix):
        return get_port(unified_auto_entry_supervisor_service_name())
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