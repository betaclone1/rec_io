-- Reverse 20260501_2200_monitor_list_symbol_wide_columns.up.sql

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
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_cooldown_start_time', sch, ml_tbl);
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_cooldown_duration', sch, ml_tbl);
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_loss_prevention', sch, ml_tbl);
    END LOOP;
  END LOOP;
END
$$;
