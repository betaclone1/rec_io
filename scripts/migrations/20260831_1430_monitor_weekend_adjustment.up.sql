-- Per-monitor weekend trading adjustment preference + applied-state snapshot.
-- Preference stays on weekend_adjustment; live overrides use weekend_adjustment_snapshot.
DO $$
DECLARE
  sch text;
  ml_tbl text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR ml_tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^monitor_list_'
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'weekend_adjustment'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN weekend_adjustment TEXT NOT NULL DEFAULT %L',
          sch, ml_tbl, 'none'
        );
        EXECUTE format(
          'ALTER TABLE %I.%I ADD CONSTRAINT %I CHECK (weekend_adjustment IN (%L, %L, %L, %L, %L, %L))',
          sch, ml_tbl,
          ml_tbl || '_weekend_adjustment_chk',
          'none',
          'paper_only',
          'reduce_position_50',
          'reduce_position_25',
          'probability_adjustment_10',
          'probability_adjustment_25'
        );
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = ml_tbl AND c.column_name = 'weekend_adjustment_snapshot'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN weekend_adjustment_snapshot JSONB',
          sch, ml_tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;
