# MOMENTUM BREAKOUT monitor_confirmed Diagnosis Report

## Problem Summary
MOMENTUM BREAKOUT monitors stopped recording high_price and low_price values during active trade lifetime, resulting in `monitor_confirmed = FALSE` for closed trades.

## Root Cause Analysis

### The Monitoring Flow

1. **Monitoring Loop** (`active_trade_supervisor.py:1630-1716`)
   - `start_monitoring_loop()` runs a continuous loop
   - Calls `update_active_trade_monitoring_data()` every iteration
   - Only runs if there are active trades

2. **Update Monitoring Data** (`active_trade_supervisor.py:1325-1486`)
   - Gets Kalshi market snapshot
   - For each active trade:
     - Gets current symbol price
     - **CRITICAL**: Gets current market price via `get_current_closing_price_for_trade(ticker, side)`
     - If market price is `None`, **SKIPS ENTIRE TRADE UPDATE** (line 1373-1375)
     - If not skipped, calculates position_value and updates high_price/low_price

3. **Get Closing Price** (`active_trade_supervisor.py:1216-1264`)
   - Does exact string match: `market.get("ticker") == trade_ticker` (line 1236)
   - If no match found, returns `None`
   - Logs: `"⚠️ Market not found for ticker: {trade_ticker}"`

4. **Trade Closure** (`trade_manager.py:642-870`)
   - When trade closes, calls `get_high_low_prices_from_active_trades(trade_id)`
   - Retrieves high_price and low_price from active_trades table
   - If values were never updated (because monitoring was skipped), they remain at initial `buy_price`
   - Sets `monitor_confirmed = FALSE` if `high_price == low_price` (line 1727-1733)

## Critical Failure Point

**Location**: `active_trade_supervisor.py:1372-1375`

```python
current_market_price = get_current_closing_price_for_trade(ticker, side)
if current_market_price is None:
    log(f"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping")
    continue  # ⚠️ THIS SKIPS THE ENTIRE UPDATE, INCLUDING high_price/low_price
```

**Impact**: When `get_current_closing_price_for_trade()` returns `None`, the entire monitoring update for that trade is skipped, meaning:
- `high_price` and `low_price` are never updated
- They remain at initial `buy_price` value
- When trade closes, `high_price == low_price`, so `monitor_confirmed = FALSE`

## Why Ticker Matching Fails

**Location**: `active_trade_supervisor.py:1236`

```python
if market.get("ticker") == trade_ticker:
```

This exact string match can fail if:

1. **Ticker Format Mismatch**
   - Ticker stored in trades table doesn't exactly match ticker in market snapshot
   - Possible causes:
     - Different formatting (whitespace, case, special characters)
     - Ticker stored incorrectly during trade creation
     - Market snapshot uses different ticker format

2. **Missing Market Data**
   - Market not present in `live_data.market_kalshi_{symbol}` table
   - Market expired and removed from snapshot
   - Market not yet populated when monitoring starts

3. **Timing Issues**
   - Market snapshot updated before trade is created
   - Market snapshot doesn't include the specific ticker for MOMENTUM CONTAIN trades

## Why MOMENTUM BREAKOUT Specifically?

MOMENTUM BREAKOUT trades might be affected more because:

1. **Ticker Source**: Tickers come from `strike_above_data.get('ticker')` and `strike_below_data.get('ticker')` in `check_auto_entry_conditions_momentum_breakout()` (lines 3302, 3325)
2. **Strike Table Format**: The ticker format from strike table might not match the format in market snapshot
3. **Market Availability**: MOMENTUM BREAKOUT trades might use tickers that are less commonly in the market snapshot
4. **Timing**: MOMENTUM BREAKOUT activates during momentum spikes, which might create trades before markets are fully populated in the snapshot

## Evidence Points

### Log Messages to Look For

1. **During Monitoring**:
   - `"⚠️ Could not get market price for trade {trade_id} ({ticker}), skipping"`
   - `"⚠️ Market not found for ticker: {trade_ticker}"`
   - `"⚠️ No closing price (_dollars) found for {trade_ticker} ({trade_side})"`

