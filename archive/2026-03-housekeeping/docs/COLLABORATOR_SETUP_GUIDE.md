# REC.IO Collaborator Setup Guide

## Overview

This guide explains how collaborators can set up their own REC.IO trading system using a snapshot of the production system. This approach ensures you get a fully functional system without the complexity of fresh installations.

## How It Works

1. **You receive a snapshot ID** from the REC.IO team
2. **You run the setup script** on your own system/droplet
3. **Script creates a new droplet** in your Digital Ocean account
4. **System is automatically configured** for your use
5. **You get a fully functional REC.IO system** ready for testing

## Prerequisites

### 1. Digital Ocean Account
- You need your own Digital Ocean account
- You need a Digital Ocean API token

### 2. System Requirements
- A Linux system (Ubuntu 20.04+ recommended)
- SSH access to your system
- Internet connectivity

### 3. Required Information
- **Snapshot ID**: Provided by the REC.IO team
- **Kalshi Credentials**: Your Kalshi API credentials (optional)

## Step-by-Step Setup

### Step 1: Install Digital Ocean CLI

```bash
# Install doctl
snap install doctl

# Or download from Digital Ocean
# Visit: https://docs.digitalocean.com/reference/doctl/how-to/install/
```

### Step 2: Authenticate with Digital Ocean

```bash
# Initialize authentication
doctl auth init

# You'll be prompted for your API token
# Get your token from: https://cloud.digitalocean.com/account/api/tokens
```

### Step 3: Download the Setup Script

```bash
# Download the collaborator setup script
wget https://raw.githubusercontent.com/betaclone1/rec_io/main/scripts/collaborator_setup.sh

# Make it executable
chmod +x collaborator_setup.sh
```

### Step 4: Configure the Script

Edit the script to add your snapshot ID:

```bash
# Open the script in a text editor
nano collaborator_setup.sh

# Find this line and replace with your snapshot ID:
SNAPSHOT_ID="your_snapshot_id_here"
```

### Step 5: Run the Setup Script

```bash
# Run the setup script
./collaborator_setup.sh
```

The script will:
1. **Check prerequisites** (doctl, authentication)
2. **Verify snapshot access**
3. **Collect your information** (user ID, name, email, etc.)
4. **Get your Kalshi credentials** (optional)
5. **Let you choose droplet configuration** (region, size)
6. **Create your droplet** from the snapshot
7. **Sanitize all user data**
8. **Configure the system for your use**
9. **Start all services**
10. **Verify everything is working**

## What You'll Be Asked For

### User Information
- **User ID**: Format `user_XXXX` (e.g., `user_0002`)
- **Full Name**: Your complete name
- **Email Address**: Your email address
- **Phone Number**: Your phone number
- **Password**: Your login password

### Kalshi Credentials (Optional)
- **Kalshi Email**: Your Kalshi account email
- **API Key**: Your Kalshi API key
- **API Secret**: Your Kalshi API secret

If you skip Kalshi credentials, the system will run in demo mode until you add them later.

### Droplet Configuration
- **Region**: Choose a Digital Ocean region close to you
- **Size**: Choose droplet size based on your needs

## What the Script Does

### 1. Creates Your Droplet
- Creates a new droplet in your Digital Ocean account
- Uses the production snapshot as the base image
- Configures it with your chosen region and size

### 2. Sanitizes the System
- **Removes all original user data** from the database
- **Deletes all credential files** from the system
- **Clears all logs and user files**
- **Resets database sequences** to start fresh

### 3. Configures for Your Use
- **Creates your user directory structure**
- **Sets up your user information**
- **Configures your Kalshi credentials** (if provided)
- **Creates your database tables**
- **Sets proper file permissions**

### 4. Starts the System
- **Runs MASTER RESTART** to start all services
- **Verifies all services are running**
- **Tests system functionality**

## After Setup

### Access Your System
- **Web Interface**: `http://YOUR_DROPLET_IP:3000`
- **Health Check**: `http://YOUR_DROPLET_IP:3000/health`
- **SSH Access**: `ssh root@YOUR_DROPLET_IP`

### First Steps
1. **Access the web interface** at the provided URL
2. **Log in** with your credentials
3. **Configure your preferences** in the web interface
4. **Test the system** functionality

### If You Skipped Kalshi Credentials
If you didn't provide Kalshi credentials during setup, you can add them later:

```bash
# SSH to your droplet
ssh root@YOUR_DROPLET_IP

# Navigate to the project
cd /opt/rec_io

# Edit the credentials file
nano backend/data/users/YOUR_USER_ID/credentials/kalshi-credentials/prod/kalshi-auth.txt

# Add your credentials in this format:
# email:your_email@example.com
# key:your_api_key_here

# Restart services
./scripts/MASTER_RESTART.sh
```

## Troubleshooting

### Common Issues

#### 1. doctl Not Installed
```bash
# Install doctl
snap install doctl

# Or download manually from Digital Ocean
```

#### 2. Authentication Failed
```bash
# Re-authenticate
doctl auth init

# Verify your API token is correct
doctl account get
```

#### 3. Snapshot Not Found
- Verify the snapshot ID with the REC.IO team
- Ensure the snapshot is accessible in your region

#### 4. Droplet Creation Failed
- Check your Digital Ocean account has sufficient credits
- Verify the region and size are available
- Check your API token has write permissions

#### 5. SSH Connection Failed
- Wait a few minutes for the droplet to fully initialize
- Check your firewall settings
- Verify the droplet is active

### Getting Help

If you encounter issues:

