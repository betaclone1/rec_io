-- Per-monitor checkbox state for trade history (mon_<slot>_<id> -> checked).
-- Tenant tables live in schemas users_NNNN (see 20260411_1300_rename_users_schema_to_users_0001).

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
      'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS monitor_selection JSONB NOT NULL DEFAULT ''{}''::jsonb',
      r.table_schema,
      r.table_name
    );
  END LOOP;
END
$$;
