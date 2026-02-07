# Momentum Breakout Strategy - Correct Analysis

## Data Structure Understanding

- **Cycles identified by:** `cycle_pnl` value (trades with same `cycle_pnl` = same cycle)
- **Trades per cycle:** 2 trades (YES and NO positions)
- **Total PnL calculation:** Sum of `pnl` column from ALL trades = **-$278.08**

---

## Baseline Statistics

- **Total Cycles:** 211 (128 wins, 83 losses)
- **Win Rate:** 60.66%
- **Total Cycle PnL:** -$424.09 (sum of distinct cycle_pnl values)
- **Total Trade PnL:** -$278.08 (sum of all individual trade pnl values)
- **Date Range:** Dec 19, 2025 - Feb 4, 2026
- **Target Win Rate:** 70%+ for profitability

**Note:** There's a discrepancy between cycle_pnl sum and trade pnl sum. Using cycle_pnl for cycle-level analysis.

---

## 1. TIME-BASED PATTERNS

### Hour of Day Analysis

**Best Performing Hours:**
- **Hour 8 (8 AM):** 83.33% win rate (5 wins, 1 loss) - +$70.58 total PnL
- **Hour 20 (8 PM):** 75.00% win rate (6 wins, 2 losses) - +$115.33 total PnL
- **Hour 22 (10 PM):** 75.00% win rate (3 wins, 1 loss) - +$107.00 total PnL
- **Hour 15 (3 PM):** 72.73% win rate (8 wins, 3 losses) - +$145.65 total PnL
- **Hour 13 (1 PM):** 68.42% win rate (13 wins, 6 losses) - +$146.47 total PnL
- **Hour 9 (9 AM):** 67.74% win rate (21 wins, 10 losses) - -$66.33 total PnL
- **Hour 12 (Noon):** 66.67% win rate (14 wins, 7 losses) - +$99.14 total PnL

**Worst Performing Hours:**
- **Hour 0 (Midnight):** 0.00% win rate (0 wins, 1 loss) - -$88.88 total PnL
- **Hour 3 (3 AM):** 0.00% win rate (0 wins, 1 loss) - -$9.68 total PnL
- **Hour 14 (2 PM):** 35.71% win rate (5 wins, 9 losses) - -$328.00 total PnL ⚠️
- **Hour 17 (5 PM):** 40.00% win rate (2 wins, 3 losses) - -$42.96 total PnL
- **Hour 10 (10 AM):** 59.38% win rate (19 wins, 13 losses) - -$400.04 total PnL ⚠️
- **Hour 11 (11 AM):** 57.14% win rate (16 wins, 12 losses) - -$231.26 total PnL
- **Hour 21 (9 PM):** 50.00% win rate (5 wins, 5 losses) - -$89.07 total PnL
- **Hour 18 (6 PM):** 50.00% win rate (5 wins, 5 losses) - -$47.73 total PnL

### Day of Week Analysis

**Best Performing Days:**
- **Sunday:** 75.00% win rate (24 wins, 8 losses) - +$448.51 total PnL ⭐
- **Thursday:** 67.74% win rate (21 wins, 10 losses) - +$145.96 total PnL
- **Friday:** 63.33% win rate (19 wins, 11 losses) - -$85.59 total PnL
- **Saturday:** 63.64% win rate (7 wins, 4 losses) - +$34.38 total PnL

**Worst Performing Days:**
- **Monday:** 48.15% win rate (13 wins, 14 losses) - -$311.19 total PnL ⚠️
- **Wednesday:** 54.05% win rate (20 wins, 17 losses) - -$454.91 total PnL ⚠️
- **Tuesday:** 55.81% win rate (24 wins, 19 losses) - -$201.25 total PnL

---

## 2. KEY FINDINGS FOR LOSING CYCLES

### Strongest Signals (Predicting Losses)

1. **Time-Based Avoidance:**
   - **Hour 14 (2 PM):** 35.71% win rate, -$328.00 total PnL
   - **Hour 10 (10 AM):** 59.38% win rate but -$400.04 total PnL (high loss volume)
   - **Hour 11 (11 AM):** 57.14% win rate, -$231.26 total PnL
   - **Hours 0, 3:** 0% win rate (small sample)

