# PM proposed tasks / next steps

When the PM proposes a short list of starting tasks or next steps for the project, record that list here so the CEO and future sessions can recall it. Update this doc whenever such a list is proposed; archive or trim when items are done or superseded.

---

## Current proposed list

- ~~**Kalshi fixed-point migration**~~ **DONE (2026-03-07)** — trade_executor, kalshi_account_sync_ws, kalshi_market_watchdog, live_orderbook_snapshot, kalshi_market_ticker_websocket now prefer `count_fp`/`_dollars` and derive legacy when missing. Changelog and brain 11 updated.
- ~~**Fix known bugs**~~ **DONE (2026-03-07)** — (a) auto_entry_supervisor.py: `get_port("main")` → `get_port("main_app")` at update_monitor_position call. (b) main.py: `get_trade_history_preferences_postgresql()` now uses `get_postgresql_connection()` from backend.core.config.database instead of hardcoded credentials.
- **DB maintenance system audit** — Align reference doc, `database.py`, and prod. Single source of truth; no schema drift. See docs/changelog/TODO.md 2026-03-05 checklist. Defer full prod changes until non-disruptive.
- **Kalshi account history** — v1 `account/history` 404; switch sync to `/deposits` and `/withdrawals` if 404 persists; update schema and frontend for vendor/rail. Lower urgency than fixed-point; sync currently degrades gracefully.
- ~~**Env conventions**~~ **DONE (2026-03-07)** — database.py prefers DB_*, falls back to REC_DB_*; backend and scripts use get_postgresql_connection()/get_database_config(); POSTGRES_* deprecated. Brain 03/04 and TODO updated.
- **Auto_entry_supervisor consolidation** — Single process, multi-monitor loop (per TODO/open items). Simplifies deployment and monitoring. *Pinned for now (deferred).*
- **System-wide logging audit** — Identify high-volume log sources; define policy (INFO vs DEBUG); trim verbose per-tick/per-request output; keep operational/debug signal. Improves I/O and disk. *Pinned for now (deferred).*
- **Project housekeeping** — Audit scripts, docs, backend, and root to identify what’s in use vs. litter; archive (don’t delete) unused/obsolete items to a single archive tree with an index. Plan: `docs/PROJECT_HOUSEKEEPING_AUDIT_PLAN.md`.

---

*Last updated: 2026-03-07.*
