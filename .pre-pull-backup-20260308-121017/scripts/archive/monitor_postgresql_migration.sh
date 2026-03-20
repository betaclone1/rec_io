#!/bin/bash

# POSTGRESQL MIGRATION MONITORING SCRIPT
# This script monitors the PostgreSQL migration deployment in production

set -e  # Exit on any error

echo "📊 POSTGRESQL MIGRATION MONITORING"
echo "==================================="
echo ""

# Configuration
MONITORING_LOG="/tmp/postgresql_migration_monitoring_$(date +%Y%m%d_%H%M%S).log"
MONITORING_INTERVAL=60  # seconds

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$MONITORING_LOG"
}

success() {
    echo -e "${GREEN}✅ $1${NC}" | tee -a "$MONITORING_LOG"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}" | tee -a "$MONITORING_LOG"
}

error() {
    echo -e "${RED}❌ $1${NC}" | tee -a "$MONITORING_LOG"
}

# Function to check PostgreSQL status
check_postgresql_status() {
    if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
        success "PostgreSQL is running"
        return 0
    else
        error "PostgreSQL is not running"
        return 1
    fi
}

# Function to check database connectivity
check_database_connectivity() {
    if psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT 1;" >/dev/null 2>&1; then
        success "Database connectivity OK"
        return 0
    else
        error "Database connectivity failed"
        return 1
    fi
}

