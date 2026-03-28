-- Snapshot of strike-table final-window ask min/max/range (4 dp) at trade insert time.

ALTER TABLE users.trades_0001
  ADD COLUMN IF NOT EXISTS yes_ask_min_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS yes_ask_max_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS no_ask_min_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS no_ask_max_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS yes_ask_range_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS no_ask_range_15m NUMERIC(18,4);

ALTER TABLE users.trades_simulated_0001
  ADD COLUMN IF NOT EXISTS yes_ask_min_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS yes_ask_max_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS no_ask_min_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS no_ask_max_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS yes_ask_range_15m NUMERIC(18,4),
  ADD COLUMN IF NOT EXISTS no_ask_range_15m NUMERIC(18,4);
