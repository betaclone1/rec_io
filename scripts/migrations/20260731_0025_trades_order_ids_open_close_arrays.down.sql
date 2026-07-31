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
      ORDER BY t.table_name
    LOOP
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS order_ids_open', sch, tbl);
      EXECUTE format('ALTER TABLE %I.%I DROP COLUMN IF EXISTS order_ids_close', sch, tbl);
    END LOOP;
  END LOOP;

  FOR tbl IN
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'archive'
      AND t.table_type = 'BASE TABLE'
      AND t.table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY t.table_name
  LOOP
    EXECUTE format('ALTER TABLE archive.%I DROP COLUMN IF EXISTS order_ids_open', tbl);
    EXECUTE format('ALTER TABLE archive.%I DROP COLUMN IF EXISTS order_ids_close', tbl);
  END LOOP;
END
$$;
