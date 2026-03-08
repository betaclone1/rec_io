# Digital Ocean Deployment V2 - Comprehensive Checklist
## Second Attempt with Lessons Learned from Failed Deployment

**Date**: January 27, 2025  
**Purpose**: Successful deployment with all critical issues resolved  
**Goal**: True mirror image of locally functional system on Digital Ocean  
**Status**: 🔴 **NOT STARTED** - Requires critical fixes first

---

## 🚨 **LESSONS LEARNED FROM FAILED DEPLOYMENT**

### **What Went Wrong:**
1. **❌ Insufficient Pre-Deployment Audit**: Critical hardcoded paths were missed
2. **❌ System-Specific Dependencies**: macOS vs Ubuntu differences were significant
3. **❌ Import Path Failures**: `ModuleNotFoundError: No module named 'backend'` on server
4. **❌ Process Detection Issues**: Local path patterns failed on Ubuntu
5. **❌ Supervisor Configuration**: Path mismatches between environments

### **Key Insights:**
- **Hardcoded paths are everywhere**: Not just in obvious places
- **Environment differences matter**: macOS vs Ubuntu have different tool locations
- **Import paths are critical**: PYTHONPATH issues cause immediate failures
- **Process detection needs adaptation**: Local patterns don't work on server
- **Frontend displays need updating**: Shows local paths to users

---

## 🔧 **PHASE 1: CRITICAL FIXES (REQUIRED BEFORE DEPLOYMENT)**

### **1.1 Dynamic Project Root Detection** ✅
- [x] **File**: `backend/util/paths.py` (enhanced existing file)
  - [x] Enhanced existing `get_project_root()` function
  - [x] Added dynamic path detection functions (`get_supervisorctl_path()`, `get_system_type()`, `get_dynamic_project_root()`)
  - [x] Preserved all existing functionality while adding deployment compatibility
  - [x] Tested on macOS environment successfully

- [ ] **Files**: All files with hardcoded `/Users/ericwais1/rec_io_20`
  - [ ] `backend/main.py` (Lines 1887, 2935, 2985, 3026, 3066)
  - [ ] `backend/system_monitor.py` (Line 152)
  - [ ] Replace with dynamic detection calls

### **1.2 Cross-Platform Supervisor Path Detection** ✅
- [x] **File**: `backend/main.py` (Lines 2939, 2990, 3031, 3075)
  - [x] Replace `/opt/homebrew/bin/supervisorctl` with dynamic detection
  - [x] Add macOS vs Ubuntu path detection logic
  - [x] Update PATH environment variable handling

- [x] **Files**: All supervisor config references
  - [x] `backend/system_monitor.py` (Lines 78, 321, 569, 760, 777)
  - [x] `backend/cascading_failure_detector.py` (Lines 84, 335)
  - [x] `backend/core/port_flush.py` (Lines 75, 79, 83)
  - [x] Replace `backend/supervisord.conf` with dynamic paths

### **1.3 Import Path Fixes** ✅
- [x] **File**: `backend/main.py` (Line 31)
  - [x] Fix `from backend.util.paths import get_project_root`
  - [x] Ensure PYTHONPATH is set correctly
  - [x] Test import resolution on server environment

- [x] **Files**: All relative imports
  - [x] Verify all `from backend.` imports work
  - [x] Test import resolution in virtual environment
  - [x] Ensure no circular import issues

### **1.4 Process Detection Updates** ✅
- [x] **File**: `backend/system_monitor.py` (Line 152)
  - [x] Replace hardcoded path check with dynamic detection
  - [x] Update process filtering logic for Ubuntu
  - [x] Test process detection on both environments

### **1.5 Frontend Directory Display Fixes** ✅
- [x] **File**: `frontend/terminal-control.html` (Lines 165, 302)
  - [x] Replace hardcoded directory display
  - [x] Add dynamic directory detection
  - [x] Test on both local and server environments

