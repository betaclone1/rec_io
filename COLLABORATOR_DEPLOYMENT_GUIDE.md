# REC.IO Collaborator Deployment Guide
UPDATED: August 19, 2025

## Overview

This guide walks you through setting up your own REC.IO trading system using a snapshot of our production system. This approach ensures you get a fully functional system without the complexity of fresh installations.

## Prerequisites

### 1. Digital Ocean Account
- **Create a Digital Ocean account** at [digitalocean.com](https://digitalocean.com)
- **Add a payment method** to your account
- **Get your API token** from [Digital Ocean API Tokens](https://cloud.digitalocean.com/account/api/tokens)

### 2. SSH Keys
- **Generate SSH keys** (if you don't have them):
  ```bash
  ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
  ```
- **Add SSH key to Digital Ocean**:
  - Go to [Digital Ocean SSH Keys](https://cloud.digitalocean.com/account/security)
  - Click "Add SSH Key"
  - Paste your public key content

### 3. Kalshi Trading Account
- **Create a Kalshi account** at [kalshi.com](https://kalshi.com)
- **Get your API credentials**:
  - Go to [Account & Security](https://kalshi.com/account/profile)
  - Create a new API key (API Keys at bottom of page)
  - Note your **Email**, **API Key**, and **API Secret**. Keep this information on hand. The API Secret Key will only be displayed once and is neccessary for creating the credential files in the trading system.

## Deployment Process

### Step 1: Request Snapshot from REC.IO Team

Contact the REC.IO team and provide:
- **Your Digital Ocean email address** (for snapshot transfer)

The team will:
1. Create a snapshot of the production system
2. Transfer it to your Digital Ocean account
3. Provide you with the snapshot name

### Step 2: Create Your Droplet

1. **Log into Digital Ocean** and navigate to **"Backups & Snapshots"**
2. **Find your transferred snapshot** in the list
   - It will be named something like: `rec_io_production_snapshot_YYYYMMDD_HHMMSS`
3. **Click on the snapshot** to view its details
4. **Click "Create Droplet from Snapshot"**
5. **Configure your droplet**:

   **Choose a datacenter:**
   - Select the datacenter closest to you
   - Recommended: Choose the same region as the snapshot

   **Choose size:**
   - **Minimum Required**: 4 GB / 2 AMD CPUs ($28/month) - **Bare minimum to run the system**

   **Choose SSH keys:**
   - Select your SSH key from the list

   **Finalize and create:**
   - **Enable monitoring**: Check "Add improved metrics monitoring and alerting (free)"
   - **Hostname**: Give it a memorable name like `rec-io-user-0002`
   - **Click "Create Droplet"**

**Note:** Creating the droplet directly from the snapshot ensures all specifications are set correctly automatically.

### Step 3: Wait for Initial Setup

The droplet will automatically start and begin the setup process:

1. **First boot initialization** (automatic)
2. **System configuration** (automatic)
3. **Security setup** (automatic)

**This process takes 2-3 minutes.** You'll see the droplet status change from "Creating" to "Active".

### Step 4: Access Your System

Once the droplet is active:

1. **Note your droplet's IP address** (shown in the Digital Ocean dashboard)
2. **SSH into your droplet** via a terminal window:
   ```bash
   ssh root@YOUR_DROPLET_IP
   ```
3. You may get a Connection Refused message initially. Give the system a minute and try again. This is normal.
4. Enter "yes" to "Are you sure you want to continue connecting (yes/no/[fingerprint])?"

### Step 5: Complete Your Setup

After SSH'ing into your droplet, you'll see a welcome message and instructions. Follow these steps:

1. **Navigate to the project directory**:
   
   cd /opt/rec_io_server
   ./scripts/collaborator_setup.sh

2. **Run the collaborator setup script**:
   
   ./scripts/collaborator_setup.sh
   

3. **Follow the interactive prompts**:
   - Enter your user information (ID, name, email, phone)
   - Provide your Kalshi credentials:
     - **Email**: Your Kalshi account email
     - **API Key**: Your Kalshi API key
     - **API Secret**: Paste your entire private key (including BEGIN/END lines) and press **Ctrl+D** when done
   - The system will automatically:
     - Sanitize all data (clear database, disable maintenance)
     - Update user information in database
     - Write credential files
     - Start all services (MASTER_RESTART)

4. **System will auto-start on future reboots** (automatic)

### Step 6: Access Your Trading System

Once setup is complete:

- **Web Interface**: `http://YOUR_DROPLET_IP:3000`
- **Health Check**: `http://YOUR_DROPLET_IP:3000/health`

## What Happens During Setup

### Automatic Processes (No Action Required)
- ✅ **Data sanitization** - All original user data is removed
- ✅ **System configuration** - Database and services are prepared
- ✅ **Security setup** - Proper permissions and isolation

### Manual Processes (You Need to Complete)
- ✅ **User information** - Your personal details and preferences
- ✅ **Kalshi credentials** - Your trading API credentials
- ✅ **System startup** - Automatically handled by the setup script

## Troubleshooting

### Droplet Won't Start
- **Check Digital Ocean status** at [status.digitalocean.com](https://status.digitalocean.com)
- **Verify your account** has sufficient credits
- **Contact Digital Ocean support** if issues persist

### Can't SSH to Droplet
- **Verify your SSH key** is added to Digital Ocean
- **Check your firewall** isn't blocking SSH (port 22)
- **Try connecting from a different network**

### Setup Script Fails
- **Check the logs**: `tail -f /var/log/first_boot_sanitize.log`
- **Verify snapshot access**: Contact the REC.IO team
- **Check system resources**: Ensure droplet has sufficient memory

### System Won't Start After Setup
- **Check service status**: `supervisorctl status`
- **View logs**: `tail -f logs/*.out.log`
- **Restart services**: `./scripts/MASTER_RESTART.sh`

## Security Features

### Data Protection
- ✅ **Complete data isolation** - No access to original user data
- ✅ **Secure credential storage** - Your credentials are encrypted and isolated
- ✅ **Automatic sanitization** - Original data is removed on first boot

### System Security
- ✅ **Isolated environment** - Your system is completely separate
- ✅ **Secure permissions** - Proper file and directory permissions
- ✅ **No cross-user access** - Complete user isolation

## Cost Information

### Digital Ocean Costs
- **Droplet**: $28-56/month depending on size
  - **Minimum Required**: 4 GB / 2 AMD CPUs ($28/month) - Bare minimum to run the system
  - **Recommended**: 8 GB / 2 AMD CPUs ($42/month) - Better performance for production
  - **Higher Performance**: 8 GB / 4 AMD CPUs ($56/month) - For heavy trading activity
- **Snapshot**: Free (shared by REC.IO team)
- **Bandwidth**: Standard Digital Ocean rates
- **Monitoring**: Free (included with droplet)

### Optimization Tips
- **Choose appropriate droplet size** for your needs
- **Monitor usage** to avoid unnecessary costs
- **Delete droplet** when not in use (you can recreate from snapshot)

## Support

### Getting Help
1. **Check this guide** for common issues
2. **Review system logs** for error details
3. **Contact the REC.IO team** with specific error messages

### Information to Provide
When contacting support, include:
- **Your droplet IP address**
- **Error messages** from logs
- **Steps you've already tried**
- **Screenshots** of any error screens

## Next Steps

After successful deployment:

1. **Test the web interface** - Verify all features work
2. **Configure your preferences** - Set up trading parameters
3. **Test with small amounts** - Start with demo trading
4. **Monitor system performance** - Check Digital Ocean metrics
5. **Set up alerts** - Configure monitoring notifications

## Important Notes

- **Your droplet is your responsibility** - You manage and maintain it
- **Keep credentials secure** - Don't share your Kalshi API keys
- **Regular backups** - Consider backing up your configuration
- **Stay updated** - The REC.IO team may provide system updates

---

**Need help?** Contact the REC.IO team with your droplet IP and any error messages.
