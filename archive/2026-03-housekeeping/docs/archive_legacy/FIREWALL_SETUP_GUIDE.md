# Trading System Firewall Setup Guide

## Overview

This guide covers the implementation of a secure, non-intrusive firewall system for the trading platform that works both locally and on DigitalOcean without disrupting local development or system operations.

## 🔒 Firewall System Features

### Security Features
- **Non-intrusive**: Preserves all localhost and internal communication
- **Mode-aware**: Different rules for local vs production deployment
- **Safe defaults**: Deny incoming, allow outgoing
- **API access**: Allows outbound traffic for trading APIs (Kalshi, Coinbase, TradingView)
- **Service ports**: Allows internal service communication
- **SSH protection**: Restricts SSH to whitelisted IPs in production

### Compatibility
- ✅ **Local Development**: Full compatibility with existing workflows
- ✅ **Internal Services**: Preserves all supervisor-managed processes
- ✅ **API Communication**: Maintains outbound API access for trading
- ✅ **Web Interface**: Allows HTTP/HTTPS access
- ✅ **SSH Access**: Configurable SSH restrictions

## 📁 Files Created

### Core Scripts
- `scripts/setup_firewall.sh` - Bash implementation
- `scripts/firewall_setup.py` - Python implementation
- `config/firewall_whitelist.json` - IP whitelist configuration

### Configuration
- `config/firewall_whitelist.json` - Default IP allowlist
- `logs/firewall_setup.log` - Setup logs

## 🚀 Usage

### Local Development Mode
```bash
# Bash version
sudo ./scripts/setup_firewall.sh --mode local

# Python version
sudo python scripts/firewall_setup.py --mode local
```

### Production Mode
```bash
# Bash version
sudo ./scripts/setup_firewall.sh --mode production

# Python version
sudo python scripts/firewall_setup.py --mode production
```

### Dry Run (Preview Rules)
```bash
# Preview production rules without applying
sudo ./scripts/setup_firewall.sh --mode production --dry-run

# Python version
sudo python scripts/firewall_setup.py --mode production --dry-run
```

## 🔧 Configuration

### IP Whitelist Configuration
Edit `config/firewall_whitelist.json` to customize allowed IPs:

```json
{
  "ssh_allowed_ips": [
    "10.0.0.0/8",
    "172.16.0.0/12", 
    "192.168.0.0/16",
    "127.0.0.1",
    "::1"
  ],
  "api_endpoints": {
    "kalshi": ["api.kalshi.com"],
    "coinbase": ["api.coinbase.com", "api.pro.coinbase.com"],
    "tradingview": ["api.tradingview.com"]
  }
}
```

### Trading System Ports
The firewall automatically configures access for all trading system ports:
- 3000 - main_app
- 4000 - trade_manager
- 6000 - active_trade_supervisor
- 8001 - trade_executor
- 8002 - btc_price_watchdog
- 8003 - db_poller
- 8004 - kalshi_account_sync
- 8005 - kalshi_api_watchdog
- 8009 - auto_entry_supervisor
- 8010 - unified_production_coordinator
- 8011 - trade_initiator

## 🛡️ Security Modes

### Local Development Mode
**Purpose**: Development and testing environment
**Features**:
- ✅ Allow all localhost traffic (127.0.0.1, ::1)
- ✅ Allow all internal networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- ✅ Allow all trading system ports
- ✅ Allow unrestricted SSH
- ✅ Allow outbound API access
- ✅ Allow HTTP/HTTPS (80, 443)

**Use Case**: Local development, testing, debugging

### Production Mode
**Purpose**: Secure production deployment
**Features**:
- ✅ Allow localhost traffic only (127.0.0.1, ::1)
- ✅ Restrict trading ports to localhost only
- ✅ Restrict SSH to whitelisted IPs
- ✅ Allow outbound API access (critical for trading)
- ✅ Allow HTTP/HTTPS (80, 443)
- ✅ Enable SSH rate limiting
- ✅ Deny all other incoming traffic

