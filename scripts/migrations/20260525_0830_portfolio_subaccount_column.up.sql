-- Add subaccount INTEGER NOT NULL DEFAULT 1 to fills, orders, and positions tables
-- across all tenant schemas. Update positions unique index to (ticker, subaccount).

DO $$
DECLARE
  sch text;
  tbl text;
  slot text;
  idx_name text;
  idx_rec record;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    -- fills_NNNN: add subaccount column
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^fills_[0-9]{4}$'
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

    -- orders_NNNN: add subaccount column
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^orders_[0-9]{4}$'
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

    -- positions_NNNN: add subaccount column + replace ticker-only unique indexes
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^positions_[0-9]{4}$'
    LOOP
      slot := substring(tbl from '([0-9]{4})$');

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'subaccount'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN subaccount INTEGER NOT NULL DEFAULT 1',
          sch, tbl
        );
      END IF;

      -- Drop ALL unique indexes that cover only (ticker) regardless of name.
      -- Tenant schemas created via LIKE can have differently-named clones.
      FOR idx_rec IN
        SELECT i.relname AS indexname
        FROM pg_index ix
        JOIN pg_class t2 ON t2.oid = ix.indrelid
        JOIN pg_class i  ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t2.relnamespace
        WHERE n.nspname = sch
          AND t2.relname = tbl
          AND ix.indisunique
          AND array_length(ix.indkey, 1) = 1
          AND EXISTS (
            SELECT 1 FROM pg_attribute a
            WHERE a.attrelid = t2.oid
              AND a.attnum = ix.indkey[0]
              AND a.attname = 'ticker'
          )
          AND i.relname NOT LIKE '%pkey%'
      LOOP
        EXECUTE format('DROP INDEX %I.%I', sch, idx_rec.indexname);
      END LOOP;

      -- Also drop non-unique single-column ticker indexes (plain btree)
      FOR idx_rec IN
        SELECT i.relname AS indexname
        FROM pg_index ix
        JOIN pg_class t2 ON t2.oid = ix.indrelid
        JOIN pg_class i  ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t2.relnamespace
        WHERE n.nspname = sch
          AND t2.relname = tbl
          AND NOT ix.indisunique
          AND array_length(ix.indkey, 1) = 1
          AND EXISTS (
            SELECT 1 FROM pg_attribute a
            WHERE a.attrelid = t2.oid
              AND a.attnum = ix.indkey[0]
              AND a.attname = 'ticker'
          )
          AND i.relname NOT LIKE '%pkey%'
      LOOP
        EXECUTE format('DROP INDEX %I.%I', sch, idx_rec.indexname);
      END LOOP;

      -- Create composite unique index on (ticker, subaccount)
      idx_name := format('idx_positions_%s_ticker_subaccount', slot);
      IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = sch AND tablename = tbl AND indexname = idx_name
      ) THEN
        EXECUTE format(
          'CREATE UNIQUE INDEX %I ON %I.%I (ticker, subaccount)',
          idx_name, sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
