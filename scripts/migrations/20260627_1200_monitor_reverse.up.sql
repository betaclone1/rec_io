-- Monitor REVERSE mode: when true, AES flips executed side at dispatch; auto-stop disabled.
-- Schemas: legacy `users` and tenant `users_NNNN`.

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
        WHERE c.table_schema = sch AND c.table_name = tbl AND c.column_name = 'reverse'
      ) THEN
        EXECUTE format(
          'ALTER TABLE %I.%I ADD COLUMN reverse BOOLEAN NOT NULL DEFAULT FALSE',
          sch, tbl
        );
      END IF;

      EXECUTE format(
        'COMMENT ON COLUMN %I.%I.reverse IS %L',
        sch, tbl,
        'When true, auto-entry dispatches the opposite side of the detected signal; auto-stop disabled; strategy displays as Reverse {strategy}.'
      );
    END LOOP;
  END LOOP;
END
$$;
