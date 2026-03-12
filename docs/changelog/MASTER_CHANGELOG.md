# Master Changelog

This changelog is used when pushing updates to production. Each entry is timestamped and includes a summary plus any instructions for the production server agent (DB schema steps, scripts to run, restart order, etc.).

**Workflow:** Merge feature branch to `main`, sync repo on production, then have the production agent read the latest entry, work through the checklist (checking off each task), and restart services when all boxes are complete.

---

## 2026-03-12 — Kalshi market volume_fp alignment

**Summary**

- Rename Kalshi market volume columns on all live market tables from `volume` / `volume_24h` to `volume_fp` / `volume_24h_fp` to match the Kalshi API’s fixed-point fields.
- Update `kalshi_market_watchdog` to write `volume_fp` and `volume_24h_fp` as integer counts derived from the API’s fixed-point strings (e.g. `"56658.00"` → `56658`), with safe fallbacks.
- Keep strike table schemas unchanged; `strike_table_generator` now reads `volume_fp` / `volume_24h_fp` from `market_kalshi_*` and continues to store them in the existing `volume` column on the strike tables.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Update DB schema on production Kalshi market tables: rename `live_data.market_kalshi_hourly_{btc,eth,ndx,spx}` and `live_data.market_kalshi_15m_{btc,eth}` columns from `volume` → `volume_fp` and `volume_24h` → `volume_24h_fp` using direct DDL (one-time ALTER TABLE per table).
- [x] Run `scripts/MASTER_RESTART.sh` so all Kalshi watchdogs, strike generators, and dependent services load the new code.
- [x] Verify production: health (main_app :3000, trade_executor :8001), supervisor status, and that Kalshi market tables on prod now have `volume_fp` / `volume_24h_fp` columns and are being populated with non-zero values.

---

## 2026-03-11 — Drawdown safety valve and monitor list frontend sync

**Summary**

- **Drawdown safety valve:** When account sync detects a significant drawdown (Master Trading Bankroll ≤ 70% of previous bankroll), it steps down `bankroll_current` and notifies monitor_manager with `bankroll_stepped_down: true`. Monitor_manager then sets all monitors' `auto_trade` to FALSE and `auto_trade_status` to `'off'` so auto entry is halted until the user manually re-enables per monitor.
- **Sync path:** `kalshi_account_sync_ws` sets `bankroll_stepped_down` only in the ratchet step-down branch and passes it in the POST body to `/api/bankroll_updated`. Monitor_manager reads the flag and runs the bulk UPDATE on `users.monitor_list_0001` before recalculating allotments.
- **Frontend notify on every monitor_list change:** Monitor_manager now calls `_notify_frontend_monitor_list_updated()` whenever it changes the monitor list (bankroll update, position variables update, statistics update, create monitor, toggle auto_trade, sync_monitor_processes). The main app broadcasts `monitor_list_updated` so the dashboard runs `loadMonitors()` and refreshes tiles.
- **Dashboard (tabs + mobile) failsafe:** The AUTO TRADE toggle on monitor tiles is updated in the same 30s refresh loop as other tile stats. `updateMonitorStatValues` now syncs the `.auto-trade-toggle` element's `active` class from the API data (`autoTrade` / `auto_trade`), so if a WebSocket update is missed, the next poll corrects the toggle.

No DB schema changes. Backend (kalshi_account_sync_ws, monitor_manager) and frontend (dashboard.html, dashboard_mobile.html) only.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB migrations. Run `scripts/MASTER_RESTART.sh` so kalshi_account_sync and monitor_manager load the new code.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Optionally simulate a drawdown (or wait for one) and confirm dashboard toggles show auto_trade off and refresh when expected.

---

## 2026-03-12 — Kalshi API: fills and settlements _dollars (schema)

**Summary**

- **Fills:** Kalshi API now exposes `yes_price_dollars` and `no_price_dollars`; legacy `yes_price_fixed` / `no_price_fixed` and cent fields deprecated. We removed deprecated columns and added `yes_price_dollars`, `no_price_dollars` to `users.fills_0001`. Sync and ingest read from API _dollars (fallback to _fixed during rollout). Frontend uses the new column names.
- **Settlements:** API exposes `yes_total_cost_dollars` and `no_total_cost_dollars`. We removed `yes_total_cost`, `no_total_cost` and added `yes_total_cost_dollars`, `no_total_cost_dollars` to `users.settlements_0001`. Sync and ingest read _dollars (fallback to cent fields).
- **Schema:** Direct DDL only (no migration files). Reference: `docs/MASTER_DB_SCHEMA_REFERENCE.md`. CREATE TABLEs updated in trade_manager.py, kalshi_account_sync_ws.py, kalshi_historical_ingest.py.

