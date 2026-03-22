# Hypothetical entry pricing (`price_estimator`)

**Status:** active research / engineering.  
**Code:** `scripts/backtest/price_estimator.py`  
**Parent initiative:** [`BACKTESTING.md`](./BACKTESTING.md)

This document records **methodology** for estimating a **plausible executed buy price** from historical context (TTC, spot vs strike, model probability, and peer trades). The intent is to support **long-horizon hypothetical backtests** (e.g. replaying years of price logs against Kalshi strike schedules) where **true** order-book fills are unavailable. Accuracy in the **single-cent** sense is **not** expected; the bar is **useful, repeatable, and conservatively biased** where possible.

---

## 1. Goals and non-goals

| In scope | Out of scope (today) |
|----------|----------------------|
| Peer-based **prior** for `buy_price` given entry-time features | Full limit-order-book simulation |
| Same **TTC** convention as the core backtester (15m vs hourly by strategy) | Guaranteed fill at mid or best ask |
| **Live** vs **paper** trade pools for comparison and calibration | Real-time production pricing API |
| **Holdout** metrics to track drift as data grows | Legal/market “official” settlement price |

**Future (not implemented):** ingestion of Kalshi **archived market candlesticks** per contract ticker (see **§10**) to tighten hypothetical fills with exchange-recorded bid/ask/trade OHLC.

---

## 2. Data sources

All rows come from **`users.trades_0001`** (see `scripts/backtest/helpers/constants.py`).

**Required for strict peer models (3D + k-NN):**

- `buy_price` — observed price (live fill or paper-log price).
- `created_at` — entry timestamp (timezone-aware).
- `trade_strategy` — drives **15m vs hourly** TTC grid (same rule as `strategy_implies_15m_ttc_grid` in `trade_filters.py`).
- `symbol`, `contract` — **segment** label (e.g. `BTC hourly`, `ETH 15m`).
- `strike`, `symbol_open` — parsed to numeric **spot − strike** when possible.
- `prob` — model probability at entry (0–100 scale as stored).
- `side` — normalized to Y/N for side-stratified peers.

**Filters (defaults, match backtest conventions):**

- `buy_price IS NOT NULL`
- **`--paper`:** `live` (default), `paper`, or `all` — see CLI.
- Excludes `test_filter = TRUE` unless `--include-test-filter`.

**TTC timezone:** `--ttc-tz` (default `America/New_York`), aligned with open-to-boundary minutes in `hypothetical_trades.open_to_next_boundary_minutes`.

---

## 3. Feature definitions

### 3.1 Market segment

`infer_market_segment(symbol, trade_strategy, contract)`:

- **Cadence:** `15m` if strategy text contains `15m` / `15 m`; else **hourly**.
- **Weekly tag:** if `WBTC` in contract or `weekly` in strategy, append ` weekly`.

Segments keep **TTC** and **peer pools** **market-specific**.

### 3.2 TTC (minutes)

Minutes from `created_at` to the **next** bar boundary in `--ttc-tz`:

- **Hourly:** next top-of-hour.
- **15m:** next :00 / :15 / :30 / :45.

Same semantics as SQL TTC fragments in `trade_filters.open_to_next_boundary_ttc_sql` (implemented in Python for row enrichment).

### 3.3 Spot − strike

`spot_minus_strike = symbol_open_num − strike_num` when both parse as numbers (strip `$`, commas).

- **Positive:** live spot snapshot **above** the strike number in stored units.
- Used as a **directional distance** feature, not a guarantee of contract economics without market-type context.

---

## 4. Peer prediction methods (implemented)

All methods predict a **scalar** “expected” price as a **median** of peer `buy_price` values (unless noted). Training peers are always taken from a **training set** that **excludes** the holdout trade id when evaluating.

### 4.1 2D quantile bins (segment)

- Bin **TTC** and **spot − strike** each into **5** quantile buckets on the **training** peer set **in that segment**.
- Target cell: median `buy_price` of peers in the same **(TTC bin, distance bin)**.
- **Fallbacks** (in order): same TTC bin only; same distance bin only; median of entire segment peer set in training.
- **Parameter:** minimum peers per cell (`min_cell`, default 3).

### 4.2 3D quantile bins (segment + prob)

- Adds **`prob`** in **4** quantile bins → **5 × 5 × 4** cells within segment.
- If the 3D cell is sparse, **fall back** to **4.1** (2D segment bins).

This is the **default “best simple”** peer rule for **live** holdouts in early experiments: it materially improved error vs 2D-only when `prob` encodes synthesized state.

### 4.3 2D bins with side

Same as **4.1** but peers restricted to **same `side_norm` (Y/N)** within segment. Reduces pooling across YES/NO economics.

### 4.4 k-NN (segment + side)

- Peers: same segment and side.
- Features: **z-scored** TTC, spot−strike, prob using **training** pool moments.
- Prediction: **median** `buy_price` of the **k** nearest neighbors by Euclidean distance in z-space (default **k = 15**).

