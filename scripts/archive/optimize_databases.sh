#!/bin/bash

echo "🔧 OPTIMIZING DATABASES..."

# Optimize trades.db
echo "  Optimizing trades.db..."
sqlite3 backend/data/users/user_0001/trade_history/trades.db << 'SQL'
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_ticket_id ON trades(ticket_id);
ANALYZE;
VACUUM;
SQL

# Optimize active_trades.db
echo "  Optimizing active_trades.db..."
sqlite3 backend/data/users/user_0001/active_trades/active_trades.db << 'SQL'
CREATE INDEX IF NOT EXISTS idx_active_trades_symbol ON active_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_active_trades_status ON active_trades(status);
ANALYZE;
VACUUM;
SQL

# Optimize price history
echo "  Optimizing btc_price_history.db..."
sqlite3 backend/data/live_data/price_history/btc_price_history.db << 'SQL'
CREATE INDEX IF NOT EXISTS idx_price_timestamp ON price_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_history(symbol);
ANALYZE;
VACUUM;
SQL

# Optimize account databases
echo "  Optimizing account databases..."
for db in backend/data/users/user_0001/accounts/kalshi/*/*.db; do
    if [ -f "$db" ]; then
        echo "    Optimizing $(basename $db)..."
        sqlite3 "$db" << 'SQL'
ANALYZE;
VACUUM;
SQL
    fi
done

echo "✅ Database optimization complete" 