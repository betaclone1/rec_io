# Logging inventory

Inventory of what each script logs and where. Used for the logging audit (see `docs/LOGGING_INVENTORY.md`).  
**Default philosophy (most persistent scripts):** Quiet by default. Log errors/failures, one-line startup, optional one-line outcome per cycle, heartbeat when we have it. Routine success and raw dumps → DEBUG or remove. See initiative doc §4.  
**Format and consistency:** One mechanism (logging), one timestamp format (ISO 8601 + TZ), one line format; consistent errors, startup, restart, heartbeat. See initiative doc §5.  
**Constraint:** Cleanup is logging-only. Do not change script behavior, logic, control flow, API calls, or DB writes; only what and how we log.  
**Capture:** All output goes to supervisor stdout/stderr unless noted. Supervisor writes to `logs/{program_name}.out.log` and `logs/{program_name}.err.log` (with rotation; see docs/CRITICAL_ASSET_LOGGING.md for supervisord and critical-service retention). **No duplication:** supervised scripts should log only to stdout so supervisor is the single destination; no script-owned log files or FileHandlers unless there is a documented exception (initiative §5.9).

---

## 1. Supervisor program scripts (backend)

### main_app — entry `backend/main.py`, setup `backend/web/main_app_logging.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` (logger name **`main_app`**). EST formatter, single handler to stdout with flush—configured in **`main_app_logging.py`** (`get_main_app_logger()`). Route modules use `logging.getLogger("main_app")` for the same logger. |
| **Destination** | stdout → supervisor. Admin/UI log viewers still read `logs/{script_name}.out.log` via routes implemented under **`backend/web/routers/`** (not in slim `main.py`). |
| **Volume** | INFO: startup (port, main app started/shutting down). WARNING: PostgreSQL/AUTH/Preferences/MAIN forwarding errors, sync failed, API errors. DEBUG: all per-request success (forwarding, client connect/disconnect, preferences updated, momentum/BTC price, etc.). |
| **Notable** | One-line startup; errors upgraded to warning so they appear at default level; routine traffic at DEBUG to avoid storage ballooning. |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Logging setup (EST, flush); print→logger; errors→warning, routine→debug.

---

### trade_manager — `backend/trade_manager.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` (logger name `trade_manager`). EST formatter, single handler to stdout with flush. `log(msg)` → INFO; `log_debug(msg)` → DEBUG. `log_event(ticket_id, message)` → PostgreSQL via `backend.util.trade_logger.log_trade_event` (unchanged). |
| **Destination** | stdout → supervisor; PostgreSQL for trade events (unchanged). |
| **Volume** | INFO: lifecycle (trade opened/closed, confirmations, PnL), errors, failsafe, trading disabled. DEBUG: SENDING/EXECUTOR RESPONSE, STATUS UPDATE RECEIVED, CONFIRMING CLOSE TRADE, NOTIFIED ATS, 💾 write confirmations, STORING ORDER_ID, WAITING FOR POSITION, performance refresh, high_price retrieval, Skipping PostgreSQL (no connection). |
| **Notable** | Internal heartbeat every 5 min. All former `print()` routed through `log()` (INFO) or `log_debug()` (DEBUG). DB write confirmations and executor plumbing at DEBUG. |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Logging setup (EST, flush, heartbeat); log/log_debug split; print→log; plumbing→DEBUG, lifecycle/errors→INFO. loss_prevention INFO line still to add when touching cycle processing.

---

### trade_executor — `backend/trade_executor.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `log_event(ticket_id, message, trade_id=None)` → `print(log_message, flush=True)` + `log_trade_event(..., service="trade_executor")` to PostgreSQL. |
| **Destination** | stdout → supervisor; PostgreSQL (trade/event log). |
| **Volume** | Low; one sequence per trade attempt (RECEIVED TICKET, CREDENTIALS, REQUEST, RESPONSE, SUCCESS/REJECTED). All lines include **trade_id=X** (hero id from users.trades_<slot>) when present so the full pipeline is traceable by id. |
| **Notable** | trade_manager now inserts the trade row before calling the executor (opens) so executor always receives and logs the hero id; closes already sent id. Rejection log (see below) for liquidity ceiling tracking. |
| **Extra files** | `logs/insufficient_resting_volume_rejections.jsonl` — see below. |