2. **During Trade Closure**:
   - `"⚠️ Trade {trade_id}: monitor_confirmed = FALSE (high_price == low_price = {high_price})"`
   - `"⚠️ FAILSAFE: Trade {id} has high_price == low_price - ATS was not monitoring correctly"`

### Database Queries to Verify

```sql
-- Check for trades with monitor_confirmed = FALSE
SELECT id, ticker, monitor, trade_strategy, high_price, low_price, monitor_confirmed
FROM users.trades_0001
WHERE monitor_confirmed = FALSE
AND trade_strategy LIKE '%Momentum Breakout%'
ORDER BY id DESC
LIMIT 50;

-- Check if tickers in trades match market snapshot
SELECT DISTINCT t.ticker, t.trade_strategy
FROM users.trades_0001 t
WHERE t.trade_strategy LIKE '%Momentum Breakout%'
AND t.status = 'closed'
AND NOT EXISTS (
    SELECT 1 FROM live_data.market_kalshi_btc m
    WHERE m.market_ticker = t.ticker
)
LIMIT 20;

-- Check active trades that might be failing to update
SELECT at.trade_id, at.ticker, at.symbol, at.status, at.high_price, at.low_price, at.last_updated
FROM users.active_trades_0001_XXXXX at
WHERE at.status = 'active'
AND at.high_price = at.low_price
ORDER BY at.last_updated DESC;
```

## System Components Involved

1. **active_trade_supervisor.py**
   - `update_active_trade_monitoring_data()` - Main monitoring function
   - `get_current_closing_price_for_trade()` - Ticker matching logic
   - `get_kalshi_market_snapshot()` - Market data retrieval
   - `start_monitoring_loop()` - Monitoring loop orchestration

2. **trade_manager.py**
   - `get_high_low_prices_from_active_trades()` - Retrieves values on closure
   - `update_trade_status_with_ret_pct()` - Sets monitor_confirmed flag
   - `confirm_close_trade()` - Trade closure orchestration

3. **auto_entry_supervisor.py**
   - `check_auto_entry_conditions_momentum_breakout()` - Creates MOMENTUM BREAKOUT trades (lines 3083-3352)
   - `trigger_auto_entry_trade()` - Stores ticker in trades table (line 2242)

## Potential Fixes (NOT IMPLEMENTED - DIAGNOSIS ONLY)

1. **Improve Ticker Matching**
   - Use fuzzy matching or normalization
   - Handle case sensitivity
   - Strip whitespace and special characters
   - Add fallback matching strategies

2. **Handle Missing Market Data Gracefully**
   - Don't skip entire update if market price unavailable
   - Use last known price or symbol-based fallback
   - Continue updating high_price/low_price even if market price unavailable

3. **Add Logging and Monitoring**
   - Log ticker mismatches with details
   - Track which trades are being skipped
   - Alert when monitor_confirmed = FALSE

4. **Verify Ticker Storage**
   - Ensure ticker format is consistent between:
     - Strike table → Trade creation → Active trades table → Market snapshot
   - Add validation during trade creation

## Next Steps

1. **Verify the Issue**
   - Check logs for "Could not get market price" messages
   - Query database for trades with monitor_confirmed = FALSE
   - Compare ticker formats between trades and market snapshot

2. **Identify Root Cause**
   - Check if ticker format mismatch exists
   - Verify market snapshot contains MOMENTUM CONTAIN tickers
   - Check timing of market snapshot updates vs trade creation

3. **Implement Fix**
   - Based on root cause, implement appropriate solution
   - Add comprehensive logging
   - Test with MOMENTUM CONTAIN trades

## Files to Review

- `/opt/rec_io_server/backend/active_trade_supervisor.py` (lines 1216-1264, 1325-1486)
- `/opt/rec_io_server/backend/trade_manager.py` (lines 874-942, 1666-1754)
- `/opt/rec_io_server/backend/auto_entry_supervisor.py` (lines 3083-3352 for MOMENTUM BREAKOUT trade creation)
