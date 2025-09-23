#!/bin/bash
# Check Cron Job Status - No Interactive Interface

echo "=== CRON JOB STATUS ==="
echo "Current time: $(date)"
echo ""

# Check if cron job is installed
if crontab -l 2>/dev/null | grep -q "run_daily_update.sh"; then
    echo "✅ CRON JOB IS INSTALLED"
    echo ""
    echo "Current crontab:"
    crontab -l
    echo ""
    
    # Check for recent log files
    echo "=== RECENT LOG FILES ==="
    LOG_FILES=$(find /opt/rec_io_server/logs -name "daily_update_*" -mtime -1 2>/dev/null | head -5)
    if [ -n "$LOG_FILES" ]; then
        echo "Recent daily update logs:"
        ls -la $LOG_FILES
        echo ""
        
        # Show latest log content
        LATEST_LOG=$(ls -t /opt/rec_io_server/logs/daily_update_* 2>/dev/null | head -1)
        if [ -n "$LATEST_LOG" ]; then
            echo "=== LATEST LOG CONTENT ==="
            tail -10 "$LATEST_LOG"
        fi
    else
        echo "No recent daily update logs found"
    fi
    
else
    echo "❌ CRON JOB NOT INSTALLED"
    echo ""
    echo "To install:"
    echo "1. Run: /opt/rec_io_server/install_production_cron.sh"
    echo "2. Or manually: crontab -e and add:"
    echo "   0 0 * * * /opt/rec_io_server/backend/util/analytics/run_daily_update.sh"
fi
