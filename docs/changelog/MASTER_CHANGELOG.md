# Master Changelog

This changelog is used when pushing updates to production. Each entry is timestamped and includes a summary plus any instructions for the production server agent (DB schema steps, scripts to run, restart order, etc.).

**Workflow:** Merge feature branch to `main`, sync repo on production, then have the production agent read the latest entry, work through the checklist (checking off each task), and restart services when all boxes are complete.

---

## Entry format

Each entry below uses:

- **Date** – When the update is intended for production (YYYY-MM-DD).
- **Summary** – What the release contains.
- **Production agent checklist** – A list of tasks with checkboxes (`- [ ]`). The production agent physically checks these off as each is completed. Every entry has at least a minimal checklist (e.g. "Confirm codebase changes", "Update local database" if applicable). Details or commands for a task can appear under the checklist or inline in the task text.

---

## 2026-03-07 — Simulated trade duplicate fix, dedupe script (util), one-time DB cleanup

**Summary**

- **Simulated trade duplicate prevention:** Auto-entry supervisor and trade_manager now use the same server-agnostic DB connection (`backend.core.config.database.get_postgresql_connection`) for simulated trades. `is_strike_already_simulated_traded` in AES no longer uses a separate `POSTGRES_*` connection; it uses the shared config (DB_* / REC_DB_*) so the duplicate check sees the same rows that trade_manager writes. This prevents new duplicates. Trade_manager's local hardcoded `get_postgresql_connection` was removed in favor of the centralized one.
- **Dedupe script (one-time):** `backend/util/dedupe_simulated_trades.py` removes duplicate rows in `users.trades_simulated_0001` that accumulated before the connection fix. The script is **one-time only**; duplicate prevention is now in-app. It is documented as too aggressive (it deduped by date+contract only); if a future one-off dedupe is ever needed, use (date, contract, strike, side) and keep min(id) per group.
- **No code changes to live/paper trading;** only simulated path and shared DB usage.

**Production agent checklist**

- [ ] Confirm codebase changes (pull latest `main` on production).
- [ ] Update local database: run from project root  
  `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()"`  
  if any schema migrations are pending.
- [ ] **One-time dedupe of simulated trades table (after restart):** From project root, run once:  
  `PYTHONPATH=$(pwd) venv/bin/python -m backend.util.dedupe_simulated_trades`  
  This removes duplicate rows in `users.trades_simulated_0001` that may exist from before the connection fix. If the script reports "No duplicate rows (by date, contract) found.", no action needed. Do not run the dedupe repeatedly.
- [ ] Restart application services (main_app, strike_table_generator, trade_manager, active_trade_supervisor, auto_entry_supervisor as applicable).
- [ ] Confirm: no errors in logs after restart; simulated trades no longer double up on the same strike per cycle.

---

## 2026-03-05 — Simulated 15m trade system (production)

**Summary**

