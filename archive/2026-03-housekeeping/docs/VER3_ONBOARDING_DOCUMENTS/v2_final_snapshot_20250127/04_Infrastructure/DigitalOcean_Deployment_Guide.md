# DigitalOcean Deployment Guide

## Overview
This guide provides comprehensive instructions for deploying the REC.IO trading system to DigitalOcean, including environment setup, deployment procedures, rollback mechanisms, and ongoing maintenance.

**Last Updated**: 2025-01-27  
**Target Environment**: DigitalOcean Droplet  
**System Requirements**: Ubuntu 22.04 LTS, 4GB RAM, 2 vCPUs, 80GB SSD

---

## Pre-Deployment Checklist

### System Requirements
- [ ] DigitalOcean account with billing enabled
- [ ] SSH key pair configured
- [ ] Domain name (optional but recommended)
- [ ] SSL certificate (Let's Encrypt recommended)
- [ ] Database backup strategy planned
- [ ] Monitoring and alerting configured

### Prerequisites
- [ ] PostgreSQL 14+ installed and configured
- [ ] Python 3.9+ with virtual environment
- [ ] Supervisor process manager installed
- [ ] Nginx web server installed
- [ ] Firewall configured (UFW)
- [ ] SSL certificate obtained

---

## Environment Setup

### 1. Create DigitalOcean Droplet

#### Droplet Configuration
```bash
# Recommended droplet specifications
Droplet Name: rec-io-trading-system
Region: NYC3 (or closest to target users)
Size: Basic - 4GB RAM / 2 vCPUs / 80GB SSD
Image: Ubuntu 22.04 LTS
Authentication: SSH Key
Monitoring: Enabled
Backups: Enabled (recommended)
```

#### Initial Server Setup
```bash
# Connect to droplet
ssh root@your_droplet_ip

# Update system
apt update && apt upgrade -y

# Install essential packages
apt install -y curl wget git unzip software-properties-common apt-transport-https ca-certificates gnupg lsb-release

# Create non-root user
adduser rec_io_user
usermod -aG sudo rec_io_user

# Configure SSH for new user
mkdir -p /home/rec_io_user/.ssh
cp ~/.ssh/authorized_keys /home/rec_io_user/.ssh/
chown -R rec_io_user:rec_io_user /home/rec_io_user/.ssh
chmod 700 /home/rec_io_user/.ssh
chmod 600 /home/rec_io_user/.ssh/authorized_keys
```

### 2. Install and Configure PostgreSQL

#### Install PostgreSQL
```bash
# Add PostgreSQL repository
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -
echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list

# Update and install PostgreSQL
apt update
apt install -y postgresql postgresql-contrib

# Start and enable PostgreSQL
systemctl start postgresql
systemctl enable postgresql
```

#### Configure PostgreSQL
```bash
# Switch to postgres user
sudo -u postgres psql

# Create database and user
CREATE DATABASE rec_io_db;
CREATE USER rec_io_user WITH PASSWORD 'rec_io_password';
GRANT ALL PRIVILEGES ON DATABASE rec_io_db TO rec_io_user;
CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS live_data;
CREATE SCHEMA IF NOT EXISTS historical_data;
GRANT ALL ON SCHEMA users TO rec_io_user;
GRANT ALL ON SCHEMA live_data TO rec_io_user;
GRANT ALL ON SCHEMA historical_data TO rec_io_user;

# Exit PostgreSQL
\q
```

#### Configure PostgreSQL for Remote Access
```bash
# Edit PostgreSQL configuration
sudo nano /etc/postgresql/14/main/postgresql.conf

# Add/modify these lines:
listen_addresses = 'localhost'
port = 5432
max_connections = 100
shared_buffers = 256MB
effective_cache_size = 1GB

# Edit pg_hba.conf for authentication
sudo nano /etc/postgresql/14/main/pg_hba.conf

# Add this line for local connections:
local   all             rec_io_user                    md5

# Restart PostgreSQL
sudo systemctl restart postgresql
```

### 3. Install Python and Dependencies

#### Install Python 3.9+
```bash
# Add deadsnakes PPA for Python 3.9
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.9 python3.9-venv python3.9-dev

# Create symbolic links
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.9 1
sudo update-alternatives --install /usr/bin/python python /usr/bin/python3.9 1
```

#### Install System Dependencies
```bash
# Install required system packages
sudo apt install -y build-essential libpq-dev libssl-dev libffi-dev python3-dev

# Install additional packages
sudo apt install -y supervisor nginx ufw fail2ban
```

### 4. Configure Firewall (UFW)

#### Basic Firewall Setup
```bash
# Enable UFW
sudo ufw enable

# Allow SSH
sudo ufw allow ssh

# Allow HTTP and HTTPS
sudo ufw allow 80
sudo ufw allow 443

# Allow application ports
sudo ufw allow 3000  # Main app
sudo ufw allow 4000  # Trade manager
sudo ufw allow 8001  # Trade executor
sudo ufw allow 8007  # Active trade supervisor
sudo ufw allow 8002  # BTC price watchdog
sudo ufw allow 8004  # Kalshi account sync
sudo ufw allow 8005  # Kalshi API watchdog
sudo ufw allow 8010  # Unified production coordinator

# Check firewall status
sudo ufw status
```

### 5. Install and Configure Nginx

#### Install Nginx
```bash
# Install Nginx
sudo apt install -y nginx

# Start and enable Nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

#### Configure Nginx for REC.IO
```bash
# Create Nginx configuration
sudo nano /etc/nginx/sites-available/rec-io

# Add the following configuration:
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com www.your-domain.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Main application
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # WebSocket support
    location /ws {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files
    location /static/ {
        alias /home/rec_io_user/rec_io_20/frontend/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Health check endpoint
    location /health {
        proxy_pass http://localhost:3000;
        access_log off;
    }
}

# Enable the site
sudo ln -s /etc/nginx/sites-available/rec-io /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 6. Install SSL Certificate (Let's Encrypt)

#### Install Certbot
```bash
# Install Certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain SSL certificate
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# Set up automatic renewal
sudo crontab -e

# Add this line for automatic renewal:
0 12 * * * /usr/bin/certbot renew --quiet
```

---

## Application Deployment

### 1. Clone and Setup Application

#### Clone Repository
```bash
# Switch to application user
sudo su - rec_io_user

# Clone repository
git clone https://github.com/your-org/rec_io_20.git
cd rec_io_20

# Create virtual environment
python3.9 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### Configure Application
```bash
# Create configuration files
mkdir -p backend/data/users/user_0001/credentials
mkdir -p logs
mkdir -p backup

# Set proper permissions
chmod 700 backend/data/users/user_0001/credentials
chmod 755 logs
chmod 755 backup

# Create environment file
nano .env

# Add the following content:
DATABASE_TYPE=postgresql
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=rec_io_password
TRADING_SYSTEM_HOST=your-domain.com
ENVIRONMENT=production
```

### 2. Configure Supervisor

#### Create Supervisor Configuration
```bash
# Create supervisor configuration
sudo nano /etc/supervisor/conf.d/rec-io.conf

# Add the following configuration:
[program:main_app]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/main.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/main_app.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/main_app.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:trade_manager]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/trade_manager.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/trade_manager.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/trade_manager.out.log
environment=PATH="/home/rec_io_user/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:trade_executor]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/trade_executor.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/trade_executor.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/trade_executor.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:active_trade_supervisor]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/active_trade_supervisor.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/active_trade_supervisor.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/active_trade_supervisor.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:btc_price_watchdog]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/api/coinbase-api/coinbase-btc/btc_price_watchdog.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/btc_price_watchdog.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/btc_price_watchdog.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:kalshi_account_sync]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/api/kalshi-api/kalshi_account_sync_ws.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/kalshi_account_sync.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/kalshi_account_sync.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:kalshi_api_watchdog]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/api/kalshi-api/kalshi_api_watchdog.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/kalshi_api_watchdog.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/kalshi_api_watchdog.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:unified_production_coordinator]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/unified_production_coordinator.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/unified_production_coordinator.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/unified_production_coordinator.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1

[program:system_monitor]
command=/home/rec_io_user/rec_io_20/venv/bin/python backend/system_monitor.py
directory=/home/rec_io_user/rec_io_20
user=rec_io_user
autostart=true
autorestart=true
stderr_logfile=/home/rec_io_user/rec_io_20/logs/system_monitor.err.log
stdout_logfile=/home/rec_io_user/rec_io_20/logs/system_monitor.out.log
environment=PATH="/home/rec_io_user/rec_io_20/venv/bin",PYTHONPATH="/home/rec_io_user/rec_io_20",PYTHONGC=1,PYTHONDNSCACHE=1
```

#### Start Supervisor Services
```bash
# Reload supervisor configuration
sudo supervisorctl reread
sudo supervisorctl update

# Start all services
sudo supervisorctl start all

# Check status
sudo supervisorctl status
```

### 3. Database Migration

#### Run Database Migration
```bash
# Switch to application user
sudo su - rec_io_user
cd rec_io_20

# Activate virtual environment
source venv/bin/activate

# Run database migration
python scripts/migrate_data_to_postgresql.sh

# Verify migration
python -c "
import psycopg2
conn = psycopg2.connect('postgresql://rec_io_user:rec_io_password@localhost/rec_io_db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM users.trades_0001')
print(f'Trades count: {cursor.fetchone()[0]}')
conn.close()
"
```

### 4. Configure Credentials

#### Setup Kalshi Credentials
```bash
# Create credentials file
nano backend/data/users/user_0001/credentials/kalshi-credentials

# Add your Kalshi API credentials:
{
  "api_key": "your_kalshi_api_key",
  "api_secret": "your_kalshi_api_secret",
  "account_id": "your_account_id"
}

# Set proper permissions
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials
```

---

## Deployment Verification

### 1. Health Checks

#### Application Health
```bash
# Check application health
curl -k https://your-domain.com/health

# Expected response:
{
  "status": "healthy",
  "timestamp": "2024-01-27T10:30:00Z",
  "services": {
    "database": true,
    "kalshi_api": true,
    "coinbase_api": true,
    "supervisor": true
  }
}
```

#### Service Status
```bash
# Check supervisor status
sudo supervisorctl status

# Check Nginx status
sudo systemctl status nginx

# Check PostgreSQL status
sudo systemctl status postgresql

# Check firewall status
sudo ufw status
```

### 2. Performance Monitoring

#### System Resources
```bash
# Check system resources
htop
df -h
free -h

# Check application logs
tail -f /home/rec_io_user/rec_io_20/logs/main_app.out.log
tail -f /home/rec_io_user/rec_io_20/logs/trade_manager.out.log
```

#### Database Performance
```bash
# Connect to PostgreSQL
sudo -u postgres psql

# Check active connections
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

# Check database size
SELECT pg_size_pretty(pg_database_size('rec_io_db'));

# Check slow queries
SELECT query, mean_time, calls FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;
```

---

## Rollback Procedures

### 1. Application Rollback

#### Quick Rollback Script
```bash
#!/bin/bash
# rollback.sh - Quick application rollback

echo "Starting rollback procedure..."

# Stop all services
sudo supervisorctl stop all

# Backup current version
sudo cp -r /home/rec_io_user/rec_io_20 /home/rec_io_user/rec_io_20_backup_$(date +%Y%m%d_%H%M%S)

# Restore from backup
sudo cp -r /home/rec_io_user/rec_io_20_backup_latest /home/rec_io_user/rec_io_20

# Update permissions
sudo chown -R rec_io_user:rec_io_user /home/rec_io_user/rec_io_20

# Restart services
sudo supervisorctl start all

echo "Rollback completed. Check service status:"
sudo supervisorctl status
```

#### Database Rollback
```bash
#!/bin/bash
# db_rollback.sh - Database rollback procedure

echo "Starting database rollback..."

# Stop services that use database
sudo supervisorctl stop trade_manager
sudo supervisorctl stop active_trade_supervisor

# Restore database from backup
pg_restore -h localhost -U rec_io_user -d rec_io_db /home/rec_io_user/backup/db_backup_latest.sql

# Restart services
sudo supervisorctl start trade_manager
sudo supervisorctl start active_trade_supervisor

echo "Database rollback completed."
```

### 2. Configuration Rollback

#### Nginx Configuration Rollback
```bash
# Backup current Nginx config
sudo cp /etc/nginx/sites-available/rec-io /etc/nginx/sites-available/rec-io.backup

# Restore previous configuration
sudo cp /etc/nginx/sites-available/rec-io.backup /etc/nginx/sites-available/rec-io

# Test and reload Nginx
sudo nginx -t
sudo systemctl reload nginx
```

#### Supervisor Configuration Rollback
```bash
# Backup supervisor config
sudo cp /etc/supervisor/conf.d/rec-io.conf /etc/supervisor/conf.d/rec-io.conf.backup

# Restore previous configuration
sudo cp /etc/supervisor/conf.d/rec-io.conf.backup /etc/supervisor/conf.d/rec-io.conf

# Reload supervisor
sudo supervisorctl reread
sudo supervisorctl update
```

---

## Maintenance Procedures

### 1. Regular Maintenance

#### Daily Maintenance
```bash
#!/bin/bash
# daily_maintenance.sh

echo "Running daily maintenance..."

# Check disk space
df -h

# Check log file sizes
du -sh /home/rec_io_user/rec_io_20/logs/*

# Rotate logs if needed
sudo logrotate /etc/logrotate.d/rec-io

# Check service status
sudo supervisorctl status

# Check database connections
sudo -u postgres psql -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

echo "Daily maintenance completed."
```

#### Weekly Maintenance
```bash
#!/bin/bash
# weekly_maintenance.sh

echo "Running weekly maintenance..."

# Update system packages
sudo apt update
sudo apt upgrade -y

# Clean old log files
find /home/rec_io_user/rec_io_20/logs -name "*.log" -mtime +7 -delete

# Clean old backups
find /home/rec_io_user/backup -name "*.sql" -mtime +30 -delete

# Vacuum database
sudo -u postgres psql -d rec_io_db -c "VACUUM ANALYZE;"

# Check SSL certificate renewal
sudo certbot renew --dry-run

echo "Weekly maintenance completed."
```

### 2. Backup Procedures

#### Automated Backup Script
```bash
#!/bin/bash
# backup.sh - Automated backup procedure

BACKUP_DIR="/home/rec_io_user/backup"
DATE=$(date +%Y%m%d_%H%M%S)

echo "Starting backup procedure..."

# Create backup directory
mkdir -p $BACKUP_DIR

# Database backup
pg_dump -h localhost -U rec_io_user -d rec_io_db > $BACKUP_DIR/db_backup_$DATE.sql
gzip $BACKUP_DIR/db_backup_$DATE.sql

# Application backup
tar -czf $BACKUP_DIR/app_backup_$DATE.tar.gz /home/rec_io_user/rec_io_20

# Configuration backup
tar -czf $BACKUP_DIR/config_backup_$DATE.tar.gz /etc/nginx/sites-available/rec-io /etc/supervisor/conf.d/rec-io.conf

# Clean old backups (keep last 7 days)
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete

echo "Backup completed: $BACKUP_DIR"
```

#### Setup Automated Backups
```bash
# Add to crontab
sudo crontab -e

# Add these lines for automated backups:
0 2 * * * /home/rec_io_user/rec_io_20/scripts/backup.sh
0 3 * * * /home/rec_io_user/rec_io_20/scripts/daily_maintenance.sh
0 4 * * 0 /home/rec_io_user/rec_io_20/scripts/weekly_maintenance.sh
```

### 3. Monitoring and Alerting

#### Setup Monitoring Script
```bash
#!/bin/bash
# monitor.sh - System monitoring script

# Check system resources
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
MEMORY_USAGE=$(free | grep Mem | awk '{printf("%.2f", $3/$2 * 100.0)}')
DISK_USAGE=$(df / | tail -1 | awk '{print $5}' | cut -d'%' -f1)

# Check service status
SERVICES_STATUS=$(sudo supervisorctl status | grep -c "RUNNING")
EXPECTED_SERVICES=9

# Alert thresholds
if (( $(echo "$CPU_USAGE > 80" | bc -l) )); then
    echo "ALERT: High CPU usage: ${CPU_USAGE}%"
fi

if (( $(echo "$MEMORY_USAGE > 85" | bc -l) )); then
    echo "ALERT: High memory usage: ${MEMORY_USAGE}%"
fi

if [ $DISK_USAGE -gt 90 ]; then
    echo "ALERT: High disk usage: ${DISK_USAGE}%"
fi

if [ $SERVICES_STATUS -lt $EXPECTED_SERVICES ]; then
    echo "ALERT: Some services are down. Expected: $EXPECTED_SERVICES, Running: $SERVICES_STATUS"
fi
```

#### Setup Log Rotation
```bash
# Create logrotate configuration
sudo nano /etc/logrotate.d/rec-io

# Add the following configuration:
/home/rec_io_user/rec_io_20/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 rec_io_user rec_io_user
    postrotate
        sudo supervisorctl restart all
    endscript
}
```

---

## Troubleshooting

### 1. Common Issues

#### Service Won't Start
```bash
# Check service logs
sudo supervisorctl tail main_app stderr
sudo supervisorctl tail trade_manager stderr

# Check configuration
sudo supervisorctl reread
sudo supervisorctl update

# Restart specific service
sudo supervisorctl restart main_app
```

#### Database Connection Issues
```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Check connection
sudo -u postgres psql -c "SELECT version();"

# Check logs
sudo tail -f /var/log/postgresql/postgresql-14-main.log
```

#### Nginx Issues
```bash
# Check Nginx configuration
sudo nginx -t

# Check Nginx status
sudo systemctl status nginx

# Check logs
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

### 2. Performance Issues

#### High CPU Usage
```bash
# Check top processes
htop

# Check specific Python processes
ps aux | grep python

# Check supervisor processes
sudo supervisorctl status
```

#### High Memory Usage
```bash
# Check memory usage
free -h

# Check swap usage
swapon -s

# Check PostgreSQL memory usage
sudo -u postgres psql -c "SELECT * FROM pg_stat_bgwriter;"
```

#### Database Performance
```bash
# Check slow queries
sudo -u postgres psql -c "SELECT query, mean_time, calls FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"

# Check table sizes
sudo -u postgres psql -c "SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) FROM pg_tables ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"
```

---

## Security Hardening

### 1. Additional Security Measures

#### Fail2ban Configuration
```bash
# Install fail2ban
sudo apt install -y fail2ban

# Configure fail2ban
sudo nano /etc/fail2ban/jail.local

# Add the following configuration:
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
logpath = /var/log/nginx/error.log
maxretry = 3
```

#### Regular Security Updates
```bash
# Setup automatic security updates
sudo apt install -y unattended-upgrades

# Configure automatic updates
sudo nano /etc/apt/apt.conf.d/50unattended-upgrades

# Enable automatic security updates
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## Scaling Considerations

### 1. Vertical Scaling

#### Upgrade Droplet Size
```bash
# Current specifications
# 4GB RAM / 2 vCPUs / 80GB SSD

# Recommended upgrades:
# 8GB RAM / 4 vCPUs / 160GB SSD (for increased load)
# 16GB RAM / 8 vCPUs / 320GB SSD (for high performance)
```

#### Database Optimization
```bash
# Optimize PostgreSQL for larger instances
sudo nano /etc/postgresql/14/main/postgresql.conf

# For 8GB RAM instance:
shared_buffers = 2GB
effective_cache_size = 6GB
work_mem = 16MB
maintenance_work_mem = 256MB
```

### 2. Horizontal Scaling

#### Load Balancer Setup
```bash
# Install HAProxy for load balancing
sudo apt install -y haproxy

# Configure HAProxy
sudo nano /etc/haproxy/haproxy.cfg

# Add configuration for multiple application instances
```

#### Database Replication
```bash
# Setup PostgreSQL streaming replication
# Primary server configuration
sudo nano /etc/postgresql/14/main/postgresql.conf

# Add replication settings
wal_level = replica
max_wal_senders = 3
max_replication_slots = 3
```

---

This comprehensive deployment guide provides all necessary steps for deploying the REC.IO trading system to DigitalOcean, including environment setup, deployment procedures, rollback mechanisms, maintenance procedures, and scaling considerations.
