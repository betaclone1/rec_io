-- Align legacy system.master_users (copied from old users.master_users) with registration / manage_master_users.sh shape.

DO $$
BEGIN
    IF to_regclass('system.master_users') IS NULL THEN
        RETURN;
    END IF;
    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS name VARCHAR(255);
    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active';
    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS server_hostname VARCHAR(255);
    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS system_version VARCHAR(50);
    ALTER TABLE system.master_users ADD COLUMN IF NOT EXISTS notes TEXT;
END
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'first_name'
    ) THEN
        UPDATE system.master_users
        SET name = TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')))
        WHERE name IS NULL OR TRIM(name) = '';
    END IF;
END
$$;

UPDATE system.master_users
SET name = COALESCE(NULLIF(TRIM(name), ''), email::text, user_id::text, 'unknown')
WHERE name IS NULL OR TRIM(name) = '';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'is_active'
    ) THEN
        UPDATE system.master_users
        SET status = CASE
            WHEN is_active IS TRUE THEN 'active'
            WHEN is_active IS FALSE THEN 'inactive'
            ELSE COALESCE(status, 'active')
        END;
    END IF;
END
$$;

UPDATE system.master_users SET status = COALESCE(status, 'active') WHERE status IS NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'created_at'
    ) THEN
        UPDATE system.master_users
        SET registration_date = created_at
        WHERE registration_date IS NULL AND created_at IS NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'updated_at'
    ) THEN
        UPDATE system.master_users
        SET last_updated = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        WHERE last_updated IS NULL;
    END IF;
END
$$;

UPDATE system.master_users SET registration_date = COALESCE(registration_date, CURRENT_TIMESTAMP) WHERE registration_date IS NULL;
UPDATE system.master_users SET last_updated = COALESCE(last_updated, registration_date, CURRENT_TIMESTAMP) WHERE last_updated IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM system.master_users WHERE name IS NULL OR TRIM(name) = '') THEN
        ALTER TABLE system.master_users ALTER COLUMN name SET NOT NULL;
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
