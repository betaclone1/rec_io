# Diagnosis Plan: Why get_current_closing_price_for_trade() Returns None

## The Problem

`get_current_closing_price_for_trade()` does an exact string match:
```python
if market.get("ticker") == trade_ticker:
```

If this match fails, it returns `None`, which causes the entire monitoring update to be skipped, preventing `high_price`/`low_price` from being updated.

## What We Need to Check

### 1. Ticker Format Comparison
- What ticker is stored in `users.trades_0001.ticker` for MOMENTUM BREAKOUT trades?
- What tickers are in `live_data.market_kalshi_{symbol}.market_ticker`?
- Are they exact matches? (whitespace, case, special characters)

### 2. Market Snapshot Query
- Does `get_kalshi_market_snapshot()` return markets that include the trade's ticker?
- Is the query filtering out the ticker somehow?
- Are markets from different `event_ticker` values being excluded?

### 3. Timing Issues
- When is the trade created vs when is the market snapshot queried?
- Is the market populated in the database when monitoring starts?
- Does the market get removed from the database before the trade closes?

## Database Queries to Run

```sql
-- 1. Get MOMENTUM BREAKOUT trades with monitor_confirmed = FALSE
SELECT id, ticker, trade_strategy, date, time, status, monitor_confirmed
FROM users.trades_0001
WHERE trade_strategy LIKE '%Momentum Breakout%'
AND monitor_confirmed = FALSE
ORDER BY id DESC
LIMIT 20;

-- 2. Check if those tickers exist in market_kalshi table
SELECT t.id, t.ticker as trade_ticker, 
       m.market_ticker, m.event_ticker, m.updated_at,
       CASE WHEN m.market_ticker IS NULL THEN 'NOT FOUND' ELSE 'FOUND' END as status
FROM users.trades_0001 t
LEFT JOIN live_data.market_kalshi_btc m ON m.market_ticker = t.ticker
WHERE t.trade_strategy LIKE '%Momentum Breakout%'
AND t.monitor_confirmed = FALSE
ORDER BY t.id DESC
LIMIT 20;

-- 3. Check what tickers ARE in the market snapshot
SELECT DISTINCT market_ticker, event_ticker, COUNT(*) as count, MAX(updated_at) as last_update
FROM live_data.market_kalshi_btc
GROUP BY market_ticker, event_ticker
ORDER BY last_update DESC
LIMIT 50;

-- 4. Check active_trades table for trades that aren't being updated
SELECT at.trade_id, at.ticker, at.symbol, at.high_price, at.low_price, at.buy_price, 
       at.last_updated, at.status,
       t.trade_strategy, t.monitor_confirmed
FROM users.active_trades_0001_XXXXX at
JOIN users.trades_0001 t ON t.id = at.trade_id
WHERE at.status = 'active'
AND (at.high_price = at.low_price OR at.high_price IS NULL OR at.low_price IS NULL)
AND t.trade_strategy LIKE '%Momentum Breakout%'
ORDER BY at.last_updated DESC;
```

## Log Messages to Check

1. `"⚠️ Market not found for ticker: {trade_ticker}"` - Ticker doesn't exist in snapshot
2. `"⚠️ No closing price (_dollars) found for {trade_ticker} ({trade_side})"` - Ticker found but price missing
3. `"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping"` - Update skipped
4. `"⚠️ Could not get Kalshi market snapshot, skipping monitoring update"` - Snapshot failed entirely
5. `"⚠️ No Kalshi market data found in PostgreSQL"` - Database empty

## Root Cause Hypotheses

1. **Ticker Format Mismatch**: Trade ticker format doesn't match market_ticker format
2. **Event Mismatch**: Trade is from Event A, but snapshot only has Event B markets
3. **Market Not Populated**: Market doesn't exist in database when monitoring runs
4. **Market Removed**: Market was in database but got removed/truncated before trade closed
5. **Symbol Mismatch**: Trade symbol doesn't match the symbol used in market snapshot query
