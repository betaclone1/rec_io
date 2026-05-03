-- Revert trade PnL column to REAL (previous catalog shape on most environments).

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
        AND t.table_type = 'BASE TABLE'
        AND (
          t.table_name ~ '^trades_[0-9]{4}$'
          OR t.table_name ~ '^trades_simulated_[0-9]{4}$'
        )
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'pnl'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN pnl TYPE REAL USING pnl::real',
          sch,
          tbl
        );
      END IF;
    END LOOP;
  END LOOP;

  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND (
        t.table_name ~ '^trades_archive_live_[0-9]{4}$'
        OR t.table_name ~ '^trades_archive_paper_[0-9]{4}$'
      )
  LOOP
    EXECUTE format(
      'ALTER TABLE archive.%I ALTER COLUMN pnl TYPE REAL USING pnl::real',
      tbl
    );
  END LOOP;
END
$$;
