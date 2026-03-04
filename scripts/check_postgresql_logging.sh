#!/bin/bash
# Script to check PostgreSQL logging configuration
# Can be run locally or on production server

echo "=== PostgreSQL Logging Configuration Check ==="
echo ""

# Check current logging settings
echo "Current PostgreSQL logging settings:"
psql -U rec_io_user -d rec_io_db << 'EOF'
SHOW log_statement;
SHOW log_connections;
SHOW log_disconnections;
SHOW log_min_duration_statement;
EOF

echo ""
echo "=== Checking for verbose logging settings ==="
echo ""

# Check postgresql.auto.conf for problematic settings
if [ -f "/opt/homebrew/var/postgresql@15/postgresql.auto.conf" ]; then
    echo "Found postgresql.auto.conf (Homebrew):"
    grep -E "log_statement|log_connections|log_disconnections" /opt/homebrew/var/postgresql@15/postgresql.auto.conf || echo "  No verbose logging settings found"
elif [ -f "/etc/postgresql/*/main/postgresql.auto.conf" ]; then
    echo "Found postgresql.auto.conf (Linux):"
    grep -E "log_statement|log_connections|log_disconnections" /etc/postgresql/*/main/postgresql.auto.conf || echo "  No verbose logging settings found"
fi

echo ""
echo "=== Checking log file sizes ==="
echo ""

# Check PostgreSQL log file sizes
if [ -d "/opt/homebrew/var/log" ]; then
    echo "Homebrew PostgreSQL logs:"
    ls -lh /opt/homebrew/var/log/postgresql@*.log 2>/dev/null || echo "  No log files found"
elif [ -d "/var/log/postgresql" ]; then
    echo "Linux PostgreSQL logs:"
    ls -lh /var/log/postgresql/*.log 2>/dev/null || echo "  No log files found"
fi

echo ""
echo "=== Recommendations ==="
echo ""
echo "If log_statement is set to 'mod', 'ddl', or 'all', consider:"
echo "  ALTER SYSTEM SET log_statement = 'none';"
echo "  SELECT pg_reload_conf();"
echo ""
echo "If log_connections or log_disconnections are 'on', consider:"
echo "  ALTER SYSTEM SET log_connections = 'off';"
echo "  ALTER SYSTEM SET log_disconnections = 'off';"
echo "  SELECT pg_reload_conf();"

