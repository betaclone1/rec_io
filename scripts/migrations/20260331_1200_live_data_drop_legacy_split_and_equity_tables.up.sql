-- Retire unused split-symbol 15m tables, equity (NDX/SPX) hourly feeds, legacy eth_price_log,
-- and WS-only strike duplicate. Unified tables remain: market_kalshi_15m, strike_table_15m,
-- market_kalshi_hourly_{btc,eth}, strike_table_hourly_{btc,eth}.

DROP TABLE IF EXISTS live_data.strike_table_ws_15m CASCADE;
DROP TABLE IF EXISTS live_data.strike_table_15m_btc CASCADE;
DROP TABLE IF EXISTS live_data.strike_table_15m_eth CASCADE;
DROP TABLE IF EXISTS live_data.strike_table_15m_sol CASCADE;
DROP TABLE IF EXISTS live_data.strike_table_15m_xrp CASCADE;
DROP TABLE IF EXISTS live_data.strike_table_hourly_ndx CASCADE;
DROP TABLE IF EXISTS live_data.strike_table_hourly_spx CASCADE;
DROP TABLE IF EXISTS live_data.market_kalshi_hourly_ndx CASCADE;
DROP TABLE IF EXISTS live_data.market_kalshi_hourly_spx CASCADE;
DROP TABLE IF EXISTS live_data.market_kalshi_15m_btc CASCADE;
DROP TABLE IF EXISTS live_data.market_kalshi_15m_eth CASCADE;
DROP TABLE IF EXISTS live_data.market_kalshi_15m_sol CASCADE;
DROP TABLE IF EXISTS live_data.market_kalshi_15m_xrp CASCADE;
DROP TABLE IF EXISTS live_data.live_price_log_1s_ndx CASCADE;
DROP TABLE IF EXISTS live_data.live_price_log_1s_spx CASCADE;
DROP TABLE IF EXISTS live_data.price_change_spx CASCADE;
DROP TABLE IF EXISTS live_data.eth_price_log CASCADE;
