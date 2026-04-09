-- Durable backtest 1m tables: kalshi_candles_1m_<slug> -> backtest_1m_<slug> (code + docs convention).

DO $$
DECLARE
  r RECORD;
  new_name TEXT;
BEGIN
  FOR r IN
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'backtest'
      AND tablename LIKE 'kalshi_candles_1m_%'
  LOOP
    new_name := replace(r.tablename, 'kalshi_candles_1m_', 'backtest_1m_');
    EXECUTE format('ALTER TABLE backtest.%I RENAME TO %I', r.tablename, new_name);
  END LOOP;
END $$;
