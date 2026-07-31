-- Keep archive.trades_archive_{live|paper}_NNNN aligned with users_<n>.trades_<n> so
-- union_trades_with_archives_select* stays valid and monitor archive INSERTs (which copy
-- every master column) do not fail on UndefinedColumn.
--
-- Columns stay nullable here: rows archived before these gates existed have no recorded
-- value, and stamping the master defaults would assert settings that were never in force.

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY t.table_name
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS subaccount INTEGER',
      tbl
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS min_fill_price NUMERIC(6,4)',
      tbl
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS min_slippage NUMERIC(6,4)',
      tbl
    );
  END LOOP;
END
$$;
