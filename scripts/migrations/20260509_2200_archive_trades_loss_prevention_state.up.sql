-- Align archive.trades_archive_{live|paper}_NNNN with users_<n>.trades_<n> for monitor archive INSERTs.

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
    IF NOT EXISTS (
      SELECT 1
      FROM information_schema.columns c
      WHERE c.table_schema = 'archive'
        AND c.table_name = r.table_name
        AND c.column_name = 'loss_prevention_state'
    ) THEN
      EXECUTE format(
        'ALTER TABLE archive.%I ADD COLUMN loss_prevention_state VARCHAR(64)',
        r.table_name
      );
    END IF;
  END LOOP;
END
$$;
