# BTC Price History Table - Comprehensive Analysis

## Table Overview

**Table Name:** `historical_data.btc_price_history`  
**Schema:** `historical_data`  
**Primary Key:** `timestamp` (unique, indexed)  
**Data Range:** August 25, 2020 to present (currently ~2.86 million rows)  
**Timeframe:** 1-minute candlestick data  
**Timezone:** East Coast (America/New_York) - stored as timezone-naive timestamps

---

## Table Structure

### Columns

| Column | Type | Description | Example Value |
|--------|------|-------------|---------------|
| `timestamp` | `timestamp without time zone` | 1-minute candlestick timestamp (East Coast time) | `2026-02-04 12:48:00` |
| `open` | `numeric(20,8)` | Opening price for the 1-minute period | `72427.93000000` |
| `high` | `numeric(20,8)` | Highest price during the 1-minute period | `72539.32000000` |
| `low` | `numeric(20,8)` | Lowest price during the 1-minute period | `72362.54000000` |
| `close` | `numeric(20,8)` | Closing price for the 1-minute period | `72366.80000000` |
| `volume` | `numeric(20,8)` | Trading volume during the 1-minute period | `36.95252553` |
| `momentum` | `numeric(10,4)` | Calculated momentum score (see calculation below) | `-0.1990` |
| `momentum_percentile` | `numeric(5,1)` | Momentum percentile (-99.5 to +99.5) | `-95.0` |
| `volatility` | `numeric(15,6)` | Calculated volatility score (see calculation below) | `0.001514` |
| `volatility_percentile` | `numeric(5,1)` | Volatility percentile (0.5 to 99.5) | `96.2` |

### Current Data Status
- **Total Rows:** 2,859,784
- **Earliest Timestamp:** 2020-08-25 22:57:00
- **Latest Timestamp:** 2026-02-04 12:48:00
- **Momentum Coverage:** 2,859,754 rows (99.99%)
- **Momentum Percentile Coverage:** 2,859,754 rows (99.99%)
- **Volatility Coverage:** 2,859,724 rows (99.98%)
- **Volatility Percentile Coverage:** 2,859,724 rows (99.98%)

---

## What This Table IS

### 1. **Master Historical Price Database**
This is the **single source of truth** for BTC price history in your system. It contains:
- **5+ years** of 1-minute OHLCV (Open, High, Low, Close, Volume) data
- **Continuous coverage** with minimal gaps
- **East Coast timezone** for consistent trading hours alignment

### 2. **Enriched Analytics Dataset**
Beyond raw price data, each row includes:
- **Momentum scores** - Calculated price movement indicators
- **Momentum percentiles** - Normalized momentum values for comparison
- **Volatility scores** - Multi-timeframe volatility measurements
- **Volatility percentiles** - Normalized volatility values

### 3. **Foundation for Trading Algorithms**
This table feeds:
- **Fingerprint tables** (199 tables per symbol)
- **Probability lookup tables**
- **Momentum profiles** (`analytics.btc_momentum_profile`)
- **Price profiles** (`analytics.btc_price_profile`)
- **Volatility profiles** (`analytics.btc_volatility_profile`)

---

## How Values Are Calculated

### Momentum Calculation

**Formula:** Weighted average of percentage price changes across multiple timeframes

```python
momentum = (
    ((P_now - P_1m)  / P_1m)  * 0.30 +  # 1 minute ago (30% weight)
    ((P_now - P_2m)  / P_2m)  * 0.25 +  # 2 minutes ago (25% weight)
    ((P_now - P_3m)  / P_3m)  * 0.20 +  # 3 minutes ago (20% weight)
    ((P_now - P_4m)  / P_4m)  * 0.15 +  # 4 minutes ago (15% weight)
    ((P_now - P_15m) / P_15m) * 0.05 +  # 15 minutes ago (5% weight)
    ((P_now - P_30m) / P_30m) * 0.05    # 30 minutes ago (5% weight)
) * 100
```