- **Simulated 15m trades on hourly markets:** `auto_entry_supervisor` now runs a simulated 15m entry path for all hourly monitors with `auto_trade=TRUE`, excluding Momentum Breakout/Contain (for testing). It reuses each monitor’s existing `min_time` / `max_time` window and reads `ttc_15m` / `probability_15m` from the hourly strike tables. Simulated trades ignore price/diff/volume/momentum spike rules, are always `paper_trade = TRUE` / `test_filter = FALSE`, and never call the executor or send real orders.
- **Contract + weekly_cycle per 15m window:** Simulated trades use contract labels at the *next* 15-minute boundary (e.g. `BTC 2:15pm`, `BTC 2:30pm`), so `trade_manager` can derive `hour_idx` and `weekly_cycle` with the correct decimal (.0 / .1 / .2 / .3) via the existing contract parsing logic. This ensures every simulated trade is tagged to the correct 15m window for later calibration.
- **15m expiration + symbol-close settlement (simulated):** `trade_manager`’s 15-minute expiration job now always calls `check_expired_simulated_trades()` at :00/:15/:30/:45, regardless of whether there are live trades. This function closes *only* `users.trades_simulated_0001` rows (no impact on `trades_0001`), using the latest `one_minute_avg` (or `price` fallback) from `live_data.live_price_log_1s_{symbol}` as `symbol_close` and setting `status = 'closed'`, `close_method = 'expired'`, and `win_loss` based on a YES/NO vs strike comparison. `sell_price` is recorded as `NULL` for simulated trades.
- **Simulated cycle_win_loss per 15m window:** For each 15m window (grouped by `monitor`, `date`, `weekly_cycle`) that has simulated trades closed in a given expiration run, `trade_manager` sets `cycle_win_loss` on `users.trades_simulated_0001` to `L` if **any** trade in that window is a loss, otherwise `W`. This gives a single, conservative win/loss flag per monitor per 15m cycle for downstream Strategy Health Score (SHS) work.
- **DB schema + load characteristics:** No new columns were added for this feature; it relies on the existing `users.trades_simulated_0001` schema (including `weekly_cycle NUMERIC(5,1)`, `cycle_win_loss`, `cycle_pnl`, `cycle_ret_pct`) and the `live_data.live_price_log_1s_{symbol}` tables. `insert_simulated_trade` explicitly records `diff`, `buy_price`, `position`, `fees`, `bankroll`, `price_spread`, and `sell_price` as `NULL` and touches only `users.trades_simulated_0001`. The system leverages existing CPU-intensive processes (strike generators, price logs, auto-entry loops); the new work is limited to light `SELECT` / `INSERT` / `UPDATE` statements and does not introduce new schedulers or external API calls.

**Production agent checklist**

- [x] Confirm codebase changes (pull latest `main` on production).
- [x] Update local database schema to latest (id sequences, PKs, numeric weekly_cycle, simulated table shape) by running from project root:
  - `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config/database import init_database; init_database()"`
  - This ensures `users.trades_simulated_0001` exists with a working `id` sequence / primary key and matches the definition in `docs/MASTER_DB_SCHEMA_REFERENCE.md` (including `weekly_cycle NUMERIC(5,1)`, `cycle_win_loss`, `cycle_pnl`, `cycle_ret_pct`, and boolean flags).
- [x] Restart application services in the standard order (or run `scripts/MASTER_RESTART.sh`): at minimum `main_app`, `trade_manager`, `monitor_manager` (which runs `auto_entry_supervisor` / `active_trade_supervisor`), and strike table / price watchdog services.
- [x] Verify simulated trades path:
  - Confirm `users.trades_simulated_0001` is receiving new rows for hourly monitors with `auto_trade=TRUE` (excluding Momentum Breakout / Momentum Contain), with `position`, `fees`, `bankroll`, `price_spread`, and `sell_price` recorded as `NULL`.
  - After at least one 15m boundary, confirm those simulated trades transition to `status='closed'` with `symbol_close` populated and `win_loss` correctly reflecting YES/NO vs strike.
  - For a given monitor/date/`weekly_cycle`, confirm all simulated trades share the same `cycle_win_loss` (`L` if any loss in that 15m window, otherwise `W`).
- [x] Verify no impact to live trading:
  - Confirm `users.trades_0001` behavior is unchanged (entries, expirations, cycle metrics, and pnl/ret_pct), and that real orders are still executed only from live paths.
  - Scan logs for `AUTO ENTRY`, `TRADE MANAGER`, and `SIMULATED 15m` messages to ensure there are no new errors or unexpected restarts.

---

## 2026-03-03 — Strike table alignment, simulated trades table, weekly_cycle 15m decimal

**Summary**

