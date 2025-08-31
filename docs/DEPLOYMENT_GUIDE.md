# REC.IO Trading System - Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying the REC.IO trading system to any machine, ensuring full portability and clean deployment.

## Prerequisites

### System Requirements
- **Operating System**: Linux (Ubuntu 20.04+), macOS (10.15+), or Windows with WSL
- **Python**: 3.8 or higher
- **PostgreSQL**: 12 or higher
- **Memory**: Minimum 4GB RAM (8GB recommended)
- **Storage**: Minimum 10GB free space
- **Network**: Internet connection for dependencies

### Required Software
- Python 3.8+
- PostgreSQL client tools (`psql`, `pg_dump`)
- Git (for cloning the repository)
- Supervisor (for process management)

## Quick Deployment (One Command)

### For New Users

```bash
# One command on any new server
curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/scripts/one_click_deploy.sh | bash
```

**After installation, new users will be prompted to:**
1. Set up their user profile with `python3 scripts/setup_new_user.py`
2. Configure Kalshi credentials (optional)
3. Start the system with `./scripts/MASTER_RESTART.sh`

### For Existing Users

#### 1. Package Your Data (Local Machine)

```bash
# Package your database and credentials
./scripts/package_user_data.sh
```

#### 2. Upload Package to Server

```bash
# Upload the package to your server
scp -r backup/user_data_package_YYYYMMDD_HHMMSS root@YOUR_SERVER_IP:/root/
```

#### 3. Deploy with Data Restoration

```bash
# One command on your new server
curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/scripts/one_click_deploy.sh | bash

# When prompted:
# - Choose "Existing User"
# - Provide the package path: /root/user_data_package_YYYYMMDD_HHMMSS
```

### Access Your System

- **Web Interface**: `http://YOUR_SERVER_IP:3000`
- **Health Check**: `http://YOUR_SERVER_IP:3000/health`

**That's it!** Your complete system is now running on the remote server.

## Detailed Deployment Steps

### Phase 1: Environment Preparation

#### 1.1 Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-client supervisor git
```

**macOS:**
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies
brew install python3 postgresql supervisor git
```

**CentOS/RHEL:**
```bash
sudo yum install -y python3 python3-pip postgresql postgresql-server supervisor git
```

#### 1.2 Clone Repository

```bash
git clone <repository-url> rec_io_20
cd rec_io_20
```

### Phase 2: Python Environment Setup

#### 2.1 Create Virtual Environment

```bash
# Run the bootstrap script
./scripts/bootstrap_venv.sh
```

This script will:
- Create a Python virtual environment
- Install all required dependencies
- Generate supervisor configuration
- Create necessary directories

#### 2.2 Verify Installation

```bash
# Activate virtual environment
source venv/bin/activate

# Test Python installation
python --version
pip list
```

### Phase 3: Database Configuration

#### 3.1 PostgreSQL Setup

**Start PostgreSQL service:**
```bash
# Ubuntu/Debian
sudo systemctl start postgresql
sudo systemctl enable postgresql

# macOS
brew services start postgresql

# CentOS/RHEL
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### 3.2 Database Initialization

```bash
# Run database setup script
./scripts/setup_database.sh
```

This script will:
- Create database user if needed
- Create database if needed
- Test database connectivity
- Create `.env` file with database configuration

#### 3.3 Database Testing

```bash
# Run comprehensive database tests
./scripts/test_database.sh

# Or run quick tests only
./scripts/test_database.sh --quick
```

### Phase 4: New User Setup (For New Users Only)

#### 4.1 User Profile Configuration

After installation, new users need to set up their profile:

```bash
# Run the new user setup script
python3 scripts/setup_new_user_simple.py
```

This script will:
- Collect your personal information (name, email, phone)
- Set up your user ID and account type
- Configure Kalshi API credentials (optional)
- Create necessary directories and files
- Set proper file permissions

#### 4.2 Kalshi Credentials (Optional)

If you want to use trading features, you'll need Kalshi API credentials:

1. **Get API credentials** from [Kalshi Trading Platform](https://trading.kalshi.com/settings/api)
2. **Run the setup script** and provide your credentials when prompted
3. **Or manually create** credential files:

```bash
# Create credentials directory
mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/prod

# Add your Kalshi credentials
echo "your_kalshi_email" > backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
echo "your_kalshi_api_key" >> backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt

# Set proper permissions
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
```

### Phase 5: System Configuration

#### 5.1 Environment Variables

The system uses environment variables for configuration. Create a `.env` file in the project root:

```bash
# PostgreSQL Connection Settings
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=rec_io_db
POSTGRES_USER=rec_io_user
POSTGRES_PASSWORD=your_password_here

# Trading System Configuration
TRADING_SYSTEM_HOST=localhost
REC_BIND_HOST=localhost
REC_TARGET_HOST=localhost
```

#### 5.2 Kalshi Credentials

Set up Kalshi API credentials:

```bash
# Create credentials directory
mkdir -p backend/data/users/user_0001/credentials

# Add your Kalshi credentials
echo "your_kalshi_email" > backend/data/users/user_0001/credentials/kalshi-credentials
echo "your_kalshi_password" >> backend/data/users/user_0001/credentials/kalshi-credentials
```

### Phase 6: System Startup

#### 6.1 Generate Supervisor Configuration

```bash
# Generate supervisor config with absolute paths
./scripts/generate_supervisor_config.sh
```

#### 6.2 Start All Services

```bash
# Start the entire system
./scripts/MASTER_RESTART.sh
```

This script will:
- Stop any existing services
- Flush ports
- Create logs directory
- Start all 12 trading system services
- Verify all services are running

#### 6.3 Verify System Status

```bash
# Check service status
supervisorctl -c backend/supervisord.conf status

