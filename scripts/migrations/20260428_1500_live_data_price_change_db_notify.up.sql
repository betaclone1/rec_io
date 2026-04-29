-- Fan out Trade Monitor left-panel percent changes via redis_switchboard live_symbol_spot
-- (same path as live_symbol_status).

DROP TRIGGER IF EXISTS price_change_btc_rec_io_db_notify ON live_data.price_change_btc;
CREATE TRIGGER price_change_btc_rec_io_db_notify
  AFTER INSERT OR UPDATE ON live_data.price_change_btc
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();

DROP TRIGGER IF EXISTS price_change_eth_rec_io_db_notify ON live_data.price_change_eth;
CREATE TRIGGER price_change_eth_rec_io_db_notify
  AFTER INSERT OR UPDATE ON live_data.price_change_eth
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();

DROP TRIGGER IF EXISTS price_change_sol_rec_io_db_notify ON live_data.price_change_sol;
CREATE TRIGGER price_change_sol_rec_io_db_notify
  AFTER INSERT OR UPDATE ON live_data.price_change_sol
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();

DROP TRIGGER IF EXISTS price_change_xrp_rec_io_db_notify ON live_data.price_change_xrp;
CREATE TRIGGER price_change_xrp_rec_io_db_notify
  AFTER INSERT OR UPDATE ON live_data.price_change_xrp
  FOR EACH ROW
  EXECUTE PROCEDURE public.rec_io_db_notify();
