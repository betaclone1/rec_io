# Partner SSH Connection Guide for Cursor

## Overview

This guide will help you connect to your new REC.IO trading system droplet via SSH using Cursor's built-in SSH functionality. This is much more reliable than using SSHFS and provides better performance for development work.

## Prerequisites

Before starting, you'll need:
- **Your droplet IP address** (provided by the REC.IO team after droplet creation)
- **Cursor installed** on your local machine
- **SSH key access** to your droplet (your SSH key should already be configured on the droplet)

## Step-by-Step Connection Process

### Step 1: Open Cursor Command Palette

1. **Open Cursor** on your local machine
2. **Press the command palette shortcut**:
   - **macOS**: `Cmd+Shift+P`
   - **Windows/Linux**: `Ctrl+Shift+P`

### Step 2: Connect to Remote Server

1. **Type**: `Remote-SSH: Connect to Host...`
2. **Select it** from the dropdown menu
3. **Choose**: `+ Add New SSH Host...`

### Step 3: Add Your Droplet

1. **Enter your SSH command**:
   ```
   ssh root@YOUR_DROPLET_IP
   ```
   Replace `YOUR_DROPLET_IP` with the actual IP address provided by the REC.IO team.

2. **Select config file**: Choose `~/.ssh/config` (this is the default and recommended option)

3. **Press Enter** to confirm

### Step 4: Configure SSH Settings (Optional but Recommended)

Cursor will automatically add the connection to your SSH config file. You can enhance it by editing `~/.ssh/config` to add:

```
Host rec-io-partner
    HostName YOUR_DROPLET_IP
    User root
    Port 22
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Replace `YOUR_DROPLET_IP` with your actual droplet IP address.

**Benefits of this configuration**:
- **Host alias**: `rec-io-partner` (easier to remember than IP address)
- **Keep-alive settings**: Prevents connection timeouts during long sessions
- **Standardized settings**: Consistent connection parameters

### Step 5: Connect to Your Droplet

1. **Open Command Palette again**: `Cmd+Shift+P` (macOS) or `Ctrl+Shift+P` (Windows/Linux)
2. **Type**: `Remote-SSH: Connect to Host...`
3. **Select your host**:
   - If you added the alias: Select `rec-io-partner`
   - Otherwise: Select `root@YOUR_DROPLET_IP`
4. **Enter SSH key passphrase** if prompted

### Step 6: Open the Project Folder

1. **Wait for connection** to establish (this may take 10-30 seconds)
2. **Select folder to open** when prompted
3. **Navigate to**: `/opt/rec_io_server`
4. **Click "OK"** to open the project

## What You Should See

After successful connection:
- **Cursor will show** "SSH: rec-io-partner" in the bottom-left corner
- **File explorer** will show the remote project files
- **Terminal** will be connected to the remote server
- **All Cursor features** will work as if the files were local

## Troubleshooting Common Issues

### Connection Refused
- **Wait 2-3 minutes** after droplet creation before connecting
- **Verify droplet is active** in Digital Ocean dashboard
- **Check your SSH key** is properly configured on the droplet

### SSH Key Issues
- **Enter passphrase** when prompted for your SSH key
- **Verify SSH key** is added to your Digital Ocean account
- **Check key permissions**: `chmod 600 ~/.ssh/id_rsa` (if using RSA key)

### Can't Find the Project Folder
- **Navigate to**: `/opt/rec_io_server`
- **Verify folder exists**: `ls -la /opt/rec_io_server`
- **Check permissions**: Ensure you have read access to the folder

### Connection Timeout
- **Check your internet connection**
- **Try connecting from a different network**
- **Verify firewall settings** aren't blocking SSH (port 22)

## Benefits of Cursor SSH vs SSHFS

### ✅ Cursor Built-in SSH:
- **Direct file editing** (no sync delays)
- **Better performance** and responsiveness
- **Integrated terminal** with full functionality
- **Proper file watching** for changes
- **No mount/unmount issues**
- **Better error handling** and debugging

### ❌ SSHFS Issues:
- **Network latency** affects editing experience
- **File sync problems** can cause data loss
- **Cursor indexing issues** with remote files
- **Mount/unmount complexity** and reliability issues

## Next Steps After Connection

Once connected:

1. **Verify system status**:
   ```bash
   supervisorctl status
   ```

2. **Check system health**:
   ```bash
   curl http://localhost:3000/health
   ```

3. **Access web interface**:
   - Open browser to: `http://YOUR_DROPLET_IP:3000`

4. **Explore the project structure**:
   - **Backend code**: `/opt/rec_io_server/backend/`
   - **Frontend code**: `/opt/rec_io_server/frontend/`
   - **Scripts**: `/opt/rec_io_server/scripts/`
   - **Configuration**: `/opt/rec_io_server/config/`

## Important Security Notes

- **Your SSH connection is encrypted** and secure
- **All file operations** happen over the secure SSH tunnel
- **No files are stored locally** - everything is on the remote server
- **Your credentials** are safely stored on the remote droplet
- **Disconnect properly** when done: `Remote-SSH: Close Remote Connection`

## Getting Help

If you encounter issues:

1. **Check the connection status** in Cursor's bottom-left corner
2. **Review the output panel** for error messages
3. **Verify your droplet is running** in Digital Ocean dashboard
4. **Contact the REC.IO team** with:
   - Your droplet IP address
   - Any error messages
   - Steps you've already tried

## Example Session

Here's what a successful connection looks like:

```
1. Cmd+Shift+P → "Remote-SSH: Connect to Host..."
2. Select "+ Add New SSH Host..."
3. Enter: "ssh root@192.168.1.100"
4. Select: ~/.ssh/config
5. Cmd+Shift+P → "Remote-SSH: Connect to Host..."
6. Select: "rec-io-partner" (or "root@192.168.1.100")
7. Enter SSH key passphrase
8. Select folder: "/opt/rec_io_server"
9. ✅ Connected! SSH: rec-io-partner shown in bottom-left
```

---

**Need help?** Contact the REC.IO team with your droplet IP and any specific error messages you encounter.
