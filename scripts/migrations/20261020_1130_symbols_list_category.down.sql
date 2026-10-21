DROP TABLE IF EXISTS live_data.commodity_pipeline_health;

ALTER TABLE live_data.symbols_list
  DROP CONSTRAINT IF EXISTS symbols_list_category_check;

ALTER TABLE live_data.symbols_list
  DROP COLUMN IF EXISTS category;
