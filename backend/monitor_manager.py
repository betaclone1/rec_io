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
from datetime import datetime, time as dt_time
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
        
        # Daily cleanup scheduler
        self.last_cleanup_date = None
        self.cleanup_thread = None
        self.cleanup_running = False
        
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
        
        # Use new port functions for consistent port assignment
        from backend.core.port_config import get_monitor_port, register_monitor_ports
        
        # Register ports for this monitor to ensure consistency
        register_monitor_ports(monitor_identifier)
        
        # Get monitor-specific ports
        auto_entry_port = get_monitor_port("auto_entry_supervisor", monitor_identifier)
        active_trade_port = get_monitor_port("active_trade_supervisor", monitor_identifier)
        
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

    def update_monitor_statistics_from_trades(self) -> Dict[str, Any]:
        """
        Update monitor statistics by querying the trades database and calculating metrics
        for each active/inactive monitor (excluding ARCHIVED monitors)
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                # Get all active and inactive monitors (excluding ARCHIVED)
                cursor.execute("""
                    SELECT id, name, symbol 
                    FROM users.monitor_list_0001 
                    WHERE status IN ('active', 'inactive')
                    ORDER BY id
                """)
                
                monitors = cursor.fetchall()
                updated_count = 0
                
                for monitor_id, monitor_name, symbol in monitors:
                    # Extract monitor identifier from name (e.g., "mon_0001_10001" -> "mon_0001_10001")
                    monitor_identifier = monitor_name
                    
                    # Query trades for this specific monitor
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_trades,
                            COUNT(CASE WHEN win_loss = 'W' THEN 1 END) as wins,
                            COUNT(CASE WHEN win_loss = 'L' THEN 1 END) as losses,
                            COALESCE(SUM(ret_pct), 0) as total_ret_pct,
                            COALESCE(SUM(pnl), 0) as total_pnl
                        FROM users.trades_0001 
                        WHERE monitor = %s AND status IN ('closed', 'settled') AND (test_filter IS NULL OR test_filter = FALSE)
                    """, (monitor_identifier,))
                    
                    trade_stats = cursor.fetchone()
                    if trade_stats:
                        total_trades, wins, losses, total_ret_pct, total_pnl = trade_stats
                        
                        # Calculate win/loss rate
                        win_loss_rate = 0.0
                        if total_trades > 0:
                            win_loss_rate = round((wins / total_trades) * 100, 1)
                        
                        # For ret_pct: use the sum (like trade_history summary panel does)
                        # Don't divide by total_trades - just use the sum directly
                        ret_pct_sum = total_ret_pct
                        
                        # Update monitor statistics in monitor_list table
                        cursor.execute("""
                            UPDATE users.monitor_list_0001 
                            SET 
                                trades = %s,
                                win_loss = %s,
                                ret_pct = %s,
                                pnl = %s
                            WHERE id = %s
                        """, (total_trades, win_loss_rate, ret_pct_sum, total_pnl, monitor_id))
                        
                        updated_count += 1
                        
                        self.log_event("STATS_UPDATE", f"Updated monitor {monitor_name}: trades={total_trades}, W/L={win_loss_rate}%, ret_pct={ret_pct_sum}%, PNL=${total_pnl:.2f}")
                
                conn.commit()
                
                return {
                    "status": "success",
                    "message": f"Updated statistics for {updated_count} monitors",
                    "updated_count": updated_count
                }
                
        except Exception as e:
            self.log_event("ERROR", f"Error updating monitor statistics from trades: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def handle_trade_status_update(self, trade_id: int, status: str, monitor: str = None, bulk_update: bool = False, ticker: str = None) -> Dict[str, Any]:
        """
        Handle trade status updates and automatically update monitor statistics if needed
        Called when trades are closed, settled, or have other status changes
        """
        try:
            # Only update monitor statistics for closed or settled trades
            if status in ['closed', 'settled'] and monitor:
                if bulk_update:
                    self.log_event("TRADE_UPDATE", f"Bulk trade closure for ticker {ticker}, monitor {monitor}, updating statistics")
                else:
                    self.log_event("TRADE_UPDATE", f"Trade {trade_id} {status} for monitor {monitor}, updating statistics")
                
                # Update statistics for the specific monitor
                result = self.update_monitor_statistics_from_trades()
                
                # Send WebSocket notification to frontend about monitor statistics update
                try:
                    import requests
                    requests.post('http://localhost:3000/api/broadcast_monitor_statistics_update', json={
                        'monitor': monitor,
                        'trade_id': trade_id,
                        'status': status,
                        'bulk_update': bulk_update,
                        'ticker': ticker,
                        'timestamp': time.time()
                    }, timeout=1)
                except Exception as e:
                    self.log_event("WEBSOCKET_ERROR", f"Failed to send monitor statistics update notification: {str(e)}")
                
                return result
            else:
                return {"status": "skipped", "message": f"Trade status {status} does not require statistics update"}
                
        except Exception as e:
            self.log_event("ERROR", f"Error handling trade status update: {e}")
            return {"status": "error", "message": str(e)}

    def periodic_monitor_statistics_update(self) -> Dict[str, Any]:
        """
        Periodically update all monitor statistics from trades database
        This can be called on a schedule or manually for maintenance
        """
        try:
            self.log_event("PERIODIC_UPDATE", "Starting periodic monitor statistics update")
            
            result = self.update_monitor_statistics_from_trades()
            
            if result.get('status') == 'success':
                self.log_event("PERIODIC_UPDATE", f"Periodic update completed: {result.get('message')}")
            else:
                self.log_event("PERIODIC_UPDATE_ERROR", f"Periodic update failed: {result.get('message')}")
            
            return result
            
        except Exception as e:
            self.log_event("ERROR", f"Error in periodic monitor statistics update: {e}")
            return {"status": "error", "message": str(e)}

    def get_monitor_statistics(self, monitor_id: int) -> Dict[str, Any]:
        """
        Get current statistics for a specific monitor
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        id, name, symbol, strategy, trades, win_loss, ret_pct, pnl,
                        bankroll_allotment_total, total_position, status
                    FROM users.monitor_list_0001 
                    WHERE id = %s
                """, (monitor_id,))
                
                result = cursor.fetchone()
                if result:
                    monitor_id, name, symbol, strategy, trades, win_loss, ret_pct, pnl, bankroll_allotment_total, total_position, status = result
                    
                    return {
                        "status": "success",
                        "monitor": {
                            "id": monitor_id,
                            "name": name,
                            "symbol": symbol,
                            "strategy": strategy,
                            "trades": trades,
                            "win_loss": win_loss,
                            "ret_pct": ret_pct,
                            "pnl": pnl,
                            "bankroll_allotment_total": bankroll_allotment_total,
                            "total_position": total_position,
                            "status": status
                        }
                    }
                else:
                    return {"status": "error", "message": "Monitor not found"}
                
        except Exception as e:
            self.log_event("ERROR", f"Error getting monitor statistics: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def get_all_monitor_statistics(self) -> Dict[str, Any]:
        """
        Get current statistics for all monitors
        """
        conn = None
        try:
            conn = self.get_database_connection()
            
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT 
                        id, name, symbol, strategy, trades, win_loss, ret_pct, pnl,
                        bankroll_allotment_total, total_position, status
                    FROM users.monitor_list_0001 
                    ORDER BY id
                """)
                
                monitors = []
                for row in cursor.fetchall():
                    monitor_id, name, symbol, strategy, trades, win_loss, ret_pct, pnl, bankroll_allotment_total, total_position, status = row
                    
                    monitors.append({
                        "id": monitor_id,
                        "name": name,
                        "symbol": symbol,
                        "strategy": strategy,
                        "trades": trades,
                        "win_loss": win_loss,
                        "ret_pct": ret_pct,
                        "pnl": pnl,
                        "bankroll_allotment_total": bankroll_allotment_total,
                        "total_position": total_position,
                        "status": status
                    })
                
                return {
                    "status": "success",
                    "monitors": monitors,
                    "count": len(monitors)
                }
                
        except Exception as e:
            self.log_event("ERROR", f"Error getting all monitor statistics: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            if conn:
                conn.close()

    def cleanup_inactive_monitor_logs(self):
        """Clean up log files for inactive and archived monitors"""
        try:
            print("[MONITOR_MANAGER] 🧹 Starting cleanup of inactive monitor logs...")
            
            # Get inactive and archived monitor IDs from database
            inactive_monitor_ids = self._get_inactive_monitor_ids()
            
            if not inactive_monitor_ids:
                print("[MONITOR_MANAGER] No inactive monitors found, skipping log cleanup")
                return
            
            print(f"[MONITOR_MANAGER] Found {len(inactive_monitor_ids)} inactive monitors: {inactive_monitor_ids}")
            
            # Create monitor_log_archive directory if it doesn't exist
            archive_dir = os.path.join(self.project_root, "logs", "log_archive", "monitor_log_archive")
            os.makedirs(archive_dir, exist_ok=True)
            
            # Move log files for inactive monitors
            moved_count = 0
            for monitor_id in inactive_monitor_ids:
                moved_count += self._move_monitor_logs_to_archive(monitor_id, archive_dir)
            
            print(f"[MONITOR_MANAGER] ✅ Log cleanup completed: {moved_count} files moved to archive")
            self.log_event("LOG_CLEANUP", f"Cleaned up {moved_count} log files for {len(inactive_monitor_ids)} inactive monitors")
            
        except Exception as e:
            print(f"[MONITOR_MANAGER] ❌ Error during log cleanup: {e}")
            self.log_event("LOG_CLEANUP_ERROR", f"Log cleanup failed: {str(e)}")
    
    def _get_inactive_monitor_ids(self) -> List[str]:
        """Get list of monitor IDs that are inactive or archived"""
        try:
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id FROM users.monitor_list_0001 
                    WHERE status IN ('inactive', 'ARCHIVED')
                    ORDER BY id
                """)
                return [str(row[0]) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[MONITOR_MANAGER] Error getting inactive monitor IDs: {e}")
            return []
    
    def _move_monitor_logs_to_archive(self, monitor_id: str, archive_dir: str) -> int:
        """Move all log files for a specific monitor to the archive directory"""
        moved_count = 0
        logs_dir = os.path.join(self.project_root, "logs")
        
        # Define log file patterns for this monitor - catch all log file types
        log_patterns = [
            f"active_trade_supervisor_0001_{monitor_id}*.log",
            f"auto_entry_supervisor_0001_{monitor_id}*.log"
        ]
        
        try:
            import glob
            
            for pattern in log_patterns:
                log_files = glob.glob(os.path.join(logs_dir, pattern))
                
                for log_file in log_files:
                    if os.path.isfile(log_file):
                        filename = os.path.basename(log_file)
                        destination = os.path.join(archive_dir, filename)
                        
                        # Move the file
                        os.rename(log_file, destination)
                        moved_count += 1
                        print(f"[MONITOR_MANAGER] Moved: {filename} -> monitor_log_archive/")
            
        except Exception as e:
            print(f"[MONITOR_MANAGER] Error moving logs for monitor {monitor_id}: {e}")
        
        return moved_count
    
    def cleanup_orphaned_monitor_logs(self):
        """Clean up log files for monitors that don't exist in the database"""
        try:
            print("[MONITOR_MANAGER] 🧹 Starting cleanup of orphaned monitor logs...")
            
            # Get all monitor IDs from database
            conn = self.get_database_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM users.monitor_list_0001 ORDER BY id")
                valid_monitor_ids = {str(row[0]) for row in cursor.fetchall()}
            
            # Create monitor_log_archive directory if it doesn't exist
            archive_dir = os.path.join(self.project_root, "logs", "log_archive", "monitor_log_archive")
            os.makedirs(archive_dir, exist_ok=True)
            
            logs_dir = os.path.join(self.project_root, "logs")
            moved_count = 0
            
            # Find all monitor log files
            import glob
            all_log_files = glob.glob(os.path.join(logs_dir, "*_0001_*.log"))
            
            for log_file in all_log_files:
                filename = os.path.basename(log_file)
                
                # Extract monitor ID from filename
                # Pattern: service_0001_MONITOR_ID.suffix.log
                # Need to find the position of '0001' and get the next part
                parts = filename.split('_')
                try:
                    idx_0001 = parts.index('0001')
                    if idx_0001 + 1 < len(parts):
                        monitor_id = parts[idx_0001 + 1].split('.')[0]  # Remove any file extensions
                    else:
                        continue
                except ValueError:
                    continue
                
                # Check if this monitor ID exists in database
                if monitor_id not in valid_monitor_ids:
                    destination = os.path.join(archive_dir, filename)
                    os.rename(log_file, destination)
                    moved_count += 1
                    print(f"[MONITOR_MANAGER] Moved orphaned: {filename} -> monitor_log_archive/")
            
            print(f"[MONITOR_MANAGER] ✅ Orphaned log cleanup completed: {moved_count} files moved to archive")
            if moved_count > 0:
                self.log_event("ORPHANED_LOG_CLEANUP", f"Cleaned up {moved_count} orphaned log files")
            
        except Exception as e:
            print(f"[MONITOR_MANAGER] ❌ Error during orphaned log cleanup: {e}")
            self.log_event("ORPHANED_LOG_CLEANUP_ERROR", f"Orphaned log cleanup failed: {str(e)}")
    
    def perform_startup_cleanup(self):
        """Perform cleanup tasks on startup"""
        try:
            print("[MONITOR_MANAGER] 🚀 Performing startup cleanup...")
            
            # Clean up inactive monitor logs
            self.cleanup_inactive_monitor_logs()
            
            # Clean up orphaned monitor logs
            self.cleanup_orphaned_monitor_logs()
            
            print("[MONITOR_MANAGER] ✅ Startup cleanup completed")
            
        except Exception as e:
            print(f"[MONITOR_MANAGER] ❌ Error during startup cleanup: {e}")
    
    def start_daily_cleanup_scheduler(self):
        """Start the daily cleanup scheduler thread"""
        if not self.cleanup_running:
            self.cleanup_running = True
            self.cleanup_thread = threading.Thread(target=self._daily_cleanup_loop, daemon=True)
            self.cleanup_thread.start()
            print("[MONITOR_MANAGER] 🕛 Daily cleanup scheduler started")
    
    def stop_daily_cleanup_scheduler(self):
        """Stop the daily cleanup scheduler thread"""
        self.cleanup_running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)
        print("[MONITOR_MANAGER] Daily cleanup scheduler stopped")
    
    def _daily_cleanup_loop(self):
        """Main loop for daily cleanup scheduler"""
        while self.cleanup_running:
            try:
                current_time = datetime.now().time()
                current_date = datetime.now().date()
                
                # Check if it's midnight (00:00) and we haven't run cleanup today
                if (current_time.hour == 0 and current_time.minute == 0 and 
                    self.last_cleanup_date != current_date):
                    
                    print("[MONITOR_MANAGER] 🕛 Midnight detected - running daily log cleanup...")
                    self.perform_startup_cleanup()
                    self.last_cleanup_date = current_date
                    print("[MONITOR_MANAGER] ✅ Daily cleanup completed")
                
                # Sleep for 1 minute to check again
                time.sleep(60)
                
            except Exception as e:
                print(f"[MONITOR_MANAGER] Error in daily cleanup scheduler: {e}")
                time.sleep(300)  # Wait 5 minutes on error

