# COMPREHENSIVE DIGITAL OCEAN DEPLOYMENT GUIDE
## Verified System Specifications & Step-by-Step Deployment

**Date**: August 10, 2025  
**Target**: Digital Ocean Droplet (146.190.155.233)  
**SSH Key**: `60:c5:3a:ab:1c:75:52:6e:09:bf:4c:f1:96:81:bf:6c`  
**Goal**: Exact duplication of fully functional local system

---

## **VERIFIED SYSTEM SPECIFICATIONS**

### **PROCESSES & SERVICES**
- **Total Python Processes**: 13 (1 supervisord + 12 services)
- **Supervisor Services**: 12 total (all running)
- **Python Version**: 3.13.4 (both system and venv)
- **Python Path**: `/opt/homebrew/bin/python3` (Homebrew installation)

### **RUNNING SERVICES (12 TOTAL)**
1. **main_app** - CPU: 5.1%, Port: 3000 ✅
2. **trade_manager** - CPU: 0.0%, Port: 4000 ✅
3. **trade_executor** - CPU: 0.0%, Port: 8001 ✅
4. **active_trade_supervisor** - CPU: 0.0%, Port: 8007 ✅
5. **auto_entry_supervisor** - CPU: 0.0%, Port: 8009 ✅
6. **symbol_price_watchdog_btc** - CPU: 1.0% ✅
7. **symbol_price_watchdog_eth** - CPU: 0.7% ✅
8. **kalshi_account_sync** - CPU: 0.0%, Port: 8004 ✅
9. **kalshi_api_watchdog** - CPU: 1.6%, Port: 8005 ✅
10. **unified_production_coordinator** - CPU: 18.8%, Port: 8010 ✅
11. **cascading_failure_detector** - CPU: 0.0% ✅
12. **system_monitor** - CPU: 0.0% ✅

### **DATABASE SPECIFICATIONS**
- **Database Size**: 2093 MB (2.1GB)
- **Backup File**: 1.5GB (rec_io_db_backup.sql)
- **Total Trades**: 304
- **Total Fills**: 2153
- **Total Positions**: 2
- **Largest Table**: settlements_0001 (1062 MB)

### **CRITICAL DATA & CREDENTIALS**
- **User Data Directory**: 424MB
- **Kalshi Credentials**: 
  - Prod: `.env`, `kalshi.pem`, `kalshi-auth.txt`
  - Demo: `.env`, `kalshi.pem`
- **Log Directory**: 1.5GB (excluded from deployment)
- **Virtual Environment**: 279MB (excluded from deployment)

---

## **PHASE 1: PRE-DEPLOYMENT VERIFICATION**

### **1.1 Local System Health Check**
```bash
# Verify all 12 services are running
ps aux | grep python | grep -v grep | wc -l
# Expected: 13 (1 supervisord + 12 services)

# Check main app health
curl -s http://localhost:3000/health
# Expected: {"status":"healthy","service":"main_app","port":3000}

# Verify database connectivity
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) as total_trades FROM users.trades_0001;"
# Expected: 304

# Check all ports are responding
curl -s http://localhost:3000/api/ports
# Expected: JSON with all 9 service ports
```

### **1.2 Data Integrity Verification**
```bash
# Verify database backup exists and is complete
ls -la rec_io_db_backup.sql
# Expected: 1.5GB file

# Verify credentials exist
ls -la backend/data/users/user_0001/credentials/kalshi-credentials/prod/
ls -la backend/data/users/user_0001/credentials/kalshi-credentials/demo/
# Expected: .env, kalshi.pem files in both directories

# Verify critical data directories
du -sh backend/data
# Expected: ~424MB
```

---

## **PHASE 2: SERVER ENVIRONMENT SETUP**

### **2.1 SSH to Digital Ocean Droplet**
```bash
ssh root@146.190.155.233
```

### **2.2 System Update and Package Installation**
```bash
# Update system
apt update && apt upgrade -y

# Install required packages
apt install -y python3.13 python3.13-venv python3.13-dev
apt install -y postgresql postgresql-contrib
apt install -y supervisor
apt install -y curl wget git unzip

# Verify installations
python3.13 --version
# Expected: Python 3.13.x

psql --version
# Expected: PostgreSQL version

supervisord --version
# Expected: Supervisor version
```

