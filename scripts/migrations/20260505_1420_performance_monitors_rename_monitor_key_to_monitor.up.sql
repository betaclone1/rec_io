-- Align performance_monitors_* PK column name with trades.monitor and monitor_list naming (`monitor`).

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
        AND t.table_name ~ '^performance_monitors_[0-9]{4}$'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'monitor_key'
      ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'monitor'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN monitor_key TO monitor', sch, tbl);
      END IF;
    END LOOP;
  END LOOP;
END
$$;
