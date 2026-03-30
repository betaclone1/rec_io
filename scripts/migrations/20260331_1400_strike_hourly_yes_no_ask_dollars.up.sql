-- Restore hourly strike ask columns dropped by 20260329_1500 without replacing them.
-- Generator INSERT requires yes_ask_dollars / no_ask_dollars (TEXT), same as strike_table_15m.

ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS yes_ask_dollars TEXT;
ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS no_ask_dollars TEXT;

ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS yes_ask_dollars TEXT;
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS no_ask_dollars TEXT;