**DB schema change required.** This update requires running DDL on the database. The apply-update process runs the DB step below automatically on the target server as part of the production checklist. Do not skip it; there is no separate manual migration step.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] **DB schema update (required; run automatically as part of this update):** From project root on the target server, run the DDL below. Apply-update executes this step; do not run migrations manually on other servers. Command (idempotent; safe if schema already updated):

  ```bash
  PYTHONPATH=$(pwd) venv/bin/python -c "
  from backend.core.config.database import get_postgresql_connection
  conn = get_postgresql_connection()
  cur = conn.cursor()
  # fills_0001: add new columns
  cur.execute('ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS yes_price_dollars TEXT')
  cur.execute('ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS no_price_dollars TEXT')
  cur.execute(\"SELECT 1 FROM information_schema.columns WHERE table_schema='users' AND table_name='fills_0001' AND column_name='yes_price_fixed'\")
  if cur.fetchone():
      cur.execute(\"UPDATE users.fills_0001 SET yes_price_dollars = yes_price_fixed, no_price_dollars = no_price_fixed WHERE yes_price_fixed IS NOT NULL OR no_price_fixed IS NOT NULL\")
      for col in ('yes_price_fixed', 'no_price_fixed', 'yes_price', 'no_price'):
          cur.execute(\"ALTER TABLE users.fills_0001 DROP COLUMN IF EXISTS \" + col)
  # settlements_0001: add new columns
  cur.execute('ALTER TABLE users.settlements_0001 ADD COLUMN IF NOT EXISTS yes_total_cost_dollars NUMERIC(10,2)')
  cur.execute('ALTER TABLE users.settlements_0001 ADD COLUMN IF NOT EXISTS no_total_cost_dollars NUMERIC(10,2)')
  cur.execute(\"SELECT 1 FROM information_schema.columns WHERE table_schema='users' AND table_name='settlements_0001' AND column_name='yes_total_cost'\")
  if cur.fetchone():
      cur.execute(\"UPDATE users.settlements_0001 SET yes_total_cost_dollars = yes_total_cost, no_total_cost_dollars = no_total_cost WHERE yes_total_cost IS NOT NULL OR no_total_cost IS NOT NULL\")
      cur.execute('ALTER TABLE users.settlements_0001 DROP COLUMN IF EXISTS yes_total_cost')
      cur.execute('ALTER TABLE users.settlements_0001 DROP COLUMN IF EXISTS no_total_cost')
  conn.commit()
  conn.close()
  print('DB schema update done')
  "
  ```

  Then verify schema: `users.fills_0001` has `yes_price_dollars`, `no_price_dollars` and no `yes_price_fixed`, `no_price_fixed`, `yes_price`, `no_price`; `users.settlements_0001` has `yes_total_cost_dollars`, `no_total_cost_dollars` and no `yes_total_cost`, `no_total_cost`.

- [x] Run `scripts/MASTER_RESTART.sh` so kalshi_account_sync and any dependent services load the new code.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status; optionally trigger a fills/settlements sync and confirm no errors in kalshi_account_sync logs.

---

## 2026-03-11 — Dashboard Performance panel and mobile dashboard tweaks

**Summary**

- **Performance panel (desktop + mobile):** Removed the delta/compare column (previous-period change) from the Performance panel; rows now show only label, PnL, and PnL %. Applied a 20px left shift via `transform: translateX(-20px)` on `.performance-periods` so the block is better centered in the panel.
- **Mobile dashboard:** Chart animation disabled so periodic refreshes do not re-animate the line; pull-to-refresh now triggers a full page reload; WebSocket reconnect no longer gated by `DASHBOARD_MOBILE_PAUSED`.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB or backend service changes. Frontend only; no restart required. Optional: hard refresh or clear cache on clients to pick up updated dashboard HTML/CSS.

---

## 2026-03-10 — Trade history mobile: disable contract filter (parity with desktop)

