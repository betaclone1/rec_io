-- Per-monitor Kalshi subaccount assignment (id = Kalshi subaccount number).
-- Bankroll allotments use that subaccount's bankroll_current; default 1 = Master Trading Bankroll.

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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'subaccount'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN subaccount INTEGER NOT NULL DEFAULT 1',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.subaccount IS %L',
        sch, tbl,
        'Kalshi subaccount number (users_*.subaccounts_*.id). Bankroll allotment uses that subaccount bankroll_current. Default 1 = Master Trading Bankroll.'
      );
    END LOOP;
  END LOOP;
END
$$;
