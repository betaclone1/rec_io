# 🔐 USER DATA MANAGEMENT GUIDE

## Overview

This guide explains how to manage user-specific data (credentials, databases, preferences) in the trading system, including backup, migration, and deployment strategies.

## 📋 USER DATA COMPONENTS

### **Credentials & Authentication**
```
/opt/trading_system/user_data/credentials/
├── kalshi/
│   ├── demo/
│   │   └── kalshi.pem          # Demo account credentials
│   └── prod/
│       └── kalshi-auth.txt     # Production account credentials
└── other_apis/                 # Future API credentials
```

### **User Databases**
```
/opt/trading_system/user_data/databases/
├── accounts/
│   └── kalshi/
│       ├── demo/
│       │   ├── fills.db        # Trade fills
│       │   ├── positions.db    # Open positions
│       │   └── settlements.db  # Account settlements
│       └── prod/
│           └── (production data)
├── trade_history/
│   └── trades.db               # Historical trades
└── price_history/
    └── btc_price_history.db    # BTC price data
```

### **User Preferences**
```
/opt/trading_system/user_data/preferences/
├── trading/
│   ├── trade_preferences.json  # Trading parameters
│   ├── auto_entry_settings.json # Auto-entry rules
│   └── auto_stop_settings.json # Stop-loss settings
├── system/
│   └── system_preferences.json # System configuration
└── ui/
    └── ui_preferences.json     # Interface settings
```

### **System State**
```
/opt/trading_system/user_data/state/
├── account_mode.json           # Demo/Production mode
└── system_state.json          # Current system state
```

---

## 🔧 USER DATA MANAGEMENT SCRIPTS

### **Backup User Data**
```bash
# Create backup of all user data
sudo ./scripts/backup_user_data.sh

# Create encrypted backup
sudo ./scripts/backup_user_data.sh --encrypt

# Create backup with custom name
sudo ./scripts/backup_user_data.sh --name my_backup_$(date +%Y%m%d)
```

### **Migrate User Data**
```bash
# Migrate from local development to server
sudo ./scripts/migrate_user_data.sh /path/to/local/user_data

# Dry run (see what would be migrated)
sudo ./scripts/migrate_user_data.sh /path/to/user_data --dry-run

# Force migration (overwrite existing data)
sudo ./scripts/migrate_user_data.sh /path/to/user_data --force
```

### **Restore User Data**
```bash
# Restore from backup file
sudo ./scripts/restore_user_data.sh /opt/backups/user_data_20250728_143022.tar.gz

# Restore encrypted backup
sudo ./scripts/restore_user_data.sh /opt/backups/user_data_20250728_143022.tar.gz.gpg
```

---

## 🚀 DEPLOYMENT SCENARIOS

### **Scenario 1: New Deployment (Clean)**
```bash
# 1. Deploy application without user data
./scripts/deploy_digitalocean.sh --server NEW_SERVER_IP

# 2. Create user data structure
ssh root@NEW_SERVER_IP "mkdir -p /opt/trading_system/user_data/{credentials,databases,preferences,state}"

# 3. User provides credentials manually
# - Upload kalshi.pem to /opt/trading_system/user_data/credentials/kalshi/demo/
# - Upload kalshi-auth.txt to /opt/trading_system/user_data/credentials/kalshi/prod/
# - Configure preferences in /opt/trading_system/user_data/preferences/
```

### **Scenario 2: Migration Deployment**
```bash
# 1. Backup current user data
sudo ./scripts/backup_user_data.sh

# 2. Deploy to new server
./scripts/deploy_digitalocean.sh --server NEW_SERVER_IP

# 3. Migrate user data
sudo ./scripts/migrate_user_data.sh /opt/backups/user_data_20250728_143022/user_data

# 4. Verify migration
ssh root@NEW_SERVER_IP "supervisorctl -c /opt/trading_system/backend/supervisord.conf status"
```

### **Scenario 3: Update Existing Deployment**
```bash
# 1. Backup user data
sudo ./scripts/backup_user_data.sh

# 2. Update application
./scripts/deploy_digitalocean.sh --server SERVER_IP --mode update

# 3. User data is preserved automatically
# (No additional steps needed)
```

---

## 🔐 SECURITY CONSIDERATIONS

### **Credential Protection**
```bash
# Set proper permissions for credentials
chmod 600 /opt/trading_system/user_data/credentials/kalshi/*/kalshi.pem
chmod 600 /opt/trading_system/user_data/credentials/kalshi/*/kalshi-auth.txt

# Restrict access to credentials directory
chmod 700 /opt/trading_system/user_data/credentials
chown trading_user:trading_user /opt/trading_system/user_data/credentials
```

### **Database Security**
```bash
# Secure database files
chmod 600 /opt/trading_system/user_data/databases/*/*.db
chown trading_user:trading_user /opt/trading_system/user_data/databases
```

### **Backup Security**
```bash
# Encrypt sensitive backups
sudo ./scripts/backup_user_data.sh --encrypt

# Store backups securely
# - Use encrypted storage
# - Limit access to backup files
# - Regular backup rotation
```

---

## 📊 USER DATA BACKUP STRATEGY

### **Automated Backups**
```bash
# Add to crontab for daily backups
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/trading_system/scripts/backup_user_data.sh") | crontab -

# Weekly encrypted backups
(crontab -l 2>/dev/null; echo "0 3 * * 0 /opt/trading_system/scripts/backup_user_data.sh --encrypt") | crontab -
```

