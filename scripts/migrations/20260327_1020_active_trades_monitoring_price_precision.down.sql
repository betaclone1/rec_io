-- Revert ATS monitoring column precision (may round values with more than 2 fractional digits).
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
                'ALTER TABLE users.%I ALTER COLUMN current_symbol_price TYPE NUMERIC(10,2) USING round(current_symbol_price::numeric, 2)',
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
                'ALTER TABLE users.%I ALTER COLUMN buffer_from_entry TYPE NUMERIC(10,2) USING round(buffer_from_entry::numeric, 2)',
                r.table_name
            );
        END IF;
    END LOOP;
END $$;
