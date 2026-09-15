-- Position risk Stage 2: three HWS monitor/trade snapshot settings.

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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_mode'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_mode TEXT NOT NULL DEFAULT %L',
          sch, tbl, 'legacy'
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_policy'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_policy TEXT NOT NULL DEFAULT %L',
          sch, tbl, 'hws_lvw_v1'
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_book_only_enabled'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_book_only_enabled BOOLEAN NOT NULL DEFAULT false',
          sch, tbl
        );
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_mode'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_mode TEXT NOT NULL DEFAULT %L',
          sch, tbl, 'legacy'
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_policy'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_policy TEXT NOT NULL DEFAULT %L',
          sch, tbl, 'hws_lvw_v1'
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_book_only_enabled'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_book_only_enabled BOOLEAN NOT NULL DEFAULT false',
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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_mode'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_mode TEXT NOT NULL DEFAULT %L',
          sch, tbl, 'legacy'
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_policy'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_policy TEXT NOT NULL DEFAULT %L',
          sch, tbl, 'hws_lvw_v1'
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position_risk_book_only_enabled'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN position_risk_book_only_enabled BOOLEAN NOT NULL DEFAULT false',
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
        AND c.column_name = 'position_risk_mode'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN position_risk_mode TEXT NOT NULL DEFAULT 'legacy';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'position_risk_policy'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN position_risk_policy TEXT NOT NULL DEFAULT 'hws_lvw_v1';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'position_risk_book_only_enabled'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN position_risk_book_only_enabled BOOLEAN NOT NULL DEFAULT false;
    END IF;
  END IF;
END $$;
