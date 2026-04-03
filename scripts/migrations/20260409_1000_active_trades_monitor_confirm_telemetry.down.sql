DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = 'users'
          AND (
            table_name ~ '^active_trades_15m_[0-9]+$'
            OR table_name ~ '^active_trades_hourly_[0-9]+$'
            OR table_name ~ '^active_trades_[0-9]+_[0-9]+$'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I DROP COLUMN IF EXISTS monitoring_gap_events',
            r.table_schema,
            r.table_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I DROP COLUMN IF EXISTS first_live_market_quote_at',
            r.table_schema,
            r.table_name
        );
    END LOOP;
END $$;
