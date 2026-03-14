#!/usr/bin/env python3
"""
UNIFIED SUPERVISOR CONFIGURATION GENERATOR
Generate supervisor configuration with unified configuration system.
Uses absolute paths and proper environment variables.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path (script lives in scripts/config/)
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
sys.path.insert(0, str(project_root))

from backend.core.unified_config import unified_config
from backend.core.config.database import get_database_config, get_postgresql_connection
from backend.core.path_manager import PathManager
from backend.core.host_detector import HostDetector
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SupervisorConfigGenerator:
    """Generate supervisor config with unified configuration"""
    
    def __init__(self):
        """Initialize the supervisor config generator"""
        self.config = unified_config
        self.path_manager = PathManager(unified_config)
        self.host_detector = HostDetector(unified_config.project_root)
        
        logger.info("SupervisorConfigGenerator initialized")
    
    def generate_config(self) -> bool:
        """Generate complete supervisor configuration"""
        try:
            logger.info("Generating unified supervisor configuration...")
            
            # Validate configuration
            if not self.config.validate_config():
                logger.error("Configuration validation failed")
                return False
            
            # Get configuration values
            project_root = self.config.project_root
            python_executable = self.config.get('runtime.python_executable', sys.executable)
            system_host = self.config.get('runtime.system_host', 'localhost')
            
            # Get port assignments from MASTER_PORT_MANIFEST
            ports = self._get_port_assignments()
            
            # Generate supervisor configuration content
            supervisor_config = self._generate_supervisor_content(
                project_root, python_executable, system_host, ports
            )
            
            # Write supervisor configuration file
            supervisor_config_path = self.path_manager.get_supervisor_config_path()
            self.path_manager.ensure_file_directory_exists(supervisor_config_path)
            
            with open(supervisor_config_path, 'w') as f:
                f.write(supervisor_config)
            
            logger.info(f"Generated supervisor configuration: {supervisor_config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating supervisor configuration: {e}")
            return False
    
    def _get_active_monitors(self) -> list:
        """Get active monitors from database"""
        try:
            conn = get_postgresql_connection()
            if not conn:
                logger.error("Database connection failed")
                return []
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
                logger.info(f"Found {len(monitors)} active monitors in database")
                return monitors
                
        except Exception as e:
            logger.error(f"Error getting active monitors from database: {e}")
            # Return default monitor if database query fails
            return []  # No default monitors - must be configured

    def _get_port_assignments(self) -> dict:
        """Get port assignments from MASTER_PORT_MANIFEST"""
        try:
            # Try to load from MASTER_PORT_MANIFEST
            manifest_path = self.path_manager.get_config_file_path("MASTER_PORT_MANIFEST")
            
            if self.path_manager.path_exists(manifest_path):
                import json
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                
                ports = {}
                
                # Extract ports from core_services
                for service_name, service_config in manifest.get("core_services", {}).items():
                    ports[service_name] = service_config.get("port", 3000)
                
                # Extract ports from watchdog_services
                for service_name, service_config in manifest.get("watchdog_services", {}).items():
                    ports[service_name] = service_config.get("port", 8000)
                
                logger.info(f"Loaded port assignments from MASTER_PORT_MANIFEST: {ports}")
                return ports
            
            # Fallback to default ports
            default_ports = {
                "main_app": 3000,
                "trade_manager": 4000,
                "trade_executor": 8001,
                "active_trade_supervisor": 6000,
                "auto_entry_supervisor": 8002,
                "symbol_price_watchdog_btc": 8008,
                "symbol_price_watchdog_eth": 8009,
                "symbol_price_watchdog_spx": 8017,
                "symbol_price_watchdog_ndx": 8019,
                "kalshi_account_sync": 8004,
                "kalshi_market_watchdog_hourly_btc": 8005,
                "kalshi_market_watchdog_hourly_eth": 8010,
                "kalshi_market_watchdog_hourly_spx": 8018,
                "kalshi_market_watchdog_hourly_ndx": 8020,
                "kalshi_market_watchdog_15m_btc": 8021,
                "kalshi_market_watchdog_15m_eth": 8022,
                "strike_table_generator_hourly_btc": 8014,
                "strike_table_generator_hourly_eth": 8015,
                "strike_table_generator_hourly_spx": 8016,
                "strike_table_generator_hourly_ndx": 8017,
                "strike_table_generator_15m_btc": 8023,
                "strike_table_generator_15m_eth": 8024,
                "system_monitor": 8006,
                "monitor_manager": 8012,
                "cascading_failure_detector": 8007
            }
            
            logger.info(f"Using default port assignments: {default_ports}")
            return default_ports
            
        except Exception as e:
            logger.error(f"Error getting port assignments: {e}")
            return {}
    
    def _generate_supervisor_content(self, project_root: str, python_executable: str, 
                                   system_host: str, ports: dict) -> str:
        """Generate supervisor configuration content"""
        
        # Get database configuration
        db_config = get_database_config()
        
        # Create environment variables string
        env_vars = self._create_environment_variables(db_config, system_host)
        
        # Log directory for supervisord and all program logs (durable; see docs/CRITICAL_ASSET_LOGGING.md)
        log_dir = self.path_manager.get_log_directory()
        
        # Get active monitors from database
        active_monitors = self._get_active_monitors()
        logger.info(f"Found {len(active_monitors)} active monitors: {active_monitors}")
        
        # Define core services to configure
        services = [
            {
                "name": "main_app",
                "script": "main.py",
                "port": ports.get("main_app", 3000)
            },
            {
                "name": "trade_manager",
                "script": "trade_manager.py",
                "port": ports.get("trade_manager", 4000)
            },
            {
                "name": "trade_executor",
                "script": "trade_executor.py",
                "port": ports.get("trade_executor", 8001)
            },
            {
                "name": "symbol_price_watchdog_btc",
                "script": "symbol_price_watchdog.py BTC",
                "port": ports.get("symbol_price_watchdog_btc", 8008)
            },
            {
                "name": "symbol_price_watchdog_eth",
                "script": "symbol_price_watchdog.py ETH",
                "port": ports.get("symbol_price_watchdog_eth", 8009)
            },
            # SPX/NDX not currently traded; uncomment to re-enable later.
            # {
            #     "name": "symbol_price_watchdog_spx",
            #     "script": "symbol_price_watchdog.py SPX",
            #     "port": ports.get("symbol_price_watchdog_spx", 8017)
            # },
            # {
            #     "name": "symbol_price_watchdog_ndx",
            #     "script": "symbol_price_watchdog.py NDX",
            #     "port": ports.get("symbol_price_watchdog_ndx", 8019)
            # },
            {
                "name": "kalshi_account_sync",
                "script": "kalshi_account_sync_ws.py",
                "port": ports.get("kalshi_account_sync", 8004)
            },
            {
                "name": "kalshi_market_watchdog_hourly_btc",
                "script": "kalshi_market_watchdog.py BTC",
                "port": ports.get("kalshi_market_watchdog_hourly_btc", 8005)
            },
            {
                "name": "kalshi_market_watchdog_hourly_eth",
                "script": "kalshi_market_watchdog.py ETH",
                "port": ports.get("kalshi_market_watchdog_hourly_eth", 8010)
            },
            # SPX/NDX not currently traded; uncomment to re-enable later.
            # {
            #     "name": "kalshi_market_watchdog_hourly_spx",
            #     "script": "kalshi_market_watchdog.py SPX",
            #     "port": ports.get("kalshi_market_watchdog_hourly_spx", 8018)
            # },
            # {
            #     "name": "kalshi_market_watchdog_hourly_ndx",
            #     "script": "kalshi_market_watchdog.py NDX",
            #     "port": ports.get("kalshi_market_watchdog_hourly_ndx", 8020)
            # },
            {
                "name": "kalshi_market_watchdog_15m_btc",
                "script": "kalshi_market_watchdog.py BTC --interval 15m",
                "port": ports.get("kalshi_market_watchdog_15m_btc", 8021)
            },
            {
                "name": "kalshi_market_watchdog_15m_eth",
                "script": "kalshi_market_watchdog.py ETH --interval 15m",
                "port": ports.get("kalshi_market_watchdog_15m_eth", 8022)
            },
            {
                "name": "system_monitor",
                "script": "system_monitor.py",
                "port": ports.get("system_monitor", 8006)
            },
            {
                "name": "monitor_manager",
                "script": "monitor_manager.py",
                "port": ports.get("monitor_manager", 8012)
            },
            {
                "name": "cascading_failure_detector",
                "script": "cascading_failure_detector.py",
                "port": ports.get("cascading_failure_detector", 8007)
            }
        ]
        
        # Add monitor-specific services for each active monitor
        monitor_port_base = 8015  # Start monitor ports at 8015
        for i, monitor in enumerate(active_monitors):
            user_number = monitor['user_number']
            monitor_id = monitor['monitor_id']
            monitor_identifier = f"{user_number}_{monitor_id}"
            
            # Auto entry supervisor for this monitor
            auto_entry_port = monitor_port_base + (i * 2)
            services.append({
                "name": f"auto_entry_supervisor_{monitor_identifier}",
                "script": f"auto_entry_supervisor.py {monitor_identifier}",
                "port": auto_entry_port
            })
            
            # Active trade supervisor for this monitor
            active_trade_port = monitor_port_base + (i * 2) + 1
            services.append({
                "name": f"active_trade_supervisor_{monitor_identifier}",
                "script": f"active_trade_supervisor.py {monitor_identifier}",
                "port": active_trade_port
            })
        
        # Add symbol-specific strike table generators (hourly).
        # SPX/NDX not currently traded; add 'SPX', 'NDX' to supported_symbols to re-enable.
        supported_symbols = ['BTC', 'ETH']  # was ['BTC', 'ETH', 'SPX', 'NDX']
        strike_table_default_ports = {
            'btc': 8014, 'eth': 8015, 'spx': 8016, 'ndx': 8017
        }
        for symbol in supported_symbols:
            key = f"strike_table_generator_hourly_{symbol.lower()}"
            services.append({
                "name": key,
                "script": f"strike_table_generator.py {symbol} continuous 1",
                "port": ports.get(key, strike_table_default_ports[symbol.lower()])
            })
        # 15m strike table generators (BTC, ETH only)
        for symbol in ['BTC', 'ETH']:
            key = f"strike_table_generator_15m_{symbol.lower()}"
            services.append({
                "name": key,
                "script": f"strike_table_generator.py {symbol} continuous 1 --interval 15m",
                "port": ports.get(key, 8023 if symbol == 'BTC' else 8024)
            })
        
        # Supervisord main log: durable path under logs/ with rotation (critical for incident review)
        supervisord_log = os.path.join(log_dir, "supervisord.log")
        
        # Generate supervisor configuration
        config_content = f"""[supervisord]
