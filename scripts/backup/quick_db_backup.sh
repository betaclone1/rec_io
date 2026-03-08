#!/bin/bash
cd /opt/rec_io_server
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="backup/quick_db_backup_${TIMESTAMP}.sql"
mkdir -p backup
pg_dump -h localhost -U rec_io_user -d rec_io_db --clean --if-exists --create > $BACKUP_FILE
echo "Quick backup created: $BACKUP_FILE"
echo "File size: $(du -h $BACKUP_FILE | cut -f1)"
