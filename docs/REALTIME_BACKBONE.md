# Real-time backbone: PostgreSQL + Redis

PostgreSQL and Redis form the **real-time backbone** of the system. Any change to watched database state flows through a single pipeline to every frontend and backend consumer. This doc is the single source of truth for the architecture, contracts, and how to add or modify watched state.

**Related:** [REDIS_ARCHITECTURE.md](REDIS_ARCHITECTURE.md) (full recommended architecture in detail, including **read_api**). [redis_switchboard_structure.md](redis_switchboard_structure.md) (switchboard implementation), [REDIS_DB_CHANGES_BACKEND_INTEGRATION.md](REDIS_DB_CHANGES_BACKEND_INTEGRATION.md) (backend subscription), [MASTER_DB_SCHEMA_REFERENCE.md](MASTER_DB_SCHEMA_REFERENCE.md) (trigger function and adding triggers). **Migration checklist:** [REDIS_LEGACY_COMMS_AUDIT.md](REDIS_LEGACY_COMMS_AUDIT.md). **Project tracking:** [.cursor/plans/redis-platform-initiative.md](../.cursor/plans/redis-platform-initiative.md).

---

## 0. Scope and boundaries (anti-bloat)

The backbone stays a **nervous system only**: it carries signals. It does not grow into a catch-all. Every component has a single, documented job.

**What the backbone is (and only is)**

- **PostgreSQL:** Store state; triggers emit NOTIFY on changes to watched tables.
- **Switchboard:** One process that (1) LISTENs to NOTIFY, (2) maps (schema, table) → stream name via the registry, (3) publishes one JSON message to one Redis channel, (4) fans out that same message to WebSocket clients. Plus `/health` and, during pilot, a minimal test UI.
- **Stream registry:** One mapping `(schema, table)` → stream name. No business logic, no per-stream behavior, no extra metadata unless a documented pattern is added and approved.

**What does NOT belong here**

- **Switchboard:** No application HTTP APIs (other than health and the pilot test page). No auth, no per-stream handlers, no business logic, no calls into trade_manager or other services. No new endpoints "because it's convenient." New capabilities = new streams (registry + trigger) or new services, not new routes on the switchboard.
- **Stream registry:** No logic, no imports of app modules, no fields beyond the mapping. If we need "stream config" (e.g. coalesce_ms), that gets a separate, minimal module and is documented.

**Before adding anything to the backbone, ask**

1. Is this "carry a DB change signal to many consumers"? If yes, add a stream (trigger + registry entry). If no, it belongs elsewhere (e.g. main app, a dedicated service).
2. Am I adding a new HTTP endpoint to the switchboard? If yes, the only allowed additions are health and the canonical WS path. Anything else must be justified in the backbone doc and treated as an exception.
3. Am I adding logic or metadata to the stream registry? If yes, use the minimal possible addition and document the rule in this doc.

**Where backbone code and config live (do not scatter)**

| What | Location | Rule |
|------|----------|------|
| Stream mapping | `backend/core/stream_registry.py` | Only (schema, table) → stream_name. One file. |
| Switchboard process | `backend/redis_switchboard.py` | LISTEN, map, Redis publish, WS fan-out, /health. No new endpoints except as in Section 0. |
| NOTIFY trigger function | Migration + `public.rec_io_db_notify()` | Shared function in DB; triggers per table in migrations. |
| Canonical doc | `docs/REALTIME_BACKBONE.md` | Single source of truth. Section 0 = governance. |
| Backend subscription how-to | `docs/REDIS_DB_CHANGES_BACKEND_INTEGRATION.md` | How to consume; no duplicate contract text. |

Adding a new "backbone" file (e.g. a new Python module under backend/) for real-time behavior is allowed only if Section 0 is updated and the role of that file is documented here.

This section is the **governance** for the backbone. Update it when we explicitly decide to expand scope; do not bypass it by "just adding one small thing."

---

## 1. Role of the backbone

