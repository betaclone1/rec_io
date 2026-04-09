-- Cumulative contract-window YES/NO ask min/max/range (strike-table names) on backtest.backtest_1m_*.

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
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS yes_ask_min_15m NUMERIC(20, 6);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS yes_ask_max_15m NUMERIC(20, 6);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS no_ask_min_15m NUMERIC(20, 6);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS no_ask_max_15m NUMERIC(20, 6);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS yes_ask_range_15m NUMERIC(20, 6);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS no_ask_range_15m NUMERIC(20, 6);',
      r.tablename
    );
  END LOOP;
END $$;
