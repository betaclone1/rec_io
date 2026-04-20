-- Remove immutable ticket intent fields and execution slippage from tenant trades tables.
DO $$
DECLARE
    schema_name text;
    table_name text;
BEGIN
    FOR schema_name IN
        SELECT n.nspname
        FROM pg_namespace n
        WHERE n.nspname = 'users'
           OR n.nspname ~ '^users_[0-9]{4}$'
    LOOP
        FOR table_name IN
            SELECT t.table_name
            FROM information_schema.tables t
            WHERE t.table_schema = schema_name
              AND t.table_type = 'BASE TABLE'
              AND t.table_name ~ '^trades_[0-9]{4}$'
        LOOP
            EXECUTE format(
                'ALTER TABLE %I.%I DROP COLUMN IF EXISTS initial_count',
                schema_name,
                table_name
            );
            EXECUTE format(
                'ALTER TABLE %I.%I DROP COLUMN IF EXISTS slippage',
                schema_name,
                table_name
            );
            EXECUTE format(
                'ALTER TABLE %I.%I DROP COLUMN IF EXISTS initial_price',
                schema_name,
                table_name
            );
        END LOOP;
    END LOOP;
END $$;
