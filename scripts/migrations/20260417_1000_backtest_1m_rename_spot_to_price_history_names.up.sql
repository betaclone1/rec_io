-- Rename spot_* columns on backtest.backtest_1m_* to match historical_data.*_price_history (open, high, …).

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
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_open'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_open TO %I;', r.tablename, 'open');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_high'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_high TO %I;', r.tablename, 'high');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_low'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_low TO %I;', r.tablename, 'low');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_close'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_close TO %I;', r.tablename, 'close');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_volume'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_volume TO %I;', r.tablename, 'volume');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_momentum'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_momentum TO %I;', r.tablename, 'momentum');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest'
        AND table_name = r.tablename
        AND column_name = 'spot_momentum_percentile'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN spot_momentum_percentile TO %I;',
        r.tablename,
        'momentum_percentile'
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_volatility'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_volatility TO %I;', r.tablename, 'volatility');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest'
        AND table_name = r.tablename
        AND column_name = 'spot_volatility_percentile'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN spot_volatility_percentile TO %I;',
        r.tablename,
        'volatility_percentile'
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'spot_movement'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN spot_movement TO %I;', r.tablename, 'movement');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest'
        AND table_name = r.tablename
        AND column_name = 'spot_movement_percentile'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN spot_movement_percentile TO %I;',
        r.tablename,
        'movement_percentile'
      );
    END IF;
  END LOOP;
END $$;
