-- NOTIFY on users.trades_0001 for real-time backbone (rec_io_db_notify → switchboard → Redis → /ws/db_changes).
-- Registry: backend/core/stream_registry.py maps (users, trades_0001) → stream "trades".

DROP TRIGGER IF EXISTS trades_0001_rec_io_db_notify ON users.trades_0001;

CREATE TRIGGER trades_0001_rec_io_db_notify
  AFTER INSERT OR UPDATE OR DELETE ON users.trades_0001
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();
