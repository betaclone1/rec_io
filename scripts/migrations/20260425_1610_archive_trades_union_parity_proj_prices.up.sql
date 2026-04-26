-- Keep archive.trades_archive_{live|paper}_* aligned with users*.trades_* so
-- union_trades_with_archives_select (trade history insights, full unions) stays valid.
DO $$
DECLARE
  table_name text;
BEGIN
  FOR table_name IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND (
        t.table_name ~ '^trades_archive_live_[0-9]{4}$'
        OR t.table_name ~ '^trades_archive_paper_[0-9]{4}$'
      )
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS initial_proj_price NUMERIC(10,8)',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS initial_proj_fees NUMERIC(10,4)',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ALTER COLUMN buy_price TYPE NUMERIC(12,6) USING ROUND(buy_price::numeric, 6)',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ALTER COLUMN sell_price TYPE NUMERIC(12,6) USING ROUND(sell_price::numeric, 6)',
      table_name
    );
  END LOOP;
END $$;
