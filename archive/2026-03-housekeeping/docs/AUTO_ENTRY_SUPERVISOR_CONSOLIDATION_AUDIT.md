# Auto Entry Supervisor — Consolidation Audit (High Level)

**Goal:** House all automated-trade functionality in a **single process** (one script instance) while keeping **strict discipline** between monitors so no streams cross and no errant trades.

**No code changes in this doc — analysis and design observations only.**

**Ballpark CPU impact (for future todo):** Today each supervisor process is ~6–7% of one core; 8 monitors ≈ 50% of one core total. After consolidation, one process does the same work but without 7× process/thread overhead. Total auto_entry CPU would likely drop to ~35–45% of one core. **Roughly 5–15% of one core freed in total, or ~1–2% of one core freed per active monitor.** The gain is from removing duplicate process/thread overhead, not from doing less work per monitor.

---

## How It Works Today

- **One process per monitor.** Identity comes from argv (e.g. `0001_10002`). That value is fixed for the life of the process.
- **All “current monitor” state is global:** `MONITOR_ID`, `USER_NUMBER`, `MONITOR_SYMBOL`, `MONITOR_MARKET`, `_LAST_MONITOR_STATE`, `auto_entry_indicator_state`, `previous_auto_trade_status`, `previous_settings`, `previous_indicator_state`, plus strategy-specific globals (e.g. `momentum_breakout_trades_entered`). There is no second monitor in the same process, so no cross-talk.
- **DB and API are already monitor-keyed.** Every query uses `WHERE id = %s` with `MONITOR_ID`. Trades sent to trade_manager include `"monitor": "mon_0001_{MONITOR_ID}"`. Strike tables are per symbol; symbol/market come from `monitor_list` for this monitor.
- **One thread per process:** a single `monitoring_worker` loop that runs every 1s: `cleanup_old_cooldowns()` then `check_auto_entry_conditions()` then `sleep(1)`.
- **One Flask app per process**, one port per monitor (`get_monitor_port("auto_entry_supervisor", MONITOR_IDENTIFIER)`). Frontend hits that port for that monitor’s indicator/scanning status.

So today, isolation is **process boundary + single monitor identity**. Discipline is “this process only ever touches this monitor’s row and this monitor’s state.”

---

## High-Level Observations for a Single Process

### 1. State must become per-monitor, not global

Every piece of state that today is “the current monitor’s” must be keyed by monitor in one process:

- **In-memory:** e.g. `_last_monitor_state[monitor_id]`, `auto_entry_indicator_state[monitor_id]`, `previous_auto_trade_status[monitor_id]`, `previous_settings[monitor_id]`, and any strategy globals (e.g. `momentum_breakout_trades_entered[monitor_id]`).
- **Thread-local or context object:** Alternatively, pass a small context (monitor_id, user_number, symbol, market) through the call chain and keep one global dict keyed by monitor_id. No function should read “current monitor” from a process-wide global; they should receive the monitor context for this iteration.

Strict discipline: **when handling monitor A, only read/write state for A.** No shared mutable state between monitors.

### 2. One loop, iterate over monitors

- **Discovery:** At startup (and optionally periodically), load the set of monitors that get auto-entry — e.g. from `monitor_list` where `auto_trade = true` (and any other filters you use). That set is “active monitors.”
- **Loop:** Same 1s cadence. Each tick: for each active monitor (in a deterministic or rotating order), run the equivalent of `cleanup_old_cooldowns(monitor_id)` and `check_auto_entry_conditions(monitor_id)`. No second thread per monitor; one thread does all monitors in sequence.
- **Failure isolation:** Per-monitor try/except. If one monitor’s logic throws, log and continue to the next. One monitor’s exception or bad data must not stop others.

So you keep “one iteration per second” in spirit, but each iteration is “do one pass for every monitor” instead of “do one pass for the only monitor.”

### 3. All call paths take explicit monitor context

