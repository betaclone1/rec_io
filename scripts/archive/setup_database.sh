#!/bin/bash

# =============================================================================
# DATABASE SETUP SCRIPT
# =============================================================================
# This script sets up the PostgreSQL database for the REC.IO trading system.
# It handles database creation, user setup, and initial configuration.
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
    echo -e "${BLUE}[DB_SETUP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[DB_SETUP] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[DB_SETUP] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[DB_SETUP] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    DATABASE SETUP SCRIPT${NC}"
    echo -e "${PURPLE}=============================================================================${NC}"
}

# Load environment variables
load_env() {
    print_status "Loading environment variables..."
    
    # Check for .env file
    if [ -f "$PROJECT_ROOT/.env" ]; then
        source "$PROJECT_ROOT/.env"
        print_success "Loaded .env file"
    elif [ -f "$PROJECT_ROOT/backend/util/.env" ]; then
        source "$PROJECT_ROOT/backend/util/.env"
        print_success "Loaded backend/util/.env file"
    else
        print_warning "No .env file found, using defaults"
    fi
    
    # Set defaults if not provided
    export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
    export POSTGRES_PORT=${POSTGRES_PORT:-5432}
    export POSTGRES_DB=${POSTGRES_DB:-rec_io_db}
    export POSTGRES_USER=${POSTGRES_USER:-rec_io_user}
    export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-}
    
    print_status "Database configuration:"
    print_status "  Host: $POSTGRES_HOST"
    print_status "  Port: $POSTGRES_PORT"
    print_status "  Database: $POSTGRES_DB"
    print_status "  User: $POSTGRES_USER"
}

# Check PostgreSQL installation
check_postgresql() {
    print_status "Checking PostgreSQL installation..."
    
    if ! command -v psql &> /dev/null; then
        print_error "PostgreSQL client (psql) not found"
        echo "Please install PostgreSQL client tools:"
        echo "  macOS: brew install postgresql"
        echo "  Ubuntu: sudo apt-get install postgresql-client"
        echo "  CentOS: sudo yum install postgresql"
        exit 1
    fi
    
    print_success "PostgreSQL client found"
}

# Test database connection
test_connection() {
    print_status "Testing database connection..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1;" >/dev/null 2>&1; then
        print_success "Database connection successful"
        return 0
    else
        print_warning "Database connection failed"
        return 1
    fi
}

# Create database if it doesn't exist
create_database() {
    print_status "Creating database if it doesn't exist..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Try to connect to postgres database to create our database
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE \"$POSTGRES_DB\";" >/dev/null 2>&1; then
        print_success "Database '$POSTGRES_DB' created"
    else
        print_warning "Database '$POSTGRES_DB' may already exist or creation failed"
    fi
}

# Create user if it doesn't exist
create_user() {
    print_status "Creating database user if it doesn't exist..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Try to create user (will fail if user already exists, which is fine)
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c "CREATE USER \"$POSTGRES_USER\" WITH PASSWORD '$POSTGRES_PASSWORD';" >/dev/null 2>&1; then
        print_success "User '$POSTGRES_USER' created"
    else
        print_warning "User '$POSTGRES_USER' may already exist or creation failed"
    fi
    
    # Grant privileges
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE \"$POSTGRES_DB\" TO \"$POSTGRES_USER\";" >/dev/null 2>&1; then
        print_success "Privileges granted to '$POSTGRES_USER'"
    else
        print_warning "Privilege grant may have failed"
    fi
}

# Verify database schema
verify_schema() {
    print_status "Verifying database schema..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Check if live_data schema exists
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'live_data';" | grep -q live_data; then
        print_success "live_data schema exists"
    else
        print_warning "live_data schema not found - may need to run migrations"
    fi
    
    # Check if btc_price_log table exists
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'btc_price_log';" | grep -q btc_price_log; then
        print_success "btc_price_log table exists"
    else
        print_warning "btc_price_log table not found - may need to run migrations"
    fi
}

# Create .env file if it doesn't exist
create_env_file() {
    print_status "Creating .env file if it doesn't exist..."
    
    ENV_FILE="$PROJECT_ROOT/.env"
    if [ ! -f "$ENV_FILE" ]; then
        cat > "$ENV_FILE" << EOF
# PostgreSQL Connection Settings
# Generated by setup_database.sh

POSTGRES_HOST=$POSTGRES_HOST
POSTGRES_PORT=$POSTGRES_PORT
POSTGRES_DB=$POSTGRES_DB
POSTGRES_USER=$POSTGRES_USER
POSTGRES_PASSWORD=$POSTGRES_PASSWORD

# Trading System Configuration
TRADING_SYSTEM_HOST=localhost
REC_BIND_HOST=localhost
REC_TARGET_HOST=localhost
EOF
        print_success "Created .env file at $ENV_FILE"
    else
        print_warning ".env file already exists, not overwriting"
    fi
}

# Main setup function
setup_database() {
    print_header
    print_status "Setting up database for REC.IO trading system..."
    echo ""
    
    load_env
    check_postgresql
    
    # Try to create user and database
    create_user
    create_database
    
    # Test connection
    if test_connection; then
        verify_schema
        create_env_file
        
        echo ""
        print_success "Database setup completed successfully!"
        print_status "You can now start the trading system."
    else
        echo ""
        print_error "Database setup failed"
        print_status "Please check your PostgreSQL installation and credentials."
        print_status "You may need to:"
        print_status "  1. Install PostgreSQL"
        print_status "  2. Start PostgreSQL service"
        print_status "  3. Create database and user manually"
        print_status "  4. Update .env file with correct credentials"
        exit 1
    fi
}

# Help function
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Set up the PostgreSQL database for the REC.IO trading system."
    echo ""
    echo "Options:"
    echo "  --help, -h     Show this help message"
    echo "  --test-only    Only test connection, don't create anything"
    echo ""
    echo "This script will:"
    echo "  - Load environment variables from .env file"
    echo "  - Check PostgreSQL installation"
    echo "  - Create database user if needed"
    echo "  - Create database if needed"
    echo "  - Test database connection"
    echo "  - Verify database schema"
    echo "  - Create .env file if it doesn't exist"
    echo ""
    echo "Environment variables (can be set in .env file):"
    echo "  POSTGRES_HOST     Database host (default: localhost)"
    echo "  POSTGRES_PORT     Database port (default: 5432)"
    echo "  POSTGRES_DB       Database name (default: rec_io_db)"
    echo "  POSTGRES_USER     Database user (default: rec_io_user)"
    echo "  POSTGRES_PASSWORD Database password (default: empty)"
}

# Parse command line arguments
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --test-only)
            TEST_ONLY=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Main execution
if [ "$TEST_ONLY" = true ]; then
    print_header
    load_env
    check_postgresql
    if test_connection; then
        print_success "Database connection test passed"
    else
        print_error "Database connection test failed"
        exit 1
    fi
else
    setup_database
fi
