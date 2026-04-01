-- Outcome timing is driven by Kalshi market_lifecycle_v2 (market_watchdog_ws); no polling dedupe column.
ALTER TABLE users.trades_0001
    DROP COLUMN IF EXISTS outcome_checked_at;

COMMENT ON COLUMN users.trades_0001.market_result IS
    'Kalshi binary resolution (yes/no), normalized from market_lifecycle_v2 via market_watchdog_ws on determined/settled; '
    'settlement polling in trade_manager still closes/finalizes live trades and may log settlement_market_result.';
