#!/usr/bin/env python3
"""
REC.IO Trading System - Complete Installation Script
===================================================

This script provides a complete, portable installation for the REC.IO trading system.
It handles all aspects of deployment including:
- Environment setup and validation
- User configuration (new user or import existing)
- Authentication system setup
- System startup and verification
- Frontend launch

Usage:
    python scripts/INSTALL_SYSTEM.py [--import-user /path/to/user_data]
"""

import os
import sys
import json
import shutil
import subprocess
import platform
import argparse
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def print_banner():
    """Print installation banner."""
    print("=" * 70)
    print("           REC.IO TRADING SYSTEM - COMPLETE INSTALLATION")
    print("=" * 70)
    print("This script will install and configure the REC.IO trading system")
    print("on this machine, handling all setup and configuration automatically.")
    print("=" * 70)

def check_system_requirements():
    """Check if the system meets requirements."""
    print("\n🔍 Checking system requirements...")
    
    # Check Python version
    python_version = sys.version_info
    if python_version < (3, 11):
        print(f"❌ Python {python_version.major}.{python_version.minor} detected")
        print("   Python 3.11+ is required")
        return False
    print(f"✅ Python {python_version.major}.{python_version.minor}.{python_version.micro}")
    
    # Check if we're in the right directory
    project_root = Path(__file__).parent.parent
    if not (project_root / "backend").exists():
        print("❌ Not in REC.IO project directory")
        print("   Please run this script from the project root")
        return False
    print("✅ Project structure verified")
    
    # Check for requirements.txt
    if not (project_root / "requirements.txt").exists():
        print("❌ requirements.txt not found")
        return False
    print("✅ Dependencies file found")
    
    return True

def setup_virtual_environment():
    """Set up Python virtual environment."""
    print("\n🐍 Setting up Python virtual environment...")
    
    project_root = Path(__file__).parent.parent
    venv_path = project_root / "venv"
    
    if venv_path.exists():
        print("✅ Virtual environment already exists")
        return True
    
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
        print("✅ Virtual environment created")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to create virtual environment: {e}")
        return False

