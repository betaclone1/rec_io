#!/bin/bash

# =============================================================================
# MASTER RESTART FUNCTION - UNIVERSAL SYSTEM RESTART
# =============================================================================
# This script provides a complete system restart with port flushing and
# supervisor restart. Use this as the primary tool for starting/restarting
# the trading system.
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Load unified configuration system
source "$(dirname -- "${BASH_SOURCE[0]}")/load_unified_config.sh"

# Configuration - Use unified configuration
SUPERVISOR_CONFIG="$REC_PROJECT_ROOT/backend/supervisord.conf"
SUPERVISOR_SOCKET="/tmp/supervisord.sock"
SUPERVISOR_PID="/tmp/supervisord.pid"

# Port assignments from MASTER_PORT_MANIFEST.json
PORTS=(3000 4000 6000 8001 8002 8003 8004 8005 8008)

# Function to print colored output
print_status() {
    echo -e "${BLUE}[MASTER_RESTART]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[MASTER_RESTART] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[MASTER_RESTART] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[MASTER_RESTART] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    MASTER RESTART FUNCTION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Function to check if a port is in use (only listening processes)
check_port() {
    local port=$1
    if lsof -i :$port | grep LISTEN >/dev/null 2>&1; then
        return 0  # Port is in use (listening)
    else
        return 1  # Port is free
    fi
}

# Function to kill processes on a specific port
kill_port() {
    local port=$1
    print_status "Checking port $port..."
    
    if check_port $port; then
        print_warning "Port $port is in use. Killing processes..."
        
        # Get the process IDs using the port
        local pids=$(lsof -ti :$port 2>/dev/null)
        if [ -n "$pids" ]; then
            print_warning "Found processes on port $port: $pids"
            
            # Kill the processes
            echo "$pids" | xargs kill -9 2>/dev/null || true
            /bin/sleep 2
            
            # Try again if still in use
            if check_port $port; then
                print_warning "Port $port still in use, trying again..."
                /bin/sleep 2
                lsof -ti :$port | xargs kill -9 2>/dev/null || true
                /bin/sleep 2
            fi
            
            # Final verification
            if check_port $port; then
                print_error "Failed to free port $port after multiple attempts"
                return 1
            else
                print_success "Port $port freed"
            fi
        else
            print_warning "No process IDs found for port $port"
            return 1
        fi
    else
        print_success "Port $port is already free"
    fi
}

# Function to flush all ports
flush_all_ports() {
    print_header
    print_status "Starting port flush operation..."
    
    for port in "${PORTS[@]}"; do
        kill_port $port
    done
    
    print_success "All ports flushed"
}

# Function to stop supervisor
stop_supervisor() {
    print_status "Stopping supervisor..."
    
    if [ -S "$SUPERVISOR_SOCKET" ]; then
        supervisorctl -c "$SUPERVISOR_CONFIG" shutdown 2>/dev/null || true
        /bin/sleep 2
    fi
    
    # Kill supervisor process if still running
    if [ -f "$SUPERVISOR_PID" ]; then
        local pid=$(cat "$SUPERVISOR_PID")
        if kill -0 $pid 2>/dev/null; then
            print_warning "Killing supervisor process $pid"
            kill -9 $pid 2>/dev/null || true
        fi
    fi
    
    # Clean up socket and pid files
    rm -f "$SUPERVISOR_SOCKET" "$SUPERVISOR_PID" 2>/dev/null || true
    
    print_success "Supervisor stopped"
}

# Function to start supervisor
start_supervisor() {
    print_status "Starting supervisor..."
    
    # Start supervisor in background
    supervisord -c "$SUPERVISOR_CONFIG" &
    local supervisor_pid=$!
    
    # Wait for supervisor to start
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if [ -S "$SUPERVISOR_SOCKET" ]; then
            break
        fi
        /bin/sleep 1
        attempts=$((attempts + 1))
    done
    
    if [ -S "$SUPERVISOR_SOCKET" ]; then
        print_success "Supervisor started (PID: $supervisor_pid)"
    else
        print_error "Failed to start supervisor"
        return 1
    fi
}

# Function to restart all services
restart_all_services() {
    print_status "Restarting all services..."
    
    # Wait a moment for supervisor to fully initialize
    /bin/sleep 2
    
    # Get list of all programs
    local programs=$(supervisorctl -c "$SUPERVISOR_CONFIG" status | awk '{print $1}' | grep -v "supervisorctl")
    
    for program in $programs; do
        print_status "Restarting $program..."
        supervisorctl -c "$SUPERVISOR_CONFIG" restart $program
        /bin/sleep 1
    done
    
    print_success "All services restarted"
}

# Function to verify all services are running
verify_services() {
    print_status "Verifying all services are running..."
    
    local all_running=true
    
    # Check supervisor status
    local status_output=$(supervisorctl -c "$SUPERVISOR_CONFIG" status)
    echo "$status_output" | while IFS= read -r line; do
        if [[ $line =~ ^[a-zA-Z_]+[[:space:]]+(RUNNING|STARTING) ]]; then
            local service=$(echo "$line" | awk '{print $1}')
            local state=$(echo "$line" | awk '{print $2}')
            if [ "$state" = "RUNNING" ]; then
                print_success "$service is running"
            else
                print_warning "$service is starting..."
            fi
        elif [[ $line =~ ^[a-zA-Z_]+[[:space:]]+(FATAL|EXITED|STOPPED) ]]; then
            local service=$(echo "$line" | awk '{print $1}')
            print_error "$service failed to start"
            all_running=false
        fi
    done
    
    # Check if all ports are now in use by our services
    print_status "Verifying port assignments..."
    for port in "${PORTS[@]}"; do
        if check_port $port; then
            print_success "Port $port is active"
        else
            print_warning "Port $port is not in use (may be normal for watchdog services)"
        fi
    done
    
    if [ "$all_running" = true ]; then
        print_success "All services verified"
    else
        print_error "Some services failed to start"
        return 1
    fi
}

# Function to show system status
show_status() {
    print_header
    print_status "Current system status:"
    echo ""
    
    # Show supervisor status
    supervisorctl -c "$SUPERVISOR_CONFIG" status
    
    echo ""
    print_status "Port usage:"
    for port in "${PORTS[@]}"; do
        if check_port $port; then
            local process=$(lsof -i :$port | grep LISTEN | awk '{print $1}' | head -1)
            print_success "Port $port: $process"
        else
            print_warning "Port $port: free"
        fi
    done
}

# Function to check for external connections
check_external_connections() {
    print_status "Checking for external connections that might interfere..."
    
    local external_connections=$(lsof -i | grep -E "(64\.23\.138\.71|digitalocean)" 2>/dev/null || true)
    if [ -n "$external_connections" ]; then
        print_warning "Found external connections to remote servers:"
        echo "$external_connections"
        print_warning "These connections will be terminated during restart"
        echo ""
    else
        print_success "No external connections detected"
        echo ""
    fi
}

# Function to perform complete restart
master_restart() {
    print_header
    print_status "Initiating MASTER RESTART sequence..."
    echo ""
    
    # Create logs directory if it doesn't exist
    print_status "Ensuring logs directory exists..."
    mkdir -p "$PROJECT_ROOT/logs"
    print_success "Logs directory ready"
    echo ""
    
    # Check for external connections first
    check_external_connections
    
    # Step 1: Stop supervisor first to prevent auto-restart
    print_status "Step 1: Stopping supervisor..."
    stop_supervisor
    echo ""
    
    # Step 2: Force kill ALL related processes - BULLETPROOF
    print_status "Step 2: Force killing ALL related processes..."
    
    # Kill all screen sessions that might be running our processes
    print_warning "Killing all screen sessions..."
    screen -ls 2>/dev/null | grep -E "(combined_trade_tails|trade)" | cut -d. -f1 | xargs -r kill 2>/dev/null || true
    
    # Kill all tail processes that might be monitoring logs
    print_warning "Killing all tail processes..."
    ps aux 2>/dev/null | grep "tail.*log" | grep -v grep | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Kill all Python processes related to our project - BULLETPROOF
    print_warning "Killing all Python backend processes..."
    ps aux 2>/dev/null | grep python | grep -E "(backend|main\.py|trade_manager|trade_executor|active_trade_supervisor|auto_entry_supervisor|symbol_price_watchdog|strike_table_generator|kalshi_account_sync|kalshi_market_watchdog|cascading_failure_detector|system_monitor)" | grep -v grep | grep -v "MASTER_RESTART" | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Kill any processes with our project path in the command line - BULLETPROOF
    print_warning "Killing processes with project path..."
    ps aux 2>/dev/null | grep -E "(rec_io|rec_io_20)" | grep -v grep | grep -v "MASTER_RESTART" | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Kill any processes using our ports - BULLETPROOF
    print_warning "Killing processes using our ports..."
    for port in "${PORTS[@]}"; do
        lsof -ti :$port 2>/dev/null | xargs -r kill 2>/dev/null || true
    done
    
    # Kill supervisor process if still running - BULLETPROOF
    print_warning "Killing any remaining supervisor processes..."
    ps aux 2>/dev/null | grep supervisord | grep -v grep | awk '{print $2}' | xargs -r kill 2>/dev/null || true
    
    # Wait for processes to fully terminate
    /bin/sleep 3
    echo ""
    
    # Step 3: Flush all ports
    print_status "Step 3: Flushing all ports..."
    flush_all_ports
    echo ""
    
    # Step 4: Generate supervisor configuration
    print_status "Step 4: Generating unified supervisor configuration..."
    if [ -f "$REC_PROJECT_ROOT/scripts/generate_unified_supervisor_config.py" ]; then
        "$REC_PYTHON_EXECUTABLE" "$REC_PROJECT_ROOT/scripts/generate_unified_supervisor_config.py"
    else
        print_error "generate_unified_supervisor_config.py not found"
        exit 1
    fi
    echo ""
    
    # Step 5: Start supervisor
    print_status "Step 5: Starting supervisor..."
    start_supervisor
    echo ""
    
    # Step 6: Restart all services
    print_status "Step 6: Restarting all services..."
    restart_all_services
    echo ""
    
    # Step 7: Verify everything is running
    print_status "Step 7: Verifying all services..."
    verify_services
    echo ""
    
    print_success "MASTER RESTART completed successfully!"
    echo ""
    print_status "System is now ready for trading operations."
}

# Function to perform quick restart (just supervisor restart)
quick_restart() {
    print_header
    print_status "Initiating QUICK RESTART (supervisor only)..."
    echo ""
    
    # Stop and start supervisor
    stop_supervisor
    start_supervisor
    restart_all_services
    verify_services
    
    print_success "QUICK RESTART completed!"
}

# Function to perform emergency restart (force kill everything)
emergency_restart() {
    print_header
    print_status "Initiating EMERGENCY RESTART (force kill all)..."
    echo ""
    
    # Stop supervisor first to prevent auto-restart
    print_warning "Stopping supervisor..."
    if [ -S "$SUPERVISOR_SOCKET" ]; then
        supervisorctl -c "$SUPERVISOR_CONFIG" shutdown 2>/dev/null || true
        /bin/sleep 3
    fi
    
    # Kill supervisor process if still running
    pkill -f "supervisord" || true
    /bin/sleep 2
    
    # Kill all screen sessions that might be running our processes
    print_warning "Killing all screen sessions..."
    screen -ls | grep -E "(combined_trade_tails|trade)" | cut -d. -f1 | xargs -r kill 2>/dev/null || true
    
    # Kill all tail processes that might be monitoring logs
    print_warning "Killing all tail processes..."
    pkill -f "tail.*log" || true
    
    # Kill all Python processes related to our project - MORE COMPREHENSIVE
    print_warning "Killing all Python backend processes..."
    pkill -f "python.*backend" || true
    pkill -f "python.*main.py" || true
    pkill -f "python.*trade_manager.py" || true
    pkill -f "python.*trade_executor.py" || true
    pkill -f "python.*active_trade_supervisor.py" || true
    pkill -f "python.*btc_price_watchdog.py" || true
    pkill -f "python.*kalshi_account_sync.py" || true
    pkill -f "python.*kalshi_market_watchdog.py" || true
    
    # Kill any processes with our project path in the command line
    print_warning "Killing processes with project path..."
    pkill -f "rec_io" || true
    pkill -f "rec_io_20" || true
    
    # Kill any processes using our ports
    print_warning "Killing processes using our ports..."
    for port in "${PORTS[@]}"; do
        lsof -ti :$port | xargs kill -9 2>/dev/null || true
    done
    
    # Kill any remaining Python processes that might be ours
    print_warning "Killing any remaining suspicious Python processes..."
    ps aux | grep python | grep -E "(backend|trade|kalshi|btc)" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true
    
    # Clean up socket files
    rm -f /tmp/supervisord.sock /tmp/supervisord.pid
    
    # Wait a moment for processes to fully terminate
    /bin/sleep 5
    
    # Flush all ports
    flush_all_ports
    
    # Wait a moment
    /bin/sleep 2
    
    # Start fresh
    start_supervisor
    restart_all_services
    verify_services
    
    print_success "EMERGENCY RESTART completed!"
}

# Main script logic
main() {
    case "${1:-master}" in
        "master"|"full")
            master_restart
            ;;
        "quick")
            quick_restart
            ;;
        "emergency"|"force")
            master_restart
            ;;
        "status")
            show_status
            ;;
        "flush")
            flush_all_ports
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [COMMAND]"
            echo ""
            echo "Commands:"
            echo "  master, full    - Complete MASTER RESTART with process cleanup (default)"
            echo "  quick           - Quick supervisor restart only (no process cleanup)"
            echo "  emergency, force - Same as master restart (legacy alias)"
            echo "  status          - Show current system status"
            echo "  flush           - Flush all ports only"
            echo "  help            - Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0              # MASTER RESTART (default) - KILLS ALL PROCESSES"
            echo "  $0 quick        # Quick restart (supervisor only)"
            echo "  $0 emergency    # Same as default (legacy)"
            echo "  $0 status       # Show status"
            ;;
        *)
            print_error "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@" 