### **2.3 PostgreSQL Setup**
```bash
# Start PostgreSQL service
systemctl start postgresql
systemctl enable postgresql

# Create database and user
sudo -u postgres psql -c "CREATE DATABASE rec_io_db;"
sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;"
sudo -u postgres psql -c "CREATE SCHEMA IF NOT EXISTS users;"
sudo -u postgres psql -c "CREATE SCHEMA IF NOT EXISTS live_data;"
sudo -u postgres psql -c "GRANT ALL ON SCHEMA users TO rec_io_user;"
sudo -u postgres psql -c "GRANT ALL ON SCHEMA live_data TO rec_io_user;"

# Test database connection
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT version();"
```

### **2.4 Directory Structure Setup**
```bash
# Create application directory
mkdir -p /opt/trading_system
cd /opt/trading_system

# Create required directories
mkdir -p logs
mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/prod
mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/demo
mkdir -p backend/data/users/user_0001/trade_history
mkdir -p backend/data/users/user_0001/active_trades
mkdir -p backend/data/users/user_0001/accounts

# Set proper permissions
chown -R root:root /opt/trading_system
chmod -R 755 /opt/trading_system
chmod -R 600 backend/data/users/user_0001/credentials/kalshi-credentials/*/.env
chmod -R 600 backend/data/users/user_0001/credentials/kalshi-credentials/*/kalshi.pem
```

---

## **PHASE 3: CODE TRANSFER & SETUP**

### **3.1 Create Deployment Package (Local)**
```bash
# From local machine, create deployment package
cd /Users/ericwais1/rec_io_20

# Create package excluding venv, logs, and git
tar -czf trading_system_deploy_$(date +%Y%m%d_%H%M%S).tar.gz \
  --exclude=venv \
  --exclude=logs \
  --exclude=.git \
  --exclude=*.db \
  --exclude=*.sql \
  --exclude=*.tar.gz \
  --exclude=*.zip \
  .

# Verify package size (should be ~500MB-1GB)
ls -la trading_system_deploy_*.tar.gz
```

### **3.2 Transfer Package to Server**
```bash
# Transfer from local to server
scp trading_system_deploy_*.tar.gz root@146.190.155.233:/tmp/

# SSH to server and extract
ssh root@146.190.155.233
cd /opt/trading_system
tar -xzf /tmp/trading_system_deploy_*.tar.gz

# Verify extraction
ls -la
# Expected: backend, frontend, requirements.txt, etc.
```

### **3.3 Virtual Environment Setup**
```bash
# Create virtual environment with Python 3.13
python3.13 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# Verify key packages
python -c "import psycopg2; print('psycopg2 OK')"
python -c "import fastapi; print('fastapi OK')"
python -c "import supervisor; print('supervisor OK')"
```

---

## **PHASE 4: DATABASE MIGRATION**

### **4.1 Transfer Database Backup**
```bash
# From local machine, transfer database backup
scp rec_io_db_backup.sql root@146.190.155.233:/tmp/

# On server, restore database
ssh root@146.190.155.233
cd /opt/trading_system

# Restore database
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db < /tmp/rec_io_db_backup.sql
```

### **4.2 Database Verification**
```bash
# Verify data integrity
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) as total_trades FROM users.trades_0001;"
# Expected: 304

psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) as total_fills FROM users.fills_0001;"
# Expected: 2153

psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) as total_positions FROM users.positions_0001;"
# Expected: 2

psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT pg_size_pretty(pg_database_size('rec_io_db'));"
# Expected: ~2093 MB
```

---

## **PHASE 5: CREDENTIALS & CONFIGURATION**

### **5.1 Transfer Credentials**
```bash
# From local machine, transfer credentials securely
scp -r backend/data/users/user_0001/credentials/kalshi-credentials/prod/* root@146.190.155.233:/opt/trading_system/backend/data/users/user_0001/credentials/kalshi-credentials/prod/
scp -r backend/data/users/user_0001/credentials/kalshi-credentials/demo/* root@146.190.155.233:/opt/trading_system/backend/data/users/user_0001/credentials/kalshi-credentials/demo/

# On server, set proper permissions
ssh root@146.190.155.233
chmod -R 600 /opt/trading_system/backend/data/users/user_0001/credentials/kalshi-credentials/*/.env
chmod -R 600 /opt/trading_system/backend/data/users/user_0001/credentials/kalshi-credentials/*/kalshi.pem
```

