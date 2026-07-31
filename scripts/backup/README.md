# Backup scripts

User data packaging and DB/system backups.

- **package_user_data.sh** — Full user data package (referenced by System UI → Backup Database and docs).
- **create_compressed_db_backup.sh** — Full Postgres dump → `backup/db_backups/rec_io_db_backup_*.sql.gz` (nightly cron; uploaded to Drive `DATA/DB_BACKUPS`).
- **package_user_data_fast.sh** — Faster variant.
- **essential_backup.sh**, **minimal_backup.sh**, **quick_db_backup.sh** — Backup variants.
- **test_backup.sh** — Test backup flow.

Run from project root, e.g. `./scripts/backup/package_user_data.sh`.
