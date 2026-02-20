# Previous Day Metrics — Reference and Implementation Notes

## Purpose

Maintain a record of **previous day’s average metrics** (momentum, volatility, movement **percentiles**) per symbol for use in:

- **Day filter:** Skip today when (prev day avg movement ≥ 70) AND (prev day avg volatility ≥ 70).
- **Breakout vs Contain:** Breakout when criteria met (day not skipped + movement > 80 at entry); else Momentum Contain (flip side, half size).

---

## Data Sources

Two possible sources for “previous day” averages:

| Source | Table(s) | Granularity | Columns (percentiles) |
|--------|----------|-------------|------------------------|
| **Historical 1m** | `historical_data.btc_price_history` (and eth, etc.) | 1 minute | `momentum_percentile`, `volatility_percentile`, `movement_percentile` |
| **Live tick** | `live_data.live_price_log_1s_btc` (and eth, etc.) | **Tick-by-tick** (not strict 1s) | `momentum_percentile`, `volatility_percentile`, `movement_percentile` |

**Important:** The “1s” tables are **tick-by-tick**: rows are written on each price update, so you can have many ticks per second when busy and gaps when quiet. A simple `AVG(percentile)` over all rows is **tick-weighted**, not time-weighted—busy periods dominate the average and the result is not comparable to the 1m bar average (one row per minute, equal weight per minute).

**Day window:** Full calendar day 00:00:00–23:59:59 (all rows where `timestamp::date` = that date).

**Computation from 1m:** `AVG(momentum_percentile)`, `AVG(volatility_percentile)`, `AVG(movement_percentile)` over that day (one value per minute, equal weight).

**Computation from tick data (to match 1m-style):** To replicate 1m-style daily averages from tick data, **sample one tick per minute** (e.g. the last tick in each minute with `date_trunc('minute', timestamp)`), then take `AVG(percentile)` over those ~1440 values. That gives equal weight per minute and is comparable to the historical 1m daily average. Do **not** use a raw average over all ticks.

---

## Example: 2026-02-11

### From historical_data (1m bars)

| Metric | Value |
|--------|--------|
| Rows | 1,440 (24×60) |
| Avg momentum_percentile | -1.40 |
| Avg \|momentum_percentile\| | 63.66 |
| Avg volatility_percentile | 75.27 |
| Avg movement_percentile | 76.27 |

### From live_data (1s ticks)

| Metric | Value |
|--------|--------|
| Rows | 77,955 |
| Avg momentum_percentile | -0.76 |
| Avg \|momentum_percentile\| | 64.85 |
| Avg volatility_percentile | 68.48 |
| Avg movement_percentile | *(all NULL for this day in live table)* |

**Note:** On 2/11/26, `live_price_log_1s_btc` had no non-NULL `movement_percentile` (column may be unpopulated or backfilled only for later dates). Use historical 1m for movement when live is missing.

---

## Backtest Summary (for memory)

- **Position 100, no filters:** 428 cycles, -$1,358.
- **Position 100, movement > 80 only:** 217 cycles, -$9.
- **Position 100, movement > 80 + skip day when prev mov≥70 and prev vol≥70:** 119 cycles, +$636.
- **Hybrid (Breakout pos 100 + Contain flip-side pos 50 on discounted cycles):** 119 Breakout (+$636) + 309 Contain (+$997) = **+$1,633 total.**

Prev-day rule uses **percentile** averages from the **full previous calendar day** (00:00–23:59).

---

## Using 1s logs instead of 1m (recommended for daily table)

**Context:** Historical 1m price logs are updated only every few weeks (big analytics pipeline). To always have “previous day” metrics available, we can compute them from **live 1s logs**, which are updated continuously.

### Can tick data replicate 1m results?

- **You must sample one tick per minute** when computing daily averages from the tick table (e.g. last tick in each minute). A raw average over all ticks is tick-weighted and not comparable to 1m (see above).
- **Volatility and momentum:** With one-per-minute sampling from ticks, daily averages are close to 1m. Volatility from ticks often runs a few points lower than 1m; momentum is very close. Day-to-day ordering is the same, so the “skip when prev mov≥70 and prev vol≥70” rule can be driven from this.
- **Movement:** Live `movement_percentile` was only populated from ~2/16 onward in the sample. Once the live pipeline (or backfill) fills it for all ticks, use the same one-per-minute sampling and `AVG(movement_percentile)`. Until then, the daily table can store `avg_movement_percentile` when present, and leave NULL or backfill from 1m when available.

### Threshold note when using 1s

If we use 1s for the day-skip rule, 1s vol runs ~5–7 points lower than 1m. Options: keep threshold at 70 (slightly stricter), or use ~65 on 1s to approximate “70 on 1m.” Recommend keeping 70 unless backtest suggests otherwise.

---

## Proposed: daily metrics table + update from 1s

### Table: `analytics.symbol_previous_day_metrics` (or `system.symbol_daily_metrics`)

Stores one row per symbol per calendar day with that day’s average percentiles (computed from 1s logs so it can be updated every night without the big 1m pipeline).

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | TEXT | e.g. btc, eth |
| `date` | DATE | Calendar day (00:00–23:59) |
| `avg_momentum_percentile` | NUMERIC(5,2) | AVG(momentum_percentile) over that day from 1s log |
| `avg_volatility_percentile` | NUMERIC(5,2) | AVG(volatility_percentile) over that day from 1s log |
| `avg_movement_percentile` | NUMERIC(5,2) | AVG(movement_percentile) over that day from 1s log (NULL if not in 1s) |
| `source` | TEXT | 'live_1s' |
| `row_count` | INT | Number of 1s rows used (for sanity checks) |
| `updated_at` | TIMESTAMPTZ | When the row was computed/updated |
| PRIMARY KEY | (symbol, date) | |

### Update job (concept)

- **When:** Once per day (e.g. 00:05 or 00:10) or after midnight.
- **For each** symbol in `live_data.live_price_log_1s_{symbol}`:
  - Set `yesterday = today - 1 day`.
  - From the tick table for yesterday, **sample one tick per minute** (e.g. `ROW_NUMBER() OVER (PARTITION BY date_trunc('minute', timestamp) ORDER BY timestamp DESC)` and keep `rn = 1`), then over that set compute:
    - `AVG(momentum_percentile)`, `AVG(volatility_percentile)`, `AVG(movement_percentile)` (and optionally `AVG(ABS(momentum_percentile))`).
  - Store the **number of minutes** that had at least one tick (not total tick count) in `row_count`.
  - UPSERT into `analytics.symbol_previous_day_metrics` for `(symbol, yesterday)` with these values, `source = 'live_1s'`, `updated_at = now()`.

Using **one tick per minute** keeps the daily average comparable to the historical 1m pipeline (equal weight per minute). Then the trading logic reads “previous day” from this table (one query per symbol) instead of scanning the 1m or tick tables.
