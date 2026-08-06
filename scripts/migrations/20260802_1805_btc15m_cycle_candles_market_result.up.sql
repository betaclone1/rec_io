-- Add Kalshi market_result (YES/NO/…) and widen pct columns so one bad
-- timeseries spike cannot abort the whole historical backfill.

ALTER TABLE historical_data.btc15m_cycle_candles
  ADD COLUMN IF NOT EXISTS market_result TEXT;

ALTER TABLE historical_data.btc15m_cycle_candles
  ALTER COLUMN total_range_pct TYPE NUMERIC(18, 8),
  ALTER COLUMN final_diff_pct TYPE NUMERIC(18, 8);

COMMENT ON COLUMN historical_data.btc15m_cycle_candles.market_result IS
  'Kalshi market settlement result from market.result / market_result (e.g. yes, no); NULL until settled.';

COMMENT ON COLUMN historical_data.btc15m_cycle_candles.total_range_pct IS
  '(high_price - low_price) / floor_strike * 100';

COMMENT ON COLUMN historical_data.btc15m_cycle_candles.final_diff_pct IS
  '(close - floor_strike) / floor_strike * 100';
