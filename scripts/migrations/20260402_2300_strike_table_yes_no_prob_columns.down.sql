ALTER TABLE live_data.strike_table_15m
    DROP COLUMN IF EXISTS yes_prob_hourly,
    DROP COLUMN IF EXISTS no_prob_hourly,
    DROP COLUMN IF EXISTS yes_prob_15m,
    DROP COLUMN IF EXISTS no_prob_15m;

ALTER TABLE live_data.strike_table_hourly
    DROP COLUMN IF EXISTS yes_prob_hourly,
    DROP COLUMN IF EXISTS no_prob_hourly,
    DROP COLUMN IF EXISTS yes_prob_15m,
    DROP COLUMN IF EXISTS no_prob_15m;