- **Single source of truth:** The database holds state. Any writer (main app, scripts, external API ingest, cron jobs) that changes watched tables drives the same real-time pipeline. No component has to "remember" to notify; the DB triggers do it.
- **One pipeline, all consumers:** PostgreSQL NOTIFY → switchboard (LISTEN) → Redis publish → WebSocket (frontend) and Redis subscribers (backend). Same payload for everyone.
- **Painless "watch this":** To have an asset (frontend or backend) "watch" a set of values, you (1) ensure the table(s) are in the stream registry and have triggers, (2) subscribe to the stream by name. No per-asset wiring of who-notifies-whom.

The backbone is designed to **scale from day one**: low-volume streams use row-level triggers; high-volume streams use statement-level or batched NOTIFY and optional coalescing so we never refactor for volume later.

---

## 2. Pipeline (canonical)

```
PostgreSQL (writes to watched tables)
  → trigger fires → pg_notify(rec_io_db_changes, payload)
  → switchboard LISTEN thread
  → map (schema, table) → stream name via registry
  → Redis publish rec_io:db_changes (one JSON message)
  → ├─ Redis subscribers (backend processes, scripts)
  └─ main_app: subscribe rec_io:db_changes → forward same JSON to browsers on /ws/db_changes
       (switchboard may still expose its own /ws/db_changes on its port for local tools only)
```

- **Stream name** (logical name): e.g. `trades`, `fills`, `orderbook`, `redis_basic_test`. Consumers filter by this.
- **Payload:** One stable JSON shape (see below). Same on Redis and WebSocket.

### 2.1 Server-agnostic rule (dev = prod codebase)

This stack is **one repo, any host**: you develop on a local dev machine and deploy the **same** code and config patterns to production. The real-time path must not assume “the browser can open port 3010” or any other internal service port.

**Non-negotiables**

1. **Browser WebSocket URL:** Product UIs (dashboard, trade monitor, account manager, etc.) connect to **`/ws/db_changes` on the same origin as the page** — i.e. the **main app** host (`window.location.host`), not `hostname:redis_switchboard_port`. HTTPS in prod and `http://localhost:3000` in dev both work without special-case frontend code.
2. **Main forwards Redis:** `main_app` runs a **Redis subscriber** on `rec_io:db_changes` (same env as `redis_switchboard`: `REDIS_URL` or `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD`, and `REDIS_CHANNEL_DB_CHANGES` if overridden). It pushes each message to every connected `/ws/db_changes` client. **`POST /api/notify_db_change`** still builds compatible messages for the same clients.
3. **Switchboard stays the NOTIFY → Redis writer:** One `redis_switchboard` process LISTENs PostgreSQL and publishes to Redis. It does **not** need to be reachable from end-user browsers in prod.
4. **No prod-only WebSocket wiring in the frontend.** If something needs `db_change` events, it uses the contract on **same-origin** `/ws/db_changes` or subscribes to Redis in backend code — never a hardcoded alternate host/port for “real” pages.

5. **Resilience (required for long-lived tabs):** Proxies and idle timers close WebSockets; Redis pubsub can stall without timeouts. You still use **one** same-origin `/ws/db_changes` per page (or per app shell), carrying **all** logical streams; handlers filter by `database`. **One reconnect sequence** restores that pipe for every stream — not a timer per metric. **Main’s Redis forwarder** uses timed `get_message` + `PING` instead of an unbounded `listen()` loop. **Do not** default to interval polling per widget; that defeats event-driven refetch. If a feature truly needs a poll, document it as an explicit exception.

6. **UI coalescing (required for high fan-out):** A single `db_change` channel carries every stream; NOTIFY bursts (e.g. many `trades_0001` updates) can deliver messages faster than the browser can run chart reflows and HTTP refetches. **`WebSocket.onmessage` must not start unbounded concurrent work** (e.g. an `async` handler that fires a full dashboard refresh per message). Use **debounce** plus **single-flight** (or a queued follow-up) for heavy handlers so the renderer does not run out of memory (Chromium tab crash / “Aw, Snap”, error code 5).

Violating (1) or (4) breaks the “build local, run anywhere” model.

---

## 3. Payload contract (stable)

Every message on `rec_io:db_changes` (Redis and WebSocket) has this shape:

