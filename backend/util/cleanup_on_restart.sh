#!/bin/bash
# Cleanup script for orphaned PostgreSQL temporary schemas
# Run this script after stopping services and before restarting them

echo "🧹 Cleaning up orphaned PostgreSQL temporary schemas..."

# Stop all services
echo "📊 Stopping all services..."
supervisorctl stop all

# Wait for connections to close
echo "⏳ Waiting for database connections to close..."
sleep 5

# Run the cleanup script
echo "🧹 Running schema cleanup..."
cd /opt/rec_io_server
source venv/bin/activate
python backend/util/manual_schema_cleanup.py --force

# Restart services
echo "🔄 Restarting all services..."
supervisorctl start all

echo "✅ Cleanup and restart complete"
