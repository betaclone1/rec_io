#!/bin/bash

# Manual Log Rotation Script for Trading System
# Provides logrotate functionality on macOS

echo "🔄 MANUAL LOG ROTATION SYSTEM"
echo "=============================="

# Change to project directory (required for cron execution)
cd "$(dirname "$0")/.." || exit 1

# Configuration
LOG_DIR="logs"
MAX_SIZE_MB=10
KEEP_DAYS=7
COMPRESS_OLD=true

# Function to rotate a single log file
rotate_log() {
    local log_file="$1"
    local log_size_mb=$(du -m "$log_file" 2>/dev/null | cut -f1)
    
    if [ -f "$log_file" ] && [ "$log_size_mb" -gt "$MAX_SIZE_MB" ]; then
        echo "  Rotating $log_file (${log_size_mb}MB)"
        
        # Create timestamp for rotation
        local timestamp=$(date +%Y%m%d_%H%M%S)
        local rotated_file="${log_file}.${timestamp}"
        
        # Move current log to rotated position
        mv "$log_file" "$rotated_file"
        
        # Create new empty log file
        touch "$log_file"
        chmod 644 "$log_file"
        
        # Compress old log if enabled
        if [ "$COMPRESS_OLD" = true ]; then
            gzip "$rotated_file"
            echo "    Compressed: ${rotated_file}.gz"
        fi
        
        # Reload supervisor service if it's a service log
        local service_name=$(basename "$log_file" | sed 's/\.out\.log\|\.err\.log\|\.log$//')
        if supervisorctl -c backend/supervisord.conf status "$service_name" >/dev/null 2>&1; then
            echo "    Reloading supervisor service: $service_name"
            supervisorctl -c backend/supervisord.conf reload "$service_name" >/dev/null 2>&1 || true
        fi
    fi
}

# Function to clean old rotated logs
cleanup_old_logs() {
    echo "🧹 Cleaning up old rotated logs (older than $KEEP_DAYS days)..."
    
    # Find and remove old rotated logs
    find "$LOG_DIR" -name "*.log.*" -type f -mtime +$KEEP_DAYS -delete 2>/dev/null
    find "$LOG_DIR" -name "*.log.*.gz" -type f -mtime +$KEEP_DAYS -delete 2>/dev/null
    
    echo "  Cleanup complete"
}

# Main rotation logic
echo "📊 Checking for large log files..."

# List of log files to monitor
log_files=(
    "logs/main_app.out.log"
    "logs/main_app.err.log"
    "logs/trade_manager.out.log"
    "logs/trade_manager.err.log"
    "logs/trade_executor.out.log"
    "logs/trade_executor.err.log"

    "logs/active_trade_supervisor.out.log"
    "logs/active_trade_supervisor.err.log"
    "logs/auto_entry_supervisor.out.log"
    "logs/auto_entry_supervisor.err.log"
    "logs/btc_price_watchdog.out.log"
    "logs/btc_price_watchdog.err.log"

    "logs/kalshi_account_sync.out.log"
    "logs/kalshi_account_sync.err.log"
    "logs/kalshi_market_watchdog.out.log"
    "logs/kalshi_market_watchdog.err.log"
    "logs/unified_production_coordinator.out.log"
    "logs/unified_production_coordinator.err.log"
    "logs/cascading_failure_detector.out.log"
    "logs/cascading_failure_detector.err.log"
)

# Rotate each log file
for log_file in "${log_files[@]}"; do
    if [ -f "$log_file" ]; then
        rotate_log "$log_file"
    fi
done

# Cleanup old logs
cleanup_old_logs

# Show results
echo ""
echo "📊 ROTATION RESULTS:"
echo "  Current log directory size: $(du -sh logs/ | cut -f1)"
echo "  Active log files: $(find logs/ -name "*.log" -type f | wc -l)"
echo "  Compressed log files: $(find logs/ -name "*.gz" -type f | wc -l)"

echo ""
echo "✅ Manual log rotation complete!" 