# Kalshi Credentials Setup Bug Report

**Date:** August 20, 2025  
**Severity:** High  
**Component:** `collaborator_setup.sh`  
**Issue:** Kalshi credentials not properly configured after setup

## Problem Description

After running the `collaborator_setup.sh` script, the Kalshi account sync service fails to connect with **HTTP 401 Unauthorized** errors. The system continues to use old credentials from `user_0001` instead of the newly configured user credentials.

## Current Behavior

1. ✅ **Setup script runs successfully** - User information is added to database
2. ✅ **Kalshi credentials are collected** - API key and secret are captured
3. ❌ **Credential files are not written to correct location** - System still uses old `user_0001` credentials
4. ❌ **Kalshi account sync fails** - HTTP 401 errors prevent balance display

## Root Cause Analysis

### Issue Location
The problem occurs in the `collaborator_setup.sh` script around line 100 where it should:
1. Create the new user directory structure
2. Write credentials to the correct location
3. Update configuration files to point to new credentials

### Current File Structure
```
/opt/rec_io_server/backend/data/users/
├── user_0001/  # Old credentials (still being used)
│   └── credentials/kalshi-credentials/prod/
│       ├── kalshi-auth.txt
│       └── kalshi.pem
└── m_pistorio/  # Missing - should contain new credentials
```

### Configuration Issue
The system config still points to:
```json
"credentials_path": "backend/data/users/user_0001/credentials/kalshi-credentials"
```

## Error Logs

```
[2025-08-20 18:42:15.405017-04:00] ❌ Failed to connect to User Fills WebSocket: server rejected WebSocket connection: HTTP 401
[2025-08-20 18:42:15.405066-04:00] ❌ Failed to connect, retrying in 5 seconds...
[2025-08-20 18:42:15.212334-04:00] 🔑 Using API Key: 8b5698ec...  # Old API key
```

## Expected Behavior

After setup, the system should:
1. ✅ Create directory: `/opt/rec_io_server/backend/data/users/m_pistorio/credentials/kalshi-credentials/prod/`
2. ✅ Write `kalshi-auth.txt` with new API key and email
3. ✅ Write `kalshi.pem` with new private key
4. ✅ Update configuration to point to new credentials path
5. ✅ Restart services with new credentials

## Proposed Fix

### 1. Fix Directory Creation
```bash
# In collaborator_setup.sh, after collecting credentials:
USER_ID="m_pistorio"  # From user input
CREDS_DIR="/opt/rec_io_server/backend/data/users/${USER_ID}/credentials/kalshi-credentials/prod"

# Create directory structure
mkdir -p "${CREDS_DIR}"
```

### 2. Fix Credential File Writing
```bash
# Write auth file
cat > "${CREDS_DIR}/kalshi-auth.txt" << EOF
${KALSHI_EMAIL}
${KALSHI_API_KEY}
EOF

# Write PEM file
cat > "${CREDS_DIR}/kalshi.pem" << EOF
${KALSHI_API_SECRET}
EOF
```

### 3. Fix Configuration Update
```bash
# Update the config.json to point to new credentials
CONFIG_FILE="/opt/rec_io_server/backend/api/kalshi-api/backend/core/config/config.json"
sed -i "s|user_0001|${USER_ID}|g" "${CONFIG_FILE}"
```

### 4. Fix Service Restart
```bash
# Ensure services are restarted with new configuration
supervisorctl restart kalshi_account_sync
supervisorctl restart kalshi_market_watchdog
```

## Testing Steps

1. **Run setup script** with new user credentials
2. **Verify directory creation** - Check `/opt/rec_io_server/backend/data/users/m_pistorio/`
3. **Verify credential files** - Check `kalshi-auth.txt` and `kalshi.pem`
4. **Verify config update** - Check `config.json` points to new path
5. **Test connection** - Check logs for successful Kalshi connection
6. **Verify balance display** - Check web interface shows correct balance

## Files to Modify

- `scripts/collaborator_setup.sh` - Main setup script
- `backend/api/kalshi-api/backend/core/config/config.json` - Configuration template

## Impact

- **User Experience:** Cannot see Kalshi account balance
- **Trading Functionality:** Account sync fails, may affect trading operations
- **System Reliability:** Continuous error logs and failed connection attempts

## Priority

**High Priority** - This affects core functionality and user experience. Users cannot verify their account status or proceed with trading setup.

## Additional Notes

- The setup script successfully updates the database but fails at the file system level
- This suggests a disconnect between database operations and file system operations
- Consider adding validation steps to ensure all components are properly configured
- Add logging to track each step of the credential setup process

---

**Reported By:** AI Assistant  
**Environment:** DigitalOcean Droplet (Ubuntu 22.04.4 LTS)  
**REC.IO Version:** Production Snapshot (August 19, 2025)
