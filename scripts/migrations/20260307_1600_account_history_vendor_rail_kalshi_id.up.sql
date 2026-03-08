-- Add kalshi_id, vendor, rail to users.account_history_0001 for /deposits and /withdrawals upsert.
-- Idempotent: safe to run if columns/index already exist.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'account_history_0001' AND column_name = 'kalshi_id') THEN
        ALTER TABLE users.account_history_0001 ADD COLUMN kalshi_id VARCHAR(64);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'account_history_0001' AND column_name = 'vendor') THEN
        ALTER TABLE users.account_history_0001 ADD COLUMN vendor VARCHAR(100);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'users' AND table_name = 'account_history_0001' AND column_name = 'rail') THEN
        ALTER TABLE users.account_history_0001 ADD COLUMN rail VARCHAR(100);
    END IF;
    DROP INDEX IF EXISTS users.account_history_0001_kalshi_id_key;
    CREATE UNIQUE INDEX account_history_0001_kalshi_id_key ON users.account_history_0001 (kalshi_id) WHERE kalshi_id IS NOT NULL;
END $$;
