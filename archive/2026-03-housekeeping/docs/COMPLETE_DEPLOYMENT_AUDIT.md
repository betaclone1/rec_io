# COMPLETE DEPLOYMENT AUDIT & GUIDE

## NOTE TO MYSELF: FRESH MACHINE DEPLOYMENT

This is a complete audit of what needs to be done to deploy the REC.IO trading system on a brand new machine. This guide covers EVERYTHING needed.

---

## 🚨 CRITICAL ISSUES IDENTIFIED

### 1. **SUPERVISOR CONFIGURATION IS BROKEN**
- **Problem**: `backend/supervisord.conf` has hardcoded paths like `/Users/ericwais1/rec_io_20/`
- **Impact**: Services fail immediately on any machine other than the original
- **Fix**: Must generate dynamic supervisor config

### 2. **MISSING DATABASE SCHEMA SETUP**
- **Problem**: No automatic database schema creation
- **Impact**: Services fail with "relation does not exist" errors
- **Fix**: Must create all required PostgreSQL tables and schemas

### 3. **ENVIRONMENT VARIABLES NOT SET**
- **Problem**: Services expect environment variables that aren't set
- **Impact**: Database connection failures
- **Fix**: Must set proper environment variables

### 4. **ARCHIVED SERVICES STILL REFERENCED**
- **Problem**: Supervisor tries to run `archive/old_scripts/symbol_price_watchdog.py`
- **Impact**: Services fail because files don't exist
- **Fix**: Must update supervisor config to use correct service paths

---

## 📋 COMPLETE DEPLOYMENT CHECKLIST

### **PHASE 1: SYSTEM REQUIREMENTS**

#### **1.1 Operating System**
- ✅ Ubuntu 20.04+ (recommended)
- ✅ macOS 10.15+ (supported)
- ✅ Windows with WSL (limited support)

#### **1.2 System Dependencies**
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-client supervisor git build-essential gfortran libopenblas-dev liblapack-dev pkg-config python3-dev

# macOS
brew install python3 postgresql supervisor git
```

#### **1.3 Python Requirements**
- ✅ Python 3.8+ (required)
- ✅ Virtual environment capability
- ✅ pip package manager

---

### **PHASE 2: REPOSITORY SETUP**

#### **2.1 Clone Repository**
```bash
git clone <repository-url>
cd rec_io
```

#### **2.2 Verify Repository Structure**
```
rec_io/
├── backend/
│   ├── main.py
│   ├── trade_manager.py
│   ├── active_trade_supervisor.py
│   ├── supervisord.conf (BROKEN - needs regeneration)
│   └── core/
│       ├── config/
│       │   ├── MASTER_PORT_MANIFEST.json
│       │   └── database.py
│       └── port_config.py
├── frontend/
├── scripts/
├── requirements.txt
├── requirements-core.txt
└── install.py
```

---

### **PHASE 3: DATABASE SETUP**

#### **3.1 PostgreSQL Installation & Configuration**
```bash
# Start PostgreSQL service
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database and user
sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';"
sudo -u postgres psql -c "CREATE DATABASE rec_io_db OWNER rec_io_user;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;"
```

#### **3.2 Database Schema Creation**
**CRITICAL**: The system expects these schemas and tables to exist:

```sql
-- Create schemas
CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS live_data;

