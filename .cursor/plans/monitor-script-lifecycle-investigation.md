# Monitor script lifecycle: spawn, kill, and verification

**Goal:** Document how monitor script iterations are spun up on monitor creation and torn down on deactivation, and confirm there are no lingering processes; identify gaps and optional hardening.

**Scope:**
- **In:** Create-monitor flow (spawn), deactivate-monitor flow (kill), supervisor config generation, status watcher, verification of process cleanup.
- **Out:** Changing trading logic, frontend UI redesign, multi-user monitor_list (only 0001 is in scope).

**Status:** done (investigation completed; optional hardening documented in steps 3–5)

---

## Current behavior (findings)

### Spawn (new monitor)

1. **Frontend:** User creates monitor → `POST /api/monitor/create` (Flask app in `backend/monitor_manager.py`).
2. **DB:** Row inserted into `users.monitor_list_0001` with `status = 'active'`.
3. **Spawn:** `monitor_manager.spawn_monitor_processes(monitor_data)` is called immediately:
   - Runs `scripts/config/generate_unified_supervisor_config.py`, which reads DB and includes only monitors with `status = 'active'` (so the new monitor is included).
   - Writes unified supervisor config; each active monitor gets two programs: `auto_entry_supervisor_{user}_{id}` and `active_trade_supervisor_{user}_{id}` (both with `stopasgroup=true,killasgroup=true`).
   - `supervisorctl -c <config> reread` then `supervisorctl update` → supervisor starts the new programs.

### Kill (deactivate via UI)

1. **Frontend:** User toggles monitor off → `POST /api/monitor/deactivate` (FastAPI in `backend/main.py`).
2. **DB:** `UPDATE ... SET auto_trade = FALSE, status = 'inactive'` for that monitor. No call to monitor_manager or supervisor.
3. **Indirect teardown:** A separate service, **monitor_manager** (Flask on port 8012), runs a **MonitorStatusWatcher** thread that polls `users.monitor_list_0001` every **10 seconds**. On status change it calls `sync_monitor_processes()`:
   - `get_active_monitors()` → only `status = 'active'`.
   - `get_running_monitor_processes()` → `supervisorctl status`, filter to RUNNING `auto_entry_supervisor_*` and `active_trade_supervisor_*`.
   - For any running monitor not in active list, `remove_monitor_processes(monitor)` is called:
     - Regenerates unified supervisor config (deactivated monitor no longer in `_get_active_monitors()`, so its two programs are omitted).
     - `supervisorctl reread` then `supervisorctl update` → supervisor stops and removes the programs for that monitor.

So teardown is **eventual**: up to ~10s delay after deactivate until processes are removed. There is **no explicit verification** that no Python (or child) processes for that monitor remain after `update`.

---

## Steps

1. **Document the flows** (spawn and deactivate) in one place: entrypoints, DB changes, which process runs supervisor config generation and `reread`/`update`, and the 10s watcher role. *(Done above; can be moved to a short doc under `docs/` if desired.)*
2. **Confirm supervisor behavior:** Verify that after `reread` + `update`, programs removed from the config file are actually stopped (and that `stopasgroup`/`killasgroup` are sufficient for any child processes). Optional: add a single manual test (create monitor → deactivate → check supervisor status and `ps` for that monitor id).
3. **Assess deactivate latency:** Decide if 0–10s delay is acceptable. If not, consider having `POST /api/monitor/deactivate` trigger immediate sync (e.g. call monitor_manager’s sync endpoint or run sync in-process if same deployment).
4. **Lingering-process verification:** After `remove_monitor_processes`, add an optional or diagnostic check that no process whose command line contains the monitor identifier (e.g. `active_trade_supervisor_0001_10001` or `auto_entry_supervisor_0001_10001`) remains (e.g. `pgrep -f` or equivalent). Document result; optionally fail or alert if lingering found.
5. **Note any env-specifics:** If monitor_manager is not running (e.g. dev), deactivate will never tear down processes; document that and any runbook (e.g. “run sync_monitor_processes or restart supervisor”).

---

## Completion criteria

- [ ] Spawn path (create → supervisor programs started) is documented and confirmed.
- [ ] Kill path (deactivate → DB → status watcher → sync → remove_monitor_processes → supervisor update) is documented and confirmed.
- [ ] Supervisor actually stops removed programs (and no stray child processes); documented or tested.
- [ ] Decision on 10s delay is recorded; if “must be immediate,” a concrete change (e.g. deactivate calls sync) is proposed.
- [ ] Optional verification for lingering processes is implemented and documented, or explicitly declined with reason.

---

## Blockers / decisions

- **Optional:** Add “verify no lingering processes” step after `remove_monitor_processes` (e.g. in a script or inside monitor_manager). Decide: always-on vs diagnostic-only vs skip.
- **Optional:** Have `POST /api/monitor/deactivate` trigger immediate sync (e.g. HTTP call to monitor_manager or shared sync routine) instead of relying only on the 10s poll.