### **1.6 MASTER_RESTART.sh Cross-Platform Updates** ✅
- [x] **File**: `scripts/MASTER_RESTART.sh`
  - [x] Add OS detection logic
  - [x] Update supervisor paths for Ubuntu
  - [x] Test on both macOS and Ubuntu
  - [x] Verify process killing works on both systems

---

## 🧪 **PHASE 2: LOCAL TESTING (REQUIRED)** ✅

### **2.1 Fix Verification** ✅
- [x] **Test dynamic path detection**
  - [x] Verify `get_project_root()` works on macOS
  - [x] Test in virtual environment
  - [x] Check all import paths resolve correctly

- [x] **Test supervisor integration**
  - [x] Verify supervisor status endpoint works
  - [x] Test supervisor restart functionality
  - [x] Check process detection accuracy

- [x] **Test frontend functionality**
  - [x] Verify supervisor status displays correctly
  - [x] Test terminal control interface
  - [x] Check directory displays are dynamic

### **2.2 MASTER_RESTART Testing** ✅
- [x] **Test complete system restart**
  - [x] Run `./scripts/MASTER_RESTART.sh`
  - [x] Verify all services start correctly
  - [x] Check all ports are properly assigned
  - [x] Test supervisor status after restart

- [x] **Test individual service restarts**
  - [x] Test each service restart via supervisor
  - [x] Verify no import errors occur
  - [x] Check database connections work

### **2.3 Database Connectivity Testing** ✅
- [x] **Test PostgreSQL connections**
  - [x] Verify all services connect to database
  - [x] Test database queries work correctly
  - [x] Check environment variable loading

### **2.4 Frontend Terminal Controls Audit** ✅
- [x] **Audit system.html terminal controls**
  - [x] Verify all API endpoints are environment agnostic
  - [x] Check for hardcoded paths or localhost references
  - [x] Test supervisor status and restart functionality

- [x] **Fix terminal-control.html**
  - [x] Replace hardcoded directory display with dynamic detection
  - [x] Update supervisor commands to use proper config paths
  - [x] Test all terminal control functions

- [x] **Verify cross-platform compatibility**
  - [x] All frontend controls use API endpoints
  - [x] No hardcoded macOS paths remain
  - [x] Terminal commands work on both local and remote systems

### **2.5 System Usage Numbers Audit** ✅
- [x] **Audit system resource monitoring**
  - [x] Verify CPU, Memory, Disk usage are dynamically calculated
  - [x] Check for hardcoded capacity values
  - [x] Test system capacity detection

- [x] **Enhance system monitoring**
  - [x] Add real-time system capacity data to API responses
  - [x] Update backend to provide actual GB values
  - [x] Remove hardcoded fallback values from frontend

- [x] **Verify environment agnostic resource monitoring**
  - [x] System usage numbers read actual system capacity
  - [x] No hardcoded values for total memory/disk capacity
  - [x] Resource monitoring works on any system (macOS/Ubuntu)

### **2.6 Droplet Cleanup** ✅
- [x] **Stop all running processes**
  - [x] Stop all supervisor services
  - [x] Kill any remaining Python processes
  - [x] Verify no trading system processes are running

- [x] **Remove all project files**
  - [x] Delete /opt/trading_system directory
  - [x] Delete /opt/digitalocean directory
  - [x] Clean up macOS metadata files

- [x] **Clean up system configuration**
  - [x] Remove supervisor configuration files
  - [x] Remove environment files
  - [x] Update supervisor to remove process groups

---

## 🚀 **PHASE 3: SERVER PREPARATION** ✅

### **3.1 Server Environment Setup** ✅
- [x] **Verify server specifications**
  - [x] Ubuntu 22.04 LTS installed
  - [x] Python 3.10.12 available
  - [x] PostgreSQL 14.18 installed
  - [x] Supervisor 4.2.1 installed and configured

