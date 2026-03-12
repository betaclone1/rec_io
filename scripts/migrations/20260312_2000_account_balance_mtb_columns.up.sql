-- Add MTB snapshot columns to users.account_balance_0001 so each balance row can record
-- the Master Trading Bankroll balance and its base_value at the time of sync.
-- Values are stored in cents, consistent with other balance fields.
ALTER TABLE users.account_balance_0001
    ADD COLUMN IF NOT EXISTS master_trading_bankroll INTEGER,
    ADD COLUMN IF NOT EXISTS mtb_base_value INTEGER;

