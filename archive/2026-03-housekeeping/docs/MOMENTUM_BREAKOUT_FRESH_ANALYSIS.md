# Momentum Breakout Strategy - Fresh Multi-Dimensional Analysis

## Data Overview

- **Total Cycles:** 497 (312 wins, 185 losses)
- **Overall Win Rate:** 62.78%
- **Total PnL (from individual trades):** -$278.08
- **Date Range:** Dec 19, 2025 - Feb 4, 2026 (44 trading days)
- **Target Win Rate:** 70%+ for profitability

**Note:** PnL calculated from individual trades: `(sell_price - buy_price) * position` for each trade, then summed. The `cycle_pnl` column in the table does not match the sum of individual trade PnLs.

---

## 1. TIME-BASED PATTERNS

### Hour of Day Analysis

**Best Performing Hours:**
- **Hour 8 (8 AM):** 83.33% win rate (10 wins, 2 losses) - +$141.16 total PnL
- **Hour 13 (1 PM):** 75.00% win rate (36 wins, 12 losses) - +$552.84 total PnL
- **Hour 15 (3 PM):** 75.00% win rate (24 wins, 8 losses) - +$452.66 total PnL
- **Hour 19 (7 PM):** 70.59% win rate (12 wins, 5 losses) - +$426.15 total PnL
- **Hour 20 (8 PM):** 72.73% win rate (16 wins, 6 losses) - +$286.26 total PnL

**Worst Performing Hours:**
- **Hour 0 (Midnight):** 0.00% win rate (0 wins, 2 losses) - -$177.76 total PnL
- **Hour 3 (3 AM):** 0.00% win rate (0 wins, 2 losses) - -$19.36 total PnL
- **Hour 14 (2 PM):** 41.18% win rate (14 wins, 20 losses) - -$701.32 total PnL ⚠️
- **Hour 21 (9 PM):** 46.67% win rate (14 wins, 16 losses) - -$481.40 total PnL
- **Hour 18 (6 PM):** 46.15% win rate (12 wins, 14 losses) - -$294.06 total PnL
- **Hour 10 (10 AM):** 60.61% win rate (40 wins, 26 losses) - -$695.12 total PnL ⚠️

### Day of Week Analysis

**Best Performing Days:**
- **Sunday:** 75.95% win rate (60 wins, 19 losses) - +$917.55 total PnL ⭐
- **Thursday:** 67.65% win rate (46 wins, 22 losses) - +$423.22 total PnL

**Worst Performing Days:**
- **Monday:** 54.29% win rate (38 wins, 32 losses) - -$612.66 total PnL ⚠️
- **Wednesday:** 57.50% win rate (46 wins, 34 losses) - -$833.26 total PnL ⚠️
- **Tuesday:** 59.26% win rate (64 wins, 44 losses) - -$269.66 total PnL

---

## 2. MARKET CONDITIONS AT ENTRY

### Price Movement Before Entry

**Winning Cycles:**
- 30 minutes before: **-0.1476%** (price falling)
- 15 minutes before: **-0.0787%** (price falling)
- 5 minutes before: **-0.0316%** (price falling)
- Average cycle PnL: **+$34.10**

**Losing Cycles:**
- 30 minutes before: **+0.0322%** (price rising)
- 15 minutes before: **-0.0410%** (price falling)
- 5 minutes before: **-0.0136%** (price falling)
- Average cycle PnL: **-$60.07**

**Key Finding:** Winning cycles show consistent price decline before entry. Losing cycles show price rising 30 minutes before entry.

### Momentum Patterns

**Winning Cycles:**
- Momentum at entry: **-19.16%** (strongly negative)
- Momentum 30m before: **-6.14%** (already negative)
- Momentum change: **-13.02%** (momentum continued/accelerated negative)
- Average cycle PnL: **+$34.10**

**Losing Cycles:**
- Momentum at entry: **-4.81%** (weakly negative)
- Momentum 30m before: **+15.86%** (was positive!)
- Momentum change: **-20.66%** (momentum reversed from positive to negative)
- Average cycle PnL: **-$60.07**

