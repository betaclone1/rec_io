-- Consolidate monitor loss prevention naming and method selection.
--
-- New model:
--   loss_prevention_toggle       master enable for any loss prevention
--   loss_prevention_method       'win_streak' or 'time'
--   loss_prevention_state        formerly monitor/strategy loss_prevention
--   loss_prevention_duration     formerly simulated_trade_cooldown_duration
--   *_loss_prevention_* cooldown fields replace simulated/live trade-specific names

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
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_state'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention TO loss_prevention_state', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_state'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_state VARCHAR(50) DEFAULT %L', sch, tbl, 'none');
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_method'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_method TEXT DEFAULT %L', sch, tbl, 'win_streak');
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_duration'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_duration'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_duration TO loss_prevention_duration', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_duration'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_duration INTEGER DEFAULT 4', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_start_time TO simulated_loss_prevention_cooldown_start_time', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_loss_prevention_cooldown_start_time TIMESTAMPTZ', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_simulated_trade_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN original_simulated_trade_cooldown_start_time TO original_loss_prevention_cooldown_start_time', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN original_loss_prevention_cooldown_start_time TIMESTAMPTZ', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_loss_count'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_cooldown_loss_count'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_loss_count TO loss_prevention_cooldown_loss_count', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_cooldown_loss_count'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_cooldown_loss_count INTEGER NOT NULL DEFAULT 0', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_trade_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN live_trade_cooldown_start_time TO live_loss_prevention_cooldown_start_time', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN live_loss_prevention_cooldown_start_time TIMESTAMPTZ', sch, tbl);
    END IF;

    EXECUTE format(
      'UPDATE %I.%I
       SET loss_prevention_method = CASE
             WHEN COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE THEN %L
             WHEN loss_prevention_method IS NULL OR trim(loss_prevention_method) = '''' THEN %L
             ELSE loss_prevention_method
           END,
           loss_prevention_toggle = COALESCE(loss_prevention_toggle, FALSE) OR COALESCE(simulated_trade_loss_prevention, FALSE),
           loss_prevention_duration = COALESCE(loss_prevention_duration, 4),
           loss_prevention_cooldown_loss_count = COALESCE(loss_prevention_cooldown_loss_count, 0)',
      sch, tbl, 'time', 'win_streak'
    );

    EXECUTE format(
      'UPDATE %I.%I
       SET loss_prevention_state = %L
       WHERE COALESCE(loss_prevention_toggle, FALSE) IS FALSE',
      sch, tbl, 'off'
    );
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
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_state'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN loss_prevention TO loss_prevention_state', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_state'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_state VARCHAR(50) DEFAULT %L', sch, tbl, 'none');
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_method'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_method TEXT DEFAULT %L', sch, tbl, 'win_streak');
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_duration'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_duration'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_duration TO loss_prevention_duration', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_duration'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_duration INTEGER DEFAULT 4', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_start_time TO simulated_loss_prevention_cooldown_start_time', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN simulated_loss_prevention_cooldown_start_time TIMESTAMPTZ', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_simulated_trade_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN original_simulated_trade_cooldown_start_time TO original_loss_prevention_cooldown_start_time', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'original_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN original_loss_prevention_cooldown_start_time TIMESTAMPTZ', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'simulated_trade_cooldown_loss_count'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_cooldown_loss_count'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN simulated_trade_cooldown_loss_count TO loss_prevention_cooldown_loss_count', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'loss_prevention_cooldown_loss_count'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN loss_prevention_cooldown_loss_count INTEGER NOT NULL DEFAULT 0', sch, tbl);
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_trade_cooldown_start_time'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN live_trade_cooldown_start_time TO live_loss_prevention_cooldown_start_time', sch, tbl);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = sch AND table_name = tbl AND column_name = 'live_loss_prevention_cooldown_start_time'
    ) THEN
      EXECUTE format('ALTER TABLE %I.%I ADD COLUMN live_loss_prevention_cooldown_start_time TIMESTAMPTZ', sch, tbl);
    END IF;

    EXECUTE format(
      'UPDATE %I.%I
       SET loss_prevention_method = CASE
             WHEN COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE THEN %L
             WHEN loss_prevention_method IS NULL OR trim(loss_prevention_method) = '''' THEN %L
             ELSE loss_prevention_method
           END,
           loss_prevention_toggle = COALESCE(loss_prevention_toggle, FALSE) OR COALESCE(simulated_trade_loss_prevention, FALSE),
           loss_prevention_duration = COALESCE(loss_prevention_duration, 4),
           loss_prevention_cooldown_loss_count = COALESCE(loss_prevention_cooldown_loss_count, 0)',
      sch, tbl, 'time', 'win_streak'
    );
  END LOOP;
END
$$;
