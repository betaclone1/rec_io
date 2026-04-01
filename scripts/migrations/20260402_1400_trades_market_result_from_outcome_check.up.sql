-- Venue resolution (normalized yes/no) copied from settlements.market_result (live) or event market result (paper) at outcome-check time.
ALTER TABLE users.trades_0001
    ADD COLUMN IF NOT EXISTS market_result TEXT;

COMMENT ON COLUMN users.trades_0001.market_result IS
    'Binary resolution from outcome verification: settlement market_result (live) or public event market result (paper), normalized to yes/no.';
