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
        WHERE x.table_schema = sch AND x.table_name = rel AND x.column_name = 'user_id'
      ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns x
        WHERE x.table_schema = sch AND x.table_name = rel AND x.column_name = 'singleton'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN user_id TO singleton', sch, rel);
      END IF;
    END LOOP;
  END LOOP;
END
$$;
