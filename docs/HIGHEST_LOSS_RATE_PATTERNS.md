# Highest Loss Rate Patterns - Analysis

## Top Loss Rate Patterns (DISABLE Strategy)

### 1. STRONGEST SIGNAL: Combination (1 Hour Window) ⭐⭐⭐

**Volatility < 50 / Momentum < 40:**
- **75.00% loss rate** (3 losses, 1 win)
- -$13.15 avg cycle PnL
- **4 cycles** (small sample but very strong signal)

### 2. Momentum < 40 (2 Hour Window) ⭐⭐

**Average Absolute Momentum < 40 (2 hours before entry):**
- **71.43% loss rate** (5 losses, 2 wins)
- -$31.49 avg cycle PnL
- **7 cycles**

### 3. Volatility < 50 (1 Hour Window) ⭐⭐

**Average Absolute Volatility < 50 (1 hour before entry):**
- **58.82% loss rate** (10 losses, 7 wins)
- -$19.46 avg cycle PnL
- **17 cycles**

### 4. Combination: Volatility < 50 / Momentum 40-60 (1 Hour) ⭐

**Volatility < 50 / Momentum 40-60:**
- **53.85% loss rate** (7 losses, 6 wins)
- -$21.40 avg cycle PnL
- **13 cycles**

### 5. Momentum 60-80 Range (Multiple Windows) ⚠️

**Average Absolute Momentum 60-80:**
- **1 Hour:** 41.96% loss rate (47 losses, 65 wins) - -$8.77 avg PnL
- **2 Hours:** 41.12% loss rate (44 losses, 63 wins) - -$5.45 avg PnL
- **3 Hours:** 44.09% loss rate (41 losses, 52 wins) - -$7.98 avg PnL
- **4 Hours:** 38.96% loss rate (30 losses, 47 wins) - -$3.49 avg PnL

**Pattern:** High absolute momentum (60-80) consistently underperforms across all time windows.

### 6. Volatility 70-85 Range (Multiple Windows) ⚠️

**Average Absolute Volatility 70-85:**
- **1 Hour:** 43.02% loss rate (37 losses, 49 wins) - -$7.29 avg PnL
- **2 Hours:** 39.13% loss rate (36 losses, 56 wins) - -$3.19 avg PnL
- **3 Hours:** 43.59% loss rate (34 losses, 44 wins) - -$6.46 avg PnL

**Pattern:** High absolute volatility (70-85) consistently underperforms.

### 7. Combination: Volatility 70-85 / Momentum 60-80 (1 Hour) ⚠️

**Volatility 70-85 / Momentum 60-80:**
- **44.93% loss rate** (31 losses, 38 wins)
- -$9.58 avg cycle PnL
- **69 cycles** (largest sample size for a losing combination)

---

## Summary of Highest Loss Rate Patterns

### Top 5 Highest Loss Rate Patterns:

1. **Volatility < 50 / Momentum < 40 (1h):** 75.00% loss rate ⭐⭐⭐
2. **Momentum < 40 (2h):** 71.43% loss rate ⭐⭐
3. **Volatility < 50 (1h):** 58.82% loss rate ⭐⭐
4. **Volatility < 50 / Momentum 40-60 (1h):** 53.85% loss rate ⭐
5. **Momentum 60-80 (3h):** 44.09% loss rate

### Consistent Underperformers:

1. **Momentum 60-80 range:** 38-44% loss rate across all time windows
2. **Volatility 70-85 range:** 39-43% loss rate across multiple windows
3. **Combination: Volatility 70-85 / Momentum 60-80:** 44.93% loss rate (69 cycles)

---

## Recommended DISABLE Rules

### High Confidence DISABLE (Strongest Signals):

1. **Volatility < 50 AND Momentum < 40 (1 hour):**
   - 75.00% loss rate
   - DISABLE when both conditions met

2. **Momentum < 40 (2 hours):**
   - 71.43% loss rate
   - DISABLE when momentum too low over 2 hours

3. **Volatility < 50 (1 hour):**
   - 58.82% loss rate
   - DISABLE when volatility too low

### Medium Confidence DISABLE:

4. **Momentum 60-80 (any time window):**
   - 38-44% loss rate consistently
   - DISABLE when momentum too high

5. **Volatility 70-85 (1-3 hours):**
   - 39-43% loss rate
   - DISABLE when volatility too high

6. **Combination: Volatility 70-85 / Momentum 60-80 (1 hour):**
   - 44.93% loss rate
   - 69 cycles (largest losing sample)
   - DISABLE when both conditions met

---

## Key Insights

1. **Low volatility + Low momentum = Worst combination**
   - Volatility < 50 AND Momentum < 40 = 75% loss rate
   - This is the strongest negative signal

2. **High momentum (60-80) consistently underperforms**
   - Across all time windows, 60-80 momentum range has 38-44% loss rates
   - This suggests extreme momentum (either very high or very low) is better than moderate-high

3. **High volatility (70-85) underperforms**
   - Not as bad as low volatility, but still 39-43% loss rates
   - The "sweet spot" is 50-70, not higher

4. **Combination of high volatility + high momentum = Bad**
   - 70-85 volatility / 60-80 momentum = 44.93% loss rate
   - 69 cycles affected (significant sample size)

---

## Comparison: Best vs Worst

**BEST (Enable):**
- Volatility 50-70 / Momentum 40-60 (3h): 26.23% loss rate (73.77% win rate) ⭐

**WORST (Disable):**
- Volatility < 50 / Momentum < 40 (1h): 75.00% loss rate ⚠️

**Difference:** 48.77 percentage point swing in loss rate!
