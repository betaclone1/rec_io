-- Persist dashboard performance strip calendar vs rolling (TD vs PREV) for NEW shell.

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
        AND t.table_name ~ '^dashboard_preferences_[0-9]{4}$'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'performance_rollup_view'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN performance_rollup_view VARCHAR(8) NOT NULL DEFAULT %L',
          sch, tbl, 'td'
        );
        EXECUTE format(
          'COMMENT ON COLUMN %I.%I.performance_rollup_view IS %L',
          sch, tbl,
          'Performance strip bucket: td = calendar to-date (trade date), prev = rolling windows from closed_at.'
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
