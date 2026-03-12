# TODO — Changelog backlog

**Outstanding work migrated (2026-03):** Active task tracking is in **`.cursor/plans/`** (one plan file per task). See `.cursor/plans/README.md` and `PROJECT_OPERATING_MODEL.md`. This doc remains as historical record and reference; use `.cursor/plans/*.md` for current backlog.

Timestamped tasks we want to come back to. Use checklist formatting; add technical notes where useful. Update with milestones and completion reports as work progresses.

---

## 2026-03-07 — Project housekeeping (first batch)

**Scope:** Audit scripts, docs, backend, root; archive unused/obsolete items (no deletes). Plan: `docs/PROJECT_HOUSEKEEPING_AUDIT_PLAN.md`.

**Done (2026-03-07):** Phase 1 inventories in `docs/changelog/todo_docs/` (HOUSEKEEPING_SCRIPTS_INVENTORY.md, HOUSEKEEPING_DOCS_INVENTORY.md, HOUSEKEEPING_BACKEND_ROOT_INVENTORY.md). First archive batch: 83× `MASTER_PORT_MANIFEST.json.corrupted_*` and 2 scripts (START_SERVICES_DIRECT.sh, auto_add_files.sh) moved to `archive/2026-03-housekeeping/`. Index: `archive/2026-03-housekeeping/INDEX.md`.

**Backlog:** Further script and doc candidates in inventories; move in a later pass after review. Corrupted manifests and two scripts archived; MASTER_RESTART_WITH_SANITIZATION_CHECK.sh kept (referenced by install/auto_startup).

---

## 2026-03-05 — DB maintenance system audit

**Scope:** Align DB structure across reference docs, `database.py`, and local vs remote DB states. Single source of truth and no schema drift.

**Active tracking:** See `.cursor/plans/db-prod-schema-alignment.md` and `docs/changelog/DB_MAINTENANCE_AUDIT_FINDINGS.md` for the current state. This section is a historical summary and high-level pointer, not the live task source of truth.

**Checklist (historical)**

- [x] Audit and document current state: reference doc vs `database.py` vs local DB vs remote (prod) DB. (Local audit done; prod deferred; findings in `docs/changelog/DB_MAINTENANCE_AUDIT_FINDINGS.md`.)
- [x] Define single source of truth (doc or code) and update the other to match. (Reference doc = SSOT; `database.py` = bootstrap; see findings doc.)
- [x] Ensure `database.py` CREATE TABLE / migrations produce the same types and columns as the reference doc for all critical tables (at least `users.trades_0001`, `users.trades_simulated_0001`, and any other tables used by trading paths). (Local alignment done 2026-03-07: type-compatibility buckets in drift check, reference updated with bankroll_allotment and max_probability, parser skips comment lines; `check_db_schema_drift.py` passes.)
- [x] Extend or replace `update_db_schema_to_reference.py` so it can correct type/default mismatches (not only add missing columns), or document when to run ALTERs manually. (Documented: type/default via reversible migrations or manual ALTERs; script adds columns only.)
- [x] Add a check (script or CI) that fails if `database.py` table definitions drift from the reference doc. (`scripts/db/check_db_schema_drift.py`.)
- [ ] Plan and execute remote (prod) schema fixes for tables that were created with the old `database.py` definition. (**Not yet scheduled**: when a prod maintenance window is planned, create a dedicated plan under `.cursor/plans/` for the reversible migration batch; do not track that work here.)

**Technical notes**

- Reference: `docs/MASTER_DB_SCHEMA_REFERENCE.md`. Code: `backend/core/config/database.py` (`init_database()`). Migration script: `scripts/db/update_db_schema_to_reference.py` (adds missing columns only; does not change column types).
- Reversible migrations: `.cursor/pm/DB_REVERSIBLE_MIGRATIONS.md`, runner `scripts/db/run_migration.py` (list / up / down). New schema changes should be migration pairs in `scripts/migrations/` so they can be reverted like code.
- Local vs prod comparison: `scripts/compare_simulated_table_schema.py` (trades_simulated only). Full audit: `scripts/db/audit_db_schema.py` (local DB vs doc vs database.py; no remote).
- Prod host: 137.184.224.94. Same DB credentials as local per env.
- Defer full audit until it won’t interrupt trading operations.

