# REC.IO System Bible

Canonical backbone for product documentation and future Help Center UI content.

This document defines:
- what the system does,
- who uses it,
- where each feature lives,
- how core workflows run end-to-end,
- and where to find deeper technical or operational references.

Use this as the single entry point for manual/help content. Keep detailed implementation notes in linked docs.

---

## 1) Purpose and scope

REC.IO is an automated trading platform for prediction markets with:
- live data ingestion,
- monitor-driven automated entry,
- trade lifecycle management,
- account and performance visibility,
- and operations controls for reliability and safety.

This bible is product-first and user-manual oriented. It is not a replacement for low-level architecture or migration docs.

---

## 2) Primary user roles

- **Operator/Admin**: Configures system, deploys, monitors health, manages runbooks.
- **Trader**: Uses UI to monitor markets, monitors, trades, account history, and performance.
- **Developer/Maintainer**: Extends code, migrations, services, and internal documentation.

---

## 3) Product surfaces

- **Web UI (`frontend/`)**
  - Desktop and mobile tabs for dashboard, trade monitoring, account/history, settings, and system views.
- **Backend services (`backend/`)**
  - APIs, supervisors, trading automation, account sync, watchdogs, stream/switchboard integrations.
- **Operations scripts (`scripts/`)**
  - Restart/deploy, migration/drift checks, backup, config generation, monitor/user management.
- **Data layer**
  - PostgreSQL (`users`, `live_data`, `system`) and Redis real-time transport.

---

## 4) Core feature map (manual backbone)

This section is the canonical feature inventory for Help Center IA.

### A. Authentication and access
- User login/access to main application.
- Environment and credentials setup for market integrations.
- Related docs:
  - `README.md`
  - `docs/DEPLOYMENT_GUIDE.md`

### B. Dashboard and system overview
- Top-level operational visibility for active system state.
- Entry point for navigating core tabs and status signals.
- Related docs:
  - `docs/ARCHITECTURE.md`
  - `docs/MONITORS_LIST_INFRASTRUCTURE.md`

### C. Monitor management
- Create, activate/deactivate, and supervise monitor configurations.
- Per-monitor process lifecycle under supervisor and monitor manager.
- Related docs:
  - `docs/MONITORS_LIST_INFRASTRUCTURE.md`
  - `docs/ARCHITECTURE.md`

### D. Automated trading lifecycle
- Signal/condition evaluation to open trades.
- Trade lifecycle management (open, manage, close).
- Order execution path to external trading venue.
- Related docs:
  - `docs/ARCHITECTURE.md`
  - `docs/REALTIME_BACKBONE.md`

### E. Trade monitoring (live)
- Current trade visibility, status transitions, and update propagation.
- Real-time update model via DB changes and stream events.
- Related docs:
  - `docs/REDIS_ARCHITECTURE.md`
  - `docs/REALTIME_BACKBONE.md`
  - `docs/REDIS_DB_CHANGES_BACKEND_INTEGRATION.md`

### F. Account, balances, and history
- Balance and account read endpoints.
- Historical data and account-oriented reporting surfaces.
- Related docs:
  - `docs/ARCHITECTURE.md`
  - `docs/DERIVED_DATA_COMPUTE_MODEL.md`

### G. Performance and analytics
- Realized/unrealized and portfolio-style read models.
- CLI/GUI analytics tooling for deeper analysis workflows.
- Related docs:
  - `docs/ARCHITECTURE.md`
  - `backend/util/analytics/README.md`

### H. Real-time backbone
- PostgreSQL NOTIFY -> switchboard -> Redis -> WebSocket -> UI refresh pattern.
- Stream registry contract and payload flow boundaries.
- Related docs:
  - `docs/REALTIME_BACKBONE.md`
  - `docs/REDIS_ARCHITECTURE.md`
  - `docs/redis_switchboard_structure.md`

### I. Data model and schema governance
- Canonical schema reference and migration protocol.
- Drift checks and registration/update expectations.
- Related docs:
  - `docs/MASTER_DB_SCHEMA_REFERENCE.md`
  - `docs/PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md`
  - `scripts/db/README.md`