**Traceability (2026-03):** trade_manager open flow reordered to insert first and pass `id`; trade_executor logs `trade_id=<id>` on every line so grep for a trade id shows the full send/response sequence.

**Insufficient resting volume rejection log:** When Kalshi rejects an order with `fill_or_kill_insufficient_resting_volume` (or any response containing "insufficient_resting_volume"), the executor appends one JSON object per line to `logs/insufficient_resting_volume_rejections.jsonl`. **Monthly rotation:** at first write in a new month, the existing file is renamed to `insufficient_resting_volume_rejections_YYYY-MM.jsonl` and a fresh `.jsonl` is used for the current month. Fields: `timestamp_utc`, `timestamp_est`, `intent`, `ticker`, `contract`, `symbol`, `monitor`, `position_count_fp`, `position`, `side`, `trade_id`, `ticket_id`, `kalshi_error_code`, `response_status`. **Rationale:** as bankroll grows and position sizes increase, a rise in these rejections indicates we may be running into a liquidity ceiling for that market—the log provides a time series to spot when and where that happens.

---

### kalshi_account_sync — `backend/kalshi_account_sync_ws.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` only (logger name `kalshi_account_sync`). EST formatter, single handler to stdout. |
| **Destination** | stdout → supervisor. |
| **Volume** | Low at INFO. One-line startup, connect/subscribe, sync outcomes (Balance/Positions/Fills/Settlements/Orders sync OK), heartbeat every 5 min, errors/warnings. All retries, raw dumps, "Response keys", and write confirmations at DEBUG. |
| **Notable** | Raw positions response and full WebSocket position dumps removed (were print); single DEBUG line per position update. Internal heartbeat: `logger.info("heartbeat")` in periodic_polling_task (every 5 min). |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Replaced all 215 `print()` with logger; EST timestamps; one-line outcomes per sync; heartbeat; no behavior change.

---

### symbol_price_watchdog_btc / symbol_price_watchdog_eth — `backend/symbol_price_watchdog.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` only (logger name `symbol_price_watchdog`). EST formatter, single handler to stdout with flush after each emit. |
| **Destination** | stdout → supervisor. No script-owned log or heartbeat files. |
| **Volume** | INFO = heartbeat every 5 min + errors/warnings only. Startup and prev_day_avg flow at DEBUG. |
| **Notable** | Internal heartbeat: `logger.info("heartbeat")` every 5 min (Coinbase and Yahoo paths). Only log when something goes wrong otherwise. |
| **Extra files** | None. Heartbeat file write removed; heartbeat to stdout only (initiative §5.9). |

**Phase 2 done (2026-03):** Replaced all `print()` with logger; removed DEBUG sys.path; EST timestamps; real-time flush; removed heartbeat file (single destination); added 5 min internal heartbeat; no behavior change.

---

### kalshi_market_watchdog_* — **ARCHIVED**

Legacy REST poller moved to `archive/2026-03-legacy-kalshi-market-watchdog/kalshi_market_watchdog.py`. Not started by unified supervisor.

---

### market_watchdog_ws_kalshi_hourly / market_watchdog_ws_kalshi_15m — `backend/market_watchdog_ws.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` (logger name `market_watchdog_ws`). EST-style formatter, stdout with flush. |
| **Destination** | stdout → supervisor (`logs/market_watchdog_ws_kalshi_hourly.out.log`, `logs/market_watchdog_ws_kalshi_15m.out.log`). |
| **Volume** | INFO = rollover, subscription changes, lifecycle/trade outcome lines, heartbeats; WARNING = discovery timeouts, partial rollover; errors as exceptions. |
| **Notable** | WebSocket for ticker (+ optional `market_lifecycle_v2`); REST only during rollover discovery (bounded retry). |
| **Extra files** | None. |

