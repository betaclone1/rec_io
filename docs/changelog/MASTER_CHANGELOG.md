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

## 2025-03-04 — Kalshi fixed-point migration (count / _fp)

**Summary**

- Backend support for Kalshi’s fixed-point migration for contract counts. We now record and use `_fp` fields (e.g. `count_fp`, `remaining_count_fp`, `position_fp`) in addition to legacy integer fields across portfolio sync, trade manager, order submission, and API responses.
- **Recording:** Account sync and historical ingest write all `_fp` columns to `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, `users.settlements_0001` (stored as `NUMERIC(12,2)`).
- **Reading:** Trade manager and main app prefer `_fp` when present (legacy can be NULL once the API deprecates it). Order delta check in sync uses `_fp` for comparison.
- **Outbound:** Order submission sends only `count_fp` to the Kalshi API (legacy `count` no longer sent). Internal callers (main, auto_entry, ATS, frontend) pass `count_fp` through the trade chain.
- If the API stops sending legacy count fields, operations continue unchanged; legacy columns may be NULL for new data. See `docs/FIXED_POINT_LEGACY_DEPRECATION_AUDIT.md` for details.

**Production agent checklist**

- [ ] Confirm codebase changes (pull latest `main` on production; or merge feature branch into `main` then pull).
- [ ] Update local database: ensure `_fp` columns exist on `users.fills_0001`, `users.orders_0001`, `users.positions_0001`, `users.settlements_0001` per `docs/MASTER_DB_SCHEMA_REFERENCE.md`. Add any missing as `NUMERIC(12,2)` (nullable). Columns: `fills_0001` → `count_fp`; `orders_0001` → `initial_count_fp`, `remaining_count_fp`, `fill_count_fp`; `positions_0001` → `total_traded_fp`, `position_fp`; `settlements_0001` → `yes_count_fp`, `no_count_fp`. Example: `ALTER TABLE users.fills_0001 ADD COLUMN IF NOT EXISTS count_fp NUMERIC(12,2);`
- [ ] (Optional) Run historical ingest once to backfill new columns from Kalshi API: `PYTHONPATH=$(pwd) python3 backend/api/kalshi-api/kalshi_historical_ingest.py` (see schema ref section "4. After updating portfolio-level user tables").
- [ ] Restart application services (main_app, trade_manager, trade_executor, kalshi_account_sync, active_trade_supervisor as applicable).
- [ ] Confirm: no errors in logs after restart; trading and account sync behave as expected.

---
