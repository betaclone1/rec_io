# REC.IO documentation

Minimal index for current system. Historical and one-off docs were moved to `archive/2026-03-housekeeping/` (see INDEX there).

## Overview

| Doc | Use |
|-----|-----|
| [ARCHITECTURE.md](ARCHITECTURE.md) | High-level components, data flow, and key paths. |

## Runbooks and reference

| Doc | Use |
|-----|-----|
| [PRODUCTION_SYNC_CHECKLIST.md](PRODUCTION_SYNC_CHECKLIST.md) | Production deploy and sync steps |
| [PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md](PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md) | DB schema and backfill (e.g. `backfill_trades_volatility_movement.py`) |
| [MASTER_DB_SCHEMA_REFERENCE.md](MASTER_DB_SCHEMA_REFERENCE.md) | Schema reference; used by drift check and DB work |
| [MASTER_DATABASE_REGISTRATION_GUIDE.md](MASTER_DATABASE_REGISTRATION_GUIDE.md) | DB registration |

**Agent command docs** (verify, system-restart, log-chat) live in **`.cursor/pm/`**, not in `docs/`. See [.cursor/pm/README.md](../.cursor/pm/README.md).

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

## Standards and changelog

- **[PROFESSIONAL_DEV_STANDARDS_CHECKLIST.md](PROFESSIONAL_DEV_STANDARDS_CHECKLIST.md)** — Checklist for repo structure, tests, CI, env, and docs (research-backed).
- **[changelog/](changelog/)** — [MASTER_CHANGELOG.md](changelog/MASTER_CHANGELOG.md) (releases), [TODO.md](changelog/TODO.md) (pointer to task tracking in `.cursor/plans/`), [todo_docs/](changelog/todo_docs/) (design and audit docs).

## Archived

Older docs, one-off reports, VER3 snapshot, and legacy archive: **`archive/2026-03-housekeeping/docs/`**. See **`archive/2026-03-housekeeping/INDEX.md`** for the full list.
