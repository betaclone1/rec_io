-- Move rec_io_db_notify to public so any schema can use it (DB-wide real-time change notifications).
-- Channel name matches PG_NOTIFY_CHANNEL (default rec_io_db_changes); switchboard LISTENs and publishes to Redis.

CREATE OR REPLACE FUNCTION public.rec_io_db_notify()
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

-- Point existing trigger to public function
DROP TRIGGER IF EXISTS redis_basic_test_notify ON testing.redis_basic_test;
CREATE TRIGGER redis_basic_test_notify
  AFTER INSERT OR UPDATE OR DELETE ON testing.redis_basic_test
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();

-- Remove from testing schema
DROP FUNCTION IF EXISTS testing.rec_io_db_notify();
