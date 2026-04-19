-- GET /trades unions master + archive with a shared column list; master has ``win_loss_confirmed``
-- (``20260328_1500``) but archive tables were not altered. Add nullable column on all tenant
-- archive trade tables so ``union_trades_with_archives_select_columns`` can select it.

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
      'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS win_loss_confirmed BOOLEAN',
      r.table_schema,
      r.table_name
    );
  END LOOP;
END $$;
