-- Revert Expiration Reversal strategy seed and flip-floor CHECK constraints.
-- Monitors already set to 'Expiration Reversal' keep their strategy value.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch, tbl IN
    SELECT 'system'::text, 'strategy_list_default'::text
    WHERE to_regclass('system.strategy_list_default') IS NOT NULL
    UNION ALL
    SELECT t.table_schema::text, t.table_name::text
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND (t.table_name LIKE 'strategy_list_%' OR t.table_name LIKE 'monitor_list_%')
      AND t.table_type = 'BASE TABLE'
  LOOP
    EXECUTE format(
      'ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS expiration_reversal_flip_floor_chk',
      sch, tbl
    );
    IF tbl LIKE 'strategy_list_%' THEN
      EXECUTE format('DELETE FROM %I.%I WHERE name = %L', sch, tbl, 'Expiration Reversal');
    END IF;
  END LOOP;
END $$;
