-- Reverse credits_history_<slot> then direction columns on orders_/fills_.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^credits_history_[0-9]{4}$'
  LOOP
    EXECUTE format(
      'DROP TABLE IF EXISTS %I.%I CASCADE',
      r.table_schema,
      r.table_name
    );
  END LOOP;
END $$;

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^(orders|fills)_[0-9]{4}$'
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = r.table_schema
        AND c.table_name = r.table_name
        AND c.column_name = 'side'
    ) THEN
      CONTINUE;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = r.table_schema
        AND c.table_name = r.table_name
        AND c.column_name = 'outcome_side'
    ) THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'ALTER TABLE %I.%I RENAME COLUMN outcome_side TO side',
      r.table_schema,
      r.table_name
    );

    EXECUTE format(
      'ALTER TABLE %I.%I DROP COLUMN IF EXISTS orderbook_side',
      r.table_schema,
      r.table_name
    );
  END LOOP;
END $$;
