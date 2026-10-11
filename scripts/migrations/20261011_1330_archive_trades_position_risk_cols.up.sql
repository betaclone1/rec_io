-- Archive parity: position_risk_* columns added to trades_* by 20260908_1945_position_risk_monitor_settings
-- were never added to archive.trades_archive_(live|paper)_NNNN, so monitor archive INSERTs (which copy
-- the trades_* column list) fail with UndefinedColumn.

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT t.table_name FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY t.table_name
  LOOP
    EXECUTE format('ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS position_risk_mode TEXT', tbl);
    EXECUTE format('ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS position_risk_policy TEXT', tbl);
    EXECUTE format('ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS position_risk_book_only_enabled BOOLEAN', tbl);
  END LOOP;
END $$;
