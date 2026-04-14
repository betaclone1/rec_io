-- Cannot recreate dropped per-tenant user_info_* without a backup. This only removes kalshi_user_id added by the paired up migration.
ALTER TABLE system.master_users DROP COLUMN IF EXISTS kalshi_user_id;
