-- Reverse market-wide loss prevention columns on users*.system_settings_*.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch, tbl IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE t.table_type = 'BASE TABLE'
      AND (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_name ~ '^system_settings_'
    ORDER BY 1, 2
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'stop_loss_count_threshold'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN stop_loss_count_threshold', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'hero_monitor_id'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN hero_monitor_id', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'market_wide_loss_prevention'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN market_wide_loss_prevention', sch, tbl);
    END IF;
  END LOOP;
END $$;
