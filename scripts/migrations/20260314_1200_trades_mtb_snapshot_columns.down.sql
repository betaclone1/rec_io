-- Remove MTB snapshot columns from trades tables.
ALTER TABLE users.trades_0001
    DROP COLUMN IF EXISTS master_trading_bankroll,
    DROP COLUMN IF EXISTS mtb_base_value;

ALTER TABLE users.trades_simulated_0001
    DROP COLUMN IF EXISTS master_trading_bankroll,
    DROP COLUMN IF EXISTS mtb_base_value;
