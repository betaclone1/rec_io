#!/bin/bash

# =============================================================================
# DISABLE AUTO STARTUP SCRIPT
# =============================================================================
# This script disables the automatic startup service
# =============================================================================

set -e

# Colors for output
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[DISABLE_AUTO_STARTUP]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[DISABLE_AUTO_STARTUP] ⚠️${NC} $1"
}

print_status "Disabling automatic startup service..."

# Stop and disable the service
systemctl stop rec-io-simple-startup.service
systemctl disable rec-io-simple-startup.service

print_warning "Auto-startup service disabled"
print_status "System will NOT automatically start on boot"

echo ""
print_status "To re-enable later: ./scripts/install_deploy/enable_auto_startup.sh"
print_status "To start manually: ./scripts/MASTER_RESTART.sh"

