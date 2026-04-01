-- Exchange-agnostic name (replaces kalshi_outcome_verified_at from 20260331_2300).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users'
          AND table_name = 'trades_0001'
          AND column_name = 'kalshi_outcome_verified_at'
    ) THEN
        ALTER TABLE users.trades_0001
            RENAME COLUMN kalshi_outcome_verified_at TO exchange_binary_outcome_evaluated_at;
    END IF;
END $$;

COMMENT ON COLUMN users.trades_0001.exchange_binary_outcome_evaluated_at IS
    'Set when trade_manager finished comparing the venue binary outcome to recorded win_loss; stops repeat verification.';
