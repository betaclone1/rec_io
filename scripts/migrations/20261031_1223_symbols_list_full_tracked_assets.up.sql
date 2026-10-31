-- Promote all actively tracked 15m assets to live_data_level=full so Kalshi
-- orderbook WS matches BTC/ETH. DOGE stays none (not tracked).
-- Commodity full keeps lean commodity_pipeline_health (see strike_pipeline_health);
-- market WS adds orderbook when level is not market/lean.

UPDATE live_data.symbols_list
SET live_data_level = 'full'
WHERE UPPER(TRIM(symbol)) IN ('SOL', 'XRP', 'GOLD', 'SILVER', 'WTI');
