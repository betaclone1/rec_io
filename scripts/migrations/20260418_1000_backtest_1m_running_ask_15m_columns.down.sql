-- Remove running ask 15m columns from backtest.backtest_1m_*.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'backtest'
      AND tablename LIKE 'backtest_1m_%'
  LOOP
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS yes_ask_min_15m;',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS yes_ask_max_15m;',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS no_ask_min_15m;',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS no_ask_max_15m;',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS yes_ask_range_15m;',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS no_ask_range_15m;',
      r.tablename
    );
  END LOOP;
END $$;
