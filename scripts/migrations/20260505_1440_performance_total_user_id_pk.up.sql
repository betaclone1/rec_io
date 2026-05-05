-- Align performance_total_* PK with the rest of the app (e.g. dashboard_preferences.user_id): one row per slot, user_id = 1.

DO $$
DECLARE
  sch text;
  rel text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR rel IN
      SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = sch
        AND c.relkind = 'r'
        AND c.relname ~ '^performance_total_[0-9]{4}$'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns x
        WHERE x.table_schema = sch AND x.table_name = rel AND x.column_name = 'singleton'
      ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns x
        WHERE x.table_schema = sch AND x.table_name = rel AND x.column_name = 'user_id'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN singleton TO user_id', sch, rel);
      END IF;
    END LOOP;
  END LOOP;
END
$$;
