-- Move ``updated_at`` to the last physical column on performance_total_* / performance_monitors_* (PG has no REORDER).

DO $$
DECLARE
  sch text;
  rel text;
BEGIN
  FOR sch IN
    SELECT nspname
    FROM pg_namespace
    WHERE nspname = 'users' OR nspname ~ '^users_[0-9]{4}$'
    ORDER BY 1
  LOOP
    FOR rel IN
      SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = sch
        AND c.relkind = 'r'
        AND (
          c.relname ~ '^performance_total_[0-9]{4}$'
          OR c.relname ~ '^performance_monitors_[0-9]{4}$'
        )
    LOOP
      IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns x
        WHERE x.table_schema = sch AND x.table_name = rel AND x.column_name = 'updated_at'
      ) THEN
        CONTINUE;
      END IF;
      IF EXISTS (
        SELECT 1 FROM information_schema.columns x
        WHERE x.table_schema = sch AND x.table_name = rel AND x.column_name = 'updated_at_migrate_tail'
      ) THEN
        CONTINUE;
      END IF;

      EXECUTE format(
        'ALTER TABLE %I.%I ADD COLUMN updated_at_migrate_tail TIMESTAMPTZ',
        sch, rel
      );
      EXECUTE format(
        'UPDATE %I.%I SET updated_at_migrate_tail = updated_at',
        sch, rel
      );
      EXECUTE format(
        'ALTER TABLE %I.%I DROP COLUMN updated_at',
        sch, rel
      );
      EXECUTE format(
        'ALTER TABLE %I.%I RENAME COLUMN updated_at_migrate_tail TO updated_at',
        sch, rel
      );
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN updated_at SET NOT NULL',
        sch, rel
      );
      EXECUTE format(
        'ALTER TABLE %I.%I ALTER COLUMN updated_at SET DEFAULT NOW()',
        sch, rel
      );
    END LOOP;
  END LOOP;
END
$$;