# Function to check service health
check_service_health() {
    # Get port assignments
    ACTIVE_TRADE_SUPERVISOR_PORT=$(python3 -c "
import sys
sys.path.insert(0, '.')
from backend.core.port_config import get_port
print(get_port('active_trade_supervisor'))
" 2>/dev/null || echo "8007")
    
    TRADE_MANAGER_PORT=$(python3 -c "
import sys
sys.path.insert(0, '.')
from backend.core.port_config import get_port
print(get_port('trade_manager'))
" 2>/dev/null || echo "8008")
    
    # Check active trade supervisor health
    if curl -s "http://localhost:$ACTIVE_TRADE_SUPERVISOR_PORT/health" >/dev/null; then
        success "Active trade supervisor health OK"
    else
        error "Active trade supervisor health check failed"
        return 1
    fi
    
    # Check trade manager health
    if curl -s "http://localhost:$TRADE_MANAGER_PORT/health" >/dev/null; then
        success "Trade manager health OK"
    else
        error "Trade manager health check failed"
        return 1
    fi
    
    return 0
}

# Function to check database performance
check_database_performance() {
    # Check database size
    DB_SIZE=$(psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT pg_size_pretty(pg_database_size('rec_io_db'));" 2>/dev/null | xargs)
    if [ -n "$DB_SIZE" ]; then
        log "Database size: $DB_SIZE"
    fi
    
    # Check active connections
    ACTIVE_CONNECTIONS=$(psql -h localhost -U rec_io_user -d rec_io_db -t -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';" 2>/dev/null | xargs)
    if [ -n "$ACTIVE_CONNECTIONS" ]; then
        log "Active connections: $ACTIVE_CONNECTIONS"
    fi
    
    # Check table sizes
    TABLE_SIZES=$(psql -h localhost -U rec_io_user -d rec_io_db -t -c "
        SELECT 
            schemaname,
            tablename,
            pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
        FROM pg_tables 
        WHERE schemaname = 'public'
        ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
    " 2>/dev/null)
    
    if [ -n "$TABLE_SIZES" ]; then
        log "Table sizes:"
        echo "$TABLE_SIZES" | while read line; do
            if [ -n "$line" ]; then
                log "  $line"
            fi
        done
    fi
}

# Function to check for errors in logs
check_error_logs() {
    # Check for recent errors in system logs
    RECENT_ERRORS=$(find logs/ -name "*.log" -mtime -1 -exec grep -l "ERROR\|CRITICAL\|FATAL" {} \; 2>/dev/null | head -5)
    
    if [ -n "$RECENT_ERRORS" ]; then
        warning "Recent errors found in logs:"
        echo "$RECENT_ERRORS" | while read logfile; do
            if [ -f "$logfile" ]; then
                log "  $logfile"
                tail -5 "$logfile" | grep -i "error\|critical\|fatal" | while read error; do
                    log "    $error"
                done
            fi
        done
    else
        success "No recent errors found in logs"
    fi
}

# Function to check trade execution flow
check_trade_execution_flow() {
    # Check if there are any active trades
    ACTIVE_TRADES_COUNT=$(curl -s "http://localhost:$ACTIVE_TRADE_SUPERVISOR_PORT/api/active_trades" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('count', 0))
except:
    print('0')
" 2>/dev/null || echo "0")
    
    log "Active trades count: $ACTIVE_TRADES_COUNT"
    
    # Check if auto-stop is working
    AUTO_STOP_SETTINGS=$(find backend/data/users -name "auto_stop_settings.json" -exec cat {} \; 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    enabled = data.get('auto_stop_enabled', False)
    threshold = data.get('auto_stop_threshold', 50.0)
    print(f'enabled={enabled}, threshold={threshold}')
except:
    print('not configured')
" 2>/dev/null || echo "not configured")
    
    log "Auto-stop settings: $AUTO_STOP_SETTINGS"
}

# Function to run a single monitoring cycle
run_monitoring_cycle() {
    log "Running monitoring cycle..."
    
    # Check PostgreSQL status
    check_postgresql_status || return 1
    
    # Check database connectivity
    check_database_connectivity || return 1
    
    # Check service health
    check_service_health || return 1
    
    # Check database performance
    check_database_performance
    
    # Check for errors in logs
    check_error_logs
    
    # Check trade execution flow
    check_trade_execution_flow
    
    success "Monitoring cycle completed successfully"
    return 0
}

# Function to run continuous monitoring
run_continuous_monitoring() {
    log "Starting continuous monitoring..."
    log "Monitoring interval: ${MONITORING_INTERVAL} seconds"
    log "Monitoring log: $MONITORING_LOG"
    
    CYCLE_COUNT=0
    
    while true; do
        CYCLE_COUNT=$((CYCLE_COUNT + 1))
        log "Monitoring cycle #$CYCLE_COUNT"
        
        if run_monitoring_cycle; then
            success "Cycle #$CYCLE_COUNT: All systems OK"
        else
            error "Cycle #$CYCLE_COUNT: Issues detected"
        fi
        
        log "Waiting ${MONITORING_INTERVAL} seconds until next cycle..."
        sleep $MONITORING_INTERVAL
    done
}

# Function to run a single monitoring check
run_single_check() {
    log "Running single monitoring check..."
    
    if run_monitoring_cycle; then
        success "All systems OK"
        exit 0
    else
        error "Issues detected"
        exit 1
    fi
}

# Function to generate monitoring report
generate_report() {
    log "Generating monitoring report..."
    
    REPORT_FILE="/tmp/postgresql_migration_report_$(date +%Y%m%d_%H%M%S).txt"
    
    {
        echo "POSTGRESQL MIGRATION MONITORING REPORT"
        echo "======================================"
        echo "Generated: $(date)"
        echo ""
        
        echo "SYSTEM STATUS:"
        echo "-------------"
        if check_postgresql_status; then
            echo "✅ PostgreSQL: Running"
        else
            echo "❌ PostgreSQL: Not running"
        fi
        
        if check_database_connectivity; then
            echo "✅ Database connectivity: OK"
        else
            echo "❌ Database connectivity: Failed"
        fi
        
        if check_service_health; then
            echo "✅ Service health: OK"
        else
            echo "❌ Service health: Failed"
        fi
        
        echo ""
        echo "DATABASE PERFORMANCE:"
        echo "-------------------"
        check_database_performance
        
        echo ""
        echo "ERROR LOGS:"
        echo "----------"
        check_error_logs
        
        echo ""
        echo "TRADE EXECUTION:"
        echo "---------------"
        check_trade_execution_flow
        
    } > "$REPORT_FILE"
    
    success "Report generated: $REPORT_FILE"
    cat "$REPORT_FILE"
}

# Handle command line arguments
case "${1:-check}" in
    "check")
        run_single_check
        ;;
    "monitor")
        run_continuous_monitoring
        ;;
    "report")
        generate_report
        ;;
    "postgresql")
        check_postgresql_status
        ;;
    "connectivity")
        check_database_connectivity
        ;;
    "health")
        check_service_health
        ;;
    "performance")
        check_database_performance
        ;;
    "errors")
        check_error_logs
        ;;
    "trades")
        check_trade_execution_flow
        ;;
    *)
        echo "Usage: $0 {check|monitor|report|postgresql|connectivity|health|performance|errors|trades}"
        echo ""
        echo "Commands:"
        echo "  check       - Run single monitoring check (default)"
        echo "  monitor     - Run continuous monitoring"
        echo "  report      - Generate monitoring report"
        echo "  postgresql  - Check PostgreSQL status only"
        echo "  connectivity - Check database connectivity only"
        echo "  health      - Check service health only"
        echo "  performance - Check database performance only"
        echo "  errors      - Check error logs only"
        echo "  trades      - Check trade execution flow only"
        exit 1
        ;;
esac 