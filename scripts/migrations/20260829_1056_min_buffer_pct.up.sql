-- Expiration Scalp: min_buffer_pct entry gate on monitor_list_*.
-- Same units as strike-ladder hot-path buffer_pct (percent of spot).
-- 0.000000 disables. Applied to every tenant schema (users + users_NNNN).

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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_buffer_pct'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN min_buffer_pct NUMERIC(12,6) DEFAULT 0.000000',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.min_buffer_pct IS %L',
        sch, tbl,
        'Expiration Scalp: minimum strike buffer_pct (percent of spot, same units as live strike ladder). 0.000000 disables. Reject entry when ladder buffer_pct is below this. Migration 20260829_1056_min_buffer_pct.'
      );
    END LOOP;
  END LOOP;
END
$$;
