# Trade Logs Cross-Reference with Price History - Analysis Guide

## Overview

Yes, you can cross-reference trade logs with the `historical_data.btc_price_history` table to analyze market conditions leading up to, during, and after trades. Both systems use **EST/EDT timestamps**, making this analysis straightforward.

---

## Trade Table Structure

### Key Timestamp Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `date` | `TEXT` | Trade date in EST | `'2026-02-04'` |
| `time` | `TEXT` | Trade time in EST | `'14:45:13'` |
| `created_at` | `timestamp with time zone` | Record creation timestamp | `2026-02-04 14:45:13 EST` |

### Trade Data Fields Available for Analysis

| Field | Description | Use Case |
|-------|-------------|----------|
| `symbol` | Trading symbol (BTC, ETH, etc.) | Filter trades by symbol |
| `buy_price` | Entry price | Compare with market price |
| `sell_price` | Exit price | Calculate actual vs expected returns |
| `pnl` | Profit and Loss | Performance analysis |
| `momentum_percentile` | Momentum at trade entry | Market condition analysis |
| `volatility_percentile` | Volatility at trade entry | Risk assessment |
| `symbol_open` | BTC price at trade open | Price alignment check |
| `symbol_close` | BTC price at trade close | Price alignment check |

---

## Cross-Reference Methods

### Method 1: Exact Time Match (During Trade)

Join trades with price history at the exact minute of trade entry. Note: Trades have second precision (`14:45:13`) while price history has minute precision (`14:45:00`), so we round to the nearest minute:

```sql
SELECT 
    t.id as trade_id,
    t.date,
    t.time,
    t.symbol,
    t.buy_price as trade_entry_price,
    t.pnl,
    t.momentum_percentile as trade_momentum_pct,
    t.volatility_percentile as trade_volatility_pct,
    p.timestamp as price_timestamp,
    p.close as market_price_at_entry,
    p.momentum as market_momentum,
    p.momentum_percentile as market_momentum_pct,
    p.volatility_percentile as market_volatility_pct,
    -- Price alignment check
    ABS(t.symbol_open - p.close) as price_difference
FROM users.trades_0001 t
LEFT JOIN historical_data.btc_price_history p 
    ON DATE(p.timestamp)::text = t.date 
    AND DATE_TRUNC('minute', t.time::time)::time = p.timestamp::time
WHERE t.symbol = 'BTC'
    AND t.date >= '2026-01-01'
ORDER BY t.date DESC, t.time DESC;
```

**Alternative: Nearest Minute Match** (handles edge cases better):

```sql
SELECT 
    t.id as trade_id,
    t.date,
    t.time,
    t.symbol,
    t.buy_price as trade_entry_price,
    t.pnl,
    p.timestamp as price_timestamp,
    p.close as market_price_at_entry,
    p.momentum_percentile as market_momentum_pct,
    p.volatility_percentile as market_volatility_pct
FROM users.trades_0001 t
LEFT JOIN LATERAL (
    SELECT timestamp, close, momentum_percentile, volatility_percentile
    FROM historical_data.btc_price_history
    WHERE DATE(timestamp)::text = t.date 
        AND timestamp::time >= DATE_TRUNC('minute', t.time::time)::time
        AND timestamp::time < (DATE_TRUNC('minute', t.time::time) + INTERVAL '1 minute')::time
    ORDER BY ABS(EXTRACT(EPOCH FROM (timestamp - (t.date || ' ' || t.time)::timestamp)))
    LIMIT 1
) p ON true
WHERE t.symbol = 'BTC'
    AND t.date >= '2026-01-01'
ORDER BY t.date DESC, t.time DESC;
```

### Method 2: Market Conditions Before Trade (Leading Up)

Analyze market conditions in the minutes/hours before trade entry:

