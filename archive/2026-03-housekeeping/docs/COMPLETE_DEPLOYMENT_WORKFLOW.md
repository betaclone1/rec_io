# Complete REC.IO Deployment Workflow

## Overview

This document provides the complete workflow for deploying REC.IO systems to collaborators using the snapshot transfer method. This approach ensures secure, reliable, and user-friendly deployment.

## Workflow Summary

### Phase 1: Preparation (REC.IO Team)
1. **Install security guardrails** on production system
2. **Create snapshot** when collaborator requests system
3. **Transfer snapshot** to collaborator's Digital Ocean account
4. **Provide deployment guide** to collaborator

### Phase 2: Collaborator Setup
1. **Create droplet** from transferred snapshot
2. **Wait for automatic sanitization** (2-3 minutes)
3. **SSH into droplet** and see welcome message
4. **Run setup script** with interactive prompts
5. **Access trading system** via web interface

## Detailed Workflow

### Step 1: REC.IO Team Preparation

#### 1.1 Install Security System (One-time setup)
```bash
# On your production droplet
cd /opt/rec_io
./scripts/install_first_boot_sanitization.sh
```

This installs:
- ✅ First-boot sanitization service
- ✅ Welcome message system
- ✅ Production system flag
- ✅ Security documentation

#### 1.2 Create Snapshot for Collaborator
1. **Go to Digital Ocean Control Panel**
2. **Navigate to "Backups & Snapshots"**
3. **Click "Take a Snapshot"**
4. **Select your production droplet**
5. **Name it**: `rec_io_production_snapshot_YYYYMMDD_HHMMSS`
6. **Wait for snapshot to complete**

#### 1.3 Transfer Snapshot to Collaborator
1. **Go to "Snapshots" section**
2. **Find your snapshot and click "More" → "Transfer"**
3. **Select "Email address"**
4. **Enter collaborator's Digital Ocean email**
5. **Click "Request Transfer"**
6. **Collaborator receives email and accepts transfer**

#### 1.4 Provide Deployment Guide
Send the collaborator:
- **`docs/COLLABORATOR_DEPLOYMENT_GUIDE.md`** (this document)
- **Snapshot name** for reference
- **Support contact information**

### Step 2: Collaborator Prerequisites

