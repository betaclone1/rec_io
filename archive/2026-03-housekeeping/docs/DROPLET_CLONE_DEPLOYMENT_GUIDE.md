# Droplet Clone and Sanitization Deployment Guide

## Overview

This guide describes the new deployment strategy for REC.IO that clones your production Digital Ocean droplet and sanitizes it for new users. This approach eliminates the complexity of fresh installations and ensures new users get a fully functional system immediately.

## Why This Approach?

### Benefits
- **Guaranteed Functionality**: New users get an exact copy of your working system
- **No Installation Issues**: Eliminates all the installation problems we've encountered
- **Rapid Deployment**: Complete system setup in minutes instead of hours
- **Consistent Environment**: All users have identical system configurations
- **Zero Downtime**: Original system remains completely unaffected

### How It Works
1. **Snapshot Creation**: Creates a snapshot of your production droplet
2. **Droplet Cloning**: Creates a new droplet from the snapshot
3. **Data Sanitization**: Removes all user-specific data and credentials
4. **User Configuration**: Sets up new user information and credentials
5. **System Restart**: Runs MASTER RESTART to configure everything

## Prerequisites

### On Your Production Droplet
1. **Digital Ocean CLI (doctl)**: Must be installed and authenticated
   ```bash
   # Install doctl
   snap install doctl
   
   # Authenticate
   doctl auth init
   ```

2. **SSH Access**: Ensure SSH keys are configured for droplet access

3. **System Status**: Ensure your production system is running properly

## Usage

### Step 1: Run the Clone Script
```bash
# From your production droplet
cd /opt/rec_io
./scripts/clone_and_sanitize_droplet.sh
```

### Step 2: Provide User Information
The script will prompt for:
- **User ID**: Format `user_XXXX` (e.g., `user_0002`)
- **Full Name**: User's complete name
- **Email Address**: User's email
- **Phone Number**: User's phone number
- **Password**: User's login password

### Step 3: Provide Kalshi Credentials (Optional)
- **Kalshi Email**: User's Kalshi account email
- **API Key**: User's Kalshi API key
- **API Secret**: User's Kalshi API secret

If credentials are skipped, the system will run in demo mode until added later.

## What the Script Does

### 1. Snapshot Creation
- Creates a timestamped snapshot of your production droplet
- Waits for snapshot completion
- Provides snapshot name for future reference

### 2. New Droplet Creation
- Creates new droplet with same specifications as production
- Uses the snapshot as the base image
- Waits for droplet to become active
- Provides new droplet IP address

### 3. Data Sanitization
- **Stops all services** on the new droplet
- **Clears all user data** from database tables:
  - `users.trades_0001`
  - `users.active_trades_0001`
  - `users.fills_0001`
  - `users.settlements_0001`
  - `users.positions_0001`
  - `users.trade_preferences_0001`
  - `users.orders_0001`
  - `users.account_balance_0001`
  - `users.watchlist_0001`
  - `users.auto_trade_settings_0001`
- **Resets all sequences** to start from 1
- **Clears system health data**
- **Clears live data** (keeps structure, removes data)
- **Removes all credential files**
- **Removes user-specific files**
- **Clears all logs**

### 4. New User Configuration
- **Creates new user directory structure** with proper permissions
- **Creates user_info.json** with new user details
- **Sets up Kalshi credentials** (if provided)
- **Creates new database tables** for the new user ID
- **Copies credentials** to system-expected locations

### 5. System Restart
- **Runs MASTER RESTART** to configure all services
- **Verifies service status**
- **Tests system functionality**

## Output

### New Droplet Information
The script provides:
- **Droplet Name**: `rec_io_user_XXXX_YYYYMMDD`
- **Droplet ID**: Digital Ocean droplet ID
- **IP Address**: Public IP for access
- **User ID**: New user identifier
- **User Details**: Name, email, phone

### Access Information
- **Web Interface**: `http://NEW_DROPLET_IP:3000`
- **Health Check**: `http://NEW_DROPLET_IP:3000/health`
- **SSH Access**: `ssh root@NEW_DROPLET_IP`

## Security Features

### Data Sanitization
- **Complete removal** of all original user data
- **Credential deletion** from all locations
- **Database cleanup** with sequence reset
- **File system cleanup** of user-specific files

### User Isolation
- **Separate user directories** for each new user
- **Individual database tables** per user ID
- **Isolated credential storage**
- **No cross-user data access**

### Credential Management
- **Secure file permissions** (600 for credential files)
- **Directory permissions** (700 for credential directories)
- **Multiple location support** for system compatibility
- **Placeholder files** for missing credentials

## Troubleshooting

### Common Issues

#### 1. doctl Not Installed
```bash
# Install doctl
snap install doctl

# Authenticate
doctl auth init
```

#### 2. SSH Connection Failed
- Verify SSH keys are configured
- Check firewall settings
- Ensure droplet is active

#### 3. Database Connection Failed
- Verify PostgreSQL is running
- Check database credentials
- Ensure database exists

#### 4. Services Not Starting
- Check MASTER RESTART logs
- Verify supervisor configuration
- Check port availability

### Recovery Options

#### If Script Fails Mid-Process
1. **Check droplet status**: `doctl compute droplet list`
2. **Delete failed droplet**: `doctl compute droplet delete DROPLET_ID`
3. **Delete snapshot**: `doctl compute snapshot delete SNAPSHOT_ID`
4. **Rerun script**: `./scripts/clone_and_sanitize_droplet.sh`

