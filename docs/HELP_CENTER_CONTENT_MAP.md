# REC.IO Help Center Content Map

UI-ready content map derived from `docs/SYSTEM_BIBLE.md`.

This file translates the System Bible into:
- help categories,
- article stubs,
- FAQ stubs,
- and searchable metadata (`slug`, `keywords`, `related_docs`).

Use this file as the implementation contract for the Help tab UI asset.

---

## 1) Content model contract

Each Help Center article should carry:

- `id`: stable unique id (e.g., `getting-started-overview`)
- `title`: display title
- `slug`: URL-safe path
- `category`: one of the categories in Section 2
- `audience`: `operator`, `trader`, `developer`, or `mixed`
- `summary`: 1-2 sentence description
- `keywords`: search terms
- `related_docs`: canonical deep-dive docs
- `status`: `stub`, `draft`, `ready`

---

## 2) Help tab categories

- Getting Started
- Using the Product
- Automation and Trading
- Data and Real-Time
- Troubleshooting
- Operations and Deployment
- Developer Reference

---

## 3) Article map (v1)

### Getting Started

#### Article: System Overview
- id: `getting-started-system-overview`
- slug: `getting-started/system-overview`
- audience: `mixed`
- summary: What REC.IO is, who it serves, and how the major parts fit together.
- keywords: `overview`, `architecture`, `components`, `roles`
- related_docs:
  - `docs/SYSTEM_BIBLE.md`
  - `docs/ARCHITECTURE.md`
- status: `stub`

#### Article: First Local Run
- id: `getting-started-first-local-run`
- slug: `getting-started/first-local-run`
- audience: `operator`
- summary: Prerequisites, environment setup, and first system startup.
- keywords: `setup`, `local`, `env`, `startup`, `master restart`
- related_docs:
  - `README.md`
  - `docs/DEPLOYMENT_GUIDE.md`
- status: `stub`

#### FAQ seed
- What do I need before first startup
- Which service should I check first if startup fails

### Using the Product

#### Article: Dashboard and Navigation
- id: `using-product-dashboard-navigation`
- slug: `using-product/dashboard-navigation`
- audience: `trader`
- summary: Primary UI surfaces, what each tab does, and where to find key workflows.
- keywords: `dashboard`, `tabs`, `navigation`, `ui`
- related_docs:
  - `docs/SYSTEM_BIBLE.md`
  - `docs/ARCHITECTURE.md`
- status: `stub`

#### Article: Monitor Management
- id: `using-product-monitor-management`
- slug: `using-product/monitor-management`
- audience: `trader`
- summary: Creating, enabling, disabling, and supervising monitors.
- keywords: `monitor`, `activate`, `deactivate`, `supervisor`
- related_docs:
  - `docs/MONITORS_LIST_INFRASTRUCTURE.md`
  - `docs/ARCHITECTURE.md`
- status: `stub`

#### Article: Account and History
- id: `using-product-account-history`
- slug: `using-product/account-history`
- audience: `trader`
- summary: Balances, account data, and historical views.
- keywords: `account`, `balance`, `history`, `read api`
- related_docs:
  - `docs/SYSTEM_BIBLE.md`
  - `docs/DERIVED_DATA_COMPUTE_MODEL.md`
- status: `stub`

#### FAQ seed
- Why a value in account history updates after refresh
- Which pages are real-time versus query-on-load

#### Article: Help Center Search and Navigation
- id: `using-product-help-center-navigation`
- slug: `using-product/help-center-navigation`
- audience: `mixed`
- summary: How to use Help categories, keyword search, and deep links to find system guidance quickly.
- keywords: `help center`, `search`, `categories`, `slug`, `navigation`
- related_docs:
  - `frontend/tabs/help.html`
  - `frontend/data/help_center_index.json`
  - `docs/SYSTEM_BIBLE.md`
- status: `stub`

### Automation and Trading

#### Article: Automated Trade Lifecycle
- id: `automation-trading-lifecycle`
- slug: `automation/automated-trade-lifecycle`
- audience: `mixed`
- summary: How monitor conditions lead to entries, management, and exits.
- keywords: `auto-entry`, `trade manager`, `executor`, `lifecycle`
- related_docs:
  - `docs/SYSTEM_BIBLE.md`
  - `docs/ARCHITECTURE.md`
- status: `stub`

#### Article: Live Trade Monitoring
- id: `automation-live-trade-monitoring`
- slug: `automation/live-trade-monitoring`
- audience: `trader`
- summary: Understanding active trade states and live status updates.
- keywords: `active trade`, `status`, `updates`, `trade monitor`
- related_docs:
  - `docs/REDIS_ARCHITECTURE.md`
  - `docs/REALTIME_BACKBONE.md`
- status: `stub`

#### FAQ seed
- Why a trade status can briefly lag
- What happens when execution fails or partially fills

### Data and Real-Time