**Interpretation:**
- **Positive values:** Price is rising (bullish momentum)
- **Negative values:** Price is falling (bearish momentum)
- **Magnitude:** Strength of the momentum
- **Range:** Typically -10 to +10, but can exceed during extreme volatility

**Example:**
- If momentum = `-0.1990`, BTC price has declined slightly over the past 30 minutes
- The negative value indicates downward pressure
- The magnitude (0.1990) indicates relatively mild downward momentum

### Momentum Percentile

**Calculation:** Interpolated from `analytics.btc_momentum_profile` table

**Process:**
1. Momentum profile contains 199 percentile points (-99.5 to +99.5 in 0.5 increments)
2. Each percentile maps to a momentum value based on historical distribution
3. Current momentum value is matched to nearest percentile in profile
4. Linear interpolation used for precise mapping

**Interpretation:**
- **-99.5 to -50:** Strongly bearish (bottom 50% of historical momentum)
- **-50 to 0:** Mildly bearish
- **0 to +50:** Mildly bullish
- **+50 to +99.5:** Strongly bullish (top 50% of historical momentum)

**Example:**
- Momentum = `-0.1990` → Momentum Percentile = `-95.0`
- This means the current momentum is in the **bottom 5%** of all historical momentum values
- Extremely bearish signal

### Volatility Calculation

**Formula:** Weighted multi-timeframe True Range (ATR-based) volatility

**True Range Formula:**
```
TR = max(
    high - low,                    # Current period range
    abs(high - prev_close),        # Gap up scenario
    abs(low - prev_close)          # Gap down scenario
)
```

**Volatility Calculation:**
```python
volatility = (
    TR_1m  * 0.40 +  # 1-minute True Range (40% weight)
    std(TR_5m)  * 0.30 +  # Standard deviation of 5-minute TR (30% weight)
    std(TR_15m) * 0.15 +  # Standard deviation of 15-minute TR (15% weight)
    std(TR_30m) * 0.10 +  # Standard deviation of 30-minute TR (10% weight)
    std(TR_60m) * 0.05    # Standard deviation of 60-minute TR (5% weight)
)
```

**Interpretation:**
- **Higher values:** More volatile (larger price swings)
- **Lower values:** Less volatile (calmer price action)
- **Range:** Typically 0.0001 to 0.01 for BTC
- **Percentage-based:** Represents percentage price movement

**Example:**
- Volatility = `0.001514` = 0.1514% expected price movement
- This is relatively low volatility (calm market conditions)

### Volatility Percentile

**Calculation:** Interpolated from `analytics.btc_volatility_profile` table

**Process:**
1. Volatility profile contains 199 percentile points (0.5 to 99.5)
2. Each percentile maps to a volatility value based on historical distribution
3. Current volatility value is matched to nearest percentile
4. Linear interpolation used for precise mapping

**Interpretation:**
- **0.5 to 25:** Very low volatility (calm market)
- **25 to 50:** Below-average volatility
- **50 to 75:** Above-average volatility
- **75 to 99.5:** Very high volatility (volatile market)

**Example:**
- Volatility = `0.001514` → Volatility Percentile = `96.2`
- This means current volatility is in the **top 4%** of all historical volatility values
- Despite the low absolute value, this is high relative to historical norms

---

## Analytics Pipeline Flow

### Step 1: Data Fetching (`symbol_data_fetch_pg.py`)
- **Source:** Coinbase API (CCXT library)
- **Process:** Fetches 1-minute OHLCV data
- **Updates:** Incremental updates from last timestamp to current time
- **Timezone:** Converts UTC to East Coast time
- **Initial Load:** Full 5-year download on first run

### Step 2: Momentum Generation (`momentum_generator_pg.py`)
- **Process:** Calculates momentum for all rows with sufficient history (needs 30 minutes)
- **Method:** Weighted average of price changes (see formula above)
- **Updates:** Fills missing momentum values, can recalculate all if needed
- **Output:** Updates `momentum` column in table

