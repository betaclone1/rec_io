-- Unified 15m active trade tracking: one table per user, monitor_id column (one open trade per 15m monitor in practice).
CREATE TABLE IF NOT EXISTS users.active_trades_0001_15m (
    id SERIAL PRIMARY KEY,
    monitor_id VARCHAR(20) NOT NULL,
    trade_id INTEGER NOT NULL,
    ticket_id VARCHAR(50),
    date DATE,
    time TIME WITHOUT TIME ZONE,
    strike VARCHAR(50),
    side VARCHAR(10),
    buy_price DECIMAL(10,4),
    position INTEGER,
    contract VARCHAR(50),
    ticker VARCHAR(50),
    symbol VARCHAR(10),
    exchange VARCHAR(50),
    trade_strategy VARCHAR(50),
    symbol_open DECIMAL(10,2),
    momentum DECIMAL(5,2),
    prob DECIMAL(5,2),
    fees DECIMAL(10,4),
    diff DECIMAL(10,4),
    status VARCHAR(20) DEFAULT 'active',
    current_symbol_price DECIMAL(10,2),
    current_probability DECIMAL(5,2),
    buffer_from_entry DECIMAL(10,2),
    time_since_entry INTEGER,
    current_close_price DECIMAL(10,4),
    current_pnl VARCHAR(20),
    high_price DECIMAL(10,4),
    low_price DECIMAL(10,4),
    last_updated TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT active_trades_0001_15m_trade_id_key UNIQUE (trade_id)
);

CREATE INDEX IF NOT EXISTS idx_active_trades_0001_15m_monitor_status
    ON users.active_trades_0001_15m (monitor_id, status);
