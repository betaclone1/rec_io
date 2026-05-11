-- Symbol-wide loss prevention state published from user_0001 hero monitors.
--
-- New model:
--   live_data.live_symbol_status mirrors the configured hero monitor's time-based
--   LP state/cooldowns per symbol.
--   monitor_list_*/strategy_list_* symbol_wide_loss_prevention is an independent
--   opt-in boolean for following that symbol-wide state.

ALTER TABLE live_data.live_symbol_status
  ADD COLUMN IF NOT EXISTS monitor_follow TEXT,
  ADD COLUMN IF NOT EXISTS monitor_follow_id INTEGER,
  ADD COLUMN IF NOT EXISTS loss_prevention_state VARCHAR(50) DEFAULT 'off',
  ADD COLUMN IF NOT EXISTS loss_prevention_duration INTEGER DEFAULT 4,
  ADD COLUMN IF NOT EXISTS simulated_loss_prevention_cooldown_start_time TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS original_loss_prevention_cooldown_start_time TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS loss_prevention_cooldown_loss_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS live_loss_prevention_cooldown_start_time TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS loss_prevention_updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

UPDATE live_data.live_symbol_status
SET loss_prevention_state = 'off'
WHERE loss_prevention_state IS NULL OR btrim(loss_prevention_state) = '';

UPDATE live_data.live_symbol_status
SET loss_prevention_duration = 4
WHERE loss_prevention_duration IS NULL OR loss_prevention_duration < 1;

UPDATE live_data.live_symbol_status
SET loss_prevention_cooldown_loss_count = 0
WHERE loss_prevention_cooldown_loss_count IS NULL;

COMMENT ON COLUMN live_data.live_symbol_status.monitor_follow IS
  'Hero monitor name from user_0001 whose LP state this symbol follows.';
COMMENT ON COLUMN live_data.live_symbol_status.monitor_follow_id IS
  'Resolved user_0001 monitor_list_0001 id for monitor_follow.';
COMMENT ON COLUMN live_data.live_symbol_status.loss_prevention_state IS
  'Symbol-wide LP state copied from the hero monitor; non-off states carry _symbol_wide suffix.';
COMMENT ON COLUMN live_data.live_symbol_status.loss_prevention_updated_at IS
  'Last time symbol-wide LP fields were synced from the hero monitor.';

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
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'symbol_wide_loss_prevention'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN symbol_wide_loss_prevention BOOLEAN DEFAULT FALSE',
        sch, tbl
      );
    END IF;

    -- The previous meaning of this column was deprecated. Start the new opt-in as disabled.
    EXECUTE format(
      'UPDATE %I.%I SET symbol_wide_loss_prevention = FALSE WHERE symbol_wide_loss_prevention IS DISTINCT FROM FALSE',
      sch, tbl
    );

    EXECUTE format(
      'COMMENT ON COLUMN %I.%I.symbol_wide_loss_prevention IS %L',
      sch, tbl,
      'When true, monitor effective LP state follows live_data.live_symbol_status for its symbol.'
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
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'symbol_wide_loss_prevention'
    ) THEN
      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN symbol_wide_loss_prevention BOOLEAN DEFAULT FALSE',
        sch, tbl
      );
    END IF;

    EXECUTE format(
      'UPDATE %I.%I SET symbol_wide_loss_prevention = FALSE WHERE symbol_wide_loss_prevention IS DISTINCT FROM FALSE',
      sch, tbl
    );

    EXECUTE format(
      'COMMENT ON COLUMN %I.%I.symbol_wide_loss_prevention IS %L',
      sch, tbl,
      'Default opt-in for monitors to follow live_data.live_symbol_status symbol-wide LP state.'
    );
  END LOOP;
END
$$;