### Step 3: Volatility Generation (`volatility_generator_pg.py`)
- **Process:** Calculates volatility for all rows with sufficient history (needs 60 minutes)
- **Method:** Weighted multi-timeframe True Range (see formula above)
- **Updates:** Fills missing volatility values
- **Output:** Updates `volatility` column in table

### Step 4: Profile Generation (`symbol_profiler.py`)
- **Momentum Profile:** Creates `analytics.btc_momentum_profile`
  - 199 percentile points (-99.5 to +99.5)
  - Time-weighted (recent data more important)
  - Used for percentile assignment
- **Volatility Profile:** Creates `analytics.btc_volatility_profile`
  - 199 percentile points (0.5 to 99.5)
  - Time-weighted distribution
  - Used for percentile assignment
- **Price Profile:** Creates `analytics.btc_price_profile`
  - Price movement characteristics
  - Used for lookup table design

### Step 5: Percentile Assignment (`symbol_profiler.py`)
- **Process:** Assigns percentiles to all rows based on profiles
- **Method:** Linear interpolation from profile tables
- **Updates:** `momentum_percentile` and `volatility_percentile` columns
- **Frequency:** Recalculated when profiles are regenerated

### Step 6: Fingerprint Generation (`fingerprint_generator_postgresql.py`)
- **Process:** Creates 199 fingerprint tables per symbol
- **Purpose:** Pattern recognition for trading signals
- **Input:** Uses momentum percentiles from this table

### Step 7: Probability Lookup Generation (`probability_lookup_generator.py`)
- **Process:** Creates probability lookup tables
- **Purpose:** Predict future price movements based on current conditions
- **Input:** Uses momentum and volatility data from this table

---

## How to Use This Table

### 1. **Historical Price Analysis**

```sql
-- Get price data for a specific date range
SELECT timestamp, open, high, low, close, volume
FROM historical_data.btc_price_history
WHERE timestamp >= '2025-01-01' AND timestamp < '2025-02-01'
ORDER BY timestamp;
```

### 2. **Momentum Analysis**

```sql
-- Find periods with extreme momentum
SELECT timestamp, close, momentum, momentum_percentile
FROM historical_data.btc_price_history
WHERE momentum_percentile < -90 OR momentum_percentile > 90
ORDER BY timestamp DESC
LIMIT 100;
```

### 3. **Volatility Analysis**

```sql
-- Find high volatility periods
SELECT timestamp, close, volatility, volatility_percentile
FROM historical_data.btc_price_history
WHERE volatility_percentile > 95
ORDER BY timestamp DESC
LIMIT 100;
```

### 4. **Correlation Analysis**

```sql
-- Analyze momentum vs price movement
SELECT 
    momentum_percentile,
    AVG(close) as avg_price,
    COUNT(*) as occurrences
FROM historical_data.btc_price_history
WHERE momentum_percentile IS NOT NULL
GROUP BY momentum_percentile
ORDER BY momentum_percentile;
```

### 5. **Pattern Recognition**

```sql
-- Find similar historical patterns
SELECT timestamp, close, momentum, momentum_percentile, volatility_percentile
FROM historical_data.btc_price_history
WHERE momentum_percentile BETWEEN -5 AND 5
  AND volatility_percentile BETWEEN 45 AND 55
ORDER BY timestamp DESC
LIMIT 100;
```

### 6. **Backtesting Trading Strategies**

```sql
-- Analyze entry conditions
SELECT 
    timestamp,
    close as entry_price,
    momentum_percentile,
    volatility_percentile,
    -- Calculate 1-hour forward return
    (LEAD(close, 60) OVER (ORDER BY timestamp) - close) / close * 100 as return_1h
FROM historical_data.btc_price_history
WHERE momentum_percentile IS NOT NULL
ORDER BY timestamp;
```

### 7. **Data Quality Checks**

