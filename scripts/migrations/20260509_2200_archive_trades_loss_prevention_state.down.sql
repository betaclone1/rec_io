DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'archive'
      AND table_type = 'BASE TABLE'
      AND table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
    ORDER BY table_name
  LOOP
    IF EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = 'archive'
        AND c.table_name = r.table_name
        AND c.column_name = 'loss_prevention_state'
    ) THEN
      EXECUTE format(
        'ALTER TABLE archive.%I DROP COLUMN loss_prevention_state',
        r.table_name
      );
    END IF;
  END LOOP;
END
$$;
