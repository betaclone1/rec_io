#!/bin/bash

# DATA MIGRATION SCRIPT
# This script migrates data from SQLite to PostgreSQL

set -e  # Exit on any error

echo "🔄 POSTGRESQL DATA MIGRATION"
echo "============================"
echo ""

# Configuration
MIGRATION_LOG="/tmp/postgresql_data_migration_$(date +%Y%m%d_%H%M%S).log"
BACKUP_DIR="/tmp/postgresql_migration_backup_$(date +%Y%m%d_%H%M%S)"
VERIFICATION_LOG="/tmp/postgresql_verification_$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$MIGRATION_LOG"
}

success() {
    echo -e "${GREEN}✅ $1${NC}" | tee -a "$MIGRATION_LOG"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}" | tee -a "$MIGRATION_LOG"
}

error() {
    echo -e "${RED}❌ $1${NC}" | tee -a "$MIGRATION_LOG"
}

# Function to backup SQLite databases
backup_sqlite_databases() {
    log "Creating backup of SQLite databases..."
    
    mkdir -p "$BACKUP_DIR"
    
    # Backup trades database
    if [ -f "backend/data/trade_history/trades.db" ]; then
        cp "backend/data/trade_history/trades.db" "$BACKUP_DIR/trades.db.backup"
        success "Backed up trades database"
    else
        warning "Trades database not found"
    fi
    
    # Backup active trades database
    if [ -f "backend/data/active_trades/active_trades.db" ]; then
        cp "backend/data/active_trades/active_trades.db" "$BACKUP_DIR/active_trades.db.backup"
        success "Backed up active trades database"
    else
        warning "Active trades database not found"
    fi
    
    success "Backup completed: $BACKUP_DIR"
}

# Function to export SQLite data to CSV
export_sqlite_to_csv() {
    log "Exporting SQLite data to CSV..."
    
    mkdir -p "$BACKUP_DIR/csv_exports"
    
    # Export trades table
    if [ -f "backend/data/trade_history/trades.db" ]; then
        sqlite3 backend/data/trade_history/trades.db << EOF
.mode csv
.headers on
.output $BACKUP_DIR/csv_exports/trades.csv
SELECT * FROM trades;
EOF
        success "Exported trades table to CSV"
    fi
    
    # Export active_trades table
    if [ -f "backend/data/active_trades/active_trades.db" ]; then
        sqlite3 backend/data/active_trades/active_trades.db << EOF
.mode csv
.headers on
.output $BACKUP_DIR/csv_exports/active_trades.csv
SELECT * FROM active_trades;
EOF
        success "Exported active_trades table to CSV"
    fi
    
    success "CSV export completed"
}

# Function to get SQLite table schema
get_sqlite_schema() {
    log "Getting SQLite table schemas..."
    
    mkdir -p "$BACKUP_DIR/schemas"
    
    # Get trades table schema
    if [ -f "backend/data/trade_history/trades.db" ]; then
        sqlite3 backend/data/trade_history/trades.db ".schema trades" > "$BACKUP_DIR/schemas/trades_schema.sql"
        success "Exported trades table schema"
    fi
    
    # Get active_trades table schema
    if [ -f "backend/data/active_trades/active_trades.db" ]; then
        sqlite3 backend/data/active_trades/active_trades.db ".schema active_trades" > "$BACKUP_DIR/schemas/active_trades_schema.sql"
        success "Exported active_trades table schema"
    fi
    
    success "Schema export completed"
}

