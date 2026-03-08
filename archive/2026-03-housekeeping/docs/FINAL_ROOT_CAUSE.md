# FINAL ROOT CAUSE: Symbol Mismatch in get_current_closing_price_for_trade()

## The Bug

**File**: `backend/active_trade_supervisor.py`

### Line 1372: get_current_closing_price_for_trade() called WITHOUT trade's symbol
```python
for (..., ticker, symbol, ...) in active_trades:  # symbol is available here
    current_market_price = get_current_closing_price_for_trade(ticker, side)  # ⚠️ NO SYMBOL PASSED
```

### Line 1216-1228: Function doesn't accept symbol parameter
```python
def get_current_closing_price_for_trade(trade_ticker: str, trade_side: str) -> Optional[float]:
    # ⚠️ NO symbol parameter
    snapshot_data = get_kalshi_market_snapshot()  # Uses monitor's symbol, not trade's symbol
```

### Line 1155-1160: get_kalshi_market_snapshot() uses monitor's symbol
```python
def get_kalshi_market_snapshot(symbol: str = None) -> Optional[Dict[str, Any]]:
    if symbol is None:
        symbol = get_current_monitor_symbol()  # ⚠️ MONITOR'S SYMBOL
    
    cursor.execute(f"""
        SELECT ... FROM live_data.market_kalshi_{symbol.lower()}  # ⚠️ WRONG TABLE IF TRADE HAS DIFFERENT SYMBOL
    """)
```

## The Problem

1. Each trade has a `symbol` field (line 1359)
2. `get_current_closing_price_for_trade()` is called with `ticker` and `side`, but NOT `symbol` (line 1372)
3. Function calls `get_kalshi_market_snapshot()` which uses monitor's symbol (line 1228)
4. If trade's symbol != monitor's symbol, the ticker won't be found in the wrong table
5. Returns `None`, entire update skipped, `high_price`/`low_price` never updated

## Why MOMENTUM BREAKOUT on Monitor 10020 Specifically?

Monitor 10020 might have:
- Symbol configured as "BTC" 
- But trades created with symbol "ETH" (or vice versa)
- OR trades from a different symbol's strike table somehow

## The Fix

Change line 1372 to pass the trade's symbol:
```python
current_market_price = get_current_closing_price_for_trade(ticker, side, symbol)
```

And update the function signature:
```python
def get_current_closing_price_for_trade(trade_ticker: str, trade_side: str, symbol: str = None) -> Optional[float]:
    snapshot_data = get_kalshi_market_snapshot(symbol)  # Use trade's symbol
```

## Code Locations

1. **`backend/active_trade_supervisor.py:1372`** - Call site (needs symbol parameter)
2. **`backend/active_trade_supervisor.py:1216`** - Function definition (needs symbol parameter)
3. **`backend/active_trade_supervisor.py:1228`** - Snapshot call (needs to use symbol parameter)
