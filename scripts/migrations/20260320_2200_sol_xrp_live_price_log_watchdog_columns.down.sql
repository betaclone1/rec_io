ALTER TABLE live_data.live_price_log_1s_sol
  DROP COLUMN IF EXISTS volatility_percentile,
  DROP COLUMN IF EXISTS volatility,
  DROP COLUMN IF EXISTS momentum_30s_avg,
  DROP COLUMN IF EXISTS momentum_5s_avg,
  DROP COLUMN IF EXISTS momentum_percentile;

ALTER TABLE live_data.live_price_log_1s_xrp
  DROP COLUMN IF EXISTS volatility_percentile,
  DROP COLUMN IF EXISTS volatility,
  DROP COLUMN IF EXISTS momentum_30s_avg,
  DROP COLUMN IF EXISTS momentum_5s_avg,
  DROP COLUMN IF EXISTS momentum_percentile;
