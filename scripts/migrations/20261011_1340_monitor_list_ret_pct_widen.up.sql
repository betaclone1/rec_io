-- monitor_list_*.ret_pct NUMERIC(5,1) overflows past ±9,999.9 (cumulative sum of trade ret_pct),
-- which aborted the shared monitor statistics transaction for every monitor. Widen to NUMERIC(10,2).

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
      EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN ret_pct TYPE NUMERIC(10,2)', sch, tbl);
    END LOOP;
  END LOOP;
END $$;