---

### `backend/market_watchdog.py` (shared module, not a supervisor program)

| Aspect | Details |
|--------|---------|
| **Mechanism** | Imported by `market_watchdog_ws` for public REST helpers (`fetch_event_json`, DB symbol order, event ticker helpers) and serialized `_kalshi_public_get`. |
| **Destination** | N/A (no standalone process). |
| **Notable** | Do not confuse with `market_watchdog_ws.py`, which is the running ingest service. |

---

### system_monitor — `backend/system_monitor.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` (logger name `system_monitor`). EST formatter, single handler to stdout with flush. |
| **Destination** | stdout → supervisor. Writes health report to **database** (unchanged). |
| **Volume** | INFO: startup, duplicate processes detected/killing, failed services, recovery (restarted X, system recovered), MASTER RESTART (triggered/disabled), restart completion. DEBUG: one line per cycle "Health: N/M services, CPU X%", discovery, supervisor unavailable, local dev mode, health report saved, "Attempting to restart" detail. |
| **Notable** | Full per-cycle dump removed; one DEBUG line per cycle when healthy; INFO only when there is something to act on (failures, recovery, MASTER RESTART). |
| **Extra files** | Database (system.health_status). |

**Phase 2 done (2026-03):** Logging setup (EST, flush); one-line summary per cycle at DEBUG; failures/recovery/MASTER RESTART at INFO/WARNING.

---

### monitor_manager — `backend/monitor_manager.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` only (logger name `monitor_manager`). EST formatter, single handler to stdout with flush. `log_event()` maps event types to levels. |
| **Destination** | stdout → supervisor. |
| **Volume** | INFO = heartbeat every 5 min, errors, **monitor create** (with monitor_id), **monitor deactivated** (with monitor_id), **bankroll sync completed**, **monitor process sync completed/failed** (failsafe/recovery with monitor_id), **monitor removed from database**. All TIMING, STATS_UPDATE, TRADE_UPDATE, PERIODIC_UPDATE, LOG_CLEANUP, sync details, strategy defaults, cleanup at DEBUG. |
| **Notable** | Internal heartbeat every 5 min. Explicit INFO lines for create, deactivate, bankroll, and process sync (recovery) with monitor IDs. |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Replaced all `print()` with logger; EST timestamps; real-time flush; 5 min heartbeat; log_event maps to levels; INFO for create/deactivate/bankroll/failsafe only; no behavior change.

---

### cascading_failure_detector — `backend/cascading_failure_detector.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` (logger name `cascading_failure_detector`). EST formatter, single handler to stdout with flush. `_log_event(msg)` → info; `_log_event(msg, level="debug")` and level-based status. |
| **Destination** | stdout → supervisor. |
| **Volume** | INFO: startup (one line), CATASTROPHIC/CRITICAL/WARNING/MASTER RESTART/recovery/errors. DEBUG: "Discovered N services", "System healthy - N/M services running" (per 5-min check). |
| **Notable** | Healthy check every 5 min at DEBUG only; warning/critical/catastrophic and restart/recovery at INFO/WARNING/ERROR. |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Logging setup (EST, flush); healthy at DEBUG; degraded/restart/recovery at INFO+.

---

