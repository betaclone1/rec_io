-- Restore pre-promotion feed depth: SOL/XRP/GOLD/SILVER/WTI were market.
-- BTC/ETH remain full; DOGE remains none (untouched by the up migration).

UPDATE live_data.symbols_list
SET live_data_level = 'market'
WHERE UPPER(TRIM(symbol)) IN ('SOL', 'XRP', 'GOLD', 'SILVER', 'WTI');
