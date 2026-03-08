#!/usr/bin/env python3
"""
REC.IO System Migration Tool
Creates complete system migration packages for moving to new machines.
"""

import os
import sys
import json
import tarfile
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import argparse

def get_project_root():
    """Get the project root directory."""
    current_dir = Path.cwd()
    while current_dir != current_dir.parent:
        if (current_dir / "backend" / "main.py").exists():
            return str(current_dir)
        current_dir = current_dir.parent
    raise FileNotFoundError("Could not find project root")

class SystemMigrationTool:
    def __init__(self):
        self.project_root = Path(get_project_root())
        self.migration_dir = self.project_root / "backup" / "system_migrations"
        self.migration_dir.mkdir(parents=True, exist_ok=True)
        
        # Import database backup tool
        sys.path.append(str(self.project_root / "scripts"))
        from database_backup_tool import DatabaseBackupTool
        self.db_backup_tool = DatabaseBackupTool()
    
    def get_system_info(self):
        """Collect system information."""
        info = {
            'os': os.uname().sysname if hasattr(os, 'uname') else 'Unknown',
            'python_version': sys.version,
            'project_root': str(self.project_root),
            'created_at': datetime.now().isoformat()
        }
        
        # Get PostgreSQL version
        try:
            result = subprocess.run(['psql', '--version'], 
                                  capture_output=True, text=True)
            info['postgresql_version'] = result.stdout.strip()
        except:
            info['postgresql_version'] = 'Unknown'
        
        # Get database info
        db_info = self.db_backup_tool.get_database_info()
        if db_info:
            info['database_size'] = db_info['size']
            info['database_tables'] = len(db_info['tables'])
        
        return info
    
    def get_file_inventory(self):
        """Create inventory of important project files."""
        important_files = []
        exclude_paths = {
            'venv/', '.git/', 'logs/', 'backup/', '__pycache__/',
            '.DS_Store', '*.pyc', '*.log', '*.tmp'
        }
        
        for root, dirs, files in os.walk(self.project_root):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if not any(exclude in d for exclude in exclude_paths)]
            
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.project_root)
                
                # Skip excluded files
                if any(exclude in str(rel_path) for exclude in exclude_paths):
                    continue
                
                important_files.append({
                    'path': str(rel_path),
                    'size': file_path.stat().st_size,
                    'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                })
        
        return important_files
    
    def create_database_backup(self):
        """Create a database backup for the migration package."""
        print("📦 Creating database backup for migration...")
        return self.db_backup_tool.create_backup()
    
    def create_system_package(self):
        """Create a complete system migration package."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        package_name = f"rec_io_system_migration_{timestamp}"
        package_path = self.migration_dir / f"{package_name}.tar.gz"
        
        print(f"🚀 Creating system migration package: {package_name}")
        
        # Collect system information
        print("📊 Collecting system information...")
        system_info = self.get_system_info()
        
        # Create file inventory
        print("📋 Creating file inventory...")
        file_inventory = self.get_file_inventory()
        
        # Create database backup
        if not self.create_database_backup():
            print("❌ Failed to create database backup")
            return False
        
        # Find the latest database backup
        backup_files = list(self.db_backup_tool.backup_dir.glob("*.tar.gz"))
        if not backup_files:
            print("❌ No database backup found")
            return False
        
        latest_backup = max(backup_files, key=lambda f: f.stat().st_mtime)
        
        # Create migration package
        print("📦 Creating migration package...")
        with tarfile.open(package_path, 'w:gz') as tar:
            # Add system information
            info_path = self.migration_dir / f"{package_name}_system_info.json"
            with open(info_path, 'w') as f:
                json.dump(system_info, f, indent=2)
            tar.add(info_path, arcname=f"{package_name}_system_info.json")
            
            # Add file inventory
            inventory_path = self.migration_dir / f"{package_name}_file_inventory.json"
            with open(inventory_path, 'w') as f:
                json.dump(file_inventory, f, indent=2)
            tar.add(inventory_path, arcname=f"{package_name}_file_inventory.json")
            
            # Add database backup
            tar.add(latest_backup, arcname=f"database_backup.tar.gz")
            
            # Add project files
            print("📁 Adding project files...")
            for file_info in file_inventory:
                file_path = self.project_root / file_info['path']
                if file_path.exists():
                    tar.add(file_path, arcname=f"project_files/{file_info['path']}")
            
            # Generate installation script
            install_script = self._generate_install_script(package_name)
            install_path = self.migration_dir / "install_on_new_machine.sh"
            with open(install_path, 'w') as f:
                f.write(install_script)
            os.chmod(install_path, 0o755)
            tar.add(install_path, arcname="install_on_new_machine.sh")
            
            # Generate README
            readme_content = self._generate_migration_readme(package_name, system_info)
            readme_path = self.migration_dir / "README_MIGRATION.md"
            with open(readme_path, 'w') as f:
                f.write(readme_content)
            tar.add(readme_path, arcname="README_MIGRATION.md")
        
        # Clean up temporary files
        info_path.unlink()
        inventory_path.unlink()
        install_path.unlink()
        readme_path.unlink()
        
        # Calculate package size
        package_size = package_path.stat().st_size
        package_size_mb = round(package_size / (1024 * 1024), 2)
        
        print(f"✅ Migration package created: {package_path}")
        print(f"📊 Package size: {package_size_mb} MB")
        print(f"📋 Files included: {len(file_inventory)}")
        print(f"🗄️  Database backup: {latest_backup.name}")
        
        return True
    
    def _generate_install_script(self, package_name):
        """Generate the installation script for new machines."""
        script = f"""#!/bin/bash

# REC.IO System Migration Installation Script
# Generated: {datetime.now().isoformat()}
# Package: {package_name}

set -e

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
BLUE='\\033[0;34m'
NC='\\033[0m'

print_status() {{
    echo -e "${{BLUE}}[INFO]${{NC}} $1"
}}

print_success() {{
    echo -e "${{GREEN}}[SUCCESS]${{NC}} $1"
}}

print_warning() {{
    echo -e "${{YELLOW}}[WARNING]${{NC}} $1"
}}

print_error() {{
    echo -e "${{RED}}[ERROR]${{NC}} $1"
}}

# Check if we're in the correct directory
if [ ! -f "backend/main.py" ] || [ ! -f "frontend/index.html" ]; then
    print_error "Please run this script from within the REC.IO repository"
    print_error "Make sure you have cloned the git repository first:"
    print_error "  git clone <your-repo-url>"
    print_error "  cd rec_io_20"
    exit 1
fi

# Check if .git directory exists (we're in a git repo)
if [ ! -d ".git" ]; then
    print_error "This script must be run from within a git repository"
    print_error "Please clone the REC.IO repository first"
    exit 1
fi

print_status "Starting REC.IO system migration installation..."

# Check system requirements
print_status "Checking system requirements..."

# Check Python
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is required but not installed"
    exit 1
fi

# Check PostgreSQL
if ! command -v psql &> /dev/null; then
    print_error "PostgreSQL is required but not installed"
    print_error "Please install PostgreSQL first"
    exit 1
fi

# Extract database backup
print_status "Extracting database backup..."
tar -xzf database_backup.tar.gz

# Find the SQL dump file
SQL_DUMP=$(find . -name "*.sql" | head -1)
if [ -z "$SQL_DUMP" ]; then
    print_error "No SQL dump file found in backup"
    exit 1
fi

print_status "Found SQL dump: $SQL_DUMP"

# Restore database
print_status "Restoring database..."

# Drop and recreate database
psql -h localhost -U rec_io_user -d postgres -c "DROP DATABASE IF EXISTS rec_io_db;"
psql -h localhost -U rec_io_user -d postgres -c "CREATE DATABASE rec_io_db;"

# Restore from SQL dump
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -f "$SQL_DUMP"

print_success "Database restored successfully!"

# Install Python dependencies
print_status "Installing Python dependencies..."
pip install -r requirements.txt

# Set up supervisor
print_status "Setting up supervisor..."
if command -v supervisorctl &> /dev/null; then
    print_status "Supervisor already installed"
else
    print_warning "Supervisor not found - you may need to install it manually"
fi

print_success "Migration installation completed!"
print_status "You can now start the system with: ./scripts/MASTER_RESTART.sh"
"""
        return script
    
    def _generate_migration_readme(self, package_name, system_info):
        """Generate README for the migration package."""
        readme = f"""# REC.IO System Migration Package

**Package:** {package_name}
**Created:** {system_info['created_at']}
**Source System:** {system_info['os']}

## What's Included

This migration package contains:

- ✅ **Complete database backup** with all user data and trading history
- ✅ **All project files** and source code
- ✅ **System configuration** and settings
- ✅ **Installation script** for automatic setup
- ✅ **System information** and metadata

## Installation Instructions

### Prerequisites

1. **Clone the git repository** on your new machine:
   ```bash
   git clone <your-repo-url>
   cd rec_io_20
   ```

2. **Download this migration package** and extract it:
   ```bash
   tar -xzf {package_name}.tar.gz
   cd {package_name}
   ```

3. **Run the installation script**:
   ```bash
   ./install_on_new_machine.sh
   ```

### What the Installation Does

1. **Validates system requirements** (Python, PostgreSQL)
2. **Restores the complete database** with all your data
3. **Installs Python dependencies**
4. **Sets up supervisor** for service management
5. **Configures the system** for immediate use

### After Installation

1. **Start the system**:
   ```bash
   ./scripts/MASTER_RESTART.sh
   ```

2. **Access the web interface**:
   - Main app: http://localhost:3000
   - Health check: http://localhost:3000/health

3. **Verify your data**:
   - Check that all your trading history is present
   - Verify your user settings and preferences
   - Test the system functionality

## System Information

- **OS:** {system_info['os']}
- **Python:** {system_info['python_version'].split()[0]}
- **PostgreSQL:** {system_info.get('postgresql_version', 'Unknown')}
- **Database Size:** {system_info.get('database_size', 'Unknown')}
- **Tables:** {system_info.get('database_tables', 'Unknown')}

## Troubleshooting

If the installation fails:

1. **Check system requirements**:
   - Python 3.8+ installed
   - PostgreSQL running and accessible
   - Git repository cloned correctly

2. **Verify database connection**:
   ```bash
   psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT 1;"
   ```

3. **Check logs**:
   ```bash
   tail -f logs/*.out.log
   ```

## Security Notes

- This package contains sensitive data
- Store securely and delete after successful migration
- Change passwords after migration if needed

---

**For support:** See the main project documentation
"""
        return readme

def main():
    parser = argparse.ArgumentParser(description="REC.IO System Migration Tool")
    parser.add_argument('action', choices=['create'],
                       help='Action to perform')
    
    args = parser.parse_args()
    
    tool = SystemMigrationTool()
    
    if args.action == 'create':
        success = tool.create_system_package()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