def install_dependencies():
    """Install Python dependencies."""
    print("\n📦 Installing dependencies...")
    
    project_root = Path(__file__).parent.parent
    venv_python = project_root / "venv" / "bin" / "python"
    
    if platform.system() == "Windows":
        venv_python = project_root / "venv" / "Scripts" / "python.exe"
    
    try:
        subprocess.run([str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"], check=True)
        print("✅ Dependencies installed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def ensure_data_directories():
    """Ensure all necessary data directories exist."""
    print("\n📁 Creating data directories...")
    
    try:
        from backend.util.paths import ensure_data_dirs
        ensure_data_dirs()
        print("✅ Data directories created")
        return True
    except Exception as e:
        print(f"❌ Failed to create data directories: {e}")
        return False

def setup_postgresql_database():
    """Set up PostgreSQL database and tables."""
    print("\n🗄️ Setting up PostgreSQL database...")
    
    try:
        # Check if PostgreSQL is installed and running
        result = subprocess.run(["psql", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ PostgreSQL not found. Please install PostgreSQL first:")
            print("   macOS: brew install postgresql")
            print("   Ubuntu: sudo apt-get install postgresql postgresql-contrib")
            print("   Windows: Download from https://www.postgresql.org/download/windows/")
            return False
        
        print("✅ PostgreSQL found")
        
        # Check if database exists
        result = subprocess.run([
            "psql", "-h", "localhost", "-U", "rec_io_user", "-d", "rec_io_db", 
            "-c", "SELECT 1;"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print("📋 Creating database and user...")
            
            # Create database and user
            subprocess.run([
                "sudo", "-u", "postgres", "psql", "-c", 
                "CREATE DATABASE rec_io_db;"
            ], check=True)
            
            subprocess.run([
                "sudo", "-u", "postgres", "psql", "-c", 
                "CREATE USER rec_io_user WITH PASSWORD '';"
            ], check=True)
            
            subprocess.run([
                "sudo", "-u", "postgres", "psql", "-c", 
                "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;"
            ], check=True)
            
            subprocess.run([
                "sudo", "-u", "postgres", "psql", "-c", 
                "CREATE SCHEMA IF NOT EXISTS users;"
            ], check=True)
            
            subprocess.run([
                "sudo", "-u", "postgres", "psql", "-c", 
                "GRANT ALL ON SCHEMA users TO rec_io_user;"
            ], check=True)
            
            print("✅ Database and user created")
        else:
            print("✅ Database already exists")
        
        # Set up table structure
        print("📋 Creating table structure...")
        project_root = Path(__file__).parent.parent
        schema_file = project_root / "scripts" / "create_user_0001_tables.sql"
        
        if not schema_file.exists():
            print(f"❌ Schema file not found: {schema_file}")
            return False
        
        subprocess.run([
            "psql", "-h", "localhost", "-U", "rec_io_user", "-d", "rec_io_db", 
            "-f", str(schema_file)
        ], check=True)
        
        print("✅ PostgreSQL database setup completed")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to set up PostgreSQL: {e}")
        print("   Please ensure PostgreSQL is installed and running")
        return False
    except Exception as e:
        print(f"❌ Failed to set up PostgreSQL: {e}")
        return False

def setup_new_user():
    """Set up a new user for the system."""
    print("\n👤 Setting up new user...")
    
    try:
        # Run the user setup script
        project_root = Path(__file__).parent.parent
        venv_python = project_root / "venv" / "bin" / "python"
        
        if platform.system() == "Windows":
            venv_python = project_root / "venv" / "Scripts" / "python.exe"
        
        subprocess.run([str(venv_python), "scripts/setup_new_user.py"], check=True)
        print("✅ New user setup completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to set up new user: {e}")
        return False

def import_existing_user(user_data_path: str):
    """Import existing user data."""
    print(f"\n📥 Importing existing user data from: {user_data_path}")
    
    try:
        user_data_path = Path(user_data_path)
        if not user_data_path.exists():
            print(f"❌ User data path does not exist: {user_data_path}")
            return False
        
        # Copy user data to the system
        from backend.util.paths import get_data_dir
        target_user_dir = Path(get_data_dir()) / "users" / "user_0001"
        
        if target_user_dir.exists():
            shutil.rmtree(target_user_dir)
        
        shutil.copytree(user_data_path, target_user_dir)
        print("✅ User data imported successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to import user data: {e}")
        return False

def setup_authentication():
    """Set up the authentication system."""
    print("\n🔐 Setting up authentication system...")
    
    try:
        project_root = Path(__file__).parent.parent
        venv_python = project_root / "venv" / "bin" / "python"
        
        if platform.system() == "Windows":
            venv_python = project_root / "venv" / "Scripts" / "python.exe"
        
        subprocess.run([str(venv_python), "scripts/setup_auth.py"], check=True)
        print("✅ Authentication system setup completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to set up authentication: {e}")
        return False

def test_authentication():
    """Test the authentication system."""
    print("\n🧪 Testing authentication system...")
    
    try:
        project_root = Path(__file__).parent.parent
        venv_python = project_root / "venv" / "bin" / "python"
        
        if platform.system() == "Windows":
            venv_python = project_root / "venv" / "Scripts" / "python.exe"
        
        subprocess.run([str(venv_python), "scripts/test_auth.py"], check=True)
        print("✅ Authentication system test completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Authentication test failed: {e}")
        return False

def start_system():
    """Start the trading system."""
    print("\n🚀 Starting trading system...")
    
    try:
        # Use the MASTER_RESTART script to start the system
        project_root = Path(__file__).parent.parent
        restart_script = project_root / "scripts" / "MASTER_RESTART.sh"
        
        if platform.system() == "Windows":
            # On Windows, we need to run the commands differently
            print("⚠️  Windows detected - manual startup may be required")
            print("   Please run: ./scripts/MASTER_RESTART.sh")
            return True
        else:
            subprocess.run(["bash", str(restart_script)], check=True)
            print("✅ System started successfully")
            return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start system: {e}")
        return False

def verify_system():
    """Verify that the system is running correctly."""
    print("\n🔍 Verifying system status...")
    
    try:
        import requests
        import time
        
        # Wait a moment for services to start
        time.sleep(5)
        
        # Test main app
        response = requests.get("http://localhost:3000/health", timeout=5)
        if response.status_code == 200:
            print("✅ Main application is running")
        else:
            print("❌ Main application is not responding")
            return False
        
        # Test login page
        response = requests.get("http://localhost:3000/login", timeout=5)
        if response.status_code == 200:
            print("✅ Login page is accessible")
        else:
            print("❌ Login page is not accessible")
            return False
        
        print("✅ System verification completed")
        return True
    except Exception as e:
        print(f"❌ System verification failed: {e}")
        return False

def launch_frontend():
    """Launch the frontend in the default browser."""
    print("\n🌐 Launching frontend...")
    
    try:
        import webbrowser
        webbrowser.open("http://localhost:3000")
        print("✅ Frontend launched in browser")
        return True
    except Exception as e:
        print(f"❌ Failed to launch frontend: {e}")
        print("   Please manually open: http://localhost:3000")
        return False

def print_completion_message():
    """Print completion message with next steps."""
    print("\n" + "=" * 70)
    print("🎉 REC.IO TRADING SYSTEM INSTALLATION COMPLETED!")
    print("=" * 70)
    print("\n📋 System Information:")
    print("   • Main Application: http://localhost:3000")
    print("   • Login Page: http://localhost:3000/login")
    print("   • Health Check: http://localhost:3000/health")
    print("   • PostgreSQL Database: rec_io_db (localhost:5432)")
    print("\n🔧 Management Commands:")
    print("   • Restart System: ./scripts/MASTER_RESTART.sh")
    print("   • Check Status: supervisorctl -c backend/supervisord.conf status")
    print("   • View Logs: tail -f logs/*.out.log")
    print("   • Database Access: psql -h localhost -U rec_io_user -d rec_io_db")
    print("\n📚 Documentation:")
    print("   • Deployment Guide: docs/DEPLOYMENT_GUIDE.md")
    print("   • Authentication Guide: docs/AUTHENTICATION_GUIDE.md")
    print("\n⚠️  Important Notes:")
    print("   • System starts in demo mode for safety")
    print("   • Change to production mode when ready")
    print("   • Default authentication is enabled")
    print("   • Use 'Local Development Bypass' for testing")
    print("   • PostgreSQL database is ready for parallel writes")
    print("   • Legacy SQLite files are maintained for compatibility")
    print("=" * 70)

def main():
    """Main installation function."""
    parser = argparse.ArgumentParser(description="Install REC.IO Trading System")
    parser.add_argument("--import-user", help="Path to existing user data to import")
    args = parser.parse_args()
    
    print_banner()
    
    # Check system requirements
    if not check_system_requirements():
        print("\n❌ System requirements not met. Installation cannot continue.")
        sys.exit(1)
    
    # Set up virtual environment
    if not setup_virtual_environment():
        print("\n❌ Failed to set up virtual environment.")
        sys.exit(1)
    
    # Install dependencies
    if not install_dependencies():
        print("\n❌ Failed to install dependencies.")
        sys.exit(1)
    
    # Ensure data directories
    if not ensure_data_directories():
        print("\n❌ Failed to create data directories.")
        sys.exit(1)
    
    # Set up PostgreSQL database
    if not setup_postgresql_database():
        print("\n❌ Failed to set up PostgreSQL database.")
        sys.exit(1)
    
    # Handle user setup
    if args.import_user:
        if not import_existing_user(args.import_user):
            print("\n❌ Failed to import user data.")
            sys.exit(1)
    else:
        if not setup_new_user():
            print("\n❌ Failed to set up new user.")
            sys.exit(1)
    
    # Set up authentication
    if not setup_authentication():
        print("\n❌ Failed to set up authentication.")
        sys.exit(1)
    
    # Test authentication
    if not test_authentication():
        print("\n❌ Authentication test failed.")
        sys.exit(1)
    
    # Start system
    if not start_system():
        print("\n❌ Failed to start system.")
        sys.exit(1)
    
    # Verify system
    if not verify_system():
        print("\n❌ System verification failed.")
        sys.exit(1)
    
    # Launch frontend
    launch_frontend()
    
    # Print completion message
    print_completion_message()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Installation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Installation failed: {e}")
        sys.exit(1) 