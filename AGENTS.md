# Agents

**Chat:** Use normal markdown (bold, headers, lists). Do not strip formatting.

**Context:** When you edit .cursor/pm/brain/, .cursor/rules/, .cursor/skills/, or .cursor/commands/, stage and amend the single unpushed `ctx:` commit. See .cursor/pm/brain/06_conventions_insights.md § Context files and commits.

**Org:** .cursor/pm/ORG_CHART.md

**Commands (see .cursor/pm/ for full doc):** /verify-local, /verify-production, /system-restart, /log-chat, /prepare-update, /apply-update, /apply-update-from-local, /confirm-update, /daily-briefing.

**DB changes (non-negotiable):** When the user asks to add or modify anything in the database (column, table, schema, etc.), do the full protocol. The **actual database must be modified** (run the migration). Do not only edit database.py or migration files. Steps: (1) Create migration up/down in scripts/migrations/ if not present, (2) **Run** `python3 scripts/db/run_migration.py up <migration_id>` so the live DB changes, (3) Update docs/MASTER_DB_SCHEMA_REFERENCE.md, (4) Update backend/core/config/database.py (CREATE TABLE / bootstrap) as needed, (5) Update .cursor/pm/brain/03_db_schema_brain.md as needed, (6) Run scripts/db/check_db_schema_drift.py. No DB change is done until the migration has been applied to the database.

---

## Roster

| Agent | Role | Rule |
|-------|------|------|
| @pm | Project Manager. Strategy, audits, agent/rules, coordination. First step: read INDEX then 15. Context sweep: see 06. | .cursor/rules/pm.mdc |
| @analyst | Analytics, backtests, strategy performance, data deep-dives. Memory: .cursor/pm/brain/analyst/. First step: INDEX, 15, INDEX_ANALYST. | .cursor/rules/analyst.mdc |
| @db | DB operations, schema, migrations, reference. | .cursor/rules/db.mdc |
| @frontend | Frontend, HTML/JS/CSS, mobile, UI/UX. | .cursor/rules/frontend.mdc |
| @updater | Changelog, prepare update, run checklists on prod. | .cursor/rules/updater.mdc |
| @kalshi | Kalshi API, WebSocket, broker. | .cursor/rules/kalshi.mdc |
| @digitalocean | DO API, snapshots, backups, droplets. | .cursor/rules/digitalocean.mdc |
| @assistant | Gmail, Calendar, personal productivity. No backend/DB/trading. | .cursor/rules/assistant.mdc |
