# Auto-trade backtesting initiative

**Status:** major initiative (active development).  
**Goal:** reproduce and stress-test **everything `auto_entry_supervisor` uses to decide entries**, against **historical trades** and **hypothetical economics**, so operators can find better `monitor_list` / UI auto-trade settings before (or instead of) live trial-and-error.

---

## 1. Vision

### 1.1 Near term (interactive lab)

- Choose **monitors**, **time ranges**, and **dial-in settings** (TTC window, probability, momentum thresholds, position sizing, paper vs live flags, etc.).
- Run analyses **offline** (CLI today; **web UI tab** next — placeholder: `frontend/tabs/backtester.html`, nav in `frontend/index.html`).
- Present results in **clear, comparable tables and charts** (totals, distributions, optimal bands, sensitivity sweeps).

### 1.2 Longer term (optional autonomy)

- **Periodic optimization jobs** that propose or apply **per-monitor** auto-trade setting updates.
- Always constrained by **owner-defined guardrails** (e.g. min/max bounds per field, max delta per week, dry-run vs apply, approval queue).
- This document does **not** prescribe architecture for that layer; the **backtester core** should stay **deterministic, auditable, and side-effect free** unless explicitly run in an “apply” mode with human or policy gate.

---

## 2. Relationship to the live stack

| Layer | Role |
|--------|------|
| **`users.monitor_list_<user>`** | Source of truth for **auto-trade parameters** (prob, TTC window, momentum, asks, cooldowns, spike alert fields, etc.). |
| **`backend/auto_entry_supervisor.py`** | Loads settings via **`get_auto_entry_settings()`**, reads **current TTC** via **`get_current_ttc()`**, and gates scanning/entry with **`min_time <= current_ttc <= max_time`** and strategy-specific logic. |
| **Desktop / mobile UI** | Edits the same fields (e.g. `min_time` / `max_time` as **seconds** in trade monitor / dashboard flows). |
| **`scripts/backtest/`** | Offline engine: query **`trades`**, join **`monitor_list`** for strategy context, apply **filters and hypothetical recomputations** in Python/SQL. |

**Parity principle:** any field that **materially affects** “would we have been allowed to enter / what would PnL look like” in `auto_entry_supervisor` is **in scope** for the backtester (see §4).

### 2.1 Auto Entry Supervisor (AES) changes → backtest scripts

**`backend/auto_entry_supervisor.py` is live trading code.** Backtests are intentionally **standalone** (they do not import the supervisor), so entry logic can diverge unless someone updates the offline side.

**When you change AES** — entry gates, strategy branches, `get_auto_entry_settings()` fields used in gates, TTC handling, cooldown / spike interactions, or scan order — **update any backtest code that is meant to mirror that behavior.** Examples today:

| Live reference | Offline mirror (update when Hourly HTC gates change) |
|----------------|--------------------------------------------------------|
| `check_auto_entry_conditions_hourly_htc` strike loop | `backend/util/auto_entry_htc_gates.py` |
| Ordered strike scan + 15m TTC helpers for replay | `scripts/backtest/helpers/htc_aes_replay.py` |

Other strategies (momentum scalp, reverse HTC, breakout, simulated 15m paths, etc.) will gain their own helpers over time; the same rule applies: **AES change → reflect it in `scripts/backtest/` (and any `backend/util/*` backtest-only mirrors)** in the same PR or immediately after, and note it in the revision history below when behavior shifts.

Until there are automated parity tests, treat this as a **manual dual maintenance** obligation for operators changing production auto-entry.

### 2.2 Two Hourly-HTC-shaped entry paths (do not confuse them)

| Live function | When it runs | Gates beyond TTC + probability band |
|---------------|----------------|-------------------------------------|
| **`check_auto_entry_conditions_hourly_htc`** | Default strategy; **15m** monitors use this with **full** gates | min/max differential, min volume, max ask (and spike-adjusted min probability) |
| **`check_simulated_15m_entry_hourly_htc`** | **`market == "hourly"`** on the monitor, auto-trade on, strategy not Breakout/Contain | **None** — only `min_probability`/`max_probability` and TTC from `ttc_15m` on the hourly strike table |

