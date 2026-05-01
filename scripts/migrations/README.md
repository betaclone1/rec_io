# Reversible migrations

**Source of truth for schema evolution:** new tables, columns, indexes, and type changes are applied **only** through migration pairs here plus `scripts/db/run_migration.py`. Do not add parallel `ALTER` / `ADD COLUMN` paths in `init_database()` for production-shaped objects; see `docs/TENANT_INIT_AND_MIGRATIONS.md` and `AGENTS.md` (DB section).

Pairs: `YYYYMMDD_HHMM_short_slug.up.sql` and `YYYYMMDD_HHMM_short_slug.down.sql` in this directory.

## Commands

- **Apply one:** `python3 scripts/db/run_migration.py up <migration_id>`
- **Apply all pending:** `python3 scripts/db/run_migration.py up`
- **Revert one:** `python3 scripts/db/run_migration.py down <migration_id>`
- **List applied (DB):** `python3 scripts/db/run_migration.py list`

Applied migrations are recorded in `system.schema_migrations`.

## Hygiene (project standard)

Goal: avoid dozens of one-off pairs for a single feature.

1. **One logical change → one migration id.** Put related DDL in the same `.up.sql` / `.down.sql` when it ships together.
2. **Look first:** search this folder for the same table or feature before adding a new timestamped id.
3. **Superseded drafts:** if you never ran `up` on any shared database, delete the old pair in the same PR as the replacement.
4. **Applied migrations:** do not delete files for ids already in `system.schema_migrations` on production unless the owner explicitly accepts breaking `down` and you have a documented plan.

Agents: `.cursor/rules/05-db-migration-hygiene.mdc` and `AGENTS.md` (DB section).
