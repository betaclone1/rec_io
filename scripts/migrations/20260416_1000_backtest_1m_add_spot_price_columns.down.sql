-- Remove spot_* columns from backtest.backtest_1m_* (reverse of up migration).

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
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_open;', r.tablename);
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_high;', r.tablename);
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_low;', r.tablename);
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_close;', r.tablename);
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_volume;', r.tablename);
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_momentum;', r.tablename);
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_momentum_percentile;',
      r.tablename
    );
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_volatility;', r.tablename);
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_volatility_percentile;',
      r.tablename
    );
    EXECUTE format('ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_movement;', r.tablename);
    EXECUTE format(
      'ALTER TABLE backtest.%I DROP COLUMN IF EXISTS spot_movement_percentile;',
      r.tablename
    );
  END LOOP;
END $$;
