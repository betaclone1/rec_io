ALTER TABLE users.trade_history_preferences_0001
  DROP COLUMN IF EXISTS include_test_trades;

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
        AND column_name = 'test_filter'
    ) THEN
      EXECUTE format('ALTER TABLE users.%I DROP COLUMN test_filter', tbl);
    END IF;
  END LOOP;
END
$$;
