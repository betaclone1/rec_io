# New User Setup Guide

## Overview

This guide walks new users through setting up the REC.IO trading system from scratch. The system is designed to be completely portable and secure, with no personal information included in the public repository.

## Quick Start (One Command)

For new users, the entire setup process is automated:

```bash
# One command deployment
curl -sSL https://raw.githubusercontent.com/betaclone1/rec_io/main/scripts/one_click_deploy.sh | bash
```

This will:
1. Install all system dependencies
2. Set up PostgreSQL database
3. Clone the repository
4. Create Python virtual environment
5. Set up basic user structure
6. Configure the system

## Post-Installation Setup

After the automated installation, new users need to complete their profile setup:

### 1. Run User Setup Script

```bash
cd /opt/rec_io
python3 scripts/setup_new_user_simple.py
```

This script will:
- Collect your basic information (name, email)
- Create your user directory structure
- Set up default preferences
- Create environment configuration
- Set proper file permissions

### 2. Add Kalshi Credentials (Optional)

If you want to use trading features, you'll need Kalshi API credentials:

#### Option A: Manual Setup
```bash
# Create credentials file
mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/prod
echo "your_email@example.com" > backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
echo "your_api_key" >> backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt

# Set secure permissions
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt
```

#### Option B: Use Setup Script
The `setup_new_user.py` script (more comprehensive) can also set up Kalshi credentials interactively.

### 3. Start the System

```bash
# Start all services
./scripts/MASTER_RESTART.sh
```

### 4. Access the Web Interface

Open your browser and navigate to:
- **Local**: `http://localhost:3000`
- **Remote**: `http://YOUR_SERVER_IP:3000`

## Security Features

### User Data Protection
- **No personal data in repository**: All user-specific files are excluded from git
- **Secure credential storage**: Credentials stored in user-specific directories with proper permissions
- **Environment isolation**: Each user's data is isolated in separate directories

### File Structure
```
backend/data/users/user_0001/
├── user_info.json              # Your basic profile (created by setup script)
├── credentials/                # API credentials (you add these)
│   └── kalshi-credentials/
│       ├── prod/              # Production credentials
│       └── demo/              # Demo credentials
├── preferences/               # Trading preferences
├── trade_history/            # Trade history data
├── active_trades/            # Active trade data
└── accounts/                 # Account data
```

## Verification

### Check System Status
```bash
# Check if all services are running
supervisorctl -c backend/supervisord.conf status

# Check web interface
curl http://localhost:3000/health

# Check logs
tail -f logs/main_app.out.log
```

### Test Database Connection
```bash
# Run database tests
./scripts/test_database.sh
```

## Troubleshooting

### Common Issues

#### 1. Setup Script Not Found
```bash
# If setup script is missing, create basic structure manually
mkdir -p backend/data/users/user_0001/credentials/kalshi-credentials/prod
mkdir -p backend/data/users/user_0001/preferences
mkdir -p backend/data/users/user_0001/trade_history
mkdir -p backend/data/users/user_0001/active_trades
mkdir -p backend/data/users/user_0001/accounts
```

#### 2. Permission Errors
```bash
# Fix permissions
chmod -R 700 backend/data/users/user_0001/credentials
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/*
```

#### 3. Database Connection Issues
```bash
# Test database connection
./scripts/test_database.sh --quick

# Check PostgreSQL status
sudo systemctl status postgresql
```

#### 4. Services Not Starting
```bash
# Restart all services
./scripts/MASTER_RESTART.sh

# Check logs for errors
tail -f logs/*.out.log
```

## Next Steps

After successful setup:

1. **Explore the web interface** - Familiarize yourself with the dashboard
2. **Configure trading preferences** - Set up your risk tolerance and position sizes
3. **Test with demo mode** - Use demo credentials to test trading features
4. **Set up notifications** - Configure email/SMS alerts for trades
5. **Monitor performance** - Use the built-in monitoring tools

## Support

If you encounter issues:

1. Check the logs: `tail -f logs/*.out.log`
2. Run diagnostics: `./scripts/test_database.sh`
3. Restart services: `./scripts/MASTER_RESTART.sh`
4. Review this guide and the main deployment guide
5. Check the troubleshooting section in `docs/DEPLOYMENT_GUIDE.md`

## Security Reminders

- **Never commit credentials** to version control
- **Use strong passwords** for database and API access
- **Keep credentials secure** with proper file permissions
- **Regular backups** of your user data
- **Monitor system logs** for unusual activity

## File Permissions Reference

```bash
# Secure credential files
chmod 600 backend/data/users/user_0001/credentials/kalshi-credentials/prod/*

# Secure credential directories
chmod 700 backend/data/users/user_0001/credentials

# Standard user data
chmod 755 backend/data/users/user_0001/trade_history
chmod 755 backend/data/users/user_0001/active_trades
chmod 755 backend/data/users/user_0001/accounts
```
