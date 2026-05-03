-- Store trade PnL at 6 decimal places (aligned with buy/sell NUMERIC(12,6) and fee precision from the API).
-- Tenant schemas: legacy `users` and `users_NNNN`. Tables: `trades_*`, `trades_simulated_*`.
-- Archive: `archive.trades_archive_live_*`, `archive.trades_archive_paper_*`.

DO $$
DECLARE
  sch text;
  tbl text;
  dt text;
  prec int;
  sc int;
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
      SELECT c.data_type::text,
             c.numeric_precision::int,
             c.numeric_scale::int
      INTO dt, prec, sc
      FROM information_schema.columns c
      WHERE c.table_schema = sch
        AND c.table_name = tbl
        AND c.column_name = 'pnl';
      IF NOT FOUND THEN
        CONTINUE;
      END IF;
      IF dt = 'numeric' AND prec = 12 AND sc = 6 THEN
        CONTINUE;
      END IF;
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN pnl TYPE NUMERIC(12,6) USING '
        'CASE WHEN pnl IS NULL THEN NULL ELSE round(pnl::numeric, 6) END',
        sch,
        tbl
      );
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
    SELECT c.data_type::text,
           c.numeric_precision::int,
           c.numeric_scale::int
    INTO dt, prec, sc
    FROM information_schema.columns c
    WHERE c.table_schema = 'archive'
      AND c.table_name = tbl
      AND c.column_name = 'pnl';
    IF NOT FOUND THEN
      CONTINUE;
    END IF;
    IF dt = 'numeric' AND prec = 12 AND sc = 6 THEN
      CONTINUE;
    END IF;
    EXECUTE format(
      'ALTER TABLE archive.%I ALTER COLUMN pnl TYPE NUMERIC(12,6) USING '
      'CASE WHEN pnl IS NULL THEN NULL ELSE round(pnl::numeric, 6) END',
      tbl
    );
  END LOOP;
END
$$;