**Milestones / completion**

- **2026-03-07 — Audit executed (task 3).** Ran `scripts/db/audit_db_schema.py` (local only). Findings: `docs/changelog/DB_MAINTENANCE_AUDIT_FINDINGS.md`. Single source of truth: reference doc; `database.py` for bootstrap; migrations for changes. `update_db_schema_to_reference.py` now uses `get_postgresql_connection()` (env); docstring documents that type/default fixes are out of scope (use reversible migrations or manual ALTERs). Drift check: `scripts/db/check_db_schema_drift.py` (fails if `database.py` differs from reference for critical tables: trades_0001, trades_simulated_0001, monitor_list_0001, strategy_list_0001). No prod DDL run.
- **2026-03-07 — Drift check in CI.** `.github/workflows/db-schema-drift.yml` runs on push/PR to main and master; runs `check_db_schema_drift.py` with PYTHONPATH set. Exit 1 from the script fails the job.
- **2026-03-07 — Local alignment complete.** Drift check now passes: `normalize_type_for_compare` in `audit_db_schema.py` uses compatible type buckets (STRING for TEXT/VARCHAR/DATE/TIME/TIMESTAMP, NUMERIC for REAL/DECIMAL/NUMERIC, INT for INTEGER/SMALLINT). Drift script only requires columns in database.py to exist in reference (reference may have extra columns). Parser skips lines where column name is `--`. Reference doc: added `bankroll_allotment` to monitor_list_0001, `max_probability` to strategy_list_0001. `scripts/db/check_db_schema_drift.py` exits 0. Production server elements are part of the update process; @updater coordinates and verifies when pushing to prod.
- **2026-03-07 — Prod schema fix plan (do not execute until maintenance window).**
  1. **Pre-requisites:** Backup prod DB. Ensure no trading operations during window. Have rollback plan (reversible migrations: `run_migration.py down <id>`).
  2. **Prod host:** 137.184.224.94. Same DB credentials as local per env (DB_* / REC_DB_*).
  3. **Steps:** (a) Run `scripts/db/audit_db_schema.py` against prod (point DB_* at prod) to capture current prod state vs reference. (b) For each table with missing columns or type drift (e.g. `users.trades_0001`, `users.trades_simulated_0001`), add reversible migration pairs under `scripts/migrations/` (e.g. `YYYYMMDD_HHMM_align_trades_0001_types.up.sql` / `.down.sql`). (c) Apply migrations on prod via `python3 scripts/db/run_migration.py up <id>` one at a time. (d) Update reference doc if any new columns/constraints were added. (e) Re-run audit against prod to confirm alignment.
  4. **Do not:** Run ad hoc DDL without a migration pair. Do not run destructive ALTERs (e.g. shrinking types) without explicit CEO/PM approval and backup.

---

## 2026-03-05 — Kalshi account history: consider /deposits and /withdrawals (low priority)

**Scope:** `GET /v1/users/{user_id}/account/history` has been returning 404 since ~2026-03-05 (possibly tied to overnight Kalshi maintenance). Separate endpoints `GET /v1/users/{user_id}/deposits` and `GET /v1/users/{user_id}/withdrawals` return 200 and provide richer data (vendor: venmo, plaid, zerohash; rail: apm, ach) instead of lumping into ACH/crypto.

**Checklist**