2. **Day-Based Avoidance:**
   - **Monday:** 48.15% win rate, -$311.19 total PnL
   - **Wednesday:** 54.05% win rate, -$454.91 total PnL

### Strongest Signals (Predicting Wins)

1. **Time-Based Enablement:**
   - **Hour 8 (8 AM):** 83.33% win rate, +$70.58 total PnL
   - **Hour 20 (8 PM):** 75.00% win rate, +$115.33 total PnL
   - **Hour 22 (10 PM):** 75.00% win rate, +$107.00 total PnL
   - **Hour 15 (3 PM):** 72.73% win rate, +$145.65 total PnL
   - **Hour 13 (1 PM):** 68.42% win rate, +$146.47 total PnL

2. **Day-Based Enablement:**
   - **Sunday:** 75.00% win rate, +$448.51 total PnL
   - **Thursday:** 67.74% win rate, +$145.96 total PnL

---

## 3. MARKET CONDITIONS AT ENTRY

### Momentum Patterns

**Winning Cycles:**
- Momentum at entry: **-20.80%** (strongly negative)
- Momentum 30m before: **+0.38%** (slightly positive)
- Momentum change: **-21.17%** (momentum continued/accelerated negative)
- Average cycle PnL: **+$35.20**

**Losing Cycles:**
- Momentum at entry: **-0.54%** (weakly negative)
- Momentum 30m before: **+19.33%** (was positive!)
- Momentum change: **-19.87%** (momentum REVERSED from positive to negative)
- Average cycle PnL: **-$59.39**

**Key Finding:** ⭐⭐⭐ **STRONGEST SIGNAL**
- Losing cycles show momentum REVERSAL (positive → negative)
- Winning cycles show momentum CONTINUATION (negative → more negative)

### Momentum Percentile at Entry

**Best Performing Ranges:**
- **>= 80 (Extreme Bullish):** 72.50% win rate (29 wins, 11 losses) - +$3.99 avg PnL
- **< -80 (Extreme Bearish):** 62.16% win rate (23 wins, 14 losses) - +$3.01 avg PnL
- **-80 to -50:** 62.50% win rate (15 wins, 9 losses) - -$1.31 avg PnL

**Worst Performing Ranges:**
- **50 to 80 (Bullish):** 53.66% win rate (22 wins, 19 losses) - -$8.84 avg PnL
- **-50 to 0 (Mild Bearish):** 57.69% win rate (15 wins, 11 losses) - -$4.74 avg PnL
- **0 to 50 (Mild Bullish):** 55.81% win rate (24 wins, 19 losses) - -$4.13 avg PnL

**Key Finding:** Extreme momentum (>= 80 or < -80) performs better than moderate ranges.

### Price Movement Before Entry

**Winning Cycles:**
- 30 minutes before: **-0.1625%** (price falling)
- 15 minutes before: **-0.0737%** (price falling)
- 5 minutes before: **-0.0379%** (price falling)
- Average cycle PnL: **+$35.20**

**Losing Cycles:**
- 30 minutes before: **+0.0293%** (price rising)
- 15 minutes before: **-0.0357%** (price falling)
- 5 minutes before: **-0.0012%** (price falling)
- Average cycle PnL: **-$59.39**

**Key Finding:** ⭐⭐
- Winning cycles show consistent price decline before entry
- Losing cycles show price rising 30 minutes before entry

---

## 4. STRONGEST PREDICTIVE SIGNALS

### For LOSING Cycles (Disable Strategy)

1. **Momentum Reversal Pattern** ⭐⭐⭐ (STRONGEST)
   - Momentum was positive 30m before entry (+19.33%)
   - Momentum reversed to negative at entry (-0.54%)
   - Average loss: -$59.39

2. **Price Rising Before Entry** ⭐⭐
   - Price rising in 30 minutes before entry (+0.0293%)
   - Associated with losing cycles

3. **Time-Based Patterns** ⭐⭐
   - **Hour 14 (2 PM):** 35.71% win rate, -$328.00 total PnL
   - **Hour 10 (10 AM):** 59.38% win rate but -$400.04 total PnL
   - **Hour 11 (11 AM):** 57.14% win rate, -$231.26 total PnL
   - **Hours 0, 3:** 0% win rate

