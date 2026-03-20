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
  → WebSocket /ws/db_changes (frontend) + Redis subscribers (backend)
```

- **Stream name** (logical name): e.g. `trades`, `fills`, `orderbook`, `redis_basic_test`. Consumers filter by this.
- **Payload:** One stable JSON shape (see below). Same on Redis and WebSocket.

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
- **`data.change_data`** identifies the physical table and operation. For high-volume streams, future extensions may add e.g. `symbol`, `strike_id`, or `keys` for targeted updates; the top-level shape stays the same.

Frontend and backend code must rely only on this contract. No backend-specific or frontend-specific variants.

---

## 4. Stream registry (single source of "what is watched")

The **stream registry** maps `(schema, table)` → stream name. It lives in code so it is versioned and reviewable.

- **Location:** `backend/core/stream_registry.py`. The switchboard imports it. To add a new watched set of values you add one entry and (if not already present) a trigger on the table.
- **Convention:** One logical stream per "thing" the UI or backend cares about (e.g. one stream `trades` for `users.trades_0001`). High-volume tables (e.g. orderbook rows) map to one stream (e.g. `orderbook`) and use statement-level or batched NOTIFY so we don’t emit one message per row.
- **Documentation:** This doc and the registry file list all streams. When adding a stream, add a short comment in the registry and, if useful, a line in this doc’s stream list.

---

## 5. Adding a watched set of values ("watch THIS")

To have the system (frontend and/or backend) watch a set of values backed by a table:

1. **Trigger on the table**  
   Use `public.rec_io_db_notify()` for row-level, or a custom statement-level trigger for high-volume tables (see Scalability below). Trigger fires on INSERT/UPDATE/DELETE and sends NOTIFY with `{"schema","table","op"}`.

2. **Register the table**  
   In `backend/core/stream_registry.py`, add `(schema, table) -> stream_name`. Stream name is the logical name consumers will filter on (e.g. `trades`, `orderbook`).

3. **Consumers**  
   - **Frontend:** Connect to `/ws/db_changes`, on message filter `data.database === stream_name`, then refetch or update UI (targeted refetch preferred for high-volume streams).
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
  - `redis_switchboard` maps those tables to logical streams (e.g. `account_balance`) via `stream_registry.py` and publishes `db_change` events.
  - The dashboard listens on `/ws/db_changes` and refetches from read_api when relevant streams change.

This pattern (read_api as canonical read surface, main as front door only, Redis/WS as the trigger) is the template for migrating other dashboard panels and assets.

---

## 7. Operational requirements

- **Redis:** Must be running. Switchboard and all backend subscribers depend on it.
- **Switchboard:** One process (e.g. under supervisor). LISTENs to PostgreSQL and publishes to Redis; serves `/ws/db_changes` and optionally `/ws/preferences`. Restart on failure; monitor via `/health`.
- **Triggers:** Applied via migrations. New tables that should be watched get a migration that adds the trigger and, when applicable, a note in the stream registry (registry is in code, so "add stream" is a code change plus migration).

---

## 8. Stream list (current)

| Stream name       | Source (schema.table)        | Notes                    |
|-------------------|------------------------------|---------------------------|
| `redis_basic_test` | testing.redis_basic_test   | Pilot / test stream       |
| `account_balance` | users.account_balance_0001 | Dashboard bankroll/portfolio panel |
| `live_symbol_status` | live_data.live_symbol_status | Canonical snapshot of latest symbol conditions (BTC/ETH): refetch on `db_change` |

**Canonical current-state rule (symbols):** treat `live_data.live_symbol_status` as the source of truth for "current" symbol price + condition percentiles (momentum/volatility/movement). The `live_price_log_1s_*` tables are the higher-resolution per-tick log used to derive/validate the snapshot and for debugging/analysis; consumers should prefer `live_symbol_status` for real-time decisions.

Planned next (Phase 1b): `trades` (users.trades_0001), `subaccounts` (users.subaccounts_0001) for the Performance panel. Add them to the registry and to this table when implemented. Keep the table in sync with `backend/core/stream_registry.py`.

---

## 9. Consistency checklist for new work

- **Scope first:** Run through Section 0 (Scope and boundaries). If what you're adding isn't "carry a DB change signal" or "register a stream," put it elsewhere.
- **New stream:** Add trigger (migration) + one registry entry + optional doc line in Stream list (Section 8). No new switchboard code.
- **New consumer:** Subscribe to Redis or WebSocket; filter by `database`; use only the payload contract. Consumer logic lives in the frontend or the backend service, not in the switchboard.
- **High-volume table:** Use statement-level or batched NOTIFY; document in registry and here; consider coalescing in switchboard only if the pattern is documented in this doc.
- **New endpoint on switchboard:** Unless it is health or the canonical WS path, do not add it without updating Section 0 and documenting the exception.
- **PostgreSQL utilization (when hooking up connections):** When adding a stream, moving a read/aggregate endpoint to read_api, or wiring a new consumer, consider whether that point is a good place to better utilize PostgreSQL—e.g. views, materialized views, stored functions, or trigger-maintained summary tables—for the data that connection serves. No obligation to add them every time; evaluate and adopt where it improves efficiency or clarity.
