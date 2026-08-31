-- Reverse 20260829_2105_entry_stop_verification_align: restore verification_period_*.

DO $$
DECLARE
  sch text;
  tbl text;
  has_strategy boolean;
  has_name boolean;
  has_entry_en boolean;
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
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'entry_verification_period_enabled'
      ) INTO has_entry_en;

      IF has_entry_en THEN
        IF NOT EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch AND c.table_name = tbl
            AND c.column_name = 'verification_period_enabled'
        ) THEN
          EXECUTE format(
            'ALTER TABLE %I.%I ADD COLUMN verification_period_enabled BOOLEAN DEFAULT FALSE',
            sch, tbl
          );
        END IF;
        IF NOT EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch AND c.table_name = tbl
            AND c.column_name = 'verification_period_seconds'
        ) THEN
          EXECUTE format(
            'ALTER TABLE %I.%I ADD COLUMN verification_period_seconds INTEGER',
            sch, tbl
          );
        END IF;

        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'strategy'
        ) INTO has_strategy;
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns c
          WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'name'
        ) INTO has_name;

        IF has_strategy THEN
          EXECUTE format(
            $f$
            UPDATE %I.%I SET
              verification_period_enabled = COALESCE(entry_verification_period_enabled, FALSE),
              verification_period_seconds = entry_verification_period_seconds
            WHERE strategy ILIKE '%%Expiration Scalp%%'
               OR strategy ILIKE '%%High Water Scalp%%'
            $f$,
            sch, tbl
          );
          EXECUTE format(
            $f$
            UPDATE %I.%I SET
              verification_period_enabled = COALESCE(stop_verification_period_enabled, FALSE),
              verification_period_seconds = stop_verification_period_seconds
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
              verification_period_enabled = COALESCE(entry_verification_period_enabled, FALSE),
              verification_period_seconds = entry_verification_period_seconds
            WHERE name ILIKE '%%Expiration Scalp%%'
               OR name ILIKE '%%High Water Scalp%%'
            $f$,
            sch, tbl
          );
          EXECUTE format(
            $f$
            UPDATE %I.%I SET
              verification_period_enabled = COALESCE(stop_verification_period_enabled, FALSE),
              verification_period_seconds = stop_verification_period_seconds
            WHERE NOT (
              name ILIKE '%%Expiration Scalp%%'
              OR name ILIKE '%%High Water Scalp%%'
            )
            $f$,
            sch, tbl
          );
        END IF;

        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN entry_verification_period_enabled',
          sch, tbl
        );
        EXECUTE format(
          'ALTER TABLE %I.%I DROP COLUMN entry_verification_period_seconds',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list_default'
  ) THEN
    IF EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
        AND c.column_name = 'entry_verification_period_enabled'
    ) THEN
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
          AND c.column_name = 'verification_period_enabled'
      ) THEN
        ALTER TABLE system.strategy_list_default
          ADD COLUMN verification_period_enabled BOOLEAN DEFAULT FALSE;
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'system' AND c.table_name = 'strategy_list_default'
          AND c.column_name = 'verification_period_seconds'
      ) THEN
        ALTER TABLE system.strategy_list_default
          ADD COLUMN verification_period_seconds INTEGER;
      END IF;

      UPDATE system.strategy_list_default SET
        verification_period_enabled = COALESCE(entry_verification_period_enabled, FALSE),
        verification_period_seconds = entry_verification_period_seconds
      WHERE name ILIKE '%Expiration Scalp%' OR name ILIKE '%High Water Scalp%';

      UPDATE system.strategy_list_default SET
        verification_period_enabled = COALESCE(stop_verification_period_enabled, FALSE),
        verification_period_seconds = stop_verification_period_seconds
      WHERE NOT (name ILIKE '%Expiration Scalp%' OR name ILIKE '%High Water Scalp%');

      ALTER TABLE system.strategy_list_default DROP COLUMN entry_verification_period_enabled;
      ALTER TABLE system.strategy_list_default DROP COLUMN entry_verification_period_seconds;
    END IF;
  END IF;
END
$$;
