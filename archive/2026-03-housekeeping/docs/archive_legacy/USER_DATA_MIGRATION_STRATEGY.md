# 🔐 USER DATA MIGRATION STRATEGY

## Overview

This document outlines the strategy for managing user-specific data (credentials, databases, preferences) in a way that allows for clean deployments and user-supervised migrations between environments.

## 📋 USER-SPECIFIC ELEMENTS IDENTIFIED

### 🔐 **CREDENTIALS & AUTHENTICATION**
```
backend/api/kalshi-api/kalshi-credentials/
├── demo/
│   └── kalshi.pem
└── prod/
    └── kalshi-auth.txt
```

### 🗄️ **USER DATABASES**
```
backend/data/accounts/kalshi/
├── demo/
│   ├── fills.db (147KB)
│   ├── positions.db (20KB)
│   ├── settlements.db (20KB)
│   ├── account_balance.json
│   ├── fills.json
│   ├── positions.json
│   └── settlements.json
└── prod/
    └── (production account data)
```

### ⚙️ **USER PREFERENCES & STATE**
```
backend/data/
├── preferences/
│   ├── auto_entry_settings.json
│   ├── auto_stop_settings.json
│   └── trade_preferences.json
├── account_mode_state.json
└── port_config.json
```

### 📊 **TRADING DATA**
```
backend/data/
├── trade_history/trades.db
├── active_trades/active_trades.db
└── price_history/btc_price_history.db
```

---

## 🏗️ PROPOSED DATA ARCHITECTURE

### **Core Application (Deployable)**
```
/opt/trading_system/
├── backend/           # Application code
├── frontend/          # Web interface
├── scripts/           # Deployment scripts
├── config/            # System configuration
└── requirements.txt   # Dependencies
```

### **User Data (Separate)**
```
/opt/trading_system/user_data/
├── credentials/
│   ├── kalshi/
│   │   ├── demo/
│   │   └── prod/
│   └── other_apis/
├── databases/
│   ├── accounts/
│   ├── trade_history/
│   └── price_history/
├── preferences/
│   ├── trading/
│   ├── system/
│   └── ui/
└── state/
    ├── account_mode.json
    └── system_state.json
```

---

## 🔧 IMPLEMENTATION STRATEGY

### **Phase 1: Data Separation**

#### **1.1 Create User Data Structure**
```bash
# Create user data directory structure
mkdir -p /opt/trading_system/user_data/{credentials,databases,preferences,state}

# Create subdirectories
mkdir -p /opt/trading_system/user_data/credentials/kalshi/{demo,prod}
mkdir -p /opt/trading_system/user_data/databases/{accounts,trade_history,price_history}
mkdir -p /opt/trading_system/user_data/preferences/{trading,system,ui}
```

#### **1.2 Update Application Paths**
```python
# In config.json - Add user data paths
{
  "user_data": {
    "base_path": "/opt/trading_system/user_data",
    "credentials": "/opt/trading_system/user_data/credentials",
    "databases": "/opt/trading_system/user_data/databases",
    "preferences": "/opt/trading_system/user_data/preferences",
    "state": "/opt/trading_system/user_data/state"
  }
}
```

#### **1.3 Create Migration Scripts**
```bash
# scripts/migrate_user_data.sh
# scripts/backup_user_data.sh
# scripts/restore_user_data.sh
```

### **Phase 2: Deployment Integration**

#### **2.1 Update Installation Script**
```bash
# In install_digitalocean.sh
# Create user data directories
mkdir -p /opt/trading_system/user_data/{credentials,databases,preferences,state}

# Set permissions
chown -R trading_user:trading_user /opt/trading_system/user_data
chmod -R 700 /opt/trading_system/user_data
```

#### **2.2 Create User Data Templates**
```bash
# Create template files for new deployments
/opt/trading_system/user_data/
├── credentials/
│   └── kalshi/
│       ├── demo/
│       │   └── kalshi.pem.template
│       └── prod/
│           └── kalshi-auth.txt.template
├── preferences/
│   └── trading/
│       └── trade_preferences.json.template
└── state/
    └── account_mode.json.template
```

---

## 📦 MIGRATION SCRIPTS

### **1. User Data Backup Script**
```bash
#!/bin/bash
# scripts/backup_user_data.sh

USER_DATA_DIR="/opt/trading_system/user_data"
BACKUP_DIR="/opt/backups/user_data_$(date +%Y%m%d_%H%M%S)"

# Create backup
mkdir -p "$BACKUP_DIR"
cp -r "$USER_DATA_DIR" "$BACKUP_DIR/"

# Create compressed archive
tar -czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
rm -rf "$BACKUP_DIR"

echo "User data backed up to: $BACKUP_DIR.tar.gz"
```

### **2. User Data Migration Script**
```bash
#!/bin/bash
# scripts/migrate_user_data.sh

SOURCE_DIR="$1"
TARGET_DIR="/opt/trading_system/user_data"

# Validate source
if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Error: Source directory not found: $SOURCE_DIR"
    exit 1
fi

# Stop services
systemctl stop trading_system.service

# Backup current user data
./scripts/backup_user_data.sh

# Migrate user data
cp -r "$SOURCE_DIR"/* "$TARGET_DIR/"

# Set permissions
chown -R trading_user:trading_user "$TARGET_DIR"
chmod -R 700 "$TARGET_DIR"

# Restart services
systemctl start trading_system.service

echo "User data migrated successfully"
```

