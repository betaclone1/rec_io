-- High Water Test 1: stop_loss_offset (owned-side floor = buy_price - offset).

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'stop_loss_offset'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN stop_loss_offset NUMERIC(6,4) DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.stop_loss_offset IS %L',
        sch, tbl,
        'High Water Test 1: owned-side stop floor offset below fill (e.g. 0.1000). 0 disables. Migration 20260901_1400_high_water_test_1_stop_loss_offset.'
      );
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'stop_loss_offset'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN stop_loss_offset NUMERIC(6,4) DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name ~ '^trades_[0-9]{4}$' OR t.table_name ~ '^trades_simulated_[0-9]{4}$')
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'stop_loss_offset'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN stop_loss_offset NUMERIC(6,4) NOT NULL DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'stop_loss_offset'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN stop_loss_offset NUMERIC(6,4) DEFAULT 0.0000;
    END IF;
  END IF;

  FOR tbl IN
    SELECT t.table_name FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY t.table_name
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I ADD COLUMN IF NOT EXISTS stop_loss_offset NUMERIC(6,4)',
      tbl
    );
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    UPDATE system.strategy_list_default
    SET stop_loss_price = 0.0000, stop_loss_offset = 0.1000
    WHERE name = 'High Water Test 1';
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
      EXECUTE format(
        'UPDATE %I.%I SET stop_loss_price = 0.0000, stop_loss_offset = 0.1000 WHERE name = %L',
        sch, tbl, 'High Water Test 1'
      );
    END LOOP;
  END LOOP;
END $$;
