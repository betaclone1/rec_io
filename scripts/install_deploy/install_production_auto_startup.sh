#!/bin/bash

# =============================================================================
# INSTALL PRODUCTION AUTO STARTUP SERVICE
# =============================================================================
# This script installs the auto startup service on the production server.
# Run this on your production server to enable automatic startup on reboot.
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[PROD_AUTO_STARTUP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[PROD_AUTO_STARTUP] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[PROD_AUTO_STARTUP] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[PROD_AUTO_STARTUP] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}            INSTALLING PRODUCTION AUTO STARTUP SERVICE${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Function to check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root"
        exit 1
    fi
}

# Function to check if we're on the production server
check_production_server() {
    print_status "Checking if this is the production server..."
    
    if [[ -f "/opt/rec_io_server/.production_system" ]]; then
        print_success "Production server confirmed"
    else
        print_warning "Production system flag not found"
        print_status "Creating production system flag..."
        touch /opt/rec_io_server/.production_system
        print_success "Production system flag created"
    fi
}

# Function to install auto startup service
install_auto_startup() {
    print_status "Installing auto startup service..."
    
    if [[ -f "/opt/rec_io_server/scripts/install_deploy/install_auto_startup_service.sh" ]]; then
        chmod +x /opt/rec_io_server/scripts/install_deploy/install_auto_startup_service.sh
        /opt/rec_io_server/scripts/install_deploy/install_auto_startup_service.sh
        print_success "Auto startup service installed successfully"
    else
        print_error "Auto startup service script not found"
        print_status "Please ensure the script is in /opt/rec_io_server/scripts/install_deploy/"
        exit 1
    fi
}

# Function to test the installation
test_installation() {
    print_status "Testing auto startup installation..."
    
    # Check if service is enabled
    if systemctl is-enabled rec-io-auto-startup.service > /dev/null 2>&1; then
        print_success "Auto startup service is enabled"
    else
        print_error "Auto startup service is not enabled"
        return 1
    fi
    
    # Check if service file exists
    if [[ -f "/etc/systemd/system/rec-io-auto-startup.service" ]]; then
        print_success "Service file exists"
    else
        print_error "Service file not found"
        return 1
    fi
    
    # Check if wrapper script exists
    if [[ -f "/opt/rec_io_server/scripts/auto_startup_wrapper.sh" ]]; then
        print_success "Wrapper script exists"
    else
        print_error "Wrapper script not found"
        return 1
    fi
    
    print_success "Installation test passed"
}

# Function to show next steps
show_next_steps() {
    print_status "Production auto startup service installation completed!"
    echo ""
    print_status "Next steps:"
    print_status "1. Test the auto startup service:"
    print_status "   systemctl start rec-io-auto-startup.service"
    print_status ""
    print_status "2. Check service status:"
    print_status "   systemctl status rec-io-auto-startup.service"
    print_status ""
    print_status "3. View service logs:"
    print_status "   journalctl -u rec-io-auto-startup.service -f"
    print_status "   tail -f /var/log/rec-io-auto-startup.log"
    echo ""
    print_status "4. Test reboot (optional):"
    print_status "   reboot"
    print_status "   # System should automatically start REC.IO services on boot"
    echo ""
    print_success "Your production server will now automatically start on reboot!"
}

# Main function
main() {
    print_header
    
    # Check if running as root
    check_root
    
    # Check if we're on the production server
    check_production_server
    
    # Install auto startup service
    install_auto_startup
    
    # Test the installation
    test_installation
    
    # Show next steps
    show_next_steps
}

# Run main function
main "$@"