```json
{
  "type": "db_change",
  "database": "<stream_name>",
  "data": {
    "timestamp": "<iso or null>",
    "change_data": {
      "schema": "<schema>",
      "table": "<table>",
      "op": "INSERT" | "UPDATE" | "DELETE"
    }
  },
  "timestamp": "<iso8601_utc>"
}
```

- **`database`** is the **stream name** from the registry. Use this to "watch" a set of values: subscribe and filter `msg.database === "trades"` (or equivalent).
- **Wire JSON spacing:** Python `json.dumps` emits a space after `:` (e.g. `"database": "trades"`). If you use a substring prefilter before `JSON.parse` (see `frontend/js/db_changes_prefilter.js`), it must match both that form and compact `"database":"trades"` so refetches are not skipped.
- **`data.change_data`** identifies the physical table and operation. For high-volume streams, future extensions may add e.g. `symbol`, `strike_id`, or `keys` for targeted updates; the top-level shape stays the same.

Frontend and backend code must rely only on this contract. No backend-specific or frontend-specific variants.

---

## 4. Stream registry (single source of "what is watched")

The **stream registry** maps `(schema, table)` → stream name. It lives in code so it is versioned and reviewable.

- **Location:** `backend/core/stream_registry.py`. The switchboard imports it. To add a new watched set of values you add one entry and (if not already present) a trigger on the table.
- **Convention:** One logical stream per "thing" the UI or backend cares about (e.g. one stream `trades` for the tenant’s legacy `users.trades_<slot>` name, rewritten to `users_<slot>.trades_<slot>` on NOTIFY). High-volume tables (e.g. orderbook rows) map to one stream (e.g. `orderbook`) and use statement-level or batched NOTIFY so we don’t emit one message per row.
- **Documentation:** This doc and the registry file list all streams. When adding a stream, add a short comment in the registry and, if useful, a line in this doc’s stream list.
- **Registered example — `trades`:** Table `users.trades_0001` maps to stream name **`trades`** (`stream_registry.py`). Row-level trigger **`trades_0001_rec_io_db_notify`** → `public.rec_io_db_notify()` (migration `20260401_1600_trades_0001_rec_io_db_notify`). Consumers include trade history UIs (`GET /trades` refetch on `database === "trades"`).
- **Registered example — `master_users`:** Table `system.master_users` maps to stream name **`master_users`**. Row-level trigger **`system_master_users_rec_io_db_notify`** → `public.rec_io_db_notify()` (migration `20260414_2000_system_master_users_rec_io_db_notify`). Consumers include Admin Tools (`GET /api/user/admin/master_users` refetch on `database === "master_users"`).
- **Registered example — `monitor_list`:** Table `users.monitor_list_0001` maps to stream name **`monitor_list`**. Per-tenant **`monitor_list_<slot>_rec_io_db_notify`** on **`users_<slot>.monitor_list_<slot>`** → `public.rec_io_db_notify()` (migration `20260423_1100_tenant_monitor_list_rec_io_db_notify`). Consumers include Admin Tools (same refetch as `master_users` when `database === "monitor_list"` so per-user **Monitors** counts stay current).
- **Registered example — `performance_rollups`:** Per-tenant tables **`users_<slot>.performance_total_<slot>`** and **`users_<slot>.performance_monitors_<slot>`** (pre-aggregated dashboard metrics) map to stream **`performance_rollups`** (`stream_registry.py`; template keys `users.performance_{total,monitors}_0001` for tenant resolution). Row-level triggers `*_rec_io_db_notify` → `public.rec_io_db_notify()` (migration **`20260505_1400_performance_rollup_tables`**). Writers recompute on trade close (`monitor_manager` → `recompute_performance_rollups_for_slot`). Consumers: dashboard (legacy + NEW) include this stream in the debounced bankroll/performance batch so the strip refetches after rollup commits; NEW shell reads **`GET /api/performance/rollups`**.

---

## 5. Adding a watched set of values ("watch THIS")

To have the system (frontend and/or backend) watch a set of values backed by a table:

1. **Trigger on the table**  
   Use `public.rec_io_db_notify()` for row-level, or a custom statement-level trigger for high-volume tables (see Scalability below). Trigger fires on INSERT/UPDATE/DELETE and sends NOTIFY with `{"schema","table","op"}`.