```sql
SELECT 
    t.id as trade_id,
    t.date,
    t.time,
    t.buy_price as trade_entry_price,
    t.pnl,
    -- Market conditions 30 minutes before trade
    p_30m.timestamp as price_30m_before,
    p_30m.close as price_30m_before,
    p_30m.momentum_percentile as momentum_30m_before,
    p_30m.volatility_percentile as volatility_30m_before,
    -- Market conditions 15 minutes before trade
    p_15m.timestamp as price_15m_before,
    p_15m.close as price_15m_before,
    p_15m.momentum_percentile as momentum_15m_before,
    -- Market conditions 5 minutes before trade
    p_5m.timestamp as price_5m_before,
    p_5m.close as price_5m_before,
    p_5m.momentum_percentile as momentum_5m_before,
    -- Market conditions at trade entry
    p_entry.timestamp as price_at_entry,
    p_entry.close as market_price_at_entry,
    p_entry.momentum_percentile as momentum_at_entry,
    p_entry.volatility_percentile as volatility_at_entry
FROM users.trades_0001 t
LEFT JOIN historical_data.btc_price_history p_entry
    ON DATE(p_entry.timestamp)::text = t.date 
    AND p_entry.timestamp::time = t.time::time
LEFT JOIN historical_data.btc_price_history p_5m
    ON DATE(p_5m.timestamp)::text = t.date 
    AND p_5m.timestamp = (p_entry.timestamp - INTERVAL '5 minutes')
LEFT JOIN historical_data.btc_price_history p_15m
    ON DATE(p_15m.timestamp)::text = t.date 
    AND p_15m.timestamp = (p_entry.timestamp - INTERVAL '15 minutes')
LEFT JOIN historical_data.btc_price_history p_30m
    ON DATE(p_30m.timestamp)::text = t.date 
    AND p_30m.timestamp = (p_entry.timestamp - INTERVAL '30 minutes')
WHERE t.symbol = 'BTC'
    AND t.date >= '2026-01-01'
ORDER BY t.date DESC, t.time DESC;
```

### Method 3: Market Conditions After Trade (Following)

Analyze market conditions after trade entry to see if momentum continued:

```sql
SELECT 
    t.id as trade_id,
    t.date,
    t.time,
    t.buy_price as trade_entry_price,
    t.sell_price as trade_exit_price,
    t.pnl,
    -- Market conditions at trade entry
    p_entry.timestamp as price_at_entry,
    p_entry.close as market_price_at_entry,
    p_entry.momentum_percentile as momentum_at_entry,
    -- Market conditions 5 minutes after trade
    p_5m.timestamp as price_5m_after,
    p_5m.close as market_price_5m_after,
    p_5m.momentum_percentile as momentum_5m_after,
    -- Market conditions 15 minutes after trade
    p_15m.timestamp as price_15m_after,
    p_15m.close as market_price_15m_after,
    p_15m.momentum_percentile as momentum_15m_after,
    -- Market conditions 30 minutes after trade
    p_30m.timestamp as price_30m_after,
    p_30m.close as market_price_30m_after,
    p_30m.momentum_percentile as momentum_30m_after,
    -- Market conditions 60 minutes after trade (1 hour)
    p_60m.timestamp as price_60m_after,
    p_60m.close as market_price_60m_after,
    p_60m.momentum_percentile as momentum_60m_after,
    -- Calculate price movement after trade
    (p_60m.close - p_entry.close) / p_entry.close * 100 as price_change_pct_1h
FROM users.trades_0001 t
LEFT JOIN historical_data.btc_price_history p_entry
    ON DATE(p_entry.timestamp)::text = t.date 
    AND p_entry.timestamp::time = t.time::time
LEFT JOIN historical_data.btc_price_history p_5m
    ON DATE(p_5m.timestamp)::text = t.date 
    AND p_5m.timestamp = (p_entry.timestamp + INTERVAL '5 minutes')
LEFT JOIN historical_data.btc_price_history p_15m
    ON DATE(p_15m.timestamp)::text = t.date 
    AND p_15m.timestamp = (p_entry.timestamp + INTERVAL '15 minutes')
LEFT JOIN historical_data.btc_price_history p_30m
    ON DATE(p_30m.timestamp)::text = t.date 
    AND p_30m.timestamp = (p_entry.timestamp + INTERVAL '30 minutes')
LEFT JOIN historical_data.btc_price_history p_60m
    ON DATE(p_60m.timestamp)::text = t.date 
    AND p_60m.timestamp = (p_entry.timestamp + INTERVAL '60 minutes')
WHERE t.symbol = 'BTC'
    AND t.date >= '2026-01-01'
ORDER BY t.date DESC, t.time DESC;
```

