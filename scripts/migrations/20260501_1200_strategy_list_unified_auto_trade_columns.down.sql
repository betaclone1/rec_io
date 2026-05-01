-- Reverse 20260501_1200_strategy_list_unified_auto_trade_columns.up.sql

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
    EXECUTE format(
      'ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I',
      sch, tbl, tbl || '_order_type_policy_chk'
    );
    EXECUTE format(
      'ALTER TABLE %I.%I DROP CONSTRAINT IF EXISTS %I',
      sch, tbl, tbl || '_time_in_force_chk'
    );

    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS flip_sell_floor_mult', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS flip_sell_prob_mult', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS flip_sell_floor', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS flip_sell_prob', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_cooldown_start_time', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_cooldown_duration', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_loss_prevention', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS order_type', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS time_in_force', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS regime_window', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS regime_monitor_enabled', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS max_cooldown_timer', sch, tbl);
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS min_cooldown_timer', sch, tbl);
  END LOOP;
END
$$;
