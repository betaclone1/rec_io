-- Mirror tenant trades intent/slippage columns on archive live/paper tables so UNION ALL with master stays valid.
DO $$
DECLARE
    table_name text;
BEGIN
    FOR table_name IN
        SELECT t.table_name
        FROM information_schema.tables t
        WHERE t.table_schema = 'archive'
          AND t.table_type = 'BASE TABLE'
          AND (
              t.table_name ~ '^trades_archive_live_[0-9]{4}$'
              OR t.table_name ~ '^trades_archive_paper_[0-9]{4}$'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS initial_price NUMERIC(10,4)',
            table_name
        );
        EXECUTE format(
            'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS slippage NUMERIC(10,4)',
            table_name
        );
        EXECUTE format(
            'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS initial_count INTEGER',
            table_name
        );
    END LOOP;
END $$;
