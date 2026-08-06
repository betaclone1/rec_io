-- Expiration Scalp Movement Window settings + decimal min_probability on monitor_list.
-- min_movement / max_movement: gate vs live ladder movement_percentile (0–100).
-- min_probability: prod still INTEGER on some tenants; align to numeric(5,2) like max_probability.
-- Also align strategy_list.min_probability (INTEGER → numeric(5,2)) so strategy defaults can carry decimals.

DO $$
DECLARE
  sch text;
  tbl text;
  full_type text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    -- monitor_list_*
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_movement'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN min_movement NUMERIC(5,2) DEFAULT 0.00',
          sch, tbl
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'max_movement'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN max_movement NUMERIC(5,2) DEFAULT 100.00',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'UPDATE %I.%I SET min_movement = 0.00 WHERE min_movement IS NULL',
        sch, tbl
      );
      EXECUTE format(
        'UPDATE %I.%I SET max_movement = 100.00 WHERE max_movement IS NULL',
        sch, tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN min_movement SET DEFAULT 0.00',
        sch, tbl
      );
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN max_movement SET DEFAULT 100.00',
        sch, tbl
      );

      SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
        INTO full_type
      FROM pg_attribute a
      JOIN pg_class t ON t.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
      WHERE n.nspname = sch
        AND t.relname = tbl
        AND a.attname = 'min_probability'
        AND NOT a.attisdropped;

      IF full_type IS NOT NULL AND full_type IS DISTINCT FROM 'numeric(5,2)' THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN min_probability TYPE NUMERIC(5,2) USING ROUND(min_probability::numeric, 2)',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.min_movement IS %L',
        sch, tbl,
        'Expiration Scalp: minimum movement_percentile (0–100) for entry. Default 0.00.'
      );
      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.max_movement IS %L',
        sch, tbl,
        'Expiration Scalp: maximum movement_percentile (0–100) for entry. Default 100.00.'
      );
    END LOOP;

    -- strategy_list_* min_probability INTEGER → numeric(5,2)
    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name LIKE 'strategy_list_%'
    LOOP
      SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
        INTO full_type
      FROM pg_attribute a
      JOIN pg_class t ON t.oid = a.attrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
      WHERE n.nspname = sch
        AND t.relname = tbl
        AND a.attname = 'min_probability'
        AND NOT a.attisdropped;

      IF full_type IS NOT NULL AND full_type IS DISTINCT FROM 'numeric(5,2)' THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN min_probability TYPE NUMERIC(5,2) USING ROUND(min_probability::numeric, 2)',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;

  -- system.strategy_list (shared template, if present)
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list'
  ) THEN
    SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
      INTO full_type
    FROM pg_attribute a
    JOIN pg_class t ON t.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'system'
      AND t.relname = 'strategy_list'
      AND a.attname = 'min_probability'
      AND NOT a.attisdropped;

    IF full_type IS NOT NULL AND full_type IS DISTINCT FROM 'numeric(5,2)' THEN
      EXECUTE
        'ALTER TABLE system.strategy_list ALTER COLUMN min_probability TYPE NUMERIC(5,2) USING ROUND(min_probability::numeric, 2)';
    END IF;
  END IF;
END $$;
