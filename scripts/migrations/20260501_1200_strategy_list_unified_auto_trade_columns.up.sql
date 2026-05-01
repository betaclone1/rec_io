-- Strategy defaults (strategy_list_* + system.strategy_list_default): align with monitor_list
-- unified / auto-trade fields — cooldowns, regime, Kalshi execution policy, symbol-wide LP, flip sell.
-- Idempotent ADD COLUMN / ADD CONSTRAINT. Scopes: legacy `users`, tenant `users_NNNN`, `system.strategy_list_default`.

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
  FOR sch, tbl IN
    SELECT t.table_schema, t.table_name
    FROM information_schema.tables t
    WHERE (t.table_schema = 'users' OR t.table_schema ~ '^users_[0-9]{4}$')
      AND t.table_name LIKE 'strategy_list_%'
    UNION ALL
    SELECT 'system'::text, 'strategy_list_default'::text
    WHERE EXISTS (
      SELECT 1 FROM information_schema.tables x
      WHERE x.table_schema = 'system' AND x.table_name = 'strategy_list_default'
    )
    ORDER BY 1, 2
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_cooldown_timer'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN min_cooldown_timer INTEGER DEFAULT 300',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET min_cooldown_timer = 300 WHERE min_cooldown_timer IS NULL',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'max_cooldown_timer'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN max_cooldown_timer INTEGER DEFAULT 3300',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET max_cooldown_timer = 3300 WHERE max_cooldown_timer IS NULL',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'regime_monitor_enabled'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN regime_monitor_enabled BOOLEAN DEFAULT FALSE',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET regime_monitor_enabled = FALSE WHERE regime_monitor_enabled IS NULL',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'regime_window'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN regime_window TEXT DEFAULT %L',
        sch, tbl, '30d'
      );
      EXECUTE format(
        'UPDATE %I.%I SET regime_window = %L WHERE regime_window IS NULL',
        sch, tbl, '30d'
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'time_in_force'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN time_in_force TEXT NOT NULL DEFAULT %L',
        sch, tbl, 'fill_or_kill'
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'order_type'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN order_type TEXT NOT NULL DEFAULT %L',
        sch, tbl, 'market'
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint c
      JOIN pg_class t ON c.conrelid = t.oid
      JOIN pg_namespace n ON t.relnamespace = n.oid
      WHERE n.nspname = sch AND t.relname = tbl AND c.conname = tbl || '_time_in_force_chk'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (time_in_force IN (%L, %L, %L))',
        sch, tbl, tbl || '_time_in_force_chk',
        'fill_or_kill', 'immediate_or_cancel', 'good_till_canceled'
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM pg_constraint c
      JOIN pg_class t ON c.conrelid = t.oid
      JOIN pg_namespace n ON t.relnamespace = n.oid
      WHERE n.nspname = sch AND t.relname = tbl AND c.conname = tbl || '_order_type_policy_chk'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (order_type IN (%L, %L))',
        sch, tbl, tbl || '_order_type_policy_chk',
        'limit', 'market'
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'symbol_wide_loss_prevention'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN symbol_wide_loss_prevention BOOLEAN DEFAULT FALSE',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET symbol_wide_loss_prevention = FALSE WHERE symbol_wide_loss_prevention IS NULL',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'symbol_wide_cooldown_duration'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN symbol_wide_cooldown_duration INTEGER DEFAULT 4',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET symbol_wide_cooldown_duration = 4 WHERE symbol_wide_cooldown_duration IS NULL',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'symbol_wide_cooldown_start_time'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN symbol_wide_cooldown_start_time TIMESTAMPTZ',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_prob'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN flip_sell_prob BOOLEAN NOT NULL DEFAULT FALSE',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_floor'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN flip_sell_floor BOOLEAN NOT NULL DEFAULT FALSE',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_prob_mult'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN flip_sell_prob_mult VARCHAR(32)',
        sch, tbl
      );
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'flip_sell_floor_mult'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN flip_sell_floor_mult VARCHAR(32)',
        sch, tbl
      );
    END IF;
  END LOOP;
END
$$;
