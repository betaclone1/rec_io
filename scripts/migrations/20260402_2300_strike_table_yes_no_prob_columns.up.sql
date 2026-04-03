-- Literal YES/NO lookup legs per strike row (prob_within_positive / prob_within_negative), alongside legacy probability_* scalars.
ALTER TABLE live_data.strike_table_15m
    ADD COLUMN IF NOT EXISTS yes_prob_hourly DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS no_prob_hourly DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS yes_prob_15m DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS no_prob_15m DECIMAL(5,2);

ALTER TABLE live_data.strike_table_hourly
    ADD COLUMN IF NOT EXISTS yes_prob_hourly DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS no_prob_hourly DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS yes_prob_15m DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS no_prob_15m DECIMAL(5,2);

COMMENT ON COLUMN live_data.strike_table_15m.yes_prob_hourly IS
    'Lookup prob_within_positive (hourly TTC); NULL on 15m-only rows.';
COMMENT ON COLUMN live_data.strike_table_15m.no_prob_hourly IS
    'Lookup prob_within_negative (hourly TTC); NULL on 15m-only rows.';
COMMENT ON COLUMN live_data.strike_table_15m.yes_prob_15m IS
    'Lookup prob_within_positive for 15m TTC.';
COMMENT ON COLUMN live_data.strike_table_15m.no_prob_15m IS
    'Lookup prob_within_negative for 15m TTC.';
