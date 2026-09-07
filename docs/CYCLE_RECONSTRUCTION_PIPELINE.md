# Cycle Reconstruction Pipeline

**Status:** Canonical proposal + implementation contract (local offline/batch analysis only)  
**Owner:** VIRGIL DEV (local `3_0` checkout)  
**Schema / generator version:** `cycle_recon.v1`  
**Related (do not conflate):** live Expiration Scalp Order-Book Risk Service (S2–S6) — **out of scope**; do not advance that plan from this work.

---

## 1. Purpose

Replace repetitive, token-heavy manual preparation with a **deterministic programmatic shell**.

Given a date/time span, ticker(s), and/or strategy trade-log / trade IDs, the tool:

1. Locates sealed historical cycle packages (`.tar.xz`)
2. Reconstructs the **single** Kalshi binary-contract order book
3. Fetches and caches public Kalshi executed trades
4. Aligns BTC/symbol prices and strategy trade lifecycle
5. Validates data continuity
6. Emits a **compact versioned analysis package** an LLM can consume without reopening raw archives

### Strict boundary

| Layer | Responsibility | This project |
|-------|----------------|--------------|
| **(1) Reconstruction facts** | Source events, book state, liquidity/VWAP, public trades, BTC/symbol price, timestamps, data quality | **Implements** |
| **(2) Analytical interpretation** | Risk labels, trade gates, predictions, strategy recommendations | **Does not implement** |

Quality states (`COMPLETE` / `DEGRADED` / `INVALID` / `MISSING`) are **infrastructure/data quality**, never market-risk judgments.

---

## 2. Hard safety / scope

- Runs **only** in the local saved `3_0` checkout.
- **Forbidden:** production deploy/restart, supervisor changes, live-service mutation, live Redis mutation, production DB migration/write, trading behavior change.
- **Allowed reads:** historical archives (local + Drive mirror), trade-log CSVs, local Postgres **read** for optional trade-row lookup, public/read-only Kalshi endpoints.
- **Allowed writes:** local cache dirs, local analysis run dirs, local logs; optional `pip install` into local `.venv` only.
- Preserve unrelated dirty worktree changes. **No git commit** unless Eric explicitly asks.
- If any command’s production-touch status is ambiguous → **stop and ask**.

---

## 3. Architecture overview

```
                    ┌─────────────────────────────────────┐
                    │  CLI / localhost prototype UI         │
                    │  (request → run_id → progress)        │
                    └─────────────────┬───────────────────┘
                                      │
                    ┌─────────────────▼───────────────────┐
                    │  Orchestrator (bounded workers)       │
                    │  resolve markets → per-market pipeline│
                    └─┬───────┬──────────┬──────────┬─────┘
                      │       │          │          │
           ┌──────────▼──┐ ┌──▼──────┐ ┌─▼──────┐ ┌▼────────────┐
           │ Archive     │ │ Public  │ │ Trade  │ │ Symbol/BTC  │
           │ adapter     │ │ trades  │ │ log    │ │ adapter     │
           │ (.tar.xz)   │ │ adapter │ │ adapter│ │ (from pkg)  │
           └──────┬──────┘ └──┬──────┘ └──┬─────┘ └──────┬──────┘
                  │           │           │              │
           ┌──────▼───────────▼───────────▼──────────────▼──────┐
           │  Reconstruction engine                               │
           │  book events → quality → regularized series →        │
           │  measurements → lifecycle observations               │
           └──────────────────────┬───────────────────────────────┘
                                  │
           ┌──────────────────────▼───────────────────────────────┐
           │  Package writer (atomic)                             │
           │  manifest / quality / summary / README / tables      │
           └──────────────────────────────────────────────────────┘
```

### Module layout (implementation)

