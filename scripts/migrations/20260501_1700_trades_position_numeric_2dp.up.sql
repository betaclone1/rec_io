-- Fractional Kalshi contract fills: store trades / active_trades position to 2 decimal places.
-- Schemas: legacy `users` and tenant `users_NNNN`. Tables: `trades_*` (incl. `trades_simulated_*`) and `active_trades_*`.

DO $$
DECLARE
  sch text;
  tbl text;
  col_nullable text;
  col_type text;
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
        AND (t.table_name ~ '^trades_' OR t.table_name ~ '^active_trades_')
    LOOP
      SELECT c.is_nullable, c.data_type
      INTO col_nullable, col_type
      FROM information_schema.columns c
      WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'position';
      IF NOT FOUND THEN
        CONTINUE;
      END IF;
      IF col_type NOT IN ('integer', 'bigint', 'smallint') THEN
        CONTINUE;
      END IF;
      IF col_nullable = 'YES' THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN position TYPE NUMERIC(12,2) USING (
            CASE WHEN position IS NULL THEN NULL ELSE round(position::numeric, 2) END
          )',
          sch, tbl
        );
      ELSE
        EXECUTE format(
          'ALTER TABLE %I.%I ALTER COLUMN position TYPE NUMERIC(12,2) USING round(position::numeric, 2)',
          sch, tbl
        );
      END IF;
    END LOOP;
  END LOOP;
END
$$;
