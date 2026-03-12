-- Remove MTB snapshot columns from users.account_balance_0001.
ALTER TABLE users.account_balance_0001
    DROP COLUMN IF EXISTS master_trading_bankroll,
    DROP COLUMN IF EXISTS mtb_base_value;

