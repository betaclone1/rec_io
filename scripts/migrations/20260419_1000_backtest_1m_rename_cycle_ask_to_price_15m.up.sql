-- Backtest cumulative-window columns: YES/NO **trade price** extrema (rename from ask-based names).

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
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'yes_ask_min_15m'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'yes_price_min_15m'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN yes_ask_min_15m TO yes_price_min_15m;',
        r.tablename
      );
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'yes_ask_max_15m'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'yes_price_max_15m'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN yes_ask_max_15m TO yes_price_max_15m;',
        r.tablename
      );
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'no_ask_min_15m'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'no_price_min_15m'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN no_ask_min_15m TO no_price_min_15m;',
        r.tablename
      );
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'no_ask_max_15m'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'no_price_max_15m'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN no_ask_max_15m TO no_price_max_15m;',
        r.tablename
      );
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'yes_ask_range_15m'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'yes_price_range_15m'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN yes_ask_range_15m TO yes_price_range_15m;',
        r.tablename
      );
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'no_ask_range_15m'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'backtest' AND table_name = r.tablename AND column_name = 'no_price_range_15m'
    ) THEN
      EXECUTE format(
        'ALTER TABLE backtest.%I RENAME COLUMN no_ask_range_15m TO no_price_range_15m;',
        r.tablename
      );
    END IF;
  END LOOP;
END $$;