2. **Register the table**  
   In `backend/core/stream_registry.py`, add `(schema, table) -> stream_name`. Stream name is the logical name consumers will filter on (e.g. `trades`, `orderbook`).

3. **Consumers**  
   - **Frontend:** Connect to **`/ws/db_changes` on the main app (same origin as the UI)**. On message, filter `database === stream_name` (see payload contract), then refetch or update UI (targeted refetch preferred for high-volume streams). Do not point product pages at the switchboard port.
   - **Backend:** Subscribe to Redis `rec_io:db_changes`, filter `msg["database"] == stream_name`, run your logic.

No other wiring. No "notify this service" — everyone subscribes to the same pipeline.

---

## 6. Scalability (built in from the start)

- **Low / moderate volume (e.g. trades, fills, positions, settlements, monitor list):**  
  Use **row-level** trigger with `public.rec_io_db_notify()`. One NOTIFY per row. Payload stays small; PG and Redis handle it.

- **High volume (e.g. orderbooks, many symbols × many strikes, frequent ticks):**  
  Use **statement-level** trigger (FOR EACH STATEMENT) or a **batched** design: one NOTIFY per transaction or per batch with a payload that identifies what changed (e.g. list of symbol/strike or a single "orderbook" stream). Then:
  - Optionally **coalesce** in the switchboard: for that stream, batch events over 50–100 ms and emit one message (or one per symbol) so WebSocket and downstream don’t get flooded.
  - Frontend/backend do **targeted** updates (e.g. refetch only the affected symbol/strike) using `change_data` or future fields (symbol, strike_id).

- **Single channel:** One Redis channel for all streams. Consumers filter by `database`. No per-stream channels unless we explicitly add them later for isolation; one channel keeps the model simple and consistent.

---

## 6b. Derived data and compute (design constraint)

**Do not** introduce many independent processes or scripts that each subscribe to Redis/WS and run their own calculations for dozens of display values or assets. That pattern does not scale and is hard to reason about.

**Principle:** Derived/aggregated data (e.g. PnL totals by period, dashboard summaries, monitor stats) must be produced in an **efficient, centralized** way. Redis stays the routing layer only; it does not decide *who* computes what. **Recommended model (on-demand read APIs, no backend watchers for derived data):** [DERIVED_DATA_COMPUTE_MODEL.md](DERIVED_DATA_COMPUTE_MODEL.md).

**Chosen model: read_api (on-demand read APIs, no backend watchers).** The single process **read_api** (supervisor) hosts all read/aggregate endpoints; it runs queries and returns JSON on request and does not subscribe to Redis. Full architecture: [REDIS_ARCHITECTURE.md](REDIS_ARCHITECTURE.md).

- **Signals:** Redis/WS carry "this stream changed." Frontend refetches read_api when it receives the relevant stream. No backend subscriber recomputes aggregates.
- Before adding a backend subscriber that performs calculations, confirm it is a reaction for a specific feature or document the exception here.

### 6b.1 Dashboard bankroll / portfolio / PnL (Phase 1 status)

- **Panel scope:** The top dashboard panel showing bankroll, portfolio, and PnL values and their deltas (desktop and mobile).
- **Read path:** All read/aggregate logic for this panel lives in `backend/read_api.py`:
  - `/api/portfolio/history`
  - `/api/bankroll/history`
  - `/api/pnl/history`
  - `/api/performance/realized`
- **Front door:** `backend/main.py` exposes the same four routes but only as **thin HTTP proxies** into read_api; it no longer contains SQL or aggregation for this panel.
- **Realtime triggers:** The panel’s refresh behavior is driven by the backbone:
  - PostgreSQL triggers (e.g. on `users.account_balance_0001`) emit NOTIFY.
  - `redis_switchboard` maps those tables to logical streams (e.g. `account_balance`) via `stream_registry.py` and publishes `db_change` events to Redis.
  - **`main_app`** subscribes to Redis and forwards the same payloads to browsers on **same-origin** `/ws/db_changes`; the dashboard (desktop and mobile) connects there and refetches from read_api (via main’s proxies) when relevant streams change.

