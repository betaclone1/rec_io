-- Symbol-wide loss prevention columns on tenant monitor_list_* (required by GET /api/monitors payload).
-- Previously only in init_database() loops; existing prod DBs never received ALTER. Idempotent.

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
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'symbol_wide_loss_prevention'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN symbol_wide_loss_prevention BOOLEAN DEFAULT FALSE',
          sch, ml_tbl
        );
        EXECUTE format(
          'UPDATE %I.%I SET symbol_wide_loss_prevention = FALSE WHERE symbol_wide_loss_prevention IS NULL',
          sch, ml_tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'symbol_wide_cooldown_duration'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN symbol_wide_cooldown_duration INTEGER DEFAULT 4',
          sch, ml_tbl
        );
        EXECUTE format(
          'UPDATE %I.%I SET symbol_wide_cooldown_duration = 4 WHERE symbol_wide_cooldown_duration IS NULL',
          sch, ml_tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'symbol_wide_cooldown_start_time'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN symbol_wide_cooldown_start_time TIMESTAMPTZ',
          sch, ml_tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