**Summary**

- **Issue:** Mobile trade history showed a subset of trades for the same filter parameters as desktop; e.g. trade 10625 appeared on desktop but not on mobile.
- **Cause:** Desktop has contract filtering disabled in `applyFilters()` (commented out); mobile was still applying `filterTradesByContract()`, which only keeps trades whose contract string matches hourly labels (12am–11pm) and excluded others.
- **Fix:** Disabled contract filter in mobile `applyFilters()` in `frontend/mobile/trade_history_mobile.html` so mobile shows all contracts like desktop. Same effective filters on both: date, win/loss, strategy, symbol, monitor, day, paper/live.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB or backend changes. Frontend only; no restart required. Optional: hard refresh or clear cache on mobile client to pick up updated `trade_history_mobile.html`.

---

## 2026-03-10 — Simulated trade duplicate prevention (AES + trade_manager)

**Summary**

- **Root cause:** AES `is_strike_already_simulated_traded()` only checked open/pending and (monitor, ticker, side). After the 15m expiration job closed a simulated trade, the next scan did not see it and inserted again for the same cycle. trade_manager had no server-side duplicate guard.
- **Fix:** (1) AES: duplicate check now requires date, contract, and strike in strike_data and queries for **any** row (no status filter) with (monitor, date, contract, strike, side). Caller `check_simulated_15m_entry_hourly_htc` passes date_str and contract_name (same as trigger_simulated_trade). (2) trade_manager `insert_simulated_trade`: before INSERT, SELECT for existing (monitor, date, contract, strike, side); if found, return that id and skip insert.
- **No schema or migrations.** See `docs/AUDIT_SIMULATED_TRADE_DUPLICATES.md` for full audit.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB migrations. Run `scripts/MASTER_RESTART.sh` so all auto_entry_supervisor and trade_manager processes load the new logic.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status. Optionally after a few 15m cycles, run duplicate detection on prod (e.g. inline query or script) to confirm no new duplicate groups in `users.trades_simulated_0001`.

---

## 2026-03-10 — Trade history filters and preferences (dynamic Strategy/Symbol, All/None, migrations)

**Summary**

- **Trade history (desktop + mobile):** Strategy and Symbol dropdowns are populated from the database (`strategy_list`, `symbols_list`). Contract, Monitor, and Day dropdowns use **All | None** links instead of a single "Select All" checkbox. Reset sets Strategy to only strategies with `default=TRUE` in `strategy_list`; Symbol and other dropdowns reset to all selected. Preferences persist per-strategy and per-symbol selection via JSONB.
- **Backend:** `/api/strategies` returns `strategies` and `default_strategy_names`. `get_trade_history_preferences` and `save_trade_history_preferences` read/write `strategy_selection` and `symbol_selection` (JSONB); fallbacks when columns are missing for backward compatibility.
- **Migrations:** Three reversible migrations: `20260310_1200_trade_history_preferences_strategy_selection` (strategy_selection JSONB), `20260310_1210_trade_history_preferences_symbol_selection` (symbol_selection JSONB), `20260310_1220_strategy_list_default_column` (`"default"` boolean on strategy_list_0001). Apply in order from project root with `PYTHONPATH=. venv/bin/python scripts/db/run_migration.py up <slug>`.
- **PM:** One-time migration/backfill script cleanup tracking documented in `.cursor/pm/brain/06_conventions_insights.md` and INDEX (HOUSEKEEPING_SCRIPTS_INVENTORY + MASTER_CHANGELOG).

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Apply migrations if not already applied: `20260310_1200_trade_history_preferences_strategy_selection`, `20260310_1210_trade_history_preferences_symbol_selection`, `20260310_1220_strategy_list_default_column` (from project root with `PYTHONPATH=. venv/bin/python scripts/db/run_migration.py up <slug>` for each, or run all pending via your usual process). **Prod schema verified 2026-03-11: strategy_selection and symbol_selection exist on trade_history_preferences_0001; default exists on strategy_list_0001.**
- [x] Run `scripts/MASTER_RESTART.sh` so frontend and main_app load the new code.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status; optional: open Trade History and confirm Strategy/Symbol dropdowns load and Reset sets Strategy to defaults only.

---

## 2026-03-10 — Ghost monitor guard and MASTER_RESTART startup order

**Summary**

