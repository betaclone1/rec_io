-- Revert live price feed UI real-time support.

DROP TRIGGER IF EXISTS live_symbol_status_rec_io_db_notify ON live_data.live_symbol_status;