### **5.2 Environment Configuration**
```bash
# Create environment file
cd /opt/trading_system
cp backend/util/env.example .env

# Edit environment file
cat > .env << EOF
# PostgreSQL Connection Settings
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=rec_io_password

# System Configuration
TRADING_SYSTEM_HOST=146.190.155.233
AUTH_ENABLED=false
EOF

# Set proper permissions
chmod 600 .env
```

### **5.3 Supervisor Configuration**
```bash
# Copy supervisor configuration
cp backend/supervisord.conf /etc/supervisor/conf.d/trading_system.conf

# Update supervisor config for Ubuntu paths
sed -i 's|venv/bin/python|/opt/trading_system/venv/bin/python|g' /etc/supervisor/conf.d/trading_system.conf
sed -i 's|directory=.|directory=/opt/trading_system|g' /etc/supervisor/conf.d/trading_system.conf
sed -i 's|logs/|/opt/trading_system/logs/|g' /etc/supervisor/conf.d/trading_system.conf

# Reload supervisor configuration
supervisorctl reread
supervisorctl update
```

---

## **PHASE 6: SERVICE DEPLOYMENT**

### **6.1 Start Services Individually**
```bash
# Start services one by one to catch any errors
supervisorctl start main_app
sleep 5
supervisorctl status main_app

supervisorctl start trade_manager
sleep 2
supervisorctl status trade_manager

supervisorctl start trade_executor
sleep 2
supervisorctl status trade_executor

supervisorctl start active_trade_supervisor
sleep 2
supervisorctl status active_trade_supervisor

supervisorctl start auto_entry_supervisor
sleep 2
supervisorctl status auto_entry_supervisor

supervisorctl start symbol_price_watchdog_btc
sleep 2
supervisorctl status symbol_price_watchdog_btc

supervisorctl start symbol_price_watchdog_eth
sleep 2
supervisorctl status symbol_price_watchdog_eth

supervisorctl start kalshi_account_sync
sleep 2
supervisorctl status kalshi_account_sync

supervisorctl start kalshi_api_watchdog
sleep 2
supervisorctl status kalshi_api_watchdog

supervisorctl start unified_production_coordinator
sleep 2
supervisorctl status unified_production_coordinator

supervisorctl start cascading_failure_detector
sleep 2
supervisorctl status cascading_failure_detector

supervisorctl start system_monitor
sleep 2
supervisorctl status system_monitor
```

### **6.2 Verify All Services Running**
```bash
# Check all services status
supervisorctl status

# Expected output: All 12 services should show RUNNING
# If any show ERROR or FATAL, check logs:
# tail -f /opt/trading_system/logs/[service_name].err.log
```

---

## **PHASE 7: COMPREHENSIVE TESTING**

### **7.1 Service Health Checks**
```bash
# Test main app
curl -s http://146.190.155.233:3000/health
# Expected: {"status":"healthy","service":"main_app","port":3000}

# Test all API endpoints
curl -s http://146.190.155.233:3000/api/ports
curl -s http://146.190.155.233:3000/api/active_trades
curl -s http://146.190.155.233:3000/api/strike_tables/btc
curl -s http://146.190.155.233:3000/api/watchlist/btc

# Test database connectivity
curl -s http://146.190.155.233:3000/api/db/system_health
curl -s http://146.190.155.233:3000/api/db/trades

# Test supervisor status
curl -s -X POST http://146.190.155.233:3000/api/admin/supervisor-status
```

### **7.2 Frontend Testing**
```bash
# Test main frontend
curl -s http://146.190.155.233:3000/ | head -10
# Expected: HTML content

# Test login page
curl -s http://146.190.155.233:3000/login | head -10
# Expected: HTML content

# Test terminal control
curl -s http://146.190.155.233:3000/terminal-control.html | head -10
# Expected: HTML content
```

