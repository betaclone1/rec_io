-- Remove Taker Edge strategy seed rows (does not drop monitor rows that use it).

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    DELETE FROM system.strategy_list_default WHERE name = 'Taker Edge';
  END IF;

  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = sch AND table_name LIKE 'strategy_list_%'
      ORDER BY 1
    LOOP
      EXECUTE format('DELETE FROM %I.%I WHERE name = %L', sch, tbl, 'Taker Edge');
    END LOOP;
  END LOOP;
END $$;
