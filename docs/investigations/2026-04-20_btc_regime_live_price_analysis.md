# BTC regime analysis from `live_price_log_1s_btc`

**Initiative:** Deep-dive recent BTC 1s tick behavior on production to relate price-path and stored derived features (`momentum_*`, `volatility_*`, `movement_*`) to a period when probability modeling reportedly failed badly (~late March 2026) and a subsequent recovery (~early April 2026). Goal: surface patterns that might become **early-warning signals** for medium-term regime shifts.

**Primary data:** `live_data.live_price_log_1s_btc` (prod), analyzed 2026-04-20. Population and column semantics: `docs/MASTER_DB_SCHEMA_REFERENCE.md` (table `live_data.live_price_log_1s_btc`); derived fields written by `backend/symbol_price_watchdog.py`.

---

## 1. Executive summary

- **Aggregate realized 1s volatility** (log returns, with gap-aware cleaning) was **not higher** in the stressed calendar band (3/29–4/7) than in the prior available window or after ~4/7. Average **`movement_percentile`** was **lower** in that band than in 3/15–3/29, not higher.
- Stress appears more clearly as **short hourly bursts** where **σ(1s)**, **`volatility_percentile`**, and **`movement_percentile`** spike **together** (e.g. 3/29 evening ET, 4/5 evening, 4/7 evening).
- **Correlation between `momentum_percentile` and `volatility_percentile`** is **unstable** day to day; several days show **material negative** daily correlation (e.g. 3/27, 4/01), which may invalidate models that assume a stable joint distribution of those inputs.
- **Data integrity:** the table on prod **starts 2026-03-15 13:22 ET**; there is **no** 1s history before that here. There is also a **~30 hour tick gap** from roughly **3/25 midday ET through 3/26 ~18:00 ET**. Any regime statistic that does not account for gaps can be wrong; boundary `LAG(price)` effects can inflate σ.
- **Date narrative:** recovery described as “~3/7” aligns better with **2026-04-07** than March 7 given the incident anchor ~3/29.

---

## 2. Data coverage and constraints

| Item | Detail |
|------|--------|
| **Row range (prod snapshot)** | `min(timestamp)` ≈ `2026-03-15T13:22:00` through latest (~`2026-04-20`) |
| **Requested windows** | User asked for 3/6–3/22 and 3/6–3/20; **only 3/15+** exists in this table |
| **Null rates** (Mar 15–Apr 20) | ~0.02% null `momentum_percentile`; ~0.14% null `volatility_percentile`; ~0.02% null `movement_percentile`; price null ~0% |
| **Tick gaps** | Many intervals &gt;5s; p99 gap ~3s among “normal” pairs; **very large** max gap includes table start and the **3/25–3/26** outage |
| **Major outage** | After ~**2026-03-25 12:00 ET**, ticks resume ~**2026-03-26 18:00 ET** (~30 hours missing) |

---

## 3. Methodology (analysis)

- **Eastern calendar:** `timestamp::timestamp AT TIME ZONE 'America/New_York'` for daily/hourly buckets.
- **1s log returns:** `ln(price / prev_price)` ordered by timestamp.
- **Gap cleaning:** For block σ and mean |return|, exclude pairs where `ts - prev_ts &gt; 3 seconds` so post-outage jumps do not dominate aggregates.
- **Daily metrics:** tick count, day range %, σ(1s), mean |return|, fraction of up-ticks, means/std of percentiles, `CORR(momentum_percentile, volatility_percentile)` (and vs movement), tail fractions (e.g. `mov_pct ≥ 90`), count of large jumps.
- **Hourly metrics:** same σ and avg percentiles for fine-grained burst detection (focus window 3/28–4/08 in the original run).

---

## 4. Regime blocks (gap-cleaned 1s returns)

Approximate production computation (Mar 15–Apr 20 window):

| Block (ET) | Ticks | σ 1s log ret (clean) | Avg `vol_pct` | Avg `mov_pct` | corr(`mom_pct`,`vol_pct`) | frac `mov_pct` ≥ 90 |
|------------|------:|---------------------:|--------------:|--------------:|----------------------------:|---------------------:|
| **pre-3/29** (3/15–3/29) | 971,794 | 0.0000835 | 46.2 | 76.7 | −0.008 | 0.320 |
| **3/29–4/07** | 658,933 | 0.0000717 | 38.9 | 69.1 | +0.004 | 0.239 |
| **4/07 onward** (through ~4/20) | 1,055,175 | 0.0000709 | 40.7 | 72.0 | +0.023 | 0.243 |