nodaemon=true
logfile={supervisord_log}
logfile_maxbytes=50MB
logfile_backups=10
pidfile=/tmp/supervisord.pid
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0

[supervisorctl]
serverurl=unix:///tmp/supervisord.sock

[unix_http_server]
file=/tmp/supervisord.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface


"""
        
        # Critical assets get higher log retention (see docs/CRITICAL_ASSET_LOGGING.md)
        CRITICAL_LOG_SERVICES = {"system_monitor", "cascading_failure_detector"}
        CRITICAL_STDOUT_MAX, CRITICAL_STDOUT_BACKUPS = "20MB", 10
        CRITICAL_STDERR_MAX, CRITICAL_STDERR_BACKUPS = "10MB", 10
        DEFAULT_STDOUT_MAX, DEFAULT_STDOUT_BACKUPS = "10MB", 5
        DEFAULT_STDERR_MAX, DEFAULT_STDERR_BACKUPS = "5MB", 5
        
        # Generate program sections
        for service in services:
            service_name = service["name"]
            script_path = service["script"]
            port = service["port"]
            
            stdout_log = os.path.join(log_dir, f"{service_name}.out.log")
            stderr_log = os.path.join(log_dir, f"{service_name}.err.log")
            if service_name in CRITICAL_LOG_SERVICES:
                stderr_max, stderr_backups = CRITICAL_STDERR_MAX, CRITICAL_STDERR_BACKUPS
                stdout_max, stdout_backups = CRITICAL_STDOUT_MAX, CRITICAL_STDOUT_BACKUPS
            else:
                stderr_max, stderr_backups = DEFAULT_STDERR_MAX, DEFAULT_STDERR_BACKUPS
                stdout_max, stdout_backups = DEFAULT_STDOUT_MAX, DEFAULT_STDOUT_BACKUPS
            
            run_cmd = f'{python_executable} {project_root}/backend/{script_path}'
            # Create program section
            config_content += f"""[program:{service_name}]
