-- Commodities keep lean market feed (public tape + meta); Upper Tail fires on
-- tape prints. Crypto (BTC/ETH/SOL/XRP) stay full for orderbook touch.

UPDATE live_data.symbols_list
SET live_data_level = 'market'
WHERE UPPER(TRIM(symbol)) IN ('GOLD', 'SILVER', 'WTI');
