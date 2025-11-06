# Database Changes Log

This document tracks all PostgreSQL database modifications made to the trading system. When deploying to other servers, apply these changes in chronological order.

## Change Log Format
- **Date**: YYYY-MM-DD
- **Change Type**: SCHEMA_ADDITION | SCHEMA_MODIFICATION | DATA_MIGRATION | INDEX_CREATION | etc.
- **Description**: Brief description of the change
- **SQL Commands**: The exact SQL to execute
- **Files Modified**: List of files that were updated
- **Status**: PENDING | APPLIED | VERIFIED

---

## Change History

### 2025-01-27 - High Price Tracking for Trailing Stops
- **Change Type**: SCHEMA_ADDITION
- **Description**: Add high_price column to active_trades tables for trailing stop functionality
- **SQL Commands**:
```sql
-- Step 1: Find all existing active_trades tables
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'users' 
AND table_name LIKE 'active_trades_%'
ORDER BY table_name;

-- Step 2: Add high_price column to each existing active_trades table
-- (Replace 'active_trades_XXXX_XXXXX' with actual table names from Step 1)
ALTER TABLE users.active_trades_XXXX_XXXXX ADD COLUMN high_price DECIMAL(10,4) DEFAULT NULL;

-- Step 3: Add comments for documentation
COMMENT ON COLUMN users.active_trades_XXXX_XXXXX.high_price 
IS 'Highest close price reached since trade entry, used for trailing stop calculations';

-- Step 4: For future active_trades tables, add to schema creation in active_trade_supervisor.py:
-- high_price DECIMAL(10,4) DEFAULT NULL,
```
- **Deployment Script**:
```bash
# Run this script to apply changes to all active_trades tables
python3 -c "
import sys
sys.path.append('backend')
from util.db_connection_manager import get_db_connection

with get_db_connection() as conn:
    cursor = conn.cursor()
    
    # Find all active_trades tables
    cursor.execute('''
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'users' 
        AND table_name LIKE 'active_trades_%'
        ORDER BY table_name;
    ''')
    
    tables = [row[0] for row in cursor.fetchall()]
    print(f'Found {len(tables)} active_trades tables: {tables}')
    
    for table in tables:
        try:
            # Add high_price column
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN high_price DECIMAL(10,4) DEFAULT NULL;')
            
            # Add comment
            cursor.execute(f'COMMENT ON COLUMN users.{table}.high_price IS \\'Highest close price reached since trade entry, used for trailing stop calculations\\';')
            
            print(f'✅ Added high_price to {table}')
        except Exception as e:
            if 'already exists' in str(e):
                print(f'⚠️ Column high_price already exists in {table}')
            else:
                print(f'❌ Error adding high_price to {table}: {e}')
    
    conn.commit()
    print('✅ Database schema update completed')
"
```
- **Files Modified**: 
  - `backend/active_trade_supervisor.py` (schema creation and monitoring logic) - PENDING
  - `frontend/tabs/trade_monitor.html` (display updates) - PENDING
- **Status**: APPLIED

---

### 2025-01-27 - Low Price Tracking for Trailing Stops
- **Change Type**: SCHEMA_ADDITION
- **Description**: Add low_price column to active_trades tables for trailing stop functionality
- **SQL Commands**:
```sql
-- Step 1: Find all existing active_trades tables
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'users' 
AND table_name LIKE 'active_trades_%'
ORDER BY table_name;

-- Step 2: Add low_price column to each existing active_trades table
-- (Replace 'active_trades_XXXX_XXXXX' with actual table names from Step 1)
ALTER TABLE users.active_trades_XXXX_XXXXX ADD COLUMN low_price DECIMAL(10,4) DEFAULT NULL;

-- Step 3: Add comments for documentation
COMMENT ON COLUMN users.active_trades_XXXX_XXXXX.low_price 
IS 'Lowest close price reached since trade entry, used for trailing stop calculations';

-- Step 4: For future active_trades tables, add to schema creation in active_trade_supervisor.py:
-- low_price DECIMAL(10,4) DEFAULT NULL,
```
- **Deployment Script**:
```bash
# Run this script to apply changes to all active_trades tables
python3 -c "
import sys
sys.path.append('backend')
from util.db_connection_manager import get_db_connection

with get_db_connection() as conn:
    cursor = conn.cursor()
    
    # Find all active_trades tables
    cursor.execute('''
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'users' 
        AND table_name LIKE 'active_trades_%'
        ORDER BY table_name;
    ''')
    
    tables = [row[0] for row in cursor.fetchall()]
    print(f'Found {len(tables)} active_trades tables: {tables}')
    
    for table in tables:
        try:
            # Add low_price column
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN low_price DECIMAL(10,4) DEFAULT NULL;')
            
            # Add comment
            cursor.execute(f'COMMENT ON COLUMN users.{table}.low_price IS \\'Lowest close price reached since trade entry, used for trailing stop calculations\\';')
            
            print(f'✅ Added low_price to {table}')
        except Exception as e:
            if 'already exists' in str(e):
                print(f'⚠️ Column low_price already exists in {table}')
            else:
                print(f'❌ Error adding low_price to {table}: {e}')
    
    conn.commit()
    print('✅ Database schema update completed')
"
```
- **Files Modified**: 
  - `backend/active_trade_supervisor.py` (schema creation and monitoring logic) - PENDING
  - `frontend/tabs/trade_monitor.html` (display updates) - PENDING
- **Status**: APPLIED

---

## Deployment Instructions

### For New Servers
1. Run all SQL commands in chronological order
2. Verify each change was applied successfully
3. Update status to "APPLIED" after verification
4. Test functionality before marking as "VERIFIED"

### For Existing Servers
1. Check current database schema against this log
2. Apply only missing changes
3. Verify data integrity after each change
4. Update status accordingly

## Notes
- Always backup database before applying changes
- Test changes on development environment first
- Document any issues or rollback procedures needed
- Keep this file updated with every database modification
