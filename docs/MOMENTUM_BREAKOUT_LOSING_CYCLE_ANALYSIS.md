# Momentum Breakout Strategy - Losing Cycle Prediction Analysis

## Objective

Find signals (from trade history and BTC price logs) that can predict when LOSING cycles will occur, enabling automatic ENABLE/DISABLE of the strategy to maximize PnL.

## Strategy Context

- **Strategy**: Momentum Breakout (Monitor 10020)
- **Entry**: Two trades simultaneously (YES above price, NO below price) when momentum spike detected
- **Hold**: Until expiration
- **Profitability Threshold**: ~70% win rate needed
- **Performance Pattern**: Poor early (Dec 19 - Jan 20), improved recently (Late Jan - Feb 4)

## Analysis Dimensions

### 1. Time-Based Patterns
- Hour of day (when cycles are entered)
- Day of week patterns
- Time windows (24h, 48h, 7-day rolling)
- Intraday patterns (morning vs afternoon)
- Time since last cycle

### 2. Market Condition Analysis
- Momentum patterns at entry
- Volatility regimes (high/low volatility periods)
- Price movement characteristics (trending vs ranging)
- Momentum spike strength and persistence
- Price position relative to recent range

### 3. Entry Condition Analysis
- Market state at exact entry moment
- Momentum percentile at entry
- Volatility percentile at entry
- Price movement leading up to entry
- Strike selection (distance from current price)

### 4. Prior Performance Patterns
- Recent win rate (last N cycles)
- Win/loss streaks
- Cumulative PnL trends
- Performance over time windows (24h, 48h, week)

### 5. Market Regime Detection
- Trending vs ranging markets
- High vs low volatility periods
- Momentum regime (sustained vs transient)
- Price range characteristics

### 6. Multi-Factor Correlations
- Combinations of time + market conditions
- Momentum + volatility interactions
- Prior performance + current market state
- Entry conditions + recent history

## Data Sources

1. **Trade History** (`users.trades_0001`)
   - Cycle-level: `cycle_win_loss`, `cycle_pnl`, `cycle_ret_pct`
   - Entry conditions: `momentum_percentile`, `volatility_percentile`, `date`, `time`
   - Strike information: `strike`, `side`, `buy_price`

2. **Historical Price Logs** (`historical_data.btc_price_history`)
   - Minute-by-minute: price, momentum, volatility, percentiles
   - Can analyze: pre-entry conditions, during-trade movement, post-entry patterns

## Analysis Approach

### Phase 1: Exploratory Data Analysis
- Comprehensive data profiling
- Identify all available features
- Basic statistical summaries

### Phase 2: Univariate Analysis
- Test each dimension independently
- Identify strongest individual predictors
- Statistical significance testing

### Phase 3: Multivariate Analysis
- Combine multiple signals
- Interaction effects
- Feature importance ranking

### Phase 4: Pattern Recognition
- Identify distinct losing cycle patterns
- Regime classification
- Temporal patterns

### Phase 5: Signal Generation
- Create predictive rules
- Validation framework
- Performance metrics

## Success Criteria

Find signals that:
1. **Predict losing cycles** with high accuracy
2. **Enable/disable strategy** at optimal times
3. **Improve overall PnL** vs always-on strategy
4. **Are actionable** (can be implemented in real-time)

## Notes

- User's hypothesis: Regime may be confined to single trading day or week
- Prior analysis: Cycle win/loss rates over time windows showed limited value
- Focus: Predict LOSING cycles specifically (not just win rate)
