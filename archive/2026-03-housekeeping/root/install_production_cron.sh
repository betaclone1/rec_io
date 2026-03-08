#!/bin/bash
# Install Production Cron Job - No Interactive Interface
# This script installs the midnight cron job directly

# Create the production cron entry
cat > /tmp/production_cron << 'EOF'
# Daily Historical Data Update - Runs every day at midnight
0 0 * * * /opt/rec_io_server/backend/util/analytics/run_daily_update.sh >/dev/null 2>&1
EOF

# Install the cron job
crontab /tmp/production_cron

# Verify installation
if crontab -l | grep -q "run_daily_update.sh"; then
    echo "SUCCESS: Daily update cron job installed"
    echo "SCHEDULE: Every day at 00:00 (midnight)"
    echo "COMMAND: /opt/rec_io_server/backend/util/analytics/run_daily_update.sh"
    exit 0
else
    echo "ERROR: Failed to install cron job"
    exit 1
fi
