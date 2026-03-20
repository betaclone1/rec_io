#!/bin/bash

# RESTORE TO CURRENT STATE SCRIPT
# Restores the trading system to a previously captured state

echo "🔄 RESTORING TRADING SYSTEM TO CAPTURED STATE..."
echo "================================================"

# Check if backup directory exists
if [ ! -d "backup" ]; then
    echo "❌ Backup directory not found!"
    echo "Please run CAPTURE_CURRENT_STATE.sh first to create a backup."
    exit 1
fi

# Check if restoration manifest exists
if [ ! -f "backup/RESTORATION_MANIFEST.txt" ]; then
    echo "❌ Restoration manifest not found!"
    echo "Please run CAPTURE_CURRENT_STATE.sh first to create a backup."
    exit 1
fi

echo "📄 Found restoration manifest:"
echo "Capture timestamp: $(cat backup/capture_timestamp.txt 2>/dev/null || echo 'Unknown')"
echo ""

# Stop all supervisor processes
echo "🛑 Stopping all supervisor processes..."
supervisorctl stop all 2>/dev/null || true

# Kill any remaining processes on our ports using centralized port management
echo "🔄 Killing processes on trading system ports..."
python -c "
from backend.core.port_manager import list_assignments
import subprocess
import os

assignments = list_assignments()
for service, assignment in assignments.items():
    if assignment.port:
        try:
            # Find processes using this port
            result = subprocess.run(['lsof', '-ti', f':{assignment.port}'], 
                                  capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        print(f'Killing process {pid} on port {assignment.port}')
                        os.kill(int(pid), 9)
        except Exception as e:
            print(f'Error killing process on port {assignment.port}: {e}')
"

# Wait a moment for processes to stop
sleep 2

# Clean up any port management temporary files
echo "🧹 Cleaning up port management files..."
rm -f backend/data/port_registry.json || true
rm -f backend/data/port_cache.json || true

# Clean up any universal port system files (if they exist)
rm -rf backend/universal_port_system || true
rm -f backend/universal_port_system.py || true

# Restore original configuration files
echo "📋 Restoring configuration files..."

# Restore main application files
if [ -f "backup/main.py.original" ]; then
    cp backup/main.py.original backend/main.py
    echo "✅ Restored main.py"
fi

if [ -f "backup/trade_manager.py.original" ]; then
    cp backup/trade_manager.py.original backend/trade_manager.py
    echo "✅ Restored trade_manager.py"
fi

if [ -f "backup/trade_executor.py.original" ]; then
    cp backup/trade_executor.py.original backend/trade_executor.py
    echo "✅ Restored trade_executor.py"
fi

# Restore supervisor configuration
if [ -f "backup/supervisord.conf.original" ]; then
    cp backup/supervisord.conf.original backend/supervisord.conf
    echo "✅ Restored supervisord.conf"
fi

# Restore core configuration
if [ -f "backup/config.json.original" ]; then
    cp backup/config.json.original backend/core/config/config.json
    echo "✅ Restored config.json"
fi

# Restore port registry
if [ -f "backup/port_registry.json.original" ]; then
    cp backup/port_registry.json.original backend/data/port_registry.json
    echo "✅ Restored port_registry.json"
fi

# Restore database files
echo "💾 Restoring database files..."

# Restore trade history database
if [ -f "backup/databases/trades.db.backup" ]; then
    mkdir -p backend/data/users/user_0001/trade_history
    cp backup/databases/trades.db.backup backend/data/users/user_0001/trade_history/trades.db
    echo "✅ Restored trades.db"
fi

# Restore active trades database
if [ -f "backup/databases/active_trades.db.backup" ]; then
    mkdir -p backend/data/users/user_0001/active_trades
    cp backup/databases/active_trades.db.backup backend/data/users/user_0001/active_trades/active_trades.db
    echo "✅ Restored active_trades.db"
fi

# Restore account data
if [ -d "backup/databases/accounts" ]; then
    mkdir -p backend/data/users/user_0001/accounts
    cp -r backup/databases/accounts/* backend/data/users/user_0001/accounts/ 2>/dev/null || true
    echo "✅ Restored account data"
fi

# Restore price history data
if [ -d "backup/databases/price_history" ]; then
    mkdir -p backend/data/live_data/price_history
cp -r backup/databases/price_history/* backend/data/live_data/price_history/ 2>/dev/null || true
    echo "✅ Restored price history data"
fi

# Restore environment variables
echo "🔧 Restoring environment variables..."
if [ -f "backup/trading_environment_vars.txt" ]; then
    while IFS= read -r line; do
        if [[ $line =~ ^[A-Z_]+= ]]; then
            export "$line"
        fi
    done < backup/trading_environment_vars.txt
    echo "✅ Restored environment variables"
fi

# Set environment variables using centralized port system
export MAIN_APP_PORT=${MAIN_APP_PORT:-$(python -c "from backend.core.port_config import get_port; print(get_port('main_app'))")}
export TRADE_MANAGER_PORT=${TRADE_MANAGER_PORT:-$(python -c "from backend.core.port_config import get_port; print(get_port('trade_manager'))")}
export TRADE_EXECUTOR_PORT=${TRADE_EXECUTOR_PORT:-$(python -c "from backend.core.port_config import get_port; print(get_port('trade_executor'))")}
export ACTIVE_TRADE_SUPERVISOR_PORT=${ACTIVE_TRADE_SUPERVISOR_PORT:-$(python -c "from backend.core.port_config import get_port; print(get_port('active_trade_supervisor'))")}

# Start supervisor
echo "🚀 Starting supervisor..."
supervisord -c backend/supervisord.conf

# Wait for services to start
echo "⏳ Waiting for services to start..."
sleep 5

# Check port usage using centralized port management
echo "🔍 Checking port usage..."
python -c "
from backend.core.port_config import list_all_ports
ports = list_all_ports()
print('CURRENT PORT ASSIGNMENTS:')
for service, port in ports.items():
    print(f'{service}: {port}')
"

# Test service connectivity
echo "🧪 Testing service connectivity..."

# Test main app
python -c "
from backend.core.port_config import get_port
import requests

port = get_port('main_app')
if port:
    try:
        response = requests.get(f'http://localhost:{port}/health', timeout=5)
        print(f'Main app health: {response.status_code}')
    except:
        print('Main app not responding yet')
else:
    print('Main app port not assigned')
" || echo "   ⚠️  Main app not responding yet"

# Test trade manager
python -c "
from backend.core.port_config import get_port
import requests

port = get_port('trade_manager')
if port:
    try:
        response = requests.get(f'http://localhost:{port}/health', timeout=5)
        print(f'Trade manager health: {response.status_code}')
    except:
        print('Trade manager not responding yet')
else:
    print('Trade manager port not assigned')
" || echo "   ⚠️  Trade manager not responding yet"

# Test trade executor
python -c "
from backend.core.port_config import get_port
import requests

port = get_port('trade_executor')
if port:
    try:
        response = requests.get(f'http://localhost:{port}/health', timeout=5)
        print(f'Trade executor health: {response.status_code}')
    except:
        print('Trade executor not responding yet')
else:
    print('Trade executor port not assigned')
" || echo "   ⚠️  Trade executor not responding yet"

# Check supervisor status
echo "📊 Checking supervisor status..."
supervisorctl status

# Final verification
echo "✅ RESTORATION COMPLETE"
echo ""
echo "📊 RESTORATION SUMMARY:"
echo "======================"
echo "Restored from: $(cat backup/capture_timestamp.txt 2>/dev/null || echo 'Unknown')"
echo "Current directory: $(pwd)"
echo ""
echo "📋 Final port usage:"
python -c "
from backend.core.port_config import list_all_ports
ports = list_all_ports()
for service, port in ports.items():
    print(f'{service}: {port}')
"
echo ""
echo "🔧 Service status:"
supervisorctl status
echo ""
echo "🧪 Test commands:"
echo "1. Main app: curl http://localhost:\$(python -c \"from backend.core.port_config import get_port; print(get_port('main_app'))\")/health"
echo "2. Trade manager: curl http://localhost:\$(python -c \"from backend.core.port_config import get_port; print(get_port('trade_manager'))\")/health"
echo "3. Trade executor: curl http://localhost:\$(python -c \"from backend.core.port_config import get_port; print(get_port('trade_executor'))\")/health"
echo ""
echo "🎉 Trading system restored to captured state!" 