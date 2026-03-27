-- Real-time test / consumer hook: notify backbone when unified 15m strike rows change.

DROP TRIGGER IF EXISTS strike_table_15m_rec_io_db_notify ON live_data.strike_table_15m;
CREATE TRIGGER strike_table_15m_rec_io_db_notify
  AFTER INSERT OR UPDATE OR DELETE ON live_data.strike_table_15m
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();
