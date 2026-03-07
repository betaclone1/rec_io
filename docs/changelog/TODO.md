# TODO — Changelog backlog

Timestamped tasks we want to come back to. Use checklist formatting; add technical notes where useful. Update with milestones and completion reports as work progresses.

---

## 2026-03-05 — DB maintenance system audit

**Scope:** Align DB structure across reference docs, `database.py`, and local vs remote DB states. Single source of truth and no schema drift.

**Checklist**

- [ ] Audit and document current state: reference doc vs `database.py` vs local DB vs remote (prod) DB.
- [ ] Define single source of truth (doc or code) and update the other to match.
- [ ] Ensure `database.py` CREATE TABLE / migrations produce the same types and columns as the reference doc for all critical tables (at least `users.trades_0001`, `users.trades_simulated_0001`, and any other tables used by trading paths).
- [ ] Extend or replace `update_db_schema_to_reference.py` so it can correct type/default mismatches (not only add missing columns), or document when to run ALTERs manually.
- [ ] Add a check (script or CI) that fails if `database.py` table definitions drift from the reference doc.
- [ ] Plan and execute remote (prod) schema fixes for tables that were created with the old `database.py` definition (e.g. `users.trades_simulated_0001` on prod already fixed by aligning doc + database.py; prod table still needs ALTERs if it was created before the fix).

**Technical notes**

- Reference: `docs/MASTER_DB_SCHEMA_REFERENCE.md`. Code: `backend/core/config/database.py` (`init_database()`). Migration script: `scripts/update_db_schema_to_reference.py` (adds missing columns only; does not change column types).
- Local vs prod comparison: `scripts/compare_simulated_table_schema.py` (trades_simulated only). Full audit: `scripts/audit_db_schema.py` (local DB vs doc vs database.py; no remote).
- Prod host: 137.184.224.94. Same DB credentials as local per env.
- Defer full audit until it won’t interrupt trading operations.

**Milestones / completion**

- (Add timestamped updates here as work progresses.)

---

## 2026-03-05 — Kalshi account history: consider /deposits and /withdrawals (low priority)

**Scope:** `GET /v1/users/{user_id}/account/history` has been returning 404 since ~2026-03-05 (possibly tied to overnight Kalshi maintenance). Separate endpoints `GET /v1/users/{user_id}/deposits` and `GET /v1/users/{user_id}/withdrawals` return 200 and provide richer data (vendor: venmo, plaid, zerohash; rail: apm, ach) instead of lumping into ACH/crypto.

**Checklist**

- [ ] Wait and see whether the old `account/history` endpoint comes back (may be temporary; Kalshi may be testing).
- [ ] If 404 persists or we want the better vendor/rail data: switch `kalshi_account_sync_ws` to use `/deposits` and `/withdrawals` as primary (or fallback), with pagination.
- [ ] Update DB schema to account for new vendor, rail, and any other new values (e.g. add columns to `users.account_history_0001` and/or `users.transfers_0001`; run migrations in `database.py`; update `docs/MASTER_DB_SCHEMA_REFERENCE.md`).
- [ ] Map new response shape into `users.account_history_0001` and `users.transfers_0001`; add or use a column for vendor/rail so we don’t lose granularity.
- [ ] Keep existing external-transfer → subaccount logic; derive `from`/`to` from vendor/rail instead of defaulting to ACH/Crypto.
- [ ] Update frontend to show new vendor/rail (and any other new fields) where transfers or account history are displayed (e.g. `frontend/tabs/account_manager.html`, `frontend/mobile/account_manager_mobile.html`).

**Technical notes**

- Current sync: `backend/kalshi_account_sync_ws.py` — `fetch_v1_account_history_page`, `sync_account_history`; 404 is handled gracefully (warning only).
- New endpoints: same base URL and auth; responses have `deposits[]` and `withdrawals[]` with `id`, `status`, `amount_cents`, `fee_cents` (deposits), `created_ts`, `deposit_type`/`vendor` (deposits), `rail`/`vendor` (withdrawals).

**Milestones / completion**

- (Add when we re-evaluate or implement.)

---

## 2026-03-05 — System-wide logging audit

**Scope:** Scripts are logging far too much, causing system lag and ballooning storage. Audit logging across services and reduce volume to what’s necessary for operations and debugging.

**Checklist**

- [ ] Identify main offenders: which scripts/services produce the largest or most frequent log output (e.g. auto_entry_supervisor, trade_manager, kalshi_account_sync, watchdogs, etc.).
- [ ] Define logging policy: what should be logged at INFO vs DEBUG vs only in development; reduce per-tick/per-order/per-request chatter.
- [ ] Trim or gate verbose logs (e.g. full payloads, repeated status lines, success confirmations that add little value).
- [ ] Consider log levels, conditional verbose logging, or sampling for high-frequency paths.
- [ ] Revisit logrotate/retention and any log aggregation so retained volume is bounded after the audit.

**Technical notes**

- Logs live under `logs/` (e.g. `*.out.log`, `*.err.log`); rotation in `config/logrotate.conf`. Supervisor redirects stdout/stderr into these files.
- Goal: reduce I/O and disk usage while keeping enough signal for debugging and operational visibility.

**Milestones / completion**

- (Add when audit is started or completed.)

---

## Script CPU optimization (umbrella)

Tasks to reduce CPU usage of long-running scripts via consolidation, polling/interval tuning, or similar analyses. Other scripts may be added here with comparable audits.

---

### Auto-entry supervisor consolidation

**Scope:** Consolidate `auto_entry_supervisor` from one process per monitor to a **single process** that iterates over all active monitors each tick. Keeps strict per-monitor discipline (no cross-monitor state, every trade/DB call explicitly keyed by monitor_id). Expected CPU impact: today ~6–7% of one core per process (8 monitors ≈ 50% of one core total); after consolidation ~35–45% of one core total — roughly 5–15% of one core freed, or ~1–2% per active monitor. Gain is from removing duplicate process/thread overhead.

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

**Checklist**

- [ ] Invite the bot to the Kalshi dev server (OAuth2 URL → authorize; see `docs/DISCORD_BOT_SETUP.md` §2). Server ID `871819895443189862`, channel ID `927686720990892032`.
- [ ] Verify read_messages and send_message work via MCP with those IDs; fix any MCP or permission issues.
- [ ] (Optional) Explore broader MCP usage once Discord is working—Eric wants to learn MCP with Discord as the first use case.

**Notes**

- Bot and MCP config exist; bot was in 0 servers as of 2026-03-06. Full setup: `docs/DISCORD_BOT_SETUP.md`.

---
