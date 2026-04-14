-- Restore dropped columns (empty); previous data is not recovered.
DROP VIEW IF EXISTS system.active_master_users CASCADE;
DROP VIEW IF EXISTS system.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS system.master_users_summary CASCADE;

ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS is_active BOOLEAN;
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS server_ip VARCHAR(45);
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS server_hostname VARCHAR(255);
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE;

CREATE OR REPLACE VIEW system.active_master_users AS
SELECT user_id, name, email, server_ip, last_updated
FROM system.master_users
WHERE status = 'active';

CREATE OR REPLACE VIEW system.recent_master_registrations AS
SELECT user_id, name, email, server_ip, registration_date
FROM system.master_users
WHERE registration_date > NOW() - INTERVAL '30 days';

CREATE OR REPLACE VIEW system.master_users_summary AS
SELECT
    COUNT(*)::bigint AS total_users,
    COUNT(*) FILTER (WHERE status = 'active')::bigint AS active_users,
    COUNT(*) FILTER (WHERE registration_date > NOW() - INTERVAL '30 days')::bigint AS recent_registrations
FROM system.master_users;
