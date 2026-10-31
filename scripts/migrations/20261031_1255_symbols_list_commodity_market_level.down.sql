-- Restore commodity full orderbook membership from 20261031_1223.

UPDATE live_data.symbols_list
SET live_data_level = 'full'
WHERE UPPER(TRIM(symbol)) IN ('GOLD', 'SILVER', 'WTI');