### Method 4: Complete Trade Lifecycle Analysis

Analyze market conditions from 30 minutes before to 60 minutes after trade:

```sql
WITH trade_timestamps AS (
    SELECT 
        t.id as trade_id,
        t.date,
        t.time,
        t.buy_price,
        t.sell_price,
        t.pnl,
        t.momentum_percentile as trade_momentum_pct,
        t.volatility_percentile as trade_volatility_pct,
        -- Create timestamp from date and time
        (t.date || ' ' || t.time)::timestamp as trade_timestamp
    FROM users.trades_0001 t
    WHERE t.symbol = 'BTC'
        AND t.date >= '2026-01-01'
)
SELECT 
    tt.trade_id,
    tt.trade_timestamp,
    tt.buy_price,
    tt.pnl,
    -- Price history at various time points
    p.timestamp as price_timestamp,
    p.close as price,
    p.momentum_percentile,
    p.volatility_percentile,
    -- Calculate minutes relative to trade
    EXTRACT(EPOCH FROM (p.timestamp - tt.trade_timestamp)) / 60 as minutes_from_trade
FROM trade_timestamps tt
CROSS JOIN LATERAL (
    SELECT timestamp, close, momentum_percentile, volatility_percentile
    FROM historical_data.btc_price_history
    WHERE timestamp >= (tt.trade_timestamp - INTERVAL '30 minutes')
        AND timestamp <= (tt.trade_timestamp + INTERVAL '60 minutes')
    ORDER BY timestamp
) p
ORDER BY tt.trade_timestamp DESC, p.timestamp;
```

---

## Analysis Use Cases

### 1. Entry Signal Validation

Check if trades were entered at optimal momentum conditions:

```sql
SELECT 
    t.id,
    t.date,
    t.time,
    t.buy_price,
    t.pnl,
    t.momentum_percentile as trade_momentum_pct,
    p.momentum_percentile as market_momentum_pct,
    p.volatility_percentile as market_volatility_pct,
    CASE 
        WHEN p.momentum_percentile > 80 THEN 'Strong Bullish Entry'
        WHEN p.momentum_percentile > 50 THEN 'Moderate Bullish Entry'
        WHEN p.momentum_percentile > -50 THEN 'Neutral Entry'
        WHEN p.momentum_percentile > -80 THEN 'Moderate Bearish Entry'
        ELSE 'Strong Bearish Entry'
    END as entry_condition
FROM users.trades_0001 t
LEFT JOIN historical_data.btc_price_history p
    ON DATE(p.timestamp)::text = t.date 
    AND p.timestamp::time = t.time::time
WHERE t.symbol = 'BTC'
    AND t.status = 'closed'
ORDER BY t.date DESC, t.time DESC;
```

### 2. Momentum Trend Analysis

Check if momentum was increasing or decreasing before trade entry:

