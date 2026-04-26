-- Reverse archive-only columns from 20260426_1600_kalshi_execution_monitor_trades_archive.up.sql

DO $$
DECLARE
  rel text;
BEGIN
  FOR rel IN
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'archive' AND c.relkind = 'r'
      AND c.relname ~ '^trades_archive_(live|paper)_[0-9]{4}$'
  LOOP
    EXECUTE format('ALTER TABLE archive.%I DROP COLUMN IF EXISTS order_type', rel);
    EXECUTE format('ALTER TABLE archive.%I DROP COLUMN IF EXISTS time_in_force', rel);
  END LOOP;
END $$;
