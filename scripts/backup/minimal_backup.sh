#!/bin/bash
cd /opt/rec_io_server
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backup/minimal_backup_${TIMESTAMP}.sql"
mkdir -p backup
pg_dump -h localhost -U rec_io_user -d rec_io_db --clean --if-exists --create --exclude-table=analytics.* --exclude-table=historical_data.* --exclude-table=live_data.* --exclude-table=work_progress.* > $BACKUP_FILE
echo "Minimal backup created: $BACKUP_FILE"
echo "File size: $(du -h $BACKUP_FILE | cut -f1)"
