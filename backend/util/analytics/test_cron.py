#!/usr/bin/env python3
"""
Simple test script to verify cron job setup works
"""

import os
import sys
from datetime import datetime
from pathlib import Path

def main():
    """Simple test function that just logs and exits."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"cron_test_{timestamp}.log"
    
    with open(log_file, 'w') as f:
        f.write(f"CRON TEST SUCCESSFUL\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Python executable: {sys.executable}\n")
        f.write(f"Working directory: {os.getcwd()}\n")
        f.write(f"Script path: {__file__}\n")
        f.write(f"Environment variables:\n")
        for key, value in os.environ.items():
            if 'PATH' in key or 'PYTHON' in key:
                f.write(f"  {key}={value}\n")
    
    print(f"✅ Cron test successful - log written to {log_file}")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