Strong when the segment mix is **heterogeneous** (notably **paper** logs with wide price dispersion).

---

## 5. Evaluation protocol (holdout)

**CLI:** `--peer-holdout N --peer-holdout-seed S` (optional `--peer-knn-k`).

**Eligibility:** rows with finite **TTC**, **spot − strike**, **prob**, and **buy_price**.

**Procedure:**

1. Sample **N** distinct eligible rows (seeded RNG).
2. **Training set** = all enriched rows in the window **except** those **N** ids (full columns; paper mode per run).
3. For each held-out row, compute predicted price under each method; compare to recorded `buy_price`.

**Reported metrics:** MAE, RMSE, mean absolute **percent** error vs actual, fraction within **0.01** and **0.02**, Pearson **r** between predicted and actual.

**Important:** metrics are **slice-specific** (time range, paper vs live, monitor filters). Re-run when expanding to **5y** replay or new strategies.

---

## 6. Empirical snapshot (for calibration memory)

**Window (example):** 2025-06-01 through 2026-03-22 (America/New_York-style offsets in CLI).  
**Holdout:** N = 100, seed = 42.

**Live pool (`--paper live`):** on the order of **~2.2k** strict rows; **3D segment** peer median achieved roughly **~0.019 MAE** on a 0–1 price scale vs **~0.024** for **2D segment-only**; **~37%** of trades within **0.01** vs **~16%** for 2D (see CLI table).

**Signed bias (3D segment, same holdout):** mean **(pred − actual)** was slightly **positive** (small **over**estimate of buy price on average), median **0**, with **over** vs **under** counts roughly balanced. For **backtest conservatism**, a slight **over**estimate of entry price is generally **safer** than systematic **under**pricing.

**Paper pool (`--paper paper`):** much **larger** row count and **wider** price dispersion. **Segment-only 2D/3D** can look **poor**; **side + k-NN** recovers structure. Do **not** assume paper peers proxy **live** execution without stratification.

**Dual-pool spot checks (`--spot-check-dual`):** comparing **live-trained** vs **paper-trained** peer medians on the **same** trade id shows that **live** peers often track **live** recorded prices **better** than **paper** peers on **live** rows (populations differ).

Treat this section as **historical calibration notes**; replace with fresh numbers when the analytics job re-runs.

---

## 7. Intended use in backtesting

1. **Hypothetical entries** on historical paths: once **instrument** (Kalshi series, strike tier, expiry) is fixed, use **enriched** features at the hypothetical clock time and apply **4.2** or **4.4** with a **training pool** built from **live** trades in a **rolling** or **expanding** window (policy TBD).
2. **Conservatism:** prefer methods or **post-adjustments** that do **not** systematically **under**state entry price; track **mean signed error** by segment/month.
3. **Sensitivity:** run **bands** (e.g. peer median vs median + fixed slippage) to bracket PnL.
4. **Drift:** as new trades arrive, re-run **`--peer-holdout`** (and optional dashboards) to detect **regime shift** or **bias creep**.

---

## 8. Analytics pipeline (future)

**Objective:** periodic job (e.g. weekly) that:

- Refreshes **holdout metrics** on rolling windows.
- Optionally exports **calibration tables** (median error by segment × prob decile).
- **Versions** the peer rule (bin counts, k, paper vs live training policy) in git or a small **config artifact** so backtests remain **reproducible**.

**Integration points:** same DB access as `scripts/backtest/helpers/db.py`; output JSON/CSV for `backend/util/analytics` or a cron wrapper. Implementation is **not** wired yet; this section is the **contract** for when it is.

---

## 9. CLI quick reference

```bash
# Pattern report (correlations + marginal + joint tables)
.venv/bin/python3 scripts/backtest/price_estimator.py \
  --start 2025-06-01T00:00:00-04:00 --end 2026-03-22T00:00:00-04:00

# Peer holdout comparison (four methods)
.venv/bin/python3 scripts/backtest/price_estimator.py ... \
  --peer-holdout 100 --peer-holdout-seed 42 --no-buckets

# Paper-only training pool
.venv/bin/python3 scripts/backtest/price_estimator.py ... --paper paper --peer-holdout 100 --no-buckets

# Live vs paper peer expected price for specific ids
.venv/bin/python3 scripts/backtest/price_estimator.py ... \
  --spot-check-dual 8459,6911 --spot-check-dual-only
```

**Other flags:** `--by-side`, `--joint-min-cell-n`, `--legacy-full-correlations`, `--fit`, `--holdout-eval` (legacy OLS), `--export`.

---

## 10. Kalshi market candlesticks (live vs historical)

Kalshi splits candlesticks across **two** paths. Using the wrong one returns **`failed_to_get_market_by_ticker: not_found`** even when `GET /markets/{ticker}` works.

### 10.1 Cutoff (which API to call)