# Check logs
tail -f logs/unified_production_coordinator.out.log
```

## Service Management

### Starting Services

```bash
# Start all services
./scripts/MASTER_RESTART.sh

# Start individual service
supervisorctl -c backend/supervisord.conf start <service_name>
```

### Stopping Services

```bash
# Stop all services
supervisorctl -c backend/supervisord.conf shutdown

# Stop individual service
supervisorctl -c backend/supervisord.conf stop <service_name>
```

### Restarting Services

```bash
# Restart all services
./scripts/MASTER_RESTART.sh

# Restart individual service
supervisorctl -c backend/supervisord.conf restart <service_name>
```

### Viewing Logs

```bash
# View all logs
tail -f logs/*.out.log

# View specific service log
tail -f logs/unified_production_coordinator.out.log
tail -f logs/main_app.out.log
```

## Database Management

### Creating Backups

```bash
# Create a new backup
./scripts/backup_database.sh backup

# List available backups
./scripts/backup_database.sh list

# Clean old backups (older than 7 days)
./scripts/backup_database.sh clean 7
```

### Restoring Backups

```bash
# Restore from backup file
./scripts/backup_database.sh restore backup/rec_io_db_backup_20250101_120000.tar.gz
```

### Database Testing

```bash
# Run comprehensive tests
./scripts/test_database.sh

# Run quick tests only
./scripts/test_database.sh --quick
```

## Troubleshooting

### Common Issues

#### 1. Database Connection Failed

**Symptoms:**
- Services fail to start
- Database connection errors in logs

**Solutions:**
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Test database connection
./scripts/test_database.sh --quick

# Check .env file configuration
cat .env
```

#### 2. Port Already in Use

**Symptoms:**
- "Address already in use" errors
- Services fail to start

**Solutions:**
```bash
# Flush all ports
./scripts/MASTER_RESTART.sh

# Or manually kill processes
sudo lsof -ti:3000 | xargs kill -9
sudo lsof -ti:4000 | xargs kill -9
```

#### 3. Python Dependencies Missing

**Symptoms:**
- Import errors
- Module not found errors

**Solutions:**
```bash
# Reinstall dependencies
source venv/bin/activate
pip install -r requirements.txt

# Or run bootstrap script
./scripts/bootstrap_venv.sh
```

#### 4. Supervisor Configuration Issues

**Symptoms:**
- Services not starting
- Configuration errors

**Solutions:**
```bash
# Regenerate supervisor config
./scripts/generate_supervisor_config.sh

# Check config syntax
supervisord -c backend/supervisord.conf -n
```

### Log Analysis

#### Key Log Files

- `logs/main_app.out.log` - Main application logs
- `logs/unified_production_coordinator.out.log` - Production coordinator logs
- `logs/kalshi_api_watchdog.out.log` - Kalshi API watchdog logs
- `logs/symbol_watchdog.out.log` - Symbol watchdog logs

#### Common Log Patterns

**Successful startup:**
```
[INFO] Service started successfully
[INFO] Database connection established
[INFO] All services running
```

**Error patterns:**
```
[ERROR] Database connection failed
[ERROR] Port already in use
[ERROR] Import error: No module named
```

## Security Considerations

### 1. Credentials Management

- Store credentials in user-specific directories only
- Never commit credentials to version control
- Use environment variables for sensitive data

### 2. Network Security

- Configure firewall rules appropriately
- Use HTTPS for external communications
- Restrict database access to localhost

### 3. File Permissions

```bash
# Set appropriate permissions
chmod 600 backend/data/users/*/credentials/*
chmod 644 .env
chmod 755 scripts/*.sh
```

## Performance Optimization

### 1. Database Optimization

```bash
# Create indexes for better performance

```

### 2. System Resources

- Monitor memory usage
- Ensure adequate disk space
- Optimize PostgreSQL configuration

### 3. Log Management

```bash
# Set up log rotation
sudo cp config/logrotate.conf /etc/logrotate.d/rec_io
```

## Monitoring and Maintenance

### 1. Health Checks

```bash
# Check system health
curl http://localhost:3000/health

# Check service status
supervisorctl -c backend/supervisord.conf status
```

### 2. Regular Maintenance

```bash
# Daily: Check logs for errors
tail -n 100 logs/*.out.log | grep ERROR

# Weekly: Create database backup
./scripts/backup_database.sh backup

# Monthly: Clean old backups
./scripts/backup_database.sh clean 30
```

### 3. Updates

```bash
# Update code
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Restart services
./scripts/MASTER_RESTART.sh
```

## Support

For issues not covered in this guide:

1. Check the logs for specific error messages
2. Review the troubleshooting section
3. Consult the system documentation
4. Contact the development team

## Appendix

### Service List

The system includes 12 services:

1. `main_app` - Main Flask application
2. `unified_production_coordinator` - Data production coordinator
3. `kalshi_api_watchdog` - Kalshi API monitoring
4. `symbol_watchdog` - Symbol price monitoring
5. `trade_manager` - Trade management
6. `trade_executor` - Trade execution
7. `active_trade_supervisor` - Active trade supervision
8. `auto_entry_supervisor` - Auto entry supervision
9. `cascading_failure_detector` - Failure detection
10. `system_monitor` - System monitoring
11. `kalshi_account_sync` - Account synchronization
12. `account_mode` - Account mode management

### Port Configuration

- **3000**: Main application
- **4000**: Trade manager
- **8001**: Trade executor
- **8007**: Active trade supervisor

### File Structure

```
rec_io_20/
├── backend/           # Backend services
├── frontend/          # Frontend application
├── scripts/           # Deployment scripts
├── logs/              # System logs
├── backup/            # Database backups
├── config/            # Configuration files
└── docs/              # Documentation
``` 