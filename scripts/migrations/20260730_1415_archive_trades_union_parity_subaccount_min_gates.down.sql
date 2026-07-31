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
    EXECUTE format('ALTER TABLE archive.%I DROP COLUMN IF EXISTS subaccount', tbl);
    EXECUTE format('ALTER TABLE archive.%I DROP COLUMN IF EXISTS min_fill_price', tbl);
    EXECUTE format('ALTER TABLE archive.%I DROP COLUMN IF EXISTS min_slippage', tbl);
  END LOOP;
END
$$;