- [ ] Wait and see whether the old `account/history` endpoint comes back (may be temporary; Kalshi may be testing).
- [x] If 404 persists or we want the better vendor/rail data: switch to `/deposits` and `/withdrawals` (done 2026-03-07).
- [x] Update DB schema: added kalshi_id, vendor, rail to account_history_0001 via reversible migration; reference doc and database.py updated.
- [x] Map new response shape into `users.account_history_0001` and `users.transfers_0001`; add or use a column for vendor/rail so we don’t lose granularity.
- [x] Keep existing external-transfer → subaccount logic; derive from/to from vendor/rail.
- [x] Update frontend: transfers table shows From/To (vendor/rail-derived) and Status; desktop and mobile account manager updated.

**Technical notes**

- Sync now uses `fetch_v1_deposits_page` and `fetch_v1_withdrawals_page`; `sync_account_history` merges both, maps via `_deposit_to_row`/`_withdrawal_to_row`, upserts by `kalshi_id`.
- New endpoints: same base URL and auth; responses have `deposits[]` and `withdrawals[]` with `id`, `status`, `amount_cents`, `fee_cents` (deposits), `created_ts`, `deposit_type`/`vendor` (deposits), `rail`/`vendor` (withdrawals).

**Milestones / completion**

- **2026-03-07 — Migrated to /deposits and /withdrawals.** Reversible migration added kalshi_id (unique), vendor, rail to account_history_0001. Sync fetches both endpoints, maps to rows, upserts by kalshi_id. Transfers from/to derived from vendor/rail. Frontend: Status column and From/To show new values. Script `scripts/check_kalshi_account_endpoints.py` checks endpoint status.

---

## 2026-03-05 — System-wide logging audit (completed)

**Scope:** Scripts are logging far too much, causing system lag and ballooning storage. Audit logging across services and reduce volume to what’s necessary for operations and debugging.

**Checklist**

- [x] Identify main offenders: which scripts/services produce the largest or most frequent log output (e.g. auto_entry_supervisor, trade_manager, kalshi_account_sync, watchdogs, etc.).
- [x] Define logging policy: what should be logged at INFO vs DEBUG vs only in development; reduce per-tick/per-order/per-request chatter.
- [x] Trim or gate verbose logs (e.g. full payloads, repeated status lines, success confirmations that add little value).
- [x] Consider log levels, conditional verbose logging, or sampling for high-frequency paths.
- [x] Revisit logrotate/retention and any log aggregation so retained volume is bounded after the audit.

**Technical notes**

- Logs live under `logs/` (e.g. `*.out.log`, `*.err.log`); rotation in `config/logrotate.conf`. Supervisor redirects stdout/stderr into these files.
- Goal: reduce I/O and disk usage while keeping enough signal for debugging and operational visibility.

**Milestones / completion**

- **2026-03-12 — Logging audit completed.** Offending services identified, log volume trimmed per policy, and retention/rotation updated; see `.cursor/plans/logging-audit.md` for details and status.

---

## 2026-03-07 — Env conventions (DB_* / REC_DB_* only)

**Scope:** Single pattern for DB config: scripts and backend use backend.core.config.database (get_postgresql_connection / get_database_config); no POSTGRES_* or hardcoded credentials.

**Checklist**

- [x] database.py: prefer DB_*, fall back to REC_DB_* (REC_DB_PASS → password) so one place handles both conventions.
- [x] Backend: symbol_price_watchdog_finance, strike_table_generator, cleanup_temp_schemas, symbol_data_fetch_pg, symbol_profiler, live_table_viewer, probability_lookup_generator now use get_postgresql_connection() or get_database_config().
- [x] Scripts: update_position_to_100, rollback_position_update, generate_schema_doc use get_postgresql_connection(); audit_db_schema uses it and no longer maps REC_DB_*→DB_* manually.
- [x] Brain: 03_db_schema_brain.md and 04_config_env.md updated; POSTGRES_* deprecated for new code.

**Notes**

