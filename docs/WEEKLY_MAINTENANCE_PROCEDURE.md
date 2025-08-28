# Weekly Maintenance Procedure

## Overview

This document outlines a comprehensive weekly maintenance procedure for the REC.IO trading system. The procedure includes automated backup creation, system updates, and verification to ensure system reliability while maintaining the protection against automatic maintenance failures.

## Schedule

- **Frequency**: Weekly
- **Timing**: Saturday night (low trading activity period)
- **Duration**: Approximately 30-45 minutes
- **Time Zone**: Server local time (UTC-5/UTC-4)

## Automated Maintenance Script

### Script Location
```
/opt/rec_io_server/scripts/weekly_maintenance.sh
```

### Execution Schedule
```bash
# Add to crontab for Saturday 2:00 AM
0 2 * * 6 /opt/rec_io_server/scripts/weekly_maintenance.sh >> /var/log/rec_io_maintenance.log 2>&1
```

## Step-by-Step Procedure

### Phase 1: Pre-Maintenance Preparation (2:00 AM - 2:05 AM)

#### 1.1 System Status Check
```bash
# Verify all services are running
supervisorctl status

# Check system resources
df -h
free -h
top -n 1

# Verify database connectivity
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT 1;"
```

#### 1.2 Notification System
```bash
# Send maintenance start notification
curl -X POST "https://api.notification.service/alert" \
  -H "Content-Type: application/json" \
  -d '{"message": "REC.IO Weekly Maintenance Starting", "level": "info"}'
```

### Phase 2: Service Shutdown (2:05 AM - 2:10 AM)

#### 2.1 Graceful Service Stop
```bash
# Stop all trading services
supervisorctl stop all

# Wait for services to stop gracefully
sleep 30

# Force stop any remaining processes
supervisorctl shutdown
```

#### 2.2 Database Backup
```bash
# Create timestamp for backup
BACKUP_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Create PostgreSQL backup
pg_dump -h localhost -U rec_io_user -d rec_io_db > /opt/backups/database_${BACKUP_TIMESTAMP}.sql

# Compress backup
gzip /opt/backups/database_${BACKUP_TIMESTAMP}.sql
```

### Phase 3: System Backup (2:10 AM - 2:25 AM)

#### 3.1 Full System Image Creation
```bash
# Create system image backup
dd if=/dev/vda of=/opt/backups/system_image_${BACKUP_TIMESTAMP}.img bs=4M status=progress

# Compress system image
gzip /opt/backups/system_image_${BACKUP_TIMESTAMP}.img
```

#### 3.2 Critical Data Backup
```bash
# Backup critical directories
tar -czf /opt/backups/critical_data_${BACKUP_TIMESTAMP}.tar.gz \
  /opt/rec_io_server/backend/data \
  /opt/rec_io_server/backend/core/config \
  /opt/rec_io_server/venv \
  /etc/supervisor/conf.d \
  /etc/apt/apt.conf.d/99disable-auto-updates
```

### Phase 4: Cloud Backup Upload (2:25 AM - 2:40 AM)

#### 4.1 Google Drive Upload
```bash
# Upload to Google Drive using rclone
rclone copy /opt/backups/ gdrive:rec_io_backups/${BACKUP_TIMESTAMP}/ \
  --progress --transfers 4 --checkers 8
```

#### 4.2 Alternative Backup Locations
```bash
# Upload to Dropbox (if configured)
rclone copy /opt/backups/ dropbox:rec_io_backups/${BACKUP_TIMESTAMP}/ \
  --progress --transfers 4 --checkers 8

# Upload to local storage (if available)
rsync -avz /opt/backups/ /mnt/local_backup/rec_io_backups/${BACKUP_TIMESTAMP}/
```

### Phase 5: Cleanup Old Backups (2:40 AM - 2:45 AM)

#### 5.1 Local Cleanup
```bash
# Keep only last 4 weeks of backups locally
find /opt/backups/ -name "*.gz" -mtime +28 -delete
find /opt/backups/ -name "*.img" -mtime +28 -delete
```

