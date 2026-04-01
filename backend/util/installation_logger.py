#!/usr/bin/env python3
"""
Installation Access Logger

This module provides logging functionality for tracking installation access
to the remote database during system data cloning.
"""

import os
import sys
import time
import socket
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import psycopg2
from psycopg2.extras import RealDictCursor

# Add the backend directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.config.config_manager import ConfigManager
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

class InstallationLogger:
    """Handles logging of installation access for system data cloning."""
    
    def __init__(self):
        self.config = ConfigManager()
        # Use the database configuration from environment variables
        self.db_config = merge_psycopg2_connect_kwargs(
            {
                "host": os.getenv("DB_HOST", "localhost"),
                "database": os.getenv("DB_NAME", "rec_io_db"),
                "user": os.getenv("DB_USER", "rec_io_user"),
                "password": os.getenv("DB_PASSWORD", "rec_io_password"),
                "port": int(os.getenv("DB_PORT", "5432")),
            }
        )
        self.log_entry_id = None
        self.connection_start_time = None
        
    def get_installer_info(self) -> Dict[str, Any]:
        """Get installer information from environment or user input."""
        return {
            'user_id': os.getenv('INSTALLER_USER_ID', 'unknown'),
            'name': os.getenv('INSTALLER_NAME', 'Unknown Installer'),
            'email': os.getenv('INSTALLER_EMAIL', 'unknown@example.com'),
            'ip_address': self._get_client_ip(),
            'user_agent': os.getenv('INSTALLER_USER_AGENT', 'REC.IO Installation Package'),
            'package_version': os.getenv('INSTALLATION_PACKAGE_VERSION', '1.0.0')
        }
    
    def _get_client_ip(self) -> str:
        """Get the client IP address."""
        try:
            # Try to get external IP
            import requests
            response = requests.get('https://api.ipify.org', timeout=5)
            return response.text
        except:
            try:
                # Fallback to local IP
                hostname = socket.gethostname()
                return socket.gethostbyname(hostname)
            except:
                return 'unknown'
    
    def start_logging(self, schemas_to_access: List[str]) -> bool:
        """Start logging an installation access session."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            installer_info = self.get_installer_info()
            
            # Insert log entry
            cursor.execute("""
                INSERT INTO system.installation_access_log (
                    installer_user_id, installer_name, installer_email, 
                    installer_ip_address, schemas_accessed, status
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                installer_info['user_id'],
                installer_info['name'],
                installer_info['email'],
                installer_info['ip_address'],
                schemas_to_access,
                'in_progress'
            ))
            
            self.log_entry_id = cursor.fetchone()[0]
            self.connection_start_time = time.time()
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"📝 Installation access logged (ID: {self.log_entry_id})")
            return True
            
        except Exception as e:
            print(f"❌ Failed to start installation logging: {e}")
            return False
    
    def update_progress(self, tables_cloned: int, rows_cloned: int) -> bool:
        """Update progress during cloning."""
        if not self.log_entry_id:
            return False
            
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE system.installation_access_log 
                SET tables_cloned = %s, total_rows_cloned = %s
                WHERE id = %s
            """, (tables_cloned, rows_cloned, self.log_entry_id))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return True
            
        except Exception as e:
            print(f"⚠️  Failed to update progress: {e}")
            return False
    
    def complete_logging(self, success: bool = True, error_message: Optional[str] = None) -> bool:
        """Complete the installation logging session."""
        if not self.log_entry_id:
            return False
            
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            duration_seconds = int(time.time() - self.connection_start_time) if self.connection_start_time else 0
            status = 'completed' if success else 'failed'
            
            cursor.execute("""
                UPDATE system.installation_access_log 
                SET connection_end = NOW(),
                    clone_duration_seconds = %s,
                    status = %s,
                    error_message = %s
                WHERE id = %s
            """, (duration_seconds, status, error_message, self.log_entry_id))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"📝 Installation access logging completed (ID: {self.log_entry_id})")
            return True
            
        except Exception as e:
            print(f"❌ Failed to complete installation logging: {e}")
            return False
    
    def log_error(self, error_message: str) -> bool:
        """Log an error during installation."""
        return self.complete_logging(success=False, error_message=error_message)
    
    def get_recent_installations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent installation access logs."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute("""
                SELECT * FROM system.installation_access_log 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))
            
            results = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            return [dict(row) for row in results]
            
        except Exception as e:
            print(f"❌ Failed to get recent installations: {e}")
            return []
    
    def get_installation_stats(self) -> Dict[str, Any]:
        """Get installation statistics."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Total installations
            cursor.execute("SELECT COUNT(*) FROM system.installation_access_log")
            total_installations = cursor.fetchone()[0]
            
            # Successful installations
            cursor.execute("SELECT COUNT(*) FROM system.installation_access_log WHERE status = 'completed'")
            successful_installations = cursor.fetchone()[0]
            
            # Failed installations
            cursor.execute("SELECT COUNT(*) FROM system.installation_access_log WHERE status = 'failed'")
            failed_installations = cursor.fetchone()[0]
            
            # Recent activity (last 30 days)
            cursor.execute("""
                SELECT COUNT(*) FROM system.installation_access_log 
                WHERE created_at >= NOW() - INTERVAL '30 days'
            """)
            recent_activity = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return {
                'total_installations': total_installations,
                'successful_installations': successful_installations,
                'failed_installations': failed_installations,
                'success_rate': (successful_installations / total_installations * 100) if total_installations > 0 else 0,
                'recent_activity_30_days': recent_activity
            }
            
        except Exception as e:
            print(f"❌ Failed to get installation stats: {e}")
            return {}

def log_installation_access(func):
    """Decorator to automatically log installation access."""
    def wrapper(*args, **kwargs):
        logger = InstallationLogger()
        
        # Start logging
        schemas_to_access = ['analytics', 'historical_data', 'live_data']
        logger.start_logging(schemas_to_access)
        
        try:
            # Execute the function
            result = func(*args, **kwargs)
            
            # Log success
            logger.complete_logging(success=True)
            
            return result
            
        except Exception as e:
            # Log error
            logger.log_error(str(e))
            raise e
    
    return wrapper

# Example usage
if __name__ == "__main__":
    logger = InstallationLogger()
    
    # Test logging
    print("Testing installation logging...")
    
    # Set test environment variables
    os.environ['INSTALLER_USER_ID'] = 'test_user_001'
    os.environ['INSTALLER_NAME'] = 'Test Installer'
    os.environ['INSTALLER_EMAIL'] = 'test@example.com'
    
    # Start logging
    success = logger.start_logging(['analytics', 'historical_data', 'live_data'])
    print(f"Logging started: {success}")
    
    # Simulate progress
    logger.update_progress(10, 1000)
    
    # Complete logging
    logger.complete_logging(success=True)
    
    # Show stats
    stats = logger.get_installation_stats()
    print(f"Installation stats: {stats}")
