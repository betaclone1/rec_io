-- Remove venue outcome column from simulated trade tables (settlement uses spot vs strike only).

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_name ~ '^trades_simulated_[0-9]{4}$'
      AND table_schema ~ '^(users|users_[0-9]{4})$'
    ORDER BY table_schema, table_name
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = r.table_schema
        AND c.table_name = r.table_name
        AND c.column_name = 'market_result'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I DROP COLUMN market_result',
        r.table_schema,
        r.table_name
      );
    END IF;
  END LOOP;
END
$$;
