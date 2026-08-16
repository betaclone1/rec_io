-- Expiration Scalp: entry verification defaults (enabled, 3s).
-- Reuses monitor_list.verification_period_* (HTC still uses these for auto-stop dwell).
-- AES entry dwell only applies when strategy = Expiration Scalp.

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
        AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'verification_period_enabled'
      ) AND EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'verification_period_seconds'
      ) THEN
        EXECUTE format(
          'UPDATE %I.%I
           SET verification_period_enabled = TRUE,
               verification_period_seconds = 3
           WHERE name = %L',
          sch, tbl, 'Expiration Scalp'
        );
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'verification_period_enabled'
      ) AND EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'verification_period_seconds'
      ) THEN
        EXECUTE format(
          'UPDATE %I.%I
           SET verification_period_enabled = TRUE,
               verification_period_seconds = 3
           WHERE strategy = %L',
          sch, tbl, 'Expiration Scalp'
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
