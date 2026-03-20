#!/bin/bash

# =============================================================================
# USER DATA MIGRATION SCRIPT
# =============================================================================
# 
# This script migrates user-specific data from one environment to another,
# including credentials, databases, preferences, and state files.
#
# USAGE:
#   ./scripts/migrate_user_data.sh SOURCE_DIR
#   ./scripts/migrate_user_data.sh /path/to/user_data
#
# PREREQUISITES:
# - Source directory contains valid user data
# - Trading system service is running
# - Sufficient disk space for migration
# =============================================================================

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TARGET_DIR="/opt/trading_system/user_data"
LOG_FILE="$PROJECT_DIR/logs/user_data_migration.log"

# Default values
SOURCE_DIR=""
DRY_RUN=false
FORCE_MIGRATION=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE_MIGRATION=true
            shift
            ;;
        --help)
            echo "Usage: $0 SOURCE_DIR [--dry-run] [--force]"
            echo ""
            echo "Arguments:"
            echo "  SOURCE_DIR    Source directory containing user data"
            echo ""
            echo "Options:"
            echo "  --dry-run     Show what would be migrated without doing it"
            echo "  --force       Force migration even if target exists"
            exit 0
            ;;
        *)
            if [[ -z "$SOURCE_DIR" ]]; then
                SOURCE_DIR="$1"
            else
                echo "Error: Multiple source directories specified"
                exit 1
            fi
            shift
            ;;
    esac
done

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (use sudo)"
    fi
}

# Validate source directory
validate_source() {
    if [[ -z "$SOURCE_DIR" ]]; then
        error "Source directory is required. Use: $0 SOURCE_DIR"
    fi
    
    if [[ ! -d "$SOURCE_DIR" ]]; then
        error "Source directory not found: $SOURCE_DIR"
    fi
    
    # Check if source contains user data structure
    if [[ ! -d "$SOURCE_DIR/credentials" ]] && [[ ! -d "$SOURCE_DIR/databases" ]] && [[ ! -d "$SOURCE_DIR/preferences" ]]; then
        warning "Source directory may not contain valid user data structure"
        if [[ "$FORCE_MIGRATION" != "true" ]]; then
            error "Use --force to proceed anyway"
        fi
    fi
    
    log "Source directory validated: $SOURCE_DIR"
}

# Check target directory
check_target() {
    if [[ -d "$TARGET_DIR" ]] && [[ "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]]; then
        warning "Target directory already contains data: $TARGET_DIR"
        
        if [[ "$FORCE_MIGRATION" != "true" ]]; then
            echo "Existing data will be overwritten. Use --force to proceed."
            read -p "Continue? (y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                error "Migration cancelled by user"
            fi
        fi
    fi
    
    log "Target directory ready: $TARGET_DIR"
}

# Create target directory structure
create_target_structure() {
    log "Creating target directory structure..."
    
    mkdir -p "$TARGET_DIR"/{credentials,databases,preferences,state}
    mkdir -p "$TARGET_DIR"/credentials/kalshi/{demo,prod}
    mkdir -p "$TARGET_DIR"/databases/{accounts,trade_history,price_history}
    mkdir -p "$TARGET_DIR"/preferences/{trading,system,ui}
    
    # Set permissions
    chmod 700 "$TARGET_DIR"
    chown -R trading_user:trading_user "$TARGET_DIR" 2>/dev/null || true
    
    log "Target directory structure created"
}

# Stop trading system services
stop_services() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY RUN] Would stop trading system services"
        return
    fi
    
    log "Stopping trading system services..."
    
    # Stop systemd service
    if systemctl is-active --quiet trading_system.service; then
        systemctl stop trading_system.service
        log "Trading system service stopped"
    else
        log "Trading system service not running"
    fi
    
    # Stop supervisor services
    if command -v supervisorctl >/dev/null 2>&1; then
        supervisorctl -c /opt/trading_system/backend/supervisord.conf shutdown 2>/dev/null || true
        log "Supervisor services stopped"
    fi
}

