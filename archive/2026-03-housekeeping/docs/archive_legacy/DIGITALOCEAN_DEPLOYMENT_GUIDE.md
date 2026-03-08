# 🚀 DIGITALOCEAN DEPLOYMENT GUIDE

## Overview

This guide provides complete instructions for deploying the trading system to DigitalOcean as a single-user service. The system is optimized, secured, and ready for immediate deployment.

## 📋 PREREQUISITES

### DigitalOcean Account
- ✅ DigitalOcean account with API access
- ✅ SSH key configured
- ✅ Payment method set up

### Server Requirements
- **OS**: Ubuntu 22.04 LTS (recommended)
- **Size**: 2GB RAM, 1 vCPU minimum (4GB RAM recommended)
- **Storage**: 20GB SSD minimum
- **Network**: Public IP address

## 🔧 DEPLOYMENT OPTIONS

### Option 1: Automated Deployment (Recommended)
```bash
# Deploy to your server
./scripts/deploy_digitalocean.sh --server YOUR_SERVER_IP --key YOUR_SSH_KEY

# Example
./scripts/deploy_digitalocean.sh --server 123.456.789.012 --key ~/.ssh/id_rsa
```

### Option 2: Manual Installation
```bash
# SSH to your server
ssh root@YOUR_SERVER_IP

# Run installation script
curl -sSL https://raw.githubusercontent.com/your-repo/main/scripts/install_digitalocean.sh | bash
```

### Option 3: Step-by-Step Manual
Follow the detailed manual installation steps below.

## 🚀 AUTOMATED DEPLOYMENT

### Step 1: Prepare Your Environment
```bash
# Ensure you have SSH access to your server
ssh root@YOUR_SERVER_IP

# Test connectivity
ping -c 3 YOUR_SERVER_IP
```

### Step 2: Run Deployment Script
```bash
# Full deployment
./scripts/deploy_digitalocean.sh --server YOUR_SERVER_IP --key YOUR_SSH_KEY

# Update existing deployment
./scripts/deploy_digitalocean.sh --server YOUR_SERVER_IP --key YOUR_SSH_KEY --mode update

# Verify deployment
./scripts/deploy_digitalocean.sh --server YOUR_SERVER_IP --key YOUR_SSH_KEY --mode verify
```

### Step 3: Verify Deployment
```bash
# Check system status
systemctl status trading_system.service

# Check supervisor services
supervisorctl -c /opt/trading_system/backend/supervisord.conf status

# Test web interface
curl http://YOUR_SERVER_IP:3000/
```

## 📋 MANUAL INSTALLATION STEPS

### Step 1: Create DigitalOcean Droplet

1. **Log into DigitalOcean**
   - Go to https://cloud.digitalocean.com
   - Click "Create" → "Droplets"

2. **Configure Droplet**
   - **Choose an image**: Ubuntu 22.04 LTS
   - **Choose a plan**: Basic (2GB RAM, 1 vCPU minimum)
   - **Choose a datacenter**: Select closest to you
   - **Add your SSH key**: Upload or select existing key
   - **Finalize and create**: Click "Create Droplet"

3. **Note Server Details**
   - **IP Address**: Your server's public IP
   - **Root Password**: (if not using SSH key)

### Step 2: Connect to Server
```bash
# SSH to your server
ssh root@YOUR_SERVER_IP

# Update system
apt-get update && apt-get upgrade -y
```

### Step 3: Install Dependencies
```bash
# Install system dependencies
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    supervisor \
    ufw \
    curl \
    wget \
    git \
    sqlite3 \
    nginx \
    htop \
    unzip \
    cron \
    logrotate
```

### Step 4: Download and Install Trading System
```bash
# Create installation directory
mkdir -p /opt/trading_system
cd /opt/trading_system

# Download installation script
wget https://raw.githubusercontent.com/your-repo/main/scripts/install_digitalocean.sh
chmod +x install_digitalocean.sh

# Run installation
./install_digitalocean.sh
```

### Step 5: Configure Firewall
```bash
# Setup firewall in production mode
/opt/trading_system/scripts/setup_firewall.sh --mode production

# Verify firewall status
ufw status
```

### Step 6: Start Services
```bash
# Start trading system service
systemctl start trading_system.service
systemctl enable trading_system.service

# Check status
systemctl status trading_system.service
```

## 🔍 VERIFICATION CHECKLIST

### System Services
```bash
# Check all services are running
supervisorctl -c /opt/trading_system/backend/supervisord.conf status

# Expected output: All 12 services should show RUNNING
```

### Web Interface
```bash
# Test web interface
curl http://localhost:3000/

# Test from external IP
curl http://YOUR_SERVER_IP:3000/
```

### Firewall Status
```bash
# Check firewall rules
ufw status numbered

# Verify trading ports are accessible
netstat -tlnp | grep -E ':(3000|4000|6000|8010)'
```

### Log Files
```bash
# Check recent logs
tail -f /opt/trading_system/logs/main_app.out.log

# Check system logs
journalctl -u trading_system.service -f
```

## 🔧 CONFIGURATION

### Environment Variables
```bash
# Edit configuration file
nano /opt/trading_system/backend/core/config/config.json

# Key settings to verify:
# - API credentials
# - Database paths
# - Port configurations

# Configure SMTP for notifications
export GMAIL_USER="rec.io.alerts@gmail.com"
export GMAIL_PASSWORD="jfnc adxj ubfz lrtw"

# Or add to system environment
echo "export GMAIL_USER=rec.io.alerts@gmail.com" >> ~/.bashrc
echo "export GMAIL_PASSWORD=jfnc adxj ubfz lrtw" >> ~/.bashrc
source ~/.bashrc
```

