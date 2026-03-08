#!/bin/bash

# =============================================================================
# ENABLE AUTO STARTUP SCRIPT
# =============================================================================
# This script re-enables the automatic startup service for production systems
# =============================================================================

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${BLUE}[ENABLE_AUTO_STARTUP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[ENABLE_AUTO_STARTUP] ✅${NC} $1"
}

print_status "Re-enabling automatic startup service..."

# Re-enable the service
systemctl enable rec-io-simple-startup.service

print_success "Auto-startup service re-enabled"
print_status "System will now automatically start on boot"

echo ""
print_status "To verify: systemctl is-enabled rec-io-simple-startup.service"
print_status "To start now: systemctl start rec-io-simple-startup.service"

