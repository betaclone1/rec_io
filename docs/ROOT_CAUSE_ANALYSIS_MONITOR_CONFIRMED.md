# ROOT CAUSE ANALYSIS: monitor_confirmed = FALSE for MOMENTUM BREAKOUT

## Executive Summary

**Root Cause**: When Kalshi event cycles change (hourly), the `market_kalshi_{symbol}` table is completely TRUNCATED, removing all markets from the previous event. Active trades from the previous event can no longer find their tickers in the market snapshot, causing monitoring updates to be skipped, which prevents `high_price` and `low_price` from being updated.

## The Problem Chain

### 1. Trade Creation (Working Correctly)
- MOMENTUM BREAKOUT trade is created with ticker from strike table
- Ticker is stored in `users.trades_0001.ticker` column
- Example: `"KXBTCD-25JAN1515-T119499.99"` (Event: KXBTCD-25JAN1515)

### 2. Event Cycle Change (The Breaking Point)
**File**: `backend/kalshi_market_watchdog.py:390-404`

```python
if previous_event_ticker and previous_event_ticker != event_ticker:
    print(f"[{datetime.now(EST)}] 🔄 Market changed: {previous_event_ticker} → {event_ticker}")
    print(f"[{datetime.now(EST)}] 🧹 Cleaning up old market data...")
    
    # Truncate table to remove old market data
    connection = connect_database()
    if connection:
        cursor = connection.cursor()
        table_name = f"live_data.market_kalshi_{SYMBOL.lower()}"
        cursor.execute(f"TRUNCATE TABLE {table_name}")  # ⚠️ REMOVES ALL MARKETS
        connection.commit()
        connection.close()
```

**Impact**: When event changes (e.g., 2pm → 3pm), ALL markets from the previous event are deleted from the database.

### 3. Monitoring Attempt (Fails)
**File**: `backend/active_trade_supervisor.py:1155-1214`

```python
def get_kalshi_market_snapshot(symbol: str = None) -> Optional[Dict[str, Any]]:
    # Get market data from PostgreSQL
    cursor.execute(f"""
        SELECT 
            market_ticker,
            yes_ask,
            no_ask,
            yes_ask_dollars,
            no_ask_dollars,
            volume,
            event_ticker,
            strike
        FROM live_data.market_kalshi_{symbol.lower()}
        ORDER BY updated_at DESC  # ⚠️ NO FILTER BY event_ticker
    """)
```

**Problem**: This query gets ALL markets from the current event only (because old events were truncated). It does NOT filter by the trade's original `event_ticker`.

### 4. Ticker Lookup Failure
**File**: `backend/active_trade_supervisor.py:1216-1264`

```python
def get_current_closing_price_for_trade(trade_ticker: str, trade_side: str) -> Optional[float]:
    snapshot_data = get_kalshi_market_snapshot()
    markets = snapshot_data["markets"]
    
    # Find the market that matches the trade ticker
    for market in markets:
        if market.get("ticker") == trade_ticker:  # ⚠️ TICKER NOT FOUND (was truncated)
            # ... return price
    log(f"⚠️ Market not found for ticker: {trade_ticker}")  # ⚠️ THIS HAPPENS
    return None
```

**Result**: Returns `None` because the ticker from the previous event no longer exists in the table.

### 5. Monitoring Update Skipped
**File**: `backend/active_trade_supervisor.py:1372-1375`

```python
current_market_price = get_current_closing_price_for_trade(ticker, side)
if current_market_price is None:
    log(f"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping")
    continue  # ⚠️ ENTIRE UPDATE SKIPPED
```

**Impact**: When `current_market_price` is `None`, the entire monitoring update for that trade is skipped, including the `high_price` and `low_price` updates.

### 6. Trade Closure (monitor_confirmed = FALSE)
**File**: `backend/trade_manager.py:1727-1733`

```python
monitor_confirmed = False
if final_high_price is not None and final_low_price is not None:
    if final_high_price != final_low_price:
        monitor_confirmed = True
    else:
        log(f"⚠️ Trade {trade_id}: monitor_confirmed = FALSE (high_price == low_price = {final_high_price})")
```

**Result**: Since `high_price` and `low_price` were never updated (remained at initial `buy_price`), they are equal, so `monitor_confirmed = FALSE`.

## Why MOMENTUM BREAKOUT Specifically?

1. **Timing**: MOMENTUM BREAKOUT trades are created during momentum spikes, which often occur near the end of an event cycle
2. **Event Transition**: When the event changes (new hour), markets are truncated before the trade can be properly monitored
3. **No Event Tracking**: Trades don't store which `event_ticker` they belong to, so monitoring can't filter by the original event

## Evidence

### Code Locations

1. **Market Truncation**: `backend/kalshi_market_watchdog.py:401`
   - `TRUNCATE TABLE` removes all markets when event changes

