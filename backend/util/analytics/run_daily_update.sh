#!/bin/bash
#
# Daily Update Cron Wrapper Script
# Runs the daily historical data update with proper environment setup
#

# Set script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Set environment variables
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
export PATH="/opt/rec_io_server/venv/bin:$PATH"

# Set working directory
cd "$PROJECT_ROOT"

# Log file with timestamp
LOG_FILE="/opt/rec_io_server/logs/daily_update_cron_$(date +%Y%m%d_%H%M%S).log"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "🚀 Starting daily historical data update cron job"
log "Project root: $PROJECT_ROOT"
log "Script directory: $SCRIPT_DIR"
log "Python path: $PYTHONPATH"

# Check if virtual environment exists
if [ ! -f "/opt/rec_io_server/venv/bin/python" ]; then
    log "❌ ERROR: Virtual environment not found at /opt/rec_io_server/venv/"
    exit 1
fi

# Check if daily update script exists
if [ ! -f "$SCRIPT_DIR/daily_update.py" ]; then
    log "❌ ERROR: Daily update script not found at $SCRIPT_DIR/daily_update.py"
    exit 1
fi

# Run the daily update script
log "📊 Executing daily update script..."
python3 "$SCRIPT_DIR/daily_update.py" 2>&1 | tee -a "$LOG_FILE"

# Capture exit code
EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "✅ Daily update completed successfully"
else
    log "❌ Daily update failed with exit code: $EXIT_CODE"
fi

log "🏁 Daily update cron job finished"
exit $EXIT_CODE
