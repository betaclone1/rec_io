# Tenant init, migrations, and provisioning

## Authoritative schema evolution (migrations only)

- **All ongoing schema changes** (new columns, tables, alters, type fixes) are applied via **reversible migration pairs** under [`scripts/migrations/`](../scripts/migrations/) and [`scripts/db/run_migration.py`](../scripts/db/run_migration.py). Applied ids are recorded in **`system.schema_migrations`**.
- **Do not** extend **`init_database()`** with new `ALTER TABLE` / `ADD COLUMN` / repair blocks for environments that should already exist. That path is **legacy greenfield bootstrap**; adding DDL there duplicates migrations, hides drift, and breaks the rule that production can replay a single migration history.
- Runtime **fail-fast** catalog checks (e.g. `backend/core/db_schema_contract.py`) complement migrations: if the DB exists but required objects are missing, processes exit with **`DB_SCHEMA_MISMATCH`** instead of limping.

## `init_database()` vs per-tenant provisioning

- **`init_database()`** in [`backend/core/config/database.py`](../backend/core/config/database.py) bootstraps **shared** schemas (`live_data`, `system`, `testing`, …) and applies template DDL for the **default tenant** schema from `default_pg_schema_for_init()` (typically `users_0001`). It is a **greenfield / legacy one-shot** entrypoint, not a substitute for onboarding every trading user, and **not** where new schema work is authored.
- **Adding a new trading user** (`users_NNNN`) should use an explicit **provision** path: repeat the tenant table DDL (migrations or a dedicated `provision_user_schema` script), grant RLS/session GUC expectations, and register the user in `system.master_users`. Forward migrations should state whether they apply **once per tenant** or **globally**.

## Migration forward rule

- **Platform DDL** (extensions, `system.*`, `live_data.*`): one migration, run once.
- **Tenant-shaped DDL** (`users_NNNN.*`): document in the migration header whether operators must **re-apply per user** (loop `users_0001`, `users_0002`, …) or whether a single rename/template migration covers all existing tenants. New tenants created after the migration still need that DDL applied during provisioning.

## Related

- Full process/service inventory: [TENANT_TOUCH_REGISTRY.md](TENANT_TOUCH_REGISTRY.md)
- Redis fan-out for Kalshi lifecycle: [TRADING_REDIS_COMMS.md](TRADING_REDIS_COMMS.md)
