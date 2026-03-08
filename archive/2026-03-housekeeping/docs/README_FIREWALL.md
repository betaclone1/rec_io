# Trading System Firewall Setup - Minimally Intrusive

## Overview

This firewall configuration provides **standard protection** for production deployment while being **minimally intrusive** to system functionality. The design prioritizes preserving all internal communication and outbound API calls while only blocking unwanted incoming connections.

## Core Principles

### ✅ What the Firewall DOES:
- **ALLOWS** all localhost traffic (127.0.0.1, ::1)
- **ALLOWS** all internal network communication (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
- **ALLOWS** all outbound traffic (API calls to Kalshi, Coinbase, etc.)
- **ALLOWS** specified inbound ports for SSH, HTTP/HTTPS, and system APIs
- **BLOCKS** unwanted incoming connections from unknown public IPs

### ❌ What the Firewall DOES NOT:
- **DOES NOT** interfere with local development
- **DOES NOT** block internal service-to-service communication
- **DOES NOT** restrict outbound traffic (API calls to Kalshi, Coinbase, etc.)
- **DOES NOT** use exotic packet rules, ICMP blocking, or stealth modes
- **DOES NOT** apply verbose logging or intrusion detection

## Usage

### Local Development Mode
```bash
# Apply permissive rules for development
sudo ./scripts/setup_firewall.sh --mode local

# Or using Python version
sudo python scripts/firewall_setup.py --mode local
```

### Production Mode
```bash
# Apply standard protection for production
sudo ./scripts/setup_firewall.sh --mode production

# Or using Python version
sudo python scripts/firewall_setup.py --mode production
```

### Dry Run (Preview Rules)
```bash
# Preview rules without applying
sudo ./scripts/setup_firewall.sh --mode production --dry-run
```

## Firewall Rules Applied

### Local Mode (Development)
- **Default Policy**: Deny incoming, Allow outgoing
- **Localhost**: Allow all traffic from 127.0.0.1 and ::1
- **Internal Networks**: Allow all traffic from private IP ranges
- **Trading Ports**: Allow unrestricted access to all system ports
- **Web Ports**: Allow SSH (22), HTTP (80), HTTPS (443)
- **Outbound**: Allow all outbound traffic (preserves API calls)

### Production Mode (Standard Protection)
- **Default Policy**: Deny incoming, Allow outgoing
- **Localhost**: Allow all traffic from 127.0.0.1 and ::1
- **Internal Networks**: Allow all traffic from private IP ranges
- **Trading Ports**: Restrict to localhost access only
- **SSH**: Restrict to whitelisted IPs (from `config/firewall_whitelist.json`)
- **Web Ports**: Allow HTTP (80), HTTPS (443)
- **Outbound**: Allow all outbound traffic (preserves API calls)
- **Rate Limiting**: Enable SSH rate limiting

## Trading System Ports

The firewall manages access to these trading system ports:

| Port | Service | Description |
|------|---------|-------------|
| 3000 | main_app | Main web application |
| 4000 | trade_manager | Trade management service |
| 8001 | trade_executor | Trade execution service |
| 8002 | btc_price_watchdog | Bitcoin price monitoring |
| 8003 | db_poller | Database polling service |
| 8004 | kalshi_account_sync | Kalshi account synchronization |
| 8005 | kalshi_api_watchdog | Kalshi API monitoring |
| 8007 | active_trade_supervisor | Active trade monitoring |
| 8009 | auto_entry_supervisor | Auto entry monitoring |
| 8010 | unified_production_coordinator | Unified data coordinator |
| 8011 | trade_initiator | Trade initiation service |

## Configuration Files

### `config/firewall_whitelist.json`
```json
{
  "ssh_allowed_ips": [
    "10.0.0.0/8",
    "172.16.0.0/12", 
    "192.168.0.0/16",
    "127.0.0.1",
    "::1"
  ]
}
```

### Log Files
- **Location**: `logs/firewall_setup.log`
- **Content**: Detailed setup logs and rule application

## Verification Steps

After applying firewall rules, verify:

### 1. Localhost Communication
```bash
# Test internal service communication
curl http://localhost:3000
curl http://localhost:4000
```

### 2. Outbound API Calls
```bash
# Test API connectivity
curl https://api.kalshi.com
curl https://api.coinbase.com
```

### 3. Supervisor Services
```bash
# Check all services are running
supervisorctl -c backend/supervisord.conf status
```

### 4. Firewall Status
```bash
# View current rules
ufw status numbered
```

## Troubleshooting

### Common Issues

#### 1. Services Not Starting
**Symptom**: Supervisor services fail to start or communicate
**Solution**: Ensure localhost traffic is allowed
```bash
sudo ufw allow from 127.0.0.1 to any
```

#### 2. API Calls Failing
**Symptom**: Trading system cannot connect to Kalshi/Coinbase APIs
**Solution**: Verify outbound traffic is allowed
```bash
sudo ufw default allow outgoing
```

#### 3. SSH Access Denied
**Symptom**: Cannot SSH to production server
**Solution**: Check whitelist configuration
```bash
# View current SSH rules
sudo ufw status | grep 22
```

### Emergency Disable
```bash
# Completely disable firewall (emergency only)
sudo ufw disable
```

## Security Considerations

### Production Deployment
- **SSH Access**: Restrict to specific IP ranges or whitelisted addresses
- **Trading Ports**: Limit access to localhost only
- **Rate Limiting**: Enable SSH rate limiting to prevent brute force
- **Logging**: Monitor firewall logs for suspicious activity

### Local Development
- **Permissive Mode**: Allows all internal communication
- **No Restrictions**: Preserves development workflow
- **Easy Testing**: No interference with local testing

## Integration with DigitalOcean

### Deployment Checklist
1. **Install ufw**: `apt-get install ufw`
2. **Apply Production Rules**: `sudo ./scripts/setup_firewall.sh --mode production`
3. **Verify Services**: Check all supervisor services are running
4. **Test APIs**: Verify outbound API calls work
5. **Monitor Logs**: Watch for any connectivity issues

### DigitalOcean Firewall
- **Complementary**: Works alongside DigitalOcean's cloud firewall
- **Application-Level**: Provides additional application-specific protection
- **Service-Aware**: Understands trading system port requirements

## Files and Scripts

### Primary Scripts
- `scripts/setup_firewall.sh` - Bash version
- `scripts/firewall_setup.py` - Python version

### Configuration
- `config/firewall_whitelist.json` - IP whitelist configuration
- `backend/core/config/MASTER_PORT_MANIFEST.json` - Port definitions

### Documentation
- `README_FIREWALL.md` - This documentation
- `logs/firewall_setup.log` - Setup logs

## Summary

This firewall configuration provides **standard protection** suitable for DigitalOcean production deployment while being **minimally intrusive** to system functionality. It preserves all internal communication, outbound API calls, and local development workflows while only blocking unwanted incoming connections.

The design prioritizes:
- ✅ **System Functionality**: All internal services work normally
- ✅ **API Connectivity**: Outbound calls to trading APIs preserved
- ✅ **Development Workflow**: No interference with local development
- ✅ **Standard Protection**: Blocks unwanted incoming connections
- ✅ **Production Ready**: Suitable for cloud deployment 