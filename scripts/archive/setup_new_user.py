#!/usr/bin/env python3
"""
User Setup Script for REC.IO Trading System
Creates personalized user configuration including user_info.json and Kalshi credentials.
"""

import os
import sys
import json
import getpass
from pathlib import Path
from typing import Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.util.paths import get_data_dir, get_kalshi_credentials_dir, ensure_data_dirs

def print_banner():
    """Print setup banner."""
    print("=" * 60)
    print("           REC.IO TRADING SYSTEM USER SETUP")
    print("=" * 60)
    print("This script will configure a new user for the trading system.")
    print("You'll need your Kalshi API credentials ready.")
    print("=" * 60)

def get_user_input(prompt: str, required: bool = True, password: bool = False) -> str:
    """Get user input with validation."""
    while True:
        if password:
            value = getpass.getpass(prompt)
        else:
            value = input(prompt)
        
        if not value.strip() and required:
            print("❌ This field is required. Please try again.")
            continue
        return value.strip()

def validate_email(email: str) -> bool:
    """Basic email validation."""
    return '@' in email and '.' in email

def validate_phone(phone: str) -> bool:
    """Basic phone validation."""
    # Remove common separators
    clean_phone = ''.join(c for c in phone if c.isdigit())
    return len(clean_phone) >= 10

def get_user_info() -> Dict[str, Any]:
    """Collect user identity information."""
    print("\n📋 USER IDENTITY INFORMATION")
    print("-" * 40)
    
    user_id = get_user_input("Enter your user ID (e.g., 'ewais'): ")
    
    name = get_user_input("Enter your full name: ")
    
    while True:
        email = get_user_input("Enter your email address: ")
        if validate_email(email):
            break
        print("❌ Please enter a valid email address.")
    
    while True:
        phone = get_user_input("Enter your phone number: ")
        if validate_phone(phone):
            break
        print("❌ Please enter a valid phone number.")
    
    print("\nAccount Type Options:")
    print("1. user - Standard trading user")
    print("2. admin - Administrative access")
    print("3. master_admin - Full system control")
    
    while True:
        account_type = get_user_input("Select account type (1/2/3): ").lower()
        if account_type in ['1', 'user']:
            account_type = 'user'
            break
        elif account_type in ['2', 'admin']:
            account_type = 'admin'
            break
        elif account_type in ['3', 'master_admin']:
            account_type = 'master_admin'
            break
        else:
            print("❌ Please select 1, 2, or 3.")
    
    return {
        "user_id": user_id,
        "name": name,
        "email": email,
        "phone": phone,
        "account_type": account_type
    }

def get_kalshi_credentials() -> Dict[str, str]:
    """Collect Kalshi API credentials."""
    print("\n🔑 KALSHI API CREDENTIALS")
    print("-" * 40)
    print("You'll need your Kalshi API credentials.")
    print("Get them from: https://trading.kalshi.com/settings/api")
    print()
    
    email = get_user_input("Enter your Kalshi account email: ")
    
    api_key = get_user_input("Enter your Kalshi API Key ID: ")
    
    private_key = get_user_input("Enter your Kalshi Private Key (PEM format): ", password=True)
    
    return {
        "email": email,
        "api_key": api_key,
        "private_key": private_key
    }

def create_user_directory(user_id: str) -> Path:
    """Create user directory structure."""
    user_dir = Path(get_data_dir()) / "users" / f"user_{user_id}"
    
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

def write_user_info(user_dir: Path, user_info: Dict[str, Any]) -> None:
    """Write user_info.json file."""
    user_info_file = user_dir / "user_info.json"
    
    with open(user_info_file, 'w') as f:
        json.dump(user_info, f, indent=2)
    
    print(f"✅ Created: {user_info_file}")