**Interpretation:** The “failure” window is **not** characterized by higher average 1s σ or higher average `movement_percentile` in this table. Differences are **subtle**: slightly **restored positive** correlation between `momentum_percentile` and `volatility_percentile` after ~4/7 vs the mid-window.

Subset aligned with user’s overlapping “early March” intent (only data available):

| Block | Ticks | σ clean | Notes |
|-------|------:|--------:|-------|
| 3/15–3/23 | 600,258 | 0.0000817 | “~3/6–3/22” overlap |
| 3/15–3/21 | 438,918 | 0.0000868 | “~3/6–3/20” overlap |

---

## 5. Notable daily patterns (selected)

- **`corr(mom_pct, vol_pct)` negative:** e.g. **2026-03-27** ≈ −0.17, **2026-04-01** ≈ −0.14 — unusual vs typical days nearer zero or mild positive.
- **Quiet weekend / holiday-like days:** **2026-04-04** — very low σ, low avg `vol_pct` / `mov_pct`; **2026-04-03** tails off similarly. Session mix matters for any detector.
- **High-range days:** **2026-04-07** large intraday range and strong evening spike in derived percentiles and σ (see hourly bursts below).

---

## 6. Hourly “joint stress” examples

Bursts where **realized σ(1s)** and **avg `vol_pct` / `mov_pct`** are extreme **simultaneously** (examples from original hourly rollup):

- **2026-03-29 ~18:00–22:00 ET:** σ(1s) on the order of **1.5×10⁻⁴**; hourly avg `vol_pct` **~72–80+**; `mov_pct` **~94–96**.
- **2026-04-05 ~18:00–20:00 ET:** similar co-movement.
- **2026-04-07 ~18:00 ET:** σ(1s) **~1.85×10⁻⁴**; `vol_pct` **~83**; `mov_pct` **~97**.

**Hypothesis for a signal:** rolling **1–3 hour** fraction of ticks (or hours) satisfying joint thresholds, e.g. `vol_pct &gt; 80` **and** `mov_pct &gt; 90` **and** σ above a rolling quantile — tuned on historical bad P&amp;L days.

---

## 7. Hypothesis-level forward signals (nothing deployed)

1. **Joint extreme score:** short-window frequency of joint high `vol_pct`, high `mov_pct`, and high clean σ.
2. **Rolling corr(`mom_pct`,`vol_pct`):** multi-day negative runs or breach below a negative threshold (e.g. &lt; −0.1 on daily aggregates).
3. **Slow coupling:** rising 5–10d average corr(`mom_pct`,`vol_pct`) as “back to normal” indicator (post-4/7 block showed higher positive corr than mid-window).
4. **Session stratification:** compute detectors **within** session / DOW to avoid weekend quiet false positives.
5. **Feed gate:** if max tick gap &gt; **N minutes**, flag **model-degraded** or require cooldown before full probability trust (complements price-only regime logic).

---

## 8. Open items / next steps

- [ ] **Extend history:** join or backfill pre-3/15 BTC series (e.g. `historical_data` or vendor) for baseline “months of stability” before March.
- [ ] **Patch the 3/25–3/26 gap** in analytics (or mark “no-trade / reduced confidence” for downstream consumers).
- [ ] **Align with outcomes:** time-align these features with **per-strategy P&amp;L / trade logs** to validate which features precede losses (hours/days lead).
- [ ] **Operationalize:** optional materialized daily/hourly stats table or scheduled script (repo location TBD) with: clean σ, percentile moments, corr(mom, vol), joint-extreme counts, max gap.
- [ ] **Re-run** this analysis after more calendar time to refresh block statistics.

---

## 9. References

- `docs/MASTER_DB_SCHEMA_REFERENCE.md` — `live_data.live_price_log_1s_btc`
- `backend/symbol_price_watchdog.py` — writes `move_*`, `movement`, `movement_percentile`, volatility/momentum percentiles
- `docs/PRODUCTION_HOST.md` — prod DB/SSH host resolution
- Related: `docs/investigations/2026-04-02_aes_probability_price_feed_notes.md` (AES / price feed)

---

*Document started: 2026-04-20. Findings reflect prod queries run that day; re-run for updated row ranges.*