| Path | Role |
|------|------|
| `docs/CYCLE_RECONSTRUCTION_PIPELINE.md` | This contract |
| `backend/core/cycle_recon/` | Library: adapters, book engine, metrics, package I/O |
| `scripts/cycle_recon/reconstruct.py` | Batch CLI |
| `scripts/cycle_recon/ui_server.py` | Optional standalone localhost UI (`127.0.0.1:8765`) |
| `frontend/tabs/backtester.html` | Main desktop **Backtester** tab (cycle reconstruction UI) |
| `frontend/tabs/cycle_recon.html` | Redirect to Backtester (legacy deep link) |
| `backend/web/routers/cycle_recon_routes.py` | Authenticated `/api/cycle_recon/*` on main_app |
| `backend/core/cycle_recon/archive.py` | Canonical handoff `.tar.zst` / `.tar.gz` packaging |
| `backend/data/historical_data/cycle_recon_cache/` | API + normalized archive cache |
| `backend/data/historical_data/cycle_recon_runs/` | Default run output root |
| `tests/unit/cycle_recon/` | Unit + fixture tests |
| `tests/fixtures/cycle_recon/` | Golden / degraded fixtures |

Reuse (do not fork semantics):

- `backend/core/cycle_package.py` — load `.tar.xz`, `iter_book_states`, cycle open/close UTC
- `backend/core/cycle_packager.py` — `package_path_for_ticker`, Eastern month folders
- `backend/core/orderbook_strike_prices.py` — complementary touch + `project_taker_buy_from_levels`
- `backend/core/time_eastern.py` / package UTC parsers — clock helpers
- `scripts/backtest/fetch_kalshi_historical_trades_to_backtest.py` — pagination patterns (file-cache variant here; no required DB upsert)
- `scripts/gdrive/download-backtesting-data.js` — optional local archive fetch from Drive

---

## 4. Primary interfaces

### 4.1 Batch CLI (primary)

```bash
PYTHONPATH=. .venv/bin/python scripts/cycle_recon/reconstruct.py \
  [--start ISO] [--end ISO] \
  [--ticker TICKER ...] \
  [--trade-log PATH.csv] [--trade-id ID ...] [--monitor MON ...] \
  [--pre-entry-seconds N] [--post-close-seconds N] \
  [--context-1s / --near-ms 100] \
  [--output-dir PATH] \
  [--workers N] \
  [--force-refresh] [--offline] \
  [--export-csv] \
  [--standardized-sizes 1,5,10,25,50,100]
```

**Resolution rules**

- Any combination of time range, tickers, and trade-log filters is valid.
- Trade-log / trade-id paths expand to tickers + entry/close anchors.
- Missing sealed packages → market status `MISSING` with reason; do not invent book state.
- `--offline` / cache-only: use local archives + API cache only; fail required public-trade completeness if cache incomplete (unless market already `MISSING`).
- Default workers: `2` (cap sensible default `4`). Target ≤2 saturated cores and &lt;2 GB peak.

### 4.2 Prototype UI (after CLI acceptance)

- Bind **`127.0.0.1` only** (pattern: `orderbook_ui_redis_server.py`).
- Inputs: datetime range, tickers, optional trade log/IDs, context windows.
- Actions: start/cancel local job; show progress/errors; list packages; quality summary; market/trade selector; compact whole-cent entry snapshot + lifecycle preview; download links.
- Label clearly: **local analysis tooling** — no auth, no deploy.

---

## 5. Data sources (adapter boundaries)

### 5.1 Historical cycle packages (authoritative book + spot rings)

- Layout: `backend/data/historical_data/backtesting_data/{SERIES}/{YYYY}/{YYYY_MM_MON}/{TICKER}.tar.xz`
- Members (`schema_version` 2): `meta.json`, `market_meta.json`, `snapshot.csv`, `deltas.csv`, `strike_table.csv`, `price_ring.csv`, `metrics_ring.csv`
- Optional: pull missing packages from Drive via existing download script into the **same** local tree (archive cache only).

### 5.2 Public Kalshi executed trades

