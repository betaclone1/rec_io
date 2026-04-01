# Digital Ocean Deployment Guide

## Overview

The `deploy_digital_ocean.sh` script provides a complete, automated deployment solution for REC.IO on Digital Ocean servers. It handles everything from backup management to system verification.

**This project’s live production box:** see [PRODUCTION_HOST.md](PRODUCTION_HOST.md) (public IPv4 **165.22.13.146**, app root **/opt/rec_io_server**). Examples below that use `<remote_host>` or older `/opt/rec_io` paths may differ on historical droplets; prefer the canonical doc when targeting prod.

## Prerequisites

1. **SSH Access**: Ensure you have SSH access to your Digital Ocean droplet
2. **Root Access**: The script requires root access on the remote server
3. **Local System**: Must be run from the REC.IO project root directory

## Usage

### Basic Usage
```bash
./scripts/deploy_digital_ocean.sh <remote_host_ip>
```

### Advanced Usage
```bash
./scripts/deploy_digital_ocean.sh <remote_host_ip> <username> <remote_directory>
```

### Examples
```bash
# Deploy to Digital Ocean droplet
./scripts/deploy_digital_ocean.sh YOUR_DROPLET_IP

# Deploy with custom user and directory
./scripts/deploy_digital_ocean.sh YOUR_DROPLET_IP root /opt/trading_system
```

## What the Script Does

### 1. Backup Management
- **Cleans old backups**: Removes previous system and database backup packages
- **Creates system backup**: Archives the entire codebase (excluding venv, logs, etc.)
- **Creates database backup**: Archives user data, trade history, and credentials
- **Creates deployment package**: Prepares clean deployment archive

### 2. Remote Server Setup
- **Creates remote directory**: Sets up the target directory on the remote server
- **Uploads packages**: Transfers deployment and database packages
- **Extracts files**: Unpacks the deployment package on the remote server
- **Sets permissions**: Configures proper file permissions
- **Restores data**: Extracts and restores database backup

### 3. Database Setup
- **Installs PostgreSQL**: Installs and configures PostgreSQL server
- **Creates database**: Sets up `rec_io_db` database
- **Creates user**: Creates `rec_io_user` with proper permissions
- **Configures access**: Sets up remote connection access

### 4. Python Environment
- **Installs dependencies**: Installs Python 3, pip, venv, and supervisor
- **Creates virtual environment**: Sets up isolated Python environment
- **Installs packages**: Installs all requirements from requirements.txt

### 5. System Configuration
- **Generates supervisor config**: Creates portable supervisor configuration
- **Starts services**: Uses MASTER_RESTART to start all services
- **Verifies system**: Checks that all services are running and ports are accessible

## Deployment Process

The script follows this sequence:

```
1. Clean old backups
2. Create system backup
3. Create database backup  
4. Create deployment package
5. Setup remote server
6. Setup PostgreSQL
7. Install Python dependencies
8. Start and verify system
9. Display summary
```

## Verification Steps

The script automatically verifies:

- ✅ **Supervisor status**: All services are running
- ✅ **Main app**: Port 3000 is accessible
- ✅ **Trade manager**: Port 4000 is accessible
- ✅ **Service health**: Critical services are operational

## Post-Deployment Steps

After successful deployment:

1. **Add Kalshi credentials**:
   ```bash
   ssh root@<remote_host> "nano /opt/rec_io/backend/data/users/user_0001/credentials/kalshi-credentials/prod/kalshi-auth.txt"
   ```

2. **Update user info**:
   ```bash
   ssh root@<remote_host> "nano /opt/rec_io/backend/data/users/user_0001/user_info.json"
   ```

3. **Access the system**:
   ```
   http://<remote_host>:3000
   ```

4. **Monitor logs**:
   ```bash
   ssh root@<remote_host> "tail -f /opt/rec_io/logs/*.out.log"
   ```

5. **Restart system** (if needed):
   ```bash
   ssh root@<remote_host> "cd /opt/rec_io && ./scripts/MASTER_RESTART.sh"
   ```

## Troubleshooting

### Common Issues

1. **SSH Connection Failed**
   - Verify the IP address is correct
   - Ensure SSH key is properly configured
   - Check firewall settings

2. **Permission Denied**
   - Ensure you're running as root or have sudo access
   - Check file permissions on the remote server

3. **Port Already in Use**
   - The script automatically flushes ports
   - If issues persist, manually kill processes on the remote server

4. **PostgreSQL Installation Failed**
   - Check internet connectivity on the remote server
   - Verify package repositories are accessible

### Manual Recovery

If the script fails, you can manually complete the deployment:

```bash
# Connect to remote server
ssh root@<remote_host>

# Navigate to deployment directory
cd /opt/rec_io

# Generate supervisor config
./scripts/generate_supervisor_config.sh

# Start system
./scripts/MASTER_RESTART.sh

# Check status
supervisorctl -c backend/supervisord.conf status
```

## Backup Files

The script creates these backup files:

- `backup/system_backup_YYYYMMDD_HHMMSS.tar.gz` - Complete system backup
- `backup/database_backup_YYYYMMDD_HHMMSS.tar.gz` - User data backup
- `backup/full_deployment_YYYYMMDD_HHMMSS.tar.gz` - Deployment package

## Security Notes

- The script creates a PostgreSQL user with a default password
- Consider changing the database password after deployment
- Ensure proper firewall rules are in place
- Use SSH keys instead of password authentication

## Support

If you encounter issues:

1. Check the script output for error messages
2. Verify all prerequisites are met
3. Check the remote server logs
4. Ensure the local system is in a working state before deployment

