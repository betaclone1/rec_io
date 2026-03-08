-- Fix user_0001 table structure issues

-- Drop and recreate trades table with proper ticket_id type
DROP TABLE IF EXISTS users.trades_0001 CASCADE;

CREATE TABLE users.trades_0001 (
    id SERIAL PRIMARY KEY,
    status TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    symbol TEXT DEFAULT 'BTC',
    market TEXT DEFAULT 'Kalshi',
    trade_strategy TEXT DEFAULT 'Hourly HTC',
    contract TEXT NOT NULL,
    strike TEXT NOT NULL,
    side TEXT NOT NULL,
    prob REAL DEFAULT NULL,
    diff TEXT DEFAULT NULL,
    buy_price REAL NOT NULL,
    position INTEGER NOT NULL,
    sell_price REAL,
    closed_at TEXT,
    fees INTEGER,
    pnl INTEGER,
    symbol_open INTEGER,
    symbol_close INTEGER,
    momentum INTEGER,
    volatility INTEGER,
    win_loss TEXT,
    ticker TEXT,
    ticket_id TEXT,  -- Changed from INTEGER to TEXT
    market_id TEXT DEFAULT 'BTC-USD',
    momentum_delta REAL DEFAULT NULL,
    entry_method TEXT DEFAULT 'manual',
    close_method TEXT DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Drop and recreate positions table without unique constraint
DROP TABLE IF EXISTS users.positions_0001 CASCADE;

CREATE TABLE users.positions_0001 (
    id SERIAL PRIMARY KEY,
    ticker TEXT,
    total_traded INTEGER,
    position INTEGER,
    market_exposure INTEGER,
    realized_pnl REAL,
    fees_paid REAL,
    last_updated_ts TEXT,
    raw_json TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_trades_0001_date ON users.trades_0001(date);
CREATE INDEX IF NOT EXISTS idx_trades_0001_symbol ON users.trades_0001(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_0001_status ON users.trades_0001(status);
CREATE INDEX IF NOT EXISTS idx_trades_0001_ticket_id ON users.trades_0001(ticket_id);

CREATE INDEX IF NOT EXISTS idx_positions_0001_ticker ON users.positions_0001(ticker);

-- Recreate triggers
CREATE TRIGGER update_trades_0001_updated_at 
    BEFORE UPDATE ON users.trades_0001 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_positions_0001_updated_at 
    BEFORE UPDATE ON users.positions_0001 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column(); 