#### Article: Real-Time Update Pipeline
- id: `data-realtime-pipeline`
- slug: `data/real-time-update-pipeline`
- audience: `developer`
- summary: DB changes to switchboard to Redis to WebSocket and UI refresh.
- keywords: `real-time`, `redis`, `switchboard`, `db changes`, `websocket`
- related_docs:
  - `docs/REALTIME_BACKBONE.md`
  - `docs/REDIS_ARCHITECTURE.md`
  - `docs/REDIS_DB_CHANGES_BACKEND_INTEGRATION.md`
- status: `stub`

#### Article: Derived Data and Read APIs
- id: `data-derived-read-apis`
- slug: `data/derived-data-read-apis`
- audience: `developer`
- summary: Query/compute model for read surfaces and derived metrics.
- keywords: `read_api`, `derived`, `metrics`, `queries`
- related_docs:
  - `docs/DERIVED_DATA_COMPUTE_MODEL.md`
  - `docs/ARCHITECTURE.md`
- status: `stub`

#### FAQ seed
- Why some values are computed on request
- What triggers a UI refetch in real-time views

### Troubleshooting

#### Article: Common Startup and Service Issues
- id: `troubleshooting-startup-services`
- slug: `troubleshooting/startup-services`
- audience: `operator`
- summary: Fast triage path for startup failures and unhealthy services.
- keywords: `troubleshooting`, `startup`, `supervisor`, `logs`, `restart`
- related_docs:
  - `README.md`
  - `docs/DEPLOYMENT_GUIDE.md`
- status: `stub`

#### Article: Data Freshness and Sync Issues
- id: `troubleshooting-data-freshness-sync`
- slug: `troubleshooting/data-freshness-sync`
- audience: `mixed`
- summary: Diagnosing stale UI, delayed updates, and sync gaps.
- keywords: `stale`, `sync`, `real-time`, `latency`, `refresh`
- related_docs:
  - `docs/PRODUCTION_SYNC_CHECKLIST.md`
  - `docs/REALTIME_BACKBONE.md`
- status: `stub`

#### FAQ seed
- What to check when data stops updating
- How to separate UI issue from backend issue

### Operations and Deployment

#### Article: Restart and Service Supervision
- id: `ops-restart-supervision`
- slug: `operations/restart-and-supervision`
- audience: `operator`
- summary: Restart model, service lifecycle, and expected post-restart checks.
- keywords: `master restart`, `supervisor`, `services`, `health`
- related_docs:
  - `docs/ARCHITECTURE.md`
  - `docs/DEPLOYMENT_GUIDE.md`
- status: `stub`

#### Article: Deployment and Sync Checklist
- id: `ops-deployment-sync-checklist`
- slug: `operations/deployment-sync-checklist`
- audience: `operator`
- summary: Safe deployment and environment sync baseline.
- keywords: `deployment`, `sync`, `checklist`, `production`
- related_docs:
  - `docs/PRODUCTION_SYNC_CHECKLIST.md`
  - `docs/AUTOMATIC_MAINTENANCE_DEPLOYMENT_PROTECTION.md`
- status: `stub`

#### FAQ seed
- Which checks are mandatory before/after deploy
- What is safe to retry during deployment

### Developer Reference

#### Article: Schema and Migration Protocol
- id: `dev-schema-migration-protocol`
- slug: `developer/schema-and-migrations`
- audience: `developer`
- summary: Required DB change workflow and drift prevention.
- keywords: `schema`, `migration`, `drift`, `database`
- related_docs:
  - `docs/MASTER_DB_SCHEMA_REFERENCE.md`
  - `docs/PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md`
  - `scripts/db/README.md`
- status: `stub`

#### Article: Documentation and Change Discipline
- id: `dev-docs-change-discipline`
- slug: `developer/docs-and-change-discipline`
- audience: `developer`
- summary: How to keep docs/changelog and feature map canonical with code changes.
- keywords: `documentation`, `changelog`, `standards`, `canonical`
- related_docs:
  - `docs/SYSTEM_BIBLE.md`
  - `docs/changelog/MASTER_CHANGELOG.md`
  - `docs/PROFESSIONAL_DEV_STANDARDS_CHECKLIST.md`
- status: `stub`

#### FAQ seed
- Which docs must change when adding a feature
- How to decide if a change is major enough for System Bible updates

---

## 4) Search index seed

Initial global keyword set for Help UI indexing:

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

## 5) Maintenance workflow

When features change:

1. Update `docs/SYSTEM_BIBLE.md` feature map and/or flow sections.
2. Update this map:
   - add/edit article stubs,
   - update keywords/tags,
   - update related docs.
3. Update `docs/changelog/MASTER_CHANGELOG.md` when release-relevant.
4. Ensure `docs/README.md` still points to canonical manual docs.

Completion check for feature work:
- `SYSTEM_BIBLE` updated or explicitly marked "no impact"
- `HELP_CENTER_CONTENT_MAP` updated or explicitly marked "no impact"

