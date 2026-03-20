-- Revert the live price feed hygiene trigger flow.

DROP TRIGGER IF EXISTS sync_live_symbol_status_btc_from_price_log ON live_data.live_price_log_1s_btc;
DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_btc();

DROP TRIGGER IF EXISTS sync_live_symbol_status_eth_from_price_log ON live_data.live_price_log_1s_eth;
DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_eth();

DROP INDEX IF EXISTS live_symbol_status_symbol_uniq;