**Key Finding:** Losing cycles show momentum REVERSAL (positive → negative). Winning cycles show momentum CONTINUATION (negative → more negative).

---

## 3. DAILY PERFORMANCE PATTERNS

### Daily Win Rate Distribution

**Strong Days (70%+ win rate):**
- Dec 26: 100% (6 cycles) - +$150.88
- Dec 30: 80% (10 cycles) - +$175.48
- Jan 3: 100% (2 cycles) - +$67.80
- Jan 6: 71.43% (14 cycles) - +$47.46
- Jan 8: 83.33% (12 cycles) - +$201.15
- Jan 11: 75% (8 cycles) - +$39.10
- Jan 13: 71.43% (14 cycles) - +$7.54
- Jan 18: 100% (4 cycles) - +$82.08
- Jan 22: 80% (10 cycles) - +$91.02
- Jan 25: 75% (16 cycles) - +$105.78
- Jan 26: 83.33% (12 cycles) - +$100.80
- Jan 29: 70% (20 cycles) - +$16.24
- Jan 30: 87.5% (16 cycles) - +$60.32
- Feb 1: 92.86% (28 cycles) - +$169.36
- Feb 4: 85.71% (14 cycles) - +$22.62

**Weak Days (< 50% win rate):**
- Dec 24: 33.33% (6 cycles) - -$173.84
- Jan 1: 0% (2 cycles) - -$59.89
- Jan 4: 28.57% (7 cycles) - -$44.07
- Jan 5: 25% (8 cycles) - -$179.67
- Jan 7: 0% (4 cycles) - -$161.59
- Jan 9: 40% (10 cycles) - -$168.91
- Jan 12: 33.33% (12 cycles) - -$104.72
- Jan 19: 0% (2 cycles) - -$45.36
- Jan 20: 37.5% (16 cycles) - -$225.72
- Jan 21: 44.44% (18 cycles) - -$133.79
- Jan 23: 42.86% (14 cycles) - -$60.68
- Jan 24: 0% (2 cycles) - -$13.12

---

## 4. KEY FINDINGS FOR LOSING CYCLES

### Strongest Signals (Predicting Losses)

1. **Momentum Reversal Pattern:**
   - Momentum was positive 30m before entry
   - Momentum reversed to negative at entry
   - **Impact:** Average loss of -$60.07

2. **Price Rising Before Entry:**
   - Price rising in 30 minutes before entry
   - **Impact:** Associated with losing cycles

3. **Time-Based Avoidance:**
   - **Hour 14 (2 PM):** 41.18% win rate, -$701.32 total PnL
   - **Hour 10 (10 AM):** 60.61% win rate but -$695.12 total PnL
   - **Hour 21 (9 PM):** 46.67% win rate, -$481.40 total PnL
   - **Hour 18 (6 PM):** 46.15% win rate, -$294.06 total PnL
   - **Hours 0, 3:** 0% win rate

4. **Day-Based Avoidance:**
   - **Monday:** 54.29% win rate, -$612.66 total PnL
   - **Wednesday:** 57.50% win rate, -$833.26 total PnL

### Strongest Signals (Predicting Wins)

1. **Momentum Continuation:**
   - Momentum already negative 30m before
   - Momentum continues/accelerates negative at entry
   - **Impact:** Average gain of +$34.10

2. **Price Falling Before Entry:**
   - Consistent price decline in 30 minutes before entry
   - **Impact:** Associated with winning cycles

3. **Time-Based Enablement:**
   - **Hour 8 (8 AM):** 83.33% win rate
   - **Hour 13 (1 PM):** 75.00% win rate
   - **Hour 15 (3 PM):** 75.00% win rate
   - **Hour 19 (7 PM):** 70.59% win rate
   - **Hour 20 (8 PM):** 72.73% win rate

