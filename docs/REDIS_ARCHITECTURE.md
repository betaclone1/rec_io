# Redis / real-time architecture (recommended)

This doc describes the full recommended architecture: the real-time backbone (PostgreSQL + Redis + switchboard), the **read_api** (single global service for all read/aggregate data), a slimmed main, and how the frontend gets real-time updates. One source of truth for how these pieces fit together.

**Suggested name for the global read service:** **read_api**. One persistent process run under supervisor (e.g. `read_api`); the codebase module can be `backend/read_api.py` or similar.

---

## 1. Components

| Component | Role | Does NOT do |
|-----------|------|--------------|
| **PostgreSQL** | Source of truth. Stores all state. Triggers on watched tables fire NOTIFY with `{schema, table, op}`. | No Redis, no HTTP, no business logic beyond triggers. |
| **Redis** | Carries one channel `rec_io:db_changes`. Receives messages from switchboard; frontend (via WS) and backend subscribers consume. Routing only. | No queries, no calculation, no formatting, no storage of application data. |
| **Switchboard** | One process. LISTENs to PostgreSQL NOTIFY; maps (schema, table) → stream name via stream registry; publishes one JSON message per event to Redis; fans out same message to WebSocket `/ws/db_changes`. Serves `/health` and pilot test UI only. | No read/aggregate endpoints, no auth, no business logic. |
| **read_api** | One persistent process (supervisor: `read_api`). Hosts **all** HTTP endpoints that read from the DB and/or compute derived/aggregate data for display. Request in → run query (and any calculation/formatting) → return JSON. Does **not** subscribe to Redis. | No WebSocket, no broadcast, no auth (or minimal; can sit behind main as proxy). |
| **Main (slimmed)** | Auth, serve static frontend, route or proxy to read_api and switchboard. No read/aggregate endpoints, no `db_change_clients`, no broadcast, no `/api/notify_*` or `/api/broadcast_*`. | No SQL for dashboard/trade_history/trade_monitor data; no fan-out to WS clients for db_changes. |
| **Frontend** | Loads from main. Subscribes to `/ws/db_changes` (from switchboard, possibly via main proxy). On message, filters by `data.database` and refetches the **read_api** endpoints that need fresh data; updates the DOM. | Does not compute aggregates server-side; it calls read_api. |

---

## 2. End-to-end flow (example: 4 trade log rows updated)

1. **DB:** Four rows in `users.trades_0001` are updated (e.g. status, PnL, closed_at).
2. **Trigger:** `public.rec_io_db_notify()` runs (four times or coalesced); sends NOTIFY on channel `rec_io_db_changes` with payload `{"schema":"users","table":"trades_0001","op":"UPDATE"}`.
3. **Switchboard:** LISTEN thread receives NOTIFY; stream registry maps `(users, trades_0001)` → `trades`; builds message `{ type: "db_change", database: "trades", data: { change_data: { schema, table, op } }, timestamp }`; publishes to Redis `rec_io:db_changes`; sends same message to all connected WebSocket clients on `/ws/db_changes`.
4. **Frontend:** Receives the message. Handler for `data.database === 'trades'` runs. Dashboard knows which areas depend on trades: Performance panel (day/week/month/year PnL and ret%), bankroll/portfolio if derived from trades, monitor cards’ PnL/Ret%, allocation if relevant. It **refetches** the corresponding **read_api** endpoints in parallel (e.g. `GET /api/performance/realized`, `GET /api/portfolio/history`, monitor stats, etc.).
5. **read_api:** Receives those HTTP requests. For each request, runs the appropriate query (which now sees the four updated rows), computes and formats the result, returns JSON. No Redis subscription; it only responds to HTTP.
6. **Frontend:** Gets responses; updates the dozen (or more) display areas. Real-time update complete.

So: **signals** are pushed (DB → NOTIFY → switchboard → Redis → WS). **Values** are pulled (frontend refetches read_api on signal). All calculation and formatting for display happens in **read_api** on that refetch.

---

