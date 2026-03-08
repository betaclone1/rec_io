# Volatility Percentile Analysis - Findings

## Key Findings from BTC Price History

### 1. Volatility at Entry

**Winning Cycles:**
- Average volatility at entry: **76.97%** (higher)
- Range: 18.70% to 99.50%
- Average cycle PnL: **+$35.20**

**Losing Cycles:**
- Average volatility at entry: **72.45%** (lower)
- Range: 2.30% to 96.40%
- Average cycle PnL: **-$59.39**

**Finding:** Winning cycles occur in slightly higher volatility environments, but both are in high volatility ranges.

### 2. Volatility Trend (1 Hour Before Entry)

**Best Performing Patterns:**
- **Volatility Rising (> +10):** 65.33% win rate, +$2.34 total PnL (75 cycles)
  - Large volatility spike in the hour before entry
- **Volatility Falling (0 to -10):** 63.04% win rate, +$166.58 total PnL (46 cycles)
  - Moderate volatility decrease

**Worst Performing Patterns:**
- **Volatility Rising (0 to +10):** 57.58% win rate, -$269.87 total PnL (33 cycles) ⚠️
  - Moderate volatility increase - WORST PERFORMER
- **Volatility Falling (< -10):** 55.36% win rate, -$234.26 total PnL (56 cycles) ⚠️
  - Large volatility decrease - POOR PERFORMER

**Key Finding:** ⭐⭐
- **Moderate volatility increases (0 to +10) are the WORST pattern** - 57.58% win rate, -$269.87 total PnL
- Large volatility spikes (> +10) perform well
- Moderate volatility decreases (0 to -10) perform well
- Large volatility decreases (< -10) perform poorly

### 3. Volatility Percentile Ranges at Entry

**Best Performing:**
- **>= 75th percentile:** 65.41% win rate (87 wins, 46 losses) - -$1.73 avg PnL
- **< 25th percentile:** 60.00% win rate (3 wins, 2 losses) - +$33.55 avg PnL (small sample)

**Worst Performing:**
- **50-75th percentile:** 50.98% win rate (26 wins, 25 losses) - -$7.39 avg PnL ⚠️
- **25-50th percentile:** 54.55% win rate (12 wins, 10 losses) - +$0.68 avg PnL

**Finding:** Very high volatility (>= 75th) performs best, but moderate volatility (50-75th) performs worst.

### 4. Volatility Acceleration Pattern

**Winning Cycles:**
- Volatility change 1h before: **+6.45%**
- Volatility change 1h to 2h before: **+12.28%**
- Acceleration: **-5.82%** (volatility was rising faster, then slowed)

**Losing Cycles:**
- Volatility change 1h before: **+4.96%**
- Volatility change 1h to 2h before: **+4.31%**
- Acceleration: **+0.65%** (volatility rising more steadily)

**Finding:** Winning cycles show volatility that was accelerating upward, then slowed. Losing cycles show more steady volatility increases.

### 5. Volatility Over Multiple Timeframes

**Winning Cycles:**
- At entry: 76.97%
- 1 hour before: 70.51%
- 2 hours before: 58.24%
- 4 hours before: 49.13%
- **Pattern:** Volatility increasing over 4 hours leading to entry

**Losing Cycles:**
- At entry: 72.45%
- 1 hour before: 68.03%
- 2 hours before: 63.72%
- 4 hours before: 51.13%
- **Pattern:** Volatility also increasing, but from a higher base

**Finding:** Both show volatility increasing, but winning cycles start from lower volatility 4 hours before.

---

## STRONGEST SIGNALS

### For LOSING Cycles (Disable Strategy)

1. **Moderate Volatility Increase (0 to +10)** ⭐⭐⭐
   - Volatility rising 0 to 10 points in 1 hour before entry
   - 57.58% win rate, -$269.87 total PnL
   - **STRONGEST NEGATIVE SIGNAL**

2. **Large Volatility Decrease (< -10)** ⭐⭐
   - Volatility falling more than 10 points in 1 hour before entry
   - 55.36% win rate, -$234.26 total PnL

3. **Moderate Volatility Range (50-75th percentile)** ⭐
   - Volatility between 50th and 75th percentile at entry
   - 50.98% win rate, -$7.39 avg PnL

### For WINNING Cycles (Enable Strategy)

1. **Large Volatility Spike (> +10)** ⭐⭐⭐
   - Volatility rising more than 10 points in 1 hour before entry
   - 65.33% win rate, +$2.34 total PnL
   - **STRONGEST POSITIVE SIGNAL**

2. **Moderate Volatility Decrease (0 to -10)** ⭐⭐
   - Volatility falling 0 to 10 points in 1 hour before entry
   - 63.04% win rate, +$166.58 total PnL
   - **BEST PnL PERFORMER**

3. **Very High Volatility (>= 75th percentile)** ⭐
   - Volatility at or above 75th percentile at entry
   - 65.41% win rate

---

## RECOMMENDED RULES

### DISABLE Strategy When:
- Volatility rising 0 to 10 points in 1 hour before entry (moderate increase)
- Volatility falling more than 10 points in 1 hour before entry (large decrease)
- Volatility between 50-75th percentile at entry

### ENABLE Strategy When:
- Volatility rising more than 10 points in 1 hour before entry (large spike)
- Volatility falling 0 to 10 points in 1 hour before entry (moderate decrease)
- Volatility at or above 75th percentile at entry

---

## Key Insight

**The volatility trend pattern is more predictive than absolute volatility level.**

The most important signal is the **change in volatility in the hour before entry**:
- Large spikes (> +10) = Good
- Moderate increases (0 to +10) = Bad
- Moderate decreases (0 to -10) = Good
- Large decreases (< -10) = Bad

This suggests the strategy works best when volatility is either:
1. Spiking dramatically (panic/breakout)
2. Moderately decreasing (stabilizing after a spike)

But fails when volatility is:
1. Moderately increasing (building pressure)
2. Dramatically decreasing (crash/panic subsiding)
