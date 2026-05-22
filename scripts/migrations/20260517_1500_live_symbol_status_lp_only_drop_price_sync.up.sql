-- live_symbol_status is symbol-wide LP / cooldown state only.
-- Stop mirroring live_price_log_1s_* ticks into this table (tradeflow reads live_state Redis).

DROP TRIGGER IF EXISTS sync_live_symbol_status_btc_from_price_log ON live_data.live_price_log_1s_btc;
DROP TRIGGER IF EXISTS sync_live_symbol_status_eth_from_price_log ON live_data.live_price_log_1s_eth;
DROP TRIGGER IF EXISTS sync_live_symbol_status_sol_from_price_log ON live_data.live_price_log_1s_sol;
DROP TRIGGER IF EXISTS sync_live_symbol_status_xrp_from_price_log ON live_data.live_price_log_1s_xrp;

DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_from_price_log();
DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_btc();
DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_eth();
DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_sol();
DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_xrp();

COMMENT ON TABLE live_data.live_symbol_status IS
  'Per-symbol loss-prevention hub (monitor_follow, LP state, cooldown anchors). '
  'Tick metrics are in live_state Redis / live_price_log_1s_*; not mirrored here.';