- **No more `MONITOR_ID` / `get_monitor_identifier()` at module level.** Functions that today use `MONITOR_ID`, `get_current_monitor_symbol()`, `get_auto_entry_settings()`, etc. must receive the monitor (id or context) as an argument. Helpers like `get_current_monitor_symbol()` become `get_monitor_symbol(monitor_id)` or live on a context object.
- **DB and HTTP unchanged in shape.** Queries stay `WHERE id = %s` with the monitor id; trade payloads still include `"monitor": "mon_0001_{monitor_id}"`. Only the source of that id changes (argument instead of global).
- **Strike table:** Symbol and market come from `monitor_list` for the current monitor in the loop. So `get_master_strike_table_data()` (or equivalent) takes monitor_id, looks up symbol/market for that monitor, then hits the same per-symbol strike table as today.

Discipline: **every DB write and every trade submission is explicitly for the monitor id passed in.** No implicit “current” monitor.

### 4. Trade submission stays monitor-tagged

- **Real and simulated trades:** `trigger_auto_entry_trade` and any simulated-trade path already send `monitor` in the payload. In a single process they must receive the monitor id for this pass and set `"monitor": "mon_0001_{monitor_id}"` from that. trade_manager already uses that field; no change on that side for correctness.
- **Atomicity / double-fire:** Today, separate processes prevent two monitors from sharing state. In one process, double-fire prevention still comes from DB (e.g. cooldowns, can_trade_strike) and any in-process guards keyed by monitor_id (e.g. “already entered this cycle for this monitor”). No shared “we already sent a trade” flag across monitors.

### 5. Flask and ports

- **Single app, monitor in the request:** One Flask app. Routes that today return “this monitor’s” state take monitor id from path or query, e.g. `/api/auto_entry_indicator/<monitor_id>` or `?monitor_id=10002`. The handler looks up `auto_entry_indicator_state[monitor_id]` (or equivalent) and returns it.
- **Ports:** Either one port for the supervisor and all clients (including frontend and main app) pass monitor_id, or you keep multiple ports and have the single process listen on each (more moving parts). Single port + monitor in path/query is the simpler way to keep strict “this request is for this monitor only.”
- **Health:** Health check can report “ok” if the loop is running and optionally list monitor ids; per-monitor health can be a separate route that takes monitor_id.

### 6. Startup and config

- **No monitor in argv.** Process starts with no monitor list. It loads “active monitors” from DB (and optionally re-queries periodically). So the single process is “supervisor for all auto_trade monitors” instead of “supervisor for monitor X.”
- **Port config:** If you move to one port, `get_monitor_port("auto_entry_supervisor", ...)` is no longer used for this service; you’d have one `auto_entry_supervisor` port. Frontend and main app would call that one endpoint with monitor_id.

### 7. Order and fairness

- **Order of monitors in the loop:** If you always iterate in the same order (e.g. by monitor id), the first monitor gets first look every second. You could rotate the order each tick or shuffle to avoid systematic bias; or accept a fixed order and document it. No change to correctness, only to which monitor is “first” when multiple could fire in the same second.
- **Single thread:** One thread keeps the model simple and avoids locking. Per-monitor work is still the same DB and HTTP calls as today; you’re just doing N monitors’ worth in sequence. If N is large and one pass exceeds 1s, you’d need to either shorten per-monitor work or relax “one full pass per second” (e.g. spread monitors across ticks). For moderate N, one thread is likely enough.

---

## Summary: What Strict Discipline Means in One Process

| Concern | How to preserve it |
|--------|---------------------|
| No cross-monitor state | All mutable state keyed by monitor_id (or in a context that’s only ever for one monitor). |
| No wrong monitor on a trade | Every trade path gets monitor_id as argument and sets `"monitor": "mon_0001_{id}"` in the payload. |
| No wrong monitor on DB | Every query that today uses MONITOR_ID takes monitor_id as argument; no global “current” monitor. |
| One monitor’s failure doesn’t kill others | Per-monitor try/except in the loop; log and continue. |
| Frontend sees correct per-monitor state | Routes take monitor_id; response is from that monitor’s state only. |

The current design already enforces “one monitor per process.” A single-process design keeps the same logical boundaries by making monitor identity **explicit in every call** and **keying all state by monitor_id** instead of relying on one global identity per process.
