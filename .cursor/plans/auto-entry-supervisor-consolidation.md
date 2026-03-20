# Auto-entry supervisor consolidation

**Goal:** Consolidate auto_entry_supervisor from one process per monitor to a single process that iterates over all active monitors each tick; reduce CPU (remove per-process overhead while keeping strict per-monitor discipline).

**Scope:** In: auto_entry_supervisor refactor (per-monitor state, single loop, explicit monitor_id everywhere); Flask routes and port model; startup/config. Out: other scripts (umbrella for later).

**Status:** draft (long‑term initiative; not current top priority)

## Steps
1. Refactor state to be per-monitor (e.g. _last_monitor_state[monitor_id], auto_entry_indicator_state[monitor_id]); no process-wide "current monitor" global.
2. Single 1s loop: discover active monitors (monitor_list where auto_trade = true); each tick run cleanup_old_cooldowns(monitor_id) and check_auto_entry_conditions(monitor_id) per monitor in sequence; per-monitor try/except.
3. All call paths take explicit monitor context (monitor_id or context object). Replace get_current_monitor_symbol()-style with get_monitor_symbol(monitor_id). DB/trade payloads unchanged in shape.
4. Flask: single app; routes take monitor_id in path or query (e.g. /api/auto_entry_indicator/<monitor_id>). One port for auto_entry_supervisor; frontend and main app pass monitor_id.
5. Startup: no monitor in argv; load active monitors from DB (optionally re-query periodically). One auto_entry_supervisor port in config.
6. Document or implement deterministic/rotating order of monitors if fairness matters.

## Completion criteria
- [ ] Single process runs all active monitors
- [ ] No cross-monitor state; every trade/DB call keyed by monitor_id
- [ ] One port; frontend/main app pass monitor_id
- [ ] CPU usage reduced vs N processes (target: ~35–45% of one core total vs ~50% today for 8 monitors)

## Blockers / decisions
- Full design: `docs/changelog/todo_docs/AUTO_ENTRY_SUPERVISOR_CONSOLIDATION_AUDIT.md`. Current: one process per monitor, identity from argv; port from get_monitor_port("auto_entry_supervisor", MONITOR_IDENTIFIER).
