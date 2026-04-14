-- Mirror users.strategy_list_0001 into system.strategy_list_default (structure + row copy).
-- master_users lives in system only; see migration 20260410_1015_users_master_users_to_system.

CREATE SCHEMA IF NOT EXISTS system;

CREATE TABLE system.strategy_list_default (LIKE users.strategy_list_0001 INCLUDING ALL);

INSERT INTO system.strategy_list_default SELECT * FROM users.strategy_list_0001;

-- Keep SERIAL/sequence aligned after bulk copy (only when an id column + sequence exist)
DO $$
DECLARE
    seq text;
BEGIN
    IF to_regclass('system.strategy_list_default') IS NOT NULL THEN
        seq := pg_get_serial_sequence('system.strategy_list_default', 'id');
        IF seq IS NOT NULL THEN
            EXECUTE format(
                'SELECT setval(%L, (SELECT COALESCE(MAX(id), 1) FROM system.strategy_list_default), true)',
                seq
            );
        END IF;
    END IF;
END
$$;
