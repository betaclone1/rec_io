-- REC.IO v2 PostgreSQL Database Schema
-- Generated: 2025-01-27
-- Updated: 2025-12-19
-- Version: 2.1

-- Create schemas
CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS live_data;
CREATE SCHEMA IF NOT EXISTS historical_data;

-- ============================================================================
-- USERS SCHEMA - User-specific data
-- ============================================================================

-- Trades table - Complete trade lifecycle tracking
CREATE TABLE IF NOT EXISTS users.trades_0001 (
    id SERIAL PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    symbol TEXT,
    market TEXT DEFAULT 'Kalshi',
    trade_strategy TEXT DEFAULT 'Hourly HTC',
    contract TEXT NOT NULL,
    strike TEXT NOT NULL,
    side TEXT NOT NULL,
    prob REAL,
    diff TEXT,
    buy_price REAL NOT NULL,
    position INTEGER NOT NULL,
    sell_price REAL,
    closed_at TEXT,
    fees REAL,
    pnl REAL,
    symbol_open REAL,
    symbol_close REAL,
    momentum INTEGER,
    win_loss TEXT,
    ticker TEXT,
    ticket_id TEXT,
    market_id TEXT,
    momentum_percentile REAL,
    entry_method TEXT DEFAULT 'manual',
    close_method TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    test_filter BOOLEAN DEFAULT FALSE,
    notes TEXT,
    monitor TEXT,
    bankroll REAL,
    ret_pct REAL,
    momentum_5s_avg NUMERIC,
    order_id TEXT,
    order_id_open TEXT,
    order_id_close TEXT,
    high_price NUMERIC DEFAULT NULL,
    low_price NUMERIC DEFAULT NULL,
    hour_idx SMALLINT,
    weekly_cycle SMALLINT,
    loss_prevention BOOLEAN DEFAULT FALSE,
    multiplier NUMERIC,
    price_spread NUMERIC,
    volatility_percentile NUMERIC,
    paper_trade BOOLEAN DEFAULT FALSE,
    cooldown_timer INTEGER,
    monitor_confirmed BOOLEAN DEFAULT FALSE,
    cycle_win_loss TEXT,
    cycle_pnl REAL,
    cycle_ret_pct REAL
);

-- Fills table - Order execution details
CREATE TABLE IF NOT EXISTS users.fills_0001 (
    id SERIAL PRIMARY KEY,
    trade_id TEXT UNIQUE,
    ticker TEXT,
    order_id TEXT,
    side TEXT,
    action TEXT,
    count INTEGER,
    yes_price REAL,
    no_price REAL,
    is_taker BOOLEAN,
    created_time TEXT,
    raw_json TEXT
);

-- Settlements table - Trade settlement data
CREATE TABLE IF NOT EXISTS users.settlements_0001 (
    id SERIAL PRIMARY KEY,
    ticker TEXT,
    market_result TEXT,
    yes_count INTEGER,
    yes_total_cost REAL,
    no_count INTEGER,
    no_total_cost REAL,
    revenue REAL,
    settled_time TEXT,
    raw_json TEXT
);

-- Positions table - Account position tracking
CREATE TABLE IF NOT EXISTS users.positions_0001 (
    id SERIAL PRIMARY KEY,
    ticker TEXT,
    position INTEGER,
    market_exposure REAL,
    fees_paid REAL,
    created_time TEXT,
    raw_json TEXT
);

-- ============================================================================
-- LIVE_DATA SCHEMA - Real-time market data
-- ============================================================================

-- BTC price log table - Real-time Bitcoin price data
CREATE TABLE IF NOT EXISTS live_data.btc_price_log (
    timestamp TEXT PRIMARY KEY,
    price NUMERIC(10,2),
    one_minute_avg NUMERIC(10,2),
    momentum NUMERIC(10,4),
    delta_1m NUMERIC(10,4),
    delta_2m NUMERIC(10,4),
    delta_3m NUMERIC(10,4),
    delta_4m NUMERIC(10,4),
    delta_15m NUMERIC(10,4),
    delta_30m NUMERIC(10,4)
);

-- Market data table - Kalshi market information
CREATE TABLE IF NOT EXISTS live_data.market_data (
    id SERIAL PRIMARY KEY,
    ticker TEXT,
    market_id TEXT,
    title TEXT,
    description TEXT,
    status TEXT,
    created_time TEXT,
    close_time TEXT,
    settlement_time TEXT,
    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    last_price REAL,
    volume INTEGER,
    raw_json TEXT
);

-- WebSocket market data table - Real-time updates
CREATE TABLE IF NOT EXISTS live_data.websocket_market_data (
    id SERIAL PRIMARY KEY,
    ticker TEXT,
    market_id TEXT,
    event_type TEXT,
    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    last_price REAL,
    volume INTEGER,
    timestamp TEXT,
    raw_json TEXT
);

