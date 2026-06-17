#!/usr/bin/env python3
"""
PORT FLUSH SYSTEM
Flushes all ports and restarts the system cleanly.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

def load_master_manifest():
    """Load the master port manifest."""
    manifest_path = Path("backend/core/config/MASTER_PORT_MANIFEST.json")
    with open(manifest_path, 'r') as f:
        return json.load(f)

def get_all_ports():
    """Get all ports from the master manifest."""
    manifest = load_master_manifest()
    ports = []
    
    # Core services
    for service, info in manifest["core_services"].items():
        ports.append(info["port"])
    
    # Watchdog services
    for service, info in manifest["watchdog_services"].items():
        ports.append(info["port"])
    
    return ports

def check_port_conflicts():
    """Check if any ports are already in use."""
    ports = get_all_ports()
    conflicts = []
    
    for port in ports:
        try:
            result = subprocess.run(['lsof', '-i', f':{port}'], 
                                  capture_output=True, text=True)
            if result.stdout.strip():
                conflicts.append((port, result.stdout.strip()))
        except Exception as e:
            print(f"Error checking port {port}: {e}")
    
    return conflicts

def flush_ports():
    """Kill processes using our ports."""
    ports = get_all_ports()
    killed = []
    
    for port in ports:
        try:
            result = subprocess.run(['lsof', '-ti', f':{port}'], 
                                  capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        subprocess.run(['kill', '-9', pid])
                        killed.append((port, pid))
                        print(f"Killed process {pid} on port {port}")
        except Exception as e:
            print(f"Error flushing port {port}: {e}")
    
    return killed

def restart_supervisor():
    """Restart the supervisor system."""
    try:
        from backend.util.paths import (
            get_supervisorctl_path,
            get_supervisord_path,
            get_supervisor_config_path,
        )
        # Stop supervisor
        subprocess.run([get_supervisorctl_path(), '-c', get_supervisor_config_path(), 'shutdown'])
        time.sleep(2)
        
        # Start supervisor
        subprocess.run([get_supervisord_path(), '-c', get_supervisor_config_path()])
        time.sleep(3)
        
        # Check status
        result = subprocess.run([get_supervisorctl_path(), '-c', get_supervisor_config_path(), 'status'],
                              capture_output=True, text=True)
        print("Supervisor status:")
        print(result.stdout)
        
    except Exception as e:
        print(f"Error restarting supervisor: {e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python backend/core/port_flush.py [check|flush|restart]")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "check":
        conflicts = check_port_conflicts()
        if conflicts:
            print("PORT CONFLICTS DETECTED:")
            for port, process in conflicts:
                print(f"Port {port}: {process}")
        else:
            print("No port conflicts detected.")
    
    elif command == "flush":
        print("Flushing all ports...")
        killed = flush_ports()
        if killed:
            print(f"Killed {len(killed)} processes")
        else:
            print("No processes to kill")
    
    elif command == "restart":
        print("Restarting supervisor system...")
        flush_ports()
        restart_supervisor()
    
    else:
        print("Unknown command. Use: check, flush, or restart")

if __name__ == "__main__":
    main() 