# CORRECT Root Cause Analysis: monitor_confirmed = FALSE for MOMENTUM BREAKOUT

## System Flow (Correct Understanding)

### 1. Trade Creation & Active Trades Table
- Trade created in `users.trades_0001` with `ticker` stored
- Trade added to `users.active_trades_{user}_{monitor}` with status='pending'
- When confirmed, status='active' and `high_price`/`low_price` initialized to `buy_price` (line 865-866)

### 2. Monitoring Loop (active_trade_supervisor)
- `start_monitoring_loop()` runs continuous loop (line 1630)
- Calls `update_active_trade_monitoring_data()` every iteration (line 1685)
- Only runs if there are active trades (line 1675-1682)

### 3. Update Monitoring Data (THE CRITICAL FUNCTION)
**File**: `backend/active_trade_supervisor.py:1325-1486`

```python
def update_active_trade_monitoring_data():
    # Get market snapshot
    snapshot_data = get_kalshi_market_snapshot()
    if not snapshot_data or "markets" not in snapshot_data:
        log("⚠️ Could not get Kalshi market snapshot, skipping monitoring update")
        return  # ⚠️ EXITS ENTIRELY - NO TRADES UPDATED
    
    # Get all active trades
    active_trades = get_all_active_trades()
    
    for each active_trade:
        # Get symbol price
        current_symbol_price = get_current_symbol_price(symbol)
        if current_symbol_price is None:
            continue  # Skip this trade
        
        # Get market price - CRITICAL POINT
        current_market_price = get_current_closing_price_for_trade(ticker, side)
        if current_market_price is None:
            log(f"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping")
            continue  # ⚠️ SKIPS ENTIRE UPDATE FOR THIS TRADE
        
        # Calculate position_value = 1 - current_market_price
        position_value = 1 - current_market_price
        
        # Update high_price and low_price
        new_high_price = max(current_high_price, position_value)
        new_low_price = min(current_low_price, position_value)
        
        # UPDATE active_trades table
        UPDATE users.active_trades_{table}
        SET high_price = %s, low_price = %s
        WHERE id = %s
```

### 4. Trade Closure (trade_manager)
- Calls `get_high_low_prices_from_active_trades(trade_id)` (line 813)
- Retrieves `high_price` and `low_price` from `active_trades` table
- Sets `monitor_confirmed = FALSE` if `high_price == low_price` (line 1727-1733)

## The Problem

**When `get_current_closing_price_for_trade()` returns `None`, the entire monitoring update for that trade is skipped (line 1373-1375), which means `high_price` and `low_price` are NEVER updated in the `active_trades` table.**

## Why get_current_closing_price_for_trade() Returns None

**File**: `backend/active_trade_supervisor.py:1216-1264`

```python
def get_current_closing_price_for_trade(trade_ticker: str, trade_side: str):
    snapshot_data = get_kalshi_market_snapshot()
    if not snapshot_data or "markets" not in snapshot_data:
        return None
    
    markets = snapshot_data["markets"]
    
    # Find matching ticker
    for market in markets:
        if market.get("ticker") == trade_ticker:  # ⚠️ EXACT STRING MATCH
            # Return price
            return closing_price
    
    log(f"⚠️ Market not found for ticker: {trade_ticker}")
    return None  # ⚠️ TICKER NOT FOUND
```

**Possible reasons for failure:**
1. Ticker format mismatch (whitespace, case, special characters)
2. Ticker not in market snapshot (market expired, not populated yet)
3. Market snapshot is empty or None
4. Different event_ticker (markets from different event cycles)

## What to Check

### 1. Is monitoring loop running?
Check logs for:
- `"📊 MONITORING: Starting monitoring loop for active trades"`
- `"💓 MONITORING HEARTBEAT: Monitoring loop healthy"`
- `"📊 MONITORING: Checking {count} active trades"`

### 2. Is get_kalshi_market_snapshot() working?
Check logs for:
- `"⚠️ Could not get Kalshi market snapshot, skipping monitoring update"`
- `"⚠️ No Kalshi market data found in PostgreSQL"`

### 3. Is get_current_closing_price_for_trade() failing?
Check logs for:
- `"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping"`
- `"⚠️ Market not found for ticker: {trade_ticker}"`
- `"⚠️ No closing price (_dollars) found for {trade_ticker} ({trade_side})"`

### 4. Are high_price/low_price being updated?
Check `active_trades` table:
```sql
SELECT trade_id, ticker, high_price, low_price, buy_price, last_updated
FROM users.active_trades_0001_XXXXX
WHERE status = 'active'
AND (high_price = low_price OR high_price IS NULL OR low_price IS NULL)
ORDER BY last_updated DESC;
```

## Database Queries to Diagnose

```sql
-- Check if trades have monitor_confirmed = FALSE
SELECT id, ticker, trade_strategy, high_price, low_price, monitor_confirmed, date, time
FROM users.trades_0001
WHERE monitor_confirmed = FALSE
AND trade_strategy LIKE '%Momentum Breakout%'
ORDER BY id DESC
LIMIT 50;

-- Check if tickers in active_trades match market snapshot
SELECT at.trade_id, at.ticker, at.symbol, at.high_price, at.low_price, at.buy_price, at.last_updated,
       CASE WHEN m.market_ticker IS NULL THEN 'NOT IN SNAPSHOT' ELSE 'IN SNAPSHOT' END as snapshot_status
FROM users.active_trades_0001_XXXXX at
LEFT JOIN live_data.market_kalshi_btc m ON m.market_ticker = at.ticker
WHERE at.status = 'active'
ORDER BY at.last_updated DESC;

-- Check market snapshot contents
SELECT COUNT(*) as market_count, 
       MIN(updated_at) as oldest_market, 
       MAX(updated_at) as newest_market,
       COUNT(DISTINCT event_ticker) as event_count
FROM live_data.market_kalshi_btc;
```

## Files to Review

1. **`backend/active_trade_supervisor.py`**
   - Line 1325-1486: `update_active_trade_monitoring_data()` - Main monitoring function
   - Line 1216-1264: `get_current_closing_price_for_trade()` - Ticker lookup
   - Line 1155-1214: `get_kalshi_market_snapshot()` - Market data retrieval
   - Line 1372-1375: **CRITICAL** - Skip when market price unavailable

2. **`backend/trade_manager.py`**
   - Line 874-942: `get_high_low_prices_from_active_trades()` - Retrieves values on closure
   - Line 1727-1733: Sets `monitor_confirmed` flag

## Next Steps

1. **Check logs** for the warning messages listed above
2. **Query database** to see if tickers exist in market snapshot
3. **Verify monitoring loop** is actually running
4. **Check ticker format** - compare stored ticker vs market_ticker in snapshot
5. **Check timing** - are trades being monitored before markets are populated?