2. **No Event Filtering**: `backend/active_trade_supervisor.py:1181`
   - Query doesn't filter by `event_ticker`, only gets current event's markets

3. **Skip on Failure**: `backend/active_trade_supervisor.py:1373-1375`
   - Entire monitoring update skipped when market price unavailable

### Comparison: Strike Table Generator (Works Correctly)

**File**: `backend/strike_table_generator.py:536-557`

```python
# Get the latest event_ticker from the market_kalshi_{symbol} table
cursor.execute(f"""
    SELECT event_ticker 
    FROM live_data.market_kalshi_{self.symbol} 
    ORDER BY updated_at DESC 
    LIMIT 1
""")
event_ticker = result[0]

# Get all markets for this event_ticker
cursor.execute(f"""
    SELECT market_ticker, ...
    FROM live_data.market_kalshi_{self.symbol} 
    WHERE event_ticker = %s  # ✅ FILTERS BY event_ticker
    ORDER BY updated_at DESC
""", (event_ticker,))
```

**Why This Works**: Strike table generator filters by `event_ticker`, so it only gets markets from the current event. But this doesn't help active trades from previous events.

## The Fix (Not Implemented - Diagnosis Only)

### Option 1: Don't Truncate, Archive Instead
- Instead of `TRUNCATE`, mark old events as `archived` or `inactive`
- Keep markets from previous events for active trades
- Filter by `event_ticker` when looking up markets for trades

### Option 2: Store event_ticker with Trades
- Add `event_ticker` column to `users.trades_0001` table
- Store the event_ticker when trade is created
- Filter market snapshot lookup by the trade's original `event_ticker`

### Option 3: Use Historical Market Data
- Don't rely on `market_kalshi` table for active trades
- Use a different data source that maintains historical market data
- Or query Kalshi API directly for the specific ticker

### Option 4: Graceful Degradation
- Don't skip entire monitoring update when market price unavailable
- Continue updating `high_price`/`low_price` using last known price or symbol-based fallback
- Only skip if absolutely necessary

## Database Queries to Verify

```sql
-- Check for trades with monitor_confirmed = FALSE
SELECT id, ticker, monitor, trade_strategy, high_price, low_price, monitor_confirmed, date, time
FROM users.trades_0001
WHERE monitor_confirmed = FALSE
AND trade_strategy LIKE '%Momentum Breakout%'
ORDER BY id DESC
LIMIT 50;

-- Check if tickers exist in current market snapshot
SELECT t.id, t.ticker, t.trade_strategy, 
       CASE WHEN m.market_ticker IS NULL THEN 'NOT FOUND' ELSE 'FOUND' END as ticker_status
FROM users.trades_0001 t
LEFT JOIN live_data.market_kalshi_btc m ON m.market_ticker = t.ticker
WHERE t.trade_strategy LIKE '%Momentum Breakout%'
AND t.status = 'closed'
AND t.monitor_confirmed = FALSE
ORDER BY t.id DESC
LIMIT 20;

-- Check event_ticker distribution in market_kalshi table
SELECT event_ticker, COUNT(*) as market_count, MAX(updated_at) as last_update
FROM live_data.market_kalshi_btc
GROUP BY event_ticker
ORDER BY last_update DESC;
```

## Files Involved

1. **`backend/kalshi_market_watchdog.py`** (lines 390-404)
   - Truncates market table on event change

2. **`backend/active_trade_supervisor.py`** (lines 1155-1214, 1216-1264, 1372-1375)
   - Gets market snapshot without event filtering
   - Looks up ticker (fails for old events)
   - Skips update when ticker not found

3. **`backend/trade_manager.py`** (lines 1727-1733)
   - Sets monitor_confirmed based on high_price/low_price

4. **`backend/strike_table_generator.py`** (lines 536-557)
   - Correctly filters by event_ticker (reference implementation)

## Timeline of Failure

1. **Trade Created**: Ticker stored from current event (e.g., `KXBTCD-25JAN1515-T119499.99`)
2. **Event Changes**: New event starts (e.g., `KXBTCD-25JAN1616`)
3. **Table Truncated**: All markets from `KXBTCD-25JAN1515` deleted
4. **Monitoring Runs**: Tries to find ticker `KXBTCD-25JAN1515-T119499.99`
5. **Ticker Not Found**: Returns `None`
6. **Update Skipped**: `high_price`/`low_price` never updated
7. **Trade Closes**: `high_price == low_price`, so `monitor_confirmed = FALSE`

## Conclusion

The root cause is a **data lifecycle management issue**: the system aggressively cleans up old market data (truncation) without considering that active trades still need access to those markets for monitoring. The monitoring system doesn't have a way to access historical market data for trades from previous events.
