ALTER TABLE live_data.symbols_list
  DROP CONSTRAINT IF EXISTS symbols_list_live_data_level_check;

ALTER TABLE live_data.symbols_list
  DROP COLUMN IF EXISTS live_data_level;

COMMENT ON COLUMN live_data.symbols_list.category IS
  'Live-data pipeline package: crypto (full strike/market/spot) or commodity (market meta + public trades + pyth spot).';
