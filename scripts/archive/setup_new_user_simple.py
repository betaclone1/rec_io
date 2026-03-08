#!/usr/bin/env python3
"""
Simple New User Setup Script for REC.IO Trading System
Creates a basic user profile for new users after deployment.
"""

import os
import sys
import json
import getpass
from pathlib import Path

def print_banner():
    """Print setup banner."""
    print("=" * 60)
    print("           REC.IO NEW USER SETUP")
    print("=" * 60)
    print("This script will set up a basic user profile for you.")
    print("You can add Kalshi credentials later if needed.")
    print("=" * 60)

def get_user_input(prompt: str, required: bool = True) -> str:
    """Get user input with validation."""
    while True:
        value = input(prompt).strip()
        if not value and required:
            print("❌ This field is required. Please try again.")
            continue
        return value

def create_user_directory() -> Path:
    """Create user directory structure."""
    # Get project root
    current_dir = Path.cwd()
    while current_dir != current_dir.parent:
        if (current_dir / "backend" / "main.py").exists():
            break
        current_dir = current_dir.parent
    
    user_dir = current_dir / "backend" / "data" / "users" / "user_0001"
    
    # Create directory structure
    directories = [
        user_dir,
        user_dir / "credentials" / "kalshi-credentials" / "prod",
        user_dir / "credentials" / "kalshi-credentials" / "demo",
        user_dir / "preferences",
        user_dir / "trade_history",
        user_dir / "active_trades",
        user_dir / "accounts"
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    
    return user_dir

def write_user_info(user_dir: Path, user_info: dict) -> None:
    """Write user_info.json file."""
    user_info_file = user_dir / "user_info.json"
    
    with open(user_info_file, 'w') as f:
        json.dump(user_info, f, indent=2)
    
    print(f"✅ Created: {user_info_file}")

def create_default_preferences(user_dir: Path) -> None:
    """Create default preference files."""
    preferences_dir = user_dir / "preferences"
    
    # Trade preferences
    trade_prefs = {
        "auto_stop_enabled": False,
        "auto_stop_threshold": -50,
        "position_size": 100,
        "max_positions": 5,
        "risk_tolerance": "medium"
    }
    
    trade_prefs_file = preferences_dir / "trade_preferences.json"
    with open(trade_prefs_file, 'w') as f:
        json.dump(trade_prefs, f, indent=2)
    print(f"✅ Created: {trade_prefs_file}")

def create_env_file() -> None:
    """Create basic .env file."""
    env_content = """# PostgreSQL Connection Settings
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=rec_io_password

# Trading System Configuration
TRADING_SYSTEM_HOST=localhost
REC_BIND_HOST=localhost
REC_TARGET_HOST=localhost
"""
    
    env_file = Path.cwd() / ".env"
    with open(env_file, 'w') as f:
        f.write(env_content)
    print(f"✅ Created: {env_file}")

def main():
    """Main setup function."""
    print_banner()
    
    print("\n📋 Basic User Information")
    print("-" * 40)
    
    # Get basic user info
    name = get_user_input("Enter your name: ")
    email = get_user_input("Enter your email: ")
    
    # Create user directory
    print("\n📁 Creating user directory structure...")
    user_dir = create_user_directory()
    
    # Write user info
    user_info = {
        "user_id": "user_0001",
        "name": name,
        "email": email,
        "account_type": "user",
        "created": str(Path.cwd())
    }
    
    write_user_info(user_dir, user_info)
    
    # Create default preferences
    print("\n⚙️  Creating default preferences...")
    create_default_preferences(user_dir)
    
    # Create .env file
    print("\n🔧 Creating environment configuration...")
    create_env_file()
    
    # Set permissions
    print("\n🔒 Setting file permissions...")
    os.chmod(user_dir / "credentials", 0o700)
    
    print("\n" + "=" * 60)
    print("✅ NEW USER SETUP COMPLETED!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Add Kalshi credentials (optional):")
    print("   - Create: backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt")
    print("   - Add your email and API key")
    print("2. Start the system:")
    print("   - Run: ./scripts/MASTER_RESTART.sh")
    print("3. Access the web interface:")
    print("   - Open: http://localhost:3000")
    print("\nFor help, see: docs/DEPLOYMENT_GUIDE.md")

if __name__ == "__main__":
    main()
