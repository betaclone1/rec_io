-- Remove legacy / unused columns from system.master_users; refresh views.
DROP VIEW IF EXISTS system.active_master_users CASCADE;
DROP VIEW IF EXISTS system.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS system.master_users_summary CASCADE;

ALTER TABLE system.master_users DROP COLUMN IF EXISTS is_active;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS server_ip;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS server_hostname;
ALTER TABLE system.master_users DROP COLUMN IF EXISTS created_at;

CREATE OR REPLACE VIEW system.active_master_users AS
SELECT user_id, name, email, last_updated
FROM system.master_users
WHERE status = 'active';

CREATE OR REPLACE VIEW system.recent_master_registrations AS
SELECT user_id, name, email, registration_date
FROM system.master_users
WHERE registration_date > NOW() - INTERVAL '30 days';

CREATE OR REPLACE VIEW system.master_users_summary AS
SELECT
    COUNT(*)::bigint AS total_users,
    COUNT(*) FILTER (WHERE status = 'active')::bigint AS active_users,
    COUNT(*) FILTER (WHERE registration_date > NOW() - INTERVAL '30 days')::bigint AS recent_registrations
FROM system.master_users;
