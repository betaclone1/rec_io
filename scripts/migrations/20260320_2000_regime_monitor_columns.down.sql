-- Revert Regime Monitor settings columns

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'users'
      AND table_name LIKE 'monitor_list_%'
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'users'
        AND table_name = tbl
        AND column_name = 'regime_monitor_enabled'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I DROP COLUMN regime_monitor_enabled',
        tbl
      );
    END IF;

    IF EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'users'
        AND table_name = tbl
        AND column_name = 'regime_window'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I DROP COLUMN regime_window',
        tbl
      );
    END IF;
  END LOOP;
END
$$;

