# ROOT CAUSE FOUND: Symbol Mismatch Bug

## The Bug

**File**: `backend/active_trade_supervisor.py`

### Line 1339: Snapshot queried with monitor's symbol
```python
snapshot_data = get_kalshi_market_snapshot()  # Uses monitor's symbol
```

### Line 1155-1160: get_kalshi_market_snapshot() uses monitor symbol
```python
def get_kalshi_market_snapshot(symbol: str = None) -> Optional[Dict[str, Any]]:
    if symbol is None:
        symbol = get_current_monitor_symbol()  # ⚠️ MONITOR'S SYMBOL, NOT TRADE'S
    
    cursor.execute(f"""
        SELECT ... FROM live_data.market_kalshi_{symbol.lower()}  # ⚠️ WRONG TABLE
    """)
```

### Line 1228: get_current_closing_price_for_trade() calls snapshot again
```python
def get_current_closing_price_for_trade(trade_ticker: str, trade_side: str):
    snapshot_data = get_kalshi_market_snapshot()  # ⚠️ AGAIN USES MONITOR'S SYMBOL
    # Tries to find trade_ticker in markets from monitor's symbol table
```

### Line 1359: Each trade has its own symbol
```python
for (..., ticker, symbol, ...) in active_trades:  # ⚠️ TRADE HAS ITS OWN SYMBOL
    current_market_price = get_current_closing_price_for_trade(ticker, side)
    # ⚠️ Ticker is from trade's symbol, but snapshot is from monitor's symbol!
```

## The Problem

If monitor 10020 is configured with symbol "BTC", but a MOMENTUM BREAKOUT trade has symbol "ETH":
1. `get_kalshi_market_snapshot()` queries `live_data.market_kalshi_btc`
2. Trade's ticker is from `live_data.market_kalshi_eth` markets
3. Ticker not found in BTC markets
4. Returns `None`
5. Entire update skipped
6. `high_price`/`low_price` never updated

## The Fix

`get_current_closing_price_for_trade()` should accept a `symbol` parameter and pass it to `get_kalshi_market_snapshot()`, OR `get_kalshi_market_snapshot()` should be called per-trade with the trade's symbol.

## Verification Query

```sql
-- Check if monitor 10020's trades have different symbols
SELECT t.id, t.ticker, t.symbol as trade_symbol, t.trade_strategy,
       m.symbol as monitor_symbol
FROM users.trades_0001 t
JOIN users.monitor_list_0001 m ON m.id = 10020
WHERE t.monitor = 'mon_0001_10020'
AND t.trade_strategy LIKE '%Momentum Breakout%'
AND t.symbol != m.symbol
ORDER BY t.id DESC;
```
