# REC.IO documentation

Minimal index for current system. Historical and one-off docs were moved to `archive/2026-03-housekeeping/` (see INDEX there).

## Overview

| Doc | Use |
|-----|-----|
| [SYSTEM_BIBLE.md](SYSTEM_BIBLE.md) | Canonical product/manual backbone: feature inventory, end-to-end flows, Help Center IA seed, and search tags. |
| [HELP_CENTER_CONTENT_MAP.md](HELP_CENTER_CONTENT_MAP.md) | UI-ready Help Center contract: categories, article stubs, FAQ seeds, metadata, and search mapping. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level components, data flow, and key paths. |
| [REDIS_ARCHITECTURE.md](REDIS_ARCHITECTURE.md) | **Redis / real-time architecture (full):** read_api (name, role, endpoints), switchboard, main slimmed, end-to-end flow, supervisor target. Single source for how the pieces fit together. |
| [REALTIME_BACKBONE.md](REALTIME_BACKBONE.md) | **Real-time backbone:** PostgreSQL + Redis pipeline, stream registry, payload contract, scope governance (Section 0). PM: `.cursor/plans/redis-platform-initiative.md`. |

## Runbooks and reference

| Doc | Use |
|-----|-----|
| [PRODUCTION_HOST.md](PRODUCTION_HOST.md) | Canonical production IPv4, env vars (`REC_PROD_SSH_HOST` / `REC_PROD_DB_HOST`), server paths |
| [PRODUCTION_SYNC_CHECKLIST.md](PRODUCTION_SYNC_CHECKLIST.md) | Production deploy and sync steps |
| [PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md](PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md) | DB schema and backfill (e.g. `backfill_trades_volatility_movement.py`) |
| [MASTER_DB_SCHEMA_REFERENCE.md](MASTER_DB_SCHEMA_REFERENCE.md) | Schema reference; used by drift check and DB work |
| [MASTER_DATABASE_REGISTRATION_GUIDE.md](MASTER_DATABASE_REGISTRATION_GUIDE.md) | DB registration |
| [REDIS_DB_CHANGES_BACKEND_INTEGRATION.md](REDIS_DB_CHANGES_BACKEND_INTEGRATION.md) | Backend subscription to Redis db_changes |
| [redis_switchboard_structure.md](redis_switchboard_structure.md) | Switchboard implementation and main.py migration plan |
| [REDIS_LEGACY_COMMS_AUDIT.md](REDIS_LEGACY_COMMS_AUDIT.md) | Checklist: legacy notify/broadcast and WS usage (backend + frontend) to migrate to Redis/WS |
| [DERIVED_DATA_COMPUTE_MODEL.md](DERIVED_DATA_COMPUTE_MODEL.md) | Derived data / compute: on-demand read APIs, no backend watchers; when to use alternatives |

**Agent command docs** (verify, system-restart, log-chat) live in **`.cursor/`**, not in `docs/`. See [.cursor/commands/README.md](../.cursor/commands/README.md).

## Deploy and install

| Doc | Use |
|-----|-----|
| [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | Deployment procedures |
| [AUTHENTICATION_GUIDE.md](AUTHENTICATION_GUIDE.md) | Auth setup |
| [QUICK_INSTALL_GUIDE.md](QUICK_INSTALL_GUIDE.md) | Quick install |
| [DIGITAL_OCEAN_DEPLOYMENT_GUIDE.md](DIGITAL_OCEAN_DEPLOYMENT_GUIDE.md) | Digital Ocean deploy |
| [INSTALLATION_PACKAGE_SUMMARY.md](INSTALLATION_PACKAGE_SUMMARY.md) | Install package summary |
| [AUTOMATIC_MAINTENANCE_DEPLOYMENT_PROTECTION.md](AUTOMATIC_MAINTENANCE_DEPLOYMENT_PROTECTION.md) | Maintenance protection |
| [SYSTEM_DATA_PACKAGING.md](SYSTEM_DATA_PACKAGING.md) | Data export/import |

## Product and operations

| Doc | Use |
|-----|-----|
| [MONITORS_LIST_INFRASTRUCTURE.md](MONITORS_LIST_INFRASTRUCTURE.md) | Monitor list behavior |
| [PROJECT_HOUSEKEEPING_AUDIT_PLAN.md](PROJECT_HOUSEKEEPING_AUDIT_PLAN.md) | Housekeeping and archive plan |
| [LONG_TERM_INITIATIVES.md](LONG_TERM_INITIATIVES.md) | Cross-cutting backlog (e.g. multi-user / hardcoded `0001` sweep) |

## Standards and changelog

- **[PROFESSIONAL_DEV_STANDARDS_CHECKLIST.md](PROFESSIONAL_DEV_STANDARDS_CHECKLIST.md)** — Checklist for repo structure, tests, CI, env, and docs (research-backed).
- **[changelog/](changelog/)** — [MASTER_CHANGELOG.md](changelog/MASTER_CHANGELOG.md) (releases), [TODO.md](changelog/TODO.md) (pointer to task tracking in `.cursor/plans/`), [todo_docs/](changelog/todo_docs/) (design and audit docs).

## Archived

Older docs, one-off reports, VER3 snapshot, and legacy archive: **`archive/2026-03-housekeeping/docs/`**. See **`archive/2026-03-housekeeping/INDEX.md`** for the full list.
