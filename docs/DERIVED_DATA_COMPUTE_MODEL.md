# Derived data and compute: recommended model

This doc spells out how we handle aggregated/derived data (e.g. PnL totals, dashboard summaries) so we do **not** end up with many independent scripts watching Redis and doing calculations. **Full architecture (read_api, switchboard, main, flow):** [REDIS_ARCHITECTURE.md](REDIS_ARCHITECTURE.md). See [REALTIME_BACKBONE.md](REALTIME_BACKBONE.md) Section 6b for the constraint.

---

## Recommended model: read_api (on-demand read APIs)

**Name:** **read_api** — one persistent process run under supervisor (e.g. program name `read_api`; module `backend/read_api.py`).

**Who computes:** **read_api**. It hosts all endpoints like `GET /api/performance/realized`, `GET /api/account/balance`, `GET /api/subaccounts`, monitor list and stats, portfolio history, and every other read/aggregate endpoint. When a client calls one of these, read_api runs the query, computes and formats, and returns the result. It does NOT subscribe to Redis. Main does NOT run these queries; they live in read_api only.

**Who triggers the computation:** The client. Redis/WS deliver "trades changed" (or "account_balance changed," etc.). The frontend that cares about the Performance panel listens for `database === 'trades'` and then **refetches** `GET /api/performance/realized`. The computation happens once per refetch, in the API, on demand. No backend subscriber is watching the stream to do the math.

**Why this is streamlined:**

1. **Zero new processes** for derived data. No "PnL watcher," no "dashboard aggregator" process.
2. **One pattern** for every derived value: expose an API that runs a query when called; clients refetch when they see the relevant stream change.
3. **No cache invalidation** across services. No "when trades change, tell the PnL service to invalidate."
4. **Adding a new derived value** = add an endpoint (and maybe a DB view or query). Still no new watchers.

**If reads get expensive:** Add a **short TTL cache** (e.g. 5–15 seconds) inside the API layer for that endpoint. Multiple refetches in the same window get the same cached response. No Redis subscriber, no separate cache service. If you later outgrow that, introduce materialized views or a summary table and keep the same "on-demand read" contract.

---

## In practice

- **read_api:** Exposes all read/aggregate endpoints. Request in → run query (and any calculation/formatting) → return JSON. No Redis, no WebSocket. Runs under supervisor alongside main and switchboard.
- **Frontend:** Subscribes to `/ws/db_changes` (from switchboard). On `trades` → refetch read_api's performance endpoint. On `account_balance` or `subaccounts` → refetch read_api's balance/subaccounts endpoints. read_api runs the query when the frontend refetches.
- **Backend subscribers to Redis** are for **reaction** (e.g. "when trades change, run this business action" or "send an alert when PnL crosses a threshold"), not for "recompute every display aggregate." If you add such a subscriber, it is one specific feature, not a generic "compute all aggregates" watcher.

---

## Alternatives (only if needed)

- **DB materialized views or summary tables:** Use when the on-demand query is too heavy (e.g. very large tables, many concurrent requests). One refresh strategy (trigger or scheduled job) updates the summary; APIs read from it. Still one place that owns the derived state; no N watchers.
- **One aggregate service that subscribes to Redis:** Consider only if you need sub-second freshness and the query is too slow to run on every refetch. That service would be the **only** subscriber that does computation, with a single cache and a clear list of "what I compute." Do not add a second such service without updating REALTIME_BACKBONE Section 6b and this doc.

---

## Rule

Before adding any backend subscriber that performs calculations, confirm it fits this model (reaction for a specific feature) or document the exception in REALTIME_BACKBONE Section 6b.
