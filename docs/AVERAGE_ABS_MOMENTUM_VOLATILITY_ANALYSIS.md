# Average Absolute Momentum & Volatility Analysis

## Analysis Overview

Looking at the average absolute value of momentum_percentile and volatility_percentile over different time periods BEFORE cycle entry to find correlations with win/loss rates.

---

## Summary Results

### Average Absolute Values by Time Period

| Time Period | Cycle Result | Cycles | Avg ABS Momentum | Avg ABS Volatility |
|-------------|--------------|--------|------------------|-------------------|
| **1 Hour** | Losing | 83 | 61.52 | 70.54 |
| **1 Hour** | Winning | 128 | 62.25 | 72.34 |
| **12 Hours** | Losing | 83 | 49.18 | 48.76 |
| **12 Hours** | Winning | 129 | 49.48 | 49.14 |
| **24 Hours** | Losing | 84 | 48.83 | 48.01 |
| **24 Hours** | Winning | 130 | 48.74 | 48.29 |
| **48 Hours** | Losing | 84 | 46.88 | 45.39 |
| **48 Hours** | Winning | 130 | 46.88 | 45.67 |

### Key Observations

1. **1 Hour Window:**
   - Winning cycles: Slightly higher avg abs momentum (62.25 vs 61.52)
   - Winning cycles: Slightly higher avg abs volatility (72.34 vs 70.54)
   - **Difference is minimal** (~1-2 percentage points)

2. **12-48 Hour Windows:**
   - Differences are even smaller (< 1 percentage point)
   - Values converge to ~48-49 for momentum, ~45-48 for volatility
   - **No significant difference** between winning and losing cycles

---

## Range Analysis (1 Hour Window)

### Average Absolute Momentum (1 Hour Before Entry)

| Range | Total Cycles | Wins | Losses | Win Rate | Avg Cycle PnL |
|-------|--------------|------|--------|----------|---------------|
| < 40 | 4 | 1 | 3 | 25.00% | -$13.15 |
| **40-60** | **86** | **56** | **30** | **65.12%** | **+$7.85** ⭐ |
| 60-80 | 112 | 65 | 47 | 58.04% | -$8.77 ⚠️ |
| >= 80 | 9 | 6 | 3 | 66.67% | -$7.15 |

**Key Finding:** ⭐
- **40-60 range performs BEST:** 65.12% win rate, +$7.85 avg PnL
- **60-80 range performs WORST:** 58.04% win rate, -$8.77 avg PnL
- Moderate absolute momentum (40-60) is optimal

### Average Absolute Volatility (1 Hour Before Entry)

| Range | Total Cycles | Wins | Losses | Win Rate | Avg Cycle PnL |
|-------|--------------|------|--------|----------|---------------|
| < 50 | 17 | 7 | 10 | 41.18% | -$19.46 ⚠️ |
| **50-70** | **68** | **46** | **22** | **67.65%** | **+$11.78** ⭐ |
| 70-85 | 86 | 49 | 37 | 56.98% | -$7.29 ⚠️ |
| >= 85 | 40 | 26 | 14 | 65.00% | -$6.67 |

**Key Finding:** ⭐⭐
- **50-70 range performs BEST:** 67.65% win rate, +$11.78 avg PnL
- **< 50 range performs WORST:** 41.18% win rate, -$19.46 avg PnL
- **70-85 range also poor:** 56.98% win rate, -$7.29 avg PnL
- Moderate absolute volatility (50-70) is optimal

---

## Key Findings

### Strong Signals

1. **Average Absolute Volatility 50-70 (1 hour):** ⭐⭐
   - 67.65% win rate, +$11.78 avg PnL
   - **STRONGEST SIGNAL** from this analysis

2. **Average Absolute Momentum 40-60 (1 hour):** ⭐
   - 65.12% win rate, +$7.85 avg PnL
   - Good performance

### Weak Signals

1. **Average Absolute Volatility < 50 (1 hour):** ⚠️
   - 41.18% win rate, -$19.46 avg PnL
   - **DISABLE when volatility too low**

2. **Average Absolute Volatility 70-85 (1 hour):** ⚠️
   - 56.98% win rate, -$7.29 avg PnL
   - **DISABLE when volatility too high**

3. **Average Absolute Momentum 60-80 (1 hour):** ⚠️
   - 58.04% win rate, -$8.77 avg PnL
   - **DISABLE when momentum too high**

### Conclusion

**There ARE meaningful patterns when looking at ranges:**

1. **Volatility "Sweet Spot":** Average absolute volatility between 50-70 in the hour before entry performs best (67.65% win rate)
2. **Volatility "Dead Zones":** 
   - Too low (< 50): 41.18% win rate
   - Too high (70-85): 56.98% win rate
3. **Momentum "Sweet Spot":** Average absolute momentum between 40-60 performs best (65.12% win rate)
4. **Longer time periods (12-48 hours) show minimal differences** - the 1 hour window is most predictive

---

## Recommended Rules

### ENABLE Strategy When (1 hour before entry):
- Average absolute volatility between 50-70 percentile
- Average absolute momentum between 40-60 percentile

### DISABLE Strategy When (1 hour before entry):
- Average absolute volatility < 50 percentile (too low)
- Average absolute volatility between 70-85 percentile (too high)
- Average absolute momentum between 60-80 percentile (too high)
