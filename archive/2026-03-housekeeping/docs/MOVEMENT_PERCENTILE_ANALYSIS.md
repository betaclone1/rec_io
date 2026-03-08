# Movement Percentile Analysis — Monitor 10020 (Momentum Breakout)

## Scope

- **Monitor:** mon_0001_10020  
- **Strategy:** BTC Momentum Breakout  
- **Unit of analysis: individual trades only** (no cycle aggregation).  
- **Trades analyzed:** 872 (each row = one trade; W/L from `win_loss`).  
- **Entry metrics:** Per trade — `momentum_percentile`, `movement_percentile` at entry.

**Trades with |momentum_percentile| ≥ 70:** **427** (136 W, 291 L → 31.9% win rate).

---

## 1. Movement Percentile vs Trade W/L

| Movement % | Trades | Wins | Losses | Win % |
|------------|--------|------|--------|-------|
| 0-20       | 12     | 4    | 8      | 33.3  |
| 20-40      | 32     | 7    | 25     | 21.9  |
| 40-60      | 97     | 21   | 76     | 21.6  |
| 60-80      | 278    | 69   | 209    | 24.8  |
| 80-100     | 453    | 156  | 297    | **34.4** |

**Finding:** Higher movement percentile correlates with better trade win rate. Movement 80+ has 34.4% win rate (156 W, 297 L).

---

## 2. Momentum + Movement Percentile Overlap (trades)

| Momentum | Movement 0-50 | Movement 50-70 | Movement 70+ |
|----------|---------------|----------------|--------------|
| mom 0-50   | 20.4% (54)  | 28.7% (87)    | 27.1% (155)  |
| mom 50-70  | 27.8% (18)  | 23.4% (47)    | 32.1% (84)   |
| mom 70-90  | 50.0% (2)   | 16.4% (55)    | **37.7% (167)** |
| mom 90+    | 0% (3)      | 16.7% (6)     | 32.0% (194)  |

*(Numbers in parentheses = trades)*

**Findings:**
- **Mom 70-90 + movement 70+:** 37.7% win rate (63 W, 104 L) — best-performing cell.
- **Mom 90+ + movement 70+:** 32.0% win rate.
- **Mom 90+ with movement &lt; 70:** 0–16.7% win rate (9 trades) — avoid high momentum with low movement.

---

## 3. Sweet Spot

**|momentum| 70-90 + movement 70+**  
- 167 trades  
- 63 wins, 104 losses  
- **37.7% win rate**

---

## 4. Baseline

**All trades:**  
- 872 trades  
- 257 wins, 615 losses  
- **29.5% win rate**

**Trades with |momentum_percentile| ≥ 70:** 427 trades (136 W, 291 L → 31.9% win rate).

---

## 5. Practical Takeaway

- **Movement 80+:** 453 trades, 34.4% win rate (156 W, 297 L).
- **Mom 70-90 + movement 70+:** 37.7% win rate (167 trades) — strongest overlap.
- **Avoid:** Mom 90+ with movement &lt; 70.

---

## 6. Backtest: PnL vs abs(momentum_percentile) (Monitor 10002, date ≥ 2025-10-01)

| Backtest | abs(mom) discount | Trades | Total PnL |
|----------|-------------------|--------|-----------|
| Baseline | —                 | 1096   | $11.89    |
| Discount | ≥ 50              | 820    | -$923.55  |
| Discount | ≥ 60              | 916    | -$558.54  |
| Discount | ≥ 70              | 1005   | -$245.98  |
| Discount | ≥ 80              | 1058   | -$93.29   |
| Discount | ≥ 90              | 1086   | -$12.77   |

---

## 7. Hybrid Backtest (Breakout + Momentum Contain)

*(Breakout vs contain applied per trade; position 100 vs 50. Re-run for exact trade counts and PnL at trade level.)*

---

## 8. Operational Notes

- **Previous-day rule:** Skip today when (yesterday avg movement_percentile ≥ 70) **and** (yesterday avg volatility_percentile ≥ 70). Use one-per-minute sampling from live tick log for daily averages.
- **2/17/26 example:** Prev day avg vol 48.82, mov 79.74 → do not skip (vol &lt; 70). Breakout live.
- **2/18/26:** Count how many **trades** met movement &gt; 80 vs not (e.g. BTC 8am trade had mov 75.4).

---

## See also

- **Previous-day metrics and 1s rollup:** `docs/PREVIOUS_DAY_METRICS_REFERENCE.md` (day filter, tick vs 1m, one-per-minute sampling, proposed `current_symbol_data` table).
- **Monitor 10002 (BTC Hourly HTC) movement/vol/mom vs W/L:** `docs/MONITOR_10002_HTC_MOVEMENT_ANALYSIS.md` (exploratory W/L only; opposite pattern to Breakout — lower movement better for HTC).
