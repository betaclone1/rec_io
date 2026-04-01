-- Shorter column: was exchange_binary_outcome_evaluated_at (or legacy kalshi_outcome_verified_at).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users'
          AND table_name = 'trades_0001'
          AND column_name = 'exchange_binary_outcome_evaluated_at'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users'
          AND table_name = 'trades_0001'
          AND column_name = 'outcome_checked_at'
    ) THEN
        ALTER TABLE users.trades_0001
            RENAME COLUMN exchange_binary_outcome_evaluated_at TO outcome_checked_at;
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users'
          AND table_name = 'trades_0001'
          AND column_name = 'kalshi_outcome_verified_at'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users'
          AND table_name = 'trades_0001'
          AND column_name = 'outcome_checked_at'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users'
          AND table_name = 'trades_0001'
          AND column_name = 'exchange_binary_outcome_evaluated_at'
    ) THEN
        ALTER TABLE users.trades_0001
            RENAME COLUMN kalshi_outcome_verified_at TO outcome_checked_at;
    END IF;
END $$;

COMMENT ON COLUMN users.trades_0001.outcome_checked_at IS
    'When trade_manager last finished comparing venue binary outcome to recorded win_loss; stops repeat polling.';
