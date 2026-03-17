-- Notify on any change to testing.redis_basic_test so Redis switchboard can push to WebSocket clients.
-- Uses a generic trigger function so other tables can use it later (e.g. rec_io_db_notify()).

CREATE OR REPLACE FUNCTION testing.rec_io_db_notify()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM pg_notify(
    'rec_io_db_changes',
    json_build_object(
      'schema', TG_TABLE_SCHEMA,
      'table', TG_TABLE_NAME,
      'op', TG_OP
    )::text
  );
  RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS redis_basic_test_notify ON testing.redis_basic_test;
CREATE TRIGGER redis_basic_test_notify
  AFTER INSERT OR UPDATE OR DELETE ON testing.redis_basic_test
  FOR EACH ROW
  EXECUTE PROCEDURE testing.rec_io_db_notify();