- Default endpoint: `GET /trade-api/v2/markets/trades` (public tape; unsigned OK; signed optional for rate consistency).
- Fully paginate; retry with backoff; respect rate limits.
- **File cache** keyed by `(ticker, endpoint, query hash)` under `cycle_recon_cache/kalshi_trades/`.
- Record fetch metadata: request params, page counts, `fetched_at`, completeness flag, raw response hashes.
- Prefer file cache over writing `backtest.kalshi_historical_trades_api` (local analysis isolation). Optional read of existing DB rows is allowed as a cache hint but never required.

### 5.3 Strategy trade log

- **Default source:** tenant Postgres trade log (`users_NNNN.trades_NNNN` ∪ `archive.*`) via `--user-no` / session tenant. Mapped to source-scoped `StrategyTradeRef` (`source_namespace=pg:users_NNNN`).
- **CSV override:** `--trade-log PATH.csv` for fixtures/dev only (disables PG for that run).
- Required matching keys when present: `id`, `ticker`, `monitor`, `side`, `buy_price`, `sell_price`, `position`, open/close timestamps (`date`+`time` / `closed_at` / `created_at`), etc.
- Preserve available fields; leave absent columns `NULL` — **no defaults that invent venue state**.
- Missing `--trade-id` values are reported in `resolve_notes.missing_trade_ids` — **never substituted** with other rows.

### 5.4 Symbol / BTC prices

- Primary: `price_ring.csv` inside the cycle package (`spot`, `avg_60s`, etc.).
- Do **not** substitute Kalshi candles or guessed closes when the ring gaps (aligns with `trade_history_detail` / no-fallbacks).

### 5.5 Future adapters

Interfaces stay exchange/symbol-agnostic at the orchestrator boundary (`ArchiveSource`, `PublicTapeSource`, `TradeLogSource`, `SymbolPriceSource`) so additional venues can plug in later.

---

## 6. Time and book semantics

### 6.1 Clocks

- Analytical timestamps: **UTC** (`…Z` / offset-aware).
- **Backtester UI:** operators enter **Eastern** wall times (`America/New_York`); routes/CLI convert with `--start-et` / `--end-et` or `--range {24h,7d,30d,all}` before archive discovery and reconstruction.
- Trade-log `date` / `time` / `closed_at` are Eastern calendar fields (same as live trade history); `created_at`/`updated_at` are timestamptz when present.
- Derive **ET display** fields for humans; never store ET as the sole canonical analysis clock.
- Explicit fields: `cycle_open_utc`, `cycle_close_utc`, `ttc_seconds`, `seconds_since_cycle_open`, `seconds_relative_to_entry`.

**Conflict note (repo):** backtest CLI TTC sometimes uses **minutes**; live/cycle packages use **seconds**. This pipeline uses **seconds** everywhere and documents units in manifests.

### 6.2 One order book

- Kalshi stores **YES and NO bid maps**; asks are **complements** (`1 − opposite bid`) via `touch_dollars_from_orderbook_snapshot` / fill walks in `project_taker_buy_from_levels`.
- YES/NO are complementary price/side representations — **not** independent books.
- Apply events in authoritative sequence (`snapshot_seq` eras + `received_at` order), matching `iter_book_states` era resets.

### 6.3 Continuity / quality

Detect and record (never silently heal):

- Missing / duplicated / out-of-order deltas
- Negative depth after apply
- Crossed / invalid touch states
- Resyncs (`snapshot_seq` changes)
- Timestamp gaps above configured thresholds

**Never interpolate gaps.** Carried-forward regularized samples must expose `book_age_ms` / `stale` markers and exact degraded intervals. A 10s gap must not look like 10s of stable book.

---

## 7. Output resolutions

| Series | Default | Notes |
|--------|---------|-------|
| Raw / event-resolution | Always | `book_events.parquet` — every snapshot/delta with post-apply state summary |
| Regularized broad | 1s | Context window around cycle / entry |
| Regularized near events | Optional 100ms | Near entry and material book events |
| Raw ladder | Event + key observations | Tenth-cent (or native price) levels |
| Whole-cent ladder | Primary analyst view | Aggregate depth into whole-cent bins; tenth-cent retained but not dominant in summaries |

---

## 8. Deterministic measurements (facts only)

At each relevant observation (and documented standardized sizes):

- Best executable bid/ask, spread, midpoint where meaningful
- Raw and whole-cent depth
- Cumulative depth within 1c / 2c / 3c / 5c / 10c / 15c
- Largest shelf, shelf price, depth concentration, empty whole-cent levels, distance to material shelf
- Entry and liquidation VWAP for actual / configured / standardized sizes
- Worst level reached, fill coverage, slippage, qty to move executable price by 1c / 2c / 5c / 10c
- Rolling update/count/quantity and quote-jump summaries over 1 / 3 / 5 / 10 / 30 / 60s
- BTC/symbol spot, strike buffer dollars and percent, movement where source permits
- Public trade counts, contracts, notional, VWAP, largest print, price levels crossed, time since trade
- Signed / aggressor flow **only** when reliably determinable from tape fields; else `UNKNOWN` — **never zero-by-assumption**

**No-lookahead / no-leakage (non-negotiable):**

- Book state at an observation uses the last event with `event_ts <= observation_ts` (never end-of-second after the observation).
- Decision-time `public_trade_windows` are strictly trailing `[observation_ts - window, observation_ts]` for windows **1 / 3 / 5 / 10 / 30 / 60s** — never centered ± and never future prints.
- Post-entry/collapse context, if emitted, uses separately named `post_event_*` windows/tables only (not entry features).

Unavailable by design (document in README / quality): exchange-level BTC trades, order IDs / queue position, cancellation identity, unreliable aggressor, missing trigger timestamps when not in trade log.

---

## 9. Trade lifecycle alignment

Observation anchors (emit only when data is present and not stale-beyond-policy):

- Cycle open
- 120 / 90 / 60 / 30 / 15 / 10 / 5 / 1 seconds before entry (when available)
- Entry trigger / fill
- Each subsequent second while open (or regularized while position open)
- Maximum favorable / adverse executable price marks
- Limit fill / stop trigger / stop execution (when timestamps exist)
- Expiration / actual close

Each row includes: seconds since cycle open, TTC, seconds relative to entry, position state, BTC buffer, book/liquidity measurements, public-trade windows, quality state.

**Do not manufacture** observations across stale/missing intervals.

---

## 10. Versioned package contract

One run directory (atomic publish):

```
{output_dir}/{run_id}/
  run_manifest.json
  quality_report.json
  summary.json
  README.md
  schema.json
  markets.parquet
  strategy_trades.parquet
  book_events.parquet
  initial_book_snapshots.parquet
  book_timeseries.parquet
  whole_cent_ladder.parquet
  public_trades.parquet
  symbol_timeseries.parquet
  trade_lifecycle.parquet
  debug/                 # optional CSV dumps when --export-csv
```

While writing: `{run_id}.partial/` contains the same tables plus `.incomplete`. On success, `.incomplete` is removed and the directory is renamed to `{run_id}/`.

### Handoff archive (analyst / LLM)

After a successful run (default ON; disable with `--no-archive`):

- Preferred: `{run_id}.tar.zst` (python-zstandard or system `zstd`); fallback `{run_id}.tar.gz`
- Atomic publish via `{run_id}.archive.partial` → verify extract+checksums → rename; failures leave `.archive.failed` and never a final archive name
- Payload is a single top-level `{run_id}/` with README, schema, manifests, `analyst_index.json`, `checksums.sha256`, and all Parquet tables (excludes `debug/`)
- Sidecar `{archive}.sha256`; on-disk `summary.json` / `run_manifest.json` gain `handoff_archive` metadata after publish
- Directory remains for debugging; archive is the canonical analyst download

### Atomicity

- Write under `{run_id}.partial/` (with `.incomplete` present), flush streams, write JSON manifests, delete `.incomplete`, then `rename` to `{run_id}/`.
- Interrupted runs leave `{run_id}.partial/` (and `.incomplete`); they must not be treated as complete packages.

### Parquet vs fallback

- **Canonical:** Apache Parquet via **optional** `pyarrow` (install into local `.venv` when missing).
- **Documented fallback** if pyarrow cannot be installed: typed **JSON Lines + zstd** (`.jsonl.zst`) per table **plus** `schema.json` (column name, type, nullability). Same logical columns; `summary.json` lists actual encodings. Never silently omit required tables.

### Key JSON contracts (sketch)

`run_manifest.json`: request, `generator_version`, `schema_version`, git revision, source paths/hashes, requested/found/missing markets, timings, cache hit/miss counts, exit semantics.

`quality_report.json`: per-market status + reason codes + exact affected intervals; archive/API gaps; delta/order errors.

`summary.json`: compact LLM-friendly factual overview + file inventory + “what you can answer from this package” checklist.

`README.md`: human explanation, clock/book semantics warnings, unavailable fields list.

---

## 11. Quality states and reason codes

| State | Meaning |
|-------|---------|
| `COMPLETE` | Required sources present; continuity within thresholds; measurements trustworthy for analysis |
| `DEGRADED` | Usable with caveats; exact intervals listed (gaps, stale carry-forward, partial tape) |
| `INVALID` | Reconstruction inconsistent (e.g. unrecoverable book corruption); do not trust levels |
| `MISSING` | No sealed package and/or required source absent |

Example reason codes: `ARCHIVE_NOT_FOUND`, `SNAPSHOT_MISSING`, `DELTA_GAP`, `DELTA_DUPLICATE`, `DELTA_OUT_OF_ORDER`, `NEGATIVE_DEPTH`, `CROSSED_BOOK`, `RESYNC`, `TIMESTAMP_GAP`, `STALE_SAMPLE`, `API_INCOMPLETE`, `API_CACHE_MISS_OFFLINE`, `TRADE_LOG_UNMATCHED`, `SYMBOL_RING_GAP`.

---

## 12. Reproducibility and performance

- Hash inputs (archive bytes, trade-log bytes, API cache keys, CLI args, schema/generator versions).
- Same inputs + version → equivalent outputs (stable sorts; deterministic quantization).
- Streaming / bounded concurrency; default sequential markets for memory; target &lt;2 GB peak.
- Structured logs: per-market progress, timings, API/cache counts.
- Nonzero process exit if any **required** output failed for a requested market that was resolvable.

### Wall-time profile (local, 2026-09-06)

Per-event YES/NO touch originally called the full live `touch_dollars_from_orderbook_snapshot` stack (~90% of `reconstruct_book` time). Replaced with an equivalent lightweight complement touch (`1 - best_opposite_bid`) for reconstruct-time jump/cross detection; parity covered by unit test. Effect: single-market `KXBTC15M-26SEP051130-30` offline package ~173s → ~19s.

**Remaining performance limitation:** large batches are still CPU-bound on Python delta replay + writing full `book_events` (hundreds of thousands of rows per market). The pre-optimization 8-market/2h run was ~1161s at ~557 MB RSS. After the touch fix, expect roughly an order-of-magnitude wall reduction for reconstruct-dominated runs; further wins (optional event-table sampling, Cython/numba apply path, multi-process per market with separate writers) are **follow-up**, not required for correctness.

---

## 12b. Unavailable inputs / data limitations

Documented in package `README.md` / `summary.json` and enforced as NULL/UNKNOWN (no fabricated substitutes):

| Unavailable | Why |
|-------------|-----|
| Exchange-level BTC trades | Not in sealed cycle package / public Kalshi market tape |
| Order IDs / queue position | Venue does not expose in archive deltas |
| Cancellation identity | Deltas are size changes only |
| Reliable aggressor when tape lacks taker fields | Emitted as `UNKNOWN`, never zero-by-assumption |
| Trigger timestamps not in trade log | Lifecycle anchors omitted rather than invented |
| Book as-of before first archive event | Observation skipped (no manufactured pre-open book) |
| Offline public tape without complete local cache | Fails with cache miss / `API_CACHE_MISS_OFFLINE` |

---

## 13. Testing

Unit/integration coverage:

- Snapshot + delta reconstruction
- Complementary pricing
- Whole-cent aggregation
- Entry/liquidation VWAP
- Sparse books
- Gaps / duplicates / out-of-order
- Stale sampling policy
- Timezone / midnight boundaries
- Public-trade pagination + cache
- Trade-log matching
- Partial packages / atomic incomplete runs

Golden fixtures (clean + degraded): prefer recent sealed packages; include trade IDs **55286** and **55388** when their packages exist locally or after Drive pull; include at least one known 10–20s gap packet (Sep 5 target) and one clean Sep 6 packet when archives are available. **Do not hardcode unsupported conclusions from previously degraded archives.**

---

## 14. Seven-day acceptance runs (local)

After implementation, run locally:

1. Single ticker/cycle
2. Narrow multi-cycle time range
3. Trade-log-driven set
4. Clean Sep 6 range (when packages available)
5. Degraded Sep 5 range with known gap (when available)
6. Broader multi-hour / full-day if resource use is reasonable

Exercise API fetch + cache-hit/offline rerun. Record runtime, memory where possible, package sizes, markets found/missing, row counts, quality states, errors.

After each representative package: summarize schema + sample rows for analyst handoff (entry book/ladder, VWAP, pre-entry evolution, lifecycle, BTC buffer, public prints, gaps/trust).

---

## 15. Conflicts with existing data semantics (flagged)

1. **YES/NO books** — Brief and repo agree: one book, complementary asks. Do not treat stored YES+NO as independent ask ladders.
2. **Clocks** — Packages are UTC-Z; many `historical_data` tables are Eastern-naive. Pipeline normalizes analysis to UTC and derives ET labels.
3. **TTC units** — Seconds here; ignore minute-based backtest filter helpers.
4. **`market_result` / settlement** — Preserve package/trade-log venue fields as facts. Never confirm W/L from `symbol_close` / strike math when venue result is missing (workspace no-fallbacks).
5. **Tape vs book** — Public trades are not a substitute for reconstructed book VWAP; both appear in the package distinctly.
6. **Local archive coverage** — On-disk sealed packages may lag Drive (observed: JUL/AUG present; Sep may require download). Acceptance runs that need Sep packages depend on local archive availability.
7. **Trade IDs 55286 / 55388** — In local `users_0001.trades_0001` these map to **May 2026** rows (`KXETH15M-26MAY302300-00`, `KXBTCD-26MAY3103-T73699.99`), not Sep cycles. Fixture selection must follow the operator’s intended identity (see open questions).
8. **pyarrow** — Not currently installed in `.venv`; Parquet remains the contract with an explicit typed JSONL.zst fallback.
9. **Separate from live risk service** — No shared plan advancement; no live Redis/supervisor coupling.

---

## 16. Resolved decisions (2026-09-06)

1. **Trade IDs are source-scoped.** Golden fixtures use `/Users/ericwais1/Downloads/10058_full_09_05.csv` (copied to `tests/fixtures/cycle_recon/10058_full_09_05.csv`). Identity = `source_namespace|id=…|ticker=…|sha=…`. Do not bind to unrelated May rows in local DB that share numeric IDs.
2. **Sep archives:** selective copy from mounted Drive  
   `…/GoogleDrive-eric@rec-io.com/My Drive/DATA/HISTORICAL_DATA/BACKTESTING_DATA/`  
   into local `backend/data/historical_data/backtesting_data/` (read-only Drive; local cache writes only).
3. **Parquet:** `pyarrow` installed in checkout `.venv` only; listed in `requirements-dev.txt`. JSONL.zst/JSONL fallback remains.
4. **Postgres trade log is the default.** `--user-no` / session tenant; CSV `--trade-log` is optional override. `--trade-id` without CSV resolves against PG.
5. **UI filters:** range presets (24h / 7d / 30d / all), symbol checkboxes, ticker picker; Eastern times → UTC in backend.

## 17. Launch (local only)

```bash
# CLI — Postgres trade log (default)
PYTHONPATH=. .venv/bin/python scripts/cycle_recon/reconstruct.py \
  --user-no 0001 --range 7d --symbol BTC --offline --workers 1

# CLI — CSV fixture override
PYTHONPATH=. .venv/bin/python scripts/cycle_recon/reconstruct.py \
  --trade-log tests/fixtures/cycle_recon/10058_full_09_05.csv \
  --trade-id 55286 --trade-id 55388 \
  --workers 1 \
  --output-dir backend/data/historical_data/cycle_recon_runs

# Offline / ticker-only
PYTHONPATH=. .venv/bin/python scripts/cycle_recon/reconstruct.py \
  --ticker KXBTC15M-26SEP051130-30 --offline --no-pg --workers 1
```

**Main desktop UI (preferred):** with local `main_app` running, open `/app` as `master_admin` → sidebar **Backtester**. Catalog: `GET /api/cycle_recon/trade_catalog`. Jobs accept Eastern `start_et`/`end_et` or `range_preset`. Hard-disabled when `REC_ENVIRONMENT=production`.

**Optional standalone prototype:** `scripts/cycle_recon/ui_server.py` on `127.0.0.1:8765` (no session auth; prefer main UI).

Outputs: `backend/data/historical_data/cycle_recon_runs/{run_id}/`  
API cache: `backend/data/historical_data/cycle_recon_cache/kalshi_trades/`

## 18. Acceptance observations (local, 2026-09-06; corrected v2)

| Run | Markets | Status notes | Wall | Peak RSS | Path |
|-----|---------|--------------|------|----------|------|
| `accept_hws_55286_55388_v2` | 2 | COMPLETE; no-lookahead; trailing public windows | ~305s | ~517 MB | `…/cycle_recon_runs/accept_hws_55286_55388_v2` |
| `accept_sep5_gap_0400_v2` | 1 | DEGRADED: TIMESTAMP_GAP 18.96s + 12.89s; CROSSED_BOOK; NEGATIVE_DEPTH | ~158s | ~442 MB | `…/cycle_recon_runs/accept_sep5_gap_0400_v2` |
| `accept_sep5_multi_2h_v2` | 8 | COMPLETE; streaming parquet (pre-touch-opt) | ~1161s | ~557 MB | `…/cycle_recon_runs/accept_sep5_multi_2h_v2` |
| `accept_sep6_clean_v2` | 2 | COMPLETE; 0 TIMESTAMP_GAP intervals | ~312s | ~459 MB | `…/cycle_recon_runs/accept_sep6_clean_v2` |
| `accept_offline_cache_hit_v2` | 1 | COMPLETE; `cache_hit=true`; network monkeypatch = 0 calls; cache `sha256` matches | ~19s | — | `…/cycle_recon_runs/accept_offline_cache_hit_v2` |
| `smoke_55388_fix2` / UI jobs | 1 | COMPLETE; localhost UI submit/download OK | — | — | `127.0.0.1:8765` |

**Correctness (v2):** lifecycle `book_timestamp_utc <= timestamp_utc`; scalar `best_bid` / `best_ask` (`yes_ask`); decision-time `public_trade_windows` strictly trailing `[obs-window, obs]` (1/3/5/10/30/60s); `post_event_*` separate; `DELTA_DUPLICATE` only on repeated source `seq`; successful RESYNC does not alone degrade; `initial_book_snapshots` exports ladder levels.

**Resource note:** streaming ParquetWriter keeps multi-market peak RSS **under 2 GB** (~557 MB for 8 markets / ~1.95M events). Wall time was reconstruct-bound; lightweight touch cut per-market reconstruct ~10× (see §12).

**Atomicity check:** mid-run `{run_id}.partial/.incomplete` present; on success partial removed, final dir has no `.incomplete`.

**UI:** Main desktop tab **Backtester** hosts cycle reconstruction (`/tabs/backtester.html` + `/api/cycle_recon/*`); `master_admin` for API; production-disabled. Standalone `8765` prototype remains optional.

## 19. Delivery / stop condition

Complete when CLI + package contract + acceptance packages + localhost UI work locally and match this doc. No production deploy.