- **Ghost monitor guard:** `auto_entry_supervisor` and `active_trade_supervisor` now exit immediately if their monitor row is missing from `users.monitor_list_*` or has no symbol. This prevents deleted monitors from continuing to run and send trades. On startup, `get_monitor_symbol()` and (in AES) `is_auto_trade_enabled()` treat missing/invalid monitor as fatal and call `os._exit(0)` after logging.
- **kalshi_account_sync startup:** Before running the initial baseline sync, `kalshi_account_sync_ws` now waits until `trade_manager` is reachable on its port (TCP connect, up to 30s). Notify to `trade_manager` (`/api/positions_updated`) uses a shared helper with 3 retries and backoff so transient connection refused is not logged as ERROR.
- **MASTER_RESTART:** New Step 5b: after starting supervisor, the script waits until core ports 3000, 4000, and 8001 are listening (up to 30s) before proceeding to restart all services, so `trade_manager` is up before dependent services run their first sync.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes or migrations.
- [x] Run `scripts/MASTER_RESTART.sh` so all processes load the new code; ghost monitors (if any) will self-exit on next start.
- [x] Verify: health (main_app :3000, trade_executor :8001), supervisor status, and that no "Error notifying trade_manager" appears in `kalshi_account_sync.out.log` for the current process start.

---

## 2026-03-10 — Logging housekeeping (prod logs directory)

**Summary**

- **Prod logs cleanup:** Bring the production `logs/` directory back to a manageable, recent window of history by archiving/compressing rotated supervisor logs, pruning excess rotations beyond a small fixed count, and purging old logs for services that are no longer supervised.
- **Scope:** This is purely a logging/housekeeping change: it does not alter any service behavior, DB schema, or business logic. It only moves or deletes historical log files according to the rules encoded in the diagnostics scripts.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] From project root on prod (`/opt/rec_io_server`), archive or remove existing rotated logs so that only the current `.out.log`/`.err.log` files remain for each active service.
- [x] Prune older numeric rotations for active services so there are no stale `.out.log.N` / `.err.log.N` segments left in `logs/`.
- [x] Purge stale logs for services no longer managed by supervisor (including legacy SPX/NDX watchers and their strike/price logs) so only active BTC/ETH services remain.
- [x] Spot-check `logs/` on prod: confirm that each active service still has its current `.out.log` and `.err.log`, that historical clutter (e.g. daily_update* cron logs) has been removed, and that no errors occurred while cleaning the directory.

---

## 2026-03-08 — OpSec remediation (DB password, auth, CORS, bcrypt)

**Summary**

- **OpSec audit fixes:** Production now requires `DB_PASSWORD` or `REC_DB_PASS` when `REC_ENVIRONMENT=production` (no default). All backend and scripts use `get_database_config()` / `get_postgresql_connection()`. Auth: `local_dev_` bypass only when not production; bcrypt required for new password hashes; change_password uses centralized config. CORS: in production, explicit origins only (no `"*"`). Password prints removed from setup_auth/install (archive). bcrypt added to requirements.txt.
- **Production server agent:** Before or immediately after pull, ensure the production server has **DB_PASSWORD** or **REC_DB_PASS** set in the environment (e.g. in `.env` or in the env that feeds supervisor). If not set, app and config generation will fail until set. See **.cursor/pm/OPSEC_AUDIT_AND_UPGRADE.md** section "Production server: OpSec update (2026-03-08)" for full instructions.

**Production checklist**

- [x] **Before or right after pull:** Confirm production has `DB_PASSWORD` or `REC_DB_PASS` set (e.g. in `.env` or wherever supervisor gets its env). If `REC_ENVIRONMENT=production` and neither is set, `get_database_config()` will raise and services will not start. If unsure, run: `cd project_root && source .env 2>/dev/null; echo "DB_PASSWORD set: $(if [ -n \"$DB_PASSWORD\" ] || [ -n \"$REC_DB_PASS\" ]; then echo yes; else echo NO; fi)"`.
- [x] Confirm codebase changes (pull latest on production).
- [x] Install Python deps so **bcrypt** is present: from project root run `venv/bin/pip install -r requirements.txt` (or your usual deploy install). Required for change-password; existing logins unaffected.
- [x] Run `scripts/MASTER_RESTART.sh` (blocking, with permissions to stop supervisor and free ports). Config generation uses `get_database_config()` and will fail if production env has no DB password.
- [x] Run verify workflow (health, supervisor status, logs, status block per VERIFY_COMMAND.md). If any service fails to start with a DB or config error, ensure `DB_PASSWORD` or `REC_DB_PASS` is set and restart again.

