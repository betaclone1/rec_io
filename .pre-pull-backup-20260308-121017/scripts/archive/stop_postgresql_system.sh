#!/bin/bash

# PostgreSQL Test System Stop Script
# This script stops all PostgreSQL-related components

set -e

echo "🛑 Stopping PostgreSQL Test System..."

# Kill all related processes
echo "📊 Stopping Symbol Price Watchdog..."
pkill -f "symbol_price_watchdog.py" || true

echo "📊 Stopping Kalshi API Watchdog..."
pkill -f "kalshi_market_watchdog.py" || true

echo "📊 Stopping Strike Table Analysis..."
pkill -f "strike_table_analysis.py" || true

echo "📊 Stopping Live Table Viewer..."
pkill -f "live_table_viewer.py" || true

sleep 2

# Check for remaining processes
REMAINING=$(ps aux | grep -E "(symbol_price_watchdog|kalshi_market_watchdog|strike_table_analysis|live_table_viewer)" | grep -v grep | wc -l)
if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️  Warning: $REMAINING processes still running"
    ps aux | grep -E "(symbol_price_watchdog|kalshi_market_watchdog|strike_table_analysis|live_table_viewer)" | grep -v grep
    echo "🔄 Force killing remaining processes..."
    pkill -9 -f "symbol_price_watchdog.py" || true
    pkill -9 -f "kalshi_market_watchdog.py" || true
    pkill -9 -f "strike_table_analysis.py" || true
    pkill -9 -f "live_table_viewer.py" || true
    sleep 1
else
    echo "✅ All processes stopped successfully"
fi

# Clean up PID files
rm -f logs/symbol_price_watchdog.pid
rm -f logs/kalshi_market_watchdog.pid
rm -f logs/strike_table_analysis.pid
rm -f logs/live_table_viewer.pid

echo ""
echo "🎯 PostgreSQL Test System stopped!"
echo "   Use './scripts/start_postgresql_system.sh' to restart all components" 