#!/bin/bash
# Database access script for easy PostgreSQL connections
export PGPASSWORD='rec_io_password'

# Function to run SQL queries
db_query() {
    psql -h localhost -U rec_io_user -d rec_io_db -c "$1"
}

# Function to get table count
table_count() {
    db_query "SELECT COUNT(*) FROM $1;"
}

# Function to list all tables
list_tables() {
    db_query "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name;"
}

# Function to describe a table
describe_table() {
    db_query "\\d $1"
}

# If arguments provided, run them
if [ $# -gt 0 ]; then
    db_query "$*"
else
    echo "Database access script loaded. Available functions:"
    echo "  db_query 'SQL'     - Run any SQL query"
    echo "  table_count 'table' - Get row count for table"
    echo "  list_tables        - List all tables"
    echo "  describe_table 'table' - Describe table structure"
    echo ""
    echo "Example: db_query \"SELECT COUNT(*) FROM fills;\""
fi