Trades on **KXBTC15M-…** tickers can still be recorded from the **simulated 15m** path if the monitor’s market is **hourly**. Replaying those with **full** Hourly HTC gates in `backtest_market_simulator.py` will **miss** entries that only passed the looser simulated path. Use **`--htc-gate-mode simulated-15m`** when reconciling that subset. For **15m** monitors, **`full`** is the correct match to production.

Other gaps (inherent, not bugs): **1m candle** close prices/volume vs **live** strike-table snapshots; scan cadence (continuous vs once per minute).

**Ticker → contract interval (``backtest_market_simulator``):** tickers containing ``15M`` (e.g. ``KXBTC15M-...``) are treated as **15m** (``ttc_15m`` + 15m-style probability); otherwise **hourly** (``ttc_hourly`` + hourly probability), e.g. ``KXBTCD-...``. Override with ``--market 15m`` / ``--market hourly`` if needed.

### 2.3 Cycle packages: backtests **and** live-workflow diagnostics

Sealed cycle packages (`backend/util/cycle_replay/`, `scripts/backtest/cycle_replay_parity.py`) are valuable beyond hypothetical PnL. A package is a ground-truth recording of what the market/ladder looked like second-by-second; comparing **theoretical first gate-pass** to **live `trades_*` entry/exit times** is a primary way to catch live pipeline problems.

**When replay shows an entry (or earlier entry) that live missed or took late:**

1. **Investigate** — feed lag (e.g. CFB/spot), strike-ladder freshness, AES unified-pool cadence, silent gate skips, cooldowns, monitor inactive windows, IOC/fill path — not “replay clock wrong” by default.
2. **Note** the finding (trade id, ticker, Δ entry/exit seconds, root cause class).
3. **Decide:**
   - **Remediate live** if the gap is a fixable defect (stale ladder, missed wake, feed reconnect, scan starvation, missing skip telemetry, etc.).
   - **Accept as pipeline reality** if the delay is inherent rec → API → back latency that we will not close further.
4. Only after (3): if we accept the reality, **optionally** add **explicit simulated lag** (or entry-time lock) into replay so strategy economics reflect what live can actually achieve — never as a silent fudge that hides a live bug.

Entry/exit timestamps in parity output are first-class. Large `|entry Δ|` is a diagnostic signal; price Δ is often its consequence. Do not pad replay latency until the live miss has been classified.

**Worked example (2026-07-28, trade 31309 / 15m HTC):** package first flicker at 10:20:36 during/after CFB BRTI lag+reconnect; continuous gate window from ~10:20:56; live AES trigger 10:21:08. Classified as feed/ladder freshness (+ secondary unified-AES cadence), not “ignore the flag.”

---

## 3. Time-to-contract (TTC) — units (critical)

| Context | Unit | Notes |
|---------|------|--------|
| **Strike / supervisor** | **`get_current_ttc()` returns integer seconds** | From `live_data.*` strike row `ttc_15m` / `ttc_hourly`, or second-based fallback. |
| **`monitor_list.min_time`, `max_time`** | **Seconds** | Compared directly to `get_current_ttc()`. |
| **Backtest CLI (`core_backtester.py`)** | **Minutes** (floats allowed in sweeps) | Open TTC = minutes from **`trades.created_at`** to **next bar boundary** (15m vs hourly from monitor strategy), aligned with SQL helpers in `scripts/backtest/helpers/trade_filters.py`. |

**Conversion when applying backtest results to DB/UI:**

```text
monitor_list.min_time_seconds = round(MIN_TTC_minutes_from_backtest × 60)
monitor_list.max_time_seconds = round(MAX_TTC_minutes_from_backtest × 60)
```

