#!/bin/bash

# =============================================================================
# INSTALL AUTO STARTUP SERVICE
# =============================================================================
# This script installs a systemd service that automatically runs
# MASTER_RESTART on system boot for both production and collaborator systems.
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
    echo -e "${BLUE}[AUTO_STARTUP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[AUTO_STARTUP] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[AUTO_STARTUP] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[AUTO_STARTUP] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                INSTALLING AUTO STARTUP SERVICE${NC}"
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
    cat > /etc/systemd/system/rec-io-auto-startup.service << 'EOF'
[Unit]
Description=REC.IO Auto Startup Service
After=network.target postgresql.service
Wants=network.target postgresql.service

[Service]
Type=oneshot
RemainAfterExit=yes
User=root
Group=root
WorkingDirectory=/opt/rec_io_server
Environment=PATH=/opt/rec_io_server/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/rec_io_server/scripts/MASTER_RESTART_WITH_SANITIZATION_CHECK.sh
ExecStop=/bin/true
StandardOutput=journal
StandardError=journal
TimeoutStartSec=300
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
    systemctl enable rec-io-auto-startup.service
    
    print_success "Auto startup service enabled"
}

# Function to create startup script wrapper
create_startup_wrapper() {
    print_status "Creating startup wrapper script..."
    
    # Create a wrapper script that handles logging
    cat > /opt/rec_io_server/scripts/auto_startup_wrapper.sh << 'EOF'
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
EOF

    # Make the wrapper script executable
    chmod +x /opt/rec_io_server/scripts/auto_startup_wrapper.sh
    
    print_success "Startup wrapper script created"
}

# Function to update systemd service to use wrapper
update_systemd_service() {
    print_status "Updating systemd service to use wrapper script..."
    
    # Update the service file to use the wrapper
    sed -i 's|ExecStart=/opt/rec_io_server/scripts/MASTER_RESTART_WITH_SANITIZATION_CHECK.sh|ExecStart=/opt/rec_io_server/scripts/auto_startup_wrapper.sh|' /etc/systemd/system/rec-io-auto-startup.service
    
    print_success "Systemd service updated to use wrapper"
}

# Function to create log rotation configuration
setup_log_rotation() {
    print_status "Setting up log rotation for auto startup logs..."
    
    # Create logrotate configuration
    cat > /etc/logrotate.d/rec-io-auto-startup << 'EOF'
/var/log/rec-io-auto-startup.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 root root
    postrotate
        systemctl reload rec-io-auto-startup.service > /dev/null 2>&1 || true
    endscript
}
EOF

    print_success "Log rotation configured"
}

# Function to test the service
test_service() {
    print_status "Testing auto startup service..."
    
    # Check if service is properly configured
    if systemctl is-enabled rec-io-auto-startup.service > /dev/null 2>&1; then
        print_success "Service is enabled"
    else
        print_error "Service is not enabled"
        return 1
    fi
    
    # Check if service file is valid
    if systemctl cat rec-io-auto-startup.service > /dev/null 2>&1; then
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
    systemctl status rec-io-auto-startup.service --no-pager || true
    echo ""
    print_status "To manually start the service:"
    print_status "  systemctl start rec-io-auto-startup.service"
    print_status ""
    print_status "To check service logs:"
    print_status "  journalctl -u rec-io-auto-startup.service -f"
    print_status "  tail -f /var/log/rec-io-auto-startup.log"
    echo ""
}

# Main function
main() {
    print_header
    
    # Check if running as root
    check_root
    
    # Create systemd service
    create_systemd_service
    
    # Create startup wrapper
    create_startup_wrapper
    
    # Update systemd service to use wrapper
    update_systemd_service
    
    # Enable the service
    enable_service
    
    # Setup log rotation
    setup_log_rotation
    
    # Test the service
    test_service
    
    # Show service status
    show_service_status
    
    print_success "Auto startup service installation completed!"
    print_status "The system will now automatically start REC.IO services on boot"
}

# Run main function
main "$@"
