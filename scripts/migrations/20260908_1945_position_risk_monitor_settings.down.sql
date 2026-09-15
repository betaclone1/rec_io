-- Reverse position risk Stage 2 monitor/trade snapshot settings.

DO $$
DECLARE
  sch text;
  tbl text;
  col text;
BEGIN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOREACH col IN ARRAY ARRAY[
      'position_risk_mode',
      'position_risk_policy',
      'position_risk_book_only_enabled'
    ]
    LOOP
      FOR tbl IN
        SELECT t.table_name FROM information_schema.tables t
        WHERE t.table_schema = sch
          AND (
            t.table_name LIKE 'monitor_list_%'
            OR t.table_name LIKE 'strategy_list_%'
            OR t.table_name ~ '^trades_[0-9]{4}$'
            OR t.table_name ~ '^trades_simulated_[0-9]{4}$'
          )
      LOOP
        IF EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = col
        ) THEN
          EXECUTE format('ALTER TABLE %I.%I DROP COLUMN %I', sch, tbl, col);
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    FOREACH col IN ARRAY ARRAY[
      'position_risk_mode',
      'position_risk_policy',
      'position_risk_book_only_enabled'
    ]
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
          AND c.column_name = col
      ) THEN
        EXECUTE format('ALTER TABLE system.strategy_list_default DROP COLUMN %I', col);
      END IF;
    END LOOP;
  END IF;
END $$;
