#!/bin/bash
#
# Lightweight Daily Update Cron Wrapper Script
# Memory-optimized version for systems with limited resources
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
LOG_FILE="/opt/rec_io_server/logs/daily_update_lightweight_cron_$(date +%Y%m%d_%H%M%S).log"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "🚀 Starting lightweight daily update cron job"
log "Project root: $PROJECT_ROOT"
log "Script directory: $SCRIPT_DIR"
log "Python path: $PYTHONPATH"

# Check if virtual environment exists
if [ ! -f "/opt/rec_io_server/venv/bin/python" ]; then
    log "❌ ERROR: Virtual environment not found at /opt/rec_io_server/venv/"
    exit 1
fi

# Check if lightweight update script exists
if [ ! -f "$SCRIPT_DIR/daily_update_lightweight.py" ]; then
    log "❌ ERROR: Lightweight update script not found at $SCRIPT_DIR/daily_update_lightweight.py"
    exit 1
fi

# Run the lightweight update script
log "📊 Executing lightweight daily update script..."
python3 "$SCRIPT_DIR/daily_update_lightweight.py" 2>&1 | tee -a "$LOG_FILE"

# Capture exit code
EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "✅ Lightweight daily update completed successfully"
else
    log "❌ Lightweight daily update failed with exit code: $EXIT_CODE"
fi

log "🏁 Lightweight daily update cron job finished"
exit $EXIT_CODE
