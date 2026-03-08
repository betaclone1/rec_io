#!/bin/bash

# =============================================================================
# DATABASE TESTING SCRIPT
# =============================================================================
# This script tests database connectivity and functionality for the REC.IO trading system.
# It validates that all database operations work correctly.
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
    echo -e "${BLUE}[DB_TEST]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[DB_TEST] ✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[DB_TEST] ⚠️${NC} $1"
}

print_error() {
    echo -e "${RED}[DB_TEST] ❌${NC} $1"
}

print_header() {
    echo -e "${PURPLE}=============================================================================${NC}"
    echo -e "${PURPLE}                    DATABASE TESTING SCRIPT${NC}"
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

# Test basic connectivity
test_connectivity() {
    print_status "Testing basic database connectivity..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1 as test;" >/dev/null 2>&1; then
        print_success "Basic connectivity test passed"
        return 0
    else
        print_error "Basic connectivity test failed"
        return 1
    fi
}

# Test schema existence
test_schema() {
    print_status "Testing database schema..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Check if live_data schema exists
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'live_data';" | grep -q live_data; then
        print_success "live_data schema exists"
    else
        print_warning "live_data schema not found"
        return 1
    fi
    
    # Check if btc_price_log table exists
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'live_data' AND table_name = 'btc_price_log';" | grep -q btc_price_log; then
        print_success "btc_price_log table exists"
    else
        print_warning "btc_price_log table not found"
        return 1
    fi
    
    return 0
}

# Test table structure
test_table_structure() {
    print_status "Testing table structure..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Get column information for btc_price_log table
    COLUMNS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'live_data' AND table_name = 'btc_price_log' ORDER BY ordinal_position;" 2>/dev/null || echo "")
    
    if [ -n "$COLUMNS" ]; then
        print_success "btc_price_log table structure:"
        echo "$COLUMNS" | while read -r line; do
            if [ -n "$line" ]; then
                echo "    $line"
            fi
        done
    else
        print_warning "Could not retrieve table structure"
        return 1
    fi
    
    return 0
}

# Test data access
test_data_access() {
    print_status "Testing data access..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Test reading from btc_price_log table
    ROW_COUNT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM live_data.live_price_log_1s_btc;" 2>/dev/null | tr -d ' ')
    
    if [ -n "$ROW_COUNT" ] && [ "$ROW_COUNT" -ge 0 ]; then
        print_success "Data access test passed - $ROW_COUNT rows in btc_price_log"
        
        # Test reading latest record
        LATEST_RECORD=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT timestamp, price, momentum FROM live_data.live_price_log_1s_btc ORDER BY timestamp DESC LIMIT 1;" 2>/dev/null | head -1)
        
        if [ -n "$LATEST_RECORD" ]; then
            print_success "Latest record access test passed"
        else
            print_warning "No recent records found in btc_price_log"
        fi
    else
        print_warning "Data access test failed or table is empty"
        return 1
    fi
    
    return 0
}

# Test write operations
test_write_operations() {
    print_status "Testing write operations..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Create a test table for write operations
    TEST_TABLE="live_data.db_test_$(date +%s)"
    
    # Create test table
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE TABLE $TEST_TABLE (id SERIAL PRIMARY KEY, test_data TEXT, created_at TIMESTAMP DEFAULT NOW());" >/dev/null 2>&1; then
        print_success "Test table created: $TEST_TABLE"
        
        # Insert test data
        if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "INSERT INTO $TEST_TABLE (test_data) VALUES ('test_write_operation');" >/dev/null 2>&1; then
            print_success "Write operation test passed"
            
            # Clean up test table
            psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP TABLE $TEST_TABLE;" >/dev/null 2>&1
            print_success "Test table cleaned up"
        else
            print_error "Write operation test failed"
            # Clean up test table
            psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP TABLE $TEST_TABLE;" >/dev/null 2>&1
            return 1
        fi
    else
        print_error "Could not create test table"
        return 1
    fi
    
    return 0
}

# Test performance
test_performance() {
    print_status "Testing database performance..."
    
    if [ -n "$POSTGRES_PASSWORD" ]; then
        export PGPASSWORD="$POSTGRES_PASSWORD"
    fi
    
    # Test query performance
    START_TIME=$(date +%s.%N)
    
    # Run a simple query multiple times to test performance
    for i in {1..5}; do
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM live_data.live_price_log_1s_btc;" >/dev/null 2>&1
    done
    
    END_TIME=$(date +%s.%N)
    DURATION=$(echo "$END_TIME - $START_TIME" | bc -l 2>/dev/null || echo "0")
    
    print_success "Performance test completed in ${DURATION}s"
    
    # Check if performance is acceptable (less than 5 seconds for 5 queries)
    if (( $(echo "$DURATION < 5" | bc -l) )); then
        print_success "Performance test passed"
        return 0
    else
        print_warning "Performance test slow (${DURATION}s for 5 queries)"
        return 1
    fi
}

# Test Python database connection
test_python_connection() {
    print_status "Testing Python database connection..."
    
    # Create a temporary Python script to test database connection
    TEMP_SCRIPT="/tmp/test_db_connection.py"
    
    cat > "$TEMP_SCRIPT" << 'EOF'
import os
import sys
import psycopg2
from datetime import datetime

# Load environment variables
env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(env_file):
    with open(env_file, 'r') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

# Database configuration
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'database': os.getenv('POSTGRES_DB', 'rec_io_db'),
    'user': os.getenv('POSTGRES_USER', 'rec_io_user'),
    'password': os.getenv('POSTGRES_PASSWORD', '')
}

try:
    # Test connection
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    cursor = conn.cursor()
    
    # Test query
            cursor.execute("SELECT COUNT(*) FROM live_data.live_price_log_1s_btc;")
    count = cursor.fetchone()[0]
    
    print(f"Python connection successful - {count} rows in btc_price_log")
    
    cursor.close()
    conn.close()
    sys.exit(0)
    
except Exception as e:
    print(f"Python connection failed: {e}")
    sys.exit(1)
EOF

    # Run the Python test
    if python3 "$TEMP_SCRIPT" 2>/dev/null; then
        print_success "Python database connection test passed"
        rm -f "$TEMP_SCRIPT"
        return 0
    else
        print_error "Python database connection test failed"
        rm -f "$TEMP_SCRIPT"
        return 1
    fi
}

