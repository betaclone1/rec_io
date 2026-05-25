-- Add subaccount INTEGER NOT NULL DEFAULT 1 to trades and trades_simulated tables
-- across all tenant schemas. Existing rows backfilled as subaccount 1 (primary).

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
    -- trades_NNNN
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^trades_[0-9]{4}$'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'subaccount'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN subaccount INTEGER NOT NULL DEFAULT 1',
          sch, tbl
        );
      END IF;
    END LOOP;

    -- trades_simulated_NNNN
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^trades_simulated_[0-9]{4}$'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'subaccount'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN subaccount INTEGER NOT NULL DEFAULT 1',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
