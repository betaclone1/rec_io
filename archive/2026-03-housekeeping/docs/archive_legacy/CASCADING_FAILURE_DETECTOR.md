# Cascading Failure Detector

## Overview

The Cascading Failure Detector is an automated monitoring system that detects system-wide failures and can automatically trigger a MASTER RESTART when needed. This system operates independently of your database and JSON files, ensuring data integrity during recovery operations.

## Features

### 🔍 **Comprehensive Monitoring**
- **All Services Critical**: Monitors 9 core trading services
- **Supervisor Status**: Tracks overall supervisor health
- **Database Integrity**: Checks database accessibility
- **Critical Files**: Verifies configuration files exist and are readable
- **SMS Notifications**: Sends alerts when cascading failures are detected

### 🚨 **Failure Detection Levels**
- **NONE (0)**: System healthy
- **WARNING (1)**: Some services showing issues
- **CRITICAL (2)**: Multiple important services failing
- **CASCADING (3)**: System-wide failure detected

### 🔄 **Automatic Recovery**
- **Rate Limited**: Maximum 3 restart attempts per hour
- **Safe Restart**: Uses existing MASTER RESTART script
- **Logging**: Comprehensive event logging
- **Non-Destructive**: No impact on database or JSON files

## Configuration

### Service Classification

**All Services Are Critical** (system-wide monitoring):
- `main_app` - Web server and API endpoints
- `trade_manager` - Trade lifecycle management
- `trade_executor` - Trade execution engine
- `auto_entry_supervisor` - Automated entry logic
- `unified_production_coordinator` - Core pipeline coordinator
- `active_trade_supervisor` - Active trade monitoring
- `trade_initiator` - Trade initiation logic
- `kalshi_api_watchdog` - Kalshi API monitoring
- `btc_price_watchdog` - Bitcoin price monitoring

### Failure Thresholds
- **Warning**: 3 consecutive failures
- **Critical**: 5 consecutive failures  
- **Cascading**: 7 consecutive failures
- **Check Interval**: 30 seconds
- **Max Restarts**: 3 per hour

## Operation

### Detection Logic

The system assesses failure levels based on:

1. **Service Failures**: Count of services with consecutive failures ≥ 5
2. **Supervisor Health**: Overall supervisor status
3. **Database Integrity**: Database accessibility checks
4. **Critical Files**: Configuration file accessibility

### Failure Level Determination

```python
if critical_failures >= 3 or not supervisor_healthy or not files_healthy:
    return CASCADING
elif critical_failures >= 2 or important_failures >= 3:
    return CRITICAL  
elif critical_failures >= 1 or important_failures >= 2:
    return WARNING
else:
    return NONE
```

### Restart Triggers

**CASCADING FAILURE** triggers automatic MASTER RESTART when:
- 3+ services failing consecutively
- Supervisor not responding
- Critical configuration files missing/corrupted

**Rate Limiting** prevents restart loops:
- Maximum 3 restart attempts per hour
- 1-hour cooldown between restarts
- Comprehensive restart history tracking

## Monitoring

### Status API
```bash
curl http://localhost:3000/api/failure_detector_status
```

Returns comprehensive status including:
- Current failure level
- Service health details
- Supervisor status
- Database health
- Critical file status
- Restart history

### Log Files
- **Main Log**: `logs/cascading_failure_detector.out.log`
- **Error Log**: `logs/cascading_failure_detector.err.log`
- **Event Log**: `logs/cascading_failure_detector.log` (JSON format)

### Supervisor Integration
The detector runs as a supervisor service:
```bash
supervisorctl -c backend/supervisord.conf status cascading_failure_detector
```

## Safety Features

### Data Protection
- **Read-Only Checks**: Database integrity checks are read-only
- **File Verification**: Only verifies file existence/readability
- **No Data Modification**: Never modifies database or JSON files
- **Safe Restart**: Uses existing MASTER RESTART script