### J. Deployment, restart, and maintenance
- Full restart model and process supervision.
- Deployment/sync checklist and maintenance protections.
- Related docs:
  - `docs/DEPLOYMENT_GUIDE.md`
  - `docs/PRODUCTION_SYNC_CHECKLIST.md`
  - `docs/AUTOMATIC_MAINTENANCE_DEPLOYMENT_PROTECTION.md`

### K. Safety, standards, and change discipline
- Coding and release discipline for reliability.
- Changelog conventions and standards checklist.
- Related docs:
  - `docs/PROFESSIONAL_DEV_STANDARDS_CHECKLIST.md`
  - `docs/changelog/MASTER_CHANGELOG.md`

### L. Help Center and user manual navigation
- Built-in Help tab provides searchable, category-based manual navigation.
- Content is sourced from canonical manual docs and indexed metadata.
- Supports deep-link article routes by slug for direct navigation/sharing.
- Related docs:
  - `docs/HELP_CENTER_CONTENT_MAP.md`
  - `frontend/data/help_center_index.json`

---

## 5) End-to-end system flows

These are the anchor flows that Help Center topics should map to.

### Flow 1: Market data to UI visibility
1. External market data is ingested by backend market/watchdog services.
2. Data is written to PostgreSQL live-data tables.
3. DB change signals propagate via switchboard + Redis + WebSocket.
4. UI receives stream event and refreshes read endpoints for current view.

### Flow 2: Monitor to automated trade
1. Monitor config is active.
2. Entry supervisor evaluates market and strategy conditions.
3. Trade manager opens/manages lifecycle.
4. Executor places orders and sync services reconcile account/trade state.
5. UI reflects updates through read APIs plus real-time signals.

### Flow 3: User read/query path
1. User opens dashboard, trade, or account view.
2. UI requests read endpoints from main/read API surfaces.
3. Backend executes DB queries and derived computations.
4. UI renders state and listens for stream-driven refresh triggers.

---

## 6) Help Center information architecture seed

Use this taxonomy to build Help tab navigation.

- **Getting Started**
  - System purpose, prerequisites, first run
- **Using the Product**
  - Dashboard, monitors, trade monitor, account/history, settings
- **Automation and Trading**
  - How automated entries work, lifecycle, risk controls
- **Data and Real-Time**
  - Live updates, delayed/stale data behavior, refresh model
- **Troubleshooting**
  - Common failures, restart paths, log-first diagnostics
- **Operations and Deployment**
  - Deploy, sync, restart, health verification
- **Developer Reference**
  - Architecture, schema, migrations, standards, changelog

---

## 7) Search keywords and tagging baseline

Recommended tags for future UI search indexing:

- `dashboard`
- `monitor`
- `auto-entry`
- `trade manager`
- `trade executor`
- `active trade`
- `account history`
- `performance`
- `real-time`
- `redis`
- `switchboard`
- `schema`
- `migration`
- `deployment`
- `restart`
- `troubleshooting`

---

## 8) Canonical source policy

To keep this document canonical and useful:

- Keep this file as the top-level feature and flow map.
- Add links to deeper docs rather than copying implementation detail.
- Update this file whenever:
  - a major feature is added/removed,
  - primary flow behavior changes,
  - or Help Center taxonomy needs to expand.
- Prefer one concept in one home:
  - this file for feature/flow inventory,
  - linked docs for deep technical detail.

---

## 9) Planned next step for Help tab implementation

When building the Help tab UI asset, treat this file as the content contract:

- Parse section headers into navigation groups.
- Parse feature map and flows into article stubs.
- Surface related-doc links as "Deep Dive" references.
- Attach search tags from Section 7 for quick lookup.

Current implementation baseline:
- Desktop Help tab: searchable categories, audience filters, article detail panes.
- Deep-link support: `#/help/<slug>` within Help tab.
- Mobile parity: Help tab available in mobile navigation and loads the same Help content surface.