- Supervisor and generate_unified_supervisor_config still inject DB_*, POSTGRES_*, REC_DB_* for child processes; that is acceptable so existing .env or deploy vars work. New code should not read POSTGRES_*.
- tests/test_trade_manager_database.py still sets POSTGRES_*; if the code under test uses database.py, set DB_* (or rely on REC_DB_* fallback) for tests to connect.

---

## Script CPU optimization (umbrella)

Tasks to reduce CPU usage of long-running scripts via consolidation, polling/interval tuning, or similar analyses. Other scripts may be added here with comparable audits.

---

### Auto-entry supervisor consolidation

**Scope:** Consolidate `auto_entry_supervisor` from one process per monitor to a **single process** that iterates over all active monitors each tick. Keeps strict per-monitor discipline (no cross-monitor state, every trade/DB call explicitly keyed by monitor_id). Expected CPU impact: today ~6–7% of one core per process (8 monitors ≈ 50% of one core total); after consolidation ~35–45% of one core total — roughly 5–15% of one core freed, or ~1–2% per active monitor. Gain is from removing duplicate process/thread overhead.

**Active tracking:** See `.cursor/plans/auto-entry-supervisor-consolidation.md` for the live plan, steps, and completion criteria.

**Checklist**

- [ ] Refactor state to be per-monitor (e.g. `_last_monitor_state[monitor_id]`, `auto_entry_indicator_state[monitor_id]`, strategy globals keyed by monitor_id). No process-wide “current monitor” global.
- [ ] Single 1s loop: discover active monitors (e.g. from `monitor_list` where `auto_trade = true`); each tick run `cleanup_old_cooldowns(monitor_id)` and `check_auto_entry_conditions(monitor_id)` for each monitor in sequence. Per-monitor try/except so one monitor’s failure does not stop others.
- [ ] All call paths take explicit monitor context (monitor_id or context object). Replace `get_current_monitor_symbol()`-style helpers with `get_monitor_symbol(monitor_id)` (or equivalent). DB and trade payloads unchanged in shape; only the source of monitor id changes (argument instead of global).
- [ ] Flask: single app; routes take monitor_id in path or query (e.g. `/api/auto_entry_indicator/<monitor_id>`). One port for auto_entry_supervisor; frontend and main app pass monitor_id.
- [ ] Startup: no monitor in argv; load active monitors from DB (and optionally re-query periodically). Config: one `auto_entry_supervisor` port instead of per-monitor ports.
- [ ] Document or implement deterministic/rotating order of monitors in the loop if fairness across monitors matters.

**Technical notes**

- Full design and discipline table: `docs/changelog/todo_docs/AUTO_ENTRY_SUPERVISOR_CONSOLIDATION_AUDIT.md`.
- Current: one process per monitor, identity from argv (`0001_10002`); one `monitoring_worker` thread per process, 1s cadence; port from `get_monitor_port("auto_entry_supervisor", MONITOR_IDENTIFIER)`.

**Milestones / completion**

- (Add when implementation is started or completed.)

---

## 2026-03-06 — Discord MCP / Kalshi dev channel (deferred)

**Scope:** Finish Discord bot setup so @kalshi can read (and optionally post to) the Kalshi dev channel. Eric is new to MCP; he wants to come back to this later and use it as a starting point to dig into MCP functionality.

**Active tracking:** See `.cursor/plans/discord-mcp-kalshi-dev.md` for the live plan, steps, and completion criteria.

**Checklist**

- [ ] Invite the bot to the Kalshi dev server (OAuth2 URL → authorize; see `docs/DISCORD_BOT_SETUP.md` §2). Server ID `871819895443189862`, channel ID `927686720990892032`.
- [ ] Verify read_messages and send_message work via MCP with those IDs; fix any MCP or permission issues.
- [ ] (Optional) Explore broader MCP usage once Discord is working—Eric wants to learn MCP with Discord as the first use case.

**Notes**

- Bot and MCP config exist; bot was in 0 servers as of 2026-03-06. Full setup: `docs/DISCORD_BOT_SETUP.md`.

---
