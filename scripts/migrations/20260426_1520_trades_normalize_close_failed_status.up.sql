-- Retire persisted `close_failed` on tenant trade tables: failed closes leave the row `open`
-- (see `trade_manager._mark_close_trade_failed`). Backfill any legacy rows.

DO $$
DECLARE
  sch text;
  tbl text;
  n bigint;
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
        AND (
          t.table_name ~ '^trades_[0-9]{4}$'
          OR t.table_name ~ '^trades_simulated_[0-9]{4}$'
        )
    LOOP
      IF EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = sch
          AND c.table_name = tbl
          AND c.column_name = 'status'
      ) THEN
        EXECUTE format(
          'UPDATE %I.%I SET status = %L WHERE status = %L',
          sch, tbl, 'open', 'close_failed'
        );
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n > 0 THEN
          RAISE NOTICE '20260426_1520: %.% — normalized % rows (close_failed → open)', sch, tbl, n;
        END IF;
      END IF;
    END LOOP;
  END LOOP;
END $$;
