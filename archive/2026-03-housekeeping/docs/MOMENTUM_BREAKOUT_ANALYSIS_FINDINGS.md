# Momentum Breakout Strategy - Losing Cycle Analysis Findings

## Executive Summary

Comprehensive analysis of 497 cycles (312 wins, 185 losses) from Monitor 10020 to identify signals that predict losing cycles.

**Overall Performance:**
- Win Rate: 62.78% (below 70% profitability threshold)
- Total Cycles: 497
- Date Range: Dec 19, 2025 - Feb 4, 2026 (44 trading days)

---

## Key Findings

### 1. **MOMENTUM PERSISTENCE IS CRITICAL** ⭐⭐⭐

**Winning Cycles:**
- Momentum was **already negative** 30 minutes before entry (-6.14%)
- Momentum **continued/accelerated** negative at entry (-19.16%)
- Momentum **improved** after entry (+6.61% change in 15 minutes)

**Losing Cycles:**
- Momentum was **positive** 30 minutes before entry (+15.86%)
- Momentum **reversed** from positive to negative at entry (-4.81%)
- Momentum **worsened** after entry (-0.53% change in 15 minutes)

**Signal:** Strategy works when momentum is ALREADY negative and CONTINUES, but fails when momentum REVERSES from positive to negative.

### 2. **PRICE MOVEMENT BEFORE ENTRY** ⭐⭐⭐

**Winning Cycles:**
- Price was **FALLING** in 30 minutes before entry (-0.15%)
- Price was **FALLING** in 15 minutes before entry (-0.08%)
- Price was **FALLING** in 5 minutes before entry (-0.03%)

**Losing Cycles:**
- Price was **RISING** in 30 minutes before entry (+0.03%)
- Price was **FALLING** in 15 minutes before entry (-0.04%)
- Price was **FALLING** in 5 minutes before entry (-0.01%)

**Signal:** Strategy works better when price is consistently FALLING before entry, not rising.

### 3. **TIME-BASED PATTERNS** ⭐⭐

**Hour of Day (Strong Patterns):**
- **Hour 0 (Midnight)**: 0% win rate (2 cycles) - AVOID
- **Hour 3 (3 AM)**: 0% win rate (2 cycles) - AVOID
- **Hour 8 (8 AM)**: 83.33% win rate (12 cycles) - STRONG
- **Hour 14 (2 PM)**: 41.18% win rate (34 cycles) - WEAK
- **Hour 18 (6 PM)**: 46.15% win rate (26 cycles) - WEAK
- **Hour 21 (9 PM)**: 46.67% win rate (30 cycles) - WEAK
- **Hours 13, 15, 19, 20**: 70-75% win rate - GOOD

**Day of Week:**
- **Sunday**: 75.95% win rate (79 cycles) - BEST DAY
- **Monday**: 54.29% win rate (70 cycles) - WORST DAY
- **Wednesday**: 57.50% win rate (80 cycles) - WEAK
- **Thursday**: 67.65% win rate (68 cycles) - GOOD

### 4. **VOLATILITY REGIMES** ⭐

**Distribution:**
- Most cycles occur in **High Volatility** (>= 75th percentile)
- Losing cycles: 52.43% in high volatility
- Winning cycles: 67.86% in high volatility
- **Low Volatility** (< 25th percentile): Very few cycles but better win rate (74.99 avg PnL for wins)

**Signal:** Strategy operates primarily in high volatility, but low volatility periods may be safer.

### 5. **MARKET CONDITIONS AT ENTRY** ⭐

**Winning Cycles:**
- Entry Momentum: -7.92% (more negative)
- Market Momentum: -19.16% (stronger bearish)
- Volatility: 77.72% (higher)

**Losing Cycles:**
- Entry Momentum: -2.57% (less negative)
- Market Momentum: -4.81% (weaker bearish)
- Volatility: 71.68% (slightly lower)

**Signal:** Strategy works better with STRONGER negative momentum and HIGHER volatility at entry.

### 6. **MULTI-FACTOR COMBINATIONS** ⭐⭐

**Worst Combinations (0% win rate):**
- Hour 15 Wednesday + Bearish momentum (< -50): 0% (4 cycles)
- Hour 10 Wednesday + Bullish momentum (50-80): 0% (4 cycles)
- Hour 12 Monday + Bearish momentum (< -50): 0% (4 cycles)
- Hour 17 Tuesday + Bearish momentum (< -50): 0% (3 cycles)
- Hour 14 Friday + Mild Bearish (-50 to 0): 0% (3 cycles)
- Hour 11 Tuesday + Mild Bearish (-50 to 0): 0% (3 cycles)

**Best Combinations:**
- Hour 8 (any day): 83.33% win rate
- Sunday (any hour): 75.95% win rate
- Hours 13, 15, 19, 20: Generally 70-75% win rate