```sql
-- Check for missing data
SELECT 
    DATE(timestamp) as date,
    COUNT(*) as rows,
    COUNT(momentum) as momentum_count,
    COUNT(momentum_percentile) as momentum_percentile_count,
    COUNT(volatility) as volatility_count,
    COUNT(volatility_percentile) as volatility_percentile_count
FROM historical_data.btc_price_history
GROUP BY DATE(timestamp)
ORDER BY date DESC
LIMIT 30;
```

### 8. **Statistical Analysis**

```sql
-- Calculate momentum distribution
SELECT 
    CASE 
        WHEN momentum_percentile < -50 THEN 'Strongly Bearish'
        WHEN momentum_percentile < 0 THEN 'Mildly Bearish'
        WHEN momentum_percentile < 50 THEN 'Mildly Bullish'
        ELSE 'Strongly Bullish'
    END as momentum_category,
    COUNT(*) as count,
    AVG(close) as avg_price,
    STDDEV(close) as price_stddev
FROM historical_data.btc_price_history
WHERE momentum_percentile IS NOT NULL
GROUP BY momentum_category;
```

---

## Key Insights

### 1. **Data Completeness**
- **99.99% coverage** for momentum and momentum_percentile
- **99.98% coverage** for volatility and volatility_percentile
- Missing values typically occur at the beginning of the dataset (first 30-60 minutes)

### 2. **Time Coverage**
- **5+ years** of continuous 1-minute data
- **~2.86 million rows** = ~5.4 years of data (assuming 24/7 coverage)
- Updates incrementally from last timestamp

### 3. **Calculated Fields**
- **Momentum:** Real-time calculated, requires 30 minutes of history
- **Volatility:** Real-time calculated, requires 60 minutes of history
- **Percentiles:** Derived from profiles, updated when profiles regenerate

### 4. **Trading Applications**
- **Entry Signals:** Use momentum_percentile to identify entry points
- **Risk Management:** Use volatility_percentile to adjust position sizing
- **Pattern Matching:** Use combinations of percentiles to find similar historical patterns
- **Backtesting:** Use historical data to test trading strategies

### 5. **Performance Considerations**
- **Indexed on timestamp:** Fast time-range queries
- **Primary key on timestamp:** Prevents duplicates
- **Large dataset:** ~2.86M rows requires efficient querying
- **Batch processing:** Analytics pipeline processes in batches

---

## Maintenance

### Regular Updates
- **Data Fetching:** Daily incremental updates via `symbol_data_fetch_pg.py`
- **Momentum Calculation:** Runs after data updates via `momentum_generator_pg.py`
- **Volatility Calculation:** Runs after data updates via `volatility_generator_pg.py`
- **Profile Generation:** Weekly via `analytics_updater.py`
- **Percentile Assignment:** After profile generation

### Data Retention
- **5-year rolling window:** Oldest data may be removed to maintain 5-year window
- **Full history:** Currently maintains all data from August 2020

### Monitoring
- Check row counts: `SELECT COUNT(*) FROM historical_data.btc_price_history;`
- Check latest timestamp: `SELECT MAX(timestamp) FROM historical_data.btc_price_history;`
- Check data quality: Verify momentum/volatility coverage percentages

---

## Related Tables

- `analytics.btc_momentum_profile` - Momentum distribution profile
- `analytics.btc_volatility_profile` - Volatility distribution profile
- `analytics.btc_price_profile` - Price movement profile
- `analytics.btc_fingerprint_XX` - 199 fingerprint tables (XX = 00-99)
- `analytics.probability_lookup_btc` - Probability lookup tables

---

## Summary

The `historical_data.btc_price_history` table is the **foundation** of your trading analytics system. It provides:

1. **Complete historical price data** (5+ years, 1-minute resolution)
2. **Enriched analytics** (momentum, volatility, percentiles)
3. **Normalized values** (percentiles for easy comparison)
4. **Trading signals** (momentum/volatility percentiles for decision-making)
5. **Backtesting data** (historical patterns for strategy validation)

This table enables sophisticated trading algorithms by providing both raw price data and calculated indicators that can be used for pattern recognition, probability estimation, and trading signal generation.
