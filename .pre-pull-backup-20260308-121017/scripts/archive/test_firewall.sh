#!/bin/bash

# =============================================================================
# FIREWALL TEST SCRIPT
# =============================================================================
# 
# This script tests the firewall configuration to ensure it's working correctly
# and not interfering with system functionality.
#
# USAGE:
#   ./scripts/test_firewall.sh
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/logs/firewall_test.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Test result function
test_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓ PASS${NC}: $2"
        log "PASS: $2"
    else
        echo -e "${RED}✗ FAIL${NC}: $2"
        log "FAIL: $2"
    fi
}

# Test localhost connectivity
test_localhost() {
    log "Testing localhost connectivity..."
    
    # Test main app
    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        test_result 0 "Main app (port 3000) accessible"
    else
        test_result 1 "Main app (port 3000) not accessible"
    fi
    
    # Test trade manager
    if curl -s http://localhost:4000 > /dev/null 2>&1; then
        test_result 0 "Trade manager (port 4000) accessible"
    else
        test_result 1 "Trade manager (port 4000) not accessible"
    fi
}

# Test outbound API connectivity
test_api_connectivity() {
    log "Testing outbound API connectivity..."
    
    # Test Kalshi API
    if curl -s --connect-timeout 5 https://api.kalshi.com > /dev/null 2>&1; then
        test_result 0 "Kalshi API connectivity"
    else
        test_result 1 "Kalshi API connectivity failed"
    fi
    
    # Test Coinbase API
    if curl -s --connect-timeout 5 https://api.coinbase.com > /dev/null 2>&1; then
        test_result 0 "Coinbase API connectivity"
    else
        test_result 1 "Coinbase API connectivity failed"
    fi
}

# Test supervisor services
test_supervisor_services() {
    log "Testing supervisor services..."
    
    # Check if supervisor is running
    if supervisorctl -c backend/supervisord.conf status > /dev/null 2>&1; then
        test_result 0 "Supervisor is running"
        
        # Count running services
        running_services=$(supervisorctl -c backend/supervisord.conf status | grep RUNNING | wc -l)
        if [ "$running_services" -ge 10 ]; then
            test_result 0 "All supervisor services running ($running_services services)"
        else
            test_result 1 "Some supervisor services not running ($running_services services)"
        fi
    else
        test_result 1 "Supervisor not running"
    fi
}

# Test firewall status
test_firewall_status() {
    log "Testing firewall status..."
    
    # Check if ufw is enabled
    if ufw status | grep -q "Status: active"; then
        test_result 0 "UFW firewall is active"
    else
        test_result 1 "UFW firewall is not active"
    fi
    
    # Check default policies
    if ufw status | grep -q "Default: deny (incoming)"; then
        test_result 0 "Default incoming policy: deny"
    else
        test_result 1 "Default incoming policy not set to deny"
    fi
    
    if ufw status | grep -q "Default: allow (outgoing)"; then
        test_result 0 "Default outgoing policy: allow"
    else
        test_result 1 "Default outgoing policy not set to allow"
    fi
}

# Test specific firewall rules
test_firewall_rules() {
    log "Testing specific firewall rules..."
    
    # Check localhost rules
    if ufw status | grep -q "127.0.0.1"; then
        test_result 0 "Localhost traffic allowed"
    else
        test_result 1 "Localhost traffic not allowed"
    fi
    
    # Check SSH rules
    if ufw status | grep -q ":22"; then
        test_result 0 "SSH port (22) configured"
    else
        test_result 1 "SSH port (22) not configured"
    fi
    
    # Check web ports
    if ufw status | grep -q ":80"; then
        test_result 0 "HTTP port (80) allowed"
    else
        test_result 1 "HTTP port (80) not allowed"
    fi
    
    if ufw status | grep -q ":443"; then
        test_result 0 "HTTPS port (443) allowed"
    else
        test_result 1 "HTTPS port (443) not allowed"
    fi
}

# Test trading system ports
test_trading_ports() {
    log "Testing trading system ports..."
    
    trading_ports=(3000 4000 8001 8002 8003 8004 8005 8007 8009 8010 8011)
    
    for port in "${trading_ports[@]}"; do
        if ufw status | grep -q ":$port"; then
            test_result 0 "Port $port configured"
        else
            test_result 1 "Port $port not configured"
        fi
    done
}

# Main test execution
main() {
    log "=== FIREWALL CONFIGURATION TEST ==="
    log "Starting firewall tests..."
    
    echo ""
    echo "Testing Firewall Configuration"
    echo "=============================="
    echo ""
    
    # Run all tests
    test_firewall_status
    test_firewall_rules
    test_trading_ports
    test_localhost
    test_api_connectivity
    test_supervisor_services
    
    echo ""
    echo "Test Summary"
    echo "============"
    echo "Log file: $LOG_FILE"
    echo ""
    echo "If any tests failed, check:"
    echo "1. Firewall rules: sudo ufw status numbered"
    echo "2. Supervisor status: supervisorctl -c backend/supervisord.conf status"
    echo "3. Service logs: tail -f logs/*.out.log"
    echo ""
    echo "To reapply firewall rules:"
    echo "  sudo ./scripts/setup_firewall.sh --mode local"
    echo "  sudo ./scripts/setup_firewall.sh --mode production"
}

# Run main function
main "$@" 