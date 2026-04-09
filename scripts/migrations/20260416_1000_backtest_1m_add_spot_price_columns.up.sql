-- Add spot_* columns (historical_data btc/eth price_history join) to existing backtest.backtest_1m_* tables.

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
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_open NUMERIC(20, 8);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_high NUMERIC(20, 8);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_low NUMERIC(20, 8);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_close NUMERIC(20, 8);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_volume NUMERIC(20, 8);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_momentum NUMERIC(10, 4);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_momentum_percentile NUMERIC(5, 1);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_volatility NUMERIC(15, 6);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_volatility_percentile NUMERIC(5, 1);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_movement NUMERIC(10, 4);',
      r.tablename
    );
    EXECUTE format(
      'ALTER TABLE backtest.%I ADD COLUMN IF NOT EXISTS spot_movement_percentile NUMERIC(5, 1);',
      r.tablename
    );
  END LOOP;
END $$;