- [x] **Create server-specific configuration**
  - [x] Create `.env` file with server database credentials
  - [x] Set up server-specific supervisor configuration
  - [x] Configure server-specific paths

### **3.2 Database Migration Preparation** ✅
- [x] **Prepare database backup**
  - [x] Create complete PostgreSQL dump (1.5GB)
  - [x] Verify backup integrity
  - [x] Test backup restoration locally

- [x] **Plan database restoration**
  - [x] Document restoration steps
  - [x] Prepare server database setup
  - [x] Test database connectivity

---

## 📦 **PHASE 4: DEPLOYMENT EXECUTION** ✅

### **4.1 Code Upload** ✅
- [x] **Create deployment package**
  - [x] Exclude virtual environment
  - [x] Exclude log files
  - [x] Exclude local database files
  - [x] Include all fixed code

- [x] **Upload to server**
  - [x] Upload package to `/tmp/` (3.1GB)
  - [x] Extract to `/opt/trading_system/`
  - [x] Set correct permissions

### **4.2 Environment Setup** ✅
- [x] **Create virtual environment**
  - [x] Install Python dependencies (fixed numpy/pandas for Python 3.10)
  - [x] Verify all packages install correctly
  - [x] Test import resolution

- [x] **Configure environment variables**
  - [x] Set up database credentials
  - [x] Configure server-specific paths
  - [x] Test environment variable loading

### **4.3 Database Restoration** ✅
- [x] **Restore database**
  - [x] Upload database backup (1.5GB)
  - [x] Restore to server PostgreSQL (302 trades)
  - [x] Verify data integrity
  - [x] Test database connectivity

### **4.4 Service Configuration** ✅
- [x] **Configure supervisor**
  - [x] Update supervisor configuration for server paths
  - [x] Set up log file paths
  - [x] Configure environment variables

- [x] **Start services**
  - [x] Start supervisor
  - [x] Verify all services start correctly
  - [x] Check for any import or path errors

---

## ✅ **PHASE 5: VERIFICATION & TESTING**

### **5.1 Service Health Checks**
- [ ] **Verify all services running**
  - [ ] Check supervisor status
  - [ ] Verify all 8 services are RUNNING
  - [ ] Check for any ERROR or FATAL states

- [ ] **Test service connectivity**
  - [ ] Test main app on port 3000
  - [ ] Test active trade supervisor on port 8007
  - [ ] Test all other service ports

### **5.2 Frontend Functionality**
- [ ] **Test web interface**
  - [ ] Access main interface at server IP:3000
  - [ ] Verify all pages load correctly
  - [ ] Test real-time data updates

- [ ] **Test admin functions**
  - [ ] Test supervisor status display
  - [ ] Test terminal control interface
  - [ ] Test system restart functionality

### **5.3 Database Functionality**
- [ ] **Test database operations**
  - [ ] Verify active trades display
  - [ ] Test strike table data
  - [ ] Check historical data access

### **5.4 API Endpoint Testing**
- [ ] **Test all API endpoints**
  - [ ] `/api/active_trades`
  - [ ] `/api/strike_tables/btc`
  - [ ] `/api/watchlist/btc`
  - [ ] `/api/db/system_health`
  - [ ] `/api/admin/supervisor-status`

---

## 🔄 **PHASE 6: MONITORING & MAINTENANCE**

### **6.1 Continuous Monitoring**
- [ ] **Set up log monitoring**
  - [ ] Monitor supervisor logs
  - [ ] Monitor application logs
  - [ ] Set up error alerting

- [ ] **Performance monitoring**
  - [ ] Monitor CPU and memory usage
  - [ ] Monitor database performance
  - [ ] Track API response times

### **6.2 Backup Strategy**
- [ ] **Database backups**
  - [ ] Set up automated database backups
  - [ ] Test backup restoration
  - [ ] Document backup procedures

- [ ] **Code deployment**
  - [ ] Plan for future code updates
  - [ ] Document deployment procedures
  - [ ] Set up version control integration

