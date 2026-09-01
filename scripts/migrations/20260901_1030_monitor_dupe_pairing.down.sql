DO $$
DECLARE
  sch text;
  ml_tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR ml_tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^monitor_list_'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'monitor_dupe_pairing'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN monitor_dupe_pairing',
          sch, ml_tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