#### If New User Needs Credentials Later
```bash
# SSH to new droplet
ssh root@NEW_DROPLET_IP

# Navigate to project
cd /opt/rec_io

# Add credentials manually
nano backend/data/users/USER_ID/credentials/kalshi-credentials/prod/kalshi-auth.txt

# Restart services
./scripts/MASTER_RESTART.sh
```

## Maintenance

### Cleanup Old Snapshots
```bash
# List snapshots
doctl compute snapshot list

# Delete old snapshots
doctl compute snapshot delete SNAPSHOT_ID
```

### Monitor Droplet Usage
```bash
# List all droplets
doctl compute droplet list

# Get droplet details
doctl compute droplet get DROPLET_ID
```

## Cost Considerations

### Digital Ocean Costs
- **Snapshot Storage**: ~$0.05/GB/month
- **Droplet Cloning**: No additional cost for snapshot creation
- **New Droplet**: Standard droplet pricing based on size

### Optimization Tips
- **Delete old snapshots** after successful deployment
- **Use appropriate droplet sizes** for new users
- **Monitor usage** to avoid unnecessary costs

## Best Practices

### Before Running
1. **Verify production system** is stable and working
2. **Check available disk space** for snapshot creation
3. **Ensure all services** are running properly
4. **Backup any critical data** (though original is unaffected)

### During Process
1. **Monitor the script output** for any errors
2. **Note the snapshot name** for future reference
3. **Record the new droplet IP** immediately
4. **Test the new system** before giving access

### After Deployment
1. **Verify all services** are running on new droplet
2. **Test web interface** functionality
3. **Confirm user access** works properly
4. **Clean up old snapshots** if no longer needed

## Example Output

```
=============================================================================
              DROPLET CLONE AND SANITIZATION SCRIPT
=============================================================================
[CLONE_SANITIZE] Starting droplet clone and sanitization process...

[CLONE_SANITIZE] ✅ Prerequisites check passed

[CLONE_SANITIZE] Collecting new user information...
Enter new user ID (e.g., user_0002): user_0002
Enter full name: John Doe
Enter email address: john@example.com
Enter phone number: +1234567890
Enter password: 
Confirm password: 
[CLONE_SANITIZE] ✅ User information collected

[CLONE_SANITIZE] Collecting Kalshi credentials...
Do you want to set up Kalshi credentials now?
1) Yes - I have my Kalshi credentials ready
2) No - I'll add them later (system will be limited to demo mode)
Enter 1 or 2: 1

Please enter your Kalshi credentials:
Kalshi Email: john@example.com
Kalshi API Key: api_key_here
Kalshi API Secret: api_secret_here
[CLONE_SANITIZE] ✅ Kalshi credentials collected

[CLONE_SANITIZE] Creating droplet snapshot...
[CLONE_SANITIZE] Found current droplet ID: 123456789
[CLONE_SANITIZE] Creating snapshot: rec_io_production_snapshot_20250127_143022
[CLONE_SANITIZE] Waiting for snapshot to complete...
[CLONE_SANITIZE] ✅ Snapshot created successfully: rec_io_production_snapshot_20250127_143022

[CLONE_SANITIZE] Creating new droplet from snapshot...
[CLONE_SANITIZE] Creating new droplet: rec_io_user_0002_20250127
[CLONE_SANITIZE] Region: nyc1, Size: s-1vcpu-1gb, Snapshot: 987654321
[CLONE_SANITIZE] ✅ New droplet created with ID: 987654321
[CLONE_SANITIZE] Waiting for droplet to become active...
[CLONE_SANITIZE] ✅ New droplet is active at IP: 192.168.1.100

New droplet details:
  Name: rec_io_user_0002_20250127
  ID: 987654321
  IP: 192.168.1.100

[CLONE_SANITIZE] Sanitizing user data on new droplet...
[CLONE_SANITIZE] ✅ User data sanitized

[CLONE_SANITIZE] Setting up new user configuration...
[CLONE_SANITIZE] ✅ New user configuration set up

[CLONE_SANITIZE] Running MASTER RESTART on new droplet...
[CLONE_SANITIZE] ✅ MASTER RESTART completed on new droplet

[CLONE_SANITIZE] Verifying system functionality...
[CLONE_SANITIZE] ✅ Web interface is accessible
[CLONE_SANITIZE] ✅ Health endpoint is responding
[CLONE_SANITIZE] ✅ System verification completed

=============================================================================
              DROPLET CLONE AND SANITIZATION SCRIPT
=============================================================================
[CLONE_SANITIZE] ✅ Droplet clone and sanitization completed successfully!

New droplet details:
  Name: rec_io_user_0002_20250127
  ID: 987654321
  IP: 192.168.1.100
  User ID: user_0002
  User Name: John Doe
  User Email: john@example.com

Access information:
  Web Interface: http://192.168.1.100:3000
  Health Check: http://192.168.1.100:3000/health
  SSH Access: ssh root@192.168.1.100

Next steps for the new user:
1. Access the web interface at http://192.168.1.100:3000
2. Log in with the credentials provided
3. Kalshi credentials are already configured
4. Configure trading preferences in the web interface

Important notes:
- All original user data has been completely removed
- The system is now configured for user: user_0002
- Original droplet remains unchanged
- Snapshot can be deleted after verification: rec_io_production_snapshot_20250127_143022

[CLONE_SANITIZE] ✅ Deployment completed successfully!
```

## Conclusion

This droplet cloning approach provides a robust, reliable, and efficient way to deploy REC.IO for new users. It eliminates the complexity and potential issues of fresh installations while ensuring each new user gets a fully functional, sanitized system that's ready for immediate use.

The process is completely automated, secure, and maintains full isolation between users while preserving the proven functionality of your production system.
