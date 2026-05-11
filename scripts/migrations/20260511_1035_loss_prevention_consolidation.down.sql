-- Reverse the schema names introduced by 20260511_1035_loss_prevention_consolidation.
-- Data values for the former separate win-streak toggle cannot be fully reconstructed
-- after the master toggle merge; this restores the prior column names and drops method.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch, tbl IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE t.table_type = 'BASE TABLE'
      AND (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_name ~ '^monitor_list_'
    ORDER BY 1, 2
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_state'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention_state TO loss_prevention', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_method'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN loss_prevention_method', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_duration'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_duration'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention_duration TO simulated_trade_cooldown_duration', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_loss_prevention_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_loss_prevention_cooldown_start_time TO simulated_trade_cooldown_start_time', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_loss_prevention_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_simulated_trade_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN original_loss_prevention_cooldown_start_time TO original_simulated_trade_cooldown_start_time', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_cooldown_loss_count'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_loss_count'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention_cooldown_loss_count TO simulated_trade_cooldown_loss_count', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_loss_prevention_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_trade_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN live_loss_prevention_cooldown_start_time TO live_trade_cooldown_start_time', sch, tbl);
    END IF;
  END LOOP;

  FOR sch, tbl IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE t.table_type = 'BASE TABLE'
      AND (
        (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
        AND t.table_name ~ '^strategy_list_'
      )
    UNION ALL
    SELECT 'system'::text, 'strategy_list_default'::text
    WHERE to_regclass('system.strategy_list_default') IS NOT NULL
    ORDER BY 1, 2
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_state'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention_state TO loss_prevention', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_method'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN loss_prevention_method', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_duration'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_duration'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention_duration TO simulated_trade_cooldown_duration', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_loss_prevention_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_loss_prevention_cooldown_start_time TO simulated_trade_cooldown_start_time', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_loss_prevention_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_simulated_trade_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN original_loss_prevention_cooldown_start_time TO original_simulated_trade_cooldown_start_time', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_cooldown_loss_count'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_loss_count'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention_cooldown_loss_count TO simulated_trade_cooldown_loss_count', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_loss_prevention_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_trade_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN live_loss_prevention_cooldown_start_time TO live_trade_cooldown_start_time', sch, tbl);
    END IF;
  END LOOP;
END
$$;
