-- Remove weekend_adjustment preference + snapshot from all tenant monitor_list_* tables.
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
        SELECT 1 FROM information_schema.table_constraints tc
        WHERE tc.table_schema = sch
          AND tc.table_name = ml_tbl
          AND tc.constraint_name = ml_tbl || '_weekend_adjustment_chk'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I DROP CONSTRAINT %I',
          sch, ml_tbl, ml_tbl || '_weekend_adjustment_chk'
        );
      END IF;

      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'weekend_adjustment_snapshot'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN weekend_adjustment_snapshot',
          sch, ml_tbl
        );
      END IF;

      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'weekend_adjustment'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN weekend_adjustment',
          sch, ml_tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
