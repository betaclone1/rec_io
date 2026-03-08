#!/bin/bash

# =============================================================================
# PRODUCTION DATABASE RESTORE SCRIPT
# =============================================================================
# This script restores the local PostgreSQL database from a production backup
# WARNING: This will completely overwrite your local database
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

# Database configuration (can be overridden by environment variables)
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-rec_io_db}"
DB_USER="${DB_USER:-rec_io_user}"
DB_PASSWORD="${DB_PASSWORD:-rec_io_password}"

# Default backup file path
BACKUP_FILE="${1:-/Users/ericwais1/rec_io_local/2_5/backup/user_data_package_20251112_180232.tar.gz}"

print_status "Production Database Restore Script"
echo ""
print_warning "This will COMPLETELY OVERWRITE your local database: $DB_NAME"
print_warning "All current local data will be lost!"
echo ""

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    print_error "Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Extract database backup if it's a tar.gz file
TEMP_DIR="/tmp/db_restore_$$"
mkdir -p "$TEMP_DIR"

if [[ "$BACKUP_FILE" == *.tar.gz ]]; then
    print_status "Extracting backup archive..."
    tar -xzf "$BACKUP_FILE" -C "$TEMP_DIR"
    SQL_FILE=$(find "$TEMP_DIR" -name "database_backup.sql" -type f | head -1)
    if [ -z "$SQL_FILE" ]; then
        print_error "Could not find database_backup.sql in archive"
        rm -rf "$TEMP_DIR"
        exit 1
    fi
else
    SQL_FILE="$BACKUP_FILE"
fi

if [ ! -f "$SQL_FILE" ]; then
    print_error "SQL backup file not found: $SQL_FILE"
    rm -rf "$TEMP_DIR"
    exit 1
fi

print_success "Found SQL backup file: $SQL_FILE ($(du -h "$SQL_FILE" | cut -f1))"
echo ""

# Check PostgreSQL connection
print_status "Checking PostgreSQL connection..."
export PGPASSWORD="$DB_PASSWORD"
if ! psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -c "SELECT 1;" > /dev/null 2>&1; then
    print_error "Cannot connect to PostgreSQL"
    print_status "Please verify your database credentials:"
    print_status "  Host: $DB_HOST"
    print_status "  Port: $DB_PORT"
    print_status "  User: $DB_USER"
    print_status "  Database: postgres"
    rm -rf "$TEMP_DIR"
    exit 1
fi
print_success "PostgreSQL connection verified"
echo ""

# Warn about active connections
print_status "Checking for active connections to $DB_NAME..."
ACTIVE_CONNS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -t -c "SELECT count(*) FROM pg_stat_activity WHERE datname = '$DB_NAME';" 2>/dev/null | tr -d ' ')
if [ "$ACTIVE_CONNS" -gt 0 ]; then
    print_warning "Found $ACTIVE_CONNS active connection(s) to $DB_NAME"
    print_warning "These connections will be terminated during restore"
    echo ""
fi

# Confirm before proceeding
read -p "Are you sure you want to proceed? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    print_status "Restore cancelled"
    rm -rf "$TEMP_DIR"
    exit 0
fi

echo ""
print_status "Starting database restore..."
print_status "This may take several minutes for large databases..."

# Restore the database
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres -f "$SQL_FILE" > /tmp/db_restore.log 2>&1; then
    print_success "Database restored successfully!"
    print_status "Restore log saved to: /tmp/db_restore.log"
else
    print_error "Database restore failed"
    print_status "Check the log file for details: /tmp/db_restore.log"
    print_status "Last 20 lines of error log:"
    tail -20 /tmp/db_restore.log
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Verify restore
echo ""
print_status "Verifying database restore..."
TABLE_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema');" 2>/dev/null | tr -d ' ')
if [ "$TABLE_COUNT" -gt 0 ]; then
    print_success "Database verification successful: $TABLE_COUNT tables found"
else
    print_warning "Database verification: No tables found (this may be normal if the backup was empty)"
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
print_success "Database restore completed!"
print_status "Your local database now matches the production backup"