This pattern (read_api as canonical read surface, main as front door only, Redis/WS as the trigger) is the template for migrating other dashboard panels and assets.

---

## 7. Operational requirements

- **Redis:** Must be running. Switchboard, **main_app’s db_changes forwarder**, and all backend Redis subscribers depend on it. Use the same `REDIS_*` (and channel) env on every environment so dev and prod behave the same.
- **Switchboard:** One process (e.g. under supervisor). LISTENs to PostgreSQL and publishes to Redis. Its own `/ws/db_changes` on the switchboard port is optional and **not** required for product UIs (see §2.1).
- **Main app:** Must run with Redis reachable as above so it can subscribe and forward to **same-origin** `/ws/db_changes` clients. Optional env: `REDIS_DB_FORWARDER_GET_TIMEOUT` (seconds, default `30`) for pubsub read/poll cadence.
- **Triggers:** Applied via migrations. New tables that should be watched get a migration that adds the trigger and, when applicable, a note in the stream registry (registry is in code, so "add stream" is a code change plus migration).
- **ATS open enrollment:** Not a DB NOTIFY stream. `trade_manager` and each `active_trade_supervisor` process use Redis Pub/Sub channel `rec_io:ats_enroll_request` (override via `REDIS_CHANNEL_ATS_ENROLL_REQUEST`) plus short-lived keys `ats:enroll:result:{correlation_id}` for handoff ACK. Same Redis instance as the switchboard; implementation `backend/core/ats_enrollment_redis.py`. Messages do **not** flow through `redis_switchboard.py`.

---

## 8. Stream list (current)

| Stream name       | Source (schema.table)        | Notes                    |
|-------------------|------------------------------|---------------------------|
| `redis_basic_test` | testing.redis_basic_test   | Pilot / test stream       |
| `account_balance` | users.account_balance_0001 | Dashboard bankroll/portfolio panel |
| `live_symbol_status` | live_data.live_symbol_status | Canonical snapshot of latest symbol conditions (BTC/ETH): refetch on `db_change` |
| `market_kalshi_15m` | live_data.market_kalshi_15m | 15m Kalshi market ladder/quotes (used by strike table pipelines) |
| `strike_table_15m` | live_data.strike_table_15m | Unified 15m strike row(s) per symbol; pilot NOTIFY for dev/test UIs |

**Canonical current-state rule (symbols):** treat `live_data.live_symbol_status` as the source of truth for "current" symbol price + condition percentiles (momentum/volatility/movement). The `live_price_log_1s_*` tables are the higher-resolution per-tick log used to derive/validate the snapshot and for debugging/analysis; consumers should prefer `live_symbol_status` for real-time decisions.

Planned next (Phase 1b): `trades` (users.trades_0001), `subaccounts` (users.subaccounts_0001) for the Performance panel. Add them to the registry and to this table when implemented. Keep the table in sync with `backend/core/stream_registry.py`.

---

## 9. Consistency checklist for new work

- **Scope first:** Run through Section 0 (Scope and boundaries). If what you're adding isn't "carry a DB change signal" or "register a stream," put it elsewhere.
- **New stream:** Add trigger (migration) + one registry entry + optional doc line in Stream list (Section 8). No new switchboard code.
- **New consumer:** Backend: subscribe to Redis; filter by `database`. Frontend: **same-origin** `/ws/db_changes` on main only; filter by `database`; use only the payload contract. Consumer logic lives in the frontend or the backend service, not in the switchboard.
- **High-volume table:** Use statement-level or batched NOTIFY; document in registry and here; consider coalescing in switchboard only if the pattern is documented in this doc.
- **New endpoint on switchboard:** Unless it is health or the canonical WS path, do not add it without updating Section 0 and documenting the exception.
- **PostgreSQL utilization (when hooking up connections):** When adding a stream, moving a read/aggregate endpoint to read_api, or wiring a new consumer, consider whether that point is a good place to better utilize PostgreSQL—e.g. views, materialized views, stored functions, or trigger-maintained summary tables—for the data that connection serves. No obligation to add them every time; evaluate and adopt where it improves efficiency or clarity.
