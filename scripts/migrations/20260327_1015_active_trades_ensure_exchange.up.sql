-- Ensure every users.active_trades_* mirror table has execution venue as exchange (matches users.trades_*).
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema = 'users'
          AND t.table_name ~ '^active_trades_'
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns c
            WHERE c.table_schema = 'users'
              AND c.table_name = r.table_name
              AND c.column_name = 'market'
        )
        AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns c
            WHERE c.table_schema = 'users'
              AND c.table_name = r.table_name
              AND c.column_name = 'exchange'
        ) THEN
            EXECUTE format('ALTER TABLE users.%I RENAME COLUMN market TO exchange', r.table_name);
        ELSIF NOT EXISTS (
            SELECT 1 FROM information_schema.columns c
            WHERE c.table_schema = 'users'
              AND c.table_name = r.table_name
              AND c.column_name = 'exchange'
        ) THEN
            EXECUTE format(
                'ALTER TABLE users.%I ADD COLUMN exchange VARCHAR(50)',
                r.table_name
            );
        END IF;
    END LOOP;
END $$;
