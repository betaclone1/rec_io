-- Move master_users to system schema only: merge from users.master_users if present, then drop users table/views.
-- Helper views used by scripts live in system.*.

CREATE SCHEMA IF NOT EXISTS system;

-- 1) If users.master_users still exists, ensure system.master_users and merge any missing rows.
DO $$
BEGIN
    IF to_regclass('users.master_users') IS NOT NULL THEN
        IF to_regclass('system.master_users') IS NULL THEN
            EXECUTE 'CREATE TABLE system.master_users (LIKE users.master_users INCLUDING ALL)';
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'system'
              AND table_name = 'master_users'
              AND column_name = 'user_id'
        ) THEN
            EXECUTE $q$
                INSERT INTO system.master_users
                SELECT u.* FROM users.master_users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM system.master_users s
                    WHERE s.user_id IS NOT DISTINCT FROM u.user_id
                )
            $q$;
        ELSE
            IF NOT EXISTS (SELECT 1 FROM system.master_users LIMIT 1) THEN
                EXECUTE 'INSERT INTO system.master_users SELECT * FROM users.master_users';
            END IF;
        END IF;
    END IF;
END
$$;

-- 2) Greenfield or legacy installs with no table yet: canonical shape (matches registration script / manage_master_users.sh)
DO $$
BEGIN
    IF to_regclass('system.master_users') IS NULL THEN
        CREATE TABLE system.master_users (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            phone VARCHAR(50),
            server_ip VARCHAR(45),
            server_hostname VARCHAR(255),
            registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            system_version VARCHAR(50),
            status VARCHAR(20) DEFAULT 'active',
            notes TEXT
        );
    END IF;
END
$$;

-- 3) Drop users-scoped objects
DROP VIEW IF EXISTS users.active_master_users CASCADE;
DROP VIEW IF EXISTS users.recent_master_registrations CASCADE;
DROP VIEW IF EXISTS users.master_users_summary CASCADE;
DROP TABLE IF EXISTS users.master_users CASCADE;

-- 4) Helper views: migration 20260410_1020_system_master_users_registration_columns

-- 5) Sequence alignment when id is serial
DO $$
DECLARE
    seq text;
    has_id boolean;
BEGIN
    IF to_regclass('system.master_users') IS NULL THEN
        RETURN;
    END IF;
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system'
          AND table_name = 'master_users'
          AND column_name = 'id'
    ) INTO has_id;
    IF has_id THEN
        seq := pg_get_serial_sequence('system.master_users', 'id');
        IF seq IS NOT NULL THEN
            EXECUTE format(
                'SELECT setval(%L, (SELECT COALESCE(MAX(id), 1) FROM system.master_users), true)',
                seq
            );
        END IF;
    END IF;
END
$$;
