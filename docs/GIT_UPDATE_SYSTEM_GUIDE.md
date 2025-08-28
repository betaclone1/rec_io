# Git Update System Guide for REC.IO Collaborators

## Overview

The REC.IO Git Update System allows collaborators to easily pull updates from the main repository and update their codebase without losing their local data. This system is automatically configured during the collaborator setup process.

## How It Works

### 1. **Automatic Setup**
During the collaborator setup process, the system automatically:
- ✅ **Initializes a Git repository** in `/opt/rec_io`
- ✅ **Connects to the main repository** (`https://github.com/betaclone1/rec_io.git`)
- ✅ **Sets up the update script** (`scripts/git_update_system.sh`)
- ✅ **Preserves user data** during updates

### 2. **Safe Update Process**
The update system ensures your data is never lost:
- ✅ **Creates automatic backups** before each update
- ✅ **Stashes local changes** if any exist
- ✅ **Pulls latest updates** from the repository
- ✅ **Updates dependencies** and configurations
- ✅ **Restarts services** with new code
- ✅ **Verifies the update** was successful

## Using the Git Update System

### **Check for Updates**
```bash
cd /opt/rec_io
./scripts/git_update_system.sh check
```

**What this does:**
- Fetches latest changes from the repository
- Shows if updates are available
- Displays what commits would be applied
- **Does NOT apply any changes**

**Example output:**
```
[GIT_UPDATE] Checking for available updates...
[GIT_UPDATE] ✅ Fetched latest changes
[GIT_UPDATE] ⚠️ Updates available:
a1b2c3d Add new trading feature
e4f5g6h Fix bug in price monitoring
h7i8j9k Update documentation

[GIT_UPDATE] Run './scripts/git_update_system.sh update' to apply these updates
```

### **Apply Updates**
```bash
cd /opt/rec_io
./scripts/git_update_system.sh update
```

**What this does:**
1. **Creates backup** of your current system
2. **Stashes local changes** (if any)
3. **Pulls latest updates** from repository
4. **Updates Python dependencies**
5. **Regenerates configurations**
6. **Restarts all services**
7. **Verifies the update** was successful

**Example output:**
```
=============================================================================
                    REC.IO GIT UPDATE SYSTEM
=============================================================================
[GIT_UPDATE] Starting REC.IO git update process...
[GIT_UPDATE] ✅ Creating backup of current system...
[GIT_UPDATE] ✅ Backup created at: /opt/rec_io/backup/pre_update_backup_20250127_143022
[GIT_UPDATE] ✅ No local changes detected
[GIT_UPDATE] ✅ Fetched latest changes
[GIT_UPDATE] Updates available:
a1b2c3d Add new trading feature
e4f5g6h Fix bug in price monitoring
[GIT_UPDATE] ✅ Successfully pulled updates
[GIT_UPDATE] ✅ Python dependencies updated
[GIT_UPDATE] ✅ System configurations regenerated
[GIT_UPDATE] ✅ Services restarted successfully
[GIT_UPDATE] ✅ Web interface is responding
[GIT_UPDATE] ✅ Update verification completed

==========================================
        GIT UPDATE COMPLETED
==========================================

✅ Updated to commit: a1b2c3d Add new trading feature
✅ Backup created at: /opt/rec_io/backup/pre_update_backup_20250127_143022
✅ Update log: /opt/rec_io/logs/git_update_20250127_143022.log

📋 Next Steps:
1. Check the web interface: http://YOUR_IP:3000
2. Verify all features work correctly
3. Check logs if needed: tail -f logs/*.out.log
4. If issues occur, restore from backup: /opt/rec_io/backup/pre_update_backup_20250127_143022

[GIT_UPDATE] ✅ Git update completed successfully!
```

### **Create Manual Backup**
```bash
cd /opt/rec_io
./scripts/git_update_system.sh backup
```

**What this does:**
- Creates a backup of your current system
- Includes user data, configurations, and logs
- Useful before making manual changes

### **Restore from Backup**
```bash
cd /opt/rec_io
./scripts/git_update_system.sh restore /path/to/backup
```

**What this does:**
- Restores your system from a previous backup
- Useful if an update causes issues
- Restarts services after restoration

## What Gets Backed Up

### **User Data**
- ✅ **User credentials** (`backend/data/users/`)
- ✅ **Trading preferences** and settings
- ✅ **Account information** and configurations

### **System Files**
- ✅ **Supervisor configuration** (`backend/supervisord.conf`)
- ✅ **Environment variables** (`.env`)
- ✅ **Log files** (`logs/`)

