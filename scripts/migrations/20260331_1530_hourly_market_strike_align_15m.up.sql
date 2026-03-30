-- Originally aligned split tables market_kalshi_hourly_{btc,eth} / strike_table_hourly_{btc,eth}.
-- 20260329_2359 merged those into market_kalshi_hourly and strike_table_hourly;
-- 20260330_1000 realigned shapes to match 15m (indexes: strike_table_hourly_exchange_symbol_*, etc.).
-- Remaining steps: optional legacy split-market DDL if those tables still exist, plus idempotent unified strike tweaks.

-- ========== Legacy split market tables (only if still present) ==========
DO $mkb$
BEGIN
  IF to_regclass('live_data.market_kalshi_hourly_btc') IS NOT NULL THEN
    ALTER TABLE live_data.market_kalshi_hourly_btc ADD COLUMN IF NOT EXISTS symbol VARCHAR(10);
    ALTER TABLE live_data.market_kalshi_hourly_btc ADD COLUMN IF NOT EXISTS exchange VARCHAR(20);
    UPDATE live_data.market_kalshi_hourly_btc SET symbol = 'BTC' WHERE symbol IS NULL;
    UPDATE live_data.market_kalshi_hourly_btc SET exchange = 'kalshi' WHERE exchange IS NULL;
    ALTER TABLE live_data.market_kalshi_hourly_btc ALTER COLUMN symbol SET NOT NULL;
    ALTER TABLE live_data.market_kalshi_hourly_btc ALTER COLUMN exchange SET NOT NULL;
    ALTER TABLE live_data.market_kalshi_hourly_btc ALTER COLUMN symbol SET DEFAULT 'BTC';
    ALTER TABLE live_data.market_kalshi_hourly_btc ALTER COLUMN exchange SET DEFAULT 'kalshi';
    DELETE FROM live_data.market_kalshi_hourly_btc a
    USING live_data.market_kalshi_hourly_btc b
    WHERE a.id > b.id
      AND a.exchange IS NOT DISTINCT FROM b.exchange
      AND a.symbol IS NOT DISTINCT FROM b.symbol
      AND a.event_ticker IS NOT DISTINCT FROM b.event_ticker
      AND a.market_ticker IS NOT DISTINCT FROM b.market_ticker;
    ALTER TABLE live_data.market_kalshi_hourly_btc DROP CONSTRAINT IF EXISTS market_kalshi_hourly_btc_event_market_unique;
    ALTER TABLE live_data.market_kalshi_hourly_btc
        ADD CONSTRAINT market_kalshi_hourly_btc_ex_sym_evt_mkt_uniq
        UNIQUE (exchange, symbol, event_ticker, market_ticker);
    CREATE INDEX IF NOT EXISTS market_kalshi_hourly_btc_exchange_symbol_idx
        ON live_data.market_kalshi_hourly_btc (exchange, symbol);
    CREATE INDEX IF NOT EXISTS market_kalshi_hourly_btc_exchange_symbol_event_idx
        ON live_data.market_kalshi_hourly_btc (exchange, symbol, event_ticker);
  END IF;
END $mkb$;

DO $mke$
BEGIN
  IF to_regclass('live_data.market_kalshi_hourly_eth') IS NOT NULL THEN
    ALTER TABLE live_data.market_kalshi_hourly_eth ADD COLUMN IF NOT EXISTS symbol VARCHAR(10);
    ALTER TABLE live_data.market_kalshi_hourly_eth ADD COLUMN IF NOT EXISTS exchange VARCHAR(20);
    UPDATE live_data.market_kalshi_hourly_eth SET symbol = 'ETH' WHERE symbol IS NULL;
    UPDATE live_data.market_kalshi_hourly_eth SET exchange = 'kalshi' WHERE exchange IS NULL;
    ALTER TABLE live_data.market_kalshi_hourly_eth ALTER COLUMN symbol SET NOT NULL;
    ALTER TABLE live_data.market_kalshi_hourly_eth ALTER COLUMN exchange SET NOT NULL;
    ALTER TABLE live_data.market_kalshi_hourly_eth ALTER COLUMN symbol SET DEFAULT 'ETH';
    ALTER TABLE live_data.market_kalshi_hourly_eth ALTER COLUMN exchange SET DEFAULT 'kalshi';
    DELETE FROM live_data.market_kalshi_hourly_eth a
    USING live_data.market_kalshi_hourly_eth b
    WHERE a.id > b.id
      AND a.exchange IS NOT DISTINCT FROM b.exchange
      AND a.symbol IS NOT DISTINCT FROM b.symbol
      AND a.event_ticker IS NOT DISTINCT FROM b.event_ticker
      AND a.market_ticker IS NOT DISTINCT FROM b.market_ticker;
    ALTER TABLE live_data.market_kalshi_hourly_eth DROP CONSTRAINT IF EXISTS market_kalshi_hourly_eth_event_market_unique;
    ALTER TABLE live_data.market_kalshi_hourly_eth
        ADD CONSTRAINT market_kalshi_hourly_eth_ex_sym_evt_mkt_uniq
        UNIQUE (exchange, symbol, event_ticker, market_ticker);
    CREATE INDEX IF NOT EXISTS market_kalshi_hourly_eth_exchange_symbol_idx
        ON live_data.market_kalshi_hourly_eth (exchange, symbol);
    CREATE INDEX IF NOT EXISTS market_kalshi_hourly_eth_exchange_symbol_event_idx
        ON live_data.market_kalshi_hourly_eth (exchange, symbol, event_ticker);
  END IF;
END $mke$;

-- ========== Unified hourly strike (must exist after 20260329_2359) ==========
ALTER TABLE live_data.strike_table_hourly ADD COLUMN IF NOT EXISTS exchange VARCHAR(20);

DO $btc_ex$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly' AND column_name = 'broker'
  ) THEN
    EXECUTE 'UPDATE live_data.strike_table_hourly SET exchange = LOWER(TRIM(broker::text)) WHERE exchange IS NULL AND broker IS NOT NULL';
  END IF;
END $btc_ex$;

UPDATE live_data.strike_table_hourly SET exchange = 'kalshi' WHERE exchange IS NULL OR TRIM(exchange::text) = '';
ALTER TABLE live_data.strike_table_hourly ALTER COLUMN exchange SET NOT NULL;
ALTER TABLE live_data.strike_table_hourly ALTER COLUMN exchange SET DEFAULT 'kalshi';

DO $btc_br$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly' AND column_name = 'broker'
  ) THEN
    EXECUTE 'ALTER TABLE live_data.strike_table_hourly DROP COLUMN broker';
  END IF;
END $btc_br$;

ALTER TABLE live_data.strike_table_hourly
    ALTER COLUMN strike TYPE NUMERIC(18,5) USING strike::numeric;

DROP INDEX IF EXISTS live_data.strike_table_btc_strike_unique;
DROP INDEX IF EXISTS live_data.strike_table_eth_strike_unique;
