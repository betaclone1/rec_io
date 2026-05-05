-- Roll back performance rollup tables and NOTIFY triggers.

DO $$
DECLARE
  r RECORD;
  tname text;
BEGIN
  FOR r IN
    SELECT c.table_schema, c.table_name
    FROM information_schema.tables c
    WHERE c.table_type = 'BASE TABLE'
      AND c.table_schema ~ '^users_[0-9]{4}$'
      AND (c.table_name ~ '^performance_total_[0-9]{4}$' OR c.table_name ~ '^performance_monitors_[0-9]{4}$')
      AND substring(c.table_schema from '([0-9]{4})$') = substring(c.table_name from '([0-9]{4})$')
  LOOP
    tname := r.table_name || '_rec_io_db_notify';
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I.%I', tname, r.table_schema, r.table_name);
    EXECUTE format('DROP TABLE IF EXISTS %I.%I CASCADE', r.table_schema, r.table_name);
  END LOOP;
END;
$$;

DO $$
DECLARE
  r RECORD;
  tname text;
BEGIN
  FOR r IN
    SELECT c.table_name
    FROM information_schema.tables c
    WHERE c.table_type = 'BASE TABLE'
      AND c.table_schema = 'users'
      AND (c.table_name ~ '^performance_total_[0-9]{4}$' OR c.table_name ~ '^performance_monitors_[0-9]{4}$')
  LOOP
    tname := r.table_name || '_rec_io_db_notify';
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON users.%I', tname, r.table_name);
    EXECUTE format('DROP TABLE IF EXISTS users.%I CASCADE', r.table_name);
  END LOOP;
END;
$$;
