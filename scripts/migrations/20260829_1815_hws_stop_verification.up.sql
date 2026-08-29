-- High Water Scalp auto-stop verification dwell.
-- Distinct from verification_period_* (HTC auto-stop dwell / Exp Scalp+HWS entry dwell).

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
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'stop_verification_period_enabled'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN stop_verification_period_enabled BOOLEAN DEFAULT FALSE',
          sch, tbl
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'stop_verification_period_seconds'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN stop_verification_period_seconds INTEGER DEFAULT 1',
          sch, tbl
        );
      END IF;
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.stop_verification_period_enabled IS %L',
        sch, tbl,
        'High Water Scalp: dwell before floor auto-stop. Distinct from verification_period_* (entry). Migration 20260829_1815_hws_stop_verification.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.stop_verification_period_seconds IS %L',
        sch, tbl,
        'High Water Scalp floor auto-stop dwell seconds (1-60). 0 = immediate. Migration 20260829_1815_hws_stop_verification.'
      );
    END LOOP;

    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch AND t.table_name LIKE 'strategy_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'stop_verification_period_enabled'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN stop_verification_period_enabled BOOLEAN DEFAULT FALSE',
          sch, tbl
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'stop_verification_period_seconds'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN stop_verification_period_seconds INTEGER DEFAULT 1',
          sch, tbl
        );
      END IF;
      EXECUTE format(
        'UPDATE %I.%I SET stop_verification_period_enabled = FALSE, stop_verification_period_seconds = 1 WHERE name = %L',
        sch, tbl, 'High Water Scalp'
      );
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'stop_verification_period_enabled'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN stop_verification_period_enabled BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'stop_verification_period_seconds'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN stop_verification_period_seconds INTEGER DEFAULT 1;
    END IF;
    UPDATE system.strategy_list_default
       SET stop_verification_period_enabled = FALSE,
           stop_verification_period_seconds = 1
     WHERE name = 'High Water Scalp';
  END IF;
END
$$;
