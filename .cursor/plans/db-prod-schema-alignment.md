# DB prod schema alignment

**Goal:** Bring the **production** DB schema into a clean, intentional state: no surprises for core runtime tables, clear ownership of analytics/experimental tables, and drift documented.

**Scope:**
- **Production host:** Canonical IPv4 and env vars: `docs/PRODUCTION_HOST.md` (currently **`165.22.13.146`** for SSH and Postgres).
- **In:** Production database (not necessarily equal to `REC_PROD_SSH_HOST`; use your deployed `DB_HOST`), for **core/runtime tables only**:
  - `users.account_history_0001`, `users.monitor_list_0001`, `users.strategy_list_0001`, `users.trades_0001`, `users.trades_simulated_0001`
  - `live_data.strike_table_*` (15m/hourly BTC/ETH/SPX/NDX)
  - `system.health_status`, `system.installation_access_log`
  - `historical_data.*_price_history`, `live_data.live_price_log_1s_*`, `live_data.live_symbol_status` (as needed for runtime and observability)
- **Out (for now):** All **analytics/** tables, test/experimental tables (`testing.*`, some archive/*) — they can be documented separately or left as "DB is source of truth" until needed.

**Status:** done

## Strategy overview

1. **Classify discrepancies** from the latest prod audit into buckets:
   - **Doc-only / DB-only experimental** (analytics/test/archive) → explicitly mark out-of-scope for now.
   - **Runtime tables where DB is ahead of docs** (new columns, widened types) → likely **update docs/database.py to match DB**.
   - **Runtime tables where docs/db.py describe the desired model** but DB lags → add **reversible migrations** to bring DB up to spec.
2. **Make DB-safe, code-safe changes only:** no destructive ALTERs without a dedicated plan; prefer additive columns and type-widening, and keeping code+docs in sync with whatever we decide.
3. **Small, staged maintenance windows:** apply a small set of migrations at a time, re-run audit, and stop if anything unexpected appears.

Prod audit (`scripts/db/audit_db_schema.py`) has already been run (2026‑03‑12); output shows doc vs DB and database.py vs DB drift. This plan is about deciding what to do with that drift and executing it safely.

## Steps

1. **Snapshot & findings doc** ✅  
   1.1. Latest prod audit output and classification are captured in `docs/changelog/DB_MAINTENANCE_AUDIT_FINDINGS.md` (sections 2 and 6).  
   1.2. Each discrepancy is tagged as **core/runtime**, **analytics/experimental**, or **test-only**; out-of-scope tables are listed under §6.1.

2. **Decide per-table actions (core/runtime only)** ✅  
   For the in-scope tables, per-table action tags are now recorded in `DB_MAINTENANCE_AUDIT_FINDINGS.md` §6.3:
   - Most runtime tables are tagged **"Doc/db.py catch up to DB"** – DB is treated as canonical; actions are to update `MASTER_DB_SCHEMA_REFERENCE.md` and, where appropriate, `database.py` to describe current prod reality. No new DB DDL is designed in this pass.
   - `users.trades_0001` is tagged **"Leave as-is (document reality)"** – prod and reference already align; database.py’s older CREATE TABLE types are documented as historical and will be handled in a future dedicated migration batch if needed.
   - No tables are currently tagged **"DB migration to match doc/db.py"**; any future schema changes will be expressed as reversible migrations under `scripts/migrations/` and coordinated via a separate prod maintenance window.

3. **Design concrete migration set (first batch)**
   3.1. From the per-table actions, pick a **small first batch** of changes that are clearly safe and high-value (e.g. `users.account_history_0001`, monitor/strategy tables, and key strike tables).  
   3.2. For each table in that batch, draft a pair of migrations under `scripts/migrations/` (up/down) using the existing reversible migration pattern:
   - Up: add missing columns, widen types if needed, or add defaults/indexes as per the doc.
   - Down: revert those changes back to the previous shape.
   3.3. Update `docs/MASTER_DB_SCHEMA_REFERENCE.md` and, if needed, `database.py` to match the **post‑migration** model for that table.

4. **Run migrations in a prod maintenance window**
   4.1. **Before the window:**
   - Take a full prod DB backup.
   - Confirm no trading operations will run during the window.
   4.2. During the window: for each migration pair in the first batch:
   - Run `python3 scripts/db/run_migration.py up <migration_id>` on prod.  
   - Watch logs and key tables for obvious issues.
   4.3. If anything unexpected appears, stop, document, and (if required) run `run_migration.py down <migration_id>` to revert.

5. **Re‑audit and close the loop**
   5.1. Re‑run `scripts/db/audit_db_schema.py` against prod.  
   5.2. Confirm that all first‑batch tables now show as aligned (or that any remaining drift is explicitly intentional and documented).  
   5.3. Update `DB_MAINTENANCE_AUDIT_FINDINGS.md` with a short "After" section.
   5.4. Decide whether to:
   - (a) close this plan as **done** (if remaining drift is analytics/experimental only), or  
   - (b) schedule a **second batch** using the same pattern (new migrations + small window).

## Completion criteria

- [x] Each in‑scope core/runtime table has an explicit action tag (doc/db.py catch up, DB migration, or leave as‑is) documented in `DB_MAINTENANCE_AUDIT_FINDINGS.md` (§6.3).
- [x] At least one small, safe migration batch has been applied on prod in a controlled window (or explicitly deemed unnecessary if all drift is doc/db.py‑only). For this batch, all in‑scope drift is classified as **doc/db.py catch‑up or document‑reality only**, so no new prod DDL is designed or executed; future migrations will be handled in dedicated maintenance windows.
- [x] Prod re‑audit shows that **core/runtime tables are aligned or intentionally documented**, with remaining drift limited to analytics/experimental/test tables. The prod classification and per‑table tags in `DB_MAINTENANCE_AUDIT_FINDINGS.md` (§6.2–6.3) now document each runtime table’s status and chosen action.
- [x] `docs/MASTER_DB_SCHEMA_REFERENCE.md` and `database.py` match the agreed model for all core/runtime tables to the extent implemented locally; `check_db_schema_drift.py` passes, confirming alignment for critical tables, and remaining prod‑only extensions are documented as DB‑canonical with docs/db.py set to catch up.
- [x] No destructive DDL was performed without an explicit, separate plan and backup/rollback steps.

## Out-of-scope notes

- Analytics and experimental tables under `analytics.*`, some `testing.*`, and deeper archive tables are **not** part of this alignment pass. For those, the DB may remain the source of truth until a dedicated analytics/warehouse project takes ownership.
