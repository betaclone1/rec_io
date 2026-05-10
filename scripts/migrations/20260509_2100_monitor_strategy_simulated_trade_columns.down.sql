-- Reverse 20260509_2100_monitor_strategy_simulated_trade_columns.up.sql
-- Drops auxiliary columns; renames simulated_trade_* back to symbol_wide_* when symbol_wide_* are absent.
-- Roll back application code to a build that still expects symbol_wide_* column names if you use this down.

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
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_type = 'BASE TABLE'
        AND t.table_name ~ '^monitor_list_'
      ORDER BY 1
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'original_simulated_trade_cooldown_start_time'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN original_simulated_trade_cooldown_start_time',
          sch, tbl
        );
      END IF;
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_loss_count'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN simulated_trade_cooldown_loss_count',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'symbol_wide_loss_prevention'
      ) AND EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_loss_prevention'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I RENAME COLUMN simulated_trade_loss_prevention TO symbol_wide_loss_prevention',
          sch, tbl
        );
        EXECUTE format(
          'ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_duration TO symbol_wide_cooldown_duration',
          sch, tbl
        );
        EXECUTE format(
          'ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_start_time TO symbol_wide_cooldown_start_time',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;

  FOR sch, tbl IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE t.table_type = 'BASE TABLE'
      AND (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_name ~ '^strategy_list_'
    UNION ALL
    SELECT 'system'::text, 'strategy_list_default'::text
    WHERE to_regclass('system.strategy_list_default') IS NOT NULL
    ORDER BY 1, 2
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'original_simulated_trade_cooldown_start_time'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I DROP COLUMN original_simulated_trade_cooldown_start_time',
        sch, tbl
      );
    END IF;
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_loss_count'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I DROP COLUMN simulated_trade_cooldown_loss_count',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'symbol_wide_loss_prevention'
    ) AND EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_loss_prevention'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I RENAME COLUMN simulated_trade_loss_prevention TO symbol_wide_loss_prevention',
        sch, tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_duration TO symbol_wide_cooldown_duration',
        sch, tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_start_time TO symbol_wide_cooldown_start_time',
        sch, tbl
      );
    END IF;
  END LOOP;
END
$$;
