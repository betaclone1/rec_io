#!/usr/bin/env python3
"""
Force a positions update from Kalshi API and show the return message
"""

import sys
import os

# Set up Python path to ensure imports work correctly
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ['PYTHONPATH'] = project_root

# Import the sync_positions function
from backend.kalshi_account_sync_ws import sync_positions

def main():
    print("🔄 Forcing positions update from Kalshi API...")
    print("=" * 60)
    
    try:
        # Call the sync_positions function
        sync_positions()
        print("=" * 60)
        print("✅ Positions update completed!")
        
    except Exception as e:
        print(f"❌ Error during positions update: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