-- Users schema tables
CREATE TABLE users.trades_0001 (
    id SERIAL PRIMARY KEY,
    ticket_id VARCHAR(255),
    date DATE,
    time TIME,
    strike DECIMAL(10,2),
    side VARCHAR(10),
    buy_price DECIMAL(10,2),
    position INTEGER,
    contract VARCHAR(255),
    ticker VARCHAR(50),
    symbol VARCHAR(10),
    market VARCHAR(50),
    trade_strategy VARCHAR(100),
    symbol_open DECIMAL(10,2),
    momentum DECIMAL(10,4),
    prob DECIMAL(10,4),
    fees DECIMAL(10,2),
    diff DECIMAL(10,4),
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users.active_trades_0001 (
    id SERIAL PRIMARY KEY,
    trade_id INTEGER REFERENCES users.trades_0001(id),
    ticket_id VARCHAR(255),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users.auto_trade_settings_0001 (
    id INTEGER PRIMARY KEY DEFAULT 1,
    auto_entry BOOLEAN DEFAULT FALSE,
    auto_stop BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users.trade_preferences_0001 (
    id INTEGER PRIMARY KEY DEFAULT 1,
    trade_strategy VARCHAR(100) DEFAULT 'Hourly HTC',
    position_size INTEGER DEFAULT 1,
    multiplier INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users.trade_history_preferences_0001 (
    id INTEGER PRIMARY KEY DEFAULT 1,
    page_size INTEGER DEFAULT 50,
    last_search_timestamp BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Live data schema tables
CREATE TABLE live_data.btc_price_log (
    id SERIAL PRIMARY KEY,
    price DECIMAL(15,2),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE live_data.eth_price_log (
    id SERIAL PRIMARY KEY,
    price DECIMAL(15,2),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default data
INSERT INTO users.auto_trade_settings_0001 (id, auto_entry, auto_stop) VALUES (1, FALSE, TRUE) ON CONFLICT (id) DO NOTHING;
INSERT INTO users.trade_preferences_0001 (id, trade_strategy, position_size, multiplier) VALUES (1, 'Hourly HTC', 1, 1) ON CONFLICT (id) DO NOTHING;
INSERT INTO users.trade_history_preferences_0001 (id, page_size, last_search_timestamp) VALUES (1, 50, 0) ON CONFLICT (id) DO NOTHING;
```

---

### **PHASE 4: PYTHON ENVIRONMENT**

#### **4.1 Virtual Environment Setup**
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

#### **4.2 Dependencies Installation**
```bash
# Try full requirements first
pip install -r requirements.txt

# If scipy fails, use core requirements
pip install -r requirements-core.txt
```

#### **4.3 Environment Variables**
**CRITICAL**: Set these environment variables:

```bash
# Database configuration
export DB_HOST=localhost
export DB_NAME=rec_io_db
export DB_USER=rec_io_user
export DB_PASSWORD=rec_io_password
export DB_PORT=5432

# System configuration
export PYTHONPATH=/path/to/rec_io
export PYTHONGC=1
export PYTHONDNSCACHE=1
```

---

### **PHASE 5: USER PROFILE SETUP**

#### **5.1 Create User Directory Structure**
```bash
mkdir -p backend/data/users/user_0001/{credentials/kalshi-credentials/{prod,demo},preferences,trade_history,active_trades,accounts}
chmod 700 backend/data/users/user_0001/credentials
```

#### **5.2 Create User Info File**
```bash
cat > backend/data/users/user_0001/user_info.json << EOF
{
  "user_id": "user_0001",
  "name": "New User",
  "email": "user@example.com",
  "account_type": "user",
  "created": "$(pwd)"
}
EOF
```

#### **5.3 Kalshi Credentials (Optional)
```bash
# Create credential files (user must fill in actual values)
touch backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
touch backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.pem
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.pem
```

---

### **PHASE 6: SUPERVISOR CONFIGURATION**

#### **6.1 Generate Dynamic Supervisor Config**
**CRITICAL**: The existing `backend/supervisord.conf` is broken. Must generate a new one:

```bash
# Create a script to generate supervisor config
cat > scripts/generate_supervisor_config.sh << 'EOF'
#!/bin/bash

PROJECT_ROOT=$(pwd)
VENV_PATH="$PROJECT_ROOT/venv"
PYTHON_PATH="$VENV_PATH/bin/python"

cat > backend/supervisord.conf << SUPERVISOR_EOF
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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

[program:kalshi_api_watchdog]
command=$PYTHON_PATH $PROJECT_ROOT/backend/api/kalshi-api/kalshi_api_watchdog.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/kalshi_api_watchdog.err.log
stdout_logfile=$PROJECT_ROOT/logs/kalshi_api_watchdog.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

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
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"

[program:unified_production_coordinator]
command=$PYTHON_PATH $PROJECT_ROOT/backend/unified_production_coordinator.py
directory=$PROJECT_ROOT
autostart=true
autorestart=true
startretries=3
stopasgroup=true
killasgroup=true
stderr_logfile=$PROJECT_ROOT/logs/unified_production_coordinator.err.log
stdout_logfile=$PROJECT_ROOT/logs/unified_production_coordinator.out.log
environment=PATH="$VENV_PATH/bin",PYTHONPATH="$PROJECT_ROOT",PYTHONGC=1,PYTHONDNSCACHE=1,DB_HOST="localhost",DB_NAME="rec_io_db",DB_USER="rec_io_user",DB_PASSWORD="rec_io_password",DB_PORT="5432"
SUPERVISOR_EOF

echo "✅ Generated supervisor configuration"
EOF

chmod +x scripts/generate_supervisor_config.sh
```

#### **6.2 Create Logs Directory**
```bash
mkdir -p logs
```

---

### **PHASE 7: SYSTEM STARTUP**

#### **7.1 Generate Supervisor Config**
```bash
./scripts/generate_supervisor_config.sh
```

#### **7.2 Start Supervisor**
```bash
supervisord -c backend/supervisord.conf
```

#### **7.3 Check Service Status**
```bash
supervisorctl -c backend/supervisord.conf status
```

#### **7.4 Monitor Logs**
```bash
tail -f logs/*.err.log
```

---

### **PHASE 8: VERIFICATION**

#### **8.1 Database Connection Test**
```bash
python3 -c "
from backend.core.config.database import test_database_connection
success, message = test_database_connection()
print(f'Database test: {message}')
"
```

#### **8.2 Service Health Check**
```bash
curl http://localhost:3000/health
```

#### **8.3 Port Verification**
```bash
netstat -tlnp | grep -E "(3000|4000|8001|8007|8009|8004|8005|8010)"
```

---

## 🚨 TROUBLESHOOTING GUIDE

### **Common Issues & Solutions**

#### **Issue 1: Services Fail with Exit Status 1**
- **Cause**: Database connection failure
- **Solution**: Verify PostgreSQL is running and credentials are correct

#### **Issue 2: Services Fail with Exit Status 2**
- **Cause**: Missing dependencies or import errors
- **Solution**: Check Python virtual environment and package installation

#### **Issue 3: Supervisor Config Errors**
- **Cause**: Hardcoded paths in supervisord.conf
- **Solution**: Regenerate supervisor config using the script above

#### **Issue 4: Database Schema Errors**
- **Cause**: Missing tables or schemas
- **Solution**: Run the complete database schema creation script

#### **Issue 5: Environment Variable Issues**
- **Cause**: Missing or incorrect environment variables
- **Solution**: Set all required environment variables as shown above

---

## 📝 DEPLOYMENT COMMAND SEQUENCE

Here's the exact sequence of commands to run on a fresh machine:

```bash
# 1. System dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-client supervisor git build-essential gfortran libopenblas-dev liblapack-dev pkg-config python3-dev

# 2. Clone repository
git clone <repository-url>
cd rec_io

# 3. PostgreSQL setup
sudo systemctl start postgresql
sudo systemctl enable postgresql
sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';"
sudo -u postgres psql -c "CREATE DATABASE rec_io_db OWNER rec_io_user;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;"

# 4. Database schema (run the SQL script above)
psql -h localhost -U rec_io_user -d rec_io_db -f database_schema.sql

# 5. Python environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-core.txt

# 6. User setup
mkdir -p backend/data/users/user_0001/{credentials/kalshi-credentials/{prod,demo},preferences,trade_history,active_trades,accounts}
chmod 700 backend/data/users/user_0001/credentials

# 7. Generate supervisor config
./scripts/generate_supervisor_config.sh

# 8. Create logs directory
mkdir -p logs

# 9. Start system
supervisord -c backend/supervisord.conf

# 10. Check status
supervisorctl -c backend/supervisord.conf status
```

---

## ✅ SUCCESS CRITERIA

The deployment is successful when:

1. ✅ All supervisor services show "RUNNING" status
2. ✅ Database connection test passes
3. ✅ Main app responds at http://localhost:3000/health
4. ✅ No error logs in `logs/*.err.log`
5. ✅ All required ports are listening
6. ✅ User can access the web interface

---

## 🔧 MAINTENANCE NOTES

- **Logs**: Check `logs/*.err.log` for service errors
- **Database**: Monitor PostgreSQL logs with `sudo journalctl -u postgresql`
- **Supervisor**: Use `supervisorctl -c backend/supervisord.conf` for service management
- **Restart**: Use `./scripts/MASTER_RESTART.sh` for full system restart

---

**This guide covers EVERYTHING needed for a fresh deployment. Follow it step-by-step and the system will work.**
