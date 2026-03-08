# MASTER RESTART SYSTEM - COMPLETE GUIDE

## Overview

The MASTER RESTART system provides a comprehensive solution for managing the trading system backend. It ensures clean restarts with port flushing and eliminates stale process conflicts.

## Quick Start

```bash
# Show current system status
./scripts/restart status

# Perform a complete restart (recommended)
./scripts/restart

# Quick restart (supervisor only)
./scripts/restart quick

# Emergency restart (force kill everything)
./scripts/restart emergency
```

## Available Commands

### 1. Master Restart (Default)
```bash
./scripts/restart
# or
./scripts/restart master
# or
./scripts/restart full
```

**What it does:**
- Flushes all ports (3000, 4000, 6000, 8001, 8002, 8003, 8004, 8005)
- Stops supervisor cleanly
- Starts supervisor fresh
- Restarts all services
- Verifies everything is running

**When to use:**
- Primary restart method
- After code changes
- When experiencing port conflicts
- Regular system maintenance

### 2. Quick Restart
```bash
./scripts/restart quick
```

**What it does:**
- Stops and starts supervisor
- Restarts all services
- No port flushing

**When to use:**
- Minor configuration changes
- When you know ports are clean
- Faster than full restart

### 3. Emergency Restart
```bash
./scripts/restart emergency
# or
./scripts/restart force
```

**What it does:**
- Force kills all Python processes
- Kills supervisor
- Cleans up socket files
- Flushes all ports
- Starts everything fresh

**When to use:**
- System is completely stuck
- Processes won't stop normally
- Port conflicts that won't resolve
- Last resort option

### 4. Status Check
```bash
./scripts/restart status
```

**What it does:**
- Shows supervisor status for all services
- Shows port usage for all assigned ports
- Identifies any issues

**When to use:**
- Before making changes
- After restart to verify
- Troubleshooting system issues

### 5. Port Flush Only
```bash
./scripts/restart flush
```

**What it does:**
- Only flushes all ports
- Doesn't restart services

**When to use:**
- Just need to free up ports
- Manual port management
- Troubleshooting port conflicts

## System Architecture

### Port Assignments
- **3000**: Main web application
- **4000**: Trade manager service
- **6000**: Active trade supervisor
- **8001**: Trade executor service
- **8002**: BTC price watchdog (background)
- **8003**: Database poller (background)
- **8004**: Kalshi account sync (background)
- **8005**: Kalshi API watchdog (background)

### Service Types
- **HTTP Servers**: main_app, trade_manager, trade_executor, active_trade_supervisor
- **Background Processes**: btc_price_watchdog, db_poller, kalshi_account_sync, kalshi_api_watchdog

## Troubleshooting

### Common Issues

#### 1. "Port already in use" errors
```bash
./scripts/restart emergency
```

#### 2. Supervisor won't start
```bash
# Check if supervisor is already running
ps aux | grep supervisord

# Kill any existing supervisor processes
pkill -f supervisord

# Then restart
./scripts/restart
```

#### 3. Services stuck in FATAL state
```bash
# Check logs
tail -f /tmp/*.out.log

# Emergency restart
./scripts/restart emergency
```

#### 4. Socket file issues
```bash
# Remove socket files
rm -f /tmp/supervisord.sock /tmp/supervisord.pid

# Restart
./scripts/restart
```

### Log Files
- **Supervisor logs**: `/tmp/supervisord.log`
- **Service logs**: `/tmp/[service_name].out.log`
- **Error logs**: `/tmp/[service_name].err.log`

### Verification Commands
```bash
# Check all services are running
supervisorctl -c backend/supervisord.conf status

# Check port usage
lsof -i :3000,4000,6000,8001,8002,8003,8004,8005

# Check specific service
supervisorctl -c backend/supervisord.conf status main_app
```

## Best Practices

### 1. Always check status before restarting
```bash
./scripts/restart status
```

### 2. Use the appropriate restart type
- **Normal changes**: `./scripts/restart` (master restart)
- **Quick fixes**: `./scripts/restart quick`
- **Emergency situations**: `./scripts/restart emergency`

### 3. Verify after restart
```bash
./scripts/restart status
```

### 4. Check logs if issues persist
```bash
tail -f /tmp/main_app.out.log
tail -f /tmp/trade_manager.out.log
```

## Integration with Development Workflow

### After Code Changes
```bash
# 1. Make your code changes
# 2. Check current status
./scripts/restart status

# 3. Restart system
./scripts/restart

# 4. Verify everything is working
./scripts/restart status
```

### Before Trading Sessions
```bash
# Ensure clean system state
./scripts/restart status

# If needed, perform clean restart
./scripts/restart
```

### System Maintenance
```bash
# Weekly maintenance
./scripts/restart emergency
```

## Safety Features

### Error Handling
- Script exits on any error (`set -e`)
- Graceful fallbacks for missing processes
- Comprehensive error messages

### Port Safety
- Only flushes assigned ports (3000-8005)
- Avoids system ports (5000, 7000, 9000, 10000)
- Verifies ports are freed before proceeding

### Process Safety
- Graceful shutdown attempts first
- Force kill only when necessary
- Cleanup of socket and PID files

## Configuration

### Customization
Edit `scripts/MASTER_RESTART.sh` to modify:
- Project root path
- Port assignments
- Timeout values
- Log file locations

### Environment Variables
The script uses the following paths:
- `PROJECT_ROOT`: `/Users/ericwais1/rec_io_20`
- `SUPERVISOR_CONFIG`: `backend/supervisord.conf`
- `SUPERVISOR_SOCKET`: `/tmp/supervisord.sock`
- `SUPERVISOR_PID`: `/tmp/supervisord.pid`

## Support

### Getting Help
```bash
./scripts/restart help
```

### Debug Mode
Add `set -x` to the script for verbose output:
```bash
# Edit scripts/MASTER_RESTART.sh
# Add 'set -x' after 'set -e'
```

### Manual Recovery
If the script fails:
1. Check logs: `tail -f /tmp/supervisord.log`
2. Kill processes manually: `pkill -f python`
3. Clean up: `rm -f /tmp/supervisord.sock /tmp/supervisord.pid`
4. Restart manually: `supervisord -c backend/supervisord.conf` 