---

## 2026-03-08 — DigitalOcean integration and prepare-update prod snapshot

**Summary**

- **@digitalocean agent:** Rule and AGENTS.md entry; authority on DO API, snapshots, backups, droplets. MCP **digitalocean-droplets** (remote) in mcp.json with token; tool **snapshot-droplet** for autonomous snapshot create.
- **Prepare-update:** Step 1 added: create prod snapshot **rec-io-prod-pre-update-YYYY-MM-DD** (droplet 513735057) before verify/audit/changelog so the update is revertable.
- **/apply-update:** Slash command and APPLY_UPDATE_COMMAND.md for production to run open MASTER_CHANGELOG checklists and calibrate server.
- **Scripts/docs:** scripts/do/snapshot_prod.sh, .cursor/pm/DIGITALOCEAN_INTEGRATION.md, DO_AGENT_SNAPSHOT_FIX.md, sandbox.json (optional .env read). .env.example and master .env include DIGITALOCEAN_API_TOKEN.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes or migrations; no restart required.
- [ ] Optional: On prod, if using Cursor/agents, add digitalocean-droplets MCP to mcp.json for snapshot/backup; token in env/headers.

---

## 2026-03-08 — PM and agent housekeeping (Cursor commands, brain, skills, archive)

**Summary**

- **Cursor / PM:** Slash commands and PM docs moved or added under `.cursor/`: commands (`verify`, `log-chat`, `system-restart`, `prepare-update`), PM brain (from `docs/pm_brain/` to `.cursor/pm/brain/`), new brain docs (INDEX, config/env, proposed tasks, context retention, chat summary log), PM command docs (VERIFY, LOG_CHAT, SYSTEM_RESTART, PREPARE_UPDATE, ORG_CHART, DB_REVERSIBLE_MIGRATIONS), and rules (db, kalshi, pm). Skills added for verify, log-chat, system-restart, prepare-update.
- **CI:** `.github/workflows/db-schema-drift.yml` added (runs schema drift check on push/PR to main and master).
- **Archive:** `docs/pm_brain/` content moved to `.cursor/pm/brain/`; many legacy docs and corrupted `MASTER_PORT_MANIFEST.json` snapshots moved to `archive/2026-03-housekeeping/` (docs and backend/core/config corrupt copies). `AGENTS.md` and `.gitignore` updated for new paths and ignores.
- **No application or DB changes:** No backend code, schema, or migrations in this commit. Production behavior unchanged.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes or migrations; no restart required for this release.
- [ ] Optional: If using Cursor/agents on this repo, ensure local `.cursor` config (e.g. MCP paths) is set for your machine; `mcp.json` and credentials remain gitignored.

---

## Entry format

Each entry below uses:

- **Date** – When the update is intended for production (YYYY-MM-DD).
- **Summary** – What the release contains.
- **Production checklist** – A list of tasks with checkboxes (`- [ ]`). Whoever runs the update (from local via /apply-update-from-local or on prod via /apply-update) checks these off as each is completed. Every entry has at least a minimal checklist (e.g. "Confirm codebase changes", "Update local database" if applicable). Details or commands for a task can appear under the checklist or inline in the task text.

---

## 2026-03-07 — Kalshi fixed-point migration (March 12 2026 cutoff)

**Summary**

