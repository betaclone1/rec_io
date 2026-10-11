-- Fails if any monitor_list ret_pct exceeds ±9,999.9 (the reason for the up migration).

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
      SELECT c.table_name FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name ~ '^monitor_list_[0-9]{4}$'
        AND c.column_name = 'ret_pct'
    LOOP
      EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN ret_pct TYPE NUMERIC(5,1)', sch, tbl);
    END LOOP;
  END LOOP;
END $$;
