# Redis migration: legacy comms audit

Systematic checklist of every backend and frontend use of the legacy notify/broadcast API and related comms that can be replaced by the Redis/WebSocket backbone. Work through this asset-by-asset when implementing the refactor.

**Full architecture (read_api, switchboard, main, flow):** [REDIS_ARCHITECTURE.md](REDIS_ARCHITECTURE.md). **Backbone:** [REALTIME_BACKBONE.md](REALTIME_BACKBONE.md). **Initiative plan:** [.cursor/plans/redis-platform-initiative.md](../.cursor/plans/redis-platform-initiative.md). Read/aggregate endpoints currently in main move to **read_api** (one process under supervisor); main drops them and no longer holds db_change_clients or broadcast.

**Process note:** As you work through each asset (new stream, moved endpoint, new consumer), evaluate whether that connection point is a good place to better utilize PostgreSQL—views, materialized views, stored functions, or trigger-maintained summary tables—for the data that connection serves. See REALTIME_BACKBONE Section 9 (checklist).

---

## Summary: legacy surface

| Category | Main.py endpoints | Callers (backend) | Frontend consumers |
|----------|-------------------|-------------------|---------------------|
| **DB change** | `POST /api/notify_db_change` | trade_manager, kalshi_account_sync_ws, main (initiate_transfer) | WS `/ws/db_changes` in 6 places |
| **Preferences / UI events** | `POST /api/notify_auto_trade_status_change`, `notify_cooldown_timer_change`, `notify_automated_trade`, `notify_automated_close`, `broadcast_auto_entry_indicator`, `broadcast_active_trades_change`, `broadcast_monitor_total_position`, `broadcast_monitor_list_update` | trade_manager, active_trade_supervisor, auto_entry_supervisor, monitor_manager, main | WS `/ws/preferences` in 4 places |
| **Main.py internals** | `broadcast_db_change()`, `broadcast_preferences_update()`, `broadcast_account_mode()`, `connected_clients`, `db_change_clients` | main only | Same WS clients |

**Target state:** DB-driven events flow via NOTIFY → switchboard → Redis → WS (and backend Redis subscribers). Preferences-style events flow via Redis `rec_io:preferences` (or equivalent) once that channel and publish helper exist. No HTTP POST to main for notify/broadcast.

---

## Part A: Backend assets

### A1. main_app (legacy checklist: handlers now under `backend/web/routers/` + `main_realtime.py`)

Originally tracked as **`main.py` monolith**; **notify / broadcast / WS** implementations now live in **`backend/web/main_realtime.py`** and related routers. This table remains the migration checklist until Redis-only paths replace the HTTP notify surface.

| Item | Location / function | Current behavior | Migration action |
|------|----------------------|------------------|------------------|
| **Endpoints (remove after callers migrated)** | | | |
| 1 | `POST /api/notify_db_change` | Accepts `db_name`, forwards to `broadcast_db_change()` | Remove when all callers use Redis or DB triggers. |
| 2 | `POST /api/notify_auto_trade_status_change` | Builds message, sends to `connected_clients` | Replace with publish to Redis preferences channel; remove. |
| 3 | `POST /api/notify_cooldown_timer_change` | Same | Same. |
| 4 | `POST /api/notify_automated_trade` | Same | Same. |
| 5 | `POST /api/notify_automated_close` | Same | Same. |
| 6 | `POST /api/broadcast_auto_entry_indicator` | Same | Same. |
| 7 | `POST /api/broadcast_active_trades_change` | Same | Same. |
| 8 | `POST /api/broadcast_monitor_total_position` | Same | Same. |
| 9 | `POST /api/broadcast_monitor_list_update` | Same | Same. |
| **Internal broadcast helpers** | | | |
| 10 | `broadcast_db_change(db_name, change_data)` | Sends to `db_change_clients` | Keep until frontend uses switchboard; then replace with “main subscribes to Redis and calls this” or remove. |
| 11 | `broadcast_preferences_update()` | Sends to `connected_clients` | Replace with publish to Redis; remove or reduce to “forward from Redis.” |
| 12 | `broadcast_account_mode(mode)` | Sends to `connected_clients` | Same. |
| **Call sites (main as caller)** | | | |
| 13 | `broadcast_db_change("subaccounts", ...)` and `("transfers", ...)` | On initiate_transfer | DB trigger for transfers/subaccounts or publish to Redis; remove call. |
| 14 | `broadcast_preferences_update()` | Called from one place | Use Redis preferences. |
| 15 | Various in-app broadcasts (auto trade toggle, paper trade, monitor list, archive, deactivate, activate) | Loop over `connected_clients`, send JSON | Publish to Redis preferences; main may subscribe and forward until frontend points to switchboard. |
| **WS and client sets** | | | |
| 16 | `connected_clients`, `db_change_clients` | Sets of WebSocket connections | Remove when WS served by switchboard and/or main only forwards from Redis. |
| 17 | `GET /ws/preferences`, `GET /ws/db_changes` | Accept WS, add to sets | Remove when frontend connects to switchboard; or keep as proxy that subscribes to Redis and forwards. |

