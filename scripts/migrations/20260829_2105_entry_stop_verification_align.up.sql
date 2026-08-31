-- Align verification columns: entry vs stop for all strategies.
-- Renames overloaded verification_period_* → entry_verification_period_*.
-- HTC / Momentum / etc stop dwell moves into stop_verification_period_*.
-- Exp Scalp / High Water Scalp entry dwell moves into entry_verification_period_*.

DO $$
DECLARE
  sch text;
  tbl text;
  has_strategy boolean;
  has_name boolean;
  has_old_en boolean;
  has_old_sec boolean;
BEGIN
  FOR sch IN
    SELECT nspname FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR tbl IN
      SELECT t.table_name FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND (t.table_name LIKE 'monitor_list_%' OR t.table_name LIKE 'strategy_list_%')
    LOOP
      -- Ensure stop_* exist (idempotent; already added by 20260829_1815 on most DBs)
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

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'entry_verification_period_enabled'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN entry_verification_period_enabled BOOLEAN DEFAULT FALSE',
          sch, tbl
        );
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'entry_verification_period_seconds'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN entry_verification_period_seconds INTEGER',
          sch, tbl
        );
      END IF;

      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'verification_period_enabled'
      ) INTO has_old_en;
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'verification_period_seconds'
      ) INTO has_old_sec;

      IF has_old_en AND has_old_sec THEN
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'strategy'
        ) INTO has_strategy;
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'name'
        ) INTO has_name;

        IF has_strategy THEN
          -- Entry strategies: old verification_* was entry dwell
          EXECUTE format(
            $f$
            UPDATE %I.%I SET
              entry_verification_period_enabled = COALESCE(verification_period_enabled, FALSE),
              entry_verification_period_seconds = verification_period_seconds
            WHERE strategy ILIKE '%%Expiration Scalp%%'
               OR strategy ILIKE '%%High Water Scalp%%'
            $f$,
            sch, tbl
          );
          -- All other strategies: old verification_* was stop dwell
          EXECUTE format(
            $f$
            UPDATE %I.%I SET
              stop_verification_period_enabled = COALESCE(verification_period_enabled, FALSE),
              stop_verification_period_seconds = COALESCE(verification_period_seconds, stop_verification_period_seconds, 1)
            WHERE NOT (
              strategy ILIKE '%%Expiration Scalp%%'
              OR strategy ILIKE '%%High Water Scalp%%'
            )
            $f$,
            sch, tbl
          );
        ELSIF has_name THEN
          EXECUTE format(
            $f$
            UPDATE %I.%I SET
              entry_verification_period_enabled = COALESCE(verification_period_enabled, FALSE),
              entry_verification_period_seconds = verification_period_seconds
            WHERE name ILIKE '%%Expiration Scalp%%'
               OR name ILIKE '%%High Water Scalp%%'
            $f$,
            sch, tbl
          );
          EXECUTE format(
            $f$
            UPDATE %I.%I SET
              stop_verification_period_enabled = COALESCE(verification_period_enabled, FALSE),
              stop_verification_period_seconds = COALESCE(verification_period_seconds, stop_verification_period_seconds, 1)
            WHERE NOT (
              name ILIKE '%%Expiration Scalp%%'
              OR name ILIKE '%%High Water Scalp%%'
            )
            $f$,
            sch, tbl
          );
        END IF;

        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN verification_period_enabled',
          sch, tbl
        );
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN verification_period_seconds',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.entry_verification_period_enabled IS %L',
        sch, tbl,
        'Entry dwell gate (Expiration Scalp / High Water Scalp). Migration 20260829_2105_entry_stop_verification_align.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.entry_verification_period_seconds IS %L',
        sch, tbl,
        'Entry dwell seconds. Migration 20260829_2105_entry_stop_verification_align.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.stop_verification_period_enabled IS %L',
        sch, tbl,
        'Auto-stop dwell gate (HTC / Momentum / High Water Scalp floor). Migration 20260829_2105_entry_stop_verification_align.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.stop_verification_period_seconds IS %L',
        sch, tbl,
        'Auto-stop dwell seconds. Migration 20260829_2105_entry_stop_verification_align.'
      );
    END LOOP;
  END LOOP;

  -- system.strategy_list_default
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
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'entry_verification_period_enabled'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN entry_verification_period_enabled BOOLEAN DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'entry_verification_period_seconds'
    ) THEN
      ALTER TABLE system.strategy_list_default
        ADD COLUMN entry_verification_period_seconds INTEGER;
    END IF;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'verification_period_enabled'
    ) THEN
      UPDATE system.strategy_list_default SET
        entry_verification_period_enabled = COALESCE(verification_period_enabled, FALSE),
        entry_verification_period_seconds = verification_period_seconds
      WHERE name ILIKE '%Expiration Scalp%' OR name ILIKE '%High Water Scalp%';

      UPDATE system.strategy_list_default SET
        stop_verification_period_enabled = COALESCE(verification_period_enabled, FALSE),
        stop_verification_period_seconds = COALESCE(verification_period_seconds, stop_verification_period_seconds, 1)
      WHERE NOT (name ILIKE '%Expiration Scalp%' OR name ILIKE '%High Water Scalp%');

      ALTER TABLE system.strategy_list_default DROP COLUMN verification_period_enabled;
      ALTER TABLE system.strategy_list_default DROP COLUMN verification_period_seconds;
    END IF;
  END IF;
END
$$;
