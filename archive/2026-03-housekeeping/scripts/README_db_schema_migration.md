# Database Schema Migration Script

## Overview

The `update_db_schema_to_reference.py` script updates all database tables to match the schema defined in `MASTER_DB_SCHEMA_REFERENCE.md`. It preserves all existing data and only adds missing columns.

## Features

- ✅ Preserves all existing data
- ✅ Adds missing columns with appropriate defaults
- ✅ Handles monitor-specific tables (discovers all instances)
- ✅ Dry-run mode for preview
- ✅ Safe migration (no data loss)

## Usage

### Dry Run (Preview Changes)

```bash
cd /opt/rec_io_server
python3 scripts/update_db_schema_to_reference.py --dry-run
```

This will show you all the changes that would be made without actually applying them.

### Apply Migrations

```bash
cd /opt/rec_io_server
python3 scripts/update_db_schema_to_reference.py
```

The script will:
1. Parse the schema reference document
2. Compare with existing database tables
3. Show you the changes
4. Ask for confirmation before applying

## How It Works

1. **Schema Parsing**: Reads `docs/MASTER_DB_SCHEMA_REFERENCE.md` and extracts table definitions
2. **Table Discovery**: Finds all existing tables in the database
3. **Monitor Table Detection**: Automatically discovers monitor-specific table instances:
   - `users.monitor_list_0001` → finds all `users.monitor_list_XXXX`
   - `users.active_trades_0001_10002` → finds all `users.active_trades_XXXX_YYYY`
   - `users.trades_0001` → finds all `users.trades_XXXX`
4. **Column Comparison**: Compares existing columns with reference schema
5. **Migration Generation**: Creates `ALTER TABLE` statements for missing columns
6. **Safe Execution**: Applies changes while preserving all data

## What Gets Updated

- **Missing Columns**: Added with appropriate data types and defaults
- **Column Types**: Detected but not changed (to preserve data safety)
- **Constraints**: Not modified (preserves existing constraints)
- **Indexes**: Not modified (preserves existing indexes)

## Safety Features

- All existing data is preserved
- New columns are added as nullable (if no default specified)
- NOT NULL columns without defaults are added as nullable to prevent data issues
- Transaction-based execution (rolls back on error)
- Confirmation prompt before applying changes

## Example Output

```
📖 Parsing schema reference...
✅ Parsed 150 table definitions

🔌 Connecting to database...
🔍 Analyzing database schema...
📋 Found 3 instance(s) for pattern: users.monitor_list_0001

================================================================================
Found 25 migration(s) to apply
================================================================================

📋 Table: users.monitor_list_0001
   3 column(s) to add:
   • ALTER TABLE users.monitor_list_0001 ADD COLUMN new_field VARCHAR(255)
   • ALTER TABLE users.monitor_list_0001 ADD COLUMN another_field INTEGER DEFAULT 0
   ...

⚠️  Ready to apply 25 migration(s)
Continue? (yes/no): yes

✅ users.monitor_list_0001: Added column
✅ users.monitor_list_0001: Added column
...
✅ Successfully applied 25 migration(s)
```

## Notes

- The script uses the database connection from `localhost` with credentials:
  - Database: `rec_io_db`
  - User: `rec_io_user`
  - Password: `rec_io_password`

- Monitor-specific tables are automatically discovered and updated
- The script handles data type normalization (e.g., `integer(32)` → `INTEGER`)
- Default values are preserved from the reference schema