- [ ] A1 done: All endpoints and broadcast helpers above migrated or removed; client sets and WS routes removed or reduced to proxy.

---

### A2. trade_manager.py

| Item | Function / line | Current behavior | Migration action |
|------|------------------|------------------|------------------|
| 1 | `notify_frontend_trade_change()` | POST to main ` /api/notify_db_change` (db_name=trades) | Replace with Redis publish or rely on DB trigger for `users.trades_*` once stream exists. |
| 2 | `notify_strike_table_trade_change(trade_id, status)` | POST to main `/api/notify_db_change` | Same (trades stream) or dedicated stream. |
| 3 | `notify_active_trade_supervisor_direct(...)` | POST to ATS `/api/notify_automated_close` or internal | ATS subscribes to Redis (trades/active_trades stream) or keep internal HTTP until ATS refactor. |
| 4 | `notify_active_trade_supervisor_direct_with_monitor(...)` | Same | Same. |
| 5 | `notify_monitor_manager_trade_closed(...)` | POST to monitor_manager | Monitor manager subscribes to Redis or keep HTTP. |
| 6 | `notify_monitor_manager_trades_closed_by_ticker(...)` | Same | Same. |
| 7 | `broadcast_url` / `requests.post(..., /api/broadcast_active_trades_change)` | Two call sites | Publish to Redis preferences (e.g. `active_trades_change`); remove HTTP. |

- [ ] A2 done: All notify/broadcast calls above use Redis or DB-driven stream; no POST to main for notify/broadcast.

---

### A3. kalshi_account_sync_ws.py

| Item | Function / line | Current behavior | Migration action |
|------|------------------|------------------|------------------|
| 1 | `notify_frontend_db_change(db_name, ...)` | POST to main `/api/notify_db_change` | Replace with Redis publish; or add triggers for fills, positions, settlements, orders, account_balance, subaccounts, transfers and remove calls. |
| 2 | Call sites: account_balance, subaccounts, transfers, positions, fills, settlements, orders | Various lines | Register streams + triggers for those tables; or keep single publish helper for “db_change” and pass db_name. |
| 3 | `notify_monitor_manager(bankroll_stepped_down)` | POST to monitor_manager `/api/bankroll_updated` | Optional: publish to Redis; monitor_manager subscribes. |
| 4 | `_notify_trade_manager_positions_updated` | POST trade_manager `/api/positions_updated` | When `USE_TRADING_REDIS_COMMS`: `publish_positions_updated_notification` on `REDIS_CHANNEL_TM_POSITIONS_UPDATED` (default `rec_io:tm:positions_updated`); `trade_manager` subscriber calls `apply_positions_updated_payload`. HTTP fallback when flag off. |

- [ ] A3 done: All `notify_frontend_db_change` use Redis (or removed in favor of triggers); notify_monitor_manager optional Redis; trade_manager `positions_updated` uses Redis with HTTP fallback (portfolio-plane parity with db_change / bankroll).

---

### A4. monitor_manager.py

| Item | Function / line | Current behavior | Migration action |
|------|------------------|------------------|------------------|
| 1 | `_notify_frontend_monitor_list_updated(message)` | POST to main ` /api/broadcast_monitor_list_update` | Publish to Redis preferences (`monitor_list_update`); remove HTTP. |
| 2 | Call sites of `_notify_frontend_monitor_list_updated` | Multiple | Same. |
| 3 | `requests.post(..., /api/broadcast_monitor_total_position)` | Several call sites | Publish to Redis preferences (`monitor_total_position`); remove HTTP. |
| 4 | `requests.post(..., /api/broadcast_monitor_statistics_update)` | One call site | Main has no such route; add to Redis preferences or remove call. |

- [ ] A4 done: All broadcast calls use Redis preferences; no POST to main.

