-- Reverse VER4 MTB shape columns.

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
        AND t.table_name ~ '^subaccounts(_paper)?_[0-9]{4}$'
      ORDER BY 1
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'mtb_weight_pct'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN mtb_weight_pct', sch, tbl);
      END IF;
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'in_mtb'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN in_mtb', sch, tbl);
      END IF;
    END LOOP;

    FOR tbl IN
      SELECT t.table_name
      FROM information_schema.tables t
      WHERE t.table_schema = sch
        AND t.table_name ~ '^system_settings_[0-9]{4}$'
      ORDER BY 1
    LOOP
      IF EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = sch AND c.table_name = tbl
          AND c.column_name = 'mtb_base_value_cents'
      ) THEN
        EXECUTE format('ALTER TABLE %I.%I DROP COLUMN mtb_base_value_cents', sch, tbl);
      END IF;
    END LOOP;
  END LOOP;
END
$$;
