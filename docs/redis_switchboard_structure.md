# Redis switchboard: structure and contract

**Canonical reference for the real-time system:** [REALTIME_BACKBONE.md](REALTIME_BACKBONE.md). This doc describes switchboard implementation and migration from main.py.

**Purpose:** Single global persistent script (under supervisor) that subscribes to Redis and fans out to WebSocket clients. It replaces main.py’s role as the real-time hub for all DB-change and broadcast events, so main can drop `/ws/db_changes`, `/ws/preferences`, and all `/api/notify_db_change` / `/api/broadcast_*` endpoints. The switchboard does **not** query PostgreSQL; backends publish after they write to the DB.

**Scope:** Serve all current frontend consumers (trade_history, trade_monitor, account_manager, dashboard, strike-table.js, etc.) and all current backend publishers (trade_manager, kalshi_account_sync_ws, active_trade_supervisor, monitor_manager, main.py itself for in-app actions). Start with a small pilot (e.g. trades + trade_history), then migrate all flows.

---

## 1. Two WebSocket endpoints (match main exactly)

Main today exposes two distinct WebSocket endpoints; the frontend connects to one or both depending on the page. The switchboard must expose the **same paths and message shapes** so HTML/JS can switch to the switchboard by changing only the WebSocket base URL (host/port or path), not message handling.

| Endpoint         | Current main.py clients | Message shape |
|------------------|-------------------------|----------------|
| `/ws/db_changes` | trade_history, account_manager, trade_monitor, strike-table.js | `{ "type": "db_change", "database": "<name>", "data": { "timestamp", "change_data" }, "timestamp": "<iso>" }` |
| `/ws/preferences`| dashboard, trade_monitor | `{ "type": "<event_type>", "data": {...} }` or `{ "type", "monitor_id", "total_position" }` etc. |

- **db_changes**  
  Frontend filters by `data.database` (e.g. `"trades"`, `"fills"`, `"positions"`, `"settlements"`, `"orders"`, `"account_balance"`, `"subaccounts"`, `"transfers"`). No per-user filtering; one process serves all users.

- **preferences**  
  Frontend filters by `data.type` (e.g. `active_trades_change`, `monitor_list_updated`, `monitor_total_position_updated`, `auto_entry_indicator_change`, `automated_trade_closed`, `automated_trade_triggered`, `auto_trade_status_change`, `cooldown_timer_change`, `auto_trade_toggled`, `paper_trade_toggled`). Same “all users” model.

The switchboard **only** forwards messages; it does not query the DB. Refetch and all API/DB access stay in the frontend (e.g. `fetchAllTrades()`) and in existing HTTP endpoints (main or others).

---

## 2. Redis channel contract

Two Redis channels carry the **exact JSON** that will be sent to WebSocket clients. Publishers build that JSON once; the switchboard does no transformation.

| Redis channel   | Target WS endpoint   | Payload = message to send |
|-----------------|------------------------|----------------------------|
| `rec_io:db_changes`   | `/ws/db_changes`   | Full `db_change` message (type, database, data, timestamp). |
| `rec_io:preferences`   | `/ws/preferences`  | Full preferences message (type, data or type/monitor_id/total_position, etc.). |

- **Channel naming:** Use a prefix (e.g. `rec_io:`) so multiple apps on the same Redis don’t collide.
- **Payload:** UTF-8 JSON string. The switchboard parses once to validate and re-serializes when sending to each client (or forwards the same bytes if already valid JSON).
- **No DB in switchboard:** Backend services write to PostgreSQL, then publish to Redis. The switchboard never touches the DB.

---

## 3. Backend publish helper (shared module)

Backends need a single place to publish so message shape and channel choice stay consistent. Add a small module (e.g. `backend/core/redis_publish.py` or `backend/util/redis_switchboard_client.py`) used by trade_manager, kalshi_account_sync_ws, active_trade_supervisor, monitor_manager, and main when it triggers in-app broadcasts.

- **`publish_db_change(db_name, change_data=None)`**  
  Builds `{ "type": "db_change", "database": db_name, "data": { "timestamp": <now>, "change_data": change_data }, "timestamp": "<iso>" }`, publishes to `rec_io:db_changes`. Optional: skip publish if Redis is unavailable and log (or no-op), so existing HTTP fallback to main can remain during migration.

- **`publish_preferences_message(message_dict)`**  
  `message_dict` is the full object the frontend expects (e.g. `{ "type": "active_trades_change", "data": {...} }`). Publish to `rec_io:preferences`.

Backends that today do `requests.post(main_app, "/api/notify_db_change", json={...})` can switch to `publish_db_change(...)`. If you add **DB-driven events** (Section 8), any table with a NOTIFY trigger will emit changes automatically; for those tables you can stop calling `publish_db_change` and rely on the trigger. Same for each `/api/broadcast_*` and `/api/notify_*`: use `publish_preferences_message(...)`. The switchboard does not need to know about PostgreSQL or any backend; it only subscribes and fans out.