---

### A5. active_trade_supervisor.py

| Item | Function / line | Current behavior | Migration action |
|------|------------------|------------------|------------------|
| 1 | `POST /api/notify_automated_close` (receives) | Receives from trade_manager/main, then forwards | Replace with Redis subscribe for “automated_close” or trade events. |
| 2 | `broadcast_active_trades_change()` | POST to main `/api/broadcast_active_trades_change` | Publish to Redis preferences; remove HTTP. |
| 3 | All call sites of `broadcast_active_trades_change()` | Many | Same. |
| 4 | Call to ATS `/api/notify_automated_close` (from main or trade_manager) | One place | Caller publishes to Redis; ATS subscribes. |

- [ ] A5 done: No HTTP to main for broadcast; ATS consumes from Redis where applicable.

---

### A6. auto_entry_supervisor.py

| Item | Function / line | Current behavior | Migration action |
|------|------------------|------------------|------------------|
| 1 | `POST /api/notify_cooldown_timer_change` (main) | Called from AES | AES publishes to Redis preferences; remove HTTP. |
| 2 | `POST /api/notify_auto_trade_status_change` (main) | Called from AES | Same. |
| 3 | `broadcast_auto_entry_indicator_change()` | Builds payload, POST to main `/api/notify_auto_trade_status_change` (and commented broadcast_auto_entry_indicator) | Publish to Redis preferences (`auto_entry_indicator`); remove HTTP. |
| 4 | `POST /api/notify_automated_trade` (main) | AES calls main when automated trade triggered | Publish to Redis; main or frontend subscribes. |
| 5 | AES route `POST /api/notify_automated_trade` | Receives from main, forwards | Replace with Redis subscribe. |

- [ ] A6 done: All notify/broadcast use Redis; no POST to main for these.

---

### A7. auto_entry_supervisor_test.py

| Item | Function / line | Current behavior | Migration action |
|------|------------------|------------------|------------------|
| 1 | Same pattern as A6 | Test / mirror of AES | Update tests to use Redis or mock Redis when migrating A6. |

- [ ] A7 done: Tests updated for Redis-based comms.

---

### A8. trade_executor.py

| Item | Function / line | Current behavior | Migration action |
|------|------------------|------------------|------------------|
| 1 | `notify_error` / `notify_accepted` | POST to trade_manager `/api/update_trade_status` | Service-to-service; can stay HTTP or later replace with Redis (trade_manager subscribes). Optional for first phase. |

- [ ] A8 done (optional): trade_manager subscribes to Redis for trade status or keep HTTP.

---

## Part B: Frontend assets

### B0. Dashboard asset checklist (Phase 1 panels)

Track dashboard panels as they migrate to read_api + db_changes. Main remains front door (proxies) until generic routing is introduced.

| Panel | Endpoints | Streams that trigger refresh | Status |
|-------|-----------|------------------------------|--------|
| **Bankroll / Portfolio / PnL** (top panel) | `/api/portfolio/history`, `/api/bankroll/history`, `/api/pnl/history`, `/api/performance/realized` | `account_balance`, (bankroll-related) | Done (Phase 1a). read_api hosts all four; main proxies; dashboard listens db_changes. |
| **Performance** (Day/Week/Month/Year + Cash) | `/api/performance/realized`, `GET /api/subaccounts` | `trades`, `subaccounts` (to be added) | Planned (Phase 1b). Realized already in read_api; add subaccounts to read_api, add streams, wire refresh. |
| Monitors / Allocation / rest | (TBD) | (TBD) | Not started. |

Update this table as each panel is completed. See `.cursor/plans/redis-platform-initiative.md` Phase 1a / 1b for implementation details.

---

### B1. WebSocket connections (point to switchboard or proxy)

| Asset | Connection | Listens for | Migration action |
|-------|-------------|-------------|------------------|
| trade_history.html | `/ws/db_changes` | `data.database === 'trades'` (and fills) | Point WS URL to switchboard (or proxy); ensure payload unchanged. |
| trade_history_mobile.html | `/ws/db_changes` | trades, fills, positions | Same. |
| account_manager.html | `/ws/db_changes` | fills, positions, settlements, account_balance, subaccounts, transfers | Same. |
| account_manager_mobile.html | `/ws/db_changes` | fills, positions, settlements, subaccounts, transfers, account_balance | Same. |
| trade_monitor.html | `/ws/db_changes` + `/ws/preferences` | db: fills, positions, settlements, trades; preferences: many types | Same for both. |
| trade_monitor_mobile.html | `/ws/db_changes` + `/ws/preferences` | Same | Same. |
| strike-table.js | `/ws/db_changes` | `data.database === 'trades'` | Same. |
| dashboard.html | `/ws/preferences` | Preferences events | Point to switchboard when preferences channel exists. |
| dashboard_mobile.html | `/ws/preferences` | Same | Same. |

