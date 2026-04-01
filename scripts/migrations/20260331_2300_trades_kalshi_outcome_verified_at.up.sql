-- When set: Kalshi settlement (live) or public event API (paper) outcome was compared to recorded win_loss.
ALTER TABLE users.trades_0001
    ADD COLUMN IF NOT EXISTS kalshi_outcome_verified_at TIMESTAMPTZ;

COMMENT ON COLUMN users.trades_0001.kalshi_outcome_verified_at IS
    'Set when trade_manager compared Kalshi binary outcome (settlements market_result or GET /events market result) to recorded win_loss; stops repeat verification.';
