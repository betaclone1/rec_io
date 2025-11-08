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
  - `backend/active_trade_supervisor.py` (schema creation and monitoring logic) - APPLIED
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
  - `backend/active_trade_supervisor.py` (schema creation and monitoring logic) - APPLIED
  - `frontend/tabs/trade_monitor.html` (display updates) - PENDING
- **Status**: APPLIED

---

### 2025-01-27 - High/Low Price Tracking for Trades Table
- **Change Type**: SCHEMA_ADDITION
- **Description**: Add high_price and low_price columns to trades table for trailing stop functionality
- **SQL Commands**:
```sql
-- Step 1: Find all existing trades tables
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'users' 
AND table_name LIKE 'trades_%'
ORDER BY table_name;

-- Step 2: Add high_price and low_price columns to each existing trades table
-- (Replace 'trades_XXXX' with actual table names from Step 1)
ALTER TABLE users.trades_XXXX ADD COLUMN high_price DECIMAL(10,4) DEFAULT NULL;
ALTER TABLE users.trades_XXXX ADD COLUMN low_price DECIMAL(10,4) DEFAULT NULL;

-- Step 3: Add comments for documentation
COMMENT ON COLUMN users.trades_XXXX.high_price 
IS 'Highest position value reached since trade entry, used for trailing stop calculations';
COMMENT ON COLUMN users.trades_XXXX.low_price 
IS 'Lowest position value reached since trade entry, used for trailing stop calculations';

-- Step 4: For future trades tables, add to schema creation in trade_manager.py:
-- high_price DECIMAL(10,4),
-- low_price DECIMAL(10,4)
```
- **Deployment Script**:
```bash
# Run this script to apply changes to all trades tables
python3 -c "
import sys
sys.path.append('backend')
from util.db_connection_manager import get_db_connection

with get_db_connection() as conn:
    cursor = conn.cursor()
    
    # Find all trades tables
    cursor.execute('''
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'users' 
        AND table_name LIKE 'trades_%'
        ORDER BY table_name;
    ''')
    
    tables = [row[0] for row in cursor.fetchall()]
    print(f'Found {len(tables)} trades tables: {tables}')
    
    for table in tables:
        try:
            # Add high_price column
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN high_price DECIMAL(10,4) DEFAULT NULL;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.high_price IS \\'Highest position value reached since trade entry, used for trailing stop calculations\\';')
            print(f'✅ Added high_price to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column high_price already exists in {table}')
            else:
                print(f'❌ Error adding high_price to {table}: {e}')
        
        try:
            # Add low_price column
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN low_price DECIMAL(10,4) DEFAULT NULL;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.low_price IS \\'Lowest position value reached since trade entry, used for trailing stop calculations\\';')
            print(f'✅ Added low_price to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column low_price already exists in {table}')
            else:
                print(f'❌ Error adding low_price to {table}: {e}')
    
    conn.commit()
    print('✅ Database schema update completed')
"
```
- **Files Modified**: 
  - `backend/trade_manager.py` (schema creation) - APPLIED
- **Status**: APPLIED
- **Note**: Existing trades will have NULL values for these columns until they are populated by future monitoring logic

---

