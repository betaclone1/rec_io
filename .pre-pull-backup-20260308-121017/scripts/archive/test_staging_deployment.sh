#!/bin/bash

# STAGING ENVIRONMENT TEST SCRIPT
# This script tests the PostgreSQL migration in a staging environment

set -e  # Exit on any error

echo "🧪 STAGING ENVIRONMENT TEST"
echo "==========================="
echo ""

# Configuration
STAGING_DIR="/tmp/postgresql_migration_staging_$(date +%Y%m%d_%H%M%S)"
TEST_LOG="/tmp/staging_test_$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$TEST_LOG"
}

success() {
    echo -e "${GREEN}✅ $1${NC}" | tee -a "$TEST_LOG"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}" | tee -a "$TEST_LOG"
}

error() {
    echo -e "${RED}❌ $1${NC}" | tee -a "$TEST_LOG"
}

# Function to setup staging environment
setup_staging() {
    log "Setting up staging environment..."
    
    mkdir -p "$STAGING_DIR"
    cd "$STAGING_DIR"
    
    # Copy current project to staging
    cp -r /Users/ericwais1/rec_io_20/* .
    
    # Create staging-specific configuration
    cat > staging.env << EOF
DATABASE_TYPE=postgresql
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db_staging
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=
EOF
    
    success "Staging environment setup: $STAGING_DIR"
}

# Function to create staging database
create_staging_database() {
    log "Creating staging PostgreSQL database..."
    
    # Create staging database
    psql -h localhost -U rec_io_user -d postgres -c "CREATE DATABASE rec_io_db_staging;" 2>/dev/null || warning "Database may already exist"
    
    # Test connection to staging database
    if psql -h localhost -U rec_io_user -d rec_io_db_staging -c "SELECT 1;" >/dev/null 2>&1; then
        success "Staging database created and accessible"
    else
        error "Failed to create staging database"
        return 1
    fi
}

# Function to test database abstraction layer in staging
test_staging_database() {
    log "Testing database abstraction layer in staging..."
    
    cd "$STAGING_DIR"
    
    # Set staging environment
    export DATABASE_TYPE=postgresql
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=5432
    export POSTGRES_DB=rec_io_db_staging
    export POSTGRES_USER=rec_io_user
    export POSTGRES_PASSWORD=""
    
    # Test database abstraction layer
    if python3 -c "
import sys
sys.path.insert(0, '.')
from backend.core.database import test_database_connection
test_database_connection()
" >/dev/null 2>&1; then
        success "Database abstraction layer test passed in staging"
    else
        error "Database abstraction layer test failed in staging"
        return 1
    fi
}

# Function to test service startup in staging
test_service_startup() {
    log "Testing service startup in staging..."
    
    cd "$STAGING_DIR"
    
    # Test active trade supervisor startup with proper Python path
    PYTHONPATH="$STAGING_DIR" python3 backend/active_trade_supervisor_v2.py &
    SUPERVISOR_PID=$!
    
    sleep 5
    
    # Check if service started
    if kill -0 $SUPERVISOR_PID 2>/dev/null; then
        success "Active trade supervisor started in staging"
        kill $SUPERVISOR_PID
    else
        error "Active trade supervisor failed to start in staging"
        return 1
    fi
}

# Function to test integration in staging
test_staging_integration() {
    log "Testing integration in staging environment..."
    
    cd "$STAGING_DIR"
    
    # Set staging environment
    export DATABASE_TYPE=postgresql
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=5432
    export POSTGRES_DB=rec_io_db_staging
    export POSTGRES_USER=rec_io_user
    export POSTGRES_PASSWORD=""
    
    # Run integration tests with proper Python path
    PYTHONPATH="$STAGING_DIR" python3 tests/test_system_integration.py >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        success "Integration tests passed in staging"
    else
        error "Integration tests failed in staging"
        return 1
    fi
}

# Function to test rollback in staging
test_staging_rollback() {
    log "Testing rollback functionality in staging..."
    
    cd "$STAGING_DIR"
    
    # Switch back to SQLite
    export DATABASE_TYPE=sqlite
    
    # Test that services can start with SQLite
    if python3 -c "
import sys
sys.path.insert(0, '.')
from backend.core.database import test_database_connection
test_database_connection()
" >/dev/null 2>&1; then
        success "Rollback to SQLite test passed"
    else
        error "Rollback to SQLite test failed"
        return 1
    fi
}

# Function to cleanup staging environment
cleanup_staging() {
    log "Cleaning up staging environment..."
    
    # Drop staging database
    psql -h localhost -U rec_io_user -d postgres -c "DROP DATABASE IF EXISTS rec_io_db_staging;" >/dev/null 2>&1
    
    # Remove staging directory
    rm -rf "$STAGING_DIR"
    
    success "Staging environment cleaned up"
}

# Function to run full staging test
run_staging_test() {
    log "Starting full staging environment test..."
    
    # Step 1: Setup staging environment
    log "Step 1: Setting up staging environment"
    setup_staging
    
    # Step 2: Create staging database
    log "Step 2: Creating staging database"
    create_staging_database || {
        error "Staging database creation failed"
        cleanup_staging
        exit 1
    }
    
    # Step 3: Test database abstraction layer
    log "Step 3: Testing database abstraction layer"
    test_staging_database || {
        error "Database abstraction layer test failed"
        cleanup_staging
        exit 1
    }
    
    # Step 4: Test service startup
    log "Step 4: Testing service startup"
    test_service_startup || {
        error "Service startup test failed"
        cleanup_staging
        exit 1
    }
    
    # Step 5: Test integration
    log "Step 5: Testing integration"
    test_staging_integration || {
        error "Integration test failed"
        cleanup_staging
        exit 1
    }
    
    # Step 6: Test rollback
    log "Step 6: Testing rollback functionality"
    test_staging_rollback || {
        error "Rollback test failed"
        cleanup_staging
        exit 1
    }
    
    # Step 7: Cleanup
    log "Step 7: Cleaning up staging environment"
    cleanup_staging
    
    # Final success
    success "Staging environment test completed successfully!"
    log "Test log: $TEST_LOG"
    
    echo ""
    echo "🎉 STAGING TEST SUCCESSFUL!"
    echo "============================"
    echo "✅ Staging environment setup"
    echo "✅ Database creation and connectivity"
    echo "✅ Service startup and operation"
    echo "✅ Integration testing"
    echo "✅ Rollback functionality"
    echo "✅ Environment cleanup"
    echo ""
    echo "📋 Test log: $TEST_LOG"
    echo ""
    echo "✅ READY FOR PRODUCTION DEPLOYMENT"
}

# Handle command line arguments
case "${1:-test}" in
    "test")
        run_staging_test
        ;;
    "setup")
        setup_staging
        ;;
    "cleanup")
        cleanup_staging
        ;;
    "database")
        create_staging_database
        test_staging_database
        ;;
    "integration")
        setup_staging
        create_staging_database
        test_staging_integration
        cleanup_staging
        ;;
    *)
        echo "Usage: $0 {test|setup|cleanup|database|integration}"
        echo ""
        echo "Commands:"
        echo "  test       - Run full staging environment test (default)"
        echo "  setup      - Setup staging environment only"
        echo "  cleanup    - Cleanup staging environment only"
        echo "  database   - Test database creation and connectivity"
        echo "  integration - Test integration in staging environment"
        exit 1
        ;;
esac 