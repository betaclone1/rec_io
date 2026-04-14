-- Revert status width and views only (does not remove user_no / first_name / account_type if present).

DROP VIEW IF EXISTS system.master_users_summary CASCADE;
DROP VIEW IF EXISTS system.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS system.active_master_users CASCADE;

ALTER TABLE system.master_users
  ALTER COLUMN status TYPE VARCHAR(20);

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