### **7.3 Database Functionality Testing**
```bash
# Test database queries
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.trades_0001 WHERE status = 'open';"
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.fills_0001 WHERE created_at > NOW() - INTERVAL '1 hour';"
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM live_data.btc_live_strikes;"
```

### **7.4 Performance Monitoring**
```bash
# Monitor system resources
htop

# Check process status
ps aux | grep python | grep -v grep

# Monitor logs for errors
tail -f /opt/trading_system/logs/*.err.log

# Check disk usage
df -h

# Check memory usage
free -h
```

---

## **PHASE 8: FINAL VERIFICATION**

### **8.1 Complete System Verification**
```bash
# Verify all 12 services are running
supervisorctl status | grep RUNNING | wc -l
# Expected: 12

# Verify all ports are accessible
netstat -tlnp | grep python | wc -l
# Expected: 9 (services with ports)

# Verify database connectivity from all services
psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.trades_0001;"
# Expected: 304

# Verify frontend is fully functional
curl -s http://146.190.155.233:3000/health
# Expected: Healthy status
```

### **8.2 Security Verification**
```bash
# Verify credentials are secure
ls -la /opt/trading_system/backend/data/users/user_0001/credentials/kalshi-credentials/*/
# Expected: 600 permissions on .env and .pem files

# Verify environment file is secure
ls -la /opt/trading_system/.env
# Expected: 600 permissions

# Test SSH access
ssh root@146.190.155.233 "echo 'SSH access confirmed'"
```

### **8.3 Documentation**
```bash
# Create deployment summary
cat > /opt/trading_system/DEPLOYMENT_SUMMARY.md << EOF
# Deployment Summary
Date: $(date)
Server: 146.190.155.233
Status: SUCCESS

## Services Deployed: 12
- main_app (port 3000)
- trade_manager (port 4000)
- trade_executor (port 8001)
- active_trade_supervisor (port 8007)
- auto_entry_supervisor (port 8009)
- symbol_price_watchdog_btc
- symbol_price_watchdog_eth
- kalshi_account_sync (port 8004)
- kalshi_api_watchdog (port 8005)
- unified_production_coordinator (port 8010)
- cascading_failure_detector
- system_monitor

## Database
- Size: $(psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT pg_size_pretty(pg_database_size('rec_io_db'));" | tail -1)
- Trades: $(psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.trades_0001;" | tail -1)
- Fills: $(psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM users.fills_0001;" | tail -1)

## Access
- Frontend: http://146.190.155.233:3000
- Health Check: http://146.190.155.233:3000/health
- SSH: ssh root@146.190.155.233
EOF
```

---

## **SUCCESS CRITERIA**

### **Functional Requirements**
- [ ] All 12 services running under supervisor
- [ ] Frontend accessible at http://146.190.155.233:3000
- [ ] Database fully functional with all 304 trades
- [ ] All API endpoints responding correctly
- [ ] Real-time data updates working
- [ ] Admin functions (supervisor status, terminal) working

### **Performance Requirements**
- [ ] Response times under 2 seconds for all API calls
- [ ] Memory usage under 4GB total
- [ ] CPU usage under 50% average
- [ ] Database queries completing in under 1 second

### **Security Requirements**
- [ ] Credentials properly secured (600 permissions)
- [ ] SSH access working
- [ ] No sensitive data exposed
- [ ] Environment variables properly configured

### **Data Integrity Requirements**
- [ ] All 304 trades transferred
- [ ] All 2153 fills transferred
- [ ] All 2 positions transferred
- [ ] Database size matches local (2093 MB)

---

## **TROUBLESHOOTING**

### **Common Issues**
1. **Import Errors**: Check PYTHONPATH and virtual environment
2. **Database Connection**: Verify PostgreSQL credentials and permissions
3. **Port Conflicts**: Check port assignments in MASTER_PORT_MANIFEST.json
4. **Permission Errors**: Verify file permissions on credentials and logs
5. **Service Failures**: Check individual service logs in /opt/trading_system/logs/

### **Rollback Plan**
1. Keep local system fully functional
2. Document all changes made during deployment
3. Have backup of original server state
4. Test rollback procedures before deployment

---

**Deployment Complete**: System should be indistinguishable from local environment
