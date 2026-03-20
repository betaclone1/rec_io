# DB scripts

Schema, migrations, drift check, backfills, and audit. Migration SQL files live in sibling `../migrations/`.

- **run_migration.py** — Reversible migration runner: `list` | `up [id]` | `down <id>`. See `scripts/migrations/README.md`.
- **check_db_schema_drift.py** — CI drift check: database.py vs MASTER_DB_SCHEMA_REFERENCE.md (critical tables). Exit 1 if drift.
- **update_db_schema_to_reference.py** — Add missing columns from reference; no type changes.
- **audit_db_schema.py** — Full audit: local DB vs reference vs database.py.
- **generate_schema_doc.py** — Regenerate docs/MASTER_DB_SCHEMA_REFERENCE.md from DB.
- **backfill_account_history_vendor_rail.py** — One-off backfill for account_history (kalshi_id, vendor, rail).
- **backfill_trades_volatility_movement.py** — Backfill trades from historical price logs. See PRODUCTION_DB_SCHEMA_AND_BACKFILL_MASTER.md.
- **compare_simulated_table_schema.py** — Compare trades_simulated schema (e.g. local vs prod).

Run from project root with PYTHONPATH set when needed, e.g. `python3 scripts/db/run_migration.py list`.
