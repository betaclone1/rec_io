# Redis platform initiative (real-time backbone)

**Goal:** PostgreSQL + Redis as the real-time backbone: any change to watched DB state flows through one pipeline to all frontend and backend consumers. Replace main.py’s role as the nervous system with a scoped, documented, scalable design that avoids bloat.

**Scope:** In: DB-driven events (NOTIFY → switchboard → Redis → WS + Redis subscribers), stream registry, single payload contract, scope governance; **read_api** (single persistent process for all read/aggregate endpoints, run under supervisor); main slimmed (no read/aggregate routes, no broadcast); frontend refetches read_api on db_change signal. Out: production rollout (separate phases); preferences channel and publish helper (follow when DB-driven pilot is stable).

**Status:** in progress

---

## Canonical docs (single source of truth)

| Doc | Purpose |
|-----|--------|
| **docs/REDIS_ARCHITECTURE.md** | **Full recommended architecture in detail:** read_api (name, role, endpoints), switchboard, main (slimmed), end-to-end flow, supervisor target state. Single source for how the pieces fit together. |
| **docs/REALTIME_BACKBONE.md** | Backbone only: NOTIFY, payload contract, stream registry, **Section 0 = scope/governance**, how to add watched state, scalability, stream list. |
| **backend/core/stream_registry.py** | The only mapping (schema, table) → stream name. Add entries here when adding a stream. |
| **docs/REDIS_DB_CHANGES_BACKEND_INTEGRATION.md** | How backends subscribe to Redis; same payload as WS. |
| **docs/redis_switchboard_structure.md** | Switchboard implementation and migration from main.py (two channels, WS endpoints, publish helper, phased migration). |
| **docs/MASTER_DB_SCHEMA_REFERENCE.md** | Trigger function `public.rec_io_db_notify()`, how to add triggers, link to backbone. |
| **docs/ARCHITECTURE.md** | High-level: Redis and Switchboard in components; real-time data flow; key path to REALTIME_BACKBONE. |
| **AGENTS.md** | Real-time backbone convention: follow REALTIME_BACKBONE Section 0 and Section 9 when touching switchboard/registry/streams. |
| **docs/REDIS_LEGACY_COMMS_AUDIT.md** | **Migration checklist:** full audit of backend and frontend use of legacy notify/broadcast API and WS; asset-by-asset checklist to plug in Redis/WS and remove main.py bloat. |
| **docs/DERIVED_DATA_COMPUTE_MODEL.md** | **Derived data / compute:** recommended model (on-demand read APIs, no backend watchers for aggregates); when to use alternatives. |

When in doubt, **REALTIME_BACKBONE.md** is the source of truth. When implementing the refactor, work from **REDIS_LEGACY_COMMS_AUDIT.md**. Do not add behavior that contradicts Section 0 (scope and boundaries) without updating that section.

---

## Done (tracked for PM)

- [x] PostgreSQL NOTIFY trigger on a pilot table (`testing.redis_basic_test`) with generic `public.rec_io_db_notify()`.
- [x] Switchboard process: LISTEN → map (schema, table) → stream name → Redis publish → WebSocket `/ws/db_changes` fan-out; `/health`; pilot test page and GET/POST for pilot table.
- [x] Stream registry: `backend/core/stream_registry.py` as single source of (schema, table) → stream name; switchboard loads it.
- [x] Canonical backbone doc: **docs/REALTIME_BACKBONE.md** (pipeline, payload, registry, adding streams, scalability, **Section 0 scope/governance**, stream list, checklist).
- [x] Backend integration doc and runnable example script (`scripts/redis_db_changes_subscriber_example.py`).
- [x] Scope and anti-bloat: Section 0 in REALTIME_BACKBONE; SCOPE comments in `stream_registry.py` and `redis_switchboard.py`; “where things live” table; checklist in Section 9.
- [x] ARCHITECTURE.md updated (Redis, Switchboard, real-time flow, key paths to backbone docs).
- [x] MASTER_DB_SCHEMA_REFERENCE.md: real-time section with trigger and link to backbone + registry.
- [x] AGENTS.md: Real-time backbone convention for agents.
- [x] Cross-links: redis_switchboard_structure, REDIS_DB_CHANGES_BACKEND_INTEGRATION, and schema reference point to REALTIME_BACKBONE.

