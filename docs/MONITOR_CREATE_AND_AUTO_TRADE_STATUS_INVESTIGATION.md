# Monitor create + auto_trade_status investigation

**Context:** User created two new monitors on production. (1) New AES/ATS processes did not spin up until after a MASTER_RESTART. (2) When the auto-trade toggles were turned on (`auto_trade = TRUE`), the displayed `auto_trade_status` did not update; after restart, AES still did not update the status from the toggle.

---

## 1. Intended behavior

- **New monitor:** `POST /api/monitor/create` is proxied from main_app to **monitor_manager** (Flask, port 8012). monitor_manager inserts the row (with `auto_trade = FALSE`, `auto_trade_status = 'off'`) then calls `spawn_monitor_processes(monitor_data)`, which runs `generate_unified_supervisor_config.py`, then `supervisorctl reread` and `supervisorctl update`, so new AES and ATS processes for that monitor should start without a full restart.
- **Auto-trade toggle:** Frontend calls `POST /api/monitor/toggle-auto-trade` (main_app). Main_app updates **only** `auto_trade` in the DB (comment: "do NOT change auto_trade_status") and broadcasts `auto_trade_toggled` over WebSocket so the toggle switch and `monitor.autoTrade` update. The **status label** (ACTIVE / INACTIVE / OFF) is driven by `auto_trade_status`, which is **only** written by **AES** (auto_entry_supervisor). AES computes status (e.g. DISABLED when `auto_trade` is off, ACTIVE/INACTIVE when on) and writes it via `update_auto_entry_status_in_db()` and notifies the frontend via `POST /api/notify_auto_trade_status_change`.

---

## 2. Why new AES/ATS did not start until MASTER_RESTART

- **Code path:** `create_monitor()` in `backend/monitor_manager.py` (lines 1948–1954) does call `spawn_monitor_processes(monitor_data)` after the insert. So in code, spawn is invoked.
- **Possible causes on prod:**
  - **Subprocess/env:** When monitor_manager runs under supervisor, `subprocess.run([sys.executable, ...], ...)` and `get_supervisorctl_path()` / `get_supervisor_config_path()` use paths derived from `backend.util.paths` (project root from `__file__`). If supervisor does not set `PATH` such that `supervisorctl` is found, or if the config path is wrong for the prod layout, `reread`/`update` could fail.
  - **Return value ignored:** `create_monitor()` does not check the return value of `spawn_monitor_processes()`; if spawn fails, the API still returns 200 and "Monitor created successfully."
  - **Logs:** monitor_manager logs errors in `spawn_monitor_processes` (e.g. "Error regenerating supervisor config", "Error rereading supervisor config") but those are only visible in monitor_manager logs, not in main_app.

**Recommendation:** On prod, after a create-monitor call, check `/opt/rec_io_server/logs/monitor_manager.out.log` and `.err.log` for spawn errors. Add a check in `create_monitor()`: if `spawn_monitor_processes()` returns False, return 207 or 503 and a message so the frontend can surface "Monitor created but processes failed to start; try MASTER_RESTART or contact support." Optionally have main_app proxy or surface spawn result when delegating to monitor_manager.

---

## 3. Why auto_trade_status did not update when toggle was turned on

- **Toggle path:** main_app only sets `auto_trade` and broadcasts `auto_trade_toggled`. It deliberately does **not** set `auto_trade_status`. The UI updates the **toggle** from `auto_trade_toggled` and updates the **status text** only from `auto_trade_status_change`.
- **Who updates auto_trade_status:** Only AES, in two places:
  - **`update_auto_entry_status_in_db(status)`** — writes `auto_trade_status` in DB and calls `POST /api/notify_auto_trade_status_change`. It is invoked from **`broadcast_auto_entry_indicator_change()`**.
  - **`broadcast_auto_entry_indicator_change()`** is **not** called every tick. It is only called from inside **strategy-specific** code (e.g. `check_auto_entry_conditions_hourly_htc`, Momentum Breakout, etc.). So when the user turns the toggle on, no one triggers an immediate re-evaluation; the status only updates the next time that monitor’s AES runs a path that calls `broadcast_auto_entry_indicator_change()` (and then only if the computed state is different from `previous_indicator_state`).
