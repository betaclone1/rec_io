#!/bin/bash

# =============================================================================
# BLOCK NEW DEPLOYMENT SCRIPT
# =============================================================================
# This script immediately blocks a new deployment from starting with original
# credentials. Run this on any new droplet created from a snapshot.
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[BLOCK_DEPLOYMENT]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[BLOCK_DEPLOYMENT] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[BLOCK_DEPLOYMENT] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[BLOCK_DEPLOYMENT] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    BLOCKING NEW DEPLOYMENT${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Main function
main() {
    print_header
    print_status "Blocking new deployment from starting with original credentials..."
    echo ""
    
    # Stop the startup service immediately
    print_status "Stopping automatic startup service..."
    systemctl stop rec-io-simple-startup.service 2>/dev/null || true
    systemctl disable rec-io-simple-startup.service 2>/dev/null || true
    print_success "Startup service stopped and disabled"
    
    # Kill any running processes
    print_status "Killing any running REC.IO processes..."
    pkill -f "python.*main.py" 2>/dev/null || true
    pkill -f "auto_entry_supervisor" 2>/dev/null || true
    pkill -f "active_trade_supervisor" 2>/dev/null || true
    pkill -f "trade_executor" 2>/dev/null || true
    print_success "All processes stopped"
    
    # Remove production flag
    print_status "Removing production system flag..."
    rm -f /opt/rec_io_server/.production_system
    print_success "Production flag removed"
    
    # Create warning file
    print_status "Creating security warning file..."
    cat > /opt/rec_io_server/SECURITY_WARNING.txt << 'EOF'
=============================================================================
                    SECURITY WARNING - NEW DEPLOYMENT
=============================================================================

This droplet was created from a production snapshot and contains original
user data and credentials. The system has been blocked from starting for
security reasons.

TO PROCEED:
1. Run the collaborator setup script:
   cd /opt/rec_io_server
   ./scripts/install_deploy/collaborator_setup.sh

2. Provide your user information and Kalshi credentials

3. The system will be sanitized and configured for your use

DO NOT attempt to start the system manually until sanitization is complete.

=============================================================================
EOF
    print_success "Security warning file created"
    
    echo ""
    print_success "New deployment successfully blocked!"
    print_warning "System will not start until sanitization is completed"
    echo ""
    print_status "Next steps:"
    print_status "1. Run: ./scripts/install_deploy/collaborator_setup.sh"
    print_status "2. Follow the setup prompts"
    print_status "3. System will start automatically after sanitization"
    echo ""
}

# Run main function
main "$@"

