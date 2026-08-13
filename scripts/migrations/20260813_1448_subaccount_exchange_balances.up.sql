-- Kalshi exchange sharding: per-shard cash columns on live/paper subaccounts and
-- per-subaccount balance history. Keeps table names (subaccount number only).
-- balance remains the total; exchange_*_balance hold the matrix (cents).
-- Historical rows: attribute existing balance to exchange_0_balance (pre-shard world).
-- Schemas: legacy users + tenant users_NNNN.

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
  comments text[] := ARRAY[
    'Cash on Kalshi exchange_index 0 for this subaccount (cents).',
    'Cash on Kalshi exchange_index 1 for this subaccount (cents).',
    'Cash on Kalshi exchange_index 2 for this subaccount (cents). Crypto MTB home after cutover.',
    'Cash on Kalshi exchange_index 3 for this subaccount (cents).'
  ];
  i int;
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
      FOR i IN 1 .. array_length(cols, 1) LOOP
        col := cols[i];
        IF NOT EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch
            AND c.table_name = tbl
            AND c.column_name = col
        ) THEN
          EXECUTE format(
            'ALTER TABLE %I.%I ADD COLUMN %I integer NOT NULL DEFAULT 0',
            sch, tbl, col
          );
        END IF;
        EXECUTE format(
          'COMMENT ON COLUMN %I.%I.%I IS %L',
          sch, tbl, col, comments[i]
        );
      END LOOP;

      -- Pre-sharding / current 1D poller: all stored cash was shard 0.
      EXECUTE format(
        'UPDATE %I.%I SET exchange_0_balance = balance',
        sch, tbl
      );
    END LOOP;
  END LOOP;
END
$$;
