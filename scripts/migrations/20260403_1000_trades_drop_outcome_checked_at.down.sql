ALTER TABLE users.trades_0001
    ADD COLUMN IF NOT EXISTS outcome_checked_at TIMESTAMPTZ;

COMMENT ON COLUMN users.trades_0001.outcome_checked_at IS
    'When trade_manager last finished comparing venue binary outcome to recorded win_loss; stops repeat polling.';

COMMENT ON COLUMN users.trades_0001.market_result IS
    'Binary resolution from outcome verification: settlement market_result (live) or public event market result (paper), normalized to yes/no.';
