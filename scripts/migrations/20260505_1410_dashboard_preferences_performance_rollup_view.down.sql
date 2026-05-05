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
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'performance_rollup_view'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN IF EXISTS performance_rollup_view',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
