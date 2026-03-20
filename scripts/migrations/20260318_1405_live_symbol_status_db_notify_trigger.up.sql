-- Live price feed UI real-time support:
-- Notify the real-time backbone whenever live_data.live_symbol_status changes.

DROP TRIGGER IF EXISTS live_symbol_status_rec_io_db_notify ON live_data.live_symbol_status;
CREATE TRIGGER live_symbol_status_rec_io_db_notify
  AFTER INSERT OR UPDATE OR DELETE ON live_data.live_symbol_status
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();

