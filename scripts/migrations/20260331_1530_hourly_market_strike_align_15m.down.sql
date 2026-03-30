-- Best-effort rollback: restores broker on strike tables and old market unique keys.
-- Does not remove symbol/exchange from market tables (data retained).

DROP INDEX IF EXISTS live_data.strike_table_hourly_btc_exchange_symbol_timestamp_idx;
DROP INDEX IF EXISTS live_data.strike_table_hourly_btc_exchange_symbol_idx;
DROP INDEX IF EXISTS live_data.strike_table_hourly_eth_exchange_symbol_timestamp_idx;
DROP INDEX IF EXISTS live_data.strike_table_hourly_eth_exchange_symbol_idx;

ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS broker VARCHAR(20);
UPDATE live_data.strike_table_hourly_btc SET broker = INITCAP(exchange::text) WHERE broker IS NULL;
ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS exchange;

ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS broker VARCHAR(20);
UPDATE live_data.strike_table_hourly_eth SET broker = INITCAP(exchange::text) WHERE broker IS NULL;
ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS exchange;

-- strike type rollback (may truncate fractional strikes)
ALTER TABLE live_data.strike_table_hourly_btc
    ALTER COLUMN strike TYPE INTEGER USING round(strike)::integer;
ALTER TABLE live_data.strike_table_hourly_eth
    ALTER COLUMN strike TYPE INTEGER USING round(strike)::integer;

ALTER TABLE live_data.strike_table_hourly_btc ALTER COLUMN symbol DROP NOT NULL;
ALTER TABLE live_data.strike_table_hourly_eth ALTER COLUMN symbol DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS strike_table_btc_strike_unique
    ON live_data.strike_table_hourly_btc (strike);
CREATE UNIQUE INDEX IF NOT EXISTS strike_table_eth_strike_unique
    ON live_data.strike_table_hourly_eth (strike);

ALTER TABLE live_data.market_kalshi_hourly_btc DROP CONSTRAINT IF EXISTS market_kalshi_hourly_btc_ex_sym_evt_mkt_uniq;
ALTER TABLE live_data.market_kalshi_hourly_eth DROP CONSTRAINT IF EXISTS market_kalshi_hourly_eth_ex_sym_evt_mkt_uniq;

DROP INDEX IF EXISTS live_data.market_kalshi_hourly_btc_exchange_symbol_idx;
DROP INDEX IF EXISTS live_data.market_kalshi_hourly_btc_exchange_symbol_event_idx;
DROP INDEX IF EXISTS live_data.market_kalshi_hourly_eth_exchange_symbol_idx;
DROP INDEX IF EXISTS live_data.market_kalshi_hourly_eth_exchange_symbol_event_idx;

ALTER TABLE live_data.market_kalshi_hourly_btc
    ADD CONSTRAINT market_kalshi_hourly_btc_event_market_unique UNIQUE (event_ticker, market_ticker);
ALTER TABLE live_data.market_kalshi_hourly_eth
    ADD CONSTRAINT market_kalshi_hourly_eth_event_market_unique UNIQUE (event_ticker, market_ticker);

ALTER TABLE live_data.market_kalshi_hourly_btc DROP COLUMN IF EXISTS symbol;
ALTER TABLE live_data.market_kalshi_hourly_btc DROP COLUMN IF EXISTS exchange;
ALTER TABLE live_data.market_kalshi_hourly_eth DROP COLUMN IF EXISTS symbol;
ALTER TABLE live_data.market_kalshi_hourly_eth DROP COLUMN IF EXISTS exchange;
