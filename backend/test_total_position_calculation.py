#!/usr/bin/env python3
"""
Test script to run update_total_position and see the calculation
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from backend.main import update_total_position

def test_calculation():
    print("Testing total_position calculation...")
    result = update_total_position()
    print(f"Result: {result}")

if __name__ == "__main__":
    test_calculation()