-- Live strikes table - Real-time strike data
CREATE TABLE IF NOT EXISTS live_data.btc_live_strikes (
    id SERIAL PRIMARY KEY,
    ticker TEXT,
    strike_price REAL,
    yes_bid REAL,
    yes_ask REAL,
    no_bid REAL,
    no_ask REAL,
    last_price REAL,
    volume INTEGER,
    timestamp TEXT,
    raw_json TEXT
);

-- ============================================================================
-- HISTORICAL_DATA SCHEMA - Historical data archives
-- ============================================================================

-- Historical price data table
CREATE TABLE IF NOT EXISTS historical_data.price_history (
    id SERIAL PRIMARY KEY,
    symbol TEXT,
    timestamp TEXT,
    price REAL,
    volume REAL,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Historical momentum data table
CREATE TABLE IF NOT EXISTS historical_data.momentum_history (
    id SERIAL PRIMARY KEY,
    symbol TEXT,
    timestamp TEXT,
    momentum REAL,
    delta_1m REAL,
    delta_2m REAL,
    delta_3m REAL,
    delta_4m REAL,
    delta_15m REAL,
    delta_30m REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Trades table indexes
CREATE INDEX IF NOT EXISTS idx_trades_0001_status ON users.trades_0001(status);
CREATE INDEX IF NOT EXISTS idx_trades_0001_ticker ON users.trades_0001(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_0001_date ON users.trades_0001(date);
CREATE INDEX IF NOT EXISTS idx_trades_0001_ticket_id ON users.trades_0001(ticket_id);

-- Fills table indexes
CREATE INDEX IF NOT EXISTS idx_fills_0001_ticker ON users.fills_0001(ticker);
CREATE INDEX IF NOT EXISTS idx_fills_0001_trade_id ON users.fills_0001(trade_id);
CREATE INDEX IF NOT EXISTS idx_fills_0001_created_time ON users.fills_0001(created_time);

-- Settlements table indexes
CREATE INDEX IF NOT EXISTS idx_settlements_0001_ticker ON users.settlements_0001(ticker);
CREATE INDEX IF NOT EXISTS idx_settlements_0001_settled_time ON users.settlements_0001(settled_time);

-- Positions table indexes
CREATE INDEX IF NOT EXISTS idx_positions_0001_ticker ON users.positions_0001(ticker);
CREATE INDEX IF NOT EXISTS idx_positions_0001_created_time ON users.positions_0001(created_time);

-- BTC price log indexes
CREATE INDEX IF NOT EXISTS idx_btc_price_log_timestamp ON live_data.btc_price_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_btc_price_log_price ON live_data.btc_price_log(price);

-- Market data indexes
CREATE INDEX IF NOT EXISTS idx_market_data_ticker ON live_data.market_data(ticker);
CREATE INDEX IF NOT EXISTS idx_market_data_status ON live_data.market_data(status);
CREATE INDEX IF NOT EXISTS idx_market_data_created_time ON live_data.market_data(created_time);

-- WebSocket market data indexes
CREATE INDEX IF NOT EXISTS idx_websocket_market_data_ticker ON live_data.websocket_market_data(ticker);
CREATE INDEX IF NOT EXISTS idx_websocket_market_data_timestamp ON live_data.websocket_market_data(timestamp);

-- Live strikes indexes
CREATE INDEX IF NOT EXISTS idx_btc_live_strikes_ticker ON live_data.btc_live_strikes(ticker);
CREATE INDEX IF NOT EXISTS idx_btc_live_strikes_timestamp ON live_data.btc_live_strikes(timestamp);

-- Historical data indexes
CREATE INDEX IF NOT EXISTS idx_price_history_symbol ON historical_data.price_history(symbol);
CREATE INDEX IF NOT EXISTS idx_price_history_timestamp ON historical_data.price_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_momentum_history_symbol ON historical_data.momentum_history(symbol);
CREATE INDEX IF NOT EXISTS idx_momentum_history_timestamp ON historical_data.momentum_history(timestamp);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Active trades view
CREATE OR REPLACE VIEW users.active_trades_view AS
SELECT 
    id,
    ticker,
    status,
    buy_price,
    position,
    symbol_open,
    momentum,
    entry_method,
    date,
    time
FROM users.trades_0001
WHERE status IN ('pending', 'open', 'closing');

-- Recent trades view
CREATE OR REPLACE VIEW users.recent_trades_view AS
SELECT 
    id,
    ticker,
    status,
    buy_price,
    sell_price,
    pnl,
    win_loss,
    date,
    time,
    closed_at
FROM users.trades_0001
WHERE status IN ('closed', 'expired', 'settled')
ORDER BY id DESC
LIMIT 100;

-- Trade performance view
CREATE OR REPLACE VIEW users.trade_performance_view AS
SELECT 
    COUNT(*) as total_trades,
    COUNT(CASE WHEN win_loss = 'WIN' THEN 1 END) as wins,
    COUNT(CASE WHEN win_loss = 'LOSS' THEN 1 END) as losses,
    AVG(pnl) as avg_pnl,
    SUM(pnl) as total_pnl
FROM users.trades_0001
WHERE status IN ('closed', 'expired', 'settled');

-- ============================================================================
-- FUNCTIONS FOR DATA OPERATIONS
-- ============================================================================

-- Function to update trade status
CREATE OR REPLACE FUNCTION users.update_trade_status(
    p_trade_id INTEGER,
    p_status TEXT,
    p_closed_at TEXT DEFAULT NULL,
    p_sell_price REAL DEFAULT NULL,
    p_symbol_close REAL DEFAULT NULL,
    p_win_loss TEXT DEFAULT NULL,
    p_pnl REAL DEFAULT NULL,
    p_close_method TEXT DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
    UPDATE users.trades_0001
    SET 
        status = p_status,
        closed_at = COALESCE(p_closed_at, closed_at),
        sell_price = COALESCE(p_sell_price, sell_price),
        symbol_close = COALESCE(p_symbol_close, symbol_close),
        win_loss = COALESCE(p_win_loss, win_loss),
        pnl = COALESCE(p_pnl, pnl),
        close_method = COALESCE(p_close_method, close_method)
    WHERE id = p_trade_id;
END;
$$ LANGUAGE plpgsql;

-- Function to get trade statistics
CREATE OR REPLACE FUNCTION users.get_trade_statistics(
    p_start_date TEXT DEFAULT NULL,
    p_end_date TEXT DEFAULT NULL
)
RETURNS TABLE(
    total_trades BIGINT,
    wins BIGINT,
    losses BIGINT,
    win_rate NUMERIC,
    avg_pnl NUMERIC,
    total_pnl NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*)::BIGINT as total_trades,
        COUNT(CASE WHEN win_loss = 'WIN' THEN 1 END)::BIGINT as wins,
        COUNT(CASE WHEN win_loss = 'LOSS' THEN 1 END)::BIGINT as losses,
        ROUND(
            COUNT(CASE WHEN win_loss = 'WIN' THEN 1 END)::NUMERIC / 
            COUNT(*)::NUMERIC * 100, 2
        ) as win_rate,
        ROUND(AVG(pnl), 2) as avg_pnl,
        ROUND(SUM(pnl), 2) as total_pnl
    FROM users.trades_0001
    WHERE status IN ('closed', 'expired', 'settled')
    AND (p_start_date IS NULL OR date >= p_start_date)
    AND (p_end_date IS NULL OR date <= p_end_date);
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- TRIGGERS FOR DATA INTEGRITY
-- ============================================================================

-- Trigger to update trade timestamp on status change
CREATE OR REPLACE FUNCTION users.update_trade_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status != OLD.status THEN
        NEW.closed_at = CASE 
            WHEN NEW.status IN ('closed', 'expired', 'settled') 
            THEN CURRENT_TIMESTAMP::TEXT
            ELSE NEW.closed_at
        END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_trade_timestamp
    BEFORE UPDATE ON users.trades_0001
    FOR EACH ROW
    EXECUTE FUNCTION users.update_trade_timestamp();

-- ============================================================================
-- GRANTS AND PERMISSIONS
-- ============================================================================

-- Grant permissions to application user
GRANT USAGE ON SCHEMA users TO rec_io_user;
GRANT USAGE ON SCHEMA live_data TO rec_io_user;
GRANT USAGE ON SCHEMA historical_data TO rec_io_user;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA users TO rec_io_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA live_data TO rec_io_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA historical_data TO rec_io_user;

GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA users TO rec_io_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA live_data TO rec_io_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA historical_data TO rec_io_user;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA users TO rec_io_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA live_data TO rec_io_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA historical_data TO rec_io_user;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================

COMMENT ON SCHEMA users IS 'User-specific data including trades, positions, and account information';
COMMENT ON SCHEMA live_data IS 'Real-time market data and live trading information';
COMMENT ON SCHEMA historical_data IS 'Historical data archives and analytics';

COMMENT ON TABLE users.trades_0001 IS 'Complete trade lifecycle tracking for user_0001';
COMMENT ON TABLE users.fills_0001 IS 'Order execution details and fill information';
COMMENT ON TABLE users.settlements_0001 IS 'Trade settlement data and results';
COMMENT ON TABLE users.positions_0001 IS 'Account position tracking and exposure';

COMMENT ON TABLE live_data.btc_price_log IS 'Real-time Bitcoin price data with momentum calculations';
COMMENT ON TABLE live_data.market_data IS 'Kalshi market information and status';
COMMENT ON TABLE live_data.websocket_market_data IS 'Real-time market updates via WebSocket';
COMMENT ON TABLE live_data.btc_live_strikes IS 'Live strike price data for Bitcoin options';

-- ============================================================================
-- MIGRATION NOTES
-- ============================================================================

/*
Migration from SQLite to PostgreSQL completed:
- All tables migrated with proper data types
- Indexes created for performance optimization
- Views created for common queries
- Functions added for data operations
- Triggers implemented for data integrity
- Permissions configured for application user

Key improvements:
- Better data type support (NUMERIC for prices)
- Improved indexing and query performance
- Better concurrency handling
- Enhanced data integrity with triggers
- Scalable schema design for multiple users
*/