### 2025-01-27 - Momentum Scalp Strategy Settings (monitor_list)
- **Change Type**: SCHEMA_ADDITION
- **Description**: Add Momentum Scalp strategy settings to monitor_list tables
- **SQL Commands**:
```sql
-- Step 1: Find all existing monitor_list tables
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'users' 
AND table_name LIKE 'monitor_list_%'
ORDER BY table_name;

-- Step 2: Add Momentum Scalp settings to each existing monitor_list table
-- (Replace 'monitor_list_XXXX' with actual table names from Step 1)
ALTER TABLE users.monitor_list_XXXX 
ADD COLUMN momentum_scalp_entry_threshold DECIMAL(5,2) DEFAULT NULL,
ADD COLUMN momentum_scalp_trailing_stop_amount DECIMAL(5,2) DEFAULT 0.10,
ADD COLUMN momentum_scalp_profit_target DECIMAL(5,2) DEFAULT 0.99;

-- Step 3: Add comments for documentation
COMMENT ON COLUMN users.monitor_list_XXXX.momentum_scalp_entry_threshold 
IS 'Momentum threshold to trigger entry (e.g., 35.0 for ±35%). Positive spike enters YES ITM strikes, negative spike enters NO ITM strikes';
COMMENT ON COLUMN users.monitor_list_XXXX.momentum_scalp_trailing_stop_amount 
IS 'Trailing stop amount in dollars (e.g., 0.10 for 10 cents). Applied to both YES and NO contracts';
COMMENT ON COLUMN users.monitor_list_XXXX.momentum_scalp_profit_target 
IS 'Profit target as position value (e.g., 0.99 for $0.99). Hard cap - closes immediately when reached';
```
- **Deployment Script**:
```bash
# Run this script to apply changes to all monitor_list tables
python3 -c "
import sys
sys.path.append('backend')
from util.db_connection_manager import get_db_connection

with get_db_connection() as conn:
    cursor = conn.cursor()
    
    # Find all monitor_list tables
    cursor.execute('''
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'users' 
        AND table_name LIKE 'monitor_list_%'
        ORDER BY table_name;
    ''')
    
    tables = [row[0] for row in cursor.fetchall()]
    print(f'Found {len(tables)} monitor_list tables: {tables}')
    
    for table in tables:
        try:
            # Add momentum_scalp_entry_threshold
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN momentum_scalp_entry_threshold DECIMAL(5,2) DEFAULT NULL;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.momentum_scalp_entry_threshold IS \\'Momentum threshold to trigger entry (e.g., 35.0 for ±35%). Positive spike enters YES ITM strikes, negative spike enters NO ITM strikes\\';')
            print(f'✅ Added momentum_scalp_entry_threshold to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column momentum_scalp_entry_threshold already exists in {table}')
            else:
                print(f'❌ Error adding momentum_scalp_entry_threshold to {table}: {e}')
        
        try:
            # Add momentum_scalp_trailing_stop_amount
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN momentum_scalp_trailing_stop_amount DECIMAL(5,2) DEFAULT 0.10;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.momentum_scalp_trailing_stop_amount IS \\'Trailing stop amount in dollars (e.g., 0.10 for 10 cents). Applied to both YES and NO contracts\\';')
            print(f'✅ Added momentum_scalp_trailing_stop_amount to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column momentum_scalp_trailing_stop_amount already exists in {table}')
            else:
                print(f'❌ Error adding momentum_scalp_trailing_stop_amount to {table}: {e}')
        
        try:
            # Add momentum_scalp_profit_target
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN momentum_scalp_profit_target DECIMAL(5,2) DEFAULT 0.99;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.momentum_scalp_profit_target IS \\'Profit target as position value (e.g., 0.99 for $0.99). Hard cap - closes immediately when reached\\';')
            print(f'✅ Added momentum_scalp_profit_target to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column momentum_scalp_profit_target already exists in {table}')
            else:
                print(f'❌ Error adding momentum_scalp_profit_target to {table}: {e}')
    
    conn.commit()
    print('✅ Database schema update completed')
"
```
- **Files Modified**: 
  - `backend/auto_entry_supervisor.py` (settings retrieval) - PENDING
  - `backend/active_trade_supervisor.py` (settings retrieval) - PENDING
  - `frontend/tabs/trade_monitor.html` (UI for settings) - PENDING
- **Status**: APPLIED
- **Note**: 
  - Reuses existing `min_volume`, `total_position`, and `bankroll_allotment` fields
  - Loss prevention does not apply to Momentum Scalp strategy
  - No maximum position limit - enters as many strikes as collateral allows
  - Strategy enable/disable controlled by `strategy` field selection

---