---

## 4. Script layout: `redis_switchboard.py`

Suggested location: repo root or `backend/` (e.g. `backend/redis_switchboard.py`) so it can be run as `python backend/redis_switchboard.py` or `python -m backend.redis_switchboard` under supervisor.

### 4.1 Config (env)

- `REDIS_URL` or `REDIS_HOST` + `REDIS_PORT` (+ optional password). Defaults for local dev (e.g. `localhost:6379`).
- `SWITCHBOARD_HOST`, `SWITCHBOARD_PORT` for the WebSocket server (e.g. `0.0.0.0` and `3010` so nginx or the frontend can use `ws://host:3010/ws/db_changes`).
- Optional: `REDIS_CHANNEL_PREFIX` (default `rec_io:`), list of channels to subscribe to (default `["rec_io:db_changes", "rec_io:preferences"]`).

### 4.2 Components

1. **Redis subscriber (thread or async)**  
   Subscribe to `rec_io:db_changes` and `rec_io:preferences`. On each message, push `(channel, raw_message_string)` into a thread-safe queue (e.g. `queue.Queue`) or an asyncio queue. Use a dedicated thread if the Redis client is blocking, or async if using `aioredis`/`redis.asyncio`.

2. **WebSocket server (async)**  
   FastAPI or Starlette app:
   - **GET /health** — returns 200 and optionally `{"redis": "connected", "clients_db_changes": N, "clients_preferences": N }` for supervisor/monitoring.
   - **WebSocket /ws/db_changes** — accept, add connection to a set `clients_db_changes`, on disconnect remove. In the background loop: for each `(channel, message)` where channel is `rec_io:db_changes`, send `message` to every client in `clients_db_changes` (catch send errors and drop dead connections).
   - **WebSocket /ws/preferences** — same with set `clients_preferences` and channel `rec_io:preferences`.

3. **Bridge loop**  
   One asyncio task (or thread that puts into asyncio queue) that reads from the Redis message queue and dispatches to the correct client set by channel. Ensures Redis and WebSocket logic stay on the right thread/loop.

4. **Startup / shutdown**  
   On startup: connect to Redis, start subscriber, start HTTP/WS server, start bridge loop. On SIGTERM/SIGINT: stop accepting new WS, unsubscribe from Redis, drain queue and send pending messages, close WebSocket connections, exit.

5. **Logging**  
   Log startup (config, channels), client connect/disconnect (counts are enough), and any Redis/WS errors. No need to log every message.

### 4.3 No PostgreSQL

The switchboard does not import DB or run any SQL. All data flow is: **backend writes to DB → backend publishes to Redis → switchboard forwards to WS clients → frontend receives event → frontend calls existing HTTP API (which hits DB) to refetch**. So it works with all existing backend Python and PostgreSQL flows; the only new piece is “publish to Redis” after DB write.

---

## 5. Frontend compatibility (HTML/CSS/JS)

- **Same URLs, different origin:** Frontend today uses `window.location.host` for WebSocket (e.g. `wss://host/ws/db_changes`). To use the switchboard, either:
  - **Same host, different path:** e.g. nginx proxies ` /ws/db_changes` and `/ws/preferences` to the switchboard port; no JS change.
  - **Or configurable WS base URL:** e.g. `window.SWITCHBOARD_WS_URL || (protocol + '//' + host)` so in prod you can set `SWITCHBOARD_WS_URL=wss://host:3010` and point to the switchboard.
- **Message handling unchanged:** All existing `data.database`, `data.type` checks in trade_history.html, trade_monitor.html, account_manager.html, dashboard.html, strike-table.js, etc. stay as-is. The switchboard sends the same JSON shapes main sends today.

---

## 6. Supervisor and deployment

- One program, e.g. `redis_switchboard`, command `python backend/redis_switchboard.py` (or `python -m backend.redis_switchboard`), autorestart, stdout/stderr to logs. Requires Redis to be up first (or document startup order / restart policy).
- Optional: health check script or supervisor `redirect_stderr` + a small script that hits `GET /health` and fails if not 200.

---

## 7. Migration order (for main.py bloat strip)

1. Add Redis + switchboard + publish helper; run switchboard under supervisor.
2. Pilot: trade_manager publishes trades to `rec_io:db_changes` (and optionally still POSTs to main during rollout). Point trade_history’s WebSocket at the switchboard (or proxy). Remove 10s polling on trade_history once stable.
3. Migrate all other `notify_db_change` call sites to `publish_db_change`; migrate all `broadcast_*` / `notify_*` call sites to `publish_preferences_message`. Point all frontend WS at the switchboard (or proxy).
4. Remove from main.py: `db_change_clients`, `connected_clients`, `broadcast_db_change`, `/ws/db_changes`, `/ws/preferences`, `/api/notify_db_change`, and every `/api/broadcast_*` and `/api/notify_*` that only existed to fan out to those clients. Main no longer owns the “main switchboard” role.