# Backup existing user data
backup_existing() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY RUN] Would backup existing user data"
        return
    fi
    
    if [[ -d "$TARGET_DIR" ]] && [[ "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]]; then
        log "Creating backup of existing user data..."
        
        BACKUP_NAME="user_data_backup_$(date +%Y%m%d_%H%M%S)"
        BACKUP_DIR="/opt/backups/$BACKUP_NAME"
        
        mkdir -p "$BACKUP_DIR"
        cp -r "$TARGET_DIR"/* "$BACKUP_DIR/"
        
        cd /opt/backups
        tar -czf "$BACKUP_NAME.tar.gz" "$BACKUP_NAME"
        rm -rf "$BACKUP_NAME"
        
        log "Existing user data backed up to: /opt/backups/$BACKUP_NAME.tar.gz"
    fi
}

# Migrate user data
migrate_user_data() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY RUN] Would migrate user data from $SOURCE_DIR to $TARGET_DIR"
        log "[DRY RUN] Files to migrate:"
        find "$SOURCE_DIR" -type f 2>/dev/null | head -10
        return
    fi
    
    log "Migrating user data..."
    
    # Copy user data with preservation of structure
    cp -r "$SOURCE_DIR"/* "$TARGET_DIR/"
    
    # Set proper permissions
    chown -R trading_user:trading_user "$TARGET_DIR"
    chmod -R 700 "$TARGET_DIR"
    
    # Set specific permissions for credentials
    find "$TARGET_DIR/credentials" -type f -name "*.pem" -exec chmod 600 {} \; 2>/dev/null || true
    find "$TARGET_DIR/credentials" -type f -name "*.txt" -exec chmod 600 {} \; 2>/dev/null || true
    
    # Set specific permissions for databases
    find "$TARGET_DIR/databases" -type f -name "*.db" -exec chmod 600 {} \; 2>/dev/null || true
    
    log "User data migration completed"
}

# Verify migration
verify_migration() {
    log "Verifying migration..."
    
    # Check if target directory has content
    if [[ ! -d "$TARGET_DIR" ]] || [[ -z "$(ls -A "$TARGET_DIR" 2>/dev/null)" ]]; then
        error "Migration failed: Target directory is empty or missing"
    fi
    
    # Check for key directories
    local missing_dirs=()
    for dir in credentials databases preferences state; do
        if [[ ! -d "$TARGET_DIR/$dir" ]]; then
            missing_dirs+=("$dir")
        fi
    done
    
    if [[ ${#missing_dirs[@]} -gt 0 ]]; then
        warning "Missing directories: ${missing_dirs[*]}"
    fi
    
    # Check file permissions
    local permission_issues=()
    if [[ -d "$TARGET_DIR/credentials" ]]; then
        find "$TARGET_DIR/credentials" -type f -perm /022 2>/dev/null | while read -r file; do
            permission_issues+=("$file")
        done
    fi
    
    if [[ ${#permission_issues[@]} -gt 0 ]]; then
        warning "Files with loose permissions: ${permission_issues[*]}"
    fi
    
    log "Migration verification completed"
}

# Start trading system services
start_services() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log "[DRY RUN] Would start trading system services"
        return
    fi
    
    log "Starting trading system services..."
    
    # Start systemd service
    systemctl start trading_system.service
    log "Trading system service started"
    
    # Wait for services to be ready
    sleep 5
    
    # Check service status
    if systemctl is-active --quiet trading_system.service; then
        log "Trading system service is running"
    else
        error "Trading system service failed to start"
    fi
}

# Create migration report
create_migration_report() {
    REPORT_FILE="$PROJECT_DIR/logs/migration_report_$(date +%Y%m%d_%H%M%S).txt"
    
    log "Creating migration report: $REPORT_FILE"
    
    cat > "$REPORT_FILE" << EOF
# User Data Migration Report
# Created: $(date)
# Source: $SOURCE_DIR
# Target: $TARGET_DIR

## Migration Summary
- Source Directory: $SOURCE_DIR
- Target Directory: $TARGET_DIR
- Migration Date: $(date)
- Dry Run: $DRY_RUN

## Target Directory Contents
$(find "$TARGET_DIR" -type f 2>/dev/null | sort || echo "No files found")

## File Sizes
$(du -sh "$TARGET_DIR"/* 2>/dev/null || echo "No files found")

## Permissions
$(ls -la "$TARGET_DIR" 2>/dev/null || echo "No files found")

## Service Status
$(systemctl status trading_system.service --no-pager 2>/dev/null || echo "Service status unavailable")

## System Information
- Hostname: $(hostname)
- Date: $(date)
- User: $(whoami)
- Disk Usage: $(df -h "$TARGET_DIR" | tail -1)
EOF
    
    log "Migration report created: $REPORT_FILE"
}

# Main migration function
main() {
    log "=== USER DATA MIGRATION STARTED ==="
    
    # Check prerequisites
    check_root
    validate_source
    check_target
    
    # Create logs directory
    mkdir -p "$(dirname "$LOG_FILE")"
    
    # Perform migration
    create_target_structure
    stop_services
    backup_existing
    migrate_user_data
    verify_migration
    start_services
    create_migration_report
    
    log "=== USER DATA MIGRATION COMPLETE ==="
    
    # Summary
    echo ""
    echo "✅ Migration completed successfully!"
    echo "📁 Source: $SOURCE_DIR"
    echo "📁 Target: $TARGET_DIR"
    echo "📋 Report: $REPORT_FILE"
    echo ""
    echo "To verify the migration:"
    echo "  supervisorctl -c /opt/trading_system/backend/supervisord.conf status"
    echo "  systemctl status trading_system.service"
}

# Run main function
main "$@" 