-- Longer status values (e.g. pending_email_verification); optional user_no + name split on canonical id-based rows.

DROP VIEW IF EXISTS system.master_users_summary CASCADE;
DROP VIEW IF EXISTS system.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS system.active_master_users CASCADE;

ALTER TABLE system.master_users
  ALTER COLUMN status TYPE VARCHAR(64);

-- Canonical installs (id SERIAL, no user_no): add 4-digit string user_no aligned with users_NNNN.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'user_no'
    ) THEN
        ALTER TABLE system.master_users ADD COLUMN user_no VARCHAR(10);
        UPDATE system.master_users
        SET user_no = LPAD(id::text, 4, '0')
        WHERE user_no IS NULL AND id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS master_users_user_no_key ON system.master_users (user_no);
        IF NOT EXISTS (SELECT 1 FROM system.master_users WHERE user_no IS NULL) THEN
            ALTER TABLE system.master_users ALTER COLUMN user_no SET NOT NULL;
        END IF;
    END IF;
END
$$;

ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS first_name VARCHAR(100);
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS last_name VARCHAR(100);
ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS account_type VARCHAR(32) DEFAULT 'user_basic';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'first_name'
    ) THEN
        ALTER TABLE system.master_users ALTER COLUMN first_name TYPE VARCHAR(100);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'last_name'
    ) THEN
        ALTER TABLE system.master_users ALTER COLUMN last_name TYPE VARCHAR(100);
    END IF;
END
$$;

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