### Firewall Configuration
```bash
# Edit firewall whitelist
nano /opt/trading_system/config/firewall_whitelist.json

# Add your IP addresses for SSH access
```

### Log Rotation
```bash
# Check log rotation configuration
cat /etc/logrotate.d/trading_system

# Manual log rotation
/opt/trading_system/scripts/manual_log_rotation.sh
```

## 📊 MONITORING

### System Monitoring
```bash
# Check system resources
htop

# Monitor disk usage
df -h

# Check memory usage
free -h
```

### Application Monitoring
```bash
# Enhanced monitoring script
/opt/trading_system/scripts/enhanced_monitor.sh

# Check specific service logs
tail -f /opt/trading_system/logs/unified_production_coordinator.out.log
```

### Performance Monitoring
```bash
# Monitor CPU usage by service
ps aux | grep python | grep -v grep

# Check network connections
netstat -tlnp | grep python
```

## 🚨 TROUBLESHOOTING

### Common Issues

**Issue**: Web interface not accessible
```bash
# Check if service is running
systemctl status trading_system.service

# Check supervisor status
supervisorctl -c /opt/trading_system/backend/supervisord.conf status

# Check firewall
ufw status
```

**Issue**: High CPU usage
```bash
# Check which service is using CPU
htop

# Restart specific service
supervisorctl -c /opt/trading_system/backend/supervisord.conf restart unified_production_coordinator
```

**Issue**: Database errors
```bash
# Check database files
ls -la /opt/trading_system/data/

# Optimize databases
/opt/trading_system/scripts/optimize_databases.sh
```

**Issue**: Log files growing too large
```bash
# Manual log rotation
/opt/trading_system/scripts/manual_log_rotation.sh

# Check log sizes
du -sh /opt/trading_system/logs/*
```

### Emergency Recovery
```bash
# Stop all services
systemctl stop trading_system.service

# Backup current state
cp -r /opt/trading_system /opt/trading_system_backup_$(date +%s)

# Restart services
systemctl start trading_system.service

# Verify recovery
supervisorctl -c /opt/trading_system/backend/supervisord.conf status
```

## 🔒 SECURITY

### Firewall Configuration
- **SSH**: Restricted to whitelisted IPs
- **Web Interface**: Port 3000 accessible
- **Trading APIs**: Outbound access allowed
- **Internal Services**: Localhost only

### Access Control
```bash
# Change default SSH port (optional)
nano /etc/ssh/sshd_config
# Change Port 22 to Port 2222

# Restart SSH
systemctl restart ssh
```

### SSL/TLS (Optional)
```bash
# Install Certbot for Let's Encrypt
apt-get install -y certbot python3-certbot-nginx

# Get SSL certificate
certbot --nginx -d your-domain.com
```

## 📈 SCALING

### Performance Optimization
```bash
# Monitor resource usage
/opt/trading_system/scripts/enhanced_monitor.sh

# Optimize databases
/opt/trading_system/scripts/optimize_databases.sh

# Check for bottlenecks
htop
```

### Backup Strategy
```bash
# Create backup script
cat > /opt/trading_system/scripts/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/backups/trading_system_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r /opt/trading_system/data "$BACKUP_DIR/"
cp -r /opt/trading_system/config "$BACKUP_DIR/"
tar -czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
rm -rf "$BACKUP_DIR"
echo "Backup created: $BACKUP_DIR.tar.gz"
EOF

chmod +x /opt/trading_system/scripts/backup.sh
```

## 🎯 DEPLOYMENT CHECKLIST

### Pre-Deployment
- [ ] DigitalOcean account created
- [ ] SSH key configured
- [ ] Server IP address noted
- [ ] Domain name configured (optional)

### Installation
- [ ] System dependencies installed
- [ ] Python environment created
- [ ] Trading system installed
- [ ] Supervisor configured
- [ ] Firewall deployed

### Verification
- [ ] All 12 services running
- [ ] Web interface accessible
- [ ] API endpoints functional
- [ ] Firewall protecting system
- [ ] Logs being generated

### Post-Deployment
- [ ] Monitor system performance
- [ ] Configure backups
- [ ] Set up monitoring alerts
- [ ] Test trading functionality
- [ ] Document access credentials

## 📞 SUPPORT

### Log Files Location
- **System Logs**: `/opt/trading_system/logs/`
- **Supervisor Logs**: `/var/log/supervisor/`
- **System Service**: `journalctl -u trading_system.service`

### Useful Commands
```bash
# System status
systemctl status trading_system.service

# Service management
supervisorctl -c /opt/trading_system/backend/supervisord.conf [start|stop|restart] [service_name]

# Log monitoring
tail -f /opt/trading_system/logs/main_app.out.log

# Performance monitoring
/opt/trading_system/scripts/enhanced_monitor.sh
```

### Emergency Contacts
- **System Issues**: Check logs and restart services
- **Trading Issues**: Verify API credentials and connectivity
- **Security Issues**: Check firewall and SSH access

## ✅ DEPLOYMENT COMPLETE

Your trading system is now deployed and ready for use!

**Access your system at**: `http://YOUR_SERVER_IP:3000`

**Monitor your system**: `systemctl status trading_system.service`

**Check logs**: `tail -f /opt/trading_system/logs/main_app.out.log`

**The system is optimized, secured, and ready for production trading.** 