---

## Steps (phased; update as phases are scheduled)

1. ~~Document current messaging/broadcast patterns~~ — Superseded by DB-driven design; backbone doc is the architecture.
2. ~~Pilot NOTIFY + switchboard + Redis + one stream~~ — Done (redis_basic_test).
3. ~~Audit legacy comms~~ — Done: **docs/REDIS_LEGACY_COMMS_AUDIT.md** (backend + frontend checklist).
4. **Next (when scheduled):** Add production streams (e.g. trades, fills, positions, settlements) via trigger + registry entry per table; no new switchboard code.
5. **Next (when scheduled):** Main app subscribes to Redis and broadcasts to its existing `db_change_clients` so frontend can stay on main’s origin while events come from DB.
6. **Next (when scheduled):** Implement **read_api** (one process, all read/aggregate endpoints); run under supervisor. Move endpoints from main to read_api per REDIS_LEGACY_COMMS_AUDIT.
7. **Next (when scheduled):** Work through REDIS_LEGACY_COMMS_AUDIT: backend publish to Redis (or rely on triggers), frontend WS to switchboard (or proxy), frontend refetch read_api on signal; remove main.py read endpoints and client sets. **As part of this process:** at each connection point (new stream, moved endpoint, new consumer), evaluate whether there is opportunity to better utilize PostgreSQL (views, materialized views, stored functions, summary tables) for that area—see REALTIME_BACKBONE Section 9.
8. **Later:** Preferences channel and `publish_preferences_message` / backend publish helper; complete audit Part C (endpoint removal).

---

## Phase 1: Dashboard — high priority

**Focus:** Rework dashboard (desktop and mobile) to work exclusively with the new Redis backbone for **data** (db_changes + read_api). Preferences stay on main for now; we do not touch `/ws/preferences` or the preferences channel in this phase.

**Scope for Phase 1:** Dashboard as the target asset; implementation is **incremental slices**, not a single cutover.

**Implementation order (small slices first):**

1. **read_api skeleton** — Stand up read_api process (e.g. `backend/read_api.py`), run under supervisor; one or two dashboard endpoints to start (e.g. performance realized, portfolio history or balance). Verify proxy from main or direct call works.
2. **Switchboard connectivity** — Confirm dashboard (or a test page) can connect to switchboard for `/ws/db_changes`, receive payloads, and refetch in response. May use existing pilot stream initially.
3. **Production streams for first panels** — Add triggers + registry entries for the tables that feed portfolio and performance (e.g. trades, account_balance, subaccounts as needed).
4. **Portfolio and performance panels first** — Wire these panels to use `/ws/db_changes` (filter by relevant stream names) and refetch from read_api. Leave other dashboard panels (e.g. monitor list) on main for now.
5. **Expand** — Add streams and read_api endpoints for remaining dashboard panels (monitor list/stats, etc.); migrate those panels the same way. Document patterns so trade_history, trade_monitor, account_manager can follow.

**Rationale:** Dashboard is the reference asset; doing it in slices (read_api → connectivity → portfolio + performance → rest) keeps each step testable and avoids debugging the whole stack at once. Learnings apply to the rest of the migration.

**Phase 1a (completed): Bankroll / Portfolio / PnL top panel**

- `read_api` process created (`backend/read_api.py`) and running under supervisor as a core service.
- All read/aggregate logic for the dashboard bankroll/portfolio/PnL panel moved from `backend/main.py` into `read_api`:
  - `/api/portfolio/history`
  - `/api/bankroll/history`
  - `/api/pnl/history`
  - `/api/performance/realized`