4. **Day-Based Enablement:**
   - **Sunday:** 75.95% win rate, +$917.55 total PnL
   - **Thursday:** 67.65% win rate, +$423.22 total PnL

---

## 5. MOMENTUM PERCENTILE ANALYSIS

### Momentum at Entry

**Best Performing Ranges:**
- **>= 80 (Extreme Bullish):** 72.22% win rate (52 wins, 20 losses) - +$2.24 avg PnL
- **< -80 (Extreme Bearish):** 66.67% win rate (72 wins, 36 losses) - +$2.40 avg PnL

**Worst Performing Ranges:**
- **0 to 50 (Mild Bullish):** 56.25% win rate (54 wins, 42 losses) - -$4.71 avg PnL
- **50 to 80 (Bullish):** 57.53% win rate (42 wins, 31 losses) - -$3.87 avg PnL
- **-50 to 0 (Mild Bearish):** 60.53% win rate (46 wins, 30 losses) - -$1.16 avg PnL

**Key Finding:** Extreme momentum (either very bullish >= 80 or very bearish < -80) performs better than moderate momentum ranges.

### Volatility Analysis

**Note:** Volatility percentile data is not available in the trades table. This would need to be cross-referenced with price history table.

---

## 6. LOSING CYCLE PATTERNS

### Top Hours for Losing Cycles

1. **Hour 10 (10 AM):** 26 losing cycles, avg loss -$76.13, total -$1,979.30
2. **Hour 11 (11 AM):** 24 losing cycles, avg loss -$64.21, total -$1,541.04
3. **Hour 14 (2 PM):** 20 losing cycles, avg loss -$50.17, total -$1,003.42
4. **Hour 9 (9 AM):** 20 losing cycles, avg loss -$71.35, total -$1,426.96
5. **Hour 21 (9 PM):** 16 losing cycles, avg loss -$63.14, total -$1,010.30

### Worst Hour + Day Combinations

**0% Win Rate (Avoid These):**
- Hour 14 + Friday: 0% (8 cycles, all losses)
- Hour 14 + Tuesday: 0% (4 cycles, all losses)
- Hour 14 + Thursday: 0% (4 cycles, all losses)
- Hour 21 + Tuesday: 0% (4 cycles, all losses)

**Very Low Win Rate (< 30%):**
- Hour 10 + Wednesday: 14.29% (2 wins, 12 losses)
- Hour 12 + Monday: 25% (2 wins, 6 losses)
- Hour 17 + Tuesday: 25% (2 wins, 6 losses)

---

## 7. KEY FINDINGS SUMMARY

### Strongest Signals for LOSING Cycles

1. **Momentum Reversal Pattern** ⭐⭐⭐
   - Momentum was positive 30m before entry (+15.86%)
   - Momentum reversed to negative at entry (-4.81%)
   - Average loss: -$60.07

2. **Price Rising Before Entry** ⭐⭐
   - Price rising in 30 minutes before entry (+0.0322%)
   - Associated with losing cycles

3. **Time-Based Patterns** ⭐⭐
   - **Hour 14 (2 PM):** 41.18% win rate, -$701.32 total PnL
   - **Hour 10 (10 AM):** 60.61% win rate but -$695.12 total PnL (high volume of losses)
   - **Hour 21 (9 PM):** 46.67% win rate, -$481.40 total PnL
   - **Hour 18 (6 PM):** 46.15% win rate, -$294.06 total PnL
   - **Hours 0, 3:** 0% win rate (small sample)

4. **Day-Based Patterns** ⭐
   - **Monday:** 54.29% win rate, -$612.66 total PnL
   - **Wednesday:** 57.50% win rate, -$833.26 total PnL

5. **Moderate Momentum Ranges** ⭐
   - Momentum between 0-80 percentile performs worse than extremes
   - Best performance at extremes: < -80 or >= 80

### Strongest Signals for WINNING Cycles

1. **Momentum Continuation** ⭐⭐⭐
   - Momentum already negative 30m before (-6.14%)
   - Momentum continues/accelerates negative at entry (-19.16%)
   - Average gain: +$34.10

