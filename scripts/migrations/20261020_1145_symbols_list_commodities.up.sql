-- Register Kalshi commodity 15m symbols (lean package: market + public trades + pyth).
-- category=commodity selects commodity_pipeline_health (not full strike crypto package).

INSERT INTO live_data.symbols_list (symbol, date_added, category)
SELECT 'GOLD', CURRENT_TIMESTAMP, 'commodity'
WHERE NOT EXISTS (
  SELECT 1 FROM live_data.symbols_list WHERE UPPER(TRIM(symbol)) = 'GOLD'
);

INSERT INTO live_data.symbols_list (symbol, date_added, category)
SELECT 'SILVER', CURRENT_TIMESTAMP, 'commodity'
WHERE NOT EXISTS (
  SELECT 1 FROM live_data.symbols_list WHERE UPPER(TRIM(symbol)) = 'SILVER'
);

INSERT INTO live_data.symbols_list (symbol, date_added, category)
SELECT 'WTI', CURRENT_TIMESTAMP, 'commodity'
WHERE NOT EXISTS (
  SELECT 1 FROM live_data.symbols_list WHERE UPPER(TRIM(symbol)) = 'WTI'
);

-- If rows already existed without category commodity, force lean package.
UPDATE live_data.symbols_list
SET category = 'commodity'
WHERE UPPER(TRIM(symbol)) IN ('GOLD', 'SILVER', 'WTI');