# Main testing function
run_tests() {
    print_header
    print_status "Running database tests for REC.IO trading system..."
    echo ""
    
    load_env
    
    TESTS_PASSED=0
    TESTS_FAILED=0
    
    # Run all tests
    test_connectivity && TESTS_PASSED=$((TESTS_PASSED + 1)) || TESTS_FAILED=$((TESTS_FAILED + 1))
    test_schema && TESTS_PASSED=$((TESTS_PASSED + 1)) || TESTS_FAILED=$((TESTS_FAILED + 1))
    test_table_structure && TESTS_PASSED=$((TESTS_PASSED + 1)) || TESTS_FAILED=$((TESTS_FAILED + 1))
    test_data_access && TESTS_PASSED=$((TESTS_PASSED + 1)) || TESTS_FAILED=$((TESTS_FAILED + 1))
    test_write_operations && TESTS_PASSED=$((TESTS_PASSED + 1)) || TESTS_FAILED=$((TESTS_FAILED + 1))
    test_performance && TESTS_PASSED=$((TESTS_PASSED + 1)) || TESTS_FAILED=$((TESTS_FAILED + 1))
    test_python_connection && TESTS_PASSED=$((TESTS_PASSED + 1)) || TESTS_FAILED=$((TESTS_FAILED + 1))
    
    echo ""
    print_status "Test Results Summary:"
    print_status "  Tests Passed: $TESTS_PASSED"
    print_status "  Tests Failed: $TESTS_FAILED"
    print_status "  Total Tests: $((TESTS_PASSED + TESTS_FAILED))"
    
    if [ $TESTS_FAILED -eq 0 ]; then
        echo ""
        print_success "All database tests passed! Database is ready for use."
    else
        echo ""
        print_warning "Some database tests failed. Please check your database configuration."
        exit 1
    fi
}

# Help function
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Test database connectivity and functionality for the REC.IO trading system."
    echo ""
    echo "Options:"
    echo "  --help, -h     Show this help message"
    echo "  --quick        Run only basic connectivity tests"
    echo ""
    echo "This script will test:"
    echo "  - Basic database connectivity"
    echo "  - Schema existence and structure"
    echo "  - Data access and read operations"
    echo "  - Write operations (with cleanup)"
    echo "  - Query performance"
    echo "  - Python database connection"
    echo ""
    echo "Environment variables (can be set in .env file):"
    echo "  POSTGRES_HOST     Database host (default: localhost)"
    echo "  POSTGRES_PORT     Database port (default: 5432)"
    echo "  POSTGRES_DB       Database name (default: rec_io_db)"
    echo "  POSTGRES_USER     Database user (default: rec_io_user)"
    echo "  POSTGRES_PASSWORD Database password (default: empty)"
}

# Parse command line arguments
QUICK_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --quick)
            QUICK_MODE=true
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
if [ "$QUICK_MODE" = true ]; then
    print_header
    print_status "Running quick database tests..."
    echo ""
    
    load_env
    
    if test_connectivity && test_schema; then
        print_success "Quick database tests passed!"
    else
        print_error "Quick database tests failed"
        exit 1
    fi
else
    run_tests
fi
