#!/bin/bash
cd /opt/rec_io_server
mkdir -p backup
pg_dump -h localhost -U rec_io_user -d rec_io_db --table=users.master_users > backup/test_backup.sql
echo "Test backup created"
ls -la backup/test_backup.sql
