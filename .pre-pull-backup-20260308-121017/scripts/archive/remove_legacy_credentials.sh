#!/bin/bash

# =============================================================================
# SECURE CREDENTIALS MIGRATION SCRIPT
# =============================================================================
# This script removes legacy credentials from the old location
# to ensure all credentials are ONLY stored in the secure user-based location
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEGACY_CREDS_DIR="$PROJECT_ROOT/backend/api/kalshi-api/kalshi-credentials"
SECURE_CREDS_DIR="$PROJECT_ROOT/backend/data/users/user_0001/credentials/kalshi-credentials"

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    SECURE CREDENTIALS MIGRATION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

print_status() {
    echo -e "${BLUE}[MIGRATION]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[MIGRATION] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[MIGRATION] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[MIGRATION] ❌${NC} $1"
}

print_header

print_status "Step 1: Verifying secure credentials location exists..."
if [ ! -d "$SECURE_CREDS_DIR" ]; then
    print_error "Secure credentials directory does not exist: $SECURE_CREDS_DIR"
    print_error "Please run the create_kalshi_credentials.py script first"
    exit 1
fi
print_success "Secure credentials directory verified"

print_status "Step 2: Checking for legacy credentials..."
if [ ! -d "$LEGACY_CREDS_DIR" ]; then
    print_success "No legacy credentials found - already cleaned up"
    exit 0
fi

print_warning "Found legacy credentials directory: $LEGACY_CREDS_DIR"

print_status "Step 3: Listing legacy credentials for verification..."
echo "Legacy credentials found:"
find "$LEGACY_CREDS_DIR" -type f -name "*.pem" -o -name "*.env" -o -name "*.txt" | while read file; do
    echo "  - $file"
done

print_status "Step 4: Verifying secure credentials exist..."
secure_files=$(find "$SECURE_CREDS_DIR" -type f -name "*.pem" -o -name "*.env" -o -name "*.txt" | wc -l)
if [ "$secure_files" -eq 0 ]; then
    print_error "No credentials found in secure location"
    print_error "Please create credentials in the secure location first"
    exit 1
fi
print_success "Secure credentials verified ($secure_files files found)"

print_status "Step 5: Confirming removal..."
echo -e "${YELLOW}WARNING: This will permanently delete legacy credentials${NC}"
echo -e "${YELLOW}Legacy location: $LEGACY_CREDS_DIR${NC}"
echo -e "${GREEN}Secure location: $SECURE_CREDS_DIR${NC}"
echo ""
read -p "Type 'DELETE' to confirm removal of legacy credentials: " confirm

if [ "$confirm" != "DELETE" ]; then
    print_error "Confirmation failed - aborting"
    exit 1
fi

print_status "Step 6: Removing legacy credentials..."
if rm -rf "$LEGACY_CREDS_DIR"; then
    print_success "Legacy credentials removed successfully"
else
    print_error "Failed to remove legacy credentials"
    exit 1
fi

print_status "Step 7: Verifying removal..."
if [ -d "$LEGACY_CREDS_DIR" ]; then
    print_error "Legacy credentials directory still exists"
    exit 1
fi
print_success "Legacy credentials directory verified as removed"

print_status "Step 8: Final security check..."
echo "Current credentials locations:"
echo "  ✅ Secure: $SECURE_CREDS_DIR"
echo "  ❌ Legacy: $LEGACY_CREDS_DIR (removed)"

print_success "Migration completed successfully!"
echo ""
echo -e "${GREEN}🔒 SECURITY STATUS:${NC}"
echo -e "${GREEN}✅ Credentials now stored ONLY in secure user-based location${NC}"
echo -e "${GREEN}✅ Legacy credentials location removed${NC}"
echo -e "${GREEN}✅ No fallback mechanisms exist${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "1. Verify all services are using secure credentials"
echo "2. Test trading functionality"
echo "3. Monitor logs for any credential-related errors"

print_header 