This keeps the switchboard generic (two endpoints, two channels, no DB), and keeps all DB querying and API behavior in existing backend and frontend code.

---

## 8. DB-driven events: any DB change → WebSocket (optional / recommended)

**Goal:** Have *any* change to the database (from any backend script, from main.py, or from direct SQL/TablePlus) automatically flow through the WebSocket channels so all assets stay close to real-time with the actual DB contents. No backend has to remember to call `publish_db_change`; the DB itself drives the stream.

**Mechanism: PostgreSQL NOTIFY from triggers**

1. **Triggers on key tables**  
   Attach a single generic trigger function to every table that the frontend cares about (e.g. `users.trades_<slot>`, `users.trades_simulated_<slot>`, `users.monitor_list_<slot>`, `users.account_balance_<slot>`, `users.account_history_<slot>`, Kalshi sync tables that back “fills”, “positions”, “settlements”, “orders”, “subaccounts”, “transfers”, etc.).  
   On `AFTER INSERT OR UPDATE OR DELETE` the trigger runs `PERFORM pg_notify('rec_io_db_changes', payload)` where `payload` is a small JSON string, e.g.  
   `{"schema":"users","table":"trades_0001","op":"UPDATE"}`  
   (no row data in the payload; we only signal “this table changed”). Optionally include `row_id` or a hash if the frontend will use it later for granular updates.

2. **Table → frontend “database” mapping**  
   The frontend today filters on `data.database` with values like `"trades"`, `"fills"`, `"positions"`, `"settlements"`, `"orders"`, `"account_balance"`, `"subaccounts"`, `"transfers"`, `"monitor_list"`. We maintain a single mapping from `(schema, table)` to that logical name, e.g.  
   `users.trades_<slot>` → `"trades"`,
   `users.monitor_list_<slot>` → `"monitor_list"`,
   `users.account_balance_0001` → `"account_balance"`,  
   and the Kalshi-backed tables to `"fills"`, `"positions"`, etc.

3. **DB listener process**  
   A process (can be the same binary as the switchboard or a separate “pg_listener” script) holds a dedicated PostgreSQL connection and runs `LISTEN rec_io_db_changes`. When it receives a notification, it:
   - Parses the payload (schema, table, op).
   - Looks up the frontend `database` name from the mapping (unknown table → skip or log).
   - Builds the same JSON shape the frontend already expects:  
     `{ "type": "db_change", "database": "<mapped_name>", "data": { "timestamp": <now>, "change_data": { "schema", "table", "op" } }, "timestamp": "<iso>" }`
   - Publishes that JSON to Redis channel `rec_io:db_changes`.

4. **Switchboard unchanged**  
   The switchboard still subscribes to `rec_io:db_changes` and forwards to `/ws/db_changes` clients. So the pipeline becomes:  
   **DB change (any source) → trigger → NOTIFY → DB listener → Redis → switchboard → WebSocket → frontend.**  
   Frontend still refetches via existing HTTP API when it receives a `db_change`; it doesn’t need row payloads from the trigger.

**Benefits**

- **Single source of truth:** Any write to those tables (application code or direct SQL) produces an event. Dashboard data from `monitor_list`, account balance columns, trades, etc. all flow through without each backend having to call publish.
- **Real-time view:** All assets (web, mobile, any future client) get the same stream and can refetch so their view tracks the actual current contents of the DB.
- **Backend simplicity:** Backends can stop calling `publish_db_change` for those tables; the trigger covers it. You can keep `publish_db_change` for tables you don’t want to put triggers on, or for extra metadata (e.g. `change_data` with a reason).

**Operational notes**

- **Trigger overhead:** One NOTIFY per row change; payload is small. For very high write rates, consider batching or rate-limiting in the listener (e.g. coalesce “trades” notifications over 100ms) so the frontend doesn’t get spammed; for typical dashboard/balance/trade volumes this is usually fine.
- **Listener process:** Must run with DB credentials and stay connected. Run under supervisor; restart on disconnect. If the listener is part of the same process as the switchboard, use a dedicated thread or async task for `LISTEN` and push into the same Redis or into the same in-process queue the switchboard uses.
- **Migration:** Add triggers and the listener first; keep existing `publish_db_change` calls during rollout. Once triggers cover a table, you can remove `publish_db_change` for that table. For “preferences”-style events (active_trades_change, monitor_list_updated, etc.) there is no DB row per event, so those stay as explicit `publish_preferences_message` from backends.

**Summary**

- Use **PostgreSQL NOTIFY** from triggers on the tables that back “db_changes” (trades, monitor_list, account_balance, fills, positions, settlements, orders, subaccounts, transfers, etc.).
- A **DB listener** maps (schema, table) → frontend `database` name and publishes the same `db_change` JSON to `rec_io:db_changes`.
- The **Redis switchboard** is unchanged and still forwards `rec_io:db_changes` to `/ws/db_changes`. All clients then get every DB-driven change; frontend logic stays “on db_change → refetch” for a real-time view of the actual DB.