## 3. What lives in read_api (in detail)

**Purpose:** Single place that calculates, formats, and serves every piece of read/aggregate data needed by every frontend asset (dashboard, trade_history, trade_monitor, account_manager, strike table, etc.).

**Behavior:** One process, many routes. Each route is request-driven: when a client calls the endpoint, read_api runs the query (and any aggregation/formatting) and returns the response. No background watchers, no Redis subscription.

**Examples of endpoints that move from main to read_api (or are implemented there from the start):**

- **Dashboard:** `/api/performance/realized` (day/week/month/year PnL and ret%), `/api/account/balance`, `/api/subaccounts`, `/api/portfolio/history`, `/api/account/balance/history`, monitor list and per-monitor stats (win streak, W/L, Ret%, PnL, allocation), allocation data.
- **Trade history:** Trades list, fills, filters, any read-only trade APIs.
- **Trade monitor:** Positions, settlements, recent trades, active trades, any read-only APIs for that tab.
- **Account manager:** Fills, positions, settlements, account balance, subaccounts, transfers (read views).
- **Strike table / other:** Any other endpoint that is “read from DB (and optionally aggregate) and return JSON.”

**What read_api does not do:** Auth (can be done by main in front of it, or minimal auth in read_api), WebSocket, Redis subscribe, broadcast, or write operations (those stay in main or other services). Optional: short TTL cache per endpoint if a query is expensive.

**Deployment:** Run as a single process under supervisor (e.g. program name `read_api`, command e.g. `python -m backend.read_api`). Port from manifest. Frontend can call it directly (e.g. same host, different port) or via main as reverse proxy so the browser still talks to one origin.

---

## 4. What main no longer does (slimmed)

- Does **not** host read/aggregate endpoints (they move to read_api).
- Does **not** hold `db_change_clients` or broadcast to WebSocket when DB changes (signals come from switchboard).
- Does **not** expose `/api/notify_db_change`, `/api/broadcast_*`, or similar; those are removed once callers use Redis or triggers.
- **Does:** Auth, serve static files (frontend), possibly proxy to read_api and to switchboard for WebSocket, and any write/action endpoints that must stay in the main app (e.g. create monitor, initiate transfer). So main stays the “front door” for the app but stops being the place that runs every read query and every broadcast.

---

## 5. Supervisor process list (target state)

- **main** – Auth, static, proxy; no read/aggregate routes, no db_change broadcast.
- **redis_switchboard** – LISTEN → Redis → `/ws/db_changes`; health and pilot only.
- **read_api** – All read/aggregate HTTP endpoints; runs queries and returns JSON on request; no Redis.
- **Redis** – Running (e.g. system or container).
- **trade_manager, monitor_manager, kalshi_account_sync, active_trade_supervisor, auto_entry_supervisor, etc.** – Unchanged in role; they write to DB and may publish to Redis for preferences; they do not host the dashboard/trade_history read endpoints.

---

## 6. Stability and scalability

- **Stable:** One process per role. Request-driven read_api has no background loops. Supervisor restarts any process that crashes.
- **Scalable for your scope:** One read_api process handles concurrent requests (async or threaded); for a single-user or small-team trading system this is sufficient. If load grows, add per-endpoint TTL cache, read replicas, or split later.
- **Appropriate:** One global script (read_api) for all read/aggregate data keeps a single place to maintain, tune queries, and add new derived values without adding new watchers or services.

---

## 7. Relation to other docs

- **REALTIME_BACKBONE.md** – Backbone only: NOTIFY, stream registry, switchboard, payload contract, scope. Section 6b points to the derived-data model; read_api is the implementation of that model.
- **DERIVED_DATA_COMPUTE_MODEL.md** – Describes the on-demand read model and names read_api as the service that does the computation.
- **REDIS_LEGACY_COMMS_AUDIT.md** – Migration checklist; read endpoints listed there move to read_api; main drops them.
- **.cursor/plans/redis-platform-initiative.md** – Tracks rollout; read_api is part of the target architecture and migration steps.
