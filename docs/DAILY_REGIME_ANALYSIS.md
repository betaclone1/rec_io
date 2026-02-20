# Daily Regime Analysis — Monitor 10020 (Momentum Breakout)

## Objective

Find metrics **available at the start of each day** that predict day-level performance and could improve results.

---

## 1. Data

- **57 trading days** (Dec 19, 2025 – Feb 17, 2026)
- **428 cycles** total, 251 wins, 177 losses
- **Baseline total PnL:** -$988.48
- **Baseline day-level win rate:** 58.6%

---

## 2. Start-of-Day Metrics

We can only use information available before the first trade. Options:

1. **Previous day’s full-day avg** movement_percentile, volatility_percentile (available at midnight)
2. **First 3 or 6 hours** of today (available by 3am or 6am — would miss early trades)
3. **Day of week**

---

## 3. Previous Day’s Movement & Volatility

| Previous day avg movement | Days | Cycles | Win % | Total PnL |
|---------------------------|------|--------|-------|-----------|
| 0–50                      | 34   | 167    | 59.3  | -$170     |
| 50–70                     | 11   | 89     | 62.9  | -$21      |
| 70+                       | 12   | 172    | 55.8  | -$797     |

| Previous day avg volatility | Days | Cycles | Win % | Total PnL |
|-----------------------------|------|--------|-------|-----------|
| 0–50                        | 32   | 149    | 58.4  | -$175     |
| 50–70                       | 14   | 128    | **65.6** | **+$193** |
| 70+                         | 11   | 151    | 53.0  | -$1,007   |

### Finding: Skip Days After Very High Previous Regime

When **previous day avg movement ≥ 70** and **previous day avg volatility ≥ 70**:

- 11 days, 151 cycles, 53.0% win rate, **-$1,007 PnL**
- These days drive most of the loss.

**Filter: Skip trading today when (yesterday avg movement ≥ 70) AND (yesterday avg volatility ≥ 70)**

- Skipped: 11 days, 151 cycles, -$1,007
- Traded: 46 days, 277 cycles, **+$18 PnL**
- Baseline: -$988 → **+$18** (~$1,000 improvement)

---

## 4. Sweet Spot: Previous Day Volatility 50–70

When **previous day avg volatility** is between 50–70:

- 14 days, 128 cycles
- 65.6% win rate
- **+$193 total PnL**

This is the strongest regime, but only 14 days qualify.

---

## 5. First 6 Hours of Today

Using the first 6 hours (00:00–05:59) as “opening regime”:

- No clear benefit to high opening movement/volatility
- `mov_6h_0-30` performs best in PnL (+$6.50)
- `mov_6h_70+` is still negative (-$101)
- First-6h metrics do not improve performance

---

## 6. Day of Week

| Day  | Days | Cycles | Win % | Total PnL |
|------|------|--------|-------|-----------|
| Sun  | 9    | 69     | **66.7** | **+$429** |
| Mon  | 9    | 60     | 45.0  | -$655     |
| Tue  | 9    | 81     | 56.8  | -$208     |
| Wed  | 8    | 69     | 63.8  | -$237     |
| Thu  | 8    | 64     | 62.5  | +$58      |
| Fri  | 9    | 56     | 60.7  | -$216     |
| Sat  | 5    | 29     | 48.3  | -$159     |

Sunday performs best; Monday performs worst. Day-of-week alone is exploratory and could be tested as an extra filter.

---

## 7. Practical Recommendations

### Primary: Previous-Day Regime Filter

- **Skip today** when yesterday’s avg movement_percentile ≥ 70 **and** yesterday’s avg volatility_percentile ≥ 70.
- Backtest effect: -$988 → +$18.

### Optional

- **Focus on prev_vol 50–70:** Best regime (65.6% win, +$193), but limited to ~14 days.
- **Day of week:** Sunday strong (+$429), Monday weak (-$655); could be used as a secondary filter after validation.