**Use Case**: DigitalOcean deployment, production servers

## 🔍 Verification

### Check Firewall Status
```bash
# Check ufw status
sudo ufw status numbered

# Check specific rules
sudo ufw status verbose
```

### Test Local Access
```bash
# Test localhost access
curl http://localhost:3000

# Test internal service communication
curl http://localhost:4000
```

### Test API Access
```bash
# Test outbound API access
curl https://api.kalshi.com
curl https://api.coinbase.com
```

## 🚨 Troubleshooting

### Common Issues

**Issue**: "ufw command not found"
```bash
# Install ufw (Ubuntu/Debian)
sudo apt-get update && sudo apt-get install ufw

# Install ufw (CentOS/RHEL)
sudo yum install ufw
```

**Issue**: "Permission denied"
```bash
# Run with sudo
sudo ./scripts/setup_firewall.sh --mode local
```

**Issue**: "Cannot connect to services"
```bash
# Check if firewall is blocking
sudo ufw status

# Temporarily disable for testing
sudo ufw disable

# Re-enable with correct rules
sudo ./scripts/setup_firewall.sh --mode local
```

**Issue**: "API calls failing"
```bash
# Check outbound rules
sudo ufw status | grep "out"

# Verify API endpoints are allowed
sudo ufw status | grep "80\|443"
```

### Emergency Recovery
```bash
# Disable firewall completely
sudo ufw disable

# Reset to default state
sudo ufw --force reset

# Re-enable with safe defaults
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

## 🔄 Integration with Deployment

### DigitalOcean Deployment
Add to your deployment script:
```bash
#!/bin/bash
# Install and configure firewall
sudo apt-get update
sudo apt-get install -y ufw

# Configure firewall for production
sudo ./scripts/setup_firewall.sh --mode production

# Verify configuration
sudo ufw status
```

### Local Development
```bash
# Quick local setup
sudo ./scripts/setup_firewall.sh --mode local

# Verify no interference
curl http://localhost:3000
```

## 📊 Monitoring

### Firewall Logs
```bash
# View firewall logs
sudo tail -f /var/log/ufw.log

# View setup logs
tail -f logs/firewall_setup.log
```

### Status Monitoring
```bash
# Check active rules
sudo ufw status numbered

# Check rule counts
sudo ufw status | wc -l
```

## 🔐 Security Best Practices

### Production Deployment
1. **Whitelist SSH IPs**: Edit `config/firewall_whitelist.json`
2. **Test in dry-run mode**: `--dry-run` flag
3. **Monitor logs**: Check `/var/log/ufw.log`
4. **Regular audits**: Review rules monthly
5. **Backup configuration**: Save whitelist config

### Local Development
1. **Use local mode**: `--mode local`
2. **Test thoroughly**: Verify all services work
3. **Monitor for interference**: Check system logs
4. **Easy recovery**: Can disable with `sudo ufw disable`

## ✅ Safety Features

### Non-Intrusive Design
- ✅ **Preserves localhost**: All 127.0.0.1 traffic allowed
- ✅ **Internal communication**: Supervisor services unaffected
- ✅ **API access**: Trading APIs remain accessible
- ✅ **Web interface**: HTTP/HTTPS access maintained
- ✅ **Easy recovery**: Can disable firewall if needed

### Fail-Safe Mechanisms
- ✅ **Auto-install ufw**: Script installs if missing
- ✅ **Dry-run mode**: Preview rules before applying
- ✅ **Error handling**: Comprehensive error checking
- ✅ **Logging**: All actions logged for audit
- ✅ **Rollback**: Can reset to default state

## 🎯 Summary

The firewall system provides:
- **Security**: Protects against unauthorized access
- **Compatibility**: Works with existing trading system
- **Flexibility**: Different modes for different environments
- **Safety**: Non-intrusive and easily recoverable
- **Monitoring**: Comprehensive logging and status checking

**Ready for deployment on both local development and DigitalOcean production environments.** 