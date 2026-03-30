-- Hourly strike INSERT expects momentum_percentile (aligned with 15m strike tables).
-- Post-20260329_2359: unified live_data.strike_table_hourly.

ALTER TABLE live_data.strike_table_hourly ADD COLUMN IF NOT EXISTS momentum_percentile NUMERIC(5,1);
