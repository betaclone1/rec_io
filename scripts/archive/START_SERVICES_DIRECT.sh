#!/bin/bash

# Simple direct service startup - no supervisor bullshit
cd /root/rec_io_20

# Activate virtual environment
source venv/bin/activate

# Set Python path to include the project root
export PYTHONPATH=/root/rec_io_20:$PYTHONPATH

# Create logs directory
mkdir -p logs

echo "Starting REC.IO Trading System services..."

# Start main app
echo "Starting main app..."
nohup python3 backend/main.py > logs/main_app.log 2>&1 &
MAIN_PID=$!
echo "Main app started with PID: $MAIN_PID"

# Start trade manager
echo "Starting trade manager..."
nohup python3 backend/trade_manager.py > logs/trade_manager.log 2>&1 &
TRADE_MANAGER_PID=$!
echo "Trade manager started with PID: $TRADE_MANAGER_PID"

# Start trade executor
echo "Starting trade executor..."
nohup python3 backend/trade_executor.py > logs/trade_executor.log 2>&1 &
TRADE_EXECUTOR_PID=$!
echo "Trade executor started with PID: $TRADE_EXECUTOR_PID"

# Start active trade supervisor
echo "Starting active trade supervisor..."
nohup python3 backend/active_trade_supervisor.py > logs/active_trade_supervisor.log 2>&1 &
ACTIVE_TRADE_PID=$!
echo "Active trade supervisor started with PID: $ACTIVE_TRADE_PID"

# Start auto entry supervisor
echo "Starting auto entry supervisor..."
nohup python3 backend/auto_entry_supervisor.py > logs/auto_entry_supervisor.log 2>&1 &
AUTO_ENTRY_PID=$!
echo "Auto entry supervisor started with PID: $AUTO_ENTRY_PID"

# Start system monitor
echo "Starting system monitor..."
nohup python3 backend/system_monitor.py > logs/system_monitor.log 2>&1 &
SYSTEM_MONITOR_PID=$!
echo "System monitor started with PID: $SYSTEM_MONITOR_PID"

# Start cascading failure detector
echo "Starting cascading failure detector..."
nohup python3 backend/cascading_failure_detector.py > logs/cascading_failure_detector.log 2>&1 &
CASCADING_PID=$!
echo "Cascading failure detector started with PID: $CASCADING_PID"

# Start unified production coordinator
echo "Starting unified production coordinator..."
nohup python3 backend/unified_production_coordinator.py > logs/unified_production_coordinator.log 2>&1 &
UPC_PID=$!
echo "Unified production coordinator started with PID: $UPC_PID"

# Start Kalshi services
echo "Starting Kalshi services..."
nohup python3 backend/api/kalshi-api/kalshi_account_sync_ws.py > logs/kalshi_account_sync.log 2>&1 &
KALSHI_SYNC_PID=$!
echo "Kalshi account sync started with PID: $KALSHI_SYNC_PID"

nohup python3 backend/api/kalshi-api/kalshi_api_watchdog.py > logs/kalshi_api_watchdog.log 2>&1 &
KALSHI_WATCHDOG_PID=$!
echo "Kalshi API watchdog started with PID: $KALSHI_WATCHDOG_PID"

# Save PIDs to file for easy management
cat > /root/rec_io_20/service_pids.txt << EOF
MAIN_APP=$MAIN_PID
TRADE_MANAGER=$TRADE_MANAGER_PID
TRADE_EXECUTOR=$TRADE_EXECUTOR_PID
ACTIVE_TRADE_SUPERVISOR=$ACTIVE_TRADE_PID
AUTO_ENTRY_SUPERVISOR=$AUTO_ENTRY_PID
SYSTEM_MONITOR=$SYSTEM_MONITOR_PID
CASCADING_FAILURE_DETECTOR=$CASCADING_PID
UNIFIED_PRODUCTION_COORDINATOR=$UPC_PID
KALSHI_ACCOUNT_SYNC=$KALSHI_SYNC_PID
KALSHI_API_WATCHDOG=$KALSHI_WATCHDOG_PID
EOF

echo "All services started!"
echo "PIDs saved to: /root/rec_io_20/service_pids.txt"
echo "Logs in: /root/rec_io_20/logs/"
echo ""
echo "Main app: http://localhost:3000"
echo "Trade manager: http://localhost:4000"
echo ""
echo "To stop all services: kill \$(cat service_pids.txt | cut -d'=' -f2 | tr '\n' ' ')"
echo "To view logs: tail -f logs/*.log"