### auto_entry_supervisor_{user}_{monitor_id} — `backend/auto_entry_supervisor.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` (logger name `auto_entry_supervisor`). EST formatter, single handler to stdout with flush. `log(msg)` → INFO; `log_debug(msg)` → DEBUG. |
| **Destination** | stdout → supervisor. |
| **Volume** | INFO: startup (user, monitor, symbol, port), **spike started** / **spike ended** (monitor_id), STATUS CHANGE (auto_trade_status), SPIKE DETECTED, RECOVERY COMPLETE, errors (❌). DEBUG: cooldown/notification sent, symbol/market change, settings changed, check #N, position loaded, "No monitor found", recovery in progress, still in spike conditions, started/reset cooldown DB, heartbeat detail. |
| **Notable** | Internal heartbeat every 5 min. Explicit `_aes_logger.info("spike started monitor_id=%s", MONITOR_ID)` and `"spike ended monitor_id=%s"` for cooldown lifecycle. auto_trade_status change already at INFO. |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Logging setup (EST, flush, heartbeat); log/log_debug; spike started/ended at INFO; plumbing→DEBUG.

---

### active_trade_supervisor_{user}_{monitor_id} — `backend/active_trade_supervisor.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` (logger name `active_trade_supervisor`). EST formatter, single handler to stdout with flush. `log(msg)` → INFO; `log_debug(msg)` → DEBUG. |
| **Destination** | stdout → supervisor. |
| **Volume** | INFO: startup (user, monitor, symbol, port), trade lifecycle (POSITIVE/NEGATIVE SPIKE trigger, Closed N trades, Triggered AUTO STOP close, auto stop failed, errors). DEBUG: MONITORING HEARTBEAT, MONITORING Checking N trades, symbol/market change, frontend notification sent/failed, verification period started/in progress/ended (detail), "No monitor/strategy found", MS defaults, HTC debug. |
| **Notable** | Internal heartbeat every 5 min. Trade entry/closure details and spike triggers kept at INFO. |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Logging setup (EST, flush, heartbeat); log/log_debug; plumbing→DEBUG; lifecycle and errors at INFO.

---

### strike_table_generator_* — `backend/strike_table_generator.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging` only (logger name `strike_table_generator`). EST formatter, single handler to stdout with flush after each emit. |
| **Destination** | stdout → supervisor. |
| **Volume** | INFO = heartbeat every 5 min + errors + **strike table rotation** (one line when event/market changes: "Strike table rotated: X → Y (N strikes)"). All other flow (init, connect, loaded data, processing, generated, iteration, summary, waiting) at DEBUG. |
| **Notable** | Same as market wd: log when we switch to a new market/event so we see rotations without per-iteration noise. |
| **Extra files** | None. |

**Phase 2 done (2026-03):** Replaced basicConfig with EST + FlushingStreamHandler; return (success, event_ticker, num_strikes) from generate_strike_table; rotation log + 5 min heartbeat in continuous loop; all success-path INFO→DEBUG; no behavior change.

---

## 2. Config / one-off scripts that log

### generate_unified_supervisor_config — `scripts/config/generate_unified_supervisor_config.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | `logging.basicConfig(level=logging.INFO)`, `logger = logging.getLogger(__name__)`. |
| **Destination** | stdout/stderr (run by MASTER_RESTART, not as a long-lived supervisor program). |
| **Volume** | Low. Init, "Generating...", "Generated...", "Found N active monitors", port load/fallback, validation pass/fail, env error. |
| **Extra files** | None. |

**Cleanup ideas:** None critical; already reasonable.

---

## 3. Other log writers (not in supervisor list)

### kalshi_market_ticker_websocket — `backend/api/kalshi-api/kalshi_market_ticker_websocket.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | When run as `__main__`: redirects **stdout and stderr** to a file: `sys.stdout = sys.stderr = log_file`. |
| **Destination** | **Extra file:** `{get_logs_dir()}/kalshi_websocket_market.log` (i.e. `logs/kalshi_websocket_market.log`). Opened in append mode. |
| **Volume** | Whatever the websocket code prints (no rotation; file grows). |
| **Note** | Not in supervisor service list; may be run manually or by another process. |

**Cleanup ideas:** If we keep this script, either run it under supervisor (so stdout/stderr go to .out.log/.err.log with rotation) or add rotation for this file and document it.

---

### trade_logger — `backend/util/trade_logger.py`

