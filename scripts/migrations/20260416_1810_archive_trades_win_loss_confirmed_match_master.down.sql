-- Reverses ``20260416_1810_archive_trades_win_loss_confirmed_match_master.up.sql``.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_schema = 'archive'
      AND table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
  LOOP
    EXECUTE format(
      'ALTER TABLE %I.%I DROP COLUMN IF EXISTS win_loss_confirmed',
      r.table_schema,
      r.table_name
    );
  END LOOP;
END $$;
