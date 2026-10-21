DELETE FROM live_data.symbols_list
WHERE UPPER(TRIM(symbol)) IN ('GOLD', 'SILVER', 'WTI');