def write_kalshi_credentials(user_dir: Path, credentials: Dict[str, str], environment: str) -> None:
    """Write Kalshi credential files."""
    cred_dir = user_dir / "credentials" / "kalshi-credentials" / environment
    cred_dir.mkdir(parents=True, exist_ok=True)
    
    # Write kalshi-auth.txt
    auth_file = cred_dir / "kalshi-auth.txt"
    auth_content = f"email:{credentials['email']}\nkey:{credentials['api_key']}\n"
    with open(auth_file, 'w') as f:
        f.write(auth_content)
    print(f"✅ Created: {auth_file}")
    
    # Write kalshi-auth.pem
    pem_file = cred_dir / "kalshi-auth.pem"
    with open(pem_file, 'w') as f:
        f.write(credentials['private_key'])
    os.chmod(pem_file, 0o600)  # Secure permissions
    print(f"✅ Created: {pem_file}")
    
    # Write .env file
    env_file = cred_dir / ".env"
    env_content = f"""KALSHI_API_KEY_ID={credentials['api_key']}
KALSHI_PRIVATE_KEY_PATH=kalshi-auth.pem
KALSHI_EMAIL={credentials['email']}
"""
    with open(env_file, 'w') as f:
        f.write(env_content)
    print(f"✅ Created: {env_file}")

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
    
    # Auto stop settings
    auto_stop_settings = {
        "enabled": False,
        "threshold": -50,
        "action": "close_all"
    }
    
    auto_stop_file = preferences_dir / "auto_stop_settings.json"
    with open(auto_stop_file, 'w') as f:
        json.dump(auto_stop_settings, f, indent=2)
    print(f"✅ Created: {auto_stop_file}")
    
    # Auto entry settings
    auto_entry_settings = {
        "enabled": False,
        "strategy": "momentum",
        "conditions": []
    }
    
    auto_entry_file = preferences_dir / "auto_entry_settings.json"
    with open(auto_entry_file, 'w') as f:
        json.dump(auto_entry_settings, f, indent=2)
    print(f"✅ Created: {auto_entry_file}")

def update_paths_for_user(user_id: str) -> None:
    """Update paths.py to use the new user ID."""
    paths_file = Path("backend/util/paths.py")
    
    if not paths_file.exists():
        print("⚠️  Warning: paths.py not found. User paths may need manual configuration.")
        return
    
    # Read current paths.py
    with open(paths_file, 'r') as f:
        content = f.read()
    
    # Replace user_0001 with the new user_id
    updated_content = content.replace("user_0001", f"user_{user_id}")
    
    # Write updated paths.py
    with open(paths_file, 'w') as f:
        f.write(updated_content)
    
    print(f"✅ Updated paths.py to use user_{user_id}")

def create_account_mode_file(user_dir: Path) -> None:
    """Create initial account mode file."""
    account_mode_file = user_dir / "account_mode_state.json"
    account_mode_data = {"mode": "demo"}  # Start in demo mode for safety
    
    with open(account_mode_file, 'w') as f:
        json.dump(account_mode_data, f, indent=2)
    
    print(f"✅ Created: {account_mode_file}")
    print("⚠️  Account mode set to 'demo' for safety. Change to 'prod' when ready.")

def main():
    """Main setup function."""
    print_banner()
    
    # Ensure data directories exist
    ensure_data_dirs()
    
    # Get user information
    user_info = get_user_info()
    
    # Get Kalshi credentials
    credentials = get_kalshi_credentials()
    
    # Create user directory
    user_dir = create_user_directory(user_info['user_id'])
    
    print(f"\n📁 Creating user directory: {user_dir}")
    
    # Write user files
    write_user_info(user_dir, user_info)
    write_kalshi_credentials(user_dir, credentials, "prod")
    write_kalshi_credentials(user_dir, credentials, "demo")
    create_default_preferences(user_dir)
    create_account_mode_file(user_dir)
    
    # Update system paths
    update_paths_for_user(user_info['user_id'])
    
    print("\n" + "=" * 60)
    print("✅ USER SETUP COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print(f"👤 User ID: {user_info['user_id']}")
    print(f"📧 Email: {user_info['email']}")
    print(f"🔑 Account Type: {user_info['account_type']}")
    print(f"📁 User Directory: {user_dir}")
    print()
    print("🔒 SECURITY NOTES:")
    print("- Credentials are stored securely with restricted permissions")
    print("- Account mode is set to 'demo' for safety")
    print("- Change to 'prod' mode when ready for live trading")
    print()
    print("🚀 NEXT STEPS:")
    print("1. Review the created files")
    print("2. Test the system with demo mode")
    print("3. Switch to prod mode when ready")
    print("4. Run: ./scripts/MASTER_RESTART.sh")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Setup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        sys.exit(1) 