- **New monitors:** If AES for the new monitors did not run at all until after MASTER_RESTART (because spawn had failed), then until the restart there was no process to ever call `update_auto_entry_status_in_db` or `broadcast_auto_entry_indicator_change`, so the DB and frontend would never get a new `auto_trade_status`.
- **After restart:** User reported that even after restart, AES did not update the status when they toggled on. That is consistent with: (a) the status is only pushed when `broadcast_auto_entry_indicator_change()` runs, and (b) that is only called from strategy branches (e.g. when TTC is in window, or when `auto_trade_enabled` is false and we broadcast DISABLED). If the strategy path for that monitor does not run soon (e.g. missing settings, or strategy-specific guard), or if `previous_indicator_state` already matches the new status so the broadcast is skipped, the frontend would not see an update. There is also a **bug** in `broadcast_auto_entry_indicator_change()`: it calls `update_auto_entry_status_in_db(new_status)` first, then later does `if previous_indicator_state == current_state_key: return` — but `update_auto_entry_status_in_db` already has its own `previous_auto_trade_status` check and only logs when status changes; it still **writes** and notifies. So the DB and notify are done. However, the **second** notification (the one inside `broadcast_auto_entry_indicator_change` that POSTs to `notify_auto_trade_status_change`) is only sent when `previous_indicator_state != current_state_key`. So the flow is: we always call `update_auto_entry_status_in_db(new_status)` (which updates DB and sends one notify), then we might skip the rest of the function (and the duplicate notify) if state didn’t change. So the main gap is that **broadcast_auto_entry_indicator_change() is not called on a fixed interval**; it’s only called when strategy logic runs and reaches one of the call sites. So after a toggle, the next status push might be delayed until the next time that strategy path runs (e.g. next TTC window or next cooldown update).

**Recommendation (short term):** When main_app’s `toggle_auto_trade` sets `auto_trade = TRUE`, also set `auto_trade_status` to a sensible initial value (e.g. `'INACTIVE'` or `'ACTIVE'` based on a simple rule or leave as-is and only fix the push). Better: have main_app, after updating `auto_trade`, call an internal or monitor_manager endpoint that asks the **AES for that monitor** to do one immediate status re-evaluation and broadcast (if such an endpoint exists or can be added). Alternatively, ensure AES calls `broadcast_auto_entry_indicator_change()` (or at least `update_auto_entry_status_in_db(determine_auto_entry_status())`) on a regular interval (e.g. every N seconds) when `auto_trade` is true, so that a toggle quickly reflects.

**Recommendation (cleaner):** Add a small “status sync” in the main AES loop: once per tick (or every 10–30 seconds), if `is_auto_trade_enabled()` is true, call `determine_auto_entry_status()` and `update_auto_entry_status_in_db(status)` so that DB and frontend stay in sync even when strategy-specific broadcast is not invoked. That way toggling auto_trade on will be reflected in status within one tick.

---

## 4. Summary

| Issue | Cause | Next step |
|-------|--------|-----------|
| New AES/ATS not starting after create | spawn_monitor_processes() may be failing on prod (subprocess/env); return value not checked | Check monitor_manager logs on prod; consider returning spawn result from create and surfacing in UI |
| auto_trade_status not updating when toggle on | Only AES updates it, and only when strategy code calls broadcast_auto_entry_indicator_change(); no periodic status sync | Have toggle set an initial status and/or have AES periodically call update_auto_entry_status_in_db(determine_auto_entry_status()) when auto_trade is on |

---

## 5. Files to change (for fixes)

- **Spawn feedback:** `backend/monitor_manager.py` — `create_monitor()`: check return value of `spawn_monitor_processes()`; optionally return 207/503 and message. main_app proxy could forward that.
- **Status sync when toggle on:** Either (A) `backend/main.py` — in `toggle_auto_trade`, after updating `auto_trade`, set `auto_trade_status` to e.g. `'INACTIVE'` and call `notify_auto_trade_status_change` so the label updates immediately; or (B) `backend/auto_entry_supervisor.py` — in the main loop, periodically (e.g. every tick or every 30s) when `is_auto_trade_enabled()` call `update_auto_entry_status_in_db(determine_auto_entry_status())` so status stays in sync without relying only on strategy-specific broadcast.