```sql
SELECT 
    t.id,
    t.date,
    t.time,
    t.buy_price,
    t.pnl,
    -- Momentum trend (30m -> 15m -> 5m -> entry)
    p_30m.momentum_percentile as momentum_30m_before,
    p_15m.momentum_percentile as momentum_15m_before,
    p_5m.momentum_percentile as momentum_5m_before,
    p_entry.momentum_percentile as momentum_at_entry,
    -- Calculate momentum trend
    CASE 
        WHEN p_entry.momentum_percentile > p_5m.momentum_percentile 
            AND p_5m.momentum_percentile > p_15m.momentum_percentile 
            AND p_15m.momentum_percentile > p_30m.momentum_percentile 
        THEN 'Increasing Momentum'
        WHEN p_entry.momentum_percentile < p_5m.momentum_percentile 
            AND p_5m.momentum_percentile < p_15m.momentum_percentile 
            AND p_15m.momentum_percentile < p_30m.momentum_percentile 
        THEN 'Decreasing Momentum'
        ELSE 'Mixed/Unclear'
    END as momentum_trend
FROM users.trades_0001 t
LEFT JOIN historical_data.btc_price_history p_entry
    ON DATE(p_entry.timestamp)::text = t.date 
    AND p_entry.timestamp::time = t.time::time
LEFT JOIN historical_data.btc_price_history p_5m
    ON DATE(p_5m.timestamp)::text = t.date 
    AND p_5m.timestamp = (p_entry.timestamp - INTERVAL '5 minutes')
LEFT JOIN historical_data.btc_price_history p_15m
    ON DATE(p_15m.timestamp)::text = t.date 
    AND p_15m.timestamp = (p_entry.timestamp - INTERVAL '15 minutes')
LEFT JOIN historical_data.btc_price_history p_30m
    ON DATE(p_30m.timestamp)::text = t.date 
    AND p_30m.timestamp = (p_entry.timestamp - INTERVAL '30 minutes')
WHERE t.symbol = 'BTC'
    AND t.status = 'closed'
ORDER BY t.date DESC, t.time DESC;
```

### 3. Volatility Impact on Trade Performance

Analyze how volatility at entry affects trade outcomes:

```sql
SELECT 
    t.id,
    t.date,
    t.time,
    t.buy_price,
    t.pnl,
    p.volatility_percentile as volatility_at_entry,
    CASE 
        WHEN p.volatility_percentile > 75 THEN 'High Volatility'
        WHEN p.volatility_percentile > 50 THEN 'Above Average Volatility'
        WHEN p.volatility_percentile > 25 THEN 'Below Average Volatility'
        ELSE 'Low Volatility'
    END as volatility_category,
    AVG(t.pnl) OVER (PARTITION BY 
        CASE 
            WHEN p.volatility_percentile > 75 THEN 'High'
            WHEN p.volatility_percentile > 50 THEN 'Above Avg'
            WHEN p.volatility_percentile > 25 THEN 'Below Avg'
            ELSE 'Low'
        END
    ) as avg_pnl_by_volatility
FROM users.trades_0001 t
LEFT JOIN historical_data.btc_price_history p
    ON DATE(p.timestamp)::text = t.date 
    AND p.timestamp::time = t.time::time
WHERE t.symbol = 'BTC'
    AND t.status = 'closed'
    AND t.pnl IS NOT NULL
ORDER BY t.date DESC, t.time DESC;
```

### 4. Post-Trade Performance Analysis

Check if market conditions continued favorably after trade entry:

```sql
SELECT 
    t.id,
    t.date,
    t.time,
    t.buy_price,
    t.sell_price,
    t.pnl,
    p_entry.momentum_percentile as momentum_at_entry,
    p_60m.momentum_percentile as momentum_60m_after,
    p_60m.close as price_60m_after,
    (p_60m.close - p_entry.close) / p_entry.close * 100 as price_change_pct_1h,
    CASE 
        WHEN t.pnl > 0 AND p_60m.momentum_percentile > p_entry.momentum_percentile 
        THEN 'Win + Momentum Continued'
        WHEN t.pnl > 0 AND p_60m.momentum_percentile <= p_entry.momentum_percentile 
        THEN 'Win + Momentum Reversed'
        WHEN t.pnl <= 0 AND p_60m.momentum_percentile > p_entry.momentum_percentile 
        THEN 'Loss + Momentum Improved'
        ELSE 'Loss + Momentum Worsened'
    END as performance_category
FROM users.trades_0001 t
LEFT JOIN historical_data.btc_price_history p_entry
    ON DATE(p_entry.timestamp)::text = t.date 
    AND p_entry.timestamp::time = t.time::time
LEFT JOIN historical_data.btc_price_history p_60m
    ON DATE(p_60m.timestamp)::text = t.date 
    AND p_60m.timestamp = (p_entry.timestamp + INTERVAL '60 minutes')
WHERE t.symbol = 'BTC'
    AND t.status = 'closed'
    AND t.pnl IS NOT NULL
ORDER BY t.date DESC, t.time DESC;
```

