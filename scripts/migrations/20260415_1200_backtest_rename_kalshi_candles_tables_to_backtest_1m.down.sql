-- Reverse: backtest_1m_<slug> -> kalshi_candles_1m_<slug>

DO $$
DECLARE
  r RECORD;
  new_name TEXT;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'backtest'
      AND tablename LIKE 'backtest_1m_%'
  LOOP
    new_name := replace(r.tablename, 'backtest_1m_', 'kalshi_candles_1m_');
    EXECUTE format('ALTER TABLE backtest.%I RENAME TO %I', r.tablename, new_name);
  END LOOP;
END $$;
