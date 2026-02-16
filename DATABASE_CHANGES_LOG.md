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

### 2026-02-14 - Add movement columns to live price log tables (1s) and watchdog write
- **Change Type**: SCHEMA_ADDITION
- **Description**: Added eight movement-related columns to all four live 1s price log tables (btc, eth, spx, ndx): `move_1m`, `move_2m`, `move_3m`, `move_4m`, `move_15m`, `move_30m`, `movement`, `movement_percentile`. The symbol price watchdog now computes and writes these on each tick (tick-derived high/low/open per window, weighted composite, percentile from analytics movement profile).
- **SQL Commands**:
```sql
-- Add movement columns to all live_price_log_1s_* tables
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS move_1m numeric(10,4);
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS move_2m numeric(10,4);
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS move_3m numeric(10,4);
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS move_4m numeric(10,4);
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS move_15m numeric(10,4);
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS move_30m numeric(10,4);
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS movement numeric(10,4);
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS movement_percentile numeric(5,1);
-- Repeat for live_price_log_1s_eth, live_price_log_1s_spx, live_price_log_1s_ndx (same column set).
```
- **Files Modified**:
  - `backend/core/config/database.py` (CREATE/ALTER for new columns on all four tables)
  - `backend/symbol_price_watchdog.py` (load_movement_profile, calculate_movement_percentile, get_high_low_open_for_window, calculate_move_for_window, get_movement_data; insert_tick extended; movement profile pre-load in log_symbol_price and handle_yahoo_finance_symbol)
  - `docs/MASTER_DB_SCHEMA_REFERENCE.md` (movement columns documented for live 1s tables)
  - `docs/PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md` (live movement population and process)
- **Files Added**:
  - `backend/test_watchdog_movement.py` (test script: insert_tick then verify movement columns; run with `python -m backend.test_watchdog_movement` from project root)
- **Status**: PENDING
- **Notes**:
  - No backfill: new rows get movement values as the watchdog runs; older rows keep NULL for these columns unless overwritten by conflict update.
  - Movement profile source: `analytics.{symbol}_movement_profile` or latest `analytics.{symbol}_movement_profile_YYYYMMDD`. Symbols without a profile (e.g. SPX/NDX) have NULL `movement_percentile`.
  - Weights match momentum: 1m 0.3, 2m 0.25, 3m 0.2, 4m 0.15, 15m 0.05, 30m 0.05.

### 2026-02-14 - Rename momentum_value to movement_value in movement profile tables
- **Change Type**: SCHEMA_MODIFICATION
- **Description**: Renamed column `momentum_value` to `movement_value` in all analytics movement profile tables (`analytics.{symbol}_movement_profile` and `analytics.{symbol}_movement_profile_YYYYMMDD`). The column holds movement values; the name now matches. Momentum profile tables are unchanged (they keep `momentum_value`).
- **SQL Commands** (per table; migration in database.py runs this for all matching tables):
```sql
-- For each table in analytics where table_name LIKE '%_movement_profile%':
ALTER TABLE analytics.<table_name> RENAME COLUMN momentum_value TO movement_value;
```
- **Files Modified**:
  - `backend/core/config/database.py` (migration in init_database: rename column in all analytics.*_movement_profile* tables)
  - `backend/util/analytics/symbol_profiler.py` (create_movement_profile_table, insert_movement_profile_data, generate_movement_profile, assign_movement_percentiles — use movement_value)
  - `backend/symbol_price_watchdog.py` (load_movement_profile: SELECT movement_value)
  - `docs/MASTER_DB_SCHEMA_REFERENCE.md`, `docs/PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md` (document movement_value)
- **Status**: PENDING
- **Notes**: Run `init_database()` to apply the rename to existing tables. symbol_price_watchdog and strike_table_generator (reads live price log only) use movement_value after this change. New movement profiles created by symbol_profiler will have movement_value column.

