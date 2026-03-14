-- Add ret_pct_base: return % using mtb_base_value instead of bankroll (same formula).
-- Used when finalizing closed trades so we have both bankroll-based and base-based return.
ALTER TABLE users.trades_0001
    ADD COLUMN IF NOT EXISTS ret_pct_base REAL;

ALTER TABLE users.trades_simulated_0001
    ADD COLUMN IF NOT EXISTS ret_pct_base REAL;
