# Reversible DB migrations

PostgreSQL schema and data changes are critical infrastructure and harder to revert than code. This doc defines how we make DB changes **reversible** so the PG expert agent (and humans) can apply and revert them in a predictable way.

## Principle

- **Every schema-changing or data-changing operation** is a **migration** with an **up** (apply) and a **down** (revert).
- Migrations are **versioned files** in the repo. Applied migrations are **tracked** in the DB so we can list them and revert by name.
- The **PG expert agent** (and anyone changing the DB) **must** create up+down migration files and use the migration runner. No ad hoc DDL without a corresponding down migration.

## Layout

- **Migrations directory:** `scripts/migrations/`
- **Naming:** `YYYYMMDD_HHMM_short_slug.up.sql` and `YYYYMMDD_HHMM_short_slug.down.sql`
  - Example: `20260307_1200_add_foo_column.up.sql` / `20260307_1200_add_foo_column.down.sql`
  - The **migration id** used in the runner is the basename without `.up`/`.down`: `20260307_1200_add_foo_column`
- **Tracking table:** `system.schema_migrations` (created by the runner if missing)
  - Columns: `migration_id TEXT PRIMARY KEY`, `applied_at TIMESTAMPTZ DEFAULT now()`

## Runner

**Script:** `scripts/db/run_migration.py`

Uses project DB config: `backend.core.config.database.get_postgresql_connection()` (respects DB_* / REC_DB_* env).

**Commands:**

- **List applied:** `python3 scripts/db/run_migration.py list` — prints applied migration ids (newest last).
- **Apply one:** `python3 scripts/db/run_migration.py up <migration_id>` — runs `<id>.up.sql`, then inserts into `system.schema_migrations`. Fails if already applied.
- **Revert one:** `python3 scripts/db/run_migration.py down <migration_id>` — runs `<id>.down.sql`, then deletes from `system.schema_migrations`. Fails if not applied.
- **Apply all pending:** `python3 scripts/db/run_migration.py up` (no id) — applies all migrations in `scripts/migrations/` that are not yet in `system.schema_migrations`, in lexicographic order by migration_id.

**Safety:**

- Each up/down runs in a single transaction (commit only after successful run + tracking update).
- Revert is **last-applied first** when doing bulk down is needed (future): today we only support revert-by-id.

## PG expert agent

When the PG expert agent introduces or changes schema or destructive data logic:

1. **Create a migration pair** in `scripts/migrations/`: `<timestamp>_<slug>.up.sql` and `.down.sql`.
2. **Up script:** idempotent where possible (e.g. `ADD COLUMN IF NOT EXISTS`); otherwise document that re-apply after revert may require manual cleanup.
3. **Down script:** must restore prior state (e.g. `DROP COLUMN IF EXISTS`, or restore a column type). If full revert is impossible (e.g. data loss), document in the migration and in the down file as a comment; still provide a best-effort down (e.g. drop new column).
4. **Apply** via `run_migration.py up <id>`; **revert** via `run_migration.py down <id>`.
5. **Do not** run raw DDL in one-off scripts or in `database.py` for one-off changes without a migration; put those changes into migrations and run through the runner so they are revertible.

## Relation to existing tools

- **`database.py` init_database():** Remains the source for **initial** schema (new env, new tables). Ongoing **changes** to existing tables (new columns, type changes, new indexes) should be migrations so they can be reverted.
- **`update_db_schema_to_reference.py`:** Adds missing columns from the reference doc; one-way. For **targeted** changes (e.g. add one column with a specific default), prefer a migration so we have a down. The audit (task 3) may later align this script with the migration workflow or keep it for bulk “sync to reference” only.
- **Reference doc:** `docs/MASTER_DB_SCHEMA_REFERENCE.md` stays the source of truth for current shape; after applying a migration, update the reference doc so it matches the new state.

## Head of DB operations: cross-server and docs

**Goal: DB changes as painless as possible across servers.** Any change to the DB (by any process) must be reflected in the same set of artifacts so every server can apply the same migrations and reference the same doc. The @db agent (head of DB operations) monitors all DB changes and ensures these are updated: reference doc, database.py, migrations in repo, .cursor/pm/brain/03_db_schema_brain.md, and changelog when appropriate. See `.cursor/rules/db.mdc` for the full list and mandate.

## Quick reference for revert

- See what’s applied: `python3 scripts/db/run_migration.py list`
- Revert last (or a specific) change: `python3 scripts/db/run_migration.py down <migration_id>`
- Same pattern as reverting a commit: identify the change, run the down migration, then fix code/docs as needed.
