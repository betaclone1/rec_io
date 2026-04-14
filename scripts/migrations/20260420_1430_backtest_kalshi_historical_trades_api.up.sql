-- Kalshi Trade API GET /historical/trades — store each Trade object field as-is (exploration / backtest).
-- See https://docs.kalshi.com/api-reference/historical/get-historical-trades

CREATE TABLE IF NOT EXISTS backtest.kalshi_historical_trades_api (
    trade_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    count_fp TEXT,
    yes_price_dollars TEXT,
    no_price_dollars TEXT,
    taker_side TEXT NOT NULL,
    created_time TIMESTAMP WITH TIME ZONE NOT NULL,
    ingested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (trade_id)
);

CREATE INDEX IF NOT EXISTS idx_kalshi_historical_trades_api_ticker
    ON backtest.kalshi_historical_trades_api (ticker);

CREATE INDEX IF NOT EXISTS idx_kalshi_historical_trades_api_created_time
    ON backtest.kalshi_historical_trades_api (created_time);
