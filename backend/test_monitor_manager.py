#!/usr/bin/env python3
"""
Test script for monitor_manager functionality
"""

import sys
import os
import requests
import time

# Add project root to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

from backend.core.port_config import get_port

def test_monitor_manager():
    """Test monitor_manager health and functionality"""
    try:
        monitor_port = get_port("monitor_manager")
        
        print(f"Testing monitor_manager on port {monitor_port}...")
        
        # Test health endpoint
        health_url = f"http://localhost:{monitor_port}/health"
        response = requests.get(health_url, timeout=5)
        
        if response.ok:
            health_data = response.json()
            print(f"✅ Monitor manager health check: {health_data}")
        else:
            print(f"❌ Monitor manager health check failed: {response.status_code}")
            return False
        
        # Test bankroll update endpoint
        bankroll_url = f"http://localhost:{monitor_port}/api/bankroll_updated"
        response = requests.post(bankroll_url, json={}, timeout=10)
        
        if response.ok:
            result = response.json()
            print(f"✅ Bankroll update test: {result}")
            return True
        else:
            print(f"❌ Bankroll update test failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing Monitor Manager System")
    print("=" * 40)
    
    success = test_monitor_manager()
    
    if success:
        print("\n✅ All tests passed! Monitor manager is working correctly.")
    else:
        print("\n❌ Tests failed. Check monitor manager logs.")
