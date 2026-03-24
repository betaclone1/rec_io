DROP TRIGGER IF EXISTS sync_live_symbol_status_sol_from_price_log ON live_data.live_price_log_1s_sol;
DROP TRIGGER IF EXISTS sync_live_symbol_status_xrp_from_price_log ON live_data.live_price_log_1s_xrp;

-- Keep shared function if BTC/ETH or future symbols use it; remove only if nothing references it.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE NOT t.tgisinternal
          AND n.nspname = 'live_data'
          AND t.tgname IN (
            'sync_live_symbol_status_btc_from_price_log',
            'sync_live_symbol_status_eth_from_price_log',
            'sync_live_symbol_status_sol_from_price_log',
            'sync_live_symbol_status_xrp_from_price_log'
          )
    ) THEN
        DROP FUNCTION IF EXISTS live_data.trg_sync_live_symbol_status_from_price_log();
    END IF;
END $$;