command={run_cmd}
directory={project_root}
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile={stderr_log}
stderr_logfile_maxbytes={stderr_max}
stderr_logfile_backups={stderr_backups}
stdout_logfile={stdout_log}
stdout_logfile_maxbytes={stdout_max}
stdout_logfile_backups={stdout_backups}
environment={env_vars}

"""
        
        return config_content
    
    def _create_environment_variables(self, db_config: dict, system_host: str) -> str:
        """Create environment variables string for supervisor"""
        try:
            env_vars = [
                f'PATH="{self.config.get("runtime.venv_path", "")}/bin"',
                f'PYTHONPATH="{self.config.project_root}"',
                'PYTHONGC=1',
                'PYTHONDNSCACHE=1',
                'PYTHONDONTWRITEBYTECODE=1',
                f'TRADING_SYSTEM_HOST="{system_host}"',
                f'REC_SYSTEM_HOST="{system_host}"',
                f'REC_PROJECT_ROOT="{self.config.project_root}"',
                f'REC_ENVIRONMENT="{self.config.get("system.environment", "development")}"',
                f'DB_HOST="{db_config.get("host", "localhost")}"',
                f'DB_NAME="{db_config.get("database", db_config.get("name", "rec_io_db"))}"',
                f'DB_USER="{db_config.get("user", "rec_io_user")}"',
                f'DB_PASSWORD="{db_config.get("password", "")}"',
                f'DB_PORT="{db_config.get("port", 5432)}"',
                f'POSTGRES_HOST="{db_config.get("host", "localhost")}"',
                f'POSTGRES_DB="{db_config.get("database", db_config.get("name", "rec_io_db"))}"',
                f'POSTGRES_USER="{db_config.get("user", "rec_io_user")}"',
                f'POSTGRES_PASSWORD="{db_config.get("password", "")}"',
                f'POSTGRES_PORT="{db_config.get("port", 5432)}"',
                f'REC_DB_HOST="{db_config.get("host", "localhost")}"',
                f'REC_DB_NAME="{db_config.get("database", db_config.get("name", "rec_io_db"))}"',
                f'REC_DB_USER="{db_config.get("user", "rec_io_user")}"',
                f'REC_DB_PASS="{db_config.get("password", "")}"',
                f'REC_DB_PORT="{db_config.get("port", 5432)}"',
                f'REC_DB_SSLMODE="{db_config.get("sslmode", "disable")}"'
            ]
            
            return ','.join(env_vars)
            
        except Exception as e:
            logger.error(f"Error creating environment variables: {e}")
            return f'PATH="{self.config.get("runtime.venv_path", "")}/bin",PYTHONPATH="{self.config.project_root}",PYTHONGC=1,PYTHONDNSCACHE=1'
    
    def validate_generated_config(self) -> bool:
        """Validate the generated supervisor configuration"""
        try:
            supervisor_config_path = self.path_manager.get_supervisor_config_path()
            
            if not self.path_manager.path_exists(supervisor_config_path):
                logger.error("Supervisor configuration file does not exist")
                return False
            
            # Check if file is readable
            with open(supervisor_config_path, 'r') as f:
                content = f.read()
            
            # Basic validation checks
            required_sections = [
                "[supervisord]",
                "[supervisorctl]",
                "[unix_http_server]",
                "[program:main_app]"
            ]
            
            for section in required_sections:
                if section not in content:
                    logger.error(f"Missing required section in supervisor config: {section}")
                    return False
            
            logger.info("Supervisor configuration validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Error validating supervisor configuration: {e}")
            return False
    
    def get_config_summary(self) -> dict:
        """Get summary of the generated configuration"""
        try:
            supervisor_config_path = self.path_manager.get_supervisor_config_path()
            
            summary = {
                "supervisor_config_path": supervisor_config_path,
                "config_exists": self.path_manager.path_exists(supervisor_config_path),
                "project_root": self.config.project_root,
                "system_host": self.config.get('runtime.system_host'),
                "python_executable": self.config.get('runtime.python_executable'),
                "log_directory": self.path_manager.get_log_directory(),
                "database_config": self.config.get_database_config(),
                "validation_passed": self.validate_generated_config()
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting config summary: {e}")
            return {"error": str(e)}

def main():
    """Main function to generate supervisor configuration"""
    try:
        logger.info("Starting unified supervisor configuration generation...")
        
        # Initialize generator
        generator = SupervisorConfigGenerator()
        
        # Generate configuration
        success = generator.generate_config()
        
        if success:
            # Validate generated configuration
            if generator.validate_generated_config():
                logger.info("✅ Supervisor configuration generated and validated successfully")
                
                # Print summary
                summary = generator.get_config_summary()
                logger.info("Configuration Summary:")
                for key, value in summary.items():
                    logger.info(f"  {key}: {value}")
                
                return 0
            else:
                logger.error("❌ Supervisor configuration validation failed")
                return 1
        else:
            logger.error("❌ Failed to generate supervisor configuration")
            return 1
            
    except Exception as e:
        logger.error(f"❌ Error in main function: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
