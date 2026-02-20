# Monitor 10002 — BTC Hourly HTC: Exploratory Data Mining (W/L)

## Scope

- **Monitor:** mon_0001_10002  
- **Strategy:** BTC Hourly HTC  
- **Unit:** Trade-level only (each trade stands alone; no cycle logic).  
- **Window:** From 2025-10-01.  
- **Focus:** Win/loss rate only; metrics and intersections that have a notable impact on trade-level W/L.

**Baseline (Oct 2025+):** 1,096 trades, **95.0%** win rate.

---

## 1. Single-metric bands (trade-level W/L)

### Movement percentile (25-point bands)

| Band   | Trades | Win %  |
|--------|--------|--------|
| 0-25   | 65     | 96.9   |
| 25-50  | 316    | 96.5   |
| 50-75  | 463    | 94.6   |
| 75-100 | 252    | 93.3   |

Movement alone: modest gradient (high movement slightly lower win rate). No large drop.

### |Momentum| percentile (25-point bands)

| Band   | Trades | Win %  |
|--------|--------|--------|
| 0-25   | 488    | 95.7   |
| 25-50  | 330    | 95.2   |
| 50-75  | 218    | 95.0   |
| 75-100 | 58     | **87.9** |

**Notable:** **|Momentum| 75-100** has **87.9%** win rate vs 95%+ for lower bands. High absolute momentum is associated with a clear drop in W/L.

### Volatility percentile (25-point bands)

| Band   | Trades | Win %  |
|--------|--------|--------|
| 0-25   | 68     | 98.5   |
| 25-50  | 343    | 95.6   |
| 50-75  | 460    | 95.0   |
| 75-100 | 225    | 92.9   |

High volatility (75-100) is the lowest band (92.9%); gradient is modest.

---

## 2. Time-of-day (trade time, hour)

| Hour (EST) | Trades | Win %  |
|------------|--------|--------|
| 9         | 108    | **88.0** |
| 12         | 61     | **85.2** |
| 13         | 70     | 90.0   |
| 19         | 78     | 91.0   |
| 16         | 36     | 91.7   |
| … others   | …      | 96–100% |

**Notable:** **9am and 12pm** are the worst hours: **88.0%** and **85.2%** vs 96%+ for most other hours.  
**Combined “9am or 12pm”:** 169 trades, **87.0%** win rate vs **96.4%** for all other hours (~9.4 point drop).

---

## 3. Day of week

| DOW | Trades | Win %  |
|-----|--------|--------|
| Sun (0) | 99  | 94.9   |
| Mon (1) | 262 | 95.8   |
| Tue (2) | 234 | 92.7   |
| Wed (3) | 215 | 95.3   |
| Thu (4) | 142 | 93.0   |
| Fri (5) | 101 | 98.0   |
| Sat (6) | 43  | 100.0  |

Tuesday and Thursday are a bit lower (92.7%, 93.0%); sample sizes are decent. Effect is smaller than hour or |momentum|.

---

## 4. Intersections (notable impact on W/L)

### |Momentum| high vs low × Volatility high vs low

| |Mom|>=70 | Vol>=70 | Trades | Win %  |
|--------|--------|--------|--------|
| No     | No     | 754    | **96.3** |
| No     | Yes    | 249    | 92.4   |
| Yes    | No     | 33     | 90.9   |
| Yes    | Yes    | 58     | 91.4   |

**Notable:** When **|momentum| ≥ 70**, win rate is **90.9–91.4%** regardless of volatility, vs **92.4–96.3%** when |momentum| < 70. So **high |momentum|** is the main driver of lower W/L in this cut.

### Movement × Volatility (low/med/high)

- **Med movement + high vol:** 81.8% (33 trades) — lowest cell.  
- **High movement + med vol:** 86.3% (51 trades).  
- **Low/low:** 96.6% (321 trades).

So **high volatility**, especially with **med or high movement**, is associated with lower win rate.

### |Momentum| × Movement (low/med/high)

- **High |mom| + med movement:** **80.0%** (20 trades) — lowest.  
- **High |mom| + high movement:** 91.7% (36 trades).  
- **Low/low:** 96.2% (340 trades).

**High |momentum|** again shows up as the main factor; combined with med movement it has the lowest win rate.

---

## 5. Summary: metrics and intersections with notable impact

1. **|Momentum| ≥ 75 (or ≥ 70):** Strong drop in win rate (~88–91% vs 95%+). Single best predictor in this pass.  
2. **Hour 9am or 12pm:** 87% win rate vs 96.4% other hours; ~9 point drop.  
3. **High volatility (75+):** Modest drop (92.9% vs 95%+).  
4. **High vol + med/high movement:** Some cells in the 82–86% range (smaller n).  
5. **High |momentum| + med movement:** 80% (20 trades) — lowest cell.  
6. **Movement alone:** Gradient is mild (93–97%); less discriminative than |momentum| or hour.

All results above are **trade-level** only; no cycle-level data or logic.