---

## Predictive Signals for LOSING Cycles

### High Confidence Signals (Avoid Trading):

1. **Momentum Reversal Pattern:**
   - Momentum was positive 30 minutes before entry
   - Momentum reverses to negative at entry
   - **Action:** DISABLE strategy

2. **Price Rising Before Entry:**
   - Price rising in 30 minutes before entry
   - **Action:** DISABLE strategy

3. **Time-Based Avoidance:**
   - Hours 0, 3 (midnight/early morning)
   - Hour 14 (2 PM)
   - Hour 18 (6 PM)
   - Hour 21 (9 PM)
   - **Action:** DISABLE during these hours

4. **Day-Based Avoidance:**
   - Monday (worst day: 54.29% win rate)
   - Wednesday (weak: 57.50% win rate)
   - **Action:** Consider disabling on Mondays

5. **Combination Avoidance:**
   - Specific hour + day + momentum combinations with 0% win rate
   - **Action:** DISABLE for these combinations

### High Confidence Signals (Enable Trading):

1. **Momentum Continuation Pattern:**
   - Momentum already negative 30 minutes before
   - Momentum continues/accelerates negative at entry
   - **Action:** ENABLE strategy

2. **Price Falling Before Entry:**
   - Price consistently falling in 30 minutes before entry
   - **Action:** ENABLE strategy

3. **Time-Based Enablement:**
   - Hour 8 (8 AM): 83.33% win rate
   - Hours 13, 15, 19, 20: 70-75% win rate
   - **Action:** ENABLE during these hours

4. **Day-Based Enablement:**
   - Sunday: 75.95% win rate
   - Thursday: 67.65% win rate
   - **Action:** ENABLE on these days

---

## CRITICAL FINDING: Daily Regime Pattern ⭐⭐⭐

**After a day with < 50% win rate:**
- Next day win rate: **36.63%** (VERY BAD)
- Average cycle PnL: -$25.60

**After a day with >= 70% win rate:**
- Next day win rate: **78.38%** (VERY GOOD)
- Average cycle PnL: +$11.89

**Signal:** The regime appears to be **day-based**. If yesterday was a bad day, today is likely bad. If yesterday was good, today is likely good.

---

## Recommended Enable/Disable Rules

### Rule Set 1: Daily Regime (Highest Priority) ⭐⭐⭐

**DISABLE if:**
- Previous trading day had < 50% win rate
- Previous trading day had < 60% win rate (optional, more conservative)

**ENABLE if:**
- Previous trading day had >= 70% win rate
- Previous trading day had >= 60% win rate (optional, less conservative)

**Rationale:** Daily regime pattern is strongest predictor - accounts for significant portion of losing cycles.

### Rule Set 2: Momentum-Based (High Priority) ⭐⭐⭐

**DISABLE if:**
- Momentum was positive 30 minutes before entry AND momentum is negative at entry (reversal pattern)
- **This pattern accounts for 49.73% of all losing cycles!**
- Price is rising in 30 minutes before entry

**ENABLE if:**
- Momentum was negative 30 minutes before entry AND momentum continues negative/accelerates at entry
- Price is falling in 30 minutes before entry

### Rule Set 3: Time-Based

**DISABLE during:**
- Hours 0, 3 (midnight/early morning) - 0% win rate
- Hour 14 (2 PM) - 41.18% win rate (20 losing cycles = 10.81% of all losses)
- Hour 18 (6 PM) - 46.15% win rate
- Hour 21 (9 PM) - 46.67% win rate
- Mondays - 54.29% win rate (32 losing cycles = 17.30% of all losses)

**ENABLE during:**
- Hour 8 (8 AM) - 83.33% win rate (high priority)
- Hours 13, 15, 19, 20 - 70-75% win rate
- Sundays - 75.95% win rate (best day)
- Thursdays - 67.65% win rate (good day)

### Rule Set 4: Combination Rules

**DISABLE for:**
- Hour 15 Wednesday + Bearish momentum
- Hour 10 Wednesday + Bullish momentum
- Hour 12 Monday + Bearish momentum
- Hour 17 Tuesday + Bearish momentum
- Hour 14 Friday + Mild Bearish momentum
- Hour 11 Tuesday + Mild Bearish momentum

---

## Next Steps

1. **Validate Rules:** Test these rules against historical data to see improvement in win rate
2. **Refine Thresholds:** Fine-tune momentum/price change thresholds
3. **Combine Signals:** Create multi-factor scoring system
4. **Real-time Implementation:** Build monitoring system to apply these rules

---

## Data Quality Notes

- All analysis based on 497 cycles with complete data
- Price history cross-reference: 185 losing cycles, 308 winning cycles matched
- Momentum data available for most cycles
- Volatility data available for most cycles
