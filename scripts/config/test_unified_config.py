#!/usr/bin/env python3
"""
Test script for unified configuration system
"""

import sys
import os
import json
from pathlib import Path

# Get the directory where this script is located (scripts/config/ -> repo root is parent of parent)
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent

# Add project root to Python path
sys.path.insert(0, str(project_root))

# Change to project root directory
os.chdir(str(project_root))

try:
    from backend.core.unified_config import unified_config
    from backend.core.path_manager import PathManager
    from backend.core.host_detector import HostDetector
    
    # Get configuration
    config = unified_config.config
    path_manager = PathManager(unified_config)
    host_detector = HostDetector(unified_config.project_root)
    
    # Create configuration summary
    config_summary = {
        "project_root": unified_config.project_root,
        "system_host": unified_config.system_host,
        "venv_path": unified_config.venv_path,
        "python_executable": unified_config.get('runtime.python_executable'),
        "environment": unified_config.get('system.environment'),
        "database_host": unified_config.get('database.host'),
        "database_name": unified_config.get('database.name'),
        "database_user": unified_config.get('database.user'),
        "database_password": unified_config.get('database.password'),
        "database_port": unified_config.get('database.port'),
        "validation_passed": unified_config.validate_config()
    }
    
    # Output as JSON
    print(json.dumps(config_summary, indent=2))
    
except Exception as e:
    print(json.dumps({"error": str(e)}, indent=2))
    sys.exit(1)
