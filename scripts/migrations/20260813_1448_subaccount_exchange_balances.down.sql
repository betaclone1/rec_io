-- Reverse 20260813_1448_subaccount_exchange_balances: drop per-shard cash columns.

DO $$
DECLARE
  sch text;
  tbl text;
  col text;
  cols text[] := ARRAY[
    'exchange_0_balance',
    'exchange_1_balance',
    'exchange_2_balance',
    'exchange_3_balance'
  ];
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (
          t.table_name ~ '^subaccounts(_paper)?_[0-9]{4}$'
          OR t.table_name ~ '^subaccount_balance_[0-9]{4}_[0-9]+$'
        )
      ORDER BY 1
    LOOP
      FOREACH col IN ARRAY cols LOOP
        IF EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch
            AND c.table_name = tbl
            AND c.column_name = col
        ) THEN
          EXECUTE format(
            'ALTER TABLE %I.%I DROP COLUMN %I',
            sch, tbl, col
          );
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
END
$$;