---

## 🎯 **SUCCESS CRITERIA**

### **Functional Requirements**
- [ ] **All 8 services running** under supervisor
- [ ] **Frontend accessible** at server IP:3000
- [ ] **Database fully functional** with all local data
- [ ] **All API endpoints responding** correctly
- [ ] **Real-time data updates** working
- [ ] **Admin functions** (supervisor status, terminal) working

### **Performance Requirements**
- [ ] **Response times** under 2 seconds for all API calls
- [ ] **Memory usage** under 4GB total
- [ ] **CPU usage** under 50% average
- [ ] **Database queries** completing in under 1 second

### **Reliability Requirements**
- [ ] **Services auto-restart** on failure
- [ ] **No import errors** in logs
- [ ] **No path-related errors** in logs
- [ ] **Database connections** stable

---

## 🚨 **RISK MITIGATION**

### **High-Risk Areas**
- [ ] **Import path issues**: Test thoroughly before deployment
- [ ] **Supervisor configuration**: Verify paths work on Ubuntu
- [ ] **Database connectivity**: Test with server credentials
- [ ] **Process detection**: Verify works on Ubuntu

### **Rollback Plan**
- [ ] **Keep local system functional** throughout process
- [ ] **Document all changes** for easy rollback
- [ ] **Test rollback procedures** before deployment
- [ ] **Have backup deployment strategy** ready

---

## 📋 **DEPLOYMENT COMMAND SEQUENCE**

```bash
# Phase 1: Fixes (Local)
# 1. Implement all critical fixes
# 2. Test locally with MASTER_RESTART
# 3. Verify all functionality works

# Phase 2: Server Setup
# 1. Create deployment package
tar -czf trading_system_v2_deploy.tar.gz --exclude=venv --exclude=logs --exclude=*.db .

# 2. Upload to server
scp trading_system_v2_deploy.tar.gz root@64.23.138.71:/tmp/

# 3. SSH to server
ssh root@64.23.138.71

# 4. Extract and setup
cd /opt
rm -rf trading_system  # Remove old deployment
tar -xzf /tmp/trading_system_v2_deploy.tar.gz
cd trading_system

# 5. Setup environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 6. Configure environment
cp .env.example .env
# Edit .env with server database credentials

# 7. Restore database
pg_dump -h localhost -U rec_io_user -d rec_io_db > /tmp/rec_io_db_backup.sql
scp root@64.23.138.71:/tmp/rec_io_db_backup.sql ./
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db < rec_io_db_backup.sql

# 8. Configure supervisor
cp backend/supervisord.conf /etc/supervisor/conf.d/trading_system.conf
# Edit supervisor config for server paths

# 9. Start services
supervisorctl reread
supervisorctl update
supervisorctl start all

# 10. Verify deployment
curl http://localhost:3000
supervisorctl status
```

---

## 📊 **PROGRESS TRACKING**

### **Current Status**: 🔴 **NOT STARTED**
- [ ] Phase 1: Critical Fixes (0/6 complete)
- [ ] Phase 2: Local Testing (0/3 complete)
- [ ] Phase 3: Server Preparation (0/2 complete)
- [ ] Phase 4: Deployment Execution (0/4 complete)
- [ ] Phase 5: Verification & Testing (0/4 complete)
- [ ] Phase 6: Monitoring & Maintenance (0/2 complete)

### **Estimated Timeline**
- **Phase 1**: 4-5 hours (critical fixes)
- **Phase 2**: 2-3 hours (local testing)
- **Phase 3**: 1 hour (server prep)
- **Phase 4**: 2-3 hours (deployment)
- **Phase 5**: 1-2 hours (verification)
- **Phase 6**: 1 hour (monitoring setup)

**Total Estimated Time**: **11-15 hours**

---

*Last Updated: January 27, 2025*
*Checklist Version: 2.0 - Post-Failed Deployment*
*Status: Ready for Phase 1 execution*