**[Get Historical Cutoff Timestamps](https://docs.kalshi.com/api-reference/historical/get-historical-cutoff-timestamps)** — `GET /trade-api/v2/historical/cutoff` (no auth in spec).

- **`market_settled_ts`:** Markets that **settled before** this instant must use the **historical** candlestick route (and `GET /historical/markets`).
- Markets that settled **on or after** that cutoff still use the **live** candlestick route under **`/series/{series_ticker}/markets/...`**.

Example (as of one probe): `market_settled_ts` was **`2025-03-21T00:00:00Z`**. A **March 2026** BTC daily market is **after** that cutoff, so it is **not** in the historical archive path yet.

### 10.2 Live (recent) markets — correct path for most current trading

**[Get Market Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks)**:

```http
GET /trade-api/v2/series/{series_ticker}/markets/{ticker}/candlesticks
    ?start_ts=...&end_ts=...&period_interval=1|60|1440
```

- **`series_ticker`:** series prefix for the contract (e.g. `KXBTCD` for `KXBTCD-26MAR2117-T70399.99`).
- **`ticker`:** full market ticker (including strike suffix such as `-T70399.99`).
- Response candles use **`yes_bid` / `yes_ask`** objects with **`open_dollars`**, **`high_dollars`**, **`low_dollars`**, **`close_dollars`**, plus **`price`** (trades) with the same `*_dollars` fields, **`volume_fp`**, **`open_interest_fp`**, **`end_period_ts`**.

### 10.3 Historical (archived) markets

**[Get Historical Market Candlesticks](https://docs.kalshi.com/api-reference/historical/get-historical-market-candlesticks)**:

```http
GET /trade-api/v2/historical/markets/{ticker}/candlesticks
    ?start_ts=...&end_ts=...&period_interval=1|60|1440
```

Use this only for markets that settled **before** `market_settled_ts`. Schema is similar; field names in OpenAPI may differ slightly from the live response (e.g. nested `FixedPointDollars`).

**Further reading:** [Historical Data](https://kalshi.com/docs/getting_started/historical_data) (Kalshi getting started).

### 10.4 Unknowns to validate before a build

- **Auth and limits:** Live market data is often public; confirm for your tier and bulk backfill rate limits.
- **Alignment:** map **`trades.ticker`** + **series** to the path; timezone alignment with `created_at` and **TTC**.

**Suggested phased experiment**

1. **Spike:** for each ticker, call **`/historical/cutoff`** and use **live** (`/series/.../candlesticks`) vs **historical** (`/historical/markets/...`) as in §10.1–10.3. Pull a **handful** of tickers from `trades_0001`, windows around **known** live entries; compare **yes_ask close** (or **price** close / mean) at entry time to **`buy_price`** and **peer-model** predictions. Document bias and variance.
2. **Ingestion sketch:** append-only store keyed by `(ticker, end_period_ts, period_interval)` with raw JSON or normalized columns (bid/ask/trade OHLC, volume, OI). Idempotent upserts for replays.
3. **Cycle coverage:** for each **contract cycle** you care about in backtests, derive **ticker** and fetch the **full** bar set from listing to settlement (or API max), at **1m** first (finest grain), optionally **60m** for long runs to save space.
4. **Fusion model (later):** join stored candles at **decision time** with our **symbol** path, **strike**, **TTC**, and **delta / prob** features. Use as **features** (spread, mid, momentum of ask, volume) or as a **direct fill prior** (e.g. conservative buy = yes_ask close or ask high). Keep **peer median** as a **fallback** when candlesticks are missing.

**Why it fits the roadmap:** peer pricing answers “what did **we** pay in similar states.” Candlesticks answer “what did the **exchange** show for **this** contract over time.” Together they support **hypothetical** entries that are **grounded in Kalshi’s own archive**, which is the right direction for **5y**-style replay once ingestion is proven.

### 10.5 On-demand DB load (scratch)

To materialize **1m** bars for a market’s Kalshi window into **`historical_data`** with **`timestamp`** aligned to **`historical_data.*_price_history`**, use **`scripts/backtest/helpers/kalshi_market_candles_scratch.py`** (see **`docs/BACKTESTING.md`** §5.4). Supports **live-then-historical** fetch logic from §10.1–10.3 and **dated table rotation** via cleanup. Works for **any** contract length Kalshi exposes on **`open_time`..`close_time`** (e.g. **~15 rows** for **15m** markets such as **`KXBTC15M-...`**, **~60** for typical **hourly** **`KXBTCD-...`**).

---

## 11. Revision history

| Date | Note |
|------|------|
| 2026-03-21 | Initial methodology doc: features, peer methods, holdout protocol, live/paper notes, pipeline placeholder. |
| 2026-03-21 | §10: planned Kalshi historical candlesticks experiment (API link, phases, fusion with symbol data). |
| 2026-03-21 | §10: corrected live vs historical paths; `/series/{series}/markets/{ticker}/candlesticks` + cutoff doc. |
| 2026-03-22 | §10.5: scratch loader + 15m vs hourly row counts (`KXBTC15M` vs `KXBTCD`); BACKTESTING §5.4. |