Always re-check on a **sample monitor** that strategy and market (15m vs hourly) match.

**Naming in optimization output (CLI):**

- **`MIN_TTC≥`** — late-entry **floor** (drop trades with **too little** time left to boundary).
- **`MAX_TTC≤`** — early-entry **cap** (drop trades with **too much** time left).

Band: **`MIN_TTC≤ open_TTC ≤ MAX_TTC`** in minutes in the backtester; same shape as **`min_time <= ttc_seconds <= max_time`** live after scaling.

---

## 4. Scope: supervisor settings → backtester coverage

Loaded in **`get_auto_entry_settings()`** (representative query on `users.monitor_list_*`):

| Setting key | Typical use in supervisor | Backtester today | Notes |
|-------------|---------------------------|------------------|--------|
| `min_time`, `max_time` | TTC window | **Yes** — filters, sweeps, **optimize-ttc-window** | Map minutes ↔ seconds (§3). |
| `min_probability`, `max_probability` | Prob gates | **Yes** — `--min-prob` / `--max-prob` | DB scale ~0–100. |
| `min_differential`, `max_differential` | HTC-style gates | Partial / via trade row if column populated | Extend filters + docs per strategy. |
| `allow_re_entry` | Re-entry behavior | **Not yet** | Needs explicit trade-state model. |
| Spike alert fields | Adjusted prob / behavior | **Not yet** | Requires time-series of spike state or approximation. |
| `min_volume` | Volume gate | **Not yet** | If stored per trade or reconstructable. |
| `momentum_scalp_entry_threshold` | Momentum scalp | **Not yet** | Need momentum at signal time vs trade row. |
| `min_ask`, `max_ask`, `max_price_spread` | Price / microstructure | **Partial** — prices on trade | Full gate may need book snapshots. |
| `prob_adj` | Cooldown probability bump | **Not yet** | Coupled to spike/cooldown state machine. |
| `min_cooldown_timer`, `max_cooldown_timer` | Cooldown | **Not yet** | Needs cycle-aware simulation. |
| **`auto_trade` / `paper_trade`** (monitor + trade) | Master enable | **Yes** — `--paper`; monitor row for strategy | |
| Position / fees | Not always entry gate | **Yes** — **`--hypothetical-position`** + Kalshi taker fee model | Matches fee shape used in trade path (see `scripts/backtest/helpers/hypothetical_trades.py`). |

**Rule of thumb:** if it appears in **`get_auto_entry_settings()`** or in the **strategy branch** that sets `scanning_active` / entry allowed, it is **fair game** for a future backtest dimension. Implementations should stay **allowlisted** (no arbitrary SQL) for safety, mirroring `trade_filters.py`.

---

## 5. Current implementation (CLI)

**Entrypoint:** `scripts/backtest/core_backtester.py`  
**DB access:** `scripts/backtest/helpers/db.py` (SSH tunnel to prod default; env-driven).  
**Helpers:** `scripts/backtest/helpers/*` — monitors, filters, aggregates, hypothetical math, TTC SQL/Python parity.

### 5.1 Modes (summary)

| Feature | Description |
|---------|-------------|
| **Standard summary** | W/L by monitor; per-trade vs per-cycle (Momentum Contain / Breakout) from `monitor_list.strategy`. |
| **Filters** | Paper/live, prob, TTC (SQL or Python), repeatable `--trade-filter` (allowlisted columns). |
| **Hypothetical position** | Fixed contracts; recompute fees + PnL + `ret_pct` / `ret_pct_base` on closed/settled rows. |
| **Max TTC sweep** | `--max-ttc-sweep` + step seconds; one fetch per monitor. |
| **TTC window optimization** | `--optimize-ttc-window` — grid on **(MIN_TTC≥, MAX_TTC≤)**; default objective **`sum_ret_pct`** (total hypo % points over included trades). |
| **Tables** | Shared `_text_table()` formatter for consistent CLI output. |
| **Strike archive → tick HTC replay** | **`--build-tick-backtest-from-archive`** + **`--replay-htc-market`** + **`--replay-from-tick-backtest`**; see §5.5. |
| **Setting grid sweep** | **`htc_archive_setting_sweep.py`**: Cartesian overrides over archive markets in a window; see §5.6. |