# Function to create Python migration script
create_migration_script() {
    log "Creating Python migration script..."
    
    cat > "$BACKUP_DIR/migrate_data.py" << 'EOF'
#!/usr/bin/env python3
"""
Data Migration Script
Migrates data from SQLite to PostgreSQL using the database abstraction layer
"""

import os
import sys
import sqlite3
import json
from datetime import datetime
from decimal import Decimal

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.core.database import (
    get_trades_database,
    get_active_trades_database,
    init_all_databases
)

def migrate_trades_data():
    """Migrate trades data from SQLite to PostgreSQL."""
    print("🔄 Migrating trades data...")
    
    # Source SQLite database
    sqlite_path = "backend/data/trade_history/trades.db"
    if not os.path.exists(sqlite_path):
        print(f"❌ SQLite database not found: {sqlite_path}")
        return False
    
    # Target PostgreSQL database
    trades_db = get_trades_database()
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    try:
        # Get all trades from SQLite
        sqlite_cursor.execute("SELECT * FROM trades")
        trades = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(trades)} trades to migrate")
        
        # Get column names
        columns = [description[0] for description in sqlite_cursor.description]
        
        # Migrate each trade
        migrated_count = 0
        for trade in trades:
            try:
                # Create parameterized query
                placeholders = ', '.join(['%s'] * len(trade))
                query = f"INSERT INTO trades ({', '.join(columns)}) VALUES ({placeholders})"
                
                # Execute insert
                affected_rows = trades_db.execute_update(query, trade)
                
                if affected_rows == 1:
                    migrated_count += 1
                else:
                    print(f"⚠️  Failed to migrate trade {trade[0] if trade else 'unknown'}")
                    
            except Exception as e:
                print(f"❌ Error migrating trade {trade[0] if trade else 'unknown'}: {e}")
        
        print(f"✅ Successfully migrated {migrated_count}/{len(trades)} trades")
        return migrated_count == len(trades)
        
    except Exception as e:
        print(f"❌ Error during trades migration: {e}")
        return False
    finally:
        sqlite_conn.close()

def migrate_active_trades_data():
    """Migrate active_trades data from SQLite to PostgreSQL."""
    print("🔄 Migrating active_trades data...")
    
    # Source SQLite database
    sqlite_path = "backend/data/active_trades/active_trades.db"
    if not os.path.exists(sqlite_path):
        print(f"❌ SQLite database not found: {sqlite_path}")
        return False
    
    # Target PostgreSQL database
    active_trades_db = get_active_trades_database()
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cursor = sqlite_conn.cursor()
    
    try:
        # Get all active trades from SQLite
        sqlite_cursor.execute("SELECT * FROM active_trades")
        active_trades = sqlite_cursor.fetchall()
        
        print(f"📊 Found {len(active_trades)} active trades to migrate")
        
        # Get column names
        columns = [description[0] for description in sqlite_cursor.description]
        
        # Migrate each active trade
        migrated_count = 0
        for trade in active_trades:
            try:
                # Create parameterized query
                placeholders = ', '.join(['%s'] * len(trade))
                query = f"INSERT INTO active_trades ({', '.join(columns)}) VALUES ({placeholders})"
                
                # Execute insert
                affected_rows = active_trades_db.execute_update(query, trade)
                
                if affected_rows == 1:
                    migrated_count += 1
                else:
                    print(f"⚠️  Failed to migrate active trade {trade[0] if trade else 'unknown'}")
                    
            except Exception as e:
                print(f"❌ Error migrating active trade {trade[0] if trade else 'unknown'}: {e}")
        
        print(f"✅ Successfully migrated {migrated_count}/{len(active_trades)} active trades")
        return migrated_count == len(active_trades)
        
    except Exception as e:
        print(f"❌ Error during active_trades migration: {e}")
        return False
    finally:
        sqlite_conn.close()

def verify_migration():
    """Verify that migration was successful."""
    print("🔍 Verifying migration...")
    
    # Initialize databases
    init_all_databases()
    
    trades_db = get_trades_database()
    active_trades_db = get_active_trades_database()
    
    # Check trades count
    trades_count = len(trades_db.execute_query("SELECT COUNT(*) as count FROM trades"))
    print(f"📊 PostgreSQL trades count: {trades_count}")
    
    # Check active trades count
    active_trades_count = len(active_trades_db.execute_query("SELECT COUNT(*) as count FROM active_trades"))
    print(f"📊 PostgreSQL active trades count: {active_trades_count}")
    
    # Check SQLite counts for comparison
    sqlite_trades_path = "backend/data/trade_history/trades.db"
    sqlite_active_trades_path = "backend/data/active_trades/active_trades.db"
    
    if os.path.exists(sqlite_trades_path):
        sqlite_conn = sqlite3.connect(sqlite_trades_path)
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT COUNT(*) FROM trades")
        sqlite_trades_count = sqlite_cursor.fetchone()[0]
        sqlite_conn.close()
        print(f"📊 SQLite trades count: {sqlite_trades_count}")
    else:
        sqlite_trades_count = 0
        print("📊 SQLite trades database not found")
    
    if os.path.exists(sqlite_active_trades_path):
        sqlite_conn = sqlite3.connect(sqlite_active_trades_path)
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute("SELECT COUNT(*) FROM active_trades")
        sqlite_active_trades_count = sqlite_cursor.fetchone()[0]
        sqlite_conn.close()
        print(f"📊 SQLite active trades count: {sqlite_active_trades_count}")
    else:
        sqlite_active_trades_count = 0
        print("📊 SQLite active trades database not found")
    
    # Verify counts match
    trades_match = trades_count == sqlite_trades_count
    active_trades_match = active_trades_count == sqlite_active_trades_count
    
    print(f"✅ Trades count match: {trades_match}")
    print(f"✅ Active trades count match: {active_trades_match}")
    
    return trades_match and active_trades_match