# Global instance
monitor_manager = MonitorManager()

# Initialize bankroll allotments on startup
try:
    monitor_manager.log_event("STARTUP", "Monitor manager starting up, initializing bankroll allotments")
    init_result = monitor_manager.initialize_bankroll_allotments()
    monitor_manager.log_event("STARTUP", f"Startup initialization completed: {init_result}")
    
    # Also initialize monitor statistics on startup
    monitor_manager.log_event("STARTUP", "Initializing monitor statistics from trades database")
    stats_result = monitor_manager.update_monitor_statistics_from_trades()
    monitor_manager.log_event("STARTUP", f"Monitor statistics initialization completed: {stats_result}")
    
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

@app.route('/api/update_monitor_statistics', methods=['POST'])
def update_monitor_statistics():
    """Update monitor statistics from trades database"""
    try:
        print("[MONITOR_MANAGER] Manual monitor statistics update requested")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.update_monitor_statistics_from_trades()
        
        if result.get('status') == 'success':
            return jsonify({'success': True, 'message': result.get('message')})
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        print(f"[MONITOR_MANAGER] Error in manual statistics update: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/periodic_monitor_statistics_update', methods=['POST'])
def periodic_monitor_statistics_update():
    """Trigger periodic update of all monitor statistics"""
    try:
        print("[MONITOR_MANAGER] Periodic monitor statistics update requested")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.periodic_monitor_statistics_update()
        
        if result.get('status') == 'success':
            return jsonify({'success': True, 'message': result.get('message')})
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        print(f"[MONITOR_MANAGER] Error in periodic statistics update: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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
        "capabilities": [
            "bankroll_updates", 
            "position_calculation", 
            "monitor_allotments", 
            "frontend_sync", 
            "monitor_creation", 
            "monitor_statistics_update",
            "trade_status_handling",
            "periodic_statistics_update",
            "individual_monitor_statistics",
            "all_monitor_statistics"
        ]
    })

