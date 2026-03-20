# Reversible migrations

Migration pairs live here: `YYYYMMDD_HHMM_short_slug.up.sql` and `.down.sql`.

- **Apply:** `python3 scripts/db/run_migration.py up [migration_id]` or `up` for all pending.
- **Revert:** `python3 scripts/db/run_migration.py down <migration_id>`.
- **List applied:** `python3 scripts/db/run_migration.py list`.

See **scripts/migrations/README.md** for the full convention and PG expert agent rules.