### **What's NOT Backed Up**
- ❌ **Virtual environment** (`venv/`) - Recreated during update
- ❌ **Database data** - Stored separately in PostgreSQL
- ❌ **Large data files** - Historical data, market data

## Update Process Details

### **Step 1: Backup Creation**
```bash
# Creates timestamped backup directory
/opt/rec_io/backup/pre_update_backup_YYYYMMDD_HHMMSS/
├── users/                    # User data and credentials
├── supervisord.conf         # Supervisor configuration
├── .env                     # Environment variables
└── logs/                    # System logs
```

### **Step 2: Git Operations**
```bash
# Stash any local changes
git stash push -m "Auto-stash before git pull"

# Fetch and pull latest changes
git fetch origin
git pull origin main
```

### **Step 3: Dependency Updates**
```bash
# Activate virtual environment
source venv/bin/activate

# Update Python packages
pip install --upgrade pip
pip install -r requirements.txt --upgrade
```

### **Step 4: Configuration Regeneration**
```bash
# Regenerate supervisor configuration
./scripts/generate_supervisor_config.sh

# Regenerate system configurations
./scripts/generate_system_configs.sh
```

### **Step 5: Service Restart**
```bash
# Restart all services with new code
./scripts/MASTER_RESTART.sh
```

### **Step 6: Verification**
```bash
# Check service status
supervisorctl status

# Verify web interface
curl -f http://localhost:3000/health
```

## Troubleshooting

### **Update Fails**
If an update fails:

1. **Check the update log:**
   ```bash
   tail -f /opt/rec_io/logs/git_update_*.log
   ```

2. **Restore from backup:**
   ```bash
   ./scripts/git_update_system.sh restore /opt/rec_io/backup/pre_update_backup_YYYYMMDD_HHMMSS
   ```

3. **Check service status:**
   ```bash
   supervisorctl status
   ```

### **Web Interface Not Responding**
```bash
# Check if services are running
supervisorctl status

# Check logs for errors
tail -f logs/*.out.log

# Restart services manually
./scripts/MASTER_RESTART.sh
```

### **Git Repository Issues**
```bash
# Check git status
cd /opt/rec_io
git status

# Reinitialize git repository if needed
rm -rf .git
git init
git remote add origin https://github.com/betaclone1/rec_io.git
git fetch origin
git checkout -b main origin/main
```

## Best Practices

### **Before Updates**
1. **Check for updates** first: `./scripts/git_update_system.sh check`
2. **Review what's changing** in the commit list
3. **Ensure no active trades** are running
4. **Have a backup plan** ready

### **After Updates**
1. **Verify web interface** is working
2. **Check all features** function correctly
3. **Monitor logs** for any errors
4. **Test critical functionality**

### **Regular Maintenance**
1. **Check for updates weekly**
2. **Keep backups organized** (delete old ones)
3. **Monitor system performance**
4. **Report issues** to the development team

## Security Considerations

### **Data Protection**
- ✅ **User credentials** are always backed up
- ✅ **Trading data** is preserved in PostgreSQL
- ✅ **Configurations** are maintained
- ✅ **No data loss** during updates

### **Access Control**
- ✅ **Only authorized users** can run updates
- ✅ **Backup verification** before updates
- ✅ **Rollback capability** if issues occur
- ✅ **Audit trail** in update logs

## Integration with Development Workflow

### **Your Development Process**
1. **Make changes** to the codebase
2. **Test changes** thoroughly
3. **Push to repository** (`git push origin main`)
4. **Notify collaborators** of updates

### **Collaborator Update Process**
1. **Receive notification** of updates
2. **Check for updates** (`./scripts/git_update_system.sh check`)
3. **Apply updates** (`./scripts/git_update_system.sh update`)
4. **Verify functionality** and report any issues

## Support

### **Getting Help**
- **Check logs:** `tail -f /opt/rec_io/logs/git_update_*.log`
- **Review documentation:** This guide and system documentation
- **Contact development team:** For technical issues

### **Common Issues**
- **Update fails:** Check logs and restore from backup
- **Services not starting:** Check supervisor configuration
- **Web interface down:** Verify service status and restart
- **Git issues:** Reinitialize repository if needed

---

## Summary

The REC.IO Git Update System provides a **safe, automated way** for collaborators to keep their systems up to date:

- ✅ **One-command updates** with `./scripts/git_update_system.sh update`
- ✅ **Automatic backups** before every update
- ✅ **Data preservation** - no loss of user data or settings
- ✅ **Service management** - automatic restart of all services
- ✅ **Verification** - confirms updates were successful
- ✅ **Rollback capability** - restore from backup if needed

**This system ensures collaborators can easily stay current with the latest features and fixes while maintaining the security and stability of their trading systems.**