- The corresponding routes in `backend/main.py` are now **thin proxies** that forward requests to `read_api` and return its JSON; no remaining SQL or aggregation for this panel in main.
- PostgreSQL NOTIFY triggers and `stream_registry.py` wiring added for the `account_balance` stream, so db_changes for bankroll/portfolio state flow through the backbone into `redis_switchboard` and the dashboard WebSocket.
- Desktop and mobile dashboard assets updated in lockstep so the bankroll/portfolio/PnL panel uses the same Redis + read_api backbone pattern on both surfaces.

**Status:** Phase 1a complete; remaining dashboard panels (performance tiles, monitor tiles, allocation, etc.) will be migrated in subsequent slices using the same pattern.

---

## Phase 1b: Performance panel (next)

**Scope:** The dashboard Performance panel: four rows (Day / Week / Month / Year) showing realized PnL, return %, and comparison to prior period, plus Cash Balance. Desktop and mobile.

**Current state:**
- **Realized metrics:** Served by `GET /api/performance/realized`. Logic already lives in `read_api`; `main.py` proxies. Computes from `users.trades_0001` (filters: test_filter FALSE, paper_trade FALSE, status closed/settled), Eastern time windows, SUM(pnl), SUM(ret_pct), SUM(ret_pct_base) per period and prev_pnl for same-length prior window.
- **Cash balance:** Served by `GET /api/subaccounts` from `main.py` only; reads `users.subaccounts_0001`; frontend picks subaccount `"Cash Transfer"` and displays balance (cents → dollars). Same endpoint used by account_manager (read + write); only the read is in scope for this panel.

**Implementation plan:**

1. **Read path (read_api + main proxy)**
   - Confirm `/api/performance/realized` remains the single source of truth in read_api (no change needed).
   - Add `GET /api/subaccounts` to read_api (read-only: SELECT from `users.subaccounts_0001`, return `{ "subaccounts": [...] }`). Add thin proxy in main so dashboard (and account_manager) continue to call main; main forwards GET to read_api. (PATCH/POST subaccounts stay in main.)
   - After parity check, performance panel is fully served by read_api for its two data sources.

2. **Streams and refresh triggers**
   - Add production stream **`trades`**: `(users, trades_0001)` → `trades`. Migration: NOTIFY trigger on `users.trades_0001` using `public.rec_io_db_notify()`. When trades change, dashboard can refetch `/api/performance/realized`.
   - Add production stream **`subaccounts`**: `(users, subaccounts_0001)` → `subaccounts`. Migration: NOTIFY trigger on `users.subaccounts_0001`. When subaccounts change, dashboard can refetch `/api/subaccounts` for the cash balance.
   - Update dashboard (desktop + mobile) so that on `db_change` for `trades` or `subaccounts` (in addition to existing bankroll-related streams) it calls `loadPerformanceData()` and `loadPerformancePanelCashBalance()`.

3. **Optional: PostgreSQL summary for performance**
   - **Evaluate** at implementation time: Current `/api/performance/realized` runs four period × two queries (current + prev) over `trades_0001`. For typical volume this may be fine. If we want to streamline further:
     - Option A: Keep on-demand aggregation (no schema change).
     - Option B: Add a small table or materialized view (e.g. `users.performance_realized_summary_0001`) keyed by period type + period start, maintained by trigger on `trades_0001` or by a lightweight job; read_api reads from it. Document in REALTIME_BACKBONE Section 9 and MASTER_DB_SCHEMA_REFERENCE if adopted.
   - Decision: implement with on-demand first; introduce a summary table only if profiling shows need.

4. **Frontend**
   - No structural change to the performance panel UI. Ensure it refreshes only from:
     - Initial load.
     - db_change events for streams `trades`, `subaccounts` (and any already-triggered bankroll streams that we keep for consistency).
   - Remove or avoid any polling that duplicates this. Desktop and mobile in lockstep.

5. **Docs and checklist**
   - Update `docs/REALTIME_BACKBONE.md` stream list (Section 8) with `trades` and `subaccounts` once added.
   - Update `docs/REDIS_LEGACY_COMMS_AUDIT.md` dashboard asset checklist: mark Performance panel as Phase 1b (in progress → done as steps complete).
   - If a new summary table/view is added, update `docs/MASTER_DB_SCHEMA_REFERENCE.md` and `backend/core/config/database.py` per DB change protocol.

