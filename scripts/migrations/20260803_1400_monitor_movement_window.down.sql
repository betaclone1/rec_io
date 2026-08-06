-- Reverse Movement Window columns; revert min_probability to integer where we widened it.
-- Note: down loses decimal fraction on min_probability (ROUND to int).

DO $$
DECLARE
  sch text;
  tbl text;
BEGIN
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
        AND t.table_name LIKE 'monitor_list_%'
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_movement'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN min_movement', sch, tbl);
      END IF;
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'max_movement'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN max_movement', sch, tbl);
      END IF;

      -- Best-effort revert min_probability to integer (prod historical type)
      BEGIN
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN min_probability TYPE INTEGER USING ROUND(min_probability)::integer',
          sch, tbl
        );
      EXCEPTION WHEN OTHERS THEN
        NULL;
      END;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name LIKE 'strategy_list_%'
    LOOP
      BEGIN
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN min_probability TYPE INTEGER USING ROUND(min_probability)::integer',
          sch, tbl
        );
      EXCEPTION WHEN OTHERS THEN
        NULL;
      END;
    END LOOP;
  END LOOP;

  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'system' AND table_name = 'strategy_list'
  ) THEN
    BEGIN
      EXECUTE
        'ALTER TABLE system.strategy_list ALTER COLUMN min_probability TYPE INTEGER USING ROUND(min_probability)::integer';
    EXCEPTION WHEN OTHERS THEN
      NULL;
    END;
  END IF;
END $$;