### **3. User Data Restore Script**
```bash
#!/bin/bash
# scripts/restore_user_data.sh

BACKUP_FILE="$1"
TARGET_DIR="/opt/trading_system/user_data"

# Validate backup file
if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Stop services
systemctl stop trading_system.service

# Extract backup
tar -xzf "$BACKUP_FILE" -C /tmp
BACKUP_DIR=$(find /tmp -name "user_data_*" -type d | head -1)

# Restore user data
cp -r "$BACKUP_DIR"/* "$TARGET_DIR/"

# Set permissions
chown -R trading_user:trading_user "$TARGET_DIR"
chmod -R 700 "$TARGET_DIR"

# Cleanup
rm -rf "$BACKUP_DIR"

# Restart services
systemctl start trading_system.service

echo "User data restored successfully"
```

---

## 🔄 DEPLOYMENT WORKFLOW

### **New Deployment (Clean)**
```bash
# 1. Deploy application
./scripts/deploy_digitalocean.sh --server NEW_SERVER_IP

# 2. Create user data structure
ssh root@NEW_SERVER_IP "mkdir -p /opt/trading_system/user_data/{credentials,databases,preferences,state}"

# 3. User provides credentials and preferences
# (Manual step - user uploads their data)
```

### **Migration Deployment**
```bash
# 1. Backup current user data
./scripts/backup_user_data.sh

# 2. Deploy to new server
./scripts/deploy_digitalocean.sh --server NEW_SERVER_IP

# 3. Migrate user data
./scripts/migrate_user_data.sh /path/to/backup/user_data

# 4. Verify migration
ssh root@NEW_SERVER_IP "supervisorctl -c /opt/trading_system/backend/supervisord.conf status"
```

### **Update Existing Deployment**
```bash
# 1. Backup user data
./scripts/backup_user_data.sh

# 2. Update application
./scripts/deploy_digitalocean.sh --server SERVER_IP --mode update

# 3. Restore user data (if needed)
./scripts/restore_user_data.sh /path/to/backup.tar.gz
```

---

## 🔐 SECURITY CONSIDERATIONS

### **Credential Protection**
```bash
# Secure credential storage
chmod 600 /opt/trading_system/user_data/credentials/kalshi/*/kalshi.pem
chmod 600 /opt/trading_system/user_data/credentials/kalshi/*/kalshi-auth.txt

# Restrict access
chown trading_user:trading_user /opt/trading_system/user_data/credentials
chmod 700 /opt/trading_system/user_data/credentials
```

### **Database Security**
```bash
# Secure database files
chmod 600 /opt/trading_system/user_data/databases/*/*.db
chown trading_user:trading_user /opt/trading_system/user_data/databases
```

### **Backup Security**
```bash
# Encrypt backups (optional)
gpg --encrypt --recipient user@example.com backup.tar.gz
```

---

## 📋 MIGRATION CHECKLIST

### **Pre-Migration**
- [ ] Backup current user data
- [ ] Document current configuration
- [ ] Verify credential validity
- [ ] Test migration scripts locally

### **During Migration**
- [ ] Stop trading system
- [ ] Backup user data
- [ ] Deploy new system
- [ ] Migrate user data
- [ ] Verify data integrity
- [ ] Test functionality

### **Post-Migration**
- [ ] Verify all services running
- [ ] Test trading functionality
- [ ] Verify credential access
- [ ] Check database integrity
- [ ] Monitor system performance

---

## 🎯 IMPLEMENTATION PLAN

### **Immediate Actions**
1. **Create user data directory structure**
2. **Update application configuration paths**
3. **Create migration scripts**
4. **Test migration process locally**

### **Deployment Integration**
1. **Update installation scripts**
2. **Create user data templates**
3. **Add migration options to deployment script**
4. **Document migration procedures**

### **User Documentation**
1. **Create migration guide**
2. **Document backup procedures**
3. **Provide troubleshooting steps**
4. **Create user data management guide**

---

## 📊 JSON SUMMARY

```json
{
  "user_data_migration_strategy": {
    "status": "planned",
    "architecture": {
      "core_application": "/opt/trading_system/",
      "user_data": "/opt/trading_system/user_data/",
      "separation": "complete"
    },
    "user_specific_elements": {
      "credentials": {
        "kalshi_demo": "backend/api/kalshi-api/kalshi-credentials/demo/",
        "kalshi_prod": "backend/api/kalshi-api/kalshi-credentials/prod/",
        "migration_path": "/opt/trading_system/user_data/credentials/"
      },
      "databases": {
        "account_data": "backend/data/accounts/kalshi/",
        "trade_history": "backend/data/trade_history/",
        "price_history": "backend/data/price_history/",
        "migration_path": "/opt/trading_system/user_data/databases/"
      },
      "preferences": {
        "trading_prefs": "backend/data/preferences/",
        "account_state": "backend/data/account_mode_state.json",
        "migration_path": "/opt/trading_system/user_data/preferences/"
      }
    },
    "migration_scripts": {
      "backup": "scripts/backup_user_data.sh",
      "migrate": "scripts/migrate_user_data.sh",
      "restore": "scripts/restore_user_data.sh"
    },
    "deployment_workflow": {
      "new_deployment": "Clean install with user data setup",
      "migration_deployment": "Deploy + migrate existing user data",
      "update_deployment": "Update app + preserve user data"
    },
    "security": {
      "credential_protection": "600 permissions, restricted access",
      "database_security": "600 permissions, user ownership",
      "backup_security": "Optional GPG encryption"
    }
  }
}
```

---

## 🚀 NEXT STEPS

1. **Implement user data directory structure**
2. **Create migration scripts**
3. **Update application configuration**
4. **Test migration process**
5. **Update deployment documentation**
6. **Create user migration guide**

**This strategy ensures clean deployments while preserving user-specific data and allowing for supervised migrations between environments.** 