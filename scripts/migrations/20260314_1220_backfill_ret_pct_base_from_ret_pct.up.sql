-- One-time backfill: set ret_pct_base = ret_pct for existing closed trades that have ret_pct but no ret_pct_base.
-- This gives a consistent value for historical trades; new closes will compute ret_pct_base from mtb_base_value.
UPDATE users.trades_0001
SET ret_pct_base = ret_pct
WHERE ret_pct IS NOT NULL AND ret_pct_base IS NULL;

UPDATE users.trades_simulated_0001
SET ret_pct_base = ret_pct
WHERE ret_pct IS NOT NULL AND ret_pct_base IS NULL;
