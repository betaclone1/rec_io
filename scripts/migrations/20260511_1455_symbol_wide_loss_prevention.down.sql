-- Reverse symbol-wide loss prevention schema additions.

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
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_loss_prevention', sch, tbl);
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
    EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS symbol_wide_loss_prevention', sch, tbl);
  END LOOP;
END
$$;

ALTER TABLE live_data.live_symbol_status
  DROP COLUMN IF EXISTS loss_prevention_updated_at,
  DROP COLUMN IF EXISTS live_loss_prevention_cooldown_start_time,
  DROP COLUMN IF EXISTS loss_prevention_cooldown_loss_count,
  DROP COLUMN IF EXISTS original_loss_prevention_cooldown_start_time,
  DROP COLUMN IF EXISTS simulated_loss_prevention_cooldown_start_time,
  DROP COLUMN IF EXISTS loss_prevention_duration,
  DROP COLUMN IF EXISTS loss_prevention_state,
  DROP COLUMN IF EXISTS monitor_follow_id,
  DROP COLUMN IF EXISTS monitor_follow;
