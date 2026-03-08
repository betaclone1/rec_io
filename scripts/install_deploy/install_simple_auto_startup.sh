#!/bin/bash

# =============================================================================
# INSTALL SIMPLE AUTO STARTUP SERVICE
# =============================================================================
# This script installs a systemd service that automatically runs
# the ORIGINAL MASTER_RESTART.sh on system boot.
# NO SANITIZATION FEATURES - ONLY THE ORIGINAL SCRIPT
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
    echo -e "${BLUE}[SIMPLE_AUTO_STARTUP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SIMPLE_AUTO_STARTUP] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[SIMPLE_AUTO_STARTUP] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[SIMPLE_AUTO_STARTUP] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}            INSTALLING SIMPLE AUTO STARTUP SERVICE${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Function to check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root"
        exit 1
    fi
}

# Function to create the systemd service
create_systemd_service() {
    print_status "Creating systemd service for auto startup..."
    
    # Create the service file
    cat > /etc/systemd/system/rec-io-simple-startup.service << 'EOF'
[Unit]
Description=REC.IO Simple Auto Startup Service
After=network.target postgresql.service
Wants=network.target postgresql.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=root
Group=root
WorkingDirectory=/opt/rec_io_server
Environment=PATH=/opt/rec_io_server/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/rec_io_server/scripts/MASTER_RESTART.sh
ExecStop=/bin/true
StandardOutput=journal
StandardError=journal
TimeoutStartSec=600
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

    print_success "Systemd service file created"
}

# Function to enable the service
enable_service() {
    print_status "Enabling auto startup service..."
    
    # Reload systemd daemon
    systemctl daemon-reload
    
    # Enable the service
    systemctl enable rec-io-simple-startup.service
    
    print_success "Auto startup service enabled"
}

# Function to create log rotation configuration
setup_log_rotation() {
    print_status "Setting up log rotation for auto startup logs..."
    
    # Create logrotate configuration
    cat > /etc/logrotate.d/rec-io-simple-startup << 'EOF'
/var/log/rec-io-simple-startup.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 root root
    postrotate
        systemctl reload rec-io-simple-startup.service > /dev/null 2>&1 || true
    endscript
}
EOF

    print_success "Log rotation configured"
}

# Function to test the service
test_service() {
    print_status "Testing auto startup service..."
    
    # Check if service is properly configured
    if systemctl is-enabled rec-io-simple-startup.service > /dev/null 2>&1; then
        print_success "Service is enabled"
    else
        print_error "Service is not enabled"
        return 1
    fi
    
    # Check if service file is valid
    if systemctl cat rec-io-simple-startup.service > /dev/null 2>&1; then
        print_success "Service file is valid"
    else
        print_error "Service file is invalid"
        return 1
    fi
    
    print_success "Service test passed"
}

# Function to show service status
show_service_status() {
    print_status "Auto startup service status:"
    echo ""
    systemctl status rec-io-simple-startup.service --no-pager || true
    echo ""
    print_status "To manually start the service:"
    print_status "  systemctl start rec-io-simple-startup.service"
    print_status ""
    print_status "To check service logs:"
    print_status "  journalctl -u rec-io-simple-startup.service -f"
    echo ""
}

# Main function
main() {
    print_header
    
    # Check if running as root
    check_root
    
    # Create systemd service
    create_systemd_service
    
    # Enable the service
    enable_service
    
    # Setup log rotation
    setup_log_rotation
    
    # Test the service
    test_service
    
    # Show service status
    show_service_status
    
    print_success "Simple auto startup service installation completed!"
    print_status "The system will now automatically run MASTER_RESTART.sh on boot"
    print_status "NO SANITIZATION FEATURES - ONLY THE ORIGINAL SCRIPT"
}

# Run main function
main "$@"
