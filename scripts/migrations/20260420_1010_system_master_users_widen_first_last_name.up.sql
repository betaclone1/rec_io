-- Match registration UI (maxlength 120); safe if columns already VARCHAR(100).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'first_name'
    ) THEN
        ALTER TABLE system.master_users ALTER COLUMN first_name TYPE VARCHAR(100);
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'system' AND table_name = 'master_users' AND column_name = 'last_name'
    ) THEN
        ALTER TABLE system.master_users ALTER COLUMN last_name TYPE VARCHAR(100);
    END IF;
END
$$;
