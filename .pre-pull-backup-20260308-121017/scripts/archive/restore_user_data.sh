#!/bin/bash

# =============================================================================
# USER DATA RESTORATION SCRIPT
# =============================================================================
# This script restores user data after the initial deployment is complete.
# Run this after the one-click deployment script finishes.
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
    echo -e "${BLUE}[RESTORE]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[RESTORE] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[RESTORE] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[RESTORE] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    USER DATA RESTORATION${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root"
        print_status "Please run: sudo $0"
        exit 1
    fi
}

# Restore existing data
restore_existing_data() {
    print_status "Restoring existing user data..."
    
    echo ""
    print_status "Please provide the path to your data package:"
    print_status "Options:"
    print_status "  - Full path to package directory (e.g., /root/user_data_package_20250101_120000)"
    print_status "  - Full path to compressed package (e.g., /root/user_data_package_20250101_120000.tar.gz)"
    echo ""
    read -p "Enter package path: " package_path
    
    if [ ! -e "$package_path" ]; then
        print_error "Package path not found: $package_path"
        exit 1
    fi
    
    cd /opt/rec_io
    
    # Handle compressed package
    if [[ "$package_path" == *.tar.gz ]]; then
        print_status "Extracting compressed package..."
        tar -xzf "$package_path" -C /tmp/
        package_dir=$(find /tmp -name "user_data_package_*" -type d | head -1)
        if [ -z "$package_dir" ]; then
            print_error "Could not find package directory in compressed file"
            exit 1
        fi
    else
        package_dir="$package_path"
    fi
    
    # Restore database
    if [ -f "$package_dir/database_backup.sql" ]; then
        print_status "Restoring database..."
        if psql -h localhost -U rec_io_user -d postgres < "$package_dir/database_backup.sql"; then
            print_success "Database restored successfully"
        else
            print_error "Database restoration failed"
            exit 1
        fi
    else
        print_warning "No database backup found"
    fi
    
    # Restore user data (excluding credentials and personal info)
    if [ -d "$package_dir/user_data" ]; then
        print_status "Restoring user data (excluding credentials)..."
        mkdir -p backend/data
        
        # Restore only non-sensitive user data
        if [ -d "$package_dir/user_data/users" ]; then
            for user_dir in "$package_dir/user_data/users"/*; do
                if [ -d "$user_dir" ]; then
                    user_name=$(basename "$user_dir")
                    mkdir -p "backend/data/users/$user_name"
                    
                    # Restore trade history, accounts, active trades, monitors
                    for subdir in trade_history accounts active_trades monitors; do
                        if [ -d "$user_dir/$subdir" ]; then
                            cp -r "$user_dir/$subdir" "backend/data/users/$user_name/"
                        fi
                    done
                fi
            done
        fi
        
        print_success "User data restored (credentials excluded - must be added manually)"
    else
        print_warning "No user data found"
    fi
    
    # Restore .env file
    if [ -f "$package_dir/.env" ]; then
        print_status "Restoring environment configuration..."
        cp "$package_dir/.env" .
        print_success "Environment configuration restored"
    else
        print_warning "No .env file found"
    fi
    
    # Clean up
    if [[ "$package_path" == *.tar.gz ]]; then
        rm -rf "$package_dir"
    fi
    
    # Set up database schema (in case it's missing)
    print_status "Verifying database schema..."
    if [ -f "scripts/setup_database.sh" ]; then
        ./scripts/setup_database.sh
    else
        print_warning "Database setup script not found, schema may need manual setup"
    fi
    
    print_success "Existing data restored successfully"
    print_status "Database schema verified"
}

# Main execution
main() {
    print_header
    print_status "Starting user data restoration..."
    echo ""

    check_root
    restore_existing_data
    
    echo ""
    print_success "User data restoration completed!"
    print_status "You can now start the system with: ./scripts/MASTER_RESTART.sh"
}

# Main execution
main