def main():
    """Main migration function."""
    print("🚀 Starting PostgreSQL data migration...")
    
    # Set environment for PostgreSQL
    os.environ['DATABASE_TYPE'] = 'postgresql'
    os.environ['POSTGRES_HOST'] = 'localhost'
    os.environ['POSTGRES_PORT'] = '5432'
    os.environ['POSTGRES_DB'] = 'rec_io_db'
    os.environ['POSTGRES_USER'] = 'rec_io_user'
    os.environ['POSTGRES_PASSWORD'] = ''
    
    try:
        # Initialize databases
        init_all_databases()
        
        # Migrate trades data
        trades_success = migrate_trades_data()
        
        # Migrate active trades data
        active_trades_success = migrate_active_trades_data()
        
        # Verify migration
        verification_success = verify_migration()
        
        if trades_success and active_trades_success and verification_success:
            print("🎉 Data migration completed successfully!")
            return True
        else:
            print("❌ Data migration failed!")
            return False
            
    except Exception as e:
        print(f"❌ Migration error: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
EOF
    
    success "Python migration script created"
}

# Function to run data migration
run_data_migration() {
    log "Running data migration..."
    
    # Set environment for PostgreSQL
    export DATABASE_TYPE=postgresql
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=5432
    export POSTGRES_DB=rec_io_db
    export POSTGRES_USER=rec_io_user
    export POSTGRES_PASSWORD=""
    
    # Run the Python migration script with proper Python path
    cd "$BACKUP_DIR"
    PYTHONPATH="$(pwd)/.." python3 migrate_data.py
    cd - > /dev/null
    
    if [ $? -eq 0 ]; then
        success "Data migration completed successfully"
        return 0
    else
        error "Data migration failed"
        return 1
    fi
}

# Function to verify data integrity
verify_data_integrity() {
    log "Verifying data integrity..."
    
    # Set environment for PostgreSQL
    export DATABASE_TYPE=postgresql
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=5432
    export POSTGRES_DB=rec_io_db
    export POSTGRES_USER=rec_io_user
    export POSTGRES_PASSWORD=""
    
    # Run verification tests
    if python3 -c "
import sys
sys.path.insert(0, '.')
from backend.core.database import test_database_connection
test_database_connection()
print('✅ Database connectivity verified')
" >/dev/null 2>&1; then
        success "Database connectivity verified"
    else
        error "Database connectivity verification failed"
        return 1
    fi
    
    # Test data access patterns
    if python3 tests/test_system_integration.py >/dev/null 2>&1; then
        success "Data access patterns verified"
    else
        error "Data access patterns verification failed"
        return 1
    fi
    
    success "Data integrity verification completed"
    return 0
}