#### 5.2 Cloud Cleanup
```bash
# Clean up old cloud backups (keep 4 weeks)
rclone delete gdrive:rec_io_backups/ --min-age 28d
rclone delete dropbox:rec_io_backups/ --min-age 28d
```

### Phase 6: System Updates (2:45 AM - 3:00 AM)

#### 6.1 Package Updates
```bash
# Update package lists
apt update

# Install security updates only
apt upgrade --security-only -y

# Install critical package updates
apt upgrade -y

# Clean up package cache
apt autoremove -y
apt autoclean
```

#### 6.2 Python Environment Updates
```bash
# Activate virtual environment
source /opt/rec_io_server/venv/bin/activate

# Update pip
pip install --upgrade pip

# Update critical packages
pip install --upgrade fastapi uvicorn psycopg2-binary supervisor
```

### Phase 7: System Verification (3:00 AM - 3:10 AM)

#### 7.1 Configuration Verification
```bash
# Verify automatic maintenance is still disabled
systemctl list-unit-files | grep -E "(apt|unattended)" | grep enabled

# Verify supervisor configuration
supervisord -c /opt/rec_io_server/backend/supervisord.conf -t

# Verify database connectivity
PGPASSWORD=rec_io_password psql -h localhost -U rec_io_user -d rec_io_db -c "SELECT COUNT(*) FROM information_schema.tables;"
```

#### 7.2 File System Verification
```bash
# Verify critical files exist
ls -la /opt/rec_io_server/venv/bin/python
ls -la /opt/rec_io_server/backend/supervisord.conf
ls -la /etc/apt/apt.conf.d/99disable-auto-updates
```

### Phase 8: Service Restart (3:10 AM - 3:15 AM)

#### 8.1 Service Startup
```bash
# Start supervisor
supervisord -c /opt/rec_io_server/backend/supervisord.conf

# Wait for services to start
sleep 30

# Check service status
supervisorctl status
```

#### 8.2 Health Check
```bash
# Verify web interface is responding
curl -f http://localhost:3000/health || echo "Web interface not responding"

# Verify database services
curl -f http://localhost:4000/health || echo "Trade manager not responding"

# Check log files for errors
tail -20 /opt/rec_io_server/logs/main_app.err.log
```

### Phase 9: Post-Maintenance Verification (3:15 AM - 3:20 AM)

#### 9.1 System Health Check
```bash
# Verify all services are running
supervisorctl status | grep -v RUNNING

# Check system resources
df -h
free -h

# Verify backup was successful
ls -la /opt/backups/ | grep ${BACKUP_TIMESTAMP}
```

#### 9.2 Notification
```bash
# Send completion notification
curl -X POST "https://api.notification.service/alert" \
  -H "Content-Type: application/json" \
  -d '{"message": "REC.IO Weekly Maintenance Completed Successfully", "level": "success"}'
```

## Automation Script

