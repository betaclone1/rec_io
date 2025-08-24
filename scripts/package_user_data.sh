#!/bin/bash

# =============================================================================
# USER DATA PACKAGING SCRIPT
# =============================================================================
# This script packages user data (database and credentials) into a single file
# for easy transfer to a new machine during deployment.
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[PACKAGE]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[PACKAGE] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[PACKAGE] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[PACKAGE] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    USER DATA PACKAGING${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Create package directory
create_package_dir() {
    print_status "Creating package directory..." >&2
    
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    PACKAGE_DIR="$PROJECT_ROOT/backup/user_data_package_${TIMESTAMP}"
    mkdir -p "$PACKAGE_DIR"
    
    print_success "Package directory: $PACKAGE_DIR" >&2
    echo "$PACKAGE_DIR"
}

# Backup database
backup_database() {
    local package_dir="$1"
    print_status "Creating database backup (type: $BACKUP_TYPE)..."
    
    # Load environment variables
    if [ -f "$PROJECT_ROOT/.env" ]; then
        source "$PROJECT_ROOT/.env"
    fi
    
    # Set defaults
    export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
    export POSTGRES_PORT=${POSTGRES_PORT:-5432}
    export POSTGRES_DB=${POSTGRES_DB:-rec_io_db}
    export POSTGRES_USER=${POSTGRES_USER:-rec_io_user}
    export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-}
    export PGPASSWORD="rec_io_password"
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Create database backup based on type
    DB_BACKUP_FILE="$package_dir/database_backup.sql"
    
    if [[ "$BACKUP_TYPE" == "user" ]]; then
        # User data only - backup only the users schema
        if pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --create --schema=users > "$DB_BACKUP_FILE"; then
            print_success "User schema backup created: $DB_BACKUP_FILE"
        else
            print_error "User schema backup failed"
            return 1
        fi
    else
        # Full backup - entire database
        if pg_dump -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --create > "$DB_BACKUP_FILE"; then
            print_success "Full database backup created: $DB_BACKUP_FILE"
        else
            print_error "Full database backup failed"
            return 1
        fi
    fi
}

