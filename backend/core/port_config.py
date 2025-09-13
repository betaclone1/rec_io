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

# Default port assignments (fallback only)
DEFAULT_PORTS = {
    "main_app": 3000,
    "trade_manager": 4000,
    "trade_executor": 8001,
    "active_trade_supervisor": 6000,

    "kalshi_account_sync": 8004,
    "kalshi_market_watchdog_btc": 8005,
    "kalshi_market_watchdog_eth": 8011,
    "strike_table_generator_btc": 8014,
    "strike_table_generator_eth": 8015
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
                "kalshi_market_watchdog_btc": {
                    "port": 8005,
                    "description": "Kalshi BTC market data monitoring",
                    "status": "RUNNING"
                },
                "kalshi_market_watchdog_eth": {
                    "port": 8011,
                    "description": "Kalshi ETH market data monitoring",
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
                "safe_range_end": 8100,
                "description": "Safe port range avoiding macOS system services"
            },
            "notes": {
                "avoid_ports": [5000, 7000, 9000, 10000],
                "reason": "These ports conflict with macOS AirPlay, ControlCenter, and other system services"
            }
        }
        
        os.makedirs(os.path.dirname(PORT_CONFIG_FILE), exist_ok=True)
        with open(PORT_CONFIG_FILE, 'w') as f:
            json.dump(master_manifest, f, indent=2)
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
        
        # Calculate port offset based on monitor ID
        # Convert monitor ID to offset (10009 -> 9, 10002 -> 2)
        try:
            monitor_num = int(monitor_id)
            port_offset = monitor_num - 10000  # Convert 10009 -> 9, 10002 -> 2
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
        final_port = start_port + (port_offset * 2) + service_offset
        
        # Validate port is within range
        end_port = port_range.get("end_port", 8020)
        if final_port > end_port:
            raise ValueError(f"Port {final_port} exceeds monitor port range (max: {end_port})")
        
        return final_port
        
    except Exception as e:
        print(f"[PORT_CONFIG] Error calculating monitor port for {service_name} {monitor_identifier}: {e}")
        # Fallback to centralized port
        return get_port(service_name)

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
        with open(PORT_CONFIG_FILE, 'r') as f:
            manifest = json.load(f)
        
        if "monitor_instances" not in manifest:
            manifest["monitor_instances"] = {}
        
        manifest["monitor_instances"][monitor_identifier] = ports
        
        with open(PORT_CONFIG_FILE, 'w') as f:
            json.dump(manifest, f, indent=2)
            
        print(f"[PORT_CONFIG] Registered ports for monitor {monitor_identifier}: {ports}")
        
    except Exception as e:
        print(f"[PORT_CONFIG] Error registering monitor ports: {e}")
    
    return ports

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