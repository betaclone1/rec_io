-- test_filter on all monitor_list_* (trades from monitor inherit flag via trade_manager).
-- include_test_trades on trade history preferences (UI: TEST checkbox).

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
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'users'
        AND table_name = tbl
        AND column_name = 'test_filter'
    ) THEN
      EXECUTE format(
        'ALTER TABLE users.%I ADD COLUMN test_filter BOOLEAN DEFAULT FALSE',
        tbl
      );
      EXECUTE format(
        'UPDATE users.%I SET test_filter = FALSE WHERE test_filter IS NULL',
        tbl
      );
    END IF;
  END LOOP;
END
$$;

ALTER TABLE users.trade_history_preferences_0001
  ADD COLUMN IF NOT EXISTS include_test_trades BOOLEAN DEFAULT FALSE;

UPDATE users.trade_history_preferences_0001
SET include_test_trades = FALSE
WHERE include_test_trades IS NULL;
