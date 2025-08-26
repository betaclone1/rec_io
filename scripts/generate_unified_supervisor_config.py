#!/usr/bin/env python3
"""
UNIFIED SUPERVISOR CONFIGURATION GENERATOR
Generate supervisor configuration with unified configuration system.
Uses absolute paths and proper environment variables.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
current_dir = Path(__file__).parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

from backend.core.unified_config import unified_config
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
                "kalshi_account_sync": 8004,
                "kalshi_market_watchdog": 8005,
                "system_monitor": 8006,
                "cascading_failure_detector": 8007,
                "strike_table_generator": 8010
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
        db_config = self.config.get_database_config()
        
        # Create environment variables string
        env_vars = self._create_environment_variables(db_config, system_host)
        
        # Define services to configure
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
                "name": "active_trade_supervisor",
                "script": "active_trade_supervisor.py",
                "port": ports.get("active_trade_supervisor", 6000)
            },
            {
                "name": "auto_entry_supervisor",
                "script": "auto_entry_supervisor.py",
                "port": ports.get("auto_entry_supervisor", 8002)
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
            {
                "name": "strike_table_generator",
                "script": "strike_table_generator.py continuous 1",
                "port": ports.get("strike_table_generator", 8010)
            },
            {
                "name": "kalshi_account_sync",
                "script": "kalshi_account_sync_ws.py",
                "port": ports.get("kalshi_account_sync", 8004)
            },
            {
                "name": "kalshi_market_watchdog",
                "script": "kalshi_market_watchdog.py",
                "port": ports.get("kalshi_market_watchdog", 8005)
            },
            {
                "name": "system_monitor",
                "script": "system_monitor.py",
                "port": ports.get("system_monitor", 8006)
            },
            {
                "name": "cascading_failure_detector",
                "script": "cascading_failure_detector.py",
                "port": ports.get("cascading_failure_detector", 8007)
            }
        ]
        
        # Generate supervisor configuration
        config_content = f"""[supervisord]
nodaemon=true
logfile=/tmp/supervisord.log
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
        
        # Generate program sections
        for service in services:
            service_name = service["name"]
            script_path = service["script"]
            port = service["port"]
            
            # Get log file paths
            log_dir = self.path_manager.get_log_directory()
            stdout_log = os.path.join(log_dir, f"{service_name}.out.log")
            stderr_log = os.path.join(log_dir, f"{service_name}.err.log")
            
            # Create program section
            config_content += f"""[program:{service_name}]
command={python_executable} {project_root}/backend/{script_path}
directory={project_root}
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile={stderr_log}
stdout_logfile={stdout_log}
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
                f'TRADING_SYSTEM_HOST="{system_host}"',
                f'REC_SYSTEM_HOST="{system_host}"',
                f'REC_PROJECT_ROOT="{self.config.project_root}"',
                f'REC_ENVIRONMENT="{self.config.get("system.environment", "development")}"',
                f'DB_HOST="{db_config.get("host", "localhost")}"',
                f'DB_NAME="{db_config.get("name", "rec_io_db")}"',
                f'DB_USER="{db_config.get("user", "rec_io_user")}"',
                f'DB_PASSWORD="{db_config.get("password", "rec_io_password")}"',
                f'DB_PORT="{db_config.get("port", 5432)}"',
                f'POSTGRES_HOST="{db_config.get("host", "localhost")}"',
                f'POSTGRES_DB="{db_config.get("name", "rec_io_db")}"',
                f'POSTGRES_USER="{db_config.get("user", "rec_io_user")}"',
                f'POSTGRES_PASSWORD="{db_config.get("password", "rec_io_password")}"',
                f'POSTGRES_PORT="{db_config.get("port", 5432)}"',
                f'REC_DB_HOST="{db_config.get("host", "localhost")}"',
                f'REC_DB_NAME="{db_config.get("name", "rec_io_db")}"',
                f'REC_DB_USER="{db_config.get("user", "rec_io_user")}"',
                f'REC_DB_PASS="{db_config.get("password", "rec_io_password")}"',
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