### Rate Limiting
- **Restart Limits**: Maximum 3 attempts per hour
- **Cooldown Period**: 1-hour minimum between restarts
- **History Tracking**: Maintains restart attempt history
- **Manual Override**: Can be manually triggered if needed

### SMS Notifications
- **Immediate Alerts**: Sends SMS when cascading failures are detected
- **Recovery Notifications**: Confirms when MASTER RESTART completes
- **Configurable**: Enable/disable via environment variables
- **Twilio Integration**: Reliable SMS delivery service

### Error Handling
- **Graceful Degradation**: Continues monitoring even if some checks fail
- **Comprehensive Logging**: All events logged with timestamps
- **Exception Safety**: Individual service failures don't crash the detector
- **Recovery Tracking**: Monitors restart success/failure

## Manual Operations

### Check Status
```bash
# Via API
curl http://localhost:3000/api/failure_detector_status

# Via supervisor
supervisorctl -c backend/supervisord.conf status cascading_failure_detector

# View logs
tail -f logs/cascading_failure_detector.out.log
```

### Manual Restart
```bash
# Restart the detector
supervisorctl -c backend/supervisord.conf restart cascading_failure_detector

# Trigger manual MASTER RESTART
./scripts/MASTER_RESTART.sh
```

### Disable Auto-Restart
```bash
# Stop the detector
supervisorctl -c backend/supervisord.conf stop cascading_failure_detector

# Remove from supervisor config
# Edit backend/supervisord.conf and comment out the cascading_failure_detector section
```

## Integration with Existing System

### Supervisor Configuration
The detector is integrated into your existing supervisor configuration:
```ini
[program:cascading_failure_detector]
command=python backend/cascading_failure_detector.py
directory=.
autostart=true
autorestart=true
stderr_logfile=logs/cascading_failure_detector.err.log
stdout_logfile=logs/cascading_failure_detector.out.log
environment=PATH="venv/bin",PYTHONPATH="."
```

### API Integration
The detector provides status via your existing main app API:
- **Endpoint**: `/api/failure_detector_status`
- **Method**: GET
- **Response**: JSON status report

### Logging Integration
Uses your existing logging infrastructure:
- **Log Directory**: `logs/`
- **Format**: Consistent with other services
- **Rotation**: Managed by supervisor

## Troubleshooting

### Common Issues

**Service Shows as "unknown"**
- Service may not have a health endpoint
- Check if service is actually running
- Verify port configuration

**False Positives**
- Adjust failure thresholds in the detector code
- Check network connectivity
- Verify service health endpoints

**Restart Not Triggering**
- Check rate limiting (max 3 per hour)
- Verify MASTER RESTART script permissions
- Check supervisor status

### Debug Mode
```bash
# Run detector directly for debugging
python backend/cascading_failure_detector.py

# Check specific service health
supervisorctl -c backend/supervisord.conf status main_app
```

## Future Enhancements

### Potential Improvements
- **Web Dashboard**: Real-time monitoring interface
- **Email Alerts**: Notification system for failures
- **Custom Thresholds**: Configurable failure thresholds
- **Service Dependencies**: Map service dependencies
- **Predictive Analysis**: Detect patterns before failures

### Configuration Options
- **JSON Configuration**: External config file
- **Environment Variables**: Runtime configuration
- **Service-Specific Thresholds**: Different thresholds per service
- **Custom Health Checks**: Service-specific health endpoints

## Conclusion

The Cascading Failure Detector provides automated monitoring and recovery for your trading system. It operates safely without affecting your data while providing comprehensive failure detection and automatic recovery capabilities.

The system is designed to be:
- **Safe**: Never modifies your data
- **Reliable**: Comprehensive error handling
- **Configurable**: Adjustable thresholds and settings
- **Transparent**: Full logging and status reporting
- **Non-Intrusive**: Runs alongside existing services 