-- Remove Expiration Scalp strategy rows seeded by 20260612_1200_expiration_scalp_strategy.up.sql

DELETE FROM system.strategy_list_default WHERE name = 'Expiration Scalp';

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = sch
        AND table_name LIKE 'strategy_list_%'
      ORDER BY 1
    LOOP
      EXECUTE format(
        'DELETE FROM %I.%I WHERE name = %L',
        sch, tbl, 'Expiration Scalp'
      );
    END LOOP;
  END LOOP;
END $$;