### 5.2 Important limitations (today)

- **Cycle strategies:** hypothetical blocks are **per closed trade**, not re-rolled cycle PnL — documented in CLI output when relevant.
- **Hypothetical** does not yet apply arbitrary per-row overrides (paper flip, custom prices) beyond position sizing; **`apply_overrides`** in `hypothetical_trades.py` is the extension point.
- **Supervisor parity** for spike alerts, cooldown timers, and momentum scalp **full** path is **not** implemented.

### 5.3 Hypothetical entry pricing (`price_estimator`)

**CLI:** `scripts/backtest/price_estimator.py`

**Role:** estimate a **plausible** historical **entry (`buy_price`)** from peer trades using **TTC** (market-specific 15m vs hourly), **spot − strike**, **model `prob`**, and optional **side** stratification — for **hypothetical** backtests when full order-book data is unavailable.

**Methodology, evaluation protocol, live vs paper pools, and analytics-pipeline plans** are documented in **[`docs/BACKTEST_PRICE_ESTIMATOR.md`](./BACKTEST_PRICE_ESTIMATOR.md)** (source of truth for this sub-area). Re-run **`--peer-holdout`** as data grows; prefer **conservative** (non-optimistic) fill assumptions when comparing strategies.

**Future direction:** combine **`historical_data.*_price_history`** timestamps with Kalshi **1m contract candlesticks** for large random **spot checks** of hypothetical fills (not limited to rows we actually traded). The scratch pipeline below is the on-ramp.

### 5.4 Kalshi 1m candlesticks (scratch tables)

**Purpose:** On demand, pull a market’s **full 1m bars** for its Kalshi **`open_time`..`close_time`** window (from `GET /markets/{ticker}`), aligned with **`historical_data` price-history** convention (**`timestamp`** first column = US Eastern wall time, no TZ).

**CLI:** `scripts/backtest/helpers/kalshi_market_candles_scratch.py`  
**Library:** `scripts/backtest/helpers/kalshi_candles_1m.py` (also used by `scripts/testing/populate_kalshi_testing_candles_1m.py` for **`testing."candlesticks_1m_*"`** migration tables).

**Table naming (ephemeral):** `historical_data.kalshi_candles_1m_<ticker_slug>_YYYYMMDD` where **`YYYYMMDD`** is a **UTC calendar date** (default: today). Re-running the same ticker and date **upserts** into the same table.

**Rotation:** Run **`--cleanup-only --retention-days N`** (e.g. daily cron) to **`DROP`** scratch tables whose suffix date is **before** `UTC today − N` days. These tables are **not** in `database.py`; they are intentionally disposable.

**API:** Live **`/series/{series}/markets/{ticker}/candlesticks`** first; falls back to **`/historical/markets/{ticker}/candlesticks`** when needed. See **`docs/BACKTEST_PRICE_ESTIMATOR.md`** §10 for cutoff vs live/historical.

**Market duration (hourly vs 15m, etc.):** The fetch window is always Kalshi’s **`open_time`..`close_time`** from **`GET /markets/{ticker}`** with **`period_interval=1`**. Row count matches session length in minutes (e.g. **~60** bars for a **one-hour** contract, **~15** for a **15-minute** contract). **`series_ticker`** for the path is the segment **before the first `-`** in the market ticker (e.g. **`KXBTCD`** vs **`KXBTC15M`**). Session boundaries (quarter-hour for 15m, etc.) come from the API, not from local clock math.

### 5.5 Strike archive → tick HTC replay (live-parity path)

