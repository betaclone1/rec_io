DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'users'
          AND table_name = 'trades_0001'
          AND column_name = 'exchange_binary_outcome_evaluated_at'
    ) THEN
        ALTER TABLE users.trades_0001
            RENAME COLUMN exchange_binary_outcome_evaluated_at TO kalshi_outcome_verified_at;
    END IF;
END $$;
