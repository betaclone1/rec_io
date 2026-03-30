-- Restore hourly strike ask columns (TEXT), same as strike_table_15m.
-- Post-20260329_2359 hourly strikes live in unified live_data.strike_table_hourly.

ALTER TABLE live_data.strike_table_hourly ADD COLUMN IF NOT EXISTS yes_ask_dollars TEXT;
ALTER TABLE live_data.strike_table_hourly ADD COLUMN IF NOT EXISTS no_ask_dollars TEXT;