**Purpose:** Reproduce **15m / hourly HTC** entry and ATS-style exit on **the same strike snapshots** the live stack archived, without reconstructing ticks from 1s price logs or trade tape.

**Data:** `historical_data.strike_table_master` (partitioned parent; rows keyed by `market_ticker` + `timestamp`, US Eastern naive `TIMESTAMP WITHOUT TIME ZONE`). Populated when **`REC_STRIKE_TABLE_ARCHIVE`** is enabled and strike generators run; see `docs/MASTER_DB_SCHEMA_REFERENCE.md` and `backend/historical_strike_table_archive.py`.

**CLI** (`scripts/backtest/core_backtester.py`):

1. **`--build-tick-backtest-from-archive TICKER`** — copies matching archive rows into **`backtest.tick_backtest_<slug>`** with Eastern-naive **`timestamp`** / **`created_at`** (same column contract as `live_data.strike_table_15m`). Multiple archive instants in the same **Eastern clock second** collapse to the latest **`timestamptz`**.

2. **`--replay-htc-market TICKER --replay-from-tick-backtest`** — chronological scan of that table; entry settings from **`--replay-monitor-id`** + **`--replay-monitor-user`** (`users…monitor_list_*` via tenant rewrite) or **`--replay-strategy`**. Sizing: **`--replay-bankroll`**, **`--replay-allocation-pct`**. Optional **`--min-prob` / `--max-prob`** overrides.

**Contrast:** **`--build-tick-backtest`** (no `from-archive`) builds **`tick_backtest_*`** from **`live_price_log_1s_*`** + **`backtest.kalshi_historical_trades_api`** — use when the archive has no rows yet.

**DB access:** `scripts/backtest/helpers/db.py`. For **tenant** tables in replay, set **`REC_USER_SCHEMA=users_NNNN`** (e.g. `users_0001`) so legacy `users.*` SQL rewrites correctly. **`REC_IO_BACKTEST_DB=prod`** uses SSH tunneling; run the same commands on the production host with local Postgres if preferred.

**Settlement (tick replay):** Expiry **`market_result`** for PnL is resolved via **`resolve_floor_strike_and_market_result`** (Kalshi metadata), not the archive column **`market_result`** (that column is for analytics / backfill after lifecycle).

**Code:** `scripts/backtest/helpers/tick_backtest_build.py` (`build_tick_backtest_from_strike_archive`), `scripts/backtest/helpers/htc_backtest_replay.py` (`run_htc_single_market_replay`, `from_tick_table=True`). **Worked example** and copy-paste commands: **`scripts/backtest/README.md`** (section *Strike archive → tick HTC replay*).

**Window-only tick builds:** `build_tick_backtest_from_strike_archive(..., timestamp_start=, timestamp_end_exclusive=)` restricts rows to `[start, end)` so sweeps and range studies do not pull an entire market’s history.

### 5.6 Setting grid sweep (optimization research)

**Purpose:** Over a **time window**, discover all markets present in **`historical_data.strike_table_master`**, materialize **window-sliced** `backtest.tick_backtest_*` tables, then run the **full Cartesian product** of per-dimension overrides (defaults: **`max_time`** (seconds), **`min_probability`**, **`stop_loss_price`**) on top of a **base** `monitor_list_*` row. Aggregate **sum PnL**, **win rate**, etc., and rank combos to inform live monitor tuning.

**CLI:** `scripts/backtest/htc_archive_setting_sweep.py`  
**Library:** `scripts/backtest/helpers/htc_setting_grid_sweep.py` (`parse_int_range_hi_lo_step`, `parse_float_range_lo_hi_step`, `discover_markets_in_archive_window`, `run_setting_grid_sweep`).

**Cost:** work scales as **`|grid| × |markets|`** replays (each replay scans one tick table). Use **`--dry-run`**, narrow **`--series-prefix`**, raise **`--min-archive-rows`**, and coarser grid steps when exploring.

