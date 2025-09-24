#!/bin/bash

# =============================================================================
# SETUP FIRST BOOT SANITIZATION SERVICE
# =============================================================================
# This script sets up the first-boot sanitization service that automatically
# sanitizes new droplets created from snapshots.
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
    echo -e "${BLUE}[SETUP_FIRST_BOOT]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SETUP_FIRST_BOOT] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[SETUP_FIRST_BOOT] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[SETUP_FIRST_BOOT] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    SETUP FIRST BOOT SANITIZATION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Create the first-boot sanitization systemd service
create_first_boot_service() {
    print_status "Creating first-boot sanitization service..."
    
    cat > /etc/systemd/system/first-boot-sanitize.service << 'EOF'
[Unit]
Description=REC.IO First Boot Sanitization
After=network.target postgresql.service
Before=rec-io-simple-startup.service
Wants=network.target postgresql.service

[Service]
Type=oneshot
RemainAfterExit=no
User=root
Group=root
WorkingDirectory=/opt/rec_io_server
Environment=PATH=/opt/rec_io_server/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/opt/rec_io_server/scripts/first_boot_sanitize.sh
StandardOutput=journal
StandardError=journal
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

    print_success "First-boot sanitization service created"
}

# Modify the startup service to depend on sanitization
modify_startup_service() {
    print_status "Modifying startup service to depend on sanitization..."
    
    # Add dependency on first-boot sanitization
    sed -i '/After=network.target postgresql.service/c\After=network.target postgresql.service first-boot-sanitize.service' /etc/systemd/system/rec-io-simple-startup.service
    sed -i '/Wants=network.target postgresql.service/c\Wants=network.target postgresql.service first-boot-sanitize.service' /etc/systemd/system/rec-io-simple-startup.service
    
    print_success "Startup service modified to depend on sanitization"
}

# Enable the services
enable_services() {
    print_status "Enabling first-boot sanitization service..."
    
    systemctl daemon-reload
    systemctl enable first-boot-sanitize.service
    
    print_success "First-boot sanitization service enabled"
}

# Main function
main() {
    print_header
    print_status "Setting up first-boot sanitization for new deployments..."
    echo ""
    
    # Only set this up if this is NOT a production system
    if [ -f "/opt/rec_io_server/.production_system" ]; then
        print_warning "Production system detected - first-boot sanitization setup skipped"
        print_warning "This is normal and expected for production systems"
        exit 0
    fi
    
    create_first_boot_service
    modify_startup_service
    enable_services
    
    echo ""
    print_success "First-boot sanitization setup completed!"
    print_status "New droplets created from snapshots will automatically sanitize on first boot"
    echo ""
}

# Run main function
main "$@"