- [ ] B1 done: All WS URLs point to switchboard or main-as-proxy; no behavior change beyond URL/config.

---

### B2. Frontend HTTP calls to legacy notify/broadcast

| Asset | Call | Purpose | Migration action |
|-------|------|---------|------------------|
| trade_monitor.html | `fetch('/api/broadcast_monitor_list_update', ...)` | Trigger monitor list refresh | Remove when backend uses Redis; frontend already listens on `/ws/preferences` for monitor_list_update. |
| trade_monitor_mobile.html | Same | Same | Same. |

- [ ] B2 done: No frontend fetch to notify/broadcast endpoints; backend publishes to Redis.

---

### B3. Polling that could be reduced by reliable real-time

| Asset | Polling | Purpose | Migration action |
|-------|---------|---------|------------------|
| trade_history.html | `setInterval(..., 10000)` | Fallback refresh | Can reduce or remove when db_changes WS is authoritative. |
| trade_history_mobile.html | `setInterval(fetchAllTrades, 10000)` | Same | Same. |
| account_manager.html | `setInterval(...)` | Refresh | Same. |
| account_manager_mobile.html | `setInterval(...)` | Same | Same. |
| strike-table.js | `setInterval(updateStrikeTable, 1000)` etc. | Strike/middle column data | When trades (and optionally orderbook) streams are real-time, consider increasing interval or reacting only to WS. |
| live-data.js | `setInterval` for core/price | Price/core data | Keep unless live_data becomes a stream. |
| dashboard (desktop/mobile) | Various intervals | Portfolio, performance, monitor refresh | Optional: tighten after preferences + db_changes are reliable. |
| trade_monitor (desktop/mobile) | Intervals for ATS, bankroll, etc. | Backup to WS | Reduce or remove when preferences/db_changes are single source. |

- [ ] B3 done (optional): Polling reduced or removed where real-time covers the need.

---

## Part C: Main.py endpoint list (remove in order)

Use this order to avoid breakage: migrate callers first, then remove endpoint.

1. `POST /api/notify_db_change` — callers: trade_manager, kalshi_account_sync_ws, main.
2. `POST /api/notify_auto_trade_status_change` — caller: auto_entry_supervisor.
3. `POST /api/notify_cooldown_timer_change` — caller: auto_entry_supervisor.
4. `POST /api/notify_automated_trade` — caller: auto_entry_supervisor.
5. `POST /api/notify_automated_close` — callers: trade_manager, active_trade_supervisor.
6. `POST /api/broadcast_auto_entry_indicator` — caller: auto_entry_supervisor (currently commented).
7. `POST /api/broadcast_active_trades_change` — callers: trade_manager, active_trade_supervisor.
8. `POST /api/broadcast_monitor_total_position` — callers: monitor_manager, main (one place).
9. `POST /api/broadcast_monitor_list_update` — callers: monitor_manager, frontend (trade_monitor*).
10. Add if present: `POST /api/broadcast_monitor_statistics_update` — caller: monitor_manager (route missing in main; fix or remove call).

Then remove `broadcast_db_change`, `broadcast_preferences_update`, `broadcast_account_mode`, and loops over `connected_clients` / `db_change_clients`; finally remove or proxy `/ws/db_changes` and `/ws/preferences`.

---

## How to use this audit

- **Per backend asset (A1–A8):** Work through the table; for each “Migration action,” implement Redis publish (or DB trigger + stream) and remove HTTP call; then check the box when that asset is done.
- **Per frontend asset (B1–B3):** Point WS to switchboard (or proxy); remove any fetch to notify/broadcast; optionally reduce polling (B3).
- **Part C:** When all callers of an endpoint are migrated, remove that endpoint from main.py.
- **Order:** Prefer migrating DB-driven events first (notify_db_change + triggers), then preferences-style events (publish helper + Redis channel), then remove main’s broadcast endpoints and WS client sets.

Update this doc when you discover new call sites or complete items so the checklist stays accurate.