**Objectives:** `--objective sum_pnl` (default), `mean_pnl`, `win_rate`, `sum_ret_pct` (sum of per-episode `ret_pct`; with **compounding**, each episode’s `ret_pct` uses the **current equity** as denominator).

**Compounding (default):** Equity starts at **`--replay-bankroll`**. Markets are processed in **archive order**; after each closed trade, equity is updated before the next market. Disable with **`--no-compound`** (every replay uses the same starting bankroll and `ret_pct` vs that bankroll).

**Synthetic trades table:** **`--persist-trades`** inserts one row per closed replay into **`backtest.grid_sweep_trades`** (same shape as **`users…trades_*`** plus `sweep_batch_id`, `synthetic_monitor_id`, `source_monitor_id`). Filter by **`sweep_batch_id`** or **`synthetic_monitor_id`** / **`monitor`** (`mon_<user>_<synthetic_monitor_id>`). Requires migration **`20260416_1015_backtest_grid_sweep_trades`**.

---

## 6. Data and safety

- Reads **production-shaped** data; respect **real-money** governance (no silent live setting changes from this repo unless explicitly built and approved).
- Default excludes **`test_filter`** rows unless `--include-test-filter`.
- **No secrets in code** — connection via env / SSH as documented in `scripts/backtest/helpers/db.py` and `.env.example` (if present).

---

## 7. Web UI roadmap (backtester tab)

**Placeholder:** `frontend/tabs/backtester.html` (linked from `frontend/index.html`).

**Target experience:**

1. Select **monitors** (multi-select) and **datetime range** (timezone explicit).
2. Panel of **auto-trade knobs** mirroring `monitor_list` + hypothetical options (position size, objectives).
3. **Run** triggers a **backend job or API** that executes the same logic as the CLI (or calls it as a subprocess with structured JSON output — implementation choice TBD).
4. **Results:** sortable tables, optional charts, export CSV/JSON.
5. **Parity:** when the desktop tab is built, add **mobile** equivalent per project convention (`AGENTS.md`).

---

## 8. Autonomous optimization roadmap (future)

- **Inputs:** same search space as UI + **guardrail config** (per-field min/max, max step, cadence, monitors included/excluded).
- **Outputs:** proposed deltas, diff vs current `monitor_list`, confidence/sample size metrics.
- **Apply path:** human approval, or policy-limited auto-apply with audit log.
- **Safety:** dry-run default; separate role/flag for mutation; never violate user thresholds.

---

## 9. File map

