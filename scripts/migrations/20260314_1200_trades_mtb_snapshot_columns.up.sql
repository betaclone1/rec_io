-- Add MTB snapshot columns to trades tables so each new trade records
-- master_trading_bankroll and mtb_base_value from account_balance at insert time.
-- Values in cents; nullable for existing/backfilled rows.
ALTER TABLE users.trades_0001
    ADD COLUMN IF NOT EXISTS master_trading_bankroll INTEGER,
    ADD COLUMN IF NOT EXISTS mtb_base_value INTEGER;

ALTER TABLE users.trades_simulated_0001
    ADD COLUMN IF NOT EXISTS master_trading_bankroll INTEGER,
    ADD COLUMN IF NOT EXISTS mtb_base_value INTEGER;