---

## Key Considerations

### 1. Timezone Alignment

✅ **Both systems use EST/EDT:**
- Trade logs: `date` and `time` fields in EST
- Price history: `timestamp` field in EST (stored as timezone-naive)
- **No timezone conversion needed** for joins

### 2. Time Precision

- **Trades:** Stored with second precision (`'14:45:13'`)
- **Price History:** Stored with minute precision (`'14:45:00'`)
- **Solution:** Round trade time to nearest minute for exact matches, or use time ranges

### 3. Missing Data Handling

- Some trades may not have exact minute matches in price history
- Use `LEFT JOIN` to preserve all trades
- Consider time range joins (e.g., ±1 minute) for better matching

### 4. Performance Optimization

For large datasets, consider:
- Creating indexes on `(date, time)` in trades table
- Creating indexes on `(timestamp)` in price history table
- Using materialized views for common analysis queries

---

## Example: Complete Trade Analysis Query

```sql
-- Complete analysis of a single trade with market conditions
WITH trade_data AS (
    SELECT 
        t.id,
        t.date,
        t.time,
        (t.date || ' ' || t.time)::timestamp as trade_timestamp,
        t.buy_price,
        t.sell_price,
        t.pnl,
        t.momentum_percentile as trade_momentum_pct,
        t.volatility_percentile as trade_volatility_pct
    FROM users.trades_0001 t
    WHERE t.id = 12345  -- Replace with actual trade ID
)
SELECT 
    td.*,
    -- Market conditions 30 minutes before
    p_30m.close as price_30m_before,
    p_30m.momentum_percentile as momentum_30m_before,
    p_30m.volatility_percentile as volatility_30m_before,
    -- Market conditions at entry
    p_entry.close as market_price_at_entry,
    p_entry.momentum_percentile as momentum_at_entry,
    p_entry.volatility_percentile as volatility_at_entry,
    -- Market conditions 60 minutes after
    p_60m.close as price_60m_after,
    p_60m.momentum_percentile as momentum_60m_after,
    -- Calculations
    (p_entry.close - p_30m.close) / p_30m.close * 100 as price_change_30m_before,
    (p_60m.close - p_entry.close) / p_entry.close * 100 as price_change_60m_after
FROM trade_data td
LEFT JOIN historical_data.btc_price_history p_entry
    ON DATE(p_entry.timestamp)::text = td.date 
    AND p_entry.timestamp::time = td.time::time
LEFT JOIN historical_data.btc_price_history p_30m
    ON p_30m.timestamp = (p_entry.timestamp - INTERVAL '30 minutes')
LEFT JOIN historical_data.btc_price_history p_60m
    ON p_60m.timestamp = (p_entry.timestamp + INTERVAL '60 minutes');
```

---

## Summary

✅ **Yes, you can cross-reference trade logs with price history!**

**Key Points:**
1. Both systems use EST/EDT timestamps
2. Trades stored as `date` + `time` (TEXT fields)
3. Price history stored as `timestamp` (TIMESTAMP field)
4. Join on: `DATE(timestamp)::text = date AND timestamp::time = time::time`
5. Can analyze market conditions before, during, and after trades
6. Enables comprehensive trade performance analysis

This cross-reference capability allows you to:
- Validate entry signals
- Analyze momentum trends
- Assess volatility impact
- Evaluate post-trade performance
- Identify optimal market conditions for trading
