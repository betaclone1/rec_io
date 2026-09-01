DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
      AND column_name = 'stop_loss_offset'
  ) THEN
    ALTER TABLE system.strategy_list_default DROP COLUMN stop_loss_offset;
  END IF;

  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'stop_loss_offset'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN stop_loss_offset', sch, tbl);
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'stop_loss_offset'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN stop_loss_offset', sch, tbl);
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name ~ '^trades_[0-9]{4}$' OR t.table_name ~ '^trades_simulated_[0-9]{4}$')
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'stop_loss_offset'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN stop_loss_offset', sch, tbl);
      END IF;
    END LOOP;
  END LOOP;

  FOR tbl IN
    SELECT t.table_name FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I DROP COLUMN IF EXISTS stop_loss_offset',
      tbl
    );
  END LOOP;
END $$;
