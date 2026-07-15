DELETE FROM live_data.symbols_list WHERE UPPER(symbol) = 'DOGE';

DROP TABLE IF EXISTS live_data.live_price_ring_90m_doge;
DROP TABLE IF EXISTS live_data.price_change_doge;
DROP TABLE IF EXISTS live_data.live_price_log_1s_doge;
