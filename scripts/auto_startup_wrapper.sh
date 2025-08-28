#!/bin/bash

# Auto startup wrapper for REC.IO system
# This script is called by systemd on boot

set -e

# Configuration
LOG_FILE="/var/log/rec-io-auto-startup.log"
PROJECT_ROOT="/opt/rec_io_server"
MASTER_RESTART_SCRIPT="$PROJECT_ROOT/scripts/MASTER_RESTART_WITH_SANITIZATION_CHECK.sh"

# Create log directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

# Function to log messages
log_message() {
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - $1" | tee -a "$LOG_FILE"
}

# Start logging
log_message "=== REC.IO Auto Startup Started ==="
log_message "System boot detected, starting REC.IO services..."

# Change to project directory
cd "$PROJECT_ROOT" || {
    log_message "ERROR: Failed to change to project directory: $PROJECT_ROOT"
    exit 1
}

# Check if MASTER_RESTART script exists
if [[ ! -f "$MASTER_RESTART_SCRIPT" ]]; then
    log_message "ERROR: MASTER_RESTART script not found: $MASTER_RESTART_SCRIPT"
    exit 1
fi

# Make script executable
chmod +x "$MASTER_RESTART_SCRIPT"

# Run MASTER_RESTART with logging
log_message "Executing MASTER_RESTART script..."
if "$MASTER_RESTART_SCRIPT" >> "$LOG_FILE" 2>&1; then
    log_message "=== REC.IO Auto Startup Completed Successfully ==="
else
    log_message "ERROR: MASTER_RESTART script failed"
    log_message "=== REC.IO Auto Startup Failed ==="
    exit 1
fi