@app.route('/api/monitor/<int:monitor_id>/statistics', methods=['GET'])
def get_monitor_statistics(monitor_id):
    """Get statistics for a specific monitor"""
    try:
        print(f"[MONITOR_MANAGER] Getting statistics for monitor {monitor_id}")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.get_monitor_statistics(monitor_id)
        
        if result.get('status') == 'success':
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 404
        
    except Exception as e:
        print(f"[MONITOR_MANAGER] Error getting monitor statistics: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/monitors/statistics', methods=['GET'])
def get_all_monitor_statistics():
    """Get statistics for all monitors"""
    try:
        print("[MONITOR_MANAGER] Getting statistics for all monitors")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.get_all_monitor_statistics()
        
        if result.get('status') == 'success':
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        print(f"[MONITOR_MANAGER] Error getting all monitor statistics: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# === FUTURE ENDPOINTS (Foundation) ===

@app.route('/api/monitor_settings_update', methods=['POST'])
def monitor_settings_update():
    """Future: Handle monitor settings updates"""
    # TODO: Implement comprehensive settings management
    return jsonify({"status": "not_implemented", "message": "Future expansion"})

@app.route('/api/toggle-auto-trade', methods=['POST'])
def toggle_auto_trade():
    """Toggle auto_trade boolean value for a specific monitor"""
    try:
        data = request.get_json()
        monitor_id = data.get("monitor_id")
        auto_trade = data.get("auto_trade")
        user_id = data.get("user_id", "user_0001")
        
        if not monitor_id or auto_trade is None:
            return jsonify({"status": "error", "message": "Missing monitor_id or auto_trade parameter"})
        
        # Extract user number and monitor ID from monitor_id (e.g., MON_0001_10001 -> user_0001, 10001)
        if monitor_id.startswith("MON_") and "_" in monitor_id:
            parts = monitor_id.split("_")
            if len(parts) >= 3:
                user_number = parts[1]
                db_monitor_id = parts[2]
            else:
                return jsonify({"status": "error", "message": "Invalid monitor ID format"})
        else:
            return jsonify({"status": "error", "message": "Invalid monitor ID format"})
        
        conn = monitor_manager.get_database_connection()
        with conn.cursor() as cursor:
            # Update ONLY auto_trade boolean - do NOT change auto_trade_status
            cursor.execute(f"""
                UPDATE users.monitor_list_{user_number}
                SET auto_trade = %s
                WHERE id = %s
            """, (auto_trade, db_monitor_id))
            
            if cursor.rowcount == 0:
                return jsonify({"status": "error", "message": "Monitor not found"})
            
        conn.commit()
        conn.close()
        
        return jsonify({"status": "ok", "message": f"Auto trade {'enabled' if auto_trade else 'disabled'} for monitor {monitor_id}"})
        
    except Exception as e:
        print(f"Error toggling auto trade: {e}")
        return jsonify({"status": "error", "message": str(e)})

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

@app.route('/api/trade_status_update', methods=['POST'])
def trade_status_update():
    """Handle trade status updates and update monitor statistics if needed"""
    try:
        data = request.get_json()
        trade_id = data.get('trade_id')
        status = data.get('status')
        monitor = data.get('monitor')
        bulk_update = data.get('bulk_update', False)
        ticker = data.get('ticker')
        
        if not status:
            return jsonify({'success': False, 'error': 'Missing status parameter'}), 400
        
        if not bulk_update and not trade_id:
            return jsonify({'success': False, 'error': 'Missing trade_id parameter for individual trade updates'}), 400
        
        if not monitor:
            return jsonify({'success': False, 'error': 'Missing monitor parameter'}), 400
        
        if bulk_update:
            print(f"[MONITOR_MANAGER] Bulk trade status update: ticker {ticker}, status {status}, monitor {monitor}")
        else:
            print(f"[MONITOR_MANAGER] Trade status update: ID {trade_id}, status {status}, monitor {monitor}")
        
        # Use monitor_manager's built-in method
        result = monitor_manager.handle_trade_status_update(trade_id, status, monitor, bulk_update, ticker)
        
        if result.get('status') in ['success', 'skipped']:
            return jsonify({'success': True, 'message': result.get('message')})
        else:
            return jsonify({'success': False, 'error': result.get('message')}), 500
        
    except Exception as e:
        print(f"[MONITOR_MANAGER] Error handling trade status update: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

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

# Start the daily cleanup scheduler
monitor_manager.start_daily_cleanup_scheduler()

if __name__ == "__main__":
    print("[MONITOR MANAGER] 🚀 Starting Core Monitor Management System")
    print("[MONITOR MANAGER] Foundation for comprehensive monitor state management")
    print("[MONITOR MANAGER] Current capability: Bankroll-driven position updates")
    print("[MONITOR MANAGER] Future capabilities: Full monitor lifecycle management")
    
    # Perform startup cleanup (move inactive monitor logs to archive)
    # DISABLED: Too aggressive - moves logs to archive too quickly
    # monitor_manager.perform_startup_cleanup()
    
    monitor_port = get_port("monitor_manager")
    app.run(host='0.0.0.0', port=monitor_port, debug=False)
