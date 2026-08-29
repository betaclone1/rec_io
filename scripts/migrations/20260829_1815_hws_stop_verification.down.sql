-- Revert High Water Scalp auto-stop verification dwell columns.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name LIKE 'monitor_list_%' OR t.table_name LIKE 'strategy_list_%')
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'stop_verification_period_enabled'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN stop_verification_period_enabled', sch, tbl);
      END IF;
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'stop_verification_period_seconds'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN stop_verification_period_seconds', sch, tbl);
      END IF;
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns c
    WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
      AND c.column_name = 'stop_verification_period_enabled'
  ) THEN
    ALTER TABLE system.strategy_list_default DROP COLUMN stop_verification_period_enabled;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns c
    WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
      AND c.column_name = 'stop_verification_period_seconds'
  ) THEN
    ALTER TABLE system.strategy_list_default DROP COLUMN stop_verification_period_seconds;
  END IF;
END
$$;
