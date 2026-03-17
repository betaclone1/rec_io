-- Remove roi_pct from trades tables (rollback)

ALTER TABLE users.trades_0001
DROP COLUMN IF EXISTS roi_pct;

ALTER TABLE users.trades_simulated_0001
DROP COLUMN IF EXISTS roi_pct;