- **Kalshi API:** Legacy integer count fields and integer cents price fields are removed by Kalshi on **March 12, 2026**. All integration code now prefers `_fp` (e.g. `count_fp`) and `_dollars` (e.g. `yes_bid_dollars`) and derives legacy values when API omits them.
- **trade_executor.py:** Already sent only `count_fp` and `yes_price_dollars` / `no_price_dollars`; no changes. No legacy `count` or `yes_price`/`no_price` in order payload.
- **kalshi_account_sync_ws.py:** Added `_prefer_fp_or_legacy()` and `_prefer_dollars_or_legacy_cents()`. Positions, fills, orders, and settlements now prefer `*_fp` and `*_dollars` from API responses; legacy counts/prices derived when missing. Settlements support `yes_total_cost_dollars` / `no_total_cost_dollars` / `revenue_dollars` when present.
- **kalshi_market_watchdog.py:** Market data: prefer `yes_bid_dollars` etc.; derive `yes_bid`/`no_bid`/… (cents) from `_dollars` when legacy cents not returned. Module-level helper `_market_cents_from_dollars()`.
- **live_orderbook_snapshot.py:** Orderbook delta messages: accept `price_dollars` or `price` (cents); normalize to cents for internal orderbook.
- **kalshi_market_ticker_websocket.py:** Orderbook delta: accept `price_dollars` and `delta_fp`; snapshot levels normalized from price_dollars/size_fp to cents/int for existing logic.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No DB schema changes required; existing `_fp` and `_dollars` columns already used.
- [x] Restart services that talk to Kalshi: `trade_executor`, `kalshi_account_sync`, `kalshi_market_watchdog` (and any hourly/15m watchdog instances), plus `main_app` if it proxies Kalshi. Full restart: `scripts/MASTER_RESTART.sh` or equivalent.
- [ ] After March 12 2026: confirm orders, fills, positions, and market data continue to sync and display; no reliance on deprecated integer/cents fields.

---

## 2026-03-07 — Kalshi account history: /deposits and /withdrawals only

**Summary**

- **Endpoints:** Account history sync no longer uses the legacy `account/history` endpoint (404). It uses only `GET /v1/users/{user_id}/deposits` and `GET /v1/users/{user_id}/withdrawals`. Legacy fetcher and converter removed from `kalshi_account_sync_ws.py`.
- **Schema:** `users.account_history_0001` has new columns `kalshi_id`, `vendor`, `rail` (reversible migration `20260307_1600_account_history_vendor_rail_kalshi_id`). Upsert uses `kalshi_id` when present; backfill updates existing rows with NULLs by matching API data (UTC-normalized time + amount).
- **Transfers:** `users.transfers_0001` From/To and status are derived from account_history (vendor/rail/deposit_type). `_refresh_transfer_from_to_from_account_history` keeps them in sync after backfill or sync.
- **Backfill:** Sync runs `_backfill_account_history_vendor_rail` after each upsert so existing rows get `kalshi_id`/vendor/rail when the API delivers them. One-off script `scripts/db/backfill_account_history_vendor_rail.py` can be run manually to backfill existing rows (e.g. after first deploy): `PYTHONPATH=. python3 scripts/db/backfill_account_history_vendor_rail.py`.
- **Rail:** Only withdrawals have `rail` in the API; deposits correctly have `rail` NULL.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Apply migration if not already applied: `python3 scripts/db/run_migration.py up 20260307_1600_account_history_vendor_rail_kalshi_id` (from project root with PYTHONPATH set). If already applied, `run_migration.py list` will show it.
- [x] Optional one-time backfill for existing account_history rows with NULL kalshi_id/vendor/rail: `PYTHONPATH=. python3 scripts/db/backfill_account_history_vendor_rail.py`. Run once; sync will backfill on its own thereafter.
- [x] Restart `kalshi_account_sync` (or full restart: `scripts/MASTER_RESTART.sh`) so sync uses new code.
- [x] Confirm: Account manager transfers table shows From/To and Status; account_history rows have vendor/rail populated where API provides them.

---

## 2026-03-07 — Fix known bugs (get_port, main.py DB)

**Summary**

- **auto_entry_supervisor.py:** `get_port("main")` → `get_port("main_app")` at the `update_monitor_position` call so the correct port is used.
- **main.py:** `get_trade_history_preferences_postgresql()` now uses `get_postgresql_connection()` from `backend.core.config.database` instead of hardcoded localhost/rec_io_user/rec_io_password. Aligns with server-agnostic config.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Restart `auto_entry_supervisor` (or full restart: `scripts/MASTER_RESTART.sh`) and `main_app` so changes take effect.
- [x] Confirm: no errors in logs; monitor position updates and trade history preferences work.

---

## 2026-03-07 — Env conventions: DB_* / REC_DB_* only

**Summary**