#### 2.1 Digital Ocean Account
- ✅ Create account at [digitalocean.com](https://digitalocean.com)
- ✅ Add payment method
- ✅ Get API token from [API Tokens](https://cloud.digitalocean.com/account/api/tokens)

#### 2.2 SSH Keys
```bash
# Generate SSH keys (if needed)
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

# Add to Digital Ocean:
# 1. Go to SSH Keys section
# 2. Click "Add SSH Key"
# 3. Paste public key content
```

#### 2.3 Kalshi Account
- ✅ Create account at [kalshi.com](https://kalshi.com)
- ✅ Get API credentials from [API Settings](https://trading.kalshi.com/settings/api)
- ✅ Note: Email, API Key, API Secret

### Step 3: Collaborator Creates Droplet

#### 3.1 Digital Ocean Droplet Creation
1. **Log into Digital Ocean**
2. **Click "Create" → "Droplets"**
3. **Configure droplet**:

   **Datacenter**: Choose closest to you
   
   **Image**: Click "Snapshots" tab → Select transferred snapshot
   
   **Size**: 
   - `s-1vcpu-1gb` ($6/month) - Testing
   - `s-2vcpu-2gb` ($12/month) - Production
   
   **SSH Keys**: Select your SSH key
   
   **Finalize**:
   - ✅ Enable "Add improved metrics monitoring and alerting (free)"
   - ✅ Set hostname: `rec-io-user-XXXX`
   - ✅ Click "Create Droplet"

#### 3.2 Automatic Setup Process
The droplet automatically:
1. **Boots up** (Digital Ocean default)
2. **Runs first-boot sanitization** (removes all original data)
3. **Sets up welcome message system**
4. **Marks system as ready** for collaborator setup

**Timeline**: 2-3 minutes for complete automatic setup

### Step 4: Collaborator Completes Setup

#### 4.1 SSH into Droplet
```bash
ssh root@YOUR_DROPLET_IP
```

#### 4.2 Welcome Message Appears
The collaborator sees:
```
=============================================================================
                           REC.IO TRADING SYSTEM
=============================================================================

✅ System has been automatically sanitized and is ready for setup

📋 NEXT STEPS:
1. Navigate to the project directory:
   cd /opt/rec_io

2. Run the setup script:
   ./scripts/collaborator_setup.sh

3. Follow the interactive prompts to configure your system

📖 For detailed instructions, see:
   cat /opt/rec_io/SANITIZATION_WARNING.txt

=============================================================================
```

#### 4.3 Run Setup Script
```bash
cd /opt/rec_io
./scripts/collaborator_setup.sh
```

**Interactive prompts**:
- User ID (e.g., `user_0002`)
- Full name
- Email address
- Phone number
- Password
- Kalshi credentials (optional)

#### 4.4 System Startup
```bash
./scripts/MASTER_RESTART.sh
```

### Step 5: Access Trading System

#### 5.1 Web Interface
- **URL**: `http://YOUR_DROPLET_IP:3000`
- **Health Check**: `http://YOUR_DROPLET_IP:3000/health`

#### 5.2 System Management
```bash
# Check service status
supervisorctl status

# View logs
tail -f logs/*.out.log

# Restart system
./scripts/MASTER_RESTART.sh
```

### Step 6: Future Updates

#### 6.1 Git Update System
The system is automatically configured with a Git repository for easy updates:

```bash
# Check for available updates
./scripts/git_update_system.sh check

# Apply updates (creates backup, updates code, restarts services)
./scripts/git_update_system.sh update

# Create manual backup
./scripts/git_update_system.sh backup

# Restore from backup if needed
./scripts/git_update_system.sh restore /path/to/backup
```

#### 6.2 Update Process
The Git update system automatically:
- ✅ **Creates backup** of current system
- ✅ **Pulls latest updates** from repository
- ✅ **Updates dependencies** and configurations
- ✅ **Restarts services** with new code
- ✅ **Verifies update** was successful
- ✅ **Preserves user data** throughout the process

## Security Features

### Automatic Protection
- ✅ **First-boot sanitization** removes all original user data
- ✅ **Credential isolation** - no access to original credentials
- ✅ **System isolation** - complete user separation
- ✅ **Audit trail** - logs all sanitization activities

### User Experience
- ✅ **Clear guidance** - welcome messages and instructions
- ✅ **Interactive setup** - step-by-step configuration
- ✅ **Error handling** - helpful error messages and recovery
- ✅ **Professional workflow** - polished deployment experience

## What Happens Behind the Scenes

### Automatic Processes (No User Action Required)
1. **System boots** and starts systemd services
2. **First-boot sanitization** runs automatically:
   - Stops all services
   - Clears all user data from database
   - Removes all credential files
   - Resets database sequences
   - Clears all logs
3. **Welcome message system** is configured
4. **System is marked** as sanitized and ready

### Manual Processes (User Must Complete)
1. **SSH into droplet** and see welcome message
2. **Run setup script** with interactive prompts
3. **Provide user information** and credentials
4. **Start trading system** with MASTER_RESTART

## Troubleshooting

### Common Issues

#### Droplet Won't Start
- Check Digital Ocean status
- Verify account has sufficient credits
- Contact Digital Ocean support

#### Can't SSH to Droplet
- Verify SSH key is added to Digital Ocean
- Check firewall settings
- Try connecting from different network

#### Setup Script Fails
- Check logs: `tail -f /var/log/first_boot_sanitize.log`
- Verify snapshot access
- Contact REC.IO team with error details

#### System Won't Start After Setup
- Check service status: `supervisorctl status`
- View logs: `tail -f logs/*.out.log`
- Restart services: `./scripts/MASTER_RESTART.sh`

### Support Process
1. **Collaborator checks** this guide for common issues
2. **Collaborator reviews** system logs for error details
3. **Collaborator contacts** REC.IO team with:
   - Droplet IP address
   - Error messages from logs
   - Steps already tried
   - Screenshots if applicable

## Cost Structure

### REC.IO Team Costs
- **Snapshot storage**: ~$0.05/GB/month (minimal)
- **No additional droplets** - collaborators pay for their own
- **No bandwidth costs** - collaborators pay their own

### Collaborator Costs
- **Droplet**: $6-12/month depending on size
- **Snapshot access**: Free (shared by REC.IO team)
- **Bandwidth**: Standard Digital Ocean rates

## Success Metrics

### Deployment Success Rate
- **Target**: 95%+ successful deployments
- **Measurement**: Collaborators successfully completing setup

### Time to Deployment
- **Target**: <30 minutes from droplet creation to system ready
- **Measurement**: Time from "Create Droplet" to web interface accessible

### Support Requests
- **Target**: <10% of deployments require support
- **Measurement**: Number of support requests per deployment

## Best Practices

### For REC.IO Team
1. **Always install security guardrails** before creating snapshots
2. **Test the deployment process** before sharing with collaborators
3. **Keep snapshots updated** with latest system improvements
4. **Monitor deployment success** and gather feedback

### For Collaborators
1. **Follow the guide step-by-step** - don't skip steps
2. **Keep credentials secure** - don't share API keys
3. **Monitor system performance** - check Digital Ocean metrics
4. **Contact support early** if issues arise

## Conclusion

This workflow provides a secure, reliable, and user-friendly way to deploy REC.IO systems to collaborators. The combination of automatic sanitization, clear guidance, and interactive setup ensures that:

- ✅ **Security is guaranteed** - no original data exposure
- ✅ **Deployment is reliable** - consistent success rate
- ✅ **User experience is excellent** - clear guidance and feedback
- ✅ **Support burden is minimal** - self-service deployment

The workflow scales easily and provides a professional deployment experience that protects both the REC.IO team and collaborators while ensuring successful system deployment.