2. **Price Falling Before Entry** ⭐⭐
   - Consistent price decline in 30 minutes before entry (-0.1476%)
   - Associated with winning cycles

3. **Time-Based Patterns** ⭐⭐
   - **Hour 8 (8 AM):** 83.33% win rate, +$141.16 total PnL
   - **Hour 13 (1 PM):** 75.00% win rate, +$552.84 total PnL
   - **Hour 15 (3 PM):** 75.00% win rate, +$452.66 total PnL
   - **Hour 19 (7 PM):** 70.59% win rate, +$426.15 total PnL
   - **Hour 20 (8 PM):** 72.73% win rate, +$286.26 total PnL

4. **Day-Based Patterns** ⭐⭐
   - **Sunday:** 75.95% win rate, +$917.55 total PnL
   - **Thursday:** 67.65% win rate, +$423.22 total PnL

5. **Extreme Momentum** ⭐
   - Momentum < -80: 66.67% win rate
   - Momentum >= 80: 72.22% win rate

---

## 8. RECOMMENDED ENABLE/DISABLE RULES

### High Confidence DISABLE Signals

1. **Momentum Reversal:**
   - IF momentum_30m_before > 0 AND momentum_at_entry < 0
   - THEN DISABLE (momentum reversing from positive to negative)

2. **Price Rising:**
   - IF price_change_30m_before > 0
   - THEN DISABLE (price rising before entry)

3. **Time-Based:**
   - DISABLE during Hour 14 (2 PM)
   - DISABLE during Hour 10 (10 AM) - high loss volume
   - DISABLE during Hour 21 (9 PM)
   - DISABLE during Hour 18 (6 PM)
   - DISABLE during Hours 0, 3 (midnight/early morning)

4. **Day-Based:**
   - Consider DISABLING on Mondays
   - Consider DISABLING on Wednesdays

5. **Combination Rules:**
   - DISABLE Hour 14 + Friday/Tuesday/Thursday (0% win rate)
   - DISABLE Hour 21 + Tuesday (0% win rate)
   - DISABLE Hour 10 + Wednesday (14.29% win rate)

### High Confidence ENABLE Signals

1. **Momentum Continuation:**
   - IF momentum_30m_before < 0 AND momentum_at_entry < momentum_30m_before
   - THEN ENABLE (momentum continuing/accelerating negative)

2. **Price Falling:**
   - IF price_change_30m_before < -0.1%
   - THEN ENABLE (price falling before entry)

3. **Time-Based:**
   - ENABLE during Hour 8 (8 AM) - 83.33% win rate
   - ENABLE during Hour 13 (1 PM) - 75.00% win rate
   - ENABLE during Hour 15 (3 PM) - 75.00% win rate
   - ENABLE during Hour 19 (7 PM) - 70.59% win rate
   - ENABLE during Hour 20 (8 PM) - 72.73% win rate

4. **Day-Based:**
   - ENABLE on Sundays - 75.95% win rate
   - ENABLE on Thursdays - 67.65% win rate

5. **Momentum-Based:**
   - ENABLE when momentum < -80 (extreme bearish) - 66.67% win rate
   - ENABLE when momentum >= 80 (extreme bullish) - 72.22% win rate

---

## 9. NEXT STEPS

1. **Validate momentum reversal pattern** - Strongest signal, needs backtesting
2. **Test time-based filters** - Hours 14, 10, 21, 18 show poor performance
3. **Analyze day-of-week patterns** - Monday and Wednesday underperform
4. **Combine signals** - Multi-factor analysis may improve prediction
5. **Backtest enable/disable rules** - Test specific combinations
6. **Cross-reference volatility** - Need to join with price history table

---

## Data Quality Notes

- All analysis based on 497 cycles with complete data
- Price history cross-reference: 185 losing cycles, 308 winning cycles matched
- Momentum data available for most cycles
- Volatility percentile: Not available in trades table, would need price history join
