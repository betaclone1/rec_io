-- NOTIFY on users_<slot>.monitor_list_<slot> for every tenant (same pattern as 20260412_2000 trades).
-- stream_registry.resolve_stream_for_notify maps users_NNNN.monitor_list_NNNN → stream "monitor_list".

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
      AND c.table_name ~ '^monitor_list_[0-9]{4}$'
      AND substring(c.table_schema from '([0-9]{4})$') = substring(c.table_name from 'monitor_list_([0-9]{4})$')
  LOOP
    tname := r.table_name || '_rec_io_db_notify';
    EXECUTE format(
      'DROP TRIGGER IF EXISTS %I ON %I.%I',
      tname, r.table_schema, r.table_name
    );
    EXECUTE format(
      'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I.%I FOR EACH ROW EXECUTE PROCEDURE public.rec_io_db_notify()',
      tname, r.table_schema, r.table_name
    );
  END LOOP;
END;
$$;
