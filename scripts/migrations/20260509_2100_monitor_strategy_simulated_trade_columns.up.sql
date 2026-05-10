-- Replace symbol_wide_* with simulated_trade_* on monitor_list_* and strategy_list_* (+ system.strategy_list_default).
-- Add original_simulated_trade_cooldown_start_time + simulated_trade_cooldown_loss_count (per-monitor LP window + tier counts).
-- Ensure users.sim_trade_lp_cycle_ledger_<slot> exists for each monitor_list_<slot>.
-- Idempotent: skips rename when simulated_trade_* already present; adds missing columns only.

DO $$
DECLARE
  sch text;
  tbl text;
  ml text;
  slot text;
BEGIN
  -- monitor_list_* : users + users_NNNN
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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'symbol_wide_loss_prevention'
      ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_loss_prevention'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I RENAME COLUMN symbol_wide_loss_prevention TO simulated_trade_loss_prevention',
          sch, tbl
        );
        EXECUTE format(
          'ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_duration TO simulated_trade_cooldown_duration',
          sch, tbl
        );
        EXECUTE format(
          'ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_start_time TO simulated_trade_cooldown_start_time',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_loss_prevention'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN simulated_trade_loss_prevention BOOLEAN DEFAULT FALSE',
          sch, tbl
        );
        EXECUTE format(
          'UPDATE %I.%I SET simulated_trade_loss_prevention = FALSE WHERE simulated_trade_loss_prevention IS NULL',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_duration'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_duration INTEGER DEFAULT 4',
          sch, tbl
        );
        EXECUTE format(
          'UPDATE %I.%I SET simulated_trade_cooldown_duration = 4 WHERE simulated_trade_cooldown_duration IS NULL',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_start_time'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_start_time TIMESTAMPTZ',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'original_simulated_trade_cooldown_start_time'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN original_simulated_trade_cooldown_start_time TIMESTAMPTZ',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_loss_count'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_loss_count INTEGER NOT NULL DEFAULT 0',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'UPDATE %I.%I SET original_simulated_trade_cooldown_start_time = simulated_trade_cooldown_start_time
         WHERE COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
           AND simulated_trade_cooldown_start_time IS NOT NULL
           AND original_simulated_trade_cooldown_start_time IS NULL',
        sch, tbl
      );
    END LOOP;
  END LOOP;

  -- strategy_list_* + system.strategy_list_default
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
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'symbol_wide_loss_prevention'
    ) AND NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_loss_prevention'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I RENAME COLUMN symbol_wide_loss_prevention TO simulated_trade_loss_prevention',
        sch, tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_duration TO simulated_trade_cooldown_duration',
        sch, tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I RENAME COLUMN symbol_wide_cooldown_start_time TO simulated_trade_cooldown_start_time',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_loss_prevention'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN simulated_trade_loss_prevention BOOLEAN DEFAULT FALSE',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET simulated_trade_loss_prevention = FALSE WHERE simulated_trade_loss_prevention IS NULL',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_duration'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_duration INTEGER DEFAULT 4',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET simulated_trade_cooldown_duration = 4 WHERE simulated_trade_cooldown_duration IS NULL',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_start_time'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_start_time TIMESTAMPTZ',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'original_simulated_trade_cooldown_start_time'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN original_simulated_trade_cooldown_start_time TIMESTAMPTZ',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'simulated_trade_cooldown_loss_count'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN simulated_trade_cooldown_loss_count INTEGER NOT NULL DEFAULT 0',
        sch, tbl
      );
    END IF;

    EXECUTE format(
      'UPDATE %I.%I SET original_simulated_trade_cooldown_start_time = simulated_trade_cooldown_start_time
       WHERE COALESCE(simulated_trade_loss_prevention, FALSE) IS TRUE
         AND simulated_trade_cooldown_start_time IS NOT NULL
         AND original_simulated_trade_cooldown_start_time IS NULL',
      sch, tbl
    );
  END LOOP;

  -- Ledger: one table per monitor slot under schema users (legacy_users_sim_trade_lp_cycle_ledger)
  FOR ml IN
    SELECT DISTINCT t.table_name
    FROM information_schema.tables t
    WHERE t.table_type = 'BASE TABLE'
      AND (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_name ~ '^monitor_list_[0-9]{4}$'
    ORDER BY 1
  LOOP
    slot := substring(ml from 'monitor_list_(.+)');
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS users.sim_trade_lp_cycle_ledger_%s (
        monitor_id INTEGER NOT NULL,
        cycle_date DATE NOT NULL,
        weekly_cycle NUMERIC(10, 1) NOT NULL,
        applied_units INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (monitor_id, cycle_date, weekly_cycle)
      )',
      slot
    );
  END LOOP;
END
$$;
