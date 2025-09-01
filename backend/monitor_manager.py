#!/usr/bin/env python3
"""
MONITOR MANAGER - Core Monitor Management System
Foundation for comprehensive monitor state management, database synchronization,
and frontend coordination across all monitor components.

This is the starting point - will expand to handle:
- All monitor settings and preferences
- Trade state management
- Real-time frontend synchronization
- Database consistency across all monitor tables
- Event-driven updates for all monitor components
- Cross-service coordination
- Monitor lifecycle management
"""

import psycopg2
import json
import requests
import subprocess
import sys
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from flask import Flask, request, jsonify
from backend.core.unified_config import UnifiedConfigManager
from backend.core.port_config import get_port
import threading
import time

app = Flask(__name__)

class MonitorManager:
    def __init__(self):
        self.unified_config = UnifiedConfigManager()
        self.db_config = self.unified_config.get_database_config()
        self.service_name = "monitor_manager"
        self.project_root = self.unified_config.project_root
        self.python_executable = self.unified_config.get('runtime.python_executable', sys.executable)
        
        # Foundation for future expansion
        self.active_monitors = {}  # Will track all active monitors
        self.monitor_states = {}   # Will track state of all monitor components
        self.frontend_connections = set()  # Will track frontend connections
        
        # Port allocation for monitor processes
        self.monitor_port_base = 8013
        
    def get_database_connection(self):
        """Get database connection - foundation for all DB operations"""
        # Convert config to psycopg2 format
        psycopg2_config = self.db_config.copy()
        if 'name' in psycopg2_config:
            psycopg2_config['database'] = psycopg2_config.pop('name')
        return psycopg2.connect(**psycopg2_config)
    
    def log_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        """Centralized logging for monitor manager events"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{self.service_name.upper()}] {event_type}: {message}"
        if data:
            log_entry += f" | Data: {json.dumps(data)}"
        print(log_entry)
    
    # === MONITOR PROCESS MANAGEMENT ===
    
    def get_active_monitors(self) -> List[Dict]:
        """Get active monitors from database"""
        try:
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, name, status 
                    FROM users.monitor_list_0001 
                    WHERE status = 'active' 
                    ORDER BY id
                """)
                
                monitors = []
                for row in cursor.fetchall():
                    monitor_id = row[0]
                    name = row[1]
                    status = row[2]
                    
                    # Extract user_number and monitor_id from name (e.g., "mon_0001_10001")
                    if name.startswith("mon_"):
                        parts = name.split("_")
                        if len(parts) >= 3:
                            user_number = parts[1]  # 0001
                            monitor_id = parts[2]   # 10001
                        else:
                            user_number = "0001"
                            monitor_id = str(monitor_id)
                    else:
                        user_number = "0001"
                        monitor_id = str(monitor_id)
                    
                    monitors.append({
                        'id': monitor_id,
                        'name': name,
                        'status': status,
                        'user_number': user_number,
                        'monitor_id': monitor_id
                    })
                
                conn.close()
                return monitors
                
        except Exception as e:
            self.log_event("ERROR", f"Error getting active monitors from database: {e}")
            return []
    
    def get_running_monitor_processes(self) -> List[str]:
        """Get list of currently running monitor-specific processes"""
        try:
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            
            result = subprocess.run(
                [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "status"],
                capture_output=True, text=True, timeout=10
            )
            
            running_processes = []
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = line.split()
                        if len(parts) >= 2:
                            process_name = parts[0]
                            status = parts[1]
                            
                            # Check if it's a monitor-specific process
                            if ((process_name.startswith('auto_entry_supervisor_') or 
                                 process_name.startswith('active_trade_supervisor_')) and
                                status == "RUNNING"):
                                running_processes.append(process_name)
            
            return running_processes
            
        except Exception as e:
            self.log_event("ERROR", f"Error getting running monitor processes: {e}")
            return []
    
    def _create_environment_variables(self) -> str:
        """Create environment variables string for supervisor"""
        try:
            env_vars = [
                f'PATH="{self.unified_config.get("runtime.venv_path", "")}/bin"',
                f'PYTHONPATH="{self.project_root}"',
                'PYTHONGC=1',
                'PYTHONDNSCACHE=1',
                f'TRADING_SYSTEM_HOST="{self.unified_config.get("runtime.system_host", "localhost")}"',
                f'REC_SYSTEM_HOST="{self.unified_config.get("runtime.system_host", "localhost")}"',
                f'REC_PROJECT_ROOT="{self.project_root}"',
                f'REC_ENVIRONMENT="{self.unified_config.get("system.environment", "development")}"',
                f'DB_HOST="{self.db_config.get("host", "localhost")}"',
                f'DB_NAME="{self.db_config.get("name", "rec_io_db")}"',
                f'DB_USER="{self.db_config.get("user", "rec_io_user")}"',
                f'DB_PASSWORD="{self.db_config.get("password", "rec_io_password")}"',
                f'DB_PORT="{self.db_config.get("port", 5432)}"',
                f'POSTGRES_HOST="{self.db_config.get("host", "localhost")}"',
                f'POSTGRES_DB="{self.db_config.get("name", "rec_io_db")}"',
                f'POSTGRES_USER="{self.db_config.get("user", "rec_io_user")}"',
                f'POSTGRES_PASSWORD="{self.db_config.get("password", "rec_io_password")}"',
                f'POSTGRES_PORT="{self.db_config.get("port", 5432)}"',
                f'REC_DB_HOST="{self.db_config.get("host", "localhost")}"',
                f'REC_DB_NAME="{self.db_config.get("name", "rec_io_db")}"',
                f'REC_DB_USER="{self.db_config.get("user", "rec_io_user")}"',
                f'REC_DB_PASS="{self.db_config.get("password", "rec_io_password")}"',
                f'REC_DB_PORT="{self.db_config.get("port", 5432)}"',
                f'REC_DB_SSLMODE="{self.db_config.get("sslmode", "disable")}"'
            ]
            
            return ','.join(env_vars)
            
        except Exception as e:
            self.log_event("ERROR", f"Error creating environment variables: {e}")
            return f'PATH="{self.unified_config.get("runtime.venv_path", "")}/bin",PYTHONPATH="{self.project_root}",PYTHONGC=1,PYTHONDNSCACHE=1'
    
    def create_monitor_config_section(self, monitor: Dict, port_offset: int) -> str:
        """Create supervisor config section for a monitor"""
        user_number = monitor['user_number']
        monitor_id = monitor['monitor_id']
        monitor_identifier = f"{user_number}_{monitor_id}"
        
        # Get environment variables
        env_vars = self._create_environment_variables()
        
        # Get log file paths
        log_dir = os.path.join(self.project_root, 'logs')
        
        # Auto entry supervisor
        auto_entry_port = self.monitor_port_base + (port_offset * 2)
        auto_entry_config = f"""[program:auto_entry_supervisor_{monitor_identifier}]
command={self.python_executable} {self.project_root}/backend/auto_entry_supervisor.py {monitor_identifier}
directory={self.project_root}
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile={log_dir}/auto_entry_supervisor_{monitor_identifier}.err.log
stdout_logfile={log_dir}/auto_entry_supervisor_{monitor_identifier}.out.log
environment={env_vars}

"""
        
        # Active trade supervisor
        active_trade_port = self.monitor_port_base + (port_offset * 2) + 1
        active_trade_config = f"""[program:active_trade_supervisor_{monitor_identifier}]
command={self.python_executable} {self.project_root}/backend/active_trade_supervisor.py {monitor_identifier}
directory={self.project_root}
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile={log_dir}/active_trade_supervisor_{monitor_identifier}.err.log
stdout_logfile={log_dir}/active_trade_supervisor_{monitor_identifier}.out.log
environment={env_vars}

"""
        
        return auto_entry_config + active_trade_config
    
    def spawn_monitor_processes(self, monitor: Dict) -> bool:
        """Spawn processes for a specific monitor by regenerating supervisor config"""
        try:
            self.log_event("INFO", f"Regenerating supervisor config for monitor {monitor['user_number']}_{monitor['monitor_id']}")
            
            # Regenerate supervisor configuration
            result = subprocess.run([
                sys.executable, 
                os.path.join(self.project_root, 'scripts', 'generate_unified_supervisor_config.py')
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error regenerating supervisor config: {result.stderr}")
                return False
            
            # Reread and update supervisor
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "reread"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error rereading supervisor config: {result.stderr}")
                return False
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "update"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error updating supervisor: {result.stderr}")
                return False
            
            self.log_event("SUCCESS", f"Supervisor config regenerated and updated for monitor {monitor['user_number']}_{monitor['monitor_id']}")
            return True
            
        except Exception as e:
            self.log_event("ERROR", f"Error spawning monitor processes: {e}")
            return False
    
    def remove_monitor_processes(self, monitor: Dict) -> bool:
        """Remove processes for a specific monitor by regenerating supervisor config"""
        try:
            self.log_event("INFO", f"Regenerating supervisor config to remove monitor {monitor['user_number']}_{monitor['monitor_id']}")
            
            # Regenerate supervisor configuration
            result = subprocess.run([
                sys.executable, 
                os.path.join(self.project_root, 'scripts', 'generate_unified_supervisor_config.py')
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error regenerating supervisor config: {result.stderr}")
                return False
            
            # Reread and update supervisor
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "reread"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error rereading supervisor config: {result.stderr}")
                return False
            
            result = subprocess.run([
                get_supervisorctl_path(), 
                "-c", get_supervisor_config_path(), 
                "update"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.log_event("ERROR", f"Error updating supervisor: {result.stderr}")
                return False
            
            self.log_event("SUCCESS", f"Supervisor config regenerated and updated to remove monitor {monitor['user_number']}_{monitor['monitor_id']}")
            return True
            
        except Exception as e:
            self.log_event("ERROR", f"Error removing monitor processes: {e}")
            return False
    
    def sync_monitor_processes(self) -> bool:
        """Sync monitor processes with database state"""
        self.log_event("INFO", "Syncing monitor processes with database state")
        
        # Get active monitors from database
        active_monitors = self.get_active_monitors()
        self.log_event("INFO", f"Found {len(active_monitors)} active monitors in database")
        
        # Get currently running monitor processes
        running_processes = self.get_running_monitor_processes()
        self.log_event("INFO", f"Found {len(running_processes)} running monitor processes")
        
        # Extract monitor identifiers from running processes
        running_monitors = set()
        for process_name in running_processes:
            if process_name.startswith('auto_entry_supervisor_'):
                monitor_id = process_name.replace('auto_entry_supervisor_', '')
                running_monitors.add(monitor_id)
            elif process_name.startswith('active_trade_supervisor_'):
                monitor_id = process_name.replace('active_trade_supervisor_', '')
                running_monitors.add(monitor_id)
        
        # Get active monitor identifiers
        active_monitor_ids = set()
        for monitor in active_monitors:
            monitor_id = f"{monitor['user_number']}_{monitor['monitor_id']}"
            active_monitor_ids.add(monitor_id)
        
        # Spawn processes for monitors that should be active but aren't running
        for monitor in active_monitors:
            monitor_id = f"{monitor['user_number']}_{monitor['monitor_id']}"
            if monitor_id not in running_monitors:
                self.log_event("INFO", f"Spawning processes for monitor {monitor_id}")
                self.spawn_monitor_processes(monitor)
        
        # Remove processes for monitors that are running but shouldn't be active
        for monitor_id in running_monitors:
            if monitor_id not in active_monitor_ids:
                self.log_event("INFO", f"Removing processes for monitor {monitor_id}")
                # Create monitor dict for removal
                parts = monitor_id.split('_')
                if len(parts) >= 2:
                    monitor = {
                        'user_number': parts[0],
                        'monitor_id': parts[1]
                    }
                    self.remove_monitor_processes(monitor)
        
        self.log_event("SUCCESS", "Monitor process sync completed")
        
        # Alert frontend to refresh monitor list
        try:
            import requests
            self.log_event("INFO", "Sending monitor list update alert to frontend")
            response = requests.post('http://localhost:3000/api/broadcast_monitor_list_update', json={
                'type': 'monitor_list_updated',
                'message': 'Monitor list has been updated'
            }, timeout=1)
            self.log_event("INFO", f"Monitor list update alert sent, response: {response.status_code}")
        except Exception as e:
            self.log_event("WEBSOCKET_ERROR", f"Failed to send monitor list update notification: {str(e)}")
        
        return True

    # === CORE FUNCTIONALITY (Starting Point) ===
    
    def handle_bankroll_update(self) -> Dict[str, Any]:
        """
        Handle bankroll update notification from kalshi_account_sync
        This is the starting point - will expand to handle all monitor updates
        """
        try:
            self.log_event("BANKROLL_UPDATE", "Processing bankroll update notification")
            
            # Update bankroll allotments for active monitors (includes total_position calculation)
            allotment_result = self.update_monitor_bankroll_allotments(0)  # bankroll parameter not used anymore
            
            # Combine results
            combined_result = {
                "status": "success",
                "allotment_update": allotment_result,
                "message": "Bankroll update processed successfully"
            }
            
            self.log_event("BANKROLL_UPDATE", "Bankroll update processed successfully", combined_result)
            return combined_result
            
        except Exception as e:
            self.log_event("ERROR", f"Bankroll update failed: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    # DEPRECATED: update_total_position method removed - monitor_manager now only works with monitor_list table

    def update_monitor_bankroll_allotments(self, bankroll: float) -> Dict[str, Any]:
        """
        Update bankroll_allotment_total for all active monitors based on current bankroll
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                # Get current bankroll in cents
                cursor.execute("SELECT bankroll_current FROM users.account_balance_0001 ORDER BY timestamp DESC LIMIT 1")
                bankroll_result = cursor.fetchone()
                if not bankroll_result:
                    return {"status": "error", "message": "No bankroll data found"}
                
                bankroll_cents = bankroll_result[0]  # Already in cents
                
                # Get all active monitors
                cursor.execute("""
                    SELECT id, name, bankroll_allotment_pct 
                    FROM users.monitor_list_0001 
                    WHERE status = 'active'
                """)
                
                monitors = cursor.fetchall()
                updated_count = 0
                
                for monitor_id, monitor_name, allotment_pct in monitors:
                    if allotment_pct is None:
                        continue
                    
                    # Simple calculation: allotment_pct * bankroll_cents
                    allotment_total_cents = int(allotment_pct * bankroll_cents)
                    
                    # Update bankroll_allotment_total
                    cursor.execute("""
                        UPDATE users.monitor_list_0001 
                        SET bankroll_allotment_total = %s 
                        WHERE id = %s
                    """, (allotment_total_cents, monitor_id))
                    
                    # Update total_position for all monitors
                    cursor.execute("""
                        SELECT position_size, position_type, multiplier 
                        FROM users.monitor_list_0001 
                        WHERE id = %s
                    """, (monitor_id,))
                    
                    pos_result = cursor.fetchone()
                    if pos_result:
                        position_size, position_type, multiplier = pos_result
                        
                        if position_type == 'percent':
                            # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                            allotment_dollars = allotment_total_cents / 100
                            new_total_position = int(round((position_size * allotment_dollars / 100) * float(multiplier)))
                        else:
                            # For contracts: position_size * multiplier
                            new_total_position = int(position_size * float(multiplier))
                        
                        cursor.execute("""
                            UPDATE users.monitor_list_0001 
                            SET total_position = %s 
                            WHERE id = %s
                        """, (new_total_position, monitor_id))
                        
                        # Send WebSocket notification to frontend about total_position update
                        try:
                            import requests
                            requests.post('http://localhost:3000/api/broadcast_monitor_total_position', json={
                                'monitor_id': monitor_id,
                                'total_position': new_total_position
                            }, timeout=1)
                        except Exception as e:
                            self.log_event("WEBSOCKET_ERROR", f"Failed to send total_position update notification: {str(e)}")
                    
                    updated_count += 1
                
                conn.commit()
                
                return {
                    "status": "success",
                    "message": f"Updated {updated_count} monitors",
                    "updated_count": updated_count,
                    "bankroll_cents": bankroll_cents
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()
    
    # DEPRECATED: push_frontend_updates method removed - monitor_manager now only works with monitor_list table
    
    # === FUTURE EXPANSION FOUNDATION ===
    
    def handle_monitor_settings_update(self, monitor_id: str, settings: Dict[str, Any]):
        """Future: Handle updates to any monitor settings"""
        # TODO: Implement comprehensive monitor settings management
        pass
    
    def handle_trade_state_update(self, trade_id: str, state: Dict[str, Any]):
        """Future: Handle trade state changes"""
        # TODO: Implement trade state management
        pass
    
    def handle_frontend_connection(self, connection_id: str):
        """Future: Handle frontend connection management"""
        # TODO: Implement frontend connection tracking
        pass
    
    def sync_all_monitor_states(self):
        """Future: Synchronize all monitor states across the system"""
        # TODO: Implement comprehensive state synchronization
        pass
    
    def validate_monitor_consistency(self):
        """Future: Validate consistency across all monitor components"""
        # TODO: Implement consistency validation
        pass

    def initialize_bankroll_allotments(self) -> Dict[str, Any]:
        """
        Initialize bankroll allotments on first launch
        """
        return self.update_monitor_bankroll_allotments(0)  # bankroll parameter not used anymore

    def update_monitor_position_variables(self, monitor_id: int, position_size: int = None, position_type: str = None, multiplier: float = None) -> Dict[str, Any]:
        """
        Update monitor position variables and recalculate total_position
        Called when frontend sends position variable updates
        """
        import time
        start_time = time.time()
        conn = None
        try:
            conn = self.get_database_connection()
            self.log_event("TIMING", f"DB connection: {time.time() - start_time:.3f}s")
            
            with conn.cursor() as cursor:
                # Build update query for position variables
                update_fields = []
                values = []
                
                if position_size is not None:
                    update_fields.append("position_size = %s")
                    values.append(position_size)
                
                if position_type is not None:
                    update_fields.append("position_type = %s")
                    values.append(position_type)
                
                if multiplier is not None:
                    update_fields.append("multiplier = %s")
                    values.append(multiplier)
                
                if not update_fields:
                    return {"status": "error", "message": "No position variables to update"}
                
                # Update position variables
                values.append(monitor_id)
                update_start = time.time()
                cursor.execute(f"""
                    UPDATE users.monitor_list_0001 
                    SET {', '.join(update_fields)}
                    WHERE id = %s AND status = 'active'
                """, values)
                self.log_event("TIMING", f"Position update: {time.time() - update_start:.3f}s")
                
                if cursor.rowcount == 0:
                    return {"status": "error", "message": "Monitor not found or not active"}
                
                # Get current monitor settings for calculation
                fetch_start = time.time()
                cursor.execute("""
                    SELECT position_size, position_type, multiplier, bankroll_allotment_total 
                    FROM users.monitor_list_0001 
                    WHERE id = %s
                """, (monitor_id,))
                self.log_event("TIMING", f"Fetch settings: {time.time() - fetch_start:.3f}s")
                
                result = cursor.fetchone()
                if not result:
                    return {"status": "error", "message": "Failed to retrieve monitor settings"}
                
                position_size, position_type, multiplier, bankroll_allotment_total = result
                
                # Calculate new total_position
                if position_type == 'percent':
                    # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                    if bankroll_allotment_total is not None:
                        allotment_dollars = bankroll_allotment_total / 100
                        new_total_position = int(round((position_size * allotment_dollars / 100) * float(multiplier)))
                    else:
                        new_total_position = 0  # No bankroll allotment
                else:
                    # For contracts: position_size * multiplier
                    new_total_position = int(position_size * float(multiplier))
                
                # Update total_position
                total_update_start = time.time()
                cursor.execute("""
                    UPDATE users.monitor_list_0001 
                    SET total_position = %s 
                    WHERE id = %s
                """, (new_total_position, monitor_id))
                self.log_event("TIMING", f"Total position update: {time.time() - total_update_start:.3f}s")
                
                commit_start = time.time()
                conn.commit()
                self.log_event("TIMING", f"Commit: {time.time() - commit_start:.3f}s")
                
                # Send WebSocket notification to frontend
                try:
                    import requests
                    requests.post('http://localhost:3000/api/broadcast_monitor_total_position', json={
                        'monitor_id': monitor_id,
                        'total_position': new_total_position
                    }, timeout=1)
                except Exception as e:
                    self.log_event("WEBSOCKET_ERROR", f"Failed to send total_position update notification: {str(e)}")
                
                total_time = time.time() - start_time
                self.log_event("TIMING", f"Total function time: {total_time:.3f}s")
                
                return {
                    "status": "success",
                    "message": "Monitor position variables updated and total_position recalculated",
                    "monitor_id": monitor_id,
                    "total_position": new_total_position
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def recalculate_monitor_total_positions(self) -> Dict[str, Any]:
        """
        Recalculate total_position for all monitors based on their current settings
        Called when position variables (size, type, multiplier) change
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                # Get all active monitors
                cursor.execute("""
                    SELECT id, name, position_size, position_type, multiplier, bankroll_allotment_total 
                    FROM users.monitor_list_0001 
                    WHERE status = 'active'
                """)
                
                monitors = cursor.fetchall()
                updated_count = 0
                
                for monitor_id, monitor_name, position_size, position_type, multiplier, bankroll_allotment_total in monitors:
                    if position_size is None or position_type is None or multiplier is None:
                        continue
                    
                    # Calculate new total_position based on current settings
                    if position_type == 'percent':
                        # For percent: round((position_size * allotment_dollars / 100) * multiplier)
                        if bankroll_allotment_total is not None:
                            allotment_dollars = bankroll_allotment_total / 100
                            new_total_position = int(round((position_size * allotment_dollars / 100) * float(multiplier)))
                        else:
                            # If no bankroll allotment, skip this monitor
                            continue
                    else:
                        # For contracts: position_size * multiplier
                        new_total_position = int(position_size * float(multiplier))
                    
                    # Update total_position in monitor table
                    cursor.execute("""
                        UPDATE users.monitor_list_0001 
                        SET total_position = %s 
                        WHERE id = %s
                    """, (new_total_position, monitor_id))
                    
                    # Send WebSocket notification to frontend about total_position update
                    try:
                        import requests
                        requests.post('http://localhost:3000/api/broadcast_monitor_total_position', json={
                            'monitor_id': monitor_id,
                            'total_position': new_total_position
                        }, timeout=1)
                    except Exception as e:
                        self.log_event("WEBSOCKET_ERROR", f"Failed to send total_position update notification: {str(e)}")
                    
                    updated_count += 1
                
                conn.commit()
                
                return {
                    "status": "success",
                    "message": f"Recalculated total_position for {updated_count} monitors",
                    "updated_count": updated_count
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

# Global instance
monitor_manager = MonitorManager()

# Initialize bankroll allotments on startup
try:
    monitor_manager.log_event("STARTUP", "Monitor manager starting up, initializing bankroll allotments")
    init_result = monitor_manager.initialize_bankroll_allotments()
    monitor_manager.log_event("STARTUP", f"Startup initialization completed: {init_result}")
except Exception as e:
    monitor_manager.log_event("STARTUP_ERROR", f"Failed to initialize on startup: {str(e)}")

# === API ENDPOINTS (Starting Point) ===

@app.route('/api/bankroll_updated', methods=['POST'])
def bankroll_updated():
    """Endpoint called by kalshi_account_sync when bankroll changes"""
    return jsonify(monitor_manager.handle_bankroll_update())

@app.route('/api/update_monitor_position', methods=['POST'])
def update_monitor_position_variables():
    """Update monitor position variables and recalculate total_position"""
    try:
        data = request.get_json()
        monitor_id = data.get('monitor_id')
        position_size = data.get('position_size')
        position_type = data.get('position_type')
        multiplier = data.get('multiplier')
        
        print(f"[MONITOR_MANAGER] Updating monitor {monitor_id} position variables")
        print(f"[MONITOR_MANAGER] Position size: {position_size}, type: {position_type}, multiplier: {multiplier}")
        
        # Update the monitor_list table with new values
        conn = monitor_manager.get_database_connection() # Use monitor_manager's connection
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE users.monitor_list_0001 
                SET position_size = %s, position_type = %s, multiplier = %s
                WHERE id = %s
            """, (position_size, position_type, multiplier, monitor_id))
            conn.commit()
        
        # Recalculate total_position using monitor_manager method
        result = monitor_manager.update_monitor_position_variables(monitor_id, position_size, position_type, multiplier)
        
        if result.get('status') == 'error':
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
        # The monitor_manager method already handles the total_position calculation and WebSocket notification
        total_position = result.get('total_position', 0)
        
        return jsonify({'success': True, 'total_position': total_position})
        
    except Exception as e:
        print(f"[MONITOR_MANAGER] Error updating monitor position: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/sync_monitor_processes', methods=['POST'])
def sync_monitor_processes():
    """Manually trigger monitor process sync"""
    try:
        print("[MONITOR_MANAGER] Manual monitor process sync requested")
        
        # Use monitor_manager's built-in sync method
        success = monitor_manager.sync_monitor_processes()
        
        if success:
            return jsonify({'success': True, 'message': 'Monitor processes synced successfully'})
        else:
            return jsonify({'success': False, 'error': 'Monitor process sync failed'}), 500
        
    except Exception as e:
        print(f"[MONITOR_MANAGER] Error in manual sync: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/initialize_allotments', methods=['POST'])
def initialize_allotments():
    """Endpoint to recalculate total_position for all monitors when position variables change"""
    return jsonify(monitor_manager.recalculate_monitor_total_positions())

@app.route('/api/monitor/create', methods=['POST'])
def create_monitor():
    """Create a new monitor - business logic handled here"""
    try:
        data = request.get_json()
        
        # Extract parameters from request body
        symbol = data.get("symbol")
        strategy = data.get("strategy")
        bankroll_allotment_pct = data.get("bankroll_allotment_pct", 10)
        position_size = data.get("position_size", 100)
        multiplier = data.get("multiplier", 1.0)
        user_id = data.get("user_id", "user_0001")
        
        if not symbol or not strategy:
            return jsonify({"status": "error", "message": "Missing symbol or strategy parameter"}), 400
        
        # Extract user number from user_id (e.g., user_0001 -> 0001)
        user_number = user_id.replace("user_", "")
        
        conn = monitor_manager.get_database_connection()
        if not conn:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500
        
        with conn.cursor() as cursor:
            # Let PostgreSQL handle the ID automatically with SERIAL
            cursor.execute(f"""
                INSERT INTO users.monitor_list_{user_number}
                (name, symbol, strategy, auto_trade, auto_trade_status, status, bankroll_allotment_pct, position_size, multiplier, trades, win_loss, ret_pct, pnl, dashboard_order, created)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
            """, (
                f"mon_{user_number}_temp",  # Temporary name
                symbol,
                strategy,
                False,  # auto_trade defaults to False
                'off',  # auto_trade_status defaults to 'off'
                'active',  # status defaults to 'active'
                bankroll_allotment_pct,
                position_size,
                multiplier,
                0,  # trades defaults to 0
                0,  # win_loss defaults to 0
                0,  # ret_pct defaults to 0
                0,  # pnl defaults to 0
                999,  # dashboard_order defaults to 999 (end of list)
            ))
            
            # Get the generated ID
            monitor_id = cursor.fetchone()[0]
            
            # Generate the proper monitor name based on the ID
            monitor_name = f"mon_{user_number}_{monitor_id}"
            
            # Update the name with the correct ID
            cursor.execute(f"""
                UPDATE users.monitor_list_{user_number}
                SET name = %s
                WHERE id = %s
            """, (monitor_name, monitor_id))
            
        conn.commit()
        conn.close()
        
        monitor_manager.log_event("CREATE", f"Monitor {monitor_name} created successfully")
        
        # Spawn monitor processes for the new monitor
        monitor_data = {
            'user_number': user_number,
            'monitor_id': str(monitor_id),
            'name': monitor_name
        }
        monitor_manager.spawn_monitor_processes(monitor_data)
        
        return jsonify({
            "status": "ok", 
            "message": f"Monitor {monitor_name} created successfully",
            "monitor_name": monitor_name,
            "monitor_id": monitor_id
        })
        
    except Exception as e:
        monitor_manager.log_event("ERROR", f"Error creating monitor: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "service": "monitor_manager",
        "version": "1.0.0",
        "capabilities": ["bankroll_updates", "position_calculation", "monitor_allotments", "frontend_sync", "monitor_creation"]
    })

# === FUTURE ENDPOINTS (Foundation) ===

@app.route('/api/monitor_settings_update', methods=['POST'])
def monitor_settings_update():
    """Future: Handle monitor settings updates"""
    # TODO: Implement comprehensive settings management
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/trade_state_update', methods=['POST'])
def trade_state_update():
    """Future: Handle trade state updates"""
    # TODO: Implement trade state management
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/sync_all_states', methods=['POST'])
def sync_all_states():
    """Future: Synchronize all monitor states"""
    # TODO: Implement comprehensive state synchronization
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

class MonitorStatusWatcher:
    """Background thread to watch for monitor status changes"""
    
    def __init__(self, monitor_manager_instance):
        self.monitor_manager = monitor_manager_instance
        self.running = False
        self.thread = None
        self.last_status = {}  # Cache of last known status for each monitor
        
    def start(self):
        """Start the status watcher thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._watch_loop, daemon=True)
            self.thread.start()
            print("[MONITOR_MANAGER] Monitor status watcher started")
    
    def stop(self):
        """Stop the status watcher thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[MONITOR_MANAGER] Monitor status watcher stopped")
    
    def _watch_loop(self):
        """Main watching loop"""
        while self.running:
            try:
                self._check_for_status_changes()
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                print(f"[MONITOR_MANAGER] Error in status watcher: {e}")
                time.sleep(30)  # Wait longer on error
    
    def _check_for_status_changes(self):
        """Check for monitor status changes in the database"""
        try:
            conn = self.monitor_manager.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, status FROM users.monitor_list_0001 
                    ORDER BY id
                """)
                
                current_status = {}
                for row in cursor.fetchall():
                    monitor_id = row[0]
                    status = row[1]
                    current_status[monitor_id] = status
                
                conn.close()
                
                # Check for changes
                for monitor_id, status in current_status.items():
                    if monitor_id not in self.last_status or self.last_status[monitor_id] != status:
                        print(f"[MONITOR_MANAGER] Status change detected: Monitor {monitor_id} changed from {self.last_status.get(monitor_id, 'unknown')} to {status}")
                        self._handle_status_change(monitor_id, status)
                        self.last_status[monitor_id] = status
                
                # Check for removed monitors
                for monitor_id in list(self.last_status.keys()):
                    if monitor_id not in current_status:
                        print(f"[MONITOR_MANAGER] Monitor {monitor_id} removed from database")
                        del self.last_status[monitor_id]
                        
        except Exception as e:
            print(f"[MONITOR_MANAGER] Error checking status changes: {e}")
    
    def _handle_status_change(self, monitor_id, new_status):
        """Handle a monitor status change"""
        try:
            print(f"[MONITOR_MANAGER] Status change detected: Monitor {monitor_id} changed to {new_status}")
            
            # Use monitor_manager's built-in sync method
            success = self.monitor_manager.sync_monitor_processes()
            
            if success:
                print(f"[MONITOR_MANAGER] Monitor process sync completed successfully for monitor {monitor_id}")
            else:
                print(f"[MONITOR_MANAGER] Monitor process sync failed for monitor {monitor_id}")
                
        except Exception as e:
            print(f"[MONITOR_MANAGER] Error handling status change for monitor {monitor_id}: {e}")

# Initialize monitor manager instance
monitor_manager = MonitorManager()

# Initialize the status watcher
status_watcher = MonitorStatusWatcher(monitor_manager)

def start_status_watcher():
    """Start the monitor status watcher when the Flask app starts"""
    status_watcher.start()

# Start the status watcher immediately
start_status_watcher()

if __name__ == "__main__":
    print("[MONITOR MANAGER] 🚀 Starting Core Monitor Management System")
    print("[MONITOR MANAGER] Foundation for comprehensive monitor state management")
    print("[MONITOR MANAGER] Current capability: Bankroll-driven position updates")
    print("[MONITOR MANAGER] Future capabilities: Full monitor lifecycle management")
    monitor_port = get_port("monitor_manager")
    app.run(host='0.0.0.0', port=monitor_port, debug=False)
