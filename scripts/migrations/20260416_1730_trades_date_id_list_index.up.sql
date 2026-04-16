-- Composite btree for trade list: date range filter + ORDER BY id DESC (GET /trades, keyset pages).
-- Supplements single-column idx_*_date; helps planner avoid large sorts on wide windows.

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
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I (date, id DESC)',
      idx_name,
      r.table_schema,
      r.table_name
    );
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
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I.%I (date, id DESC)',
      idx_name,
      r.table_schema,
      r.table_name
    );
  END LOOP;
END $$;
