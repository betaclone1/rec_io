-- Archive UNION parity for Kalshi execution snapshot columns.
-- Tenant monitor_list + trades columns: migration `20260426_1600_monitor_trades_execution_settings`.
-- This migration only adds columns on `archive.trades_archive_{live|paper}_*` so
-- `union_trades_with_archives_select()` matches master `users*`.trades_* column lists.

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
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'archive' AND table_name = rel AND column_name = 'time_in_force'
    ) THEN
      EXECUTE format('ALTER TABLE archive.%I ADD COLUMN time_in_force TEXT', rel);
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'archive' AND table_name = rel AND column_name = 'order_type'
    ) THEN
      EXECUTE format('ALTER TABLE archive.%I ADD COLUMN order_type TEXT', rel);
    END IF;
  END LOOP;
END $$;
