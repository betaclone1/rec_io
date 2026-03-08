#!/bin/bash

# Setup Automated Log Rotation via Cron
# This script sets up automated log rotation for the trading system

echo "🔄 SETTING UP AUTOMATED LOG ROTATION"
echo "====================================="

# Get the absolute path to the project directory
PROJECT_DIR=$(pwd)
ROTATION_SCRIPT="$PROJECT_DIR/scripts/manual_log_rotation.sh"

echo "📋 Configuration:"
echo "  Project Directory: $PROJECT_DIR"
echo "  Rotation Script: $ROTATION_SCRIPT"
echo "  Rotation Schedule: Every 6 hours"
echo "  Max Log Size: 10MB"
echo "  Keep Days: 7 days"

# Check if rotation script exists
if [ ! -f "$ROTATION_SCRIPT" ]; then
    echo "❌ ERROR: Rotation script not found at $ROTATION_SCRIPT"
    exit 1
fi

# Make sure the script is executable
chmod +x "$ROTATION_SCRIPT"

# Create cron job entry
CRON_JOB="0 */6 * * * $ROTATION_SCRIPT >> $PROJECT_DIR/logs/log_rotation.log 2>&1"

echo ""
echo "📅 Adding cron job for automated rotation..."
echo "  Schedule: Every 6 hours (0, 6, 12, 18)"
echo "  Command: $ROTATION_SCRIPT"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "$ROTATION_SCRIPT"; then
    echo "  ⚠️  Cron job already exists, skipping..."
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "  ✅ Cron job added successfully"
fi

# Create log file for rotation script output
touch "$PROJECT_DIR/logs/log_rotation.log"
chmod 644 "$PROJECT_DIR/logs/log_rotation.log"

echo ""
echo "📊 VERIFICATION:"
echo "  Current cron jobs:"
crontab -l 2>/dev/null | grep -E "(log_rotation|manual_log_rotation)" || echo "    No log rotation cron jobs found"

echo ""
echo "🔄 TESTING ROTATION SCRIPT..."
echo "  Running manual rotation test..."

# Run the rotation script once to test
"$ROTATION_SCRIPT"

echo ""
echo "✅ AUTOMATED LOG ROTATION SETUP COMPLETE!"
echo ""
echo "📋 SUMMARY:"
echo "  ✅ Manual rotation script created"
echo "  ✅ Cron job configured (every 6 hours)"
echo "  ✅ Log rotation test completed"
echo "  ✅ Rotation logs will be written to: logs/log_rotation.log"
echo ""
echo "🔄 NEXT STEPS:"
echo "  1. Monitor logs/log_rotation.log for rotation activity"
echo "  2. Check logs directory size regularly"
echo "  3. Verify log access is maintained"
echo ""
echo "📊 MANUAL ROTATION COMMANDS:"
echo "  ./scripts/manual_log_rotation.sh    # Run rotation manually"
echo "  tail -f logs/log_rotation.log       # Monitor rotation activity"
echo "  du -sh logs/                        # Check log directory size" 