| Path | Purpose |
|------|---------|
| `scripts/backtest/helpers/db.py` | DB connectivity. |
| `scripts/backtest/helpers/trade_filters.py` | TTC SQL, allowlisted column filters. |
| `scripts/backtest/helpers/hypothetical_trades.py` | Fee + hypo PnL / ret%. |
| `scripts/backtest/helpers/monitor_context.py` | `monitor_list` resolution, cycle strategy detection. |
| `scripts/backtest/helpers/aggregates.py` | SQL aggregates for metrics. |
| `scripts/backtest/core_backtester.py` | CLI orchestration, reports; **`--ingest-kalshi-tickers`** loads Kalshi candles + metadata + price-history columns (`open`, `high`, …) from **`historical_data.*_price_history`** (KXBTC/KXETH tickers) into **`backtest.backtest_1m_<slug>`**. **`--ingest-no-spot`** skips the join. **`--build-tick-backtest-from-archive`** + **`--replay-htc-market`** / **`--replay-from-tick-backtest`**: strike archive HTC replay (§5.5). |
| `scripts/backtest/helpers/tick_backtest_build.py` | **`build_tick_backtest_from_strike_archive`**: **`historical_data.strike_table_master`** → **`backtest.tick_backtest_*`**. Also **`build_tick_backtest_table`** (1s log + trades). |
| `scripts/backtest/helpers/htc_backtest_replay.py` | **`run_htc_single_market_replay`** on **`backtest_1m_*`** or **`tick_backtest_*`**. |
| `scripts/backtest/helpers/htc_setting_grid_sweep.py` | Archive-window discovery + **Cartesian** monitor overrides + aggregated replay metrics. |
| `scripts/backtest/htc_archive_setting_sweep.py` | CLI for §5.6 grid sweep. |
| `scripts/backtest/helpers/kalshi_candles_1m.py` | Kalshi 1m fetch + upsert (testing, scratch, or **`backtest`** with `floor_strike` / `market_result`; `ensure_backtest_candles_with_meta_table`). |
| `scripts/backtest/helpers/kalshi_market_candles_scratch.py` | CLI: ephemeral `historical_data.kalshi_candles_1m_*_YYYYMMDD` + cleanup. |
| `backend/auto_entry_supervisor.py` | Live gates + `get_auto_entry_settings()`. |
| `frontend/tabs/backtester.html` | UI placeholder. |
| `scripts/backtest/price_estimator.py` | Hypothetical fill pricing from peer trades (see §5.3). |
| `backend/util/auto_entry_htc_gates.py` | **Backtest-only** mirror of Hourly HTC strike gates (see §2.1); not imported by production. |
| `scripts/backtest/helpers/htc_aes_replay.py` | Helpers for replaying AES-style strike order + 15m TTC (see §2.1). |
| `backend/util/cycle_replay/` | Sealed cycle-package replay (strategy adapters + paper fills). |
| `scripts/backtest/cycle_replay_parity.py` | Side-by-side replay vs live `trades_*` (times first; see §2.3). |
| **`docs/BACKTESTING.md`** | **This document — initiative source of truth.** |
| **`docs/BACKTEST_PRICE_ESTIMATOR.md`** | **Peer pricing methodology, holdout protocol, pipeline notes.** |

---

## 10. Contributing / extending

When adding a new **supervisor-driven** dimension:

1. If the change is in **`auto_entry_supervisor.py` entry logic** (any strategy), update the corresponding **backtest mirrors** under `scripts/backtest/` (and backtest-only helpers such as `backend/util/auto_entry_htc_gates.py` where applicable). See §2.1.
2. **Trace** where it is read in `auto_entry_supervisor.py` and **which DB columns** feed it.
3. **Confirm** whether the signal exists on **`trades`** (or derivable) at **entry time**.
4. Add **allowlisted** filter or hypo pass in **`trade_filters.py`** / hypothetical pipeline; document units and defaults here.
5. If the UI will expose it, add to the **future API contract** section (append below when designed).

---

## 11. Revision history (manual)

| Date | Note |
|------|------|
| 2026-03-21 | Initiative doc created: CLI backtester, TTC optimization, supervisor parity table, UI/autonomy roadmap. |
| 2026-03-21 | §5.3 + file map: `price_estimator` hypothetical pricing; linked `BACKTEST_PRICE_ESTIMATOR.md`. |
| 2026-03-22 | §5.4: Kalshi 1m scratch tables + cleanup; hourly vs 15m row counts + `series_ticker` prefix; `kalshi_candles_1m` / `kalshi_market_candles_scratch`. |
| 2026-04-15 | §5.5–§5.6 + README: strike archive tick replay; **setting grid sweep** (`htc_archive_setting_sweep.py`, `htc_setting_grid_sweep.py`); window bounds on `build_tick_backtest_from_strike_archive`. |
| 2026-04-16 | §5.6: **compounding** bankroll across markets (default); **`--persist-trades`** → `backtest.grid_sweep_trades`; `grid_sweep_trades.py`, `fetch_monitor_trade_meta`. |
| 2026-03-21 | §2.1 + file map + contributing: AES changes must be reflected in backtest scripts; documented `auto_entry_htc_gates` / `htc_aes_replay`. |
| 2026-07-28 | §2.3: cycle packages as live-workflow diagnostics; investigate replay-vs-live entry Δ before any simulated lag. |