**Completion criteria for Phase 1b:**
- [ ] `GET /api/subaccounts` implemented in read_api; main proxies GET to read_api.
- [ ] Streams `trades` and `subaccounts` registered and NOTIFY triggers applied via migrations.
- [ ] Dashboard (desktop + mobile) refreshes performance panel on db_change for `trades` and `subaccounts`.
- [ ] Asset checklist updated; REALTIME_BACKBONE stream list updated.
- [ ] Optional: If summary table added, schema ref and backbone doc updated.

---

## Notes for trade_manager / ATS refactor

- When we migrate **trade_manager** and **active_trade_supervisor** to use Redis streams instead of direct HTTP calls into main/monitor_manager, we must **harden the monitor confirmation pipeline**:
  - Today, a transient failure on the `monitor_manager bulk notification` path (HTTP 500) can leave trades untracked by ATS, so `trade_manager` sees `high_price == low_price` at expiry and sets `monitor_confirmed = FALSE` even though price data and AES are healthy.
  - Under the Redis design, the “attach this cycle to ATS” signal should be **durable and replayable** (e.g. Redis stream with consumer group), so a transient outage in main/monitor_manager/ATS cannot permanently drop a trade from tracking.
  - Stop-loss and monitor confirmation reliability for strategies like **Momentum Contain / HTC** depends on this; we will address it as part of the Redis-driven refactor rather than continuing to patch the legacy HTTP workflow.

- When we refactor **monitor_manager** for Redis, also re‑design **position sizing / `total_position` maintenance**:
  - Current behavior: `total_position` is updated only on specific API paths (bankroll updates, position‑variable updates, monitor create) and can silently drift when edits happen via different paths or when fields are NULL; there is no single canonical recalculation on restart.
  - Target behavior: one **canonical source of truth** for total_position (and related sizing fields), plus a Redis‑backed event pipeline so that any change to bankroll/position settings deterministically recomputes and persists `total_position` for all relevant monitors (with visibility into skipped/invalid rows), instead of the current best‑effort HTTP calls.

---

## Completion criteria (initiative-level)

- [x] A real-time architecture doc exists (REALTIME_BACKBONE) with pipeline, contract, registry, and scope governance.
- [x] Pilot works end-to-end: DB change → NOTIFY → switchboard → Redis → WS and Redis subscriber.
- [x] Backend integration is documented and exemplified; same payload as frontend.
- [x] Scope and anti-bloat rules are in the canonical doc and in code (SCOPE comments); AGENTS.md references them.
- [ ] **read_api** implemented and running under supervisor; all read/aggregate endpoints moved from main to read_api (per REDIS_ARCHITECTURE).
- [ ] Production streams added and frontend/backend consuming (when scheduled).
- [ ] main.py no longer owns real-time fan-out or read/aggregate endpoints (when scheduled).

---

## Blockers / decisions

- Production rollout and main.py migration depend on schedule/maintenance windows; do not implement until explicitly scheduled.
- Any expansion of switchboard or registry scope (new endpoint types, new metadata) must update REALTIME_BACKBONE Section 0 and this plan.
- **Derived data / compute:** We will not add many independent scripts watching Redis to do calculations. REALTIME_BACKBONE Section 6b + docs/DERIVED_DATA_COMPUTE_MODEL.md: recommended model is on-demand read APIs (client refetches when stream changes); no backend watchers for aggregates. Alternatives (materialized views, one aggregate service) only if needed.

---

## Keeping PM in sync

- **When adding a stream:** Update stream registry, add trigger (migration), optionally add a line to REALTIME_BACKBONE stream list (Section 8). No need to add a new plan file; this initiative covers the backbone.
- **When changing scope or governance:** Update REALTIME_BACKBONE Section 0 and Section 9, and this plan’s “Canonical docs” or “Blockers / decisions” if needed.
- **When starting a phased rollout (e.g. production streams):** Update “Steps” and “Completion criteria” in this plan; optionally create a short-lived plan for that phase (e.g. `redis-production-streams-rollout.md`) linked from here.