### 2025-01-27 - Momentum Scalp Strategy Settings (strategy_list)
- **Change Type**: SCHEMA_ADDITION
- **Description**: Add Momentum Scalp strategy default settings to strategy_list tables for strategy defaults
- **SQL Commands**:
```sql
-- Step 1: Find all existing strategy_list tables
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'users' 
AND table_name LIKE 'strategy_list_%'
ORDER BY table_name;

-- Step 2: Add Momentum Scalp settings to each existing strategy_list table
-- (Replace 'strategy_list_XXXX' with actual table names from Step 1)
ALTER TABLE users.strategy_list_XXXX 
ADD COLUMN momentum_scalp_entry_threshold DECIMAL(5,2) DEFAULT NULL,
ADD COLUMN momentum_scalp_trailing_stop_amount DECIMAL(5,2) DEFAULT 0.10,
ADD COLUMN momentum_scalp_profit_target DECIMAL(5,2) DEFAULT 0.99;

-- Step 3: Add comments for documentation
COMMENT ON COLUMN users.strategy_list_XXXX.momentum_scalp_entry_threshold 
IS 'Momentum threshold to trigger entry (e.g., 35.0 for ±35%). Positive spike enters YES ITM strikes, negative spike enters NO ITM strikes';
COMMENT ON COLUMN users.strategy_list_XXXX.momentum_scalp_trailing_stop_amount 
IS 'Trailing stop amount in dollars (e.g., 0.10 for 10 cents). Applied to both YES and NO contracts';
COMMENT ON COLUMN users.strategy_list_XXXX.momentum_scalp_profit_target 
IS 'Profit target as position value (e.g., 0.99 for $0.99). Hard cap - closes immediately when reached';
```
- **Deployment Script**:
```bash
# Run this script to apply changes to all strategy_list tables
python3 -c "
import sys
sys.path.append('backend')
from util.db_connection_manager import get_db_connection

with get_db_connection() as conn:
    cursor = conn.cursor()
    
    # Find all strategy_list tables
    cursor.execute('''
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'users' 
        AND table_name LIKE 'strategy_list_%'
        ORDER BY table_name;
    ''')
    
    tables = [row[0] for row in cursor.fetchall()]
    print(f'Found {len(tables)} strategy_list tables: {tables}')
    
    for table in tables:
        try:
            # Add momentum_scalp_entry_threshold
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN momentum_scalp_entry_threshold DECIMAL(5,2) DEFAULT NULL;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.momentum_scalp_entry_threshold IS \\'Momentum threshold to trigger entry (e.g., 35.0 for ±35%). Positive spike enters YES ITM strikes, negative spike enters NO ITM strikes\\';')
            print(f'✅ Added momentum_scalp_entry_threshold to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column momentum_scalp_entry_threshold already exists in {table}')
            else:
                print(f'❌ Error adding momentum_scalp_entry_threshold to {table}: {e}')
        
        try:
            # Add momentum_scalp_trailing_stop_amount
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN momentum_scalp_trailing_stop_amount DECIMAL(5,2) DEFAULT 0.10;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.momentum_scalp_trailing_stop_amount IS \\'Trailing stop amount in dollars (e.g., 0.10 for 10 cents). Applied to both YES and NO contracts\\';')
            print(f'✅ Added momentum_scalp_trailing_stop_amount to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column momentum_scalp_trailing_stop_amount already exists in {table}')
            else:
                print(f'❌ Error adding momentum_scalp_trailing_stop_amount to {table}: {e}')
        
        try:
            # Add momentum_scalp_profit_target
            cursor.execute(f'ALTER TABLE users.{table} ADD COLUMN momentum_scalp_profit_target DECIMAL(5,2) DEFAULT 0.99;')
            cursor.execute(f'COMMENT ON COLUMN users.{table}.momentum_scalp_profit_target IS \\'Profit target as position value (e.g., 0.99 for \$0.99). Hard cap - closes immediately when reached\\';')
            print(f'✅ Added momentum_scalp_profit_target to {table}')
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                print(f'⚠️ Column momentum_scalp_profit_target already exists in {table}')
            else:
                print(f'❌ Error adding momentum_scalp_profit_target to {table}: {e}')
    
    conn.commit()
    print('✅ Database schema update completed')
"
```
- **Files Modified**: 
  - `backend/monitor_manager.py` (get_strategy_default_settings function) - PENDING
- **Status**: APPLIED
- **Note**: 
  - These columns store default values for the Momentum Scalp strategy in the strategy_list table
  - Individual monitors can override these defaults via their monitor_list settings
  - Used by `get_strategy_default_settings()` function to populate monitor settings when a strategy is selected

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
