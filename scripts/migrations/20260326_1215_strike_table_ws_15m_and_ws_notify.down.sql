DROP TRIGGER IF EXISTS market_kalshi_ws_15m_rec_io_db_notify_stmt ON live_data.market_kalshi_ws_15m;
DROP FUNCTION IF EXISTS public.rec_io_db_notify_stmt();

DROP INDEX IF EXISTS live_data.strike_table_ws_15m_exchange_symbol_timestamp_idx;
DROP INDEX IF EXISTS live_data.idx_strike_table_ws_15m_lookup;
DROP INDEX IF EXISTS live_data.strike_table_ws_15m_exchange_symbol_idx;
DROP TABLE IF EXISTS live_data.strike_table_ws_15m;
