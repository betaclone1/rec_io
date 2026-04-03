-- Persist why monitor_confirmed is false (and avoid guessing after pool row is gone).
ALTER TABLE users.trades_0001
  ADD COLUMN IF NOT EXISTS monitor_confirm_detail TEXT;

COMMENT ON COLUMN users.trades_0001.monitor_confirm_detail IS
  'When monitor_confirmed is false: stable reason code (e.g. flat_high_low, no_pool_row, pool_stale_at_close|lag_s=...). NULL when true or unknown legacy row.';

ALTER TABLE users.trades_simulated_0001
  ADD COLUMN IF NOT EXISTS monitor_confirm_detail TEXT;
