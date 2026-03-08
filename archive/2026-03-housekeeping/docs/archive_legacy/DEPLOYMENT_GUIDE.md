# 🚀 REC.IO Trading System - Deployment Guide

## Quick Start

### **Step 1: Check System Requirements**
```bash
./scripts/check_portability.sh
```

### **Step 2: Set Up Environment**
```bash
# Create virtual environment (if not exists)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### **Step 3: Configure Credentials**
```bash
# Create credentials directories
mkdir -p backend/api/kalshi-api/kalshi-credentials/prod
mkdir -p backend/api/kalshi-api/kalshi-credentials/demo

# Add your credentials:
# - backend/api/kalshi-api/kalshi-credentials/prod/.env
# - backend/api/kalshi-api/kalshi-credentials/prod/kalshi.pem
# - backend/api/kalshi-api/kalshi-credentials/demo/.env
# - backend/api/kalshi-api/kalshi-credentials/demo/kalshi.pem
```

### **Step 4: Start the System**
```bash
# Use the existing MASTER_RESTART script
./scripts/MASTER_RESTART.sh
```

## Environment Configuration

### **Local Development**
```bash
# Default settings work for localhost
./scripts/MASTER_RESTART.sh
```

### **Production Server**
```bash
# Set environment for external access
export TRADING_SYSTEM_HOST="0.0.0.0"
./scripts/MASTER_RESTART.sh
```

### **Specific IP Address**
```bash
# Set specific IP
export TRADING_SYSTEM_HOST="192.168.1.100"
./scripts/MASTER_RESTART.sh
```

## Troubleshooting

### **Common Issues**

#### **1. "No module named 'requests'"**
```bash
# Solution: Install dependencies
pip install -r requirements.txt
```

#### **2. "Kalshi credentials not found"**
```bash
# Solution: Set up credentials
mkdir -p backend/api/kalshi-api/kalshi-credentials/prod
# Add your .env and kalshi.pem files
```

#### **3. "Port already in use"**
```bash
# Solution: Check what's using the port
lsof -i :3000
# Kill the process or restart system
```

#### **4. "Supervisor not found"**
```bash
# Solution: Install supervisor
pip install supervisor
```

### **System Status**
```bash
# Check all services
supervisorctl -c backend/supervisord.conf status

# Check logs
tail -f logs/main_app.out.log
tail -f logs/trade_manager.out.log
```

## Platform-Specific Notes

### **macOS**
- Use `brew install python3` if needed
- Ensure Xcode command line tools are installed

### **Linux**
- Use `sudo apt-get install python3 python3-pip` for dependencies
- Configure firewall if needed: `sudo ufw allow 3000`

### **Windows**
- Use `venv\Scripts\activate` instead of `source venv/bin/activate`
- Use `python` instead of `python3`
- Consider using WSL2 for Linux compatibility

## Verification

### **System Health Check**
```bash
# Check all services are running
supervisorctl -c backend/supervisord.conf status

# Check web interface
curl http://localhost:3000

# Check trade manager
curl http://localhost:4000/api/status
```

### **Database Verification**
```bash
# Check trade database
ls -la backend/data/trade_history/

# Check account databases
ls -la backend/data/accounts/kalshi/prod/
ls -la backend/data/accounts/kalshi/demo/
```

## Maintenance

### **Updates**
```bash
# Pull latest changes
git pull origin main

# Restart system
./scripts/MASTER_RESTART.sh
```

### **Backup**
```bash
# Backup data
./scripts/backup_user_data.sh

# Restore data
./scripts/RESTORE_TO_CURRENT_STATE.sh
```

## Support

### **Getting Help**
1. Run `./scripts/check_portability.sh` to diagnose issues
2. Check logs in `logs/` directory
3. Verify configuration files are correct
4. Test with minimal configuration first

### **Log Locations**
- System logs: `logs/supervisord.log`
- Application logs: `logs/*.out.log`
- Error logs: `logs/*.err.log`

---

**The REC.IO trading system is ready for deployment!** 🎉 