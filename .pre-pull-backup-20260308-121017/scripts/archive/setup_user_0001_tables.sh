#!/bin/bash

# Setup user_0001 tables and migrate data
# This script creates the PostgreSQL tables and migrates existing SQLite data

set -e  # Exit on any error

echo "🚀 Starting user_0001 table setup and data migration..."

# Step 1: Create the table structure
echo "📋 Step 1: Creating PostgreSQL table structure..."
psql -h localhost -U rec_io_user -d rec_io_db -f create_user_0001_tables.sql

if [ $? -eq 0 ]; then
    echo "✅ Table structure created successfully"
else
    echo "❌ Failed to create table structure"
    exit 1
fi

# Step 2: Run the data migration
echo "📊 Step 2: Migrating data from SQLite to PostgreSQL..."
python3 scripts/migrate_user_0001_data.py

if [ $? -eq 0 ]; then
    echo "✅ Data migration completed successfully"
else
    echo "❌ Failed to migrate data"
    exit 1
fi

# Step 3: Validate the migration
echo "🔍 Step 3: Validating migration..."
python3 scripts/validate_user_0001_migration.py

if [ $? -eq 0 ]; then
    echo "✅ Migration validation completed"
else
    echo "⚠️ Migration validation had issues"
fi

# Step 4: Show summary
echo "📈 Step 4: Migration Summary"
echo "================================"
psql -h localhost -U rec_io_user -d rec_io_db -c "
SELECT 
    'trades_0001' as table_name, 
    COUNT(*) as row_count 
FROM users.trades_0001
UNION ALL
SELECT 
    'active_trades_0001' as table_name, 
    COUNT(*) as row_count 
FROM users.active_trades_0001
UNION ALL
SELECT 
    'positions_0001' as table_name, 
    COUNT(*) as row_count 
FROM users.positions_0001
UNION ALL
SELECT 
    'fills_0001' as table_name, 
    COUNT(*) as row_count 
FROM users.fills_0001
UNION ALL
SELECT 
    'orders_0001' as table_name, 
    COUNT(*) as row_count 
FROM users.orders_0001
UNION ALL
SELECT 
    'settlements_0001' as table_name, 
    COUNT(*) as row_count 
FROM users.settlements_0001
UNION ALL
SELECT 
    'account_balance_0001' as table_name, 
    COUNT(*) as row_count 
FROM users.account_balance_0001
ORDER BY table_name;
"

echo "🎉 User_0001 table setup and migration completed!"
echo ""
echo "📋 Created tables:"
echo "  - users.user_master"
echo "  - users.trades_0001"
echo "  - users.active_trades_0001"
echo "  - users.positions_0001"
echo "  - users.fills_0001"
echo "  - users.orders_0001"
echo "  - users.settlements_0001"
echo "  - users.account_balance_0001"
echo "  - users.watchlist_0001"
echo "  - users.trade_preferences_0001"
echo "  - users.auto_trade_settings_0001"
echo "  - users.user_info_0001"
echo ""
echo "🔧 Features included:"
echo "  - Exact schema matching with existing SQLite tables"
echo "  - Proper indexes for performance"
echo "  - Automatic updated_at timestamps"
echo "  - JSONB storage for flexible preferences"
echo "  - Foreign key relationships"
echo "  - Data integrity constraints"
echo ""
echo "📊 Next steps:"
echo "  1. Test the new tables with your application"
echo "  2. Update your database connection code to use PostgreSQL"
echo "  3. Gradually migrate functionality to use the new tables"
echo "  4. Keep SQLite files as backup until fully migrated" 