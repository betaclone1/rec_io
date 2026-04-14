-- Restore users.master_users and users-scoped views; drop system helper views.

DROP VIEW IF EXISTS system.active_master_users CASCADE;
DROP VIEW IF EXISTS system.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS system.master_users_summary CASCADE;

DO $$
BEGIN
    IF to_regclass('system.master_users') IS NULL THEN
        RETURN;
    END IF;
    IF to_regclass('users.master_users') IS NULL THEN
        EXECUTE 'CREATE TABLE users.master_users (LIKE system.master_users INCLUDING ALL)';
    END IF;
    EXECUTE 'TRUNCATE users.master_users';
    EXECUTE 'INSERT INTO users.master_users SELECT * FROM system.master_users';
END
$$;

DO $$
DECLARE
    seq text;
BEGIN
    IF to_regclass('users.master_users') IS NULL THEN
        RETURN;
    END IF;
    seq := pg_get_serial_sequence('users.master_users', 'id');
    IF seq IS NOT NULL THEN
        EXECUTE format(
            'SELECT setval(%L, (SELECT COALESCE(MAX(id), 1) FROM users.master_users), true)',
            seq
        );
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('users.master_users') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users' AND table_name = 'master_users' AND column_name = 'status'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users' AND table_name = 'master_users' AND column_name = 'name'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users' AND table_name = 'master_users' AND column_name = 'last_updated'
    ) THEN
        EXECUTE $v$
            CREATE OR REPLACE VIEW users.active_master_users AS
            SELECT user_id, name, email, server_ip, last_updated
            FROM users.master_users
            WHERE status = 'active'
        $v$;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users' AND table_name = 'master_users' AND column_name = 'registration_date'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users' AND table_name = 'master_users' AND column_name = 'name'
    ) THEN
        EXECUTE $v$
            CREATE OR REPLACE VIEW users.recent_master_registrations AS
            SELECT user_id, name, email, server_ip, registration_date
            FROM users.master_users
            WHERE registration_date > NOW() - INTERVAL '30 days'
        $v$;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users' AND table_name = 'master_users' AND column_name = 'status'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users' AND table_name = 'master_users' AND column_name = 'registration_date'
    ) THEN
        EXECUTE $v$
            CREATE OR REPLACE VIEW users.master_users_summary AS
            SELECT
                COUNT(*)::bigint AS total_users,
                COUNT(*) FILTER (WHERE status = 'active')::bigint AS active_users,
                COUNT(*) FILTER (WHERE registration_date > NOW() - INTERVAL '30 days')::bigint AS recent_registrations
            FROM users.master_users
        $v$;
    END IF;
END
$$;