1. **Check the script output** for error messages
2. **Verify your Digital Ocean account** has sufficient resources
3. **Contact the REC.IO team** with the error details
4. **Include the script output** in your support request

## Security Notes

### Your Data
- **All original user data is completely removed**
- **Your system is isolated** from other users
- **Your credentials are stored securely** with proper permissions

### Your Droplet
- **The droplet is in your Digital Ocean account**
- **You have full control** over the droplet
- **You are responsible** for managing and securing it

### Credentials
- **Kalshi credentials are stored locally** on your droplet
- **Files have restricted permissions** (600 for credential files)
- **Credentials are not shared** with the REC.IO team

## Cost Considerations

### Digital Ocean Costs
- **Droplet**: Standard Digital Ocean pricing based on size
- **Snapshot**: No additional cost (snapshot is shared)
- **Bandwidth**: Standard Digital Ocean bandwidth costs

### Optimization Tips
- **Choose appropriate droplet size** for your needs
- **Monitor usage** to avoid unnecessary costs
- **Delete the droplet** when you're done testing

## Example Session

Here's what a typical setup session looks like:

```
=============================================================================
                    REC.IO COLLABORATOR SETUP
=============================================================================
[COLLABORATOR_SETUP] Starting REC.IO collaborator setup process...

[COLLABORATOR_SETUP] ✅ Prerequisites check passed

[COLLABORATOR_SETUP] Getting snapshot information...
[COLLABORATOR_SETUP] ✅ Found snapshot: rec_io_production_snapshot_20250127
[COLLABORATOR_SETUP] Snapshot region: nyc1

[COLLABORATOR_SETUP] Collecting your information...
Enter your user ID (e.g., user_0002): user_0002
Enter your full name: John Doe
Enter your email address: john@example.com
Enter your phone number: +1234567890
Enter your password: 
Confirm your password: 
[COLLABORATOR_SETUP] ✅ User information collected

[COLLABORATOR_SETUP] Collecting Kalshi credentials...
Do you want to set up Kalshi credentials now?
1) Yes - I have my Kalshi credentials ready
2) No - I'll add them later (system will be limited to demo mode)
Enter 1 or 2: 1

Please enter your Kalshi credentials:
Kalshi Email: john@example.com
Kalshi API Key: api_key_here
Kalshi API Secret: api_secret_here
[COLLABORATOR_SETUP] ✅ Kalshi credentials collected

[COLLABORATOR_SETUP] Selecting droplet configuration...
[COLLABORATOR_SETUP] Available regions:
nyc1    New York 1
sfo2    San Francisco 2
lon1    London 1
Enter region (e.g., nyc1, sfo2, lon1): nyc1

[COLLABORATOR_SETUP] Available droplet sizes:
s-1vcpu-1gb    $6.00    1024    1
s-2vcpu-2gb    $12.00   2048    2
Enter droplet size (e.g., s-1vcpu-1gb, s-2vcpu-2gb): s-1vcpu-1gb
[COLLABORATOR_SETUP] ✅ Droplet configuration selected

[COLLABORATOR_SETUP] Creating new droplet from snapshot...
[COLLABORATOR_SETUP] Creating new droplet: rec_io_user_0002_20250127
[COLLABORATOR_SETUP] Region: nyc1, Size: s-1vcpu-1gb, Snapshot: 987654321
[COLLABORATOR_SETUP] ✅ New droplet created with ID: 123456789
[COLLABORATOR_SETUP] Waiting for droplet to become active...
[COLLABORATOR_SETUP] ✅ New droplet is active at IP: 192.168.1.100

New droplet details:
  Name: rec_io_user_0002_20250127
  ID: 123456789
  IP: 192.168.1.100

[COLLABORATOR_SETUP] Sanitizing user data on new droplet...
[COLLABORATOR_SETUP] ✅ User data sanitized

[COLLABORATOR_SETUP] Setting up new user configuration...
[COLLABORATOR_SETUP] ✅ New user configuration set up

[COLLABORATOR_SETUP] Running MASTER RESTART on new droplet...
[COLLABORATOR_SETUP] ✅ MASTER RESTART completed on new droplet

[COLLABORATOR_SETUP] Verifying system functionality...
[COLLABORATOR_SETUP] ✅ Web interface is accessible
[COLLABORATOR_SETUP] ✅ Health endpoint is responding
[COLLABORATOR_SETUP] ✅ System verification completed

=============================================================================
                    REC.IO COLLABORATOR SETUP
=============================================================================
[COLLABORATOR_SETUP] ✅ REC.IO system setup completed successfully!

Your new system details:
  Droplet Name: rec_io_user_0002_20250127
  Droplet ID: 123456789
  IP Address: 192.168.1.100
  User ID: user_0002
  User Name: John Doe
  User Email: john@example.com

Access your system:
  Web Interface: http://192.168.1.100:3000
  Health Check: http://192.168.1.100:3000/health
  SSH Access: ssh root@192.168.1.100

Next steps:
1. Access the web interface at http://192.168.1.100:3000
2. Log in with your credentials
3. Kalshi credentials are already configured
4. Configure your trading preferences in the web interface

Important notes:
- All original user data has been completely removed
- Your system is now configured for user: user_0002
- This droplet is in your Digital Ocean account
- You are responsible for managing this droplet

[COLLABORATOR_SETUP] ✅ Setup completed successfully!
```

## Conclusion

This setup process provides you with a fully functional REC.IO trading system that's:

- **Ready for immediate use**
- **Completely isolated** from other users
- **Under your control** in your Digital Ocean account
- **Properly configured** with your credentials

The system is identical to the production system but sanitized for your use, ensuring you get the same functionality without any of the installation complexity.
