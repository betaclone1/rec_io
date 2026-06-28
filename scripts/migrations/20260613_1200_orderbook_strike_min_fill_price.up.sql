-- Orderbook strike pricing support: min_fill_price on monitor_list (execution floor).
-- NULL or 0 = disabled (no executor fill gate).

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_fill_price'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN min_fill_price NUMERIC(6,4)',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.min_fill_price IS %L',
        sch, tbl,
        'Minimum estimated taker fill price (dollars) before executor sends open order; NULL/0 disables.'
      );
    END LOOP;
  END LOOP;
END $$;
