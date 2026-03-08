#!/bin/bash

# PostgreSQL Test System Startup Script
# This script starts all PostgreSQL-related components for standalone testing

set -e

echo "🚀 Starting PostgreSQL Test System..."

# Kill any existing processes
echo "🛑 Stopping existing processes..."
pkill -f "symbol_price_watchdog.py" || true
pkill -f "kalshi_market_watchdog.py" || true
pkill -f "strike_table_analysis.py" || true
pkill -f "live_table_viewer.py" || true

sleep 2

# Check for remaining processes
REMAINING=$(ps aux | grep -E "(symbol_price_watchdog|kalshi_market_watchdog|strike_table_analysis|live_table_viewer)" | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️  Warning: $REMAINING processes still running"
    ps aux | grep -E "(symbol_price_watchdog|kalshi_market_watchdog|strike_table_analysis|live_table_viewer)" | grep -v grep
fi

# Set up environment
export PYTHONPATH=/Users/ericwais1/rec_io_20
cd /Users/ericwais1/rec_io_20

# Create logs directory if it doesn't exist
mkdir -p logs

# Start components in background
echo "📊 Starting Symbol Price Watchdog..."
source venv/bin/activate && PYTHONPATH=/Users/ericwais1/rec_io_20 python backend/symbol_price_watchdog.py BTC > logs/symbol_price_watchdog_btc.log 2>&1 &
SYMBOL_PID=$!
echo "   PID: $SYMBOL_PID"

echo "📊 Starting Kalshi API Watchdog..."
source venv/bin/activate && PYTHONPATH=/Users/ericwais1/rec_io_20 python backend/kalshi_market_watchdog.py > logs/kalshi_market_watchdog.log 2>&1 &
KALSHI_PID=$!
echo "   PID: $KALSHI_PID"

echo "📊 Starting Strike Table Analysis..."
source venv/bin/activate && PYTHONPATH=/Users/ericwais1/rec_io_20 python backend/strike_table_analysis.py > logs/strike_table_analysis.log 2>&1 &
STRIKE_PID=$!
echo "   PID: $STRIKE_PID"

echo "📊 Starting Live Table Viewer..."
source venv/bin/activate && PYTHONPATH=/Users/ericwais1/rec_io_20 python backend/util/live_table_viewer.py --schema live_data --table btc_live_strikes --port 8080 > logs/live_table_viewer.log 2>&1 &
VIEWER_PID=$!
echo "   PID: $VIEWER_PID"

# Save PIDs to file for later reference
echo "$SYMBOL_PID" > logs/symbol_price_watchdog.pid
echo "$KALSHI_PID" > logs/kalshi_market_watchdog.pid
echo "$STRIKE_PID" > logs/strike_table_analysis.pid
echo "$VIEWER_PID" > logs/live_table_viewer.pid

echo ""
echo "⏳ Waiting for components to initialize..."
sleep 5

# Check if processes are running
echo "🔍 Checking process status..."
for name in "Symbol Price Watchdog" "Kalshi API Watchdog" "Strike Table Analysis" "Live Table Viewer"; do
    case $name in
        "Symbol Price Watchdog") PID=$SYMBOL_PID ;;
        "Kalshi API Watchdog") PID=$KALSHI_PID ;;
        "Strike Table Analysis") PID=$STRIKE_PID ;;
        "Live Table Viewer") PID=$VIEWER_PID ;;
    esac
    
    if ps -p $PID > /dev/null 2>&1; then
        echo "✅ $name is running (PID: $PID)"
    else
        echo "❌ $name failed to start (PID: $PID)"
    fi
done

echo ""
echo "📊 System Status:"
echo "   Symbol Price Watchdog: http://localhost:8080 (if running)"
echo "   Live Table Viewer: http://localhost:8080"
echo "   Logs: logs/symbol_price_watchdog_btc.log"
echo "         logs/kalshi_market_watchdog.log"
echo "         logs/strike_table_analysis.log"
echo "         logs/live_table_viewer.log"

echo ""
echo "🎯 PostgreSQL Test System started!"
echo "   Use './scripts/stop_postgresql_system.sh' to stop all components" 