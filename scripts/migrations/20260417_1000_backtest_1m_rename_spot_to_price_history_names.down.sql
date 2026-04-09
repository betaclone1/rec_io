-- Reverse: price_history column names -> spot_* (matches 20260416 naming).

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
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'open'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_open;', r.tablename, 'open');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'high'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_high;', r.tablename, 'high');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'low'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_low;', r.tablename, 'low');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'close'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_close;', r.tablename, 'close');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'volume'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_volume;', r.tablename, 'volume');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'momentum'
    ) THEN
      EXECUTE format('ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_momentum;', r.tablename, 'momentum');
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest'
        AND table_name = r.tablename
        AND column_name = 'momentum_percentile'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_momentum_percentile;',
        r.tablename,
        'momentum_percentile'
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'volatility'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_volatility;',
        r.tablename,
        'volatility'
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest'
        AND table_name = r.tablename
        AND column_name = 'volatility_percentile'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_volatility_percentile;',
        r.tablename,
        'volatility_percentile'
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'movement'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_movement;',
        r.tablename,
        'movement'
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest'
        AND table_name = r.tablename
        AND column_name = 'movement_percentile'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN %I TO spot_movement_percentile;',
        r.tablename,
        'movement_percentile'
      );
    END IF;
  END LOOP;
END $$;
