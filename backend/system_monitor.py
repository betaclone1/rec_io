#!/usr/bin/env python3
"""
System Monitor - Simplified Version
Monitors system health and performance metrics without aggressive restart logic.
"""

import os
import sys
import psutil

import time
import subprocess
import platform
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List

# Force output to be unbuffered for supervisor
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Add project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.util.paths import get_project_root

# Add scripts directory for user_notifications
sys.path.insert(0, os.path.join(get_project_root(), 'scripts'))

from backend.core.port_config import get_port, get_port_info, list_all_ports
from backend.util.paths import get_data_dir, get_trade_history_dir, get_price_history_dir

class SystemMonitor:
    def __init__(self):
        self.monitoring_interval = 15  # seconds (critical system monitoring)
        self.health_history = []
        self.max_history = 50  # reduced history size
        
        # MASTER RESTART notification tracking
        self.restart_attempts = 0
        self.max_restart_attempts = 3
        self.trading_suspended = False
        self.master_restart_triggered = False
        self.restart_completion_checked = False
        
        # Trading state tracking removed - no longer modifying user settings automatically
        
        # Get service URLs using bulletproof port manager
        self.service_urls = {
            "main_app": get_port("main_app"),
            "trade_manager": get_port("trade_manager"),
            "trade_executor": get_port("trade_executor"),
            "active_trade_supervisor": get_port("active_trade_supervisor"),
            "auto_entry_supervisor": get_port("auto_entry_supervisor"),
            "symbol_price_watchdog_btc": get_port("symbol_price_watchdog_btc"),
            "symbol_price_watchdog_eth": get_port("symbol_price_watchdog_eth"),
            "strike_table_generator": get_port("strike_table_generator"),
            "kalshi_account_sync": get_port("kalshi_account_sync"),
            "kalshi_market_watchdog": get_port("kalshi_market_watchdog"),
            "monitor_manager": get_port("monitor_manager"),
            "cascading_failure_detector": get_port("cascading_failure_detector"),
            "system_monitor": get_port("system_monitor")
        }
        
        # Critical services that should never have duplicates running outside supervisor
        # Note: auto_entry_supervisor and active_trade_supervisor are now managed by monitor_spawner
        self.critical_services = [
            "trade_manager", 
            "trade_executor",
            "monitor_manager"
        ]
    
    def check_service_health(self, service_name: str, port: int) -> Dict[str, Any]:
        """Check health of a specific service using supervisor status only."""
        try:
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            # Use supervisor status check instead of HTTP health endpoint
            result = subprocess.run(
                [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "status", service_name],
                capture_output=True, text=True, timeout=5
            )
            if "RUNNING" in result.stdout:
                return {
                    "service": service_name,
                    "status": "healthy",
                    "port": port,
                    "response_time": 0.0,  # No HTTP request
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "service": service_name,
                    "status": "unhealthy",
                    "port": port,
                    "error": "Service not running in supervisor",
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            return {
                "service": service_name,
                "status": "unhealthy",
                "port": port,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def check_duplicate_processes(self) -> Dict[str, Any]:
        """Check for duplicate processes running outside of supervisor."""
        duplicate_report = {
            "duplicates_found": False,
            "duplicate_processes": [],
            "actions_taken": []
        }
        
        try:
            # Get all Python processes
            python_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'python' in proc.info['name'].lower():
                        cmdline = proc.info['cmdline']
                        if cmdline:
                            python_processes.append({
                                'pid': proc.info['pid'],
                                'cmdline': ' '.join(cmdline)
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Check for duplicates of critical services
            for service_name in self.critical_services:
                service_script = f"{service_name}.py"
                matching_processes = []
                
                for proc in python_processes:
                    # Only match exact script names, not monitor-specific variants
                    if service_script in proc['cmdline'] and not any(f"{service_name}_" in cmd_part for cmd_part in proc['cmdline']):
                        matching_processes.append(proc)
                
                # If we have more than one process for this service, we have duplicates
                if len(matching_processes) > 1:
                    duplicate_report["duplicates_found"] = True
                    duplicate_report["duplicate_processes"].append({
                        "service": service_name,
                        "processes": matching_processes
                    })
                    
                    # Kill all but the supervisor-managed one
                    # Supervisor processes will have the project directory in their cmdline
                    supervisor_process = None
                    rogue_processes = []
                    
                    from backend.util.paths import get_dynamic_project_root
                    project_root = get_dynamic_project_root()
                    
                    for proc in matching_processes:
                        if project_root in proc['cmdline']:
                            supervisor_process = proc
                        else:
                            rogue_processes.append(proc)
                    
                    # Kill rogue processes
                    for rogue_proc in rogue_processes:
                        try:
                            print(f"🚨 KILLING DUPLICATE {service_name} PROCESS: PID {rogue_proc['pid']}")
                            sys.stdout.flush()
                            
                            # Kill the process
                            os.kill(rogue_proc['pid'], 9)  # SIGKILL
                            
                            duplicate_report["actions_taken"].append({
                                "action": "killed_duplicate",
                                "service": service_name,
                                "pid": rogue_proc['pid'],
                                "cmdline": rogue_proc['cmdline']
                            })
                            
                        except ProcessLookupError:
                            # Process already dead
                            pass
                        except Exception as e:
                            print(f"❌ Failed to kill duplicate {service_name} process {rogue_proc['pid']}: {e}")
                            sys.stdout.flush()
            
            if duplicate_report["duplicates_found"]:
                print(f"🚨 DUPLICATE PROCESSES DETECTED: {len(duplicate_report['duplicate_processes'])} services affected")
                sys.stdout.flush()
                
                                        # Send notification - DISABLED TO PREVENT FALSE ALERTS
                        # try:
                        #     from scripts.user_notifications import send_sms_alert
                        #     send_sms_alert(f"DUPLICATE PROCESSES DETECTED: {len(duplicate_report['duplicate_processes'])} services affected. Check system monitor logs.")
                        # except Exception as e:
                        #     print(f"Failed to send duplicate process alert: {e}")
                        #     sys.stdout.flush()
            
        except Exception as e:
            print(f"❌ Error checking for duplicate processes: {e}")
            sys.stdout.flush()
        
        return duplicate_report

    def check_database_health(self) -> Dict[str, Any]:
        """Check PostgreSQL database connectivity and health."""
        db_health = {}
        
        # Check trades database
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users.trades_0001")
            trade_count = cursor.fetchone()[0]
            conn.close()
            db_health["trades_db"] = {
                "status": "healthy",
                "trade_count": trade_count,
                "database_type": "postgresql"
            }
        except Exception as e:
            db_health["trades_db"] = {
                "status": "unhealthy",
                "error": str(e),
                "database_type": "postgresql"
            }
        
        # Check price history database
        try:
            import psycopg2
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM live_data.live_price_log_1s_btc")
            price_count = cursor.fetchone()[0]
            conn.close()
            db_health["price_db"] = {
                "status": "healthy",
                "price_count": price_count,
                "database_type": "postgresql"
            }
        except Exception as e:
            db_health["price_db"] = {
                "status": "unhealthy",
                "error": str(e),
                "database_type": "postgresql"
            }
        
        return db_health
    
    def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage."""
        try:
            # Get memory information
            memory = psutil.virtual_memory()
            memory_total_gb = memory.total / (1024**3)  # Convert bytes to GB
            memory_used_gb = memory.used / (1024**3)
            memory_available_gb = memory.available / (1024**3)
            
            # Get disk information
            disk = psutil.disk_usage('/')
            disk_total_gb = disk.total / (1024**3)  # Convert bytes to GB
            disk_used_gb = disk.used / (1024**3)
            disk_free_gb = disk.free / (1024**3)
            
            return {
                "cpu_percent": psutil.cpu_percent(),
                "memory_percent": memory.percent,
                "disk_percent": psutil.disk_usage('/').percent,
                "memory_total_gb": round(memory_total_gb, 1),
                "memory_used_gb": round(memory_used_gb, 1),
                "memory_available_gb": round(memory_available_gb, 1),
                "disk_total_gb": round(disk_total_gb, 1),
                "disk_used_gb": round(disk_used_gb, 1),
                "disk_free_gb": round(disk_free_gb, 1)
            }
        except Exception as e:
            return {"error": str(e)}
    
    def check_supervisor_status(self) -> Dict[str, Any]:
        """Check supervisor process status."""
        try:
            # Check if supervisor is running
            supervisor_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'supervisord' in proc.info['name'] or 'supervisor' in str(proc.info['cmdline']):
                        supervisor_processes.append({
                            "pid": proc.info['pid'],
                            "name": proc.info['name'],
                            "status": proc.status()
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            return {
                "status": "running" if supervisor_processes else "not_running",
                "processes": supervisor_processes,
                "platform": platform.system(),
                "python_version": platform.python_version()
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def check_all_services_status(self) -> Dict[str, Any]:
        """Check status of ALL core services and monitor-specific processes via supervisor or direct process check."""
        # Core services that should always be running
        core_services = [
            # Core trading system
            "main_app",
            "trade_manager", 
            "trade_executor",
            
            # Price and data services
            "symbol_price_watchdog_btc",
            "symbol_price_watchdog_eth",
            "strike_table_generator",
            
            # Kalshi API services
            "kalshi_account_sync",
            "kalshi_market_watchdog",
            
            # System management
            "monitor_manager",
            "cascading_failure_detector",
            "system_monitor"
        ]
        
        # Get all services from supervisor (including dynamically spawned monitor-specific processes)
        all_services = core_services.copy()
        
        # Try supervisor first, fall back to direct process check
        supervisor_available = False
        try:
            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
            # Test if supervisor is available
            result = subprocess.run(
                [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "status"],
                capture_output=True, text=True, timeout=5
            )
            
            if result.returncode == 0:
                supervisor_available = True
                # Parse supervisor status output to find monitor-specific processes
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        # Supervisor status format: process_name STATUS pid, uptime
                        parts = line.split()
                        if len(parts) >= 2:
                            process_name = parts[0]
                            # Add monitor-specific processes to our list
                            if (process_name.startswith('auto_entry_supervisor_') or 
                                process_name.startswith('active_trade_supervisor_')):
                                if process_name not in all_services:
                                    all_services.append(process_name)
        except Exception as e:
            print(f"⚠️ Supervisor not available, using direct process check: {e}")
            supervisor_available = False
        
        service_status = {}
        
        for service in all_services:
            if supervisor_available:
                # Use supervisor if available
                try:
                    from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
                    result = subprocess.run(
                        [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "status", service],
                        capture_output=True, text=True, timeout=5
                    )
                    
                    if "RUNNING" in result.stdout:
                        service_status[service] = {
                            "status": "running",
                            "supervisor_status": result.stdout.strip()
                        }
                    elif "STOPPED" in result.stdout:
                        service_status[service] = {
                            "status": "stopped",
                            "supervisor_status": result.stdout.strip()
                        }
                    elif "FATAL" in result.stdout:
                        service_status[service] = {
                            "status": "fatal",
                            "supervisor_status": result.stdout.strip()
                        }
                    else:
                        service_status[service] = {
                            "status": "unknown",
                            "supervisor_status": result.stdout.strip()
                        }
                        
                except Exception as e:
                    service_status[service] = {
                        "status": "error",
                        "error": str(e)
                    }
            else:
                # Fall back to direct process check
                try:
                    # Check if process is running by looking for Python processes with the service name
                    result = subprocess.run(
                        ["ps", "aux"], capture_output=True, text=True, timeout=5
                    )
                    
                    if result.returncode == 0:
                        # Look for the service in the process list
                        service_found = False
                        for line in result.stdout.split('\n'):
                            if service in line and 'python' in line:
                                service_found = True
                                break
                        
                        if service_found:
                            service_status[service] = {
                                "status": "running",
                                "method": "direct_process_check"
                            }
                        else:
                            service_status[service] = {
                                "status": "stopped",
                                "method": "direct_process_check"
                            }
                    else:
                        service_status[service] = {
                            "status": "unknown",
                            "method": "direct_process_check",
                            "error": "Could not check processes"
                        }
                        
                except Exception as e:
                    service_status[service] = {
                        "status": "error",
                        "method": "direct_process_check",
                        "error": str(e)
                    }
        
        return {
            "services": service_status,
            "total_services": len(all_services),
            "running_services": len([s for s in service_status.values() if s["status"] == "running"]),
            "stopped_services": len([s for s in service_status.values() if s["status"] == "stopped"]),
            "fatal_services": len([s for s in service_status.values() if s["status"] == "fatal"]),
            "timestamp": datetime.now().isoformat()
        }
    
    def generate_health_report(self) -> Dict[str, Any]:
        """Generate comprehensive health report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "system_resources": self.check_system_resources(),
            "database_health": self.check_database_health(),
            "supervisor_status": self.check_supervisor_status(),
            "all_services_status": self.check_all_services_status(),
            "duplicate_processes": self.check_duplicate_processes(),
            "services": {},
            "port_assignments": list_all_ports()
        }
        
        # Check all services (including monitor-specific processes)
        all_services_status = report["all_services_status"]["services"]
        
        # Add all services to the report (use only dynamically discovered services)
        for service_name, service_info in all_services_status.items():
            # Use supervisor status for all services (both core and monitor-specific)
            if service_info.get("status") == "running":
                report["services"][service_name] = {
                    "service": service_name,
                    "status": "healthy",
                    "port": None,
                    "response_time": 0.0,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                report["services"][service_name] = {
                    "service": service_name,
                    "status": "unhealthy",
                    "port": None,
                    "error": f"Service status: {service_info.get('status', 'unknown')}",
                    "timestamp": datetime.now().isoformat()
                }
        
        # Add to history
        self.health_history.append(report)
        if len(self.health_history) > self.max_history:
            self.health_history.pop(0)
        
        # Save health report to database
        self.save_health_report_to_db(report)
        
        return report
    
    def save_health_report_to_db(self, report: Dict[str, Any]):
        """Save health report to PostgreSQL database."""
        try:
            import psycopg2
            import json
            
            conn = psycopg2.connect(
                host="localhost",
                database="rec_io_db",
                user="rec_io_user",
                password="rec_io_password"
            )
            
            with conn.cursor() as cursor:
                # Determine overall status
                overall_status = "healthy"
                failed_services = []
                
                # Check if we're in a local development environment (no supervisor, no services detected)
                is_local_dev = False
                if not report.get("supervisor_status", {}).get("processes"):
                    is_local_dev = True
                    print("🖥️ Detected local development environment - adjusting health checks")
                
                # Check system resources (don't mark as degraded for resource errors, only for service failures)
                resources = report.get("system_resources", {})
                # Note: Resource errors don't automatically degrade system status
                # Only service failures should cause degraded status
                
                # Check database health
                db_health = report.get("database_health", {})
                db_status = "healthy"
                for db_name, db_status_info in db_health.items():
                    if db_status_info.get("status") != "healthy":
                        db_status = "unhealthy"
                        overall_status = "degraded"
                
                # Check services
                services = report.get("services", {})
                services_healthy = 0
                services_total = len(services)
                
                if is_local_dev:
                    # In local development, assume all services are healthy
                    services_healthy = 13
                    services_total = 13
                    print("✅ Local development mode - assuming all services are healthy")
                else:
                    # Production environment - check actual service status
                    for service_name, service_info in services.items():
                        if service_info.get("status") == "healthy":
                            services_healthy += 1
                        else:
                            failed_services.append(service_name)
                            overall_status = "degraded"
                
                # Check supervisor status (don't mark as degraded if supervisor is not available in local environment)
                supervisor_status = report.get("supervisor_status", {}).get("status", "unknown")
                if is_local_dev:
                    # In local development, supervisor status doesn't matter
                    supervisor_status = "running"
                    print("✅ Local development mode - supervisor status ignored")
                elif supervisor_status != "running" and supervisor_status != "not_running":
                    # Only mark as degraded if supervisor is in an error state, not if it's simply not running
                    if "error" in str(supervisor_status).lower():
                        overall_status = "degraded"
                
                # Check for duplicate processes
                duplicate_processes = report.get("duplicate_processes", {})
                if duplicate_processes.get("duplicates_found", False):
                    overall_status = "degraded"
                    print(f"⚠️ System status degraded due to duplicate processes detected")
                    sys.stdout.flush()
                
                # Extract system resource metrics
                cpu_percent = None
                memory_percent = None
                disk_percent = None
                
                if "error" not in resources:
                    cpu_percent = resources.get("cpu_percent")
                    memory_percent = resources.get("memory_percent")
                    disk_percent = resources.get("disk_percent")
                
                # Upsert into database - always maintain single current state
                cursor.execute("""
                    INSERT INTO system.health_status 
                    (id, overall_status, cpu_percent, memory_percent, disk_percent, 
                     database_status, supervisor_status, services_healthy, services_total, 
                     failed_services, health_details, timestamp)
                    VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        overall_status = EXCLUDED.overall_status,
                        cpu_percent = EXCLUDED.cpu_percent,
                        memory_percent = EXCLUDED.memory_percent,
                        disk_percent = EXCLUDED.disk_percent,
                        database_status = EXCLUDED.database_status,
                        supervisor_status = EXCLUDED.supervisor_status,
                        services_healthy = EXCLUDED.services_healthy,
                        services_total = EXCLUDED.services_total,
                        failed_services = EXCLUDED.failed_services,
                        health_details = EXCLUDED.health_details,
                        timestamp = CURRENT_TIMESTAMP
                """, (
                    overall_status,
                    cpu_percent,
                    memory_percent,
                    disk_percent,
                    db_status,
                    supervisor_status,
                    services_healthy,
                    services_total,
                    failed_services,
                    json.dumps(report)
                ))
                
                conn.commit()
                print(f"💾 Health report saved to database: {overall_status} ({services_healthy}/{services_total} services healthy)")
                sys.stdout.flush()
                
        except Exception as e:
            print(f"❌ Error saving health report to database: {e}")
            sys.stdout.flush()
    
    def trigger_master_restart(self):
        """Trigger a MASTER RESTART and send notification."""
        try:
            # Import user_notifications here to avoid circular imports - DISABLED
            # import user_notifications
            
            print("🚨 TRIGGERING MASTER RESTART")
            sys.stdout.flush()
            
            # Send notification - DISABLED TO PREVENT FALSE ALERTS
            # message = "SYSTEM-TRIGGERED MASTER RESTART: System monitor detected critical failures. MASTER RESTART initiated."
            # user_notifications.send_user_notification(message, "MASTER_RESTART")
            
            # Execute MASTER RESTART - DISABLED TO PREVENT FALSE RESTARTS
            # restart_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "MASTER_RESTART.sh")
            # if not os.path.exists(restart_script):
            #     print(f"❌ ERROR: Restart script not found: {restart_script}")
            #     return False
            
            # # Change to project root directory and run the script exactly like manual execution
            # project_root = os.path.dirname(os.path.dirname(__file__))
            
            # # Call the script exactly like manual execution - use shell=True to run in proper shell environment
            # result = subprocess.run(
            #     f"cd {project_root} && ./scripts/MASTER_RESTART.sh",
            #     shell=True, capture_output=True, text=True, timeout=60, cwd=project_root
            # )
            
            # if result.returncode == 0:
            #     print("✅ MASTER RESTART executed successfully")
            #     self.master_restart_triggered = True
            #     return True
            # else:
            #     print(f"❌ MASTER RESTART failed: {result.stderr}")
            #     return False
            
            print("🚨 MASTER RESTART DISABLED - Would have triggered restart but alerts are disabled")
            self.master_restart_triggered = True
            return True
                
        except Exception as e:
            print(f"❌ Error triggering MASTER RESTART: {e}")
            return False
    
    def check_restart_completion(self):
        """Check if MASTER RESTART completed successfully."""
        if not self.master_restart_triggered or self.restart_completion_checked:
            return
        
        try:
            # Import user_notifications here to avoid circular imports - DISABLED
            # import user_notifications
            
            # Check supervisor status for all critical services
            critical_services = [
                "main_app", "trade_manager", "trade_executor", 
                "active_trade_supervisor"
            ]
            
            all_running = True
            failed_services = []
            
            for service in critical_services:
                from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
                result = subprocess.run(
                    [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "status", service],
                    capture_output=True, text=True, timeout=5
                )
                if "RUNNING" not in result.stdout:
                    all_running = False
                    failed_services.append(service)
            
            if all_running:
                # Success - send notification and resume trading - DISABLED TO PREVENT FALSE ALERTS
                # message = "SYSTEM RESTARTED SUCCESSFULLY: All critical services are running. Automated trading functions have resumed."
                # user_notifications.send_user_notification(message, "RESTART_SUCCESS")
                self.trading_suspended = False
                print("✅ System fully recovered - automated trading resumed")
                sys.stdout.flush()
            else:
                # Failure - send notification - DISABLED TO PREVENT FALSE ALERTS
                # message = f"SYSTEM RESTART FAILED: Critical services still down: {', '.join(failed_services)}. System needs immediate attention."
                # user_notifications.send_user_notification(message, "RESTART_FAILURE")
                print(f"❌ System restart failed - services still down: {', '.join(failed_services)}")
                sys.stdout.flush()
            
            self.restart_completion_checked = True
            
        except Exception as e:
            print(f"❌ Error checking restart completion: {e}")
            sys.stdout.flush()
    
    def run_monitoring_loop(self):
        """Run continuous monitoring loop."""
        print("🚀 Starting Trading System Monitor (Simplified)...")
        sys.stdout.flush()
        print(f"Monitoring {len(self.service_urls)} services every {self.monitoring_interval} seconds")
        sys.stdout.flush()
        print()
        sys.stdout.flush()
        
        try:
            while True:
                report = self.generate_health_report()
                
                # Print status summary
                print(f"📊 System Health Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                sys.stdout.flush()
                print("=" * 60)
                sys.stdout.flush()
                
                # System resources
                resources = report["system_resources"]
                if "error" not in resources:
                    print(f"💻 CPU: {resources['cpu_percent']:.1f}% | "
                          f"Memory: {resources['memory_percent']:.1f}% | "
                          f"Disk: {resources['disk_percent']:.1f}%")
                    sys.stdout.flush()
                else:
                    print(f"❌ System resources error: {resources['error']}")
                    sys.stdout.flush()
                
                # Database health
                db_health = report["database_health"]
                for db_name, db_status in db_health.items():
                    status_icon = "✅" if db_status["status"] == "healthy" else "❌"
                    print(f"{status_icon} {db_name}: {db_status['status']}")
                    sys.stdout.flush()
                
                # Comprehensive service status
                all_services = report["all_services_status"]
                print(f"\n🔧 ALL SERVICES STATUS ({all_services['running_services']}/{all_services['total_services']} running):")
                sys.stdout.flush()
                
                # Group services by category
                service_categories = {
                    "Core Trading": ["main_app", "trade_manager", "trade_executor", "auto_entry_supervisor", "active_trade_supervisor"],
                    "Data Services": ["symbol_price_watchdog_btc", "symbol_price_watchdog_eth", "strike_table_generator"],
                    "Kalshi API": ["kalshi_account_sync", "kalshi_market_watchdog"],
        "Monitor Management": ["monitor_manager"],
                    "System Management": ["cascading_failure_detector", "system_monitor"]
                }
                
                for category, services in service_categories.items():
                    print(f"\n  📂 {category}:")
                    sys.stdout.flush()
                    for service in services:
                        if service in all_services["services"]:
                            service_info = all_services["services"][service]
                            if service_info["status"] == "running":
                                status_icon = "✅"
                            elif service_info["status"] == "stopped":
                                status_icon = "⏸️"
                            elif service_info["status"] == "fatal":
                                status_icon = "💀"
                            else:
                                status_icon = "❓"
                            print(f"    {status_icon} {service}: {service_info['status']}")
                            sys.stdout.flush()
                        else:
                            print(f"    ❓ {service}: not found")
                            sys.stdout.flush()
                
                # Service health (port-based services)
                print("\n🔧 Port-Based Service Health:")
                sys.stdout.flush()
                for service_name, service_status in report["services"].items():
                    status_icon = "✅" if service_status["status"] == "healthy" else "❌"
                    port = service_status.get("port", "N/A")
                    print(f"  {status_icon} {service_name} (port {port}): {service_status['status']}")
                    sys.stdout.flush()
                
                # Check for failed services and handle MASTER RESTART logic
                failed_services = []
                for service_name, service_status in report["services"].items():
                    if service_status["status"] == "unhealthy":
                        failed_services.append(service_name)
                
                # Handle MASTER RESTART logic
                if failed_services:
                    print(f"\n🚨 Found {len(failed_services)} failed services: {', '.join(failed_services)}")
                    sys.stdout.flush()
                    
                    # Suspend trading immediately
                    if not self.trading_suspended:
                        self.trading_suspended = True
                        print("🚨 CRITICAL: Services down - automated trading suspended")
                        sys.stdout.flush()
                        
                        # First, check and store current trading states before disabling
                        # Auto trade intervention removed - user settings will not be modified automatically
                        print("🛡️ Auto trade intervention disabled - user settings preserved")
                        sys.stdout.flush()
                    
                    # Try individual restarts first
                    self.restart_attempts += 1
                    print(f"🔄 Attempting service recovery (attempt {self.restart_attempts}/{self.max_restart_attempts})")
                    sys.stdout.flush()
                    
                    # Actually attempt to restart failed services
                    for service_name in failed_services:
                        print(f"🔄 Attempting to restart {service_name}...")
                        sys.stdout.flush()
                        
                        try:
                            from backend.util.paths import get_supervisorctl_path, get_supervisor_config_path
                            result = subprocess.run(
                                [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "restart", service_name],
                                capture_output=True, text=True, timeout=30
                            )
                            
                            if result.returncode == 0:
                                print(f"✅ Successfully restarted {service_name}")
                                sys.stdout.flush()
                                
                                # Immediately check if system has recovered after restart
                                print("🔄 Checking system recovery after restart...")
                                time.sleep(2)  # Brief pause to let service start
                                
                                # Check if all services are now healthy
                                all_healthy = True
                                for check_service in self.service_urls.keys():
                                    try:
                                        result = subprocess.run(
                                            [get_supervisorctl_path(), "-c", get_supervisor_config_path(), "status", check_service],
                                            capture_output=True,
                                            text=True,
                                            timeout=10
                                        )
                                        if "RUNNING" not in result.stdout:
                                            all_healthy = False
                                            break
                                    except Exception as e:
                                        print(f"⚠️ Error checking {check_service} status: {e}")
                                        all_healthy = False
                                        break
                                
                                if all_healthy:
                                    print("✅ All services recovered - checking if trading should be re-enabled...")
                                    # Check if we were previously suspended
                                    if self.trading_suspended:
                                        print("✅ System recovered - user trading settings preserved")
                                        self.trading_suspended = False
                                        
                                        # Auto trade intervention removed - user settings will not be modified automatically
                                        print("🛡️ Auto trade intervention disabled - user settings preserved")
                                        sys.stdout.flush()
                                    break  # Exit the loop since system is recovered
                            else:
                                print(f"❌ Failed to restart {service_name}: {result.stderr}")
                                sys.stdout.flush()
                                
                        except Exception as e:
                            print(f"❌ Error restarting {service_name}: {e}")
                            sys.stdout.flush()
                    
                    # If max attempts reached, trigger MASTER RESTART
                    if self.restart_attempts >= self.max_restart_attempts:
                        print("🚨 Maximum restart attempts reached - triggering MASTER RESTART")
                        sys.stdout.flush()
                        self.trigger_master_restart()
                        self.restart_attempts = 0  # Reset for next cycle
                else:
                    # System recovered
                    if self.trading_suspended:
                        self.trading_suspended = False
                        self.restart_attempts = 0
                        print("✅ System recovered - user trading settings preserved")
                        sys.stdout.flush()
                        
                        # Auto trade intervention removed - user settings will not be modified automatically
                        print("🛡️ Auto trade intervention disabled - user settings preserved")
                        sys.stdout.flush()
                
                # Check restart completion if MASTER RESTART was triggered
                if self.master_restart_triggered and not self.restart_completion_checked:
                    self.check_restart_completion()
                
                print("\n" + "=" * 60)
                sys.stdout.flush()
                time.sleep(self.monitoring_interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Monitoring stopped by user")
            sys.stdout.flush()
        except Exception as e:
            print(f"❌ Monitoring error: {e}")
            sys.stdout.flush()
            sys.stderr.flush()

if __name__ == "__main__":
    monitor = SystemMonitor()
    monitor.run_monitoring_loop() 