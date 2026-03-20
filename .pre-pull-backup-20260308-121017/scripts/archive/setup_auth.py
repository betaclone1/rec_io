#!/usr/bin/env python3
"""
Setup Authentication System

This script sets up the authentication system for the REC.IO trading platform.
It updates user_info.json with a password and creates the necessary authentication files.
"""

import os
import json
import secrets
import hashlib
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.util.paths import get_data_dir

def hash_password(password):
    """Hash a password using PBKDF2"""
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return salt + hash_obj.hex()

def setup_auth():
    """Set up the authentication system"""
    print("🔐 Setting up REC.IO Authentication System")
    print("=" * 50)
    
    # Get user info path
    user_info_path = os.path.join(get_data_dir(), "users", "user_0001", "user_info.json")
    
    if not os.path.exists(user_info_path):
        print(f"❌ User info file not found at {user_info_path}")
        print("Please run setup_new_user.py first to create user configuration.")
        return False
    
    # Load current user info
    try:
        with open(user_info_path, "r") as f:
            user_info = json.load(f)
    except Exception as e:
        print(f"❌ Error loading user info: {e}")
        return False
    
    print(f"👤 Current user: {user_info.get('name', 'Unknown')}")
    print(f"📧 Email: {user_info.get('email', 'Not set')}")
    
    # Get password from user
    while True:
        password = input("\n🔑 Enter a password for authentication (or press Enter for 'admin'): ").strip()
        if not password:
            password = "admin"
            print("Using default password: 'admin'")
            break
        
        if len(password) < 4:
            print("❌ Password must be at least 4 characters long")
            continue
        
        confirm_password = input("🔑 Confirm password: ").strip()
        if password == confirm_password:
            break
        else:
            print("❌ Passwords don't match")
    
    # Update user info with password
    user_info["password"] = password
    
    # Save updated user info
    try:
        with open(user_info_path, "w") as f:
            json.dump(user_info, f, indent=2)
        print(f"✅ Updated user info with password")
    except Exception as e:
        print(f"❌ Error saving user info: {e}")
        return False
    
    # Create authentication directories
    auth_dir = os.path.join(get_data_dir(), "users", "user_0001")
    os.makedirs(auth_dir, exist_ok=True)
    
    # Create empty auth files
    auth_tokens_file = os.path.join(auth_dir, "auth_tokens.json")
    device_tokens_file = os.path.join(auth_dir, "device_tokens.json")
    
    for file_path in [auth_tokens_file, device_tokens_file]:
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w") as f:
                    json.dump({}, f, indent=2)
                print(f"✅ Created {os.path.basename(file_path)}")
            except Exception as e:
                print(f"❌ Error creating {file_path}: {e}")
    
    print("\n🎉 Authentication system setup complete!")
    print("\n📋 Login Information:")
    print(f"   Username: {user_info.get('user_id', 'admin')}")
    print(f"   Password: {password}")
    print("\n🔧 To enable authentication in production:")
    print("   export AUTH_ENABLED=true")
    print("\n🔧 For local development (no auth required):")
    print("   export AUTH_ENABLED=false")
    
    return True

if __name__ == "__main__":
    setup_auth() 