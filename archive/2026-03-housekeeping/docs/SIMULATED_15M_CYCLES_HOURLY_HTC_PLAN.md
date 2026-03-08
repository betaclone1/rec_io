# Simulated 15-Minute Cycles for Hourly HTC — Technical Plan

**Status:** Phase 1 data collection in production; calibration (S, health tiers, sim_cycles) not yet implemented.  
**Scope:** All hourly monitors with auto_trade=TRUE (excluding Momentum Breakout/Contain for now). Uses existing 15m infrastructure applied to the **hourly** strike table with 15m TTC/probability; simulated trades stored in `users.trades_simulated_0001` only.

---

## Progress (as of 2026-03)

| Area | Status | Notes |
|------|--------|--------|
| **Strike table renames & 15m columns** | ✅ Done | Hourly: `ttc_hourly`, `probability_hourly`, `ttc_15m`, `probability_15m`. 15m tables: same column set; legacy `ttc_seconds`/`probability` removed. |
| **users.trades_simulated_0001** | ✅ Done | Created; mirrors trades_0001. Simulated path writes here only; `paper_trade=TRUE`, `test_filter=FALSE`. `date`/`time`/`closed_at` TEXT; `weekly_cycle` NUMERIC(5,1) with decimal per 15m window. |
| **weekly_cycle decimal** | ✅ Done | Hourly = `.4`; 15m = `.0`/`.1`/`.2`/`.3` from contract minutes. Simulated contract uses next 15m boundary (e.g. BTC 2:15pm) so decimal is correct. |
| **Auto-entry simulated path** | ✅ Done | Runs for all hourly + auto_trade=TRUE (excl. Momentum Breakout/Contain). Uses `ttc_15m`/`probability_15m` from hourly table; same TTC window as live. No price/diff/momentum gates. **Spike detection is ignored for placement** (we place simulated trades regardless of spike/cooldown), but **`cooldown_timer` is recorded** on every simulated trade so we can categorize by spike vs normal for SHS/loss prevention (see §4.5). |
| **Trade_manager simulated expiration** | ✅ Done | `check_expired_simulated_trades()` every 15m. Closes open rows in trades_simulated_0001; sets `symbol_close` from live price log, `win_loss` from strike vs close; `sell_price`/`price_spread` NULL; `cycle_win_loss` per 15m window (L if any loss in that monitor/date/weekly_cycle, else W). |
| **cycle_win_streak (monitor_list)** | ⬜ Not done | Doc section 8.2 / 6.3. Not in scope for current production run. |
| **cycle_win_streak_at_entry (trades)** | ⬜ Not done | Doc section 8.3 / 6.4. Not implemented. |
| **sim_cycles, S, health tiers** | ⬜ Not done | Section 10. Calibration table and rolling S/tier computation deferred. |
| **ATS monitoring of simulated** | N/A | Simulated trades live only in trades_simulated_0001; resolution is trade_manager-only (no ATS involvement). |

---

## 1. Goal

- **Problem:** Hourly HTC only trades in a narrow TTC band (e.g. 15:00–2:00 TTC). The rest of the hour, scripts keep scanning hourly markets but that data is unused.
- **Idea:** During that “downtime,” run **simulated** 15-minute “cycles” on the **full hourly strike spectrum** (same strikes, same probability engine, but 15m TTC). No real money; no price/differential gates. Record outcomes (W/L) and maintain a **cycle_win_streak** per monitor.
- **Purpose:**
  - **Early warning:** Simulated cycle losses (or dropping win rate) outside the live window may flag regime shift or probability engine breakdown before real money is at risk.
  - **Future:** May replace or complement current win-streak loss prevention; eventually could drive defensive position sizing.
- **Phase 1:** Only **collect** data: maintain `cycle_win_streak`, write it onto every trade (real and simulated). No trading logic reads it yet.

---

## 2. Current State (Relevant Pieces)

| Component | Relevant behavior |
|-----------|-------------------|
| **Hourly strike table** | `live_data.strike_table_hourly_{symbol}`. Columns include `ttc_seconds` (to next full hour), `probability` (from lookup using that TTC). One row per strike tier. |
| **Strike table generator (hourly)** | Updates `ttc_seconds` and `probability` on a loop (e.g. every second). `calculate_ttc_seconds()` returns seconds to next hour boundary. |
| **Auto_entry_supervisor (Hourly HTC)** | Reads strike table; only enters when TTC in user-defined window (e.g. 15:00–2:00), and when probability/diff/price gates pass. |
| **Active_trade_supervisor** | Monitors open trades; applies auto-stop (probability threshold, etc.); triggers close via trade_manager. |
| **Trade_manager** | `check_expired_trades()` runs every 15m (cron `*/15`). Resolves real 15m market trades (strategies containing `"15m"`) at :00, :15, :30, :45. Inserts set `paper_trade`, `test_filter` for paper/test trades. |
| **Monitor list** | `users.monitor_list_{user_number}` has `win_streak`, `win_streak_threshold`. No `cycle_win_streak` yet. |
| **Trades table** | `users.trades_0001` has `paper_trade`, `test_filter`, `cycle_win_loss`, etc. No `cycle_win_streak_at_entry` (or similar) yet. |

---

## 3. Strike Table Changes (Hourly Only) ✅ Done

**Tables affected:** `live_data.strike_table_hourly_btc`, `live_data.strike_table_hourly_eth`, etc. **Not** 15m strike tables.

### 3.1 Column renames (existing behavior preserved)

| Current name   | New name         | Notes |
|----------------|------------------|--------|
| `ttc_seconds`  | `ttc_hourly`     | Seconds to next **hour** boundary. All existing readers must be updated. |
| `probability`  | `probability_hourly` | From existing lookup using `ttc_hourly`. All existing readers must be updated. |

**Consumers to update:** strike_table_generator (hourly), active_trade_supervisor, auto_entry_supervisor, main.py (API that serves strike table), frontend (if it displays these), any analytics or other readers. Search for `ttc_seconds` and `probability` in the context of **hourly** strike tables only.

### 3.2 New columns (implemented as `ttc_15m`, `probability_15m`)

| Column             | Type    | Description |
|--------------------|---------|-------------|
| `ttc_15m`          | INTEGER | Seconds to next **15-minute** boundary (:00, :15, :30, :45) in EST. (Doc originally said `ttc_seconds_15m`; code uses `ttc_15m`.) |
| `probability_15m`  | DECIMAL | Same probability lookup as hourly, but using `ttc_15m` and same buffers. |

### 3.3 Computation

- **ttc_seconds_15m:** In EST, current time → next boundary in { :00, :15, :30, :45 }.  
  Example: 14:07:30 → next boundary 14:15:00 → `ttc_seconds_15m = 7*60 + 30 = 450`.  
  Same timezone (EST) as existing `ttc_seconds_1h`.
- **probability_15m:** Reuse existing `get_probability(ttc_seconds, buffer_points, momentum_bucket)` (or equivalent) with `ttc_seconds_15m` and same buffer/momentum. One extra lookup per row per update cycle.

### 3.4 Strike table generator (hourly)

- In `generate_strike_table()` (or equivalent), after computing `ttc_seconds` to next hour:
  - Compute `ttc_seconds_15m` to next 15m boundary.
  - Call probability lookup with `ttc_seconds_15m` → `probability_15m`.
- Write both 1h and 15m columns. Existing 1h logic continues to drive real trading; 15m columns are for simulated path only.
- **15m strike tables:** No change (they keep single strike, their own TTC; this feature does not touch them).

---

## 4. Auto-Entry Supervisor (Hourly HTC) — Simulated Path ✅ Done

### 4.1 When it runs

- **Option A:** Only when **outside** the real trading window (e.g. TTC not in [user min, user max] for 1h). So “downtime” is used for simulation.
- **Option B:** Separate loop or flag that runs in parallel; real path and simulated path both evaluate, but only real path can insert non–test_filter trades.
- Recommendation: Option A to avoid duplicate “would we enter?” logic and keep one clear mode per tick.

### 4.2 What it evaluates

- **Reads:** `probability_15m`, `ttc_seconds_15m` from the **hourly** strike table (same table as real path, different columns).
- **Uses:** Same entry thresholds (e.g. min probability, verification period, etc.) and same “no double up on strike” rule as real Hourly HTC. **Does not** use:
  - Price / differential gates.
  - Any real-money checks.
- **Inserts:** Same `insert_trade` path (e.g. via trade_manager POST /trades) with:
  - `paper_trade = TRUE`
  - `test_filter = TRUE`
  - No PnL/return calculations; those fields can stay NULL or 0.
  - Contract: can reuse same contract label as the current hour (e.g. “BTC 2pm”) plus a way to mark the 15m “slice” if needed for expiration (e.g. store 15m boundary time or rely on `created_at` + strategy/tag).

### 4.3 Identifying simulated trades downstream

- All such trades have `paper_trade = TRUE` and `test_filter = TRUE`.
- Optional: add a column or strategy suffix (e.g. `trade_strategy = 'Hourly HTC (simulated 15m)'`) so trade_manager and reporting can filter without relying only on flags.

### 4.4 cycle_win_streak at insert

- On **every** trade insert (real or simulated) for this monitor, read current `cycle_win_streak` from `users.monitor_list_{user_number}` and set on the trade row (e.g. `cycle_win_streak_at_entry`). So every trade carries a snapshot of the streak at entry for later analysis.

### 4.5 Spike detection ignored for placement; cooldown_timer recorded for categorization

- **Placement:** We deliberately **do not** use spike/cooldown logic to gate simulated trade placement. Simulated trades are placed whenever TTC/probability and “no double up” allow it, so we collect as much data as possible.
- **Recording:** We **do** record `cooldown_timer` from the monitor on every simulated trade insert (same value that would apply to live trading at that moment).
- **Purpose:** This allows downstream analysis and Strategy Health Score (SHS) work to split simulated trades into:
  - **Momentum spike condition:** `cooldown_timer > 0` (trade placed during or shortly after a detected spike).
  - **Normal condition:** `cooldown_timer` null or ≤ 0 (no active cooldown).
- That split is important for data analysis, loss-prevention tuning, and position-sizing logic based on simulated outcomes: we can compare calibration and win rates in “spike” vs “normal” regimes and feed that into SHS and future integration.

---

## 5. Active Trade Supervisor — Simulated Trades (N/A — resolution in trade_manager only)

### 5.1 Inclusion

- ATS already loads “active” trades from the monitor’s active_trades table. Simulated trades will be added there by the same flow as real trades (trade_manager inserts, notifies ATS). So ATS will see them as active trades.

### 5.2 Monitoring and stop logic

- **Siloed logic:** For trades with `test_filter = TRUE` (and optionally `paper_trade = TRUE`), use **15m** data for monitoring:
  - Current closing price: from same Kalshi snapshot (hourly table is fine; the contract is still the hourly contract for that hour).
  - Probability: use `probability_15m` from strike table (or equivalent 15m TTC lookup).
  - Apply same auto-stop rules (e.g. probability below threshold for X seconds) but with 15m values.
- **Resolution:** Either ATS sends a “close” at the 15m boundary, or (simpler) **trade_manager** resolves all simulated trades at 15m expiration in one place (see below). Prefer trade_manager so “end of 15m cycle” is defined once.

### 5.3 No real executor

- Simulated trades never hit the real executor; they are “closed” by trade_manager at the 15m boundary by setting status and outcome (W/L) from price at boundary.

---

## 6. Trade Manager ✅ Done

### 6.1 15-minute expiration (existing)

- Already runs at :00, :15, :30, :45 (EST). Handles real 15m market trades (e.g. `trade_strategy` containing `"15m"`).

### 6.2 Extension: resolve simulated 15m cycles

- In the same 15m run (or immediately after), select open trades that are **simulated** (e.g. `paper_trade = TRUE` and `test_filter = TRUE`, and optionally strategy/tag indicating “simulated 15m”).
- For each such trade that belongs to the **current** 15m boundary (e.g. created in the last 15m window, or explicitly tagged with cycle end time):
  - Set `status = 'closed'`.
  - Set closing price from 1m avg (or same source as real 15m) at that boundary.
  - Set `win_loss` = 'W' or 'L' from strike vs closing price (same rule as real trades: YES above strike = W, etc.).
  - Do **not** need real PnL/returns; can set to 0 or NULL.

### 6.3 Cycle win streak update (after resolving simulated trades) ⬜ Not done

- After resolving all simulated trades for the current 15m boundary:
  - Group by monitor (e.g. `monitor` in trades).
  - For each monitor that had **at least one** simulated trade in this cycle:
    - If **any** of those trades has `win_loss = 'L'` → set `cycle_win_streak = 0` in `users.monitor_list_{user_number}`.
    - If **all** are wins → increment `cycle_win_streak` by 1 (or by number of winning trades, per product decision; document in “Cycle win streak rules” below).
  - For monitors with **zero** simulated trades in this cycle → **no change** to `cycle_win_streak`. (Zero trades = no effect; we only care about recorded losses.)

### 6.4 cycle_win_streak on insert ⬜ Not done

- In `insert_trade()` (and any other code path that creates a trade for a monitor), before INSERT:
  - Resolve monitor key → `users.monitor_list_{user_number}` and monitor id.
  - Read current `cycle_win_streak` for that monitor.
  - Include it in the INSERT (e.g. column `cycle_win_streak_at_entry` or `cycle_win_streak`). So every trade (real and simulated) carries the streak at entry.

---

## 7. Cycle Win Streak — Rules (Authoritative)

| Situation | Effect on `cycle_win_streak` |
|-----------|------------------------------|
| 15m cycle has **no** simulated trades | No change. |
| 15m cycle has ≥1 simulated trade, **all** wins | Increment by 1 (or by agreed amount). |
| 15m cycle has ≥1 simulated trade, **at least one** loss | Reset to 0. |

So: **zero trades in a cycle = no effect**. The streak is about **recorded losses**, not “no signal.”

---

## 8. Schema Additions

### 8.1 Hourly strike tables (live_data) ✅ Done

- Rename: `ttc_seconds` → `ttc_hourly`, `probability` → `probability_hourly`.
- Add (for simulated 15m cycles): `ttc_15m` INTEGER, `probability_15m` DECIMAL(5,2).

### 8.1a 15m strike tables (live_data) ✅ Done

- Tables: `live_data.strike_table_15m_btc`, `live_data.strike_table_15m_eth`.
- Columns (synced with hourly):
  - Same column set as hourly: `ttc_hourly`, `probability_hourly`, `ttc_15m`, `probability_15m`. Legacy `ttc_seconds` and `probability` have been removed from 15m tables.
  - For 15m tables: `ttc_hourly` and `probability_hourly` are NULL; `ttc_15m` and `probability_15m` hold the values used for 15m markets. All readers for 15m use `ttc_15m` / `probability_15m`.
- Rationale: hourly and 15m strike tables share one schema; 15m assets use `ttc_15m` and `probability_15m` only.

### 8.2 Monitor list (users.monitor_list_*) ⬜ Not done

- Add: `cycle_win_streak` INTEGER DEFAULT 0.  
  Stored alongside existing `win_streak` / `win_streak_threshold`. No UI or logic required to change it in phase 1 except write from trade_manager.

### 8.3 Trades (users.trades_0001)

- Add: `cycle_win_streak_at_entry` INTEGER (nullable).  
  Set on every insert (real and simulated) to the monitor’s current `cycle_win_streak`. For analysis only in phase 1.

---

## 9. Data Flow Summary

**Current (implemented):**

1. **Strike table (hourly):** Generator writes `ttc_hourly`, `probability_hourly`, `ttc_15m`, `probability_15m`.
2. **Auto_entry:** Every cycle for hourly + auto_trade (excl. Momentum Breakout/Contain), evaluates `ttc_15m`/`probability_15m` in same TTC window as live; inserts to trade_manager → `users.trades_simulated_0001` with `paper_trade=TRUE`, `test_filter=FALSE`; contract = next 15m boundary for `weekly_cycle` decimal.
3. **ATS:** Does not see simulated trades; they live only in trades_simulated_0001.
4. **Trade_manager (15m run):** Runs `check_expired_simulated_trades()` first; closes open simulated rows, sets `symbol_close`/`win_loss`/`cycle_win_loss` per 15m window. Then runs existing live expiration. No `cycle_win_streak` update on monitor_list yet.
5. **cycle_win_streak / cycle_win_streak_at_entry:** Not implemented.

---

## 10. Calibration & Health Telemetry (sim_cycles + S) ⬜ Not done

**Purpose:** Attach a minimal, deterministic calibration and health layer to the simulated 15-minute cycles. This layer answers: **“Are ≥95% probability outputs behaving like ≥95% in current conditions?”** It is calibration infrastructure only, not a live trading or PnL engine.

**Monitor-specific:** Calibration (S), health tier, and any downstream use (loss prevention, position sizing) are **computed per monitor only**. Simulated trade criteria (symbol, TTC window, strategy, thresholds) come from each monitor; what happens on an ETH hourly monitor has no impact on a BTC monitor. Rolling windows, S, and tier are always scoped to a single `monitor` (e.g. `monitor` in `trades_simulated_0001`). No cross-monitor aggregation.

### 10.1 Deterministic 15-minute cycle engine (calibration view)

- The hour is divided into four fixed 15-minute blocks (EST): `:00–:15`, `:15–:30`, `:30–:45`, `:45–:00`.
- For each block and symbol/strategy:
  - Define a **synthetic TTC** = minutes (seconds) remaining in that block.
  - Use the **same strike selection + probability lookup logic** as the live Hourly HTC strategy, but evaluated on `ttc_seconds_15m` / `probability_15m`.
  - Apply a **≥95% probability gate** (or higher, per configuration) when deciding whether a simulated trade “would be executed” in that block.
  - Use **symbol-only price inputs** and existing OHLC sources; no randomness is permitted anywhere in this path.
- Historical replay of this simulator over stored OHLC data must be **reproducible** (same inputs → same outputs).

This simulator is conceptually the same engine that produces the simulated trades in sections 4–6; this section defines its **calibration contract** and the telemetry we must persist.

### 10.2 sim_cycles table (calibration telemetry)

A dedicated table (e.g. `analytics.sim_cycles`) records one row per **15m block × symbol × strategy_name** where the simulator runs. Fields (names may be adapted to match `MASTER_DB_SCHEMA_REFERENCE`, but semantics are fixed):

- **Identifiers**
  - `id` (PK)
  - `cycle_start_timestamp`
  - `cycle_end_timestamp`
  - `bucket` (ENUM or SMALLINT: 0, 15, 30, 45)
  - `symbol`
  - `strategy_name`
- **Probability snapshot**
  - `selected_direction` (e.g. YES/NO or call/put)
  - `selected_strike`
  - `synthetic_ttc` (seconds remaining in the 15m block)
  - `predicted_probability` (`p`)
  - `ttc_bin`
  - `buffer_bin`
  - `momentum_bin`
  - `top_probability_available` (highest `p` among candidates)
  - `num_candidates_above_95`
  - `trade_executed` (BOOLEAN; whether a simulated trade was “taken” in this cycle under the ≥95% rule)
- **Outcome**
  - `outcome` (1 = win, 0 = loss, NULL if `trade_executed = FALSE`)
  - `realized_close_price`
  - `realized_move_distance_from_strike`
- **Context (optional in v1 implementation, but schema reserved)**
  - `volatility_metric`, `volatility_percentile`, `volatility_flag`
  - `movement_metric`, `movement_percentile`
  - `momentum_metric`, `momentum_percentile`

This table is **separate from** `users.trades_*`. The `trades_*` tables remain the authoritative source for trade-level telemetry; `sim_cycles` is the authoritative source for calibration analysis and health tiers.

### 10.3 Core calibration statistic S (rolling window)

**Per monitor:** The rolling window and S are computed **per monitor**. Use only that monitor's simulated trades (e.g. `WHERE monitor = %s` in `trades_simulated_0001`). ETH monitor S is independent of BTC monitor S.

On a rolling window of the last **N** simulated trades with `trade_executed = TRUE` **for that monitor** (recommendation: `N ≥ 30`, never below 20):

- Let `p_i` be `predicted_probability` for trade `i`.
- Let `y_i` be the binary outcome (`1` = win, `0` = loss) for trade `i`.
- **Expected losses:**  
  \[ E = \sum (1 - p_i) \]
- **Observed losses:**  
  \[ L = \sum (1 - y_i) \]
- **Variance:**  
  \[ V = \sum p_i (1 - p_i) \]
- **Calibration statistic:**  
  \[ S = \frac{L - E}{\sqrt{V}} \]

Interpretation:

- `S ≈ 0` → calibrated (observed loss rate matches expectation).
- `S ≥ 2` → material deviation.
- `S ≥ 3` → strong miscalibration signal.

Implementation notes:

- `S` is computed over simulated trades only; real trades never enter this statistic directly.
- `NO_TRADE` cycles (`trade_executed = FALSE`) are not included in the rolling window for `S`, but they are still recorded in `sim_cycles` for completeness.
- Rolling window size, bucketization of `p` (if any), and update cadence (per 15m, hourly, or fixed N trades) are configuration choices; this doc requires only that the window is **never shorter than 20 trades** in production.

### 10.4 Health tier mapping (Tiers 1–5)

A **health tier** is derived deterministically from the current `S` and a small set of hard alarms:

- Tier 5: `S ≤ 0.5`
- Tier 4: `0.5 < S ≤ 1.5`
- Tier 3: `1.5 < S ≤ 2.5`
- Tier 2: `2.5 < S ≤ 3.5`
- Tier 1: `S > 3.5` **OR** a hard alarm is triggered.

Example hard alarm (v1):

- Two consecutive simulated losses where `predicted_probability ≥ 0.98`.

Health tier output is **read-only in this phase**. It **must not** affect position sizing, pausing, or any live capital allocation decisions until validated offline.

### 10.5 v1 boundaries, red flags, and completion criteria

**In scope (calibration v1):**

- Deterministic 15m simulated cycle engine using hourly strike table (`ttc_seconds_15m`, `probability_15m`).
- Continuous population of `sim_cycles`.
- Rolling computation and storage of `S` and health tier over the last N simulated trades.
- Offline historical calibration audit (replay historical OHLC data, compute `p` and outcomes, compare predicted vs actual win rate per probability bucket).

**Out of scope (calibration v1):**

- LP integration or any order-routing changes.
- Position sizing changes or automated pausing based on `S` or health tier.
- Rolling 1-minute sliding-window simulators (we only support 15m blocks in v1).
- Additional health sub-scores beyond `S` and the tier mapping above.

**Red flags (things we intentionally avoid):**

- Using **raw win rate** as the primary calibration metric instead of `S`.
- Reducing the rolling window below 20 trades.
- Ignoring NO_TRADE cycles entirely (they should exist as rows with `trade_executed = FALSE` in `sim_cycles` even if excluded from `S`).
- Assuming independence between adjacent cycles in any statistical claims.

**v1 calibration “done” when:**

1. Deterministic simulator is operational over live and historical data.
2. `sim_cycles` is populated continuously in live operation.
3. Calibration statistic `S` is computed, stored, and queryable over a rolling window.
4. Health tier (1–5) is computed and stored historically.
5. Offline historical calibration audit is completed and documented.
6. No LP or position sizing integration with `S`/tier exists.

---

## 11. What Does Not Change (Phase 1)

- Real Hourly HTC entry/exit logic (still uses 1h TTC and 1h probability).
- Real 15m market trading (separate tables and strategies).
- Executor or Kalshi order flow for real trades.
- Any logic that **reads** `cycle_win_streak`, `cycle_win_streak_at_entry`, `S`, or health tier to alter sizing, pausing, or loss prevention. Phase 1 is data collection and calibration telemetry only.

---

## 12. Edge Cases and Notes

- **Strike table reader compatibility:** Renaming `ttc_seconds` → `ttc_seconds_1h` and `probability` → `probability_1h` is a breaking change for every reader of hourly strike tables. Must audit and update all references in one pass (strike_table_generator, main.py, ATS, auto_entry, frontend, etc.).
- **15m strike tables:** Unchanged; they keep `ttc_seconds` and `probability` as-is (no _1h/_15m split there).
- **Multiple Hourly HTC monitors:** Each has its own `cycle_win_streak`; simulated trades are per monitor.
- **Overlap with real window:** When TTC re-enters the real trading window, real path takes over; simulated path can stop evaluating for that monitor until next “downtime.”
- **Cycle boundary alignment:** Simulated “cycle” = one 15m window. Resolution time = boundary (:00, :15, :30, :45). Ensure trades are attributed to the correct cycle (e.g. by `created_at` or by storing cycle_end_time on the trade).

---

## 13. Implementation Order (Suggested)

**Done:** 1 (strike columns + trades_simulated_0001; renames done), 2 (generator writes ttc_15m/probability_15m), 3 (trade_manager resolves simulated; no cycle_win_streak yet), 4 (auto_entry simulated path), 5 (resolution in trade_manager only; ATS not involved), 7 (columns renamed to ttc_hourly/probability_hourly; 15m use ttc_15m/probability_15m).

**Remaining:** cycle_win_streak on monitor_list and cycle_win_streak_at_entry on trades (optional for current phase); sim_cycles table and S / health tier (Section 10); historical calibration audit.

---

## 14. References

- Conversation: simulated 15m cycles on hourly strikes; cycle_win_streak; no effect from zero trades; record streak on every trade for analysis.
- Existing: `docs/CYCLE_METRICS_IMPLEMENTATION_PLAN.md` (cycle metrics for real trades); `docs/WIN_STREAK_THRESHOLD_FEATURE.md` (win_streak on monitor_list); trade_manager `check_expired_trades()` and 15m expiration logic; strike_table_generator hourly vs 15m tables.
- PM spec: `REC_IO_Strategy_Calibration_Health_Cursor_Spec_v4` (deterministic simulator, `sim_cycles` schema, calibration statistic `S`, health tiers 1–5, v1 scope and red flags).