| Aspect | Details |
|--------|---------|
| **Mechanism** | Used by trade_manager's `log_event()`. Writes to **PostgreSQL** (trade/event log table), not a file. |
| **Destination** | Database. |
| **Note** | Not a file log; listed for completeness. |

---

### Heartbeat files — (legacy) `symbol_price_watchdog_finance` if used

`backend/symbol_price_watchdog.py` no longer writes a heartbeat file (Phase 2 done); heartbeat is to stdout only. If `symbol_price_watchdog_finance.py` is used, it may still write to `{get_btc_price_history_dir()}/{heartbeat_file}`; document if that remains an exception.

---

### Analytics / daily_update / weekly_update (if run)

| Aspect | Details |
|--------|---------|
| **Files** | `backend/util/analytics/daily_update.py`, `analytics_updater.py`, etc. write to timestamped files under `backend/logs/` or project `logs/` (e.g. `daily_update_{timestamp}.log`, `weekly_update_{timestamp}.log`). |
| **Note** | Not supervisor services; run via cron or manually. Include in rotation policy if we keep them. |

---

## 4. Summary table

| Script (program or file) | Mechanism | Extra files | Volume | Priority cleanup |
|--------------------------|-----------|-------------|--------|------------------|
| main_app (`main.py` + `web/routers` + `main_app_logging`) | `main_app` logger | — | Low (INFO) | Phase 2 done; errors→warning |
| trade_manager.py | log/log_debug + log_event(DB) | heartbeat | Med (INFO) | Phase 2 done |
| trade_executor.py | print | — | Low | logging |
| kalshi_account_sync_ws.py | print | — | High | logging; raw dumps→DEBUG |
| symbol_price_watchdog.py | print | heartbeat file | Medium | remove DEBUG sys.path; logging |
| market_watchdog_ws.py | logging | — | Medium | archived kalshi_market_watchdog → WS path |
| system_monitor.py | _sm_logger | — | Low (INFO) | Phase 2 done; one line/cycle DEBUG |
| monitor_manager.py | print + log_event | — | High | logging; TIMING→DEBUG |
| cascading_failure_detector.py | _cfd_logger | — | Low (INFO) | Phase 2 done; healthy→DEBUG |
| auto_entry_supervisor.py | log/log_debug | heartbeat | Med (INFO) | Phase 2 done; spike started/ended |
| active_trade_supervisor.py | log/log_debug | heartbeat | Med (INFO) | Phase 2 done |
| strike_table_generator.py | logging | — | Medium | iteration/wait→DEBUG |
| generate_unified_supervisor_config.py | logging | — | Low | OK |
| kalshi_market_ticker_websocket.py | stdout→file | kalshi_websocket_market.log | — | supervisor or rotate file |

---

## 5. Logs folder audit (what’s actually on disk)

Cross-check of the **project `logs/`** directory and other log locations. Done 2026-03-08.

### 5.1 Project `logs/` directory

- **Supervisor program logs:** `{program_name}.out.log`, `{program_name}.err.log` — all accounted for in §1. Many rotated copies (`.log.1`, `.log.2`, …) from past supervisor or manual rotation; no current rotation in generator so active files grow unbounded.
- **Legacy / old program names (no longer in current supervisor):**  
  `kalshi_market_watchdog_*` (script archived 2026-03), per-symbol `strike_table_generator_*`, `symbol_price_watchdog_ndx`, `symbol_price_watchdog_spx`, etc. Current generator uses `market_watchdog_ws_kalshi_hourly`, `market_watchdog_ws_kalshi_15m`, `strike_table_generator_ws_hourly`, `strike_table_generator_ws_15m`. Old `.out.log` files may remain on disk.
