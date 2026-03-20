#!/usr/bin/env python3
"""
Test Authentication System

This script tests the authentication system for the REC.IO trading platform.
"""

import requests
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.util.paths import get_data_dir

def test_auth():
    """Test the authentication system"""
    print("🧪 Testing REC.IO Authentication System")
    print("=" * 50)
    
    # Test server URL
    base_url = "http://localhost:3000"
    
    # Test 1: Check if login page is accessible
    print("\n1. Testing login page accessibility...")
    try:
        response = requests.get(f"{base_url}/login")
        if response.status_code == 200:
            print("✅ Login page is accessible")
        else:
            print(f"❌ Login page returned status {response.status_code}")
    except Exception as e:
        print(f"❌ Error accessing login page: {e}")
    
    # Test 2: Test login with correct credentials
    print("\n2. Testing login with correct credentials...")
    try:
        login_data = {
            "username": "ewais",
            "password": "Avail0021",
            "rememberDevice": True
        }
        
        response = requests.post(f"{base_url}/api/auth/login", json=login_data)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print("✅ Login successful")
                print(f"   Token: {data.get('token', 'N/A')[:20]}...")
                print(f"   Device ID: {data.get('deviceId', 'N/A')}")
                token = data.get("token")
                device_id = data.get("deviceId")
            else:
                print(f"❌ Login failed: {data.get('error', 'Unknown error')}")
                return
        else:
            print(f"❌ Login request failed with status {response.status_code}")
            return
    except Exception as e:
        print(f"❌ Error during login test: {e}")
        return
    
    # Test 3: Test token verification
    print("\n3. Testing token verification...")
    try:
        verify_data = {
            "token": token,
            "deviceId": device_id
        }
        
        response = requests.post(f"{base_url}/api/auth/verify", json=verify_data)
        if response.status_code == 200:
            data = response.json()
            if data.get("authenticated"):
                print("✅ Token verification successful")
                print(f"   Username: {data.get('username', 'N/A')}")
                print(f"   Name: {data.get('name', 'N/A')}")
            else:
                print("❌ Token verification failed")
        else:
            print(f"❌ Verification request failed with status {response.status_code}")
    except Exception as e:
        print(f"❌ Error during verification test: {e}")
    
    # Test 4: Test logout
    print("\n4. Testing logout...")
    try:
        logout_data = {
            "token": token,
            "deviceId": device_id
        }
        
        response = requests.post(f"{base_url}/api/auth/logout", json=logout_data)
        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                print("✅ Logout successful")
            else:
                print(f"❌ Logout failed: {data.get('error', 'Unknown error')}")
        else:
            print(f"❌ Logout request failed with status {response.status_code}")
    except Exception as e:
        print(f"❌ Error during logout test: {e}")
    
    # Test 5: Test local development bypass
    print("\n5. Testing local development bypass...")
    try:
        bypass_data = {
            "token": "local_dev_1234567890",
            "deviceId": "local_development"
        }
        
        response = requests.post(f"{base_url}/api/auth/verify", json=bypass_data)
        if response.status_code == 200:
            data = response.json()
            if data.get("authenticated"):
                print("✅ Local development bypass working")
            else:
                print("❌ Local development bypass not working")
        else:
            print(f"❌ Bypass test failed with status {response.status_code}")
    except Exception as e:
        print(f"❌ Error during bypass test: {e}")
    
    print("\n🎉 Authentication system test complete!")

if __name__ == "__main__":
    test_auth() 