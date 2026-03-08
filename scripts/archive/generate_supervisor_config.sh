#!/bin/bash

# Generate Supervisor Configuration Script
# This script creates a dynamic supervisor configuration file with correct paths

set -e

echo "🔧 Generating supervisor configuration..."

PROJECT_ROOT=$(pwd)
VENV_PATH="$PROJECT_ROOT/venv"
PYTHON_PATH="$VENV_PATH/bin/python"

# Ensure logs directory exists
mkdir -p logs

cat > backend/supervisord.conf << EOF
[supervisord]
nodaemon=true
logfile=/tmp/supervisord.log
pidfile=/tmp/supervisord.pid
stdout_logfile_maxbytes=0
stderr_logfile_maxbytes=0

[supervisorctl]
serverurl=unix:///tmp/supervisord.sock

[unix_http_server]
file=/tmp/supervisord.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[program:main_app]
command=$PYTHON_PATH $PROJECT_ROOT/backend/main.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/main_app.err.log
stdout_logfile=$PROJECT_ROOT/logs/main_app.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:trade_manager]
command=$PYTHON_PATH $PROJECT_ROOT/backend/trade_manager.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/trade_manager.err.log
stdout_logfile=$PROJECT_ROOT/logs/trade_manager.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:trade_executor]
command=$PYTHON_PATH $PROJECT_ROOT/backend/trade_executor.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/trade_executor.err.log
stdout_logfile=$PROJECT_ROOT/logs/trade_executor.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:active_trade_supervisor]
command=$PYTHON_PATH $PROJECT_ROOT/backend/active_trade_supervisor.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/active_trade_supervisor.err.log
stdout_logfile=$PROJECT_ROOT/logs/active_trade_supervisor.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:auto_entry_supervisor]
command=$PYTHON_PATH $PROJECT_ROOT/backend/auto_entry_supervisor.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/auto_entry_supervisor.err.log
stdout_logfile=$PROJECT_ROOT/logs/auto_entry_supervisor.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:symbol_price_watchdog_btc]
command=$PYTHON_PATH $PROJECT_ROOT/backend/symbol_price_watchdog.py BTC
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/symbol_price_watchdog_btc.err.log
stdout_logfile=$PROJECT_ROOT/logs/symbol_price_watchdog_btc.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:symbol_price_watchdog_eth]
command=$PYTHON_PATH $PROJECT_ROOT/backend/symbol_price_watchdog.py ETH
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/symbol_price_watchdog_eth.err.log
stdout_logfile=$PROJECT_ROOT/logs/symbol_price_watchdog_eth.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:strike_table_generator]
command=$PYTHON_PATH $PROJECT_ROOT/backend/strike_table_generator.py continuous 1
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/strike_table_generator.err.log
stdout_logfile=$PROJECT_ROOT/logs/strike_table_generator.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:kalshi_account_sync]
command=$PYTHON_PATH $PROJECT_ROOT/backend/api/kalshi-api/kalshi_account_sync_ws.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/kalshi_account_sync.err.log
stdout_logfile=$PROJECT_ROOT/logs/kalshi_account_sync.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:kalshi_market_watchdog]
command=$PYTHON_PATH $PROJECT_ROOT/backend/kalshi_market_watchdog.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/kalshi_market_watchdog.err.log
stdout_logfile=$PROJECT_ROOT/logs/kalshi_market_watchdog.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:system_monitor]
command=$PYTHON_PATH $PROJECT_ROOT/backend/system_monitor.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/system_monitor.err.log
stdout_logfile=$PROJECT_ROOT/logs/system_monitor.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"

[program:cascading_failure_detector]
command=$PYTHON_PATH $PROJECT_ROOT/backend/cascading_failure_detector.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/cascading_failure_detector.err.log
stdout_logfile=$PROJECT_ROOT/logs/cascading_failure_detector.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432",POSTGRES_HOST="localhost",POSTGRES_DB="rec_io_db",POSTGRES_USER="rec_io_user",POSTGRES_PASSWORD="rec_io_password",POSTGRES_PORT="5432"
EOF

echo "✅ Generated supervisor configuration at $PROJECT_ROOT/backend/supervisord.conf"
echo "📁 Project root: $PROJECT_ROOT"
echo "🐍 Python path: $PYTHON_PATH"
echo "📝 Logs directory: $PROJECT_ROOT/logs"