### 2026-02-14 - Add volatility and movement to strike tables (btc, eth, spx, ndx)
- **Change Type**: SCHEMA_ADDITION
- **Description**: Added four columns to all strike tables (`live_data.strike_table_btc`, `strike_table_eth`, `strike_table_spx`, `strike_table_ndx`): `volatility`, `volatility_percentile`, `movement`, `movement_percentile`. Populated by `strike_table_generator` from the same live 1s price log row used for price and momentum.
- **SQL Commands**:
```sql
ALTER TABLE live_data.strike_table_btc ADD COLUMN IF NOT EXISTS volatility NUMERIC(10,6);
ALTER TABLE live_data.strike_table_btc ADD COLUMN IF NOT EXISTS volatility_percentile NUMERIC(5,1);
ALTER TABLE live_data.strike_table_btc ADD COLUMN IF NOT EXISTS movement NUMERIC(10,4);
ALTER TABLE live_data.strike_table_btc ADD COLUMN IF NOT EXISTS movement_percentile NUMERIC(5,1);
-- Repeat for strike_table_eth, strike_table_spx, strike_table_ndx.
```
- **Files Modified**:
  - `backend/strike_table_generator.py` (get_current_market_data SELECT and return dict; CREATE TABLE and missing_columns; INSERT; get_latest_strike_table_json SELECT and result keys)
  - `backend/core/config/database.py` (migration block in init_database for all four strike tables)
  - `docs/MASTER_DB_SCHEMA_REFERENCE.md` (four new columns documented for strike_table_btc, eth, ndx, spx)
- **Status**: PENDING
- **Notes**: Generator adds columns via setup_live_data_schema() when it runs; init_database() migration adds them for existing DBs without running the generator.

### 2026-01-11 - Add momentum_30s_avg Column to Live Price Log Tables
- **Change Type**: SCHEMA_ADDITION
- **Description**: Added `momentum_30s_avg` column to all live_price_log tables (btc, eth, spx, ndx) to store 30-second rolling average of momentum values as percentile
- **SQL Commands**:
```sql
-- Add momentum_30s_avg column to all live_price_log tables
ALTER TABLE live_data.live_price_log_1s_btc ADD COLUMN IF NOT EXISTS momentum_30s_avg numeric(5,1);
ALTER TABLE live_data.live_price_log_1s_eth ADD COLUMN IF NOT EXISTS momentum_30s_avg numeric(5,1);
ALTER TABLE live_data.live_price_log_1s_spx ADD COLUMN IF NOT EXISTS momentum_30s_avg numeric(5,1);
ALTER TABLE live_data.live_price_log_1s_ndx ADD COLUMN IF NOT EXISTS momentum_30s_avg numeric(5,1);

-- Add comments to document the field
COMMENT ON COLUMN live_data.live_price_log_1s_btc.momentum_30s_avg IS '30-second rolling average of momentum values converted to percentile';
COMMENT ON COLUMN live_data.live_price_log_1s_eth.momentum_30s_avg IS '30-second rolling average of momentum values converted to percentile';
COMMENT ON COLUMN live_data.live_price_log_1s_spx.momentum_30s_avg IS '30-second rolling average of momentum values converted to percentile';
COMMENT ON COLUMN live_data.live_price_log_1s_ndx.momentum_30s_avg IS '30-second rolling average of momentum values converted to percentile';
```
- **Files Modified**:
  - `backend/symbol_price_watchdog.py` (added calculate_30s_momentum_average function and insert logic)
  - `backend/symbol_price_watchdog_finance.py` (added calculate_30s_momentum_average function and insert logic)
  - `docs/MASTER_DB_SCHEMA_REFERENCE.md` (updated schema documentation)
  - `add_momentum_30s_avg_migration.sql` (migration script created)
- **Status**: PENDING
- **Notes**:
  - The column is calculated by averaging the last 30 momentum values and converting to percentile
  - Follows the same pattern as momentum_5s_avg column
  - Column type: numeric(5,1) to match momentum_5s_avg format