- **Dedicated `auto_entry_supervisor_0001_10019.log`:**  
  Single plain `.log` file (no `.out`/`.err`). **main_app** (admin log-serving routes under `backend/web/routers/`) prefers this when serving the “out” log for script name `auto_entry_supervisor_0001_10019` (see §1 main_app). **Current `auto_entry_supervisor.py` does not write to it** — it only prints to stdout (supervisor captures to `.out.log`). So this file was likely from an older code path or a one-off. **Action:** Treat as legacy; document that the UI prefers it if present; consider removing the special case in the log-view route once we standardize on .out.log.
- **log_archive/monitor_log_archive/:**  
  **monitor_manager** moves inactive monitor logs here (cleanup of deactivated monitors). It’s a **destination** for moved `.out.log`/`.err.log` files, not an extra writer. Do not rotate/delete blindly; document as part of retention policy.
- **kalshi_websocket_market.log:**  
  Not present in `logs/` on this run. Written only when `kalshi_market_ticker_websocket.py` is run as `__main__` (§3). If that script is used, the file will appear in `logs/`.

### 5.2 Other log directories (outside project `logs/`)

- **backend/logs/**  
  **daily_update.py**, **daily_update_lightweight.py** (and tests) write here: `daily_update_{timestamp}.log`, `daily_update_lightweight_{timestamp}.log`. Path: `Path(__file__).parent.parent.parent / "logs"` → `backend/logs`. Not under supervisor; run via cron or manually. Include in rotation/retention if we keep these jobs.
- **backend/util/logs/**  
  **analytics_updater.py** (and **weekly_update_OLD.py**) write here: `weekly_update_{timestamp}.log`, `weekly_update_summary_*.json`. Path: `Path(__file__).parent.parent / "logs"` → `backend/util/logs`. Same note: not supervisor; add to rotation if kept.

### 5.3 Summary of previously missed items

| Item | Location | Writer | In §1–4? |
|------|----------|--------|----------|
| Dedicated auto_entry_supervisor_*.log | logs/ | Legacy/test (current code does not write) | main_app log-view route only |
| log_archive/monitor_log_archive/ | logs/ | monitor_manager (moves files here) | Not previously called out |
| daily_update_*.log | backend/logs/ | daily_update.py, daily_update_lightweight.py | §3 “analytics” — path clarified here |
| weekly_update_*.log | backend/util/logs/ | analytics_updater.py | §3 “analytics” — path clarified here |
| Legacy program-named logs (btc, ndx, spx without hourly/15m) | logs/ | Old supervisor config | Not in current generator; document as cruft |

---

## 5.1 Master system event log (dual-write exception)

| Aspect | Details |
|--------|---------|
| **Mechanism** | `backend.util.master_system_log.log_system_event()` — curated high-level events only |
| **Destinations** | Human-readable `logs/master_events.log` (RotatingFileHandler 20MB × 10) **and** PostgreSQL `system.event_log` |
| **CLI** | `scripts/ops/log_system_event.py` for shell scripts (`MASTER_RESTART.sh`, `git_update_system.sh`, prod pull) |
| **Categories** | `RESTART`, `WS`, `DEPLOY`, `TRADING_HALT`, `MAINTENANCE`, `ANOMALY`, `MONITOR`, `BACKUP` |
| **Admin UI** | Admin Tools → System Event Log panel (`GET /api/user/admin/master_events`) |
| **Notable** | Fail-open (never blocks trading/restarts). Per-service detail via `detail_ref` → log-viewer popup. **Lean policy:** one master line per operator MASTER RESTART (success or abort); no maintenance sub-steps; watchdog services suppressed while `core.system_state.mode = maintenance`; no ws_connected / CFD echo of service stdout. |

---

## 6. Next steps (for Phase 2)

- Script-by-script: replace `print` with `logging`, set levels, move verbose/debug lines to DEBUG.
- Remove or gate one-off debug (e.g. main's "[MAIN] 🔔", symbol_price_watchdog's sys.path).
- Add supervisor log rotation (maxbytes + backups) in `generate_unified_supervisor_config.py`.
- Document heartbeat and kalshi_websocket_market.log in rotation/retention policy.
