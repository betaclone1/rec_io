# Day Analysis: 2026-02-11 (Monitor 10020, Momentum Breakout)

## Summary

- **21 cycles**, 16 wins, 5 losses — **76.2% win rate**
- **+$209.96 total PnL**
- Strong day; user described it as "MASSIVE success" with near 100% win rate

---

## BTC Price Log Context (historical_data.btc_price_history)

### Full-day regime

- **Avg movement_percentile:** 76.3
- **Avg volatility_percentile:** 75.3  
- **Avg |momentum_percentile|:** 63.7  
- **Price range:** $65,754 – $68,516 (~$2,762)

2/11/26 was a high movement/volatility day: both movement and volatility were well above the 50th percentile and near the top of recent days (higher than 2/12, 2/13, 2/14).

---

## Cycle-by-cycle at entry (:45 each hour)

| Hour | Mom % | Vol % | Mov % | Outcome |
|------|-------|-------|-------|---------|
| 1am  | -59   | 65    | 70    | L       |
| 2am  | -95   | 84    | 87    | L       |
| 3am  | 89    | 74    | 77    | L       |
| 4am  | 38    | 53    | 58    | L       |
| 6am  | 67    | 62    | 64    | W       |
| 7am  | 70    | 57    | 56    | W       |
| 8am  | -12   | 42    | 45    | L       |
| 9am  | 86    | 88    | 83    | W       |
| 10am | 51    | **99**| **99**| W       |
| 11am | 90    | 93    | 93    | W       |
| 12pm | -93   | 95    | 97    | W       |
| 1pm  | -95   | 95    | 95    | W       |
| 2pm  | 78    | 78    | 73    | W       |
| 3pm  | -95   | **97**| 96    | W       |
| 4pm  | -60   | 62    | 55    | W       |
| 6pm  | -62   | 56    | 61    | W       |
| 7pm  | -62   | 71    | 74    | W       |
| 8pm  | 93    | 84    | 75    | W       |
| 9pm  | -73   | 66    | 74    | W       |
| 10pm | 39    | 57    | 61    | W       |
| 12am | -38   | 73    | 69    | W       |

---

## Findings

### 1. Overnight losses (1am–4am)

- 4 straight losses.
- 2am: mov 87, mom -95 — high movement but extreme negative momentum.
- 3am: mov 77, mom +89 — high movement, extreme positive momentum (reversal).
- Likely **momentum whiplash**: 2am extreme down, 3am extreme up; choppy, reversal conditions where breakouts often fail.

### 2. 8am loss

- mov 45, vol 42 — low movement and low volatility.
- Matches our **avoid** rule: low movement + low volatility.

### 3. Mid-day strength (9am–3pm)

- Volatility 88–99; movement 83–97.
- 7 wins in a row; regime where breakouts work well.
- Very high vol/movement regime drove most of the day’s profits.

### 4. Movement 80+ filter on this day

- Would have kept 14 cycles (mov > 80).
- Would have excluded 7 cycles (mov ≤ 80); all 7 were winners.
- 5 losses: 1am (70), 2am (87), 3am (77), 4am (58), 8am (45).
  - With mov > 80: keep 2am (L), drop 1am, 3am, 4am, 8am (all L).
  - Result: 1 loss instead of 5, but also 7 fewer wins.
- On this particular day, the mov > 80 filter would have reduced PnL because many winners had mov 55–77 in a favorable overall regime.

### 5. Main takeaway

- 2/11/26 worked because it was a **high movement/volatility regime** all day (avg mov 76.3, vol 75.3).
- In that environment, even cycles with mov 55–77 were profitable.
- The losses clustered in:
  1. **Overnight choppiness** (1am–4am): momentum whiplash/reversals.
  2. **8am**: low movement/volatility.
- A possible refinement: consider a **day-level filter** (e.g. avg movement/volatility above a threshold) in addition to entry-level movement_percentile, though that would need more testing.
