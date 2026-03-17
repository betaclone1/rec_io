-- Add NOTIFY trigger on users.account_balance_0001 so account/bankroll/portfolio streams
-- can flow through the real-time backbone (public.rec_io_db_notify → switchboard → Redis/WS).
-- See docs/REALTIME_BACKBONE.md and docs/MASTER_DB_SCHEMA_REFERENCE.md (Real-time section).

CREATE TRIGGER account_balance_0001_db_notify
  AFTER INSERT OR UPDATE OR DELETE ON users.account_balance_0001
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();

