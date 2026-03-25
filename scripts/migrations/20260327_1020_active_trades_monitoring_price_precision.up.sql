-- Widen ATS monitoring columns on all users.active_trades_* mirror tables so spot and buffer
-- keep full precision (aligned with live_data.live_price_log_1s_* price columns, up to numeric(10,6)).
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
              AND c.column_name = 'current_symbol_price'
        ) THEN
            EXECUTE format(
                'ALTER TABLE users.%I ALTER COLUMN current_symbol_price TYPE NUMERIC(20,8)',
                r.table_name
            );
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns c
            WHERE c.table_schema = 'users'
              AND c.table_name = r.table_name
              AND c.column_name = 'buffer_from_entry'
        ) THEN
            EXECUTE format(
                'ALTER TABLE users.%I ALTER COLUMN buffer_from_entry TYPE NUMERIC(20,8)',
                r.table_name
            );
        END IF;
    END LOOP;
END $$;