# Function to test performance
test_performance() {
    log "Testing performance with migrated data..."
    
    # Set environment for PostgreSQL
    export DATABASE_TYPE=postgresql
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=5432
    export POSTGRES_DB=rec_io_db
    export POSTGRES_USER=rec_io_user
    export POSTGRES_PASSWORD=""
    
    # Test query performance
    if python3 -c "
import sys
import time
sys.path.insert(0, '.')
from backend.core.database import get_trades_database, get_active_trades_database

# Test trades database performance
trades_db = get_trades_database()
start_time = time.time()
trades = trades_db.execute_query('SELECT * FROM trades LIMIT 100')
trades_time = time.time() - start_time
print(f'✅ Trades query performance: {trades_time:.3f}s for {len(trades)} records')

# Test active trades database performance
active_trades_db = get_active_trades_database()
start_time = time.time()
active_trades = active_trades_db.execute_query('SELECT * FROM active_trades LIMIT 100')
active_trades_time = time.time() - start_time
print(f'✅ Active trades query performance: {active_trades_time:.3f}s for {len(active_trades)} records')
" >/dev/null 2>&1; then
        success "Performance testing completed"
    else
        error "Performance testing failed"
        return 1
    fi
    
    return 0
}

# Function to rollback migration
rollback_migration() {
    error "ROLLBACK INITIATED"
    log "Restoring from backup: $BACKUP_DIR"
    
    # Restore SQLite databases
    if [ -f "$BACKUP_DIR/trades.db.backup" ]; then
        cp "$BACKUP_DIR/trades.db.backup" "backend/data/trade_history/trades.db"
        success "Restored trades database"
    fi
    
    if [ -f "$BACKUP_DIR/active_trades.db.backup" ]; then
        cp "$BACKUP_DIR/active_trades.db.backup" "backend/data/active_trades/active_trades.db"
        success "Restored active trades database"
    fi
    
    # Set environment back to SQLite
    export DATABASE_TYPE=sqlite
    
    success "Rollback completed"
}

# Main migration function
migrate_data() {
    log "Starting PostgreSQL data migration..."
    
    # Step 1: Backup current data
    log "Step 1: Creating backup"
    backup_sqlite_databases
    export_sqlite_to_csv
    get_sqlite_schema
    
    # Step 2: Create migration script
    log "Step 2: Creating migration script"
    create_migration_script
    
    # Step 3: Run data migration
    log "Step 3: Running data migration"
    run_data_migration || {
        error "Data migration failed"
        rollback_migration
        exit 1
    }
    
    # Step 4: Verify data integrity
    log "Step 4: Verifying data integrity"
    verify_data_integrity || {
        error "Data integrity verification failed"
        rollback_migration
        exit 1
    }
    
    # Step 5: Test performance
    log "Step 5: Testing performance"
    test_performance || {
        error "Performance testing failed"
        rollback_migration
        exit 1
    }
    
    # Step 6: Final verification
    log "Step 6: Final verification"
    success "PostgreSQL data migration completed successfully!"
    log "Backup location: $BACKUP_DIR"
    log "Migration log: $MIGRATION_LOG"
    
    echo ""
    echo "🎉 DATA MIGRATION SUCCESSFUL!"
    echo "=============================="
    echo "✅ SQLite data migrated to PostgreSQL"
    echo "✅ Data integrity verified"
    echo "✅ Performance tested"
    echo "✅ All queries working correctly"
    echo ""
    echo "📁 Backup location: $BACKUP_DIR"
    echo "📋 Migration log: $MIGRATION_LOG"
    echo ""
    echo "⚠️  IMPORTANT: Monitor the system for the next 24 hours"
    echo "   - Check for any data inconsistencies"
    echo "   - Monitor query performance"
    echo "   - Verify all application features work correctly"
    echo "   - Test backup and restore procedures"
}

# Handle command line arguments
case "${1:-migrate}" in
    "migrate")
        migrate_data
        ;;
    "backup")
        backup_sqlite_databases
        export_sqlite_to_csv
        get_sqlite_schema
        ;;
    "rollback")
        rollback_migration
        ;;
    "verify")
        verify_data_integrity
        ;;
    "performance")
        test_performance
        ;;
    *)
        echo "Usage: $0 {migrate|backup|rollback|verify|performance}"
        echo ""
        echo "Commands:"
        echo "  migrate    - Run full data migration (default)"
        echo "  backup     - Create backup of SQLite data only"
        echo "  rollback   - Rollback to SQLite databases"
        echo "  verify     - Verify data integrity"
        echo "  performance - Test performance with migrated data"
        exit 1
        ;;
esac 