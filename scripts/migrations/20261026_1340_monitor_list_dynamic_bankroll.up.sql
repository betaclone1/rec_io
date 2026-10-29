-- Per-monitor dynamic_bankroll: when TRUE, bankroll_allotment_total tracks subaccount
-- sticky bankroll (HWM allotment sync). When FALSE (default), allotment is a static preset.

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
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'dynamic_bankroll'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN dynamic_bankroll BOOLEAN NOT NULL DEFAULT FALSE',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.dynamic_bankroll IS %L',
        sch, tbl,
        'When TRUE, bankroll_allotment_total tracks subaccount bankroll_current via allotment sync. When FALSE, allotment is a static user preset.'
      );
    END LOOP;
  END LOOP;
END
$$;
