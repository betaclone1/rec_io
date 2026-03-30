-- Align live_data.market_kalshi_hourly_* and live_data.strike_table_hourly_* with unified 15m schemas:
-- market: add symbol + exchange, unique (exchange, symbol, event_ticker, market_ticker), same indexes as market_kalshi_15m.
-- strike: broker -> exchange, strike INTEGER -> NUMERIC(18,5), same exchange/symbol indexes as strike_table_15m.

-- ========== market_kalshi_hourly_btc ==========
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

-- ========== market_kalshi_hourly_eth ==========
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

-- ========== strike_table_hourly_btc ==========
ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS exchange VARCHAR(20);
DO $btc_ex$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc' AND column_name = 'broker'
  ) THEN
    EXECUTE 'UPDATE live_data.strike_table_hourly_btc SET exchange = LOWER(TRIM(broker::text)) WHERE exchange IS NULL AND broker IS NOT NULL';
  END IF;
END $btc_ex$;
UPDATE live_data.strike_table_hourly_btc SET exchange = 'kalshi' WHERE exchange IS NULL OR TRIM(exchange::text) = '';
ALTER TABLE live_data.strike_table_hourly_btc ALTER COLUMN exchange SET NOT NULL;
ALTER TABLE live_data.strike_table_hourly_btc ALTER COLUMN exchange SET DEFAULT 'kalshi';
UPDATE live_data.strike_table_hourly_btc SET symbol = 'BTC' WHERE symbol IS NULL OR TRIM(symbol::text) = '';
ALTER TABLE live_data.strike_table_hourly_btc ALTER COLUMN symbol SET NOT NULL;

DO $btc_br$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_btc' AND column_name = 'broker'
  ) THEN
    EXECUTE 'ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN broker';
  END IF;
END $btc_br$;

ALTER TABLE live_data.strike_table_hourly_btc
    ALTER COLUMN strike TYPE NUMERIC(18,5) USING strike::numeric;

DROP INDEX IF EXISTS live_data.strike_table_btc_strike_unique;

CREATE INDEX IF NOT EXISTS strike_table_hourly_btc_exchange_symbol_idx
    ON live_data.strike_table_hourly_btc (exchange, symbol);
CREATE INDEX IF NOT EXISTS strike_table_hourly_btc_exchange_symbol_timestamp_idx
    ON live_data.strike_table_hourly_btc (exchange, symbol, timestamp DESC);

-- ========== strike_table_hourly_eth ==========
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS exchange VARCHAR(20);
DO $eth_ex$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth' AND column_name = 'broker'
  ) THEN
    EXECUTE 'UPDATE live_data.strike_table_hourly_eth SET exchange = LOWER(TRIM(broker::text)) WHERE exchange IS NULL AND broker IS NOT NULL';
  END IF;
END $eth_ex$;
UPDATE live_data.strike_table_hourly_eth SET exchange = 'kalshi' WHERE exchange IS NULL OR TRIM(exchange::text) = '';
ALTER TABLE live_data.strike_table_hourly_eth ALTER COLUMN exchange SET NOT NULL;
ALTER TABLE live_data.strike_table_hourly_eth ALTER COLUMN exchange SET DEFAULT 'kalshi';
UPDATE live_data.strike_table_hourly_eth SET symbol = 'ETH' WHERE symbol IS NULL OR TRIM(symbol::text) = '';
ALTER TABLE live_data.strike_table_hourly_eth ALTER COLUMN symbol SET NOT NULL;

DO $eth_br$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'live_data' AND table_name = 'strike_table_hourly_eth' AND column_name = 'broker'
  ) THEN
    EXECUTE 'ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN broker';
  END IF;
END $eth_br$;

ALTER TABLE live_data.strike_table_hourly_eth
    ALTER COLUMN strike TYPE NUMERIC(18,5) USING strike::numeric;

DROP INDEX IF EXISTS live_data.strike_table_eth_strike_unique;

CREATE INDEX IF NOT EXISTS strike_table_hourly_eth_exchange_symbol_idx
    ON live_data.strike_table_hourly_eth (exchange, symbol);
CREATE INDEX IF NOT EXISTS strike_table_hourly_eth_exchange_symbol_timestamp_idx
    ON live_data.strike_table_hourly_eth (exchange, symbol, timestamp DESC);