- **Single pattern:** All DB access goes through `backend.core.config.database`: `get_postgresql_connection()` or `get_database_config()`. No POSTGRES_* or hardcoded credentials in application code.
- **database.py:** Prefers DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT; if unset, falls back to REC_DB_HOST, REC_DB_NAME, REC_DB_USER, REC_DB_PASS, REC_DB_PORT. One place for both conventions; scripts do not need to map REC_DB_* → DB_*.
- **Updated modules:** symbol_price_watchdog_finance, strike_table_generator, backend/util/cleanup_temp_schemas, symbol_data_fetch_pg, symbol_profiler, live_table_viewer, probability_lookup_generator; scripts: update_position_to_100, rollback_position_update, generate_schema_doc, audit_db_schema.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] Ensure .env or deploy sets either DB_* or REC_DB_* (database.py uses both). No code changes required if already using DB_* or REC_DB_*.
- [x] Restart any services that were changed (full restart recommended: `scripts/MASTER_RESTART.sh`) so they load the new database module behavior.
- [x] Confirm: DB-dependent scripts and services connect successfully (e.g. run a script that uses get_postgresql_connection).

---

## 2026-03-07 — DB schema drift check and reversible migrations

**Summary**

- **Drift check:** `scripts/db/check_db_schema_drift.py` compares `backend/core/config/database.py` with `docs/MASTER_DB_SCHEMA_REFERENCE.md` for critical tables (trades_0001, trades_simulated_0001, monitor_list_0001, strategy_list_0001); exits with error if definitions drift. No DB connection required.
- **CI:** `.github/workflows/db-schema-drift.yml` runs the drift check on push/PR to main and master.
- **Reversible migrations:** `scripts/db/run_migration.py` (list / up / down); migrations live in `scripts/migrations/` as `YYYYMMDD_HHMM_slug.up.sql` and `.down.sql`; applied migrations tracked in `system.schema_migrations`. See `.cursor/pm/DB_REVERSIBLE_MIGRATIONS.md`.
- **update_db_schema_to_reference.py:** Now uses `get_postgresql_connection()` from project config (env); docstring states type/default fixes are out of scope (use reversible migrations or manual ALTERs).
- **Audit findings:** `docs/changelog/DB_MAINTENANCE_AUDIT_FINDINGS.md` documents local audit and single source of truth. **Local alignment complete:** drift check passes. Prod schema changes are part of the normal update process; @updater coordinates and verifies when pushing to production.

**Production checklist**

- [x] Confirm codebase changes (pull latest on production).
- [x] No prod DDL required for this release. CI will run drift check on future push/PR.
- [ ] Optional: to audit prod schema, set DB_* (or REC_DB_*) to point at prod and run `PYTHONPATH=. python3 scripts/audit_db_schema.py` from project root. Do not run migrations or ALTERs on prod without a maintenance window and backup.

---

## 2026-03-07 — Simulated trade duplicate fix, dedupe script (util), one-time DB cleanup

**Summary**

- **Simulated trade duplicate prevention:** Auto-entry supervisor and trade_manager now use the same server-agnostic DB connection (`backend.core.config.database.get_postgresql_connection`) for simulated trades. `is_strike_already_simulated_traded` in AES no longer uses a separate `POSTGRES_*` connection; it uses the shared config (DB_* / REC_DB_*) so the duplicate check sees the same rows that trade_manager writes. This prevents new duplicates. Trade_manager's local hardcoded `get_postgresql_connection` was removed in favor of the centralized one.
- **Dedupe script (one-time):** `backend/util/dedupe_simulated_trades.py` removes duplicate rows in `users.trades_simulated_0001` that accumulated before the connection fix. The script is **one-time only**; duplicate prevention is now in-app. It is documented as too aggressive (it deduped by date+contract only); if a future one-off dedupe is ever needed, use (date, contract, strike, side) and keep min(id) per group.
- **No code changes to live/paper trading;** only simulated path and shared DB usage.

**Production checklist**

- [x] Confirm codebase changes (pull latest `main` on production).
- [x] Update local database: run from project root  
  `PYTHONPATH=$(pwd) venv/bin/python -c "from backend.core.config.database import init_database; init_database()"`  
  if any schema migrations are pending.
- [x] **One-time dedupe of simulated trades table (after restart):** From project root, run once:  
  `PYTHONPATH=$(pwd) venv/bin/python -m backend.util.dedupe_simulated_trades`  
  This removes duplicate rows in `users.trades_simulated_0001` that may exist from before the connection fix. If the script reports "No duplicate rows (by date, contract) found.", no action needed. Do not run the dedupe repeatedly.
