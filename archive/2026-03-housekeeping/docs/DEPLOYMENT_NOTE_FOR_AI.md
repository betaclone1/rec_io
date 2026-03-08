# DEPLOYMENT NOTE FOR AI

## 🚨 **YOU ARE ON A BRAND NEW MACHINE**

You have nothing but the git repository. This document tells you EVERYTHING you need to do to get the system running.

**⚠️ CRITICAL**: This system has been tested and all known issues have been resolved. The installation script addresses:
- ✅ WebSocket compatibility issues (Python 3.13)
- ✅ Supervisor startup and process management
- ✅ Port conflicts and zombie processes
- ✅ Database initialization and verification
- ✅ Dynamic path configuration
- ✅ Credential setup and validation
- ✅ Missing price watchdog services (FIXED)
- ✅ Python module import path problems (FIXED)

---

## 🎯 **STEP 1: INSTALL SYSTEM REQUIREMENTS**

**First, install the required system packages:**

### **macOS:**
```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install required packages
brew install python3 postgresql supervisor

# Start PostgreSQL
brew services start postgresql
```

### **Linux (Ubuntu/Debian):**
```bash
# Update package list
sudo apt update

# Install required packages
sudo apt install python3 python3-pip python3-venv postgresql postgresql-contrib supervisor

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### **Linux (CentOS/RHEL):**
```bash
# Install required packages
sudo yum install python3 python3-pip postgresql postgresql-server supervisor

# Initialize and start PostgreSQL
sudo postgresql-setup initdb
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

---

## 🎯 **STEP 2: SETUP DATABASE**

**Create the database and user:**

```bash
# Create database user
sudo -u postgres psql -c "CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';"

# Create database
sudo -u postgres psql -c "CREATE DATABASE rec_io_db OWNER rec_io_user;"

# Grant privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;"
```

---

## 🎯 **STEP 3: SETUP PYTHON ENVIRONMENT**

**Create virtual environment and install dependencies:**

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies (includes WebSocket compatibility fixes)
pip install -r requirements-core.txt
```

---

## 🎯 **STEP 4: RUN THE INSTALLATION SCRIPT**

**Now run the automated installation script:**

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Run the installation
./scripts/complete_installation.sh
```

**The script will automatically:**
- ✅ Configure the database schema (with fallback to code-based initialization)
- ✅ Create user directory structure
- ✅ Generate dynamic configuration files (no hardcoded paths)
- ✅ Prompt for Kalshi credentials (if you have them)
- ✅ Use MASTER_RESTART script to avoid port conflicts
- ✅ Start all services in proper order
- ✅ Verify everything is working

---

## ✅ **SUCCESS INDICATORS**

The installation is successful when you see:

- ✅ **"Installation completed successfully!"** message
- ✅ **Web interface responds**: `curl http://localhost:3000/health` returns 200
- ✅ **Services running**: `./scripts/MASTER_RESTART.sh status` shows services RUNNING
- ✅ **No critical errors**: `tail logs/*.err.log` shows no fatal errors
- ✅ **All ports listening**: Ports 3000, 4000, 8001, 8007, 8009 should be active

---

## 🔐 **KALSHI CREDENTIALS**

**During installation, you will be prompted for Kalshi credentials:**

- **If you have credentials**: Enter them when prompted
- **If you don't have credentials**: Choose "skip" - system will work but trading features won't function
- **If you skip**: You can add credentials later by editing the credential files

**Credential files will be created in:**
- `backend/data/users/user_0001/credentials/kalshi-credentials/prod/`
- `backend/api/kalshi-api/kalshi-credentials/prod/`

---

## 🚨 **IF INSTALLATION FAILS**

### **1. Check the error message**
The script will tell you exactly what failed.

### **2. Common fixes**
```bash
# If supervisor issues:
./scripts/MASTER_RESTART.sh

# If database connection fails:
# Make sure PostgreSQL is running:
brew services start postgresql  # macOS
sudo systemctl start postgresql  # Linux

# If permission issues:
chmod +x scripts/*.sh
chmod 700 backend/data/users/user_0001/credentials

# If Python environment issues:
source venv/bin/activate
pip install -r requirements-core.txt

# If port conflicts (zombie processes):
./scripts/MASTER_RESTART.sh emergency
```

### **3. Manual database setup (if automated fails)**
```bash
# Connect to database and create schema manually
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -f scripts/setup_database_schema.sql
```

### **4. WebSocket compatibility issues (if any)**
The system includes fixes for Python 3.13 + WebSockets 15.0.1 compatibility:
- ✅ `extra_headers` → `additional_headers` fix applied
- ✅ All WebSocket connections tested and working

---

## 📊 **VERIFICATION**

After installation, verify everything works:

```bash
# Check services
./scripts/MASTER_RESTART.sh status

# Check web interface
curl http://localhost:3000/health

# Check logs
tail logs/*.log

# Check port usage
lsof -i :3000
lsof -i :4000
lsof -i :8001
```

---

## 🎯 **WHAT THE SYSTEM DOES**

- **Web Interface**: http://localhost:3000
- **Trade Management**: Port 4000
- **Trade Execution**: Port 8001
- **Active Trade Monitoring**: Port 8007
- **Auto Entry System**: Port 8009

Background services run without ports (normal behavior).

---

## 🔧 **KNOWN ISSUES RESOLVED**

This installation addresses all previously identified issues:

1. **✅ WebSocket Compatibility**: Fixed Python 3.13 + WebSockets 15.0.1 compatibility
2. **✅ Supervisor Startup**: Uses MASTER_RESTART script for proper process management
3. **✅ Port Conflicts**: Comprehensive port flushing and process cleanup
4. **✅ Database Initialization**: Code-based fallback if SQL schema file missing
5. **✅ Dynamic Paths**: All configuration files generated dynamically
6. **✅ Credential Setup**: Interactive setup with proper file permissions
7. **✅ Service Verification**: Comprehensive health checks and monitoring

---

## 📞 **SUPPORT**

If you encounter issues:
1. Check the error message from the installation script
2. Run `./scripts/MASTER_RESTART.sh status` to see service status
3. Check `logs/*.log` for detailed error information
4. Make sure all system requirements are installed
5. Use `./scripts/MASTER_RESTART.sh emergency` for complete system reset

---

## 📋 **COMPLETE CHECKLIST**

Before running the installation script, ensure you have:

- [ ] Python 3.8+ installed
- [ ] PostgreSQL installed and running
- [ ] Supervisor installed
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -r requirements-core.txt`)
- [ ] Database user and database created
- [ ] Scripts made executable (`chmod +x scripts/*.sh`)

---

## 🎯 **EXPECTED OUTCOME**

After successful installation:
- ✅ All 12 services running (main_app, trade_manager, trade_executor, etc.)
- ✅ Web interface accessible at http://localhost:3000
- ✅ Database fully configured with all tables
- ✅ Credential setup completed (if provided)
- ✅ No port conflicts or zombie processes
- ✅ All WebSocket connections working
- ✅ System ready for trading operations

---

**That's it. Follow these steps in order and the system will be running.**