### **Backup Retention**
- **Daily backups**: Keep 7 days
- **Weekly backups**: Keep 4 weeks
- **Monthly backups**: Keep 12 months

### **Backup Verification**
```bash
# Verify backup integrity
tar -tzf /opt/backups/user_data_20250728_143022.tar.gz

# Test backup restoration
sudo ./scripts/restore_user_data.sh /opt/backups/user_data_20250728_143022.tar.gz --dry-run
```

---

## 🔄 MIGRATION WORKFLOW

### **Pre-Migration Checklist**
- [ ] Backup current user data
- [ ] Document current configuration
- [ ] Verify credential validity
- [ ] Test migration scripts locally
- [ ] Ensure sufficient disk space

### **Migration Process**
```bash
# 1. Stop trading system
sudo systemctl stop trading_system.service

# 2. Backup existing data
sudo ./scripts/backup_user_data.sh

# 3. Migrate user data
sudo ./scripts/migrate_user_data.sh /path/to/source/user_data

# 4. Start trading system
sudo systemctl start trading_system.service

# 5. Verify migration
sudo supervisorctl -c /opt/trading_system/backend/supervisord.conf status
```

### **Post-Migration Verification**
- [ ] All services running
- [ ] Credentials working
- [ ] Database integrity
- [ ] Trading functionality
- [ ] Performance monitoring

---

## 🛠️ TROUBLESHOOTING

### **Common Issues**

**Issue**: Credentials not working after migration
```bash
# Check credential permissions
ls -la /opt/trading_system/user_data/credentials/kalshi/*/

# Fix permissions
chmod 600 /opt/trading_system/user_data/credentials/kalshi/*/kalshi.pem
chmod 600 /opt/trading_system/user_data/credentials/kalshi/*/kalshi-auth.txt
```

**Issue**: Database errors after migration
```bash
# Check database integrity
sqlite3 /opt/trading_system/user_data/databases/accounts/kalshi/demo/fills.db "PRAGMA integrity_check;"

# Optimize databases
/opt/trading_system/scripts/optimize_databases.sh
```

**Issue**: Services not starting after migration
```bash
# Check service logs
journalctl -u trading_system.service -f

# Check supervisor status
supervisorctl -c /opt/trading_system/backend/supervisord.conf status

# Restart services
sudo systemctl restart trading_system.service
```

### **Recovery Procedures**

**Emergency Recovery**
```bash
# Stop all services
sudo systemctl stop trading_system.service

# Restore from backup
sudo ./scripts/restore_user_data.sh /opt/backups/latest_backup.tar.gz

# Start services
sudo systemctl start trading_system.service
```

**Partial Recovery**
```bash
# Restore specific components
cp /opt/backups/user_data_20250728_143022/user_data/credentials /opt/trading_system/user_data/
cp /opt/backups/user_data_20250728_143022/user_data/preferences /opt/trading_system/user_data/

# Set permissions
chmod -R 700 /opt/trading_system/user_data
chown -R trading_user:trading_user /opt/trading_system/user_data
```

---

## 📋 USER DATA CHECKLIST

### **Before Deployment**
- [ ] Backup current user data
- [ ] Document current configuration
- [ ] Verify credential validity
- [ ] Test migration scripts
- [ ] Prepare user data templates

### **During Deployment**
- [ ] Create user data structure
- [ ] Set proper permissions
- [ ] Migrate user data
- [ ] Verify data integrity
- [ ] Test functionality

### **After Deployment**
- [ ] Verify all services running
- [ ] Test trading functionality
- [ ] Monitor system performance
- [ ] Document migration results
- [ ] Update backup procedures

---

## 📊 JSON SUMMARY

```json
{
  "user_data_management": {
    "components": {
      "credentials": {
        "location": "/opt/trading_system/user_data/credentials/",
        "files": ["kalshi.pem", "kalshi-auth.txt"],
        "permissions": "600"
      },
      "databases": {
        "location": "/opt/trading_system/user_data/databases/",
        "files": ["fills.db", "positions.db", "settlements.db", "trades.db"],
        "permissions": "600"
      },
      "preferences": {
        "location": "/opt/trading_system/user_data/preferences/",
        "files": ["trade_preferences.json", "auto_entry_settings.json"],
        "permissions": "644"
      },
      "state": {
        "location": "/opt/trading_system/user_data/state/",
        "files": ["account_mode.json", "system_state.json"],
        "permissions": "644"
      }
    },
    "management_scripts": {
      "backup": "scripts/backup_user_data.sh",
      "migrate": "scripts/migrate_user_data.sh",
      "restore": "scripts/restore_user_data.sh"
    },
    "deployment_scenarios": {
      "new_deployment": "Clean install with manual user data setup",
      "migration_deployment": "Deploy + migrate existing user data",
      "update_deployment": "Update app + preserve user data"
    },
    "security": {
      "credential_protection": "600 permissions, restricted access",
      "database_security": "600 permissions, user ownership",
      "backup_security": "Optional GPG encryption"
    },
    "backup_strategy": {
      "automated": "Daily backups via cron",
      "encrypted": "Weekly encrypted backups",
      "retention": "7 days daily, 4 weeks weekly, 12 months monthly"
    }
  }
}
```

---

## 🎯 BEST PRACTICES

1. **Always backup before migration**
2. **Test migration scripts in development first**
3. **Verify data integrity after migration**
4. **Use encrypted backups for sensitive data**
5. **Document all migration procedures**
6. **Monitor system performance after migration**
7. **Keep multiple backup copies**
8. **Regular backup testing and restoration**

**This guide ensures safe and reliable user data management across deployments and migrations.** 