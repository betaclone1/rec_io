DROP VIEW IF EXISTS system.active_master_users CASCADE;
DROP VIEW IF EXISTS system.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS system.master_users_summary CASCADE;

ALTER TABLE system.master_users DROP COLUMN IF EXISTS notes;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS system_version;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS server_hostname;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS last_updated;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS registration_date;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS status;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS name;
