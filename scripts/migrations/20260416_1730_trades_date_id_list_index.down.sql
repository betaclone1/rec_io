DO $$
DECLARE
  r RECORD;
  idx_name text;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_schema ~ '^users_[0-9]{4}$'
      AND table_name ~ '^trades_[0-9]{4}$'
      AND substring(table_schema from '([0-9]{4})$') = substring(table_name from 'trades_([0-9]{4})$')
  LOOP
    idx_name := r.table_name || '_date_id_desc_idx';
    EXECUTE format('DROP INDEX IF EXISTS %I.%I', r.table_schema, idx_name);
  END LOOP;
END $$;

DO $$
DECLARE
  r RECORD;
  idx_name text;
BEGIN
  FOR r IN
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
      AND table_schema = 'archive'
      AND table_name ~ '^trades_archive_(live|paper)_[0-9]{4}$'
  LOOP
    idx_name := r.table_name || '_date_id_desc_idx';
    EXECUTE format('DROP INDEX IF EXISTS %I.%I', r.table_schema, idx_name);
  END LOOP;
END $$;
