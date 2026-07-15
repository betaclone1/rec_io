-- Snapshot monitor min_fill_price on each trade row at insert (0.0000 = gate disabled).

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
        AND (t.table_name ~ '^trades_[0-9]{4}$' OR t.table_name ~ '^trades_simulated_[0-9]{4}$')
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'min_fill_price'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN min_fill_price NUMERIC(6,4) NOT NULL DEFAULT 0.0000',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