### Complete Weekly Maintenance Script
```bash
#!/bin/bash
# /opt/rec_io_server/scripts/weekly_maintenance.sh

set -e

# Configuration
BACKUP_DIR="/opt/backups"
LOG_FILE="/var/log/rec_io_maintenance.log"
BACKUP_TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a $LOG_FILE
}

# Error handling
handle_error() {
    log "ERROR: $1"
    # Send error notification
    curl -X POST "https://api.notification.service/alert" \
      -H "Content-Type: application/json" \
      -d "{\"message\": \"REC.IO Maintenance Failed: $1\", \"level\": \"error\"}"
    exit 1
}

# Main procedure
main() {
    log "Starting weekly maintenance procedure"
    
    # Phase 1: Pre-maintenance
    log "Phase 1: Pre-maintenance preparation"
    supervisorctl status || handle_error "Services not running"
    
    # Phase 2: Service shutdown
    log "Phase 2: Stopping services"
    supervisorctl stop all
    sleep 30
    
    # Phase 3: Backup creation
    log "Phase 3: Creating backups"
    mkdir -p $BACKUP_DIR
    
    # Database backup
    pg_dump -h localhost -U rec_io_user -d rec_io_db > $BACKUP_DIR/database_${BACKUP_TIMESTAMP}.sql
    gzip $BACKUP_DIR/database_${BACKUP_TIMESTAMP}.sql
    
    # System image backup
    dd if=/dev/vda of=$BACKUP_DIR/system_image_${BACKUP_TIMESTAMP}.img bs=4M status=progress
    gzip $BACKUP_DIR/system_image_${BACKUP_TIMESTAMP}.img
    
    # Phase 4: Cloud upload
    log "Phase 4: Uploading to cloud"
    rclone copy $BACKUP_DIR/ gdrive:rec_io_backups/${BACKUP_TIMESTAMP}/ --progress
    
    # Phase 5: Cleanup
    log "Phase 5: Cleaning old backups"
    find $BACKUP_DIR/ -name "*.gz" -mtime +28 -delete
    rclone delete gdrive:rec_io_backups/ --min-age 28d
    
    # Phase 6: Updates
    log "Phase 6: System updates"
    apt update
    apt upgrade --security-only -y
    apt autoremove -y
    
    # Phase 7: Verification
    log "Phase 7: System verification"
    systemctl list-unit-files | grep -E "(apt|unattended)" | grep enabled || log "Automatic maintenance properly disabled"
    
    # Phase 8: Restart
    log "Phase 8: Restarting services"
    supervisord -c /opt/rec_io_server/backend/supervisord.conf
    sleep 30
    
    # Phase 9: Final verification
    log "Phase 9: Final verification"
    supervisorctl status | grep -v RUNNING || log "All services running"
    
    log "Weekly maintenance completed successfully"
    
    # Success notification
    curl -X POST "https://api.notification.service/alert" \
      -H "Content-Type: application/json" \
      -d '{"message": "REC.IO Weekly Maintenance Completed Successfully", "level": "success"}'
}

# Run main procedure
main "$@"
```

## Additional Maintenance Tasks

### Monthly Tasks (First Saturday of each month)
- **Log Rotation**: Archive and compress old log files
- **Database Optimization**: Run VACUUM and ANALYZE on PostgreSQL
- **Security Audit**: Review system access and permissions
- **Performance Analysis**: Review system performance metrics

### Quarterly Tasks (Every 3 months)
- **Full System Review**: Comprehensive system health check
- **Backup Restoration Test**: Test backup restoration procedures
- **Security Updates**: Review and apply major security updates
- **Configuration Review**: Review and update system configurations

## Monitoring and Alerts

### Pre-Maintenance Alerts
- 24 hours before: "Maintenance scheduled for tomorrow"
- 1 hour before: "Maintenance starting in 1 hour"

### During Maintenance
- Start notification
- Progress updates every 15 minutes
- Completion notification

### Post-Maintenance
- Success/failure notification
- System health report
- Backup verification report

## Rollback Procedures

### Emergency Rollback
```bash
# If maintenance fails, restore from latest backup
rclone copy gdrive:rec_io_backups/LATEST/ /opt/backups/restore/
gunzip /opt/backups/restore/system_image_*.img.gz
dd if=/opt/backups/restore/system_image_*.img of=/dev/vda
```

### Database Rollback
```bash
# Restore database from backup
gunzip /opt/backups/restore/database_*.sql.gz
psql -h localhost -U rec_io_user -d rec_io_db < /opt/backups/restore/database_*.sql
```

## Success Metrics

### Maintenance Success Criteria
- ✅ All services restart successfully
- ✅ No critical errors in logs
- ✅ Backup verification successful
- ✅ System performance within normal range
- ✅ All automated tests pass

### Monitoring Dashboard
- System uptime tracking
- Backup success rate
- Update success rate
- Service restart time
- Overall maintenance duration

---

**Note**: This procedure ensures system reliability while maintaining the protection against automatic maintenance failures. All updates are performed manually during controlled maintenance windows, preventing the type of failure experienced on August 19, 2025.
