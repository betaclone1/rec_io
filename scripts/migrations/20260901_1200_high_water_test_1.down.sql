-- Revert High Water Test 1 strategy seed and limit_close_offset columns.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    DELETE FROM system.strategy_list_default WHERE name = 'High Water Test 1';
  END IF;

  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = sch AND table_name LIKE 'strategy_list_%'
    LOOP
      EXECUTE format(
        'DELETE FROM %I.%I WHERE name = %L',
        sch, tbl, 'High Water Test 1'
      );
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_offset'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN limit_close_offset', sch, tbl);
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_offset'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN limit_close_offset', sch, tbl);
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name ~ '^trades_[0-9]{4}$' OR t.table_name ~ '^trades_simulated_[0-9]{4}$')
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'limit_close_offset'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN limit_close_offset', sch, tbl);
      END IF;
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
      AND column_name = 'limit_close_offset'
  ) THEN
    ALTER TABLE system.strategy_list_default DROP COLUMN limit_close_offset;
  END IF;

  FOR tbl IN
    SELECT t.table_name FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I DROP COLUMN IF EXISTS limit_close_offset',
      tbl
    );
  END LOOP;
END $$;
