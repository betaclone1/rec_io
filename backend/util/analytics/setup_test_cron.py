#!/usr/bin/env python3
"""
Setup Test Cron Job
Creates a test cron job that runs in 5 minutes
"""

import subprocess
import datetime
from pathlib import Path

def get_time_3_minutes_from_now():
    """Get the time 3 minutes from now."""
    now = datetime.datetime.now()
    future_time = now + datetime.timedelta(minutes=3)
    return future_time.minute, future_time.hour

def setup_test_cron():
    """Setup a test cron job to run in 3 minutes."""
    minute, hour = get_time_3_minutes_from_now()
    
    print(f"🕐 Setting up test cron job for {hour:02d}:{minute:02d}")
    
    # Create test cron entry
    cron_entry = f"# Test Daily Update Cron Job - Runs in 3 minutes\n{minute} {hour} * * * /opt/rec_io_server/backend/util/analytics/run_daily_update.sh >/dev/null 2>&1\n"
    
    # Save to temporary file
    temp_cron_file = "/tmp/test_cron"
    with open(temp_cron_file, 'w') as f:
        f.write(cron_entry)
    
    try:
        # Install the test cron job
        result = subprocess.run(['crontab', temp_cron_file], 
                              capture_output=True, text=True, check=True)
        print("✅ Test cron job installed successfully")
        print(f"📅 Will run at {hour:02d}:{minute:02d} today")
        
        # Show current crontab
        result = subprocess.run(['crontab', '-l'], 
                              capture_output=True, text=True, check=True)
        print("\n📋 Current crontab:")
        print(result.stdout)
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install test cron job: {e}")
        print(f"Error output: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def main():
    """Main function."""
    print("=" * 60)
    print("🧪 SETTING UP TEST CRON JOB")
    print("=" * 60)
    
    success = setup_test_cron()
    
    if success:
        print("\n✅ Test cron job setup complete!")
        print("📊 The daily update will run in 3 minutes")
        print("📁 Check logs in /opt/rec_io_server/logs/ for results")
        print("\n⚠️  Remember to remove this test cron job after testing!")
        print("   Run: crontab -r (to remove all cron jobs)")
        print("   Then reinstall the midnight cron job")
    else:
        print("\n❌ Test cron job setup failed!")
    
    return success

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