### 2025-11-08 - Trades Weekly Cycle Backfill
- **Change Type**: SCHEMA_ADDITION | DATA_MIGRATION | INDEX_CREATION
- **Description**: Added `hour_idx` and `weekly_cycle` buckets to `users.trades_0001` and backfilled using EST calendar rules to support monitor performance tracking.
- **SQL Commands**:
```sql
BEGIN;
SET search_path TO users, public;

ALTER TABLE trades_0001 ADD COLUMN IF NOT EXISTS hour_idx SMALLINT;
ALTER TABLE trades_0001 ADD COLUMN IF NOT EXISTS weekly_cycle SMALLINT;

WITH parsed AS (
    SELECT
        id,
        REGEXP_REPLACE(contract, '.*\s([0-9]{1,2})(am|pm)$', '\1')::INT AS h_raw,
        LOWER(REGEXP_REPLACE(contract, '.*\s([0-9]{1,2})(am|pm)$', '\2')) AS mer
    FROM trades_0001
),
hcalc AS (
    SELECT
        t.id,
        CASE
            WHEN p.mer = 'am' AND p.h_raw = 12 THEN 24
            WHEN p.mer = 'am' THEN p.h_raw
            WHEN p.mer = 'pm' AND p.h_raw = 12 THEN 12
            ELSE p.h_raw + 12
        END AS hour_idx
    FROM trades_0001 t
    JOIN parsed p USING (id)
),
dcalc AS (
    SELECT
        t.id,
        h.hour_idx,
        EXTRACT(DOW FROM t.date::timestamp) AS dow
    FROM trades_0001 t
    JOIN hcalc h USING (id)
)
UPDATE trades_0001 t
SET hour_idx = d.hour_idx,
    weekly_cycle = (d.dow::INT * 24) + d.hour_idx
FROM dcalc d
WHERE t.id = d.id;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'trades_0001_weekly_cycle_idx'
          AND n.nspname = current_schema()
    ) THEN
        EXECUTE 'CREATE INDEX trades_0001_weekly_cycle_idx ON trades_0001(weekly_cycle)';
    END IF;
END$$;

-- Sanity checks
SELECT MIN(weekly_cycle) AS min_cycle,
       MAX(weekly_cycle) AS max_cycle,
       COUNT(*) FILTER (WHERE weekly_cycle IS NULL) AS null_cycles
FROM trades_0001;

SELECT weekly_cycle, COUNT(*) AS trades
FROM trades_0001
GROUP BY weekly_cycle
ORDER BY weekly_cycle
LIMIT 30;

SELECT id, date, contract, hour_idx, weekly_cycle
FROM trades_0001
ORDER BY date, weekly_cycle
LIMIT 50;

COMMIT;
```
- **Files Modified**:
  - `users.trades_0001` (schema)
  - `trades_0001_weekly_cycle_idx` (index)
- **Status**: VERIFIED
- **Notes**:
  - `weekly_cycle` is 1–168 (Sunday 1am through Saturday midnight bucketed as 24). Unparsable contracts remain `NULL`.
  - `hour_idx` is retained for debugging joins and verification; drop only after upstream adoption.
  - Re-run is idempotent; index creation wrapped in `DO` block guard.
- **Production Deployment**: VERIFIED (2025-11-08, host 137.184.224.94). Full table replaced with local verified copy; backup snapshot stored at `/Users/ericwais1/rec_io_local/2_5/prod_trades_0001_backup_20251108.sql`.

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
- **Production Deployment**: APPLIED (2025-01-27, host 137.184.224.94)

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
- **Production Deployment**: APPLIED (2025-01-27, host 137.184.224.94)

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
- **Production Deployment**: APPLIED (2025-01-27, host 137.184.224.94)
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
- **Production Deployment**: APPLIED (2025-01-27, host 137.184.224.94)
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
- **Production Deployment**: APPLIED (2025-01-27, host 137.184.224.94)
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
