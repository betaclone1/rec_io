-- Revert: drop subaccount column from fills, orders, positions tables;
-- restore ticker-only unique indexes on positions.

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
    -- positions_NNNN: drop composite index, restore ticker-only, drop subaccount
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^positions_[0-9]{4}$'
    LOOP
      slot := substring(tbl from '([0-9]{4})$');

      -- Drop composite (ticker, subaccount) indexes
      FOR idx_rec IN
        SELECT i.relname AS indexname
        FROM pg_index ix
        JOIN pg_class t2 ON t2.oid = ix.indrelid
        JOIN pg_class i  ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t2.relnamespace
        WHERE n.nspname = sch AND t2.relname = tbl
          AND ix.indisunique
          AND i.relname LIKE '%ticker_subaccount%'
      LOOP
        EXECUTE format('DROP INDEX %I.%I', sch, idx_rec.indexname);
      END LOOP;

      -- Restore canonical ticker-only unique indexes
      idx_name := format('idx_positions_%s_ticker', slot);
      IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = sch AND tablename = tbl AND indexname = idx_name
      ) THEN
        EXECUTE format(
          'CREATE UNIQUE INDEX %I ON %I.%I (ticker)',
          idx_name, sch, tbl
        );
      END IF;

      idx_name := format('idx_positions_%s_ticker_unique', slot);
      IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = sch AND tablename = tbl AND indexname = idx_name
      ) THEN
        EXECUTE format(
          'CREATE UNIQUE INDEX %I ON %I.%I (ticker)',
          idx_name, sch, tbl
        );
      END IF;

      -- Drop subaccount column
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'subaccount'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN subaccount', sch, tbl);
      END IF;
    END LOOP;

    -- orders_NNNN: drop subaccount
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^orders_[0-9]{4}$'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'subaccount'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN subaccount', sch, tbl);
      END IF;
    END LOOP;

    -- fills_NNNN: drop subaccount
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^fills_[0-9]{4}$'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'subaccount'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN subaccount', sch, tbl);
      END IF;
    END LOOP;
  END LOOP;
END
$$;