# Backup user credentials only
backup_user_data() {
    local package_dir="$1"
    print_status "Backing up user credentials..."
    
    # Create user data directory
    USER_DATA_DIR="$package_dir/user_data"
    mkdir -p "$USER_DATA_DIR"
    
    # Copy only credentials (no other user data needed)
    if [ -d "$PROJECT_ROOT/backend/data/users" ]; then
        # Create user data directory structure
        mkdir -p "$USER_DATA_DIR/users"
        
        # Copy only credentials for each user
        for user_dir in "$PROJECT_ROOT/backend/data/users"/*; do
            if [ -d "$user_dir" ]; then
                user_name=$(basename "$user_dir")
                mkdir -p "$USER_DATA_DIR/users/$user_name"
                
                # Copy only credentials directory (if exists)
                if [ -d "$user_dir/credentials" ]; then
                    cp -r "$user_dir/credentials" "$USER_DATA_DIR/users/$user_name/"
                    print_success "Credentials backed up for $user_name"
                else
                    print_warning "No credentials found for $user_name"
                fi
                
                # DO NOT copy: trade_history, accounts, active_trades, monitors, auth_tokens, device_tokens, or user_info.json
            fi
        done
    else
        print_warning "No user data found to backup"
    fi
    
    # Copy .env file if it exists
    if [ -f "$PROJECT_ROOT/.env" ]; then
        cp "$PROJECT_ROOT/.env" "$package_dir/"
        print_success "Environment file backed up"
    else
        print_warning "No .env file found"
    fi
}

# Create deployment instructions
create_instructions() {
    local package_dir="$1"
    print_status "Creating deployment instructions..."
    
    cat > "$package_dir/DEPLOYMENT_INSTRUCTIONS.md" << 'EOF'
# REC.IO User Data Package

This package contains your user data for deployment to a new machine.

## Contents
- `database_backup.sql` - Complete database with all your data
- `user_data/` - Your credentials only (all other data is in the database)
- `.env` - Environment configuration

## Important Note
**Only credentials are included in user_data.** All trade history, accounts, and other data is stored in the database and will be restored automatically.

## Deployment Instructions

### 1. Upload to New Server
```bash
# Upload this entire directory to your new server
scp -r user_data_package_YYYYMMDD_HHMMSS root@YOUR_SERVER_IP:/root/
```

### 2. Deploy on New Server
```bash
# SSH into your new server
ssh root@YOUR_SERVER_IP

# Run the one-command deployment
curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/scripts/one_click_deploy.sh | bash
```

### 3. When Prompted
- Choose "Existing User"
- Provide the path: `/root/user_data_package_YYYYMMDD_HHMMSS`

That's it! Your complete system will be restored with all your data.
EOF

    print_success "Deployment instructions created"
}

# Clean up old backup files (keep only 2 most recent)
cleanup_old_backups() {
    print_status "Cleaning up old backup files..."
    
    cd "$PROJECT_ROOT/backup"
    
    # Find all .tar.gz backup files, sort by modification time (newest first), keep only 2 most recent
    if ls user_data_package_*.tar.gz 1> /dev/null 2>&1; then
        # Get list of backup files sorted by modification time (newest first)
        BACKUP_FILES=$(ls -t user_data_package_*.tar.gz 2>/dev/null | head -n 2)
        ALL_BACKUP_FILES=$(ls user_data_package_*.tar.gz 2>/dev/null)
        
        # Count files to delete
        TOTAL_FILES=$(echo "$ALL_BACKUP_FILES" | wc -l)
        KEEP_FILES=$(echo "$BACKUP_FILES" | wc -l)
        DELETE_COUNT=$((TOTAL_FILES - KEEP_FILES))
        
        if [ $DELETE_COUNT -gt 0 ]; then
            # Delete files not in the keep list
            for file in $ALL_BACKUP_FILES; do
                if ! echo "$BACKUP_FILES" | grep -q "$file"; then
                    rm -f "$file"
                    print_status "Deleted old backup: $file"
                fi
            done
            print_success "Kept $KEEP_FILES most recent backup files, deleted $DELETE_COUNT old files"
        else
            print_status "No old backup files to delete"
        fi
    else
        print_status "No existing backup files found"
    fi
}

# Create compressed package
create_compressed_package() {
    local package_dir="$1"
    print_status "Creating compressed package..."
    
    cd "$PROJECT_ROOT/backup"
    PACKAGE_NAME=$(basename "$package_dir")
    
    if tar -czf "${PACKAGE_NAME}.tar.gz" "$PACKAGE_NAME"; then
        print_success "Compressed package created: ${PACKAGE_NAME}.tar.gz"
        rm -rf "$PACKAGE_NAME"
        print_status "File size: $(du -h "${PACKAGE_NAME}.tar.gz" | cut -f1)"
        
        # Clean up old backups after creating new one
        cleanup_old_backups
    else
        print_error "Failed to create compressed package"
        return 1
    fi
}

# Main packaging function
package_user_data() {
    print_header
    print_status "Creating user data package..."
    echo ""
    
    # Create package directory
    PACKAGE_DIR=$(create_package_dir)
    
    # Create package contents
    backup_database "$PACKAGE_DIR"
    backup_user_data "$PACKAGE_DIR"
    create_instructions "$PACKAGE_DIR"
    create_compressed_package "$PACKAGE_DIR"
    
    echo ""
    print_success "User data package created successfully!"
    print_status "Package location: $PACKAGE_DIR"
    print_status "Compressed package: ${PACKAGE_DIR}.tar.gz"
    echo ""
    print_status "To deploy to a new server:"
    print_status "  1. Upload: scp -r $PACKAGE_DIR root@YOUR_SERVER:/root/"
    print_status "  2. Deploy: curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/scripts/one_click_deploy.sh | bash"
}

# Help function
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Package user data for deployment to a new machine."
    echo ""
    echo "This script will create:"
    echo "  - Database backup (user schema or full database)"
    echo "  - User credentials backup"
    echo "  - Environment configuration"
    echo "  - Deployment instructions"
    echo "  - Compressed package"
    echo ""
    echo "Options:"
    echo "  --type TYPE     Backup type: 'user' (users schema only) or 'full' (entire database)"
    echo "  --help, -h      Show this help message"
}

# Parse command line arguments
BACKUP_TYPE="full"  # Default to full backup

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --type)
            if [[ $# -lt 2 ]]; then
                print_error "Missing value for --type option"
                exit 1
            fi
            BACKUP_TYPE="$2"
            shift 2
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Validate backup type
if [[ "$BACKUP_TYPE" != "user" && "$BACKUP_TYPE" != "full" ]]; then
    print_error "Invalid backup type: $BACKUP_TYPE. Must be 'user' or 'full'"
    exit 1
fi

# Main execution
package_user_data
