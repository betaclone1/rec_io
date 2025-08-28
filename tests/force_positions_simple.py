#!/usr/bin/env python3
"""
Simple script to force a positions update from Kalshi API
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Now import the function
sys.path.insert(0, os.path.join(project_root, 'backend', 'api', 'kalshi-api'))

try:
    from backend.kalshi_account_sync_ws import sync_positions
    print("🔄 Forcing positions update from Kalshi API...")
    print("=" * 60)
    sync_positions()
    print("=" * 60)
    print("✅ Positions update completed!")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