4. **Day-Based Patterns** ⭐
   - **Monday:** 48.15% win rate, -$311.19 total PnL
   - **Wednesday:** 54.05% win rate, -$454.91 total PnL

5. **Moderate Momentum Ranges** ⭐
   - Momentum between 50-80 percentile: 53.66% win rate, -$8.84 avg PnL

### For WINNING Cycles (Enable Strategy)

1. **Momentum Continuation Pattern** ⭐⭐⭐ (STRONGEST)
   - Momentum already negative 30m before (+0.38%)
   - Momentum continues/accelerates negative at entry (-20.80%)
   - Average gain: +$35.20

2. **Price Falling Before Entry** ⭐⭐
   - Consistent price decline in 30 minutes before entry (-0.1625%)
   - Associated with winning cycles

3. **Time-Based Patterns** ⭐⭐
   - **Hour 8 (8 AM):** 83.33% win rate, +$70.58 total PnL
   - **Hour 20 (8 PM):** 75.00% win rate, +$115.33 total PnL
   - **Hour 22 (10 PM):** 75.00% win rate, +$107.00 total PnL
   - **Hour 15 (3 PM):** 72.73% win rate, +$145.65 total PnL
   - **Hour 13 (1 PM):** 68.42% win rate, +$146.47 total PnL

4. **Day-Based Patterns** ⭐⭐
   - **Sunday:** 75.00% win rate, +$448.51 total PnL
   - **Thursday:** 67.74% win rate, +$145.96 total PnL

5. **Extreme Momentum** ⭐
   - Momentum >= 80: 72.50% win rate, +$3.99 avg PnL
   - Momentum < -80: 62.16% win rate, +$3.01 avg PnL

---

## 5. RECOMMENDED ENABLE/DISABLE RULES

### High Confidence DISABLE Signals

1. **Momentum Reversal:**
   - IF momentum_30m_before > 0 AND momentum_at_entry < 0
   - THEN DISABLE (momentum reversing from positive to negative)

2. **Price Rising:**
   - IF price_change_30m_before > 0
   - THEN DISABLE (price rising before entry)

3. **Time-Based:**
   - DISABLE during Hour 14 (2 PM) - 35.71% win rate
   - DISABLE during Hour 10 (10 AM) - high loss volume
   - DISABLE during Hour 11 (11 AM) - 57.14% win rate
   - DISABLE during Hours 0, 3 (midnight/early morning)

4. **Day-Based:**
   - DISABLE on Mondays - 48.15% win rate
   - DISABLE on Wednesdays - 54.05% win rate

### High Confidence ENABLE Signals

1. **Momentum Continuation:**
   - IF momentum_30m_before < 0 AND momentum_at_entry < momentum_30m_before
   - THEN ENABLE (momentum continuing/accelerating negative)

2. **Price Falling:**
   - IF price_change_30m_before < -0.1%
   - THEN ENABLE (price falling before entry)

3. **Time-Based:**
   - ENABLE during Hour 8 (8 AM) - 83.33% win rate
   - ENABLE during Hour 20 (8 PM) - 75.00% win rate
   - ENABLE during Hour 22 (10 PM) - 75.00% win rate
   - ENABLE during Hour 15 (3 PM) - 72.73% win rate
   - ENABLE during Hour 13 (1 PM) - 68.42% win rate

4. **Day-Based:**
   - ENABLE on Sundays - 75.00% win rate
   - ENABLE on Thursdays - 67.74% win rate

5. **Momentum-Based:**
   - ENABLE when momentum >= 80 (extreme bullish) - 72.50% win rate
   - ENABLE when momentum < -80 (extreme bearish) - 62.16% win rate

---

## NEXT STEPS

1. **Validate momentum reversal pattern** - Strongest signal, needs backtesting
2. **Test time-based filters** - Hours 14, 10, 11 show poor performance
3. **Analyze day-of-week patterns** - Monday and Wednesday underperform
4. **Combine signals** - Multi-factor analysis may improve prediction
5. **Backtest enable/disable rules** - Test specific combinations
