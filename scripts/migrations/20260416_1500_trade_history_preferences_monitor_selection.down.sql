DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_schema ~ '^users_[0-9]{4}$'
      AND table_name ~ '^trade_history_preferences_[0-9]{4}$'
  LOOP
    EXECUTE format(
      'ALTER TABLE %I.%I DROP COLUMN IF EXISTS monitor_selection',
      r.table_schema,
      r.table_name
    );
  END LOOP;
END
$$;
