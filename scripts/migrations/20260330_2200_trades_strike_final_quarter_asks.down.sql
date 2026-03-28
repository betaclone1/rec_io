ALTER TABLE users.trades_0001
  DROP COLUMN IF EXISTS yes_ask_min_15m,
  DROP COLUMN IF EXISTS yes_ask_max_15m,
  DROP COLUMN IF EXISTS no_ask_min_15m,
  DROP COLUMN IF EXISTS no_ask_max_15m,
  DROP COLUMN IF EXISTS yes_ask_range_15m,
  DROP COLUMN IF EXISTS no_ask_range_15m;

ALTER TABLE users.trades_simulated_0001
  DROP COLUMN IF EXISTS yes_ask_min_15m,
  DROP COLUMN IF EXISTS yes_ask_max_15m,
  DROP COLUMN IF EXISTS no_ask_min_15m,
  DROP COLUMN IF EXISTS no_ask_max_15m,
  DROP COLUMN IF EXISTS yes_ask_range_15m,
  DROP COLUMN IF EXISTS no_ask_range_15m;
