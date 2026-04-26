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
      'ALTER TABLE archive.%I ALTER COLUMN buy_price TYPE NUMERIC(10,4) USING ROUND(buy_price::numeric, 4)',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE archive.%I ALTER COLUMN sell_price TYPE NUMERIC(10,4) USING ROUND(sell_price::numeric, 4)',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE archive.%I DROP COLUMN IF EXISTS initial_proj_fees',
      table_name
    );
    EXECUTE format(
      'ALTER TABLE archive.%I DROP COLUMN IF EXISTS initial_proj_price',
      table_name
    );
  END LOOP;
END $$;