- **Strike tables:** Hourly and 15m strike tables now share the same column set (`ttc_hourly`, `ttc_15m`, `probability_hourly`, `probability_15m`). Legacy columns `ttc_seconds` and `probability` were removed from 15m tables; all 15m readers use `ttc_15m` and `probability_15m`. Hourly tables already used `ttc_hourly` / `probability_hourly`; no change to hourly column names. Strike table generator, main.py, active_trade_supervisor, and auto_entry_supervisor read/write the correct columns per market. See `docs/SIMULATED_15M_CYCLES_HOURLY_HTC_PLAN.md` and `docs/MASTER_DB_SCHEMA_REFERENCE.md`.
- **users.trades_simulated_0001:** New table (duplicate of `trades_0001`) for simulated 15m-cycle trades; documented in MASTER_DB_SCHEMA_REFERENCE. Any future schema changes to `trades_0001` must be applied to `trades_simulated_0001` as well.
- **weekly_cycle decimal:** `users.trades_0001.weekly_cycle` (and `trades_simulated_0001` if present) now stored with one decimal place: hourly trades = `hour.4` (e.g. 64.4 = fourth quarter of the hour); 15m trades = `hour.0 | .1 | .2 | .3` from contract minutes (:00, :15, :30, :45). Column type migrated from INTEGER to `NUMERIC(5,1)`. Cycle performance and monitor_cycle_performance still use the integer part only (`FLOOR(weekly_cycle)`); decimals are for record-keeping and future use.

**Production agent checklist**

- [x] Confirm codebase changes (pull latest `main` on production).
- [x] Update local database: run `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()"` from project root. This applies: (1) drop `ttc_seconds` and `probability` from `live_data.strike_table_15m_btc` and `strike_table_15m_eth` if present; (2) alter `users.trades_0001.weekly_cycle` and `users.trades_simulated_0001.weekly_cycle` (if table exists) from integer to `NUMERIC(5,1)`.
- [x] Restart application services (main_app, strike_table_generator, trade_manager, active_trade_supervisor, auto_entry_supervisor as applicable).
- [x] Confirm: no errors in logs after restart; strike tables and trade monitor UI load correctly; new trades receive `weekly_cycle` with one decimal (e.g. 64.4 for hourly, 64.1 for 2:15pm 15m).

---

## 2025-03-04 — Kalshi fixed-point migration (count / _fp)

**Summary**

- Backend support for Kalshi’s fixed-point migration for contract counts. We now record and use `_fp` fields (e.g. `count_fp`, `remaining_count_fp`, `position_fp`) in addition to legacy integer fields across portfolio sync, trade manager, order submission, and API responses.
- **Recording:** Account sync and historical ingest write all `_fp` columns to `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, `users.settlements_0001` (stored as `NUMERIC(12,2)`).
- **Reading:** Trade manager and main app prefer `_fp` when present (legacy can be NULL once the API deprecates it). Order delta check in sync uses `_fp` for comparison.
- **Outbound:** Order submission sends only `count_fp` to the Kalshi API (legacy `count` no longer sent). Internal callers (main, auto_entry, ATS, frontend) pass `count_fp` through the trade chain.
- If the API stops sending legacy count fields, operations continue unchanged; legacy columns may be NULL for new data. See `docs/FIXED_POINT_LEGACY_DEPRECATION_AUDIT.md` for details.

**Production agent checklist**

- [x] Confirm codebase changes (pull latest `main` on production; or merge feature branch into `main` then pull).
- [x] Update local database: ensure `_fp` columns exist on `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, `users.settlements_0001` per `docs/MASTER_DB_SCHEMA_REFERENCE.md`. Add any missing as `NUMERIC(12,2)` (nullable). Columns: `fills_0001` → `count_fp`; `orders_0001` → `initial_count_fp`, `remaining_count_fp`, `fill_count_fp`; `positions_0001` → `total_traded_fp`, `position_fp`; `settlements_0001` → `yes_count_fp`, `no_count_fp`. Example: `ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS count_fp NUMERIC(12,2);`
- [x] Run historical ingest once to backfill new columns from Kalshi API: `PYTHONPATH=$(pwd) venv/bin/python backend/api/kalshi-api/kalshi_historical_ingest.py` (see schema ref section "4. After updating portfolio-level user tables").
- [x] Restart application services (main_app, trade_manager, trade_executor, kalshi_account_sync, active_trade_supervisor as applicable).
- [x] Confirm: no errors in logs after restart; trading and account sync behave as expected.

---
