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
