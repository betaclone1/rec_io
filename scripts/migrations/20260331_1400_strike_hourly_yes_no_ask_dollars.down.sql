ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS yes_ask_dollars;
ALTER TABLE live_data.strike_table_hourly_btc DROP COLUMN IF EXISTS no_ask_dollars;

ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS yes_ask_dollars;
ALTER TABLE live_data.strike_table_hourly_eth DROP COLUMN IF EXISTS no_ask_dollars;
