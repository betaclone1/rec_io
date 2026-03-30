-- Hourly strike INSERT expects momentum_percentile (aligned with live_price_log / 15m strike tables).

ALTER TABLE live_data.strike_table_hourly_btc ADD COLUMN IF NOT EXISTS momentum_percentile NUMERIC(5,1);
ALTER TABLE live_data.strike_table_hourly_eth ADD COLUMN IF NOT EXISTS momentum_percentile NUMERIC(5,1);