- [x] Restart application services (main_app, strike_table_generator, trade_manager, active_trade_supervisor, auto_entry_supervisor as applicable).
- [x] Confirm: no errors in logs after restart; simulated trades no longer double up on the same strike per cycle.

---

## 2026-03-05 — Simulated 15m trade system (production)

**Summary**

- **Simulated 15m trades on hourly markets:** `auto_entry_supervisor` now runs a simulated 15m entry path for all hourly monitors with `auto_trade=TRUE`, excluding Momentum Breakout/Contain (for testing). It reuses each monitor’s existing `min_time` / `max_time` window and reads `ttc_15m` / `probability_15m` from the hourly strike tables. Simulated trades ignore price/diff/volume/momentum spike rules, are always `paper_trade = TRUE` / `test_filter = FALSE`, and never call the executor or send real orders.
- **Contract + weekly_cycle per 15m window:** Simulated trades use contract labels at the *next* 15-minute boundary (e.g. `BTC 2:15pm`, `BTC 2:30pm`), so `trade_manager` can derive `hour_idx` and `weekly_cycle` with the correct decimal (.0 / .1 / .2 / .3) via the existing contract parsing logic. This ensures every simulated trade is tagged to the correct 15m window for later calibration.
- **15m expiration + symbol-close settlement (simulated):** `trade_manager`’s 15-minute expiration job now always calls `check_expired_simulated_trades()` at :00/:15/:30/:45, regardless of whether there are live trades. This function closes *only* `users.trades_simulated_0001` rows (no impact on `trades_0001`), using the latest `one_minute_avg` (or `price` fallback) from `live_data.live_price_log_1s_{symbol}` as `symbol_close` and setting `status = 'closed'`, `close_method = 'expired'`, and `win_loss` based on a YES/NO vs strike comparison. `sell_price` is recorded as `NULL` for simulated trades.
- **Simulated cycle_win_loss per 15m window:** For each 15m window (grouped by `monitor`, `date`, `weekly_cycle`) that has simulated trades closed in a given expiration run, `trade_manager` sets `cycle_win_loss` on `users.trades_simulated_0001` to `L` if **any** trade in that window is a loss, otherwise `W`. This gives a single, conservative win/loss flag per monitor per 15m cycle for downstream Strategy Health Score (SHS) work.
- **DB schema + load characteristics:** No new columns were added for this feature; it relies on the existing `users.trades_simulated_0001` schema (including `weekly_cycle NUMERIC(5,1)`, `cycle_win_loss`, `cycle_pnl`, `cycle_ret_pct`) and the `live_data.live_price_log_1s_{symbol}` tables. `insert_simulated_trade` explicitly records `diff`, `buy_price`, `position`, `fees`, `bankroll`, `price_spread`, and `sell_price` as `NULL` and touches only `users.trades_simulated_0001`. The system leverages existing CPU-intensive processes (strike generators, price logs, auto-entry loops); the new work is limited to light `SELECT` / `INSERT` / `UPDATE` statements and does not introduce new schedulers or external API calls.

**Production checklist**

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

**Production checklist**

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

**Production checklist**

- [x] Confirm codebase changes (pull latest `main` on production; or merge feature branch into `main` then pull).
- [x] Update local database: ensure `_fp` columns exist on `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, `users.settlements_0001` per `docs/MASTER_DB_SCHEMA_REFERENCE.md`. Add any missing as `NUMERIC(12,2)` (nullable). Columns: `fills_0001` → `count_fp`; `orders_0001` → `initial_count_fp`, `remaining_count_fp`, `fill_count_fp`; `positions_0001` → `total_traded_fp`, `position_fp`; `settlements_0001` → `yes_count_fp`, `no_count_fp`. Example: `ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS count_fp NUMERIC(12,2);`
- [x] Run historical ingest once to backfill new columns from Kalshi API: `PYTHONPATH=$(pwd) venv/bin/python backend/api/kalshi-api/kalshi_historical_ingest.py` (see schema ref section "4. After updating portfolio-level user tables").
- [x] Restart application services (main_app, trade_manager, trade_executor, kalshi_account_sync, active_trade_supervisor as applicable).
- [x] Confirm: no errors in logs after restart; trading and account sync behave as expected.

---
