-- Roll back only legacy split hourly market tables if they still exist (2359 drops them on upgrade).
-- Unified strike_table_hourly / market_kalshi_hourly are not reverted here (would undo 2359/1000 invariants).

DO $d$
BEGIN
  IF to_regclass('live_data.market_kalshi_hourly_btc') IS NOT NULL THEN
    DROP INDEX IF EXISTS live_data.market_kalshi_hourly_btc_exchange_symbol_idx;
    DROP INDEX IF EXISTS live_data.market_kalshi_hourly_btc_exchange_symbol_event_idx;
    ALTER TABLE live_data.market_kalshi_hourly_btc DROP CONSTRAINT IF EXISTS market_kalshi_hourly_btc_ex_sym_evt_mkt_uniq;
    ALTER TABLE live_data.market_kalshi_hourly_btc
        ADD CONSTRAINT market_kalshi_hourly_btc_event_market_unique UNIQUE (event_ticker, market_ticker);
    ALTER TABLE live_data.market_kalshi_hourly_btc DROP COLUMN IF EXISTS symbol;
    ALTER TABLE live_data.market_kalshi_hourly_btc DROP COLUMN IF EXISTS exchange;
  END IF;
  IF to_regclass('live_data.market_kalshi_hourly_eth') IS NOT NULL THEN
    DROP INDEX IF EXISTS live_data.market_kalshi_hourly_eth_exchange_symbol_idx;
    DROP INDEX IF EXISTS live_data.market_kalshi_hourly_eth_exchange_symbol_event_idx;
    ALTER TABLE live_data.market_kalshi_hourly_eth DROP CONSTRAINT IF EXISTS market_kalshi_hourly_eth_ex_sym_evt_mkt_uniq;
    ALTER TABLE live_data.market_kalshi_hourly_eth
        ADD CONSTRAINT market_kalshi_hourly_eth_event_market_unique UNIQUE (event_ticker, market_ticker);
    ALTER TABLE live_data.market_kalshi_hourly_eth DROP COLUMN IF EXISTS symbol;
    ALTER TABLE live_data.market_kalshi_hourly_eth DROP COLUMN IF EXISTS exchange;
  END IF;
END $d$;
