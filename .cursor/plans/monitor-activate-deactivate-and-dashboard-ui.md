# Monitor activate/deactivate reliability and dashboard UI

**Goal:** Reliable script lifecycle on activate/deactivate and immediate feedback when toggling monitor on/off in the dashboard.
**Scope:** main_app deactivate/activate sync (fallback + activate path), monitor_list semantics docs, dashboard optimistic status-light/tile update (desktop + mobile).
**Status:** done (completed 2026-03-15)

## What was done

1. **Deactivate** — main_app already called monitor_manager sync; added in-process fallback (generate_unified_supervisor_config + supervisorctl reread/update) so AES/ATS tear down even if monitor_manager is unreachable.
2. **Activate** — main_app only set status in DB; added same sync (HTTP to monitor_manager + in-process generate + supervisorctl) so AES/ATS spin up when a monitor is re-enabled.
3. **Documentation** — Clarified in code and `docs/MASTER_DB_SCHEMA_REFERENCE.md`: `status` = script lifecycle (active/inactive); `auto_trade` / `auto_trade_status` = auto-trading only.
4. **Dashboard UI** — On status-light click, tile and light update immediately (optimistic); pointer-events disabled on the light until request completes to prevent double-clicks; revert on API failure. Applied on desktop and mobile dashboard.

## Completion criteria

- [x] Deactivate tears down AES/ATS promptly (in-process fallback).
- [x] Activate spins up AES/ATS promptly (same sync path).
- [x] status vs auto_trade documented in schema and key code paths.
- [x] Dashboard: tile greys/un-greys and light flips on click; no repeat-clicks during request.
