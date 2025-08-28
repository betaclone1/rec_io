# Snapshot Security Guardrails

## Overview

This document describes the security guardrails implemented to prevent running REC.IO systems with original user data and credentials when deploying via snapshot transfer.

## The Security Problem

When you transfer a snapshot to a collaborator via Digital Ocean's UI:

1. **Complete System Clone**: The snapshot contains ALL your user data and credentials
2. **Immediate Access**: The collaborator can start the system immediately
3. **Security Risk**: Your Kalshi credentials and user data are exposed
4. **No Automatic Protection**: Digital Ocean doesn't provide built-in sanitization

## Our Security Solution

We've implemented a multi-layered security approach:

### Layer 1: First-Boot Automatic Sanitization

**What it does:**
- Automatically runs when a new droplet boots for the first time
- Completely removes all user data and credentials
- Prevents the system from running with original data

**How it works:**
```bash
# Systemd service runs on first boot
/etc/systemd/system/first-boot-sanitize.service

# Executes the sanitization script
/opt/rec_io/scripts/first_boot_sanitize.sh
```

**What it removes:**
- All database user data (trades, positions, credentials)
- **CRITICAL**: Master users table and views (ONLY exists on production server)
- All credential files from all locations
- All user-specific files and directories
- All logs and temporary data
- Resets all database sequences

### Layer 2: MASTER_RESTART Sanitization Check

**What it does:**
- Checks if system has been sanitized before allowing startup
- Blocks startup if sanitization hasn't occurred
- Provides clear instructions for remediation

**How it works:**
```bash
# Checks for sanitization flag
/opt/rec_io/.sanitization_complete

# If missing, blocks startup with error message
# If present, allows normal startup
```

**Security features:**
- **Production systems bypass check** (using `.production_system` flag)
- **Clear error messages** explaining the security risk
- **Instructions for proper sanitization**
- **User confirmation** for partially sanitized systems

### Layer 3: Visual Warnings and Documentation

**What it creates:**
- Prominent warning files in the project directory
- Clear instructions for proper setup
- Documentation about security requirements

**Files created:**
```
/opt/rec_io/SANITIZATION_WARNING.txt
/opt/rec_io/SNAPSHOT_DEPLOYMENT_README.md
```

## Installation Process

### Step 1: Install Security Guardrails (Your Side)

Before creating any snapshots, install the security system:

```bash
# On your production droplet
cd /opt/rec_io
./scripts/install_first_boot_sanitization.sh
```

This installs:
- First-boot sanitization service
- Production system flag
- Documentation and warnings

### Step 2: Create and Transfer Snapshot

```bash
# Create snapshot via Digital Ocean UI
# Transfer to collaborator via email
```

### Step 3: Collaborator Creates Droplet

When collaborator creates droplet from snapshot:
1. **First boot triggers automatic sanitization**
2. **All user data is removed**
3. **System is marked as sanitized**
4. **Warning files are created**

## Security Workflow

### What Happens on First Boot

1. **System boots normally**
2. **Systemd starts first-boot-sanitize service**
3. **Service waits for system to be ready**
4. **Sanitization script runs automatically**
5. **All user data is removed**
6. **System is marked as sanitized**
7. **Warning files are created**

### What the Collaborator Sees

After first boot, the collaborator will find:

```
/opt/rec_io/SANITIZATION_WARNING.txt
```

This file contains:
- Clear explanation of what happened
- Instructions for next steps
- Security warnings
- Setup requirements

### What Happens if They Try to Start the System

If they try to run `./scripts/MASTER_RESTART.sh` before sanitization:

```
❌ SECURITY WARNING: System has not been sanitized!
❌ This droplet was created from a production snapshot
❌ and contains original user data and credentials.

⚠️  To sanitize the system, run:
⚠️    ./scripts/first_boot_sanitize.sh

⚠️  Or if you want to proceed anyway (NOT RECOMMENDED):
⚠️    touch /opt/rec_io/.sanitization_complete

❌ ABORTING: System startup blocked for security reasons
```

## Security Features

### Automatic Protection
- **No manual intervention required** - sanitization happens automatically
- **No way to accidentally skip** - systemd service runs on every first boot
- **Comprehensive cleanup** - removes data from all locations

### Clear Communication
- **Prominent warnings** about security risks
- **Step-by-step instructions** for proper setup
- **Clear error messages** when security checks fail

### Flexible Override
- **Production systems bypass checks** (using `.production_system` flag)
- **Manual override available** (though not recommended)
- **User confirmation** for edge cases

### Audit Trail
- **Logging** of all sanitization activities
- **Timestamps** of when sanitization occurred
- **Documentation** of what was removed

## Testing the Security System

### Test Installation
```bash
# Install the security system
./scripts/install_first_boot_sanitization.sh

# Test that it's installed correctly
./scripts/install_first_boot_sanitization.sh test
```

### Test Sanitization (Simulation)
```bash
# Manually run sanitization (for testing)
./scripts/first_boot_sanitize.sh
```

### Test MASTER_RESTART Protection
```bash
# Try to start system without sanitization
./scripts/MASTER_RESTART_WITH_SANITIZATION_CHECK.sh

# Should block startup with security warning
```

## Troubleshooting

### Service Not Running
```bash
# Check service status
systemctl status first-boot-sanitize.service

# Check if enabled
systemctl is-enabled first-boot-sanitize.service

# Reinstall if needed
./scripts/install_first_boot_sanitization.sh
```

### Sanitization Failed
```bash
# Check logs
tail -f /var/log/first_boot_sanitize.log

# Manual sanitization
./scripts/first_boot_sanitize.sh
```

### System Won't Start
```bash
# Check sanitization status
ls -la /opt/rec_io/.sanitization_complete

# If missing, run sanitization
./scripts/first_boot_sanitize.sh

# Or force override (NOT RECOMMENDED)
touch /opt/rec_io/.sanitization_complete
```

## Best Practices

### For You (REC.IO Team)
1. **Always install security guardrails** before creating snapshots
2. **Test the security system** before sharing snapshots
3. **Document the security features** for collaborators
4. **Monitor for security issues** in deployment

### For Collaborators
1. **Wait for first boot** to complete (automatic sanitization)
2. **Read warning files** before proceeding
3. **Follow setup instructions** carefully
4. **Contact support** if security warnings appear

### Security Monitoring
1. **Check sanitization logs** after deployment
2. **Verify warning files** are present
3. **Confirm system startup** works properly
4. **Document any issues** for future improvements

## Security Benefits

### Automatic Protection
✅ **No manual intervention required** - sanitization happens automatically
✅ **Comprehensive data removal** - covers all user data locations
✅ **Clear audit trail** - logs all sanitization activities

### User Experience
✅ **Clear communication** - users understand what happened
✅ **Step-by-step guidance** - instructions for proper setup
✅ **Flexible override** - handles edge cases gracefully

### System Integrity
✅ **Production systems unaffected** - bypass checks for your system
✅ **Consistent behavior** - same security for all deployments
✅ **Reliable operation** - robust error handling and recovery

## Conclusion

These security guardrails provide comprehensive protection against accidentally running systems with original user data and credentials. The multi-layered approach ensures that:

1. **Automatic sanitization** happens on first boot
2. **System startup is blocked** until sanitization occurs
3. **Clear warnings and instructions** guide users
4. **Audit trails** document all security activities

This creates a secure, user-friendly deployment process that protects your data while making it easy for collaborators to set up their own systems.
