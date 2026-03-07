# Docs and changelog

## Docs layout

- **docs/** — 224+ markdown files (at audit time) excluding pm_brain; deployment, installation, audits, VER3 onboarding, archive.
- **docs/changelog/** — MASTER_CHANGELOG.md (timestamped entries, production checklists), CHANGELOG_AGENT_INSTRUCTIONS.md, README.md (workflow), TODO.md (backlog).
- **docs/MASTER_DB_SCHEMA_REFERENCE.md** — Full schema/table/column reference; how to run init_database and optional historical ingest.
- **docs/pm_brain/** — PM persistent context (this folder).
- **docs/** — Other: INSTALLATION_*, SYSTEM_*, GIT_UPDATE_*, SIMULATED_15M_*, FIXED_POINT_*, POST_DEPLOYMENT_*, FRONTEND_*, COLLABORATOR_*, etc.
- **AGENTS.md** — Root; lists @pm and @updater, pointers to .cursor/rules.

## Changelog workflow

- **Add entry:** Before push, add new ## YYYY-MM-DD — Title in MASTER_CHANGELOG.md at top. Summary + Production agent checklist with - [ ] items (codebase, init_database, one-time scripts, restart, verification).
- **Run checklist:** @updater new update (or production agent): read CHANGELOG_AGENT_INSTRUCTIONS.md and MASTER_CHANGELOG.md; for each open entry (newest first), execute each unchecked task, then set - [ ] → - [x].
- **Python:** From project root, PYTHONPATH=$(pwd) venv/bin/python (never bare python3 for scripts).

## Updater agent

- **.cursor/rules/updater.mdc** — @updater prepare update (pre-push: review changes, update changelog, schema ref, database.py alignment); @updater new update (execute open checklists).
- **AGENTS.md** — Short summary of @pm and @updater.

## TODO.md

- docs/changelog/TODO.md — Backlog; check/update periodically; completed/old items can be archived to keep lean.
- **Notable open items (onboarding snapshot):** DB maintenance system audit (schema alignment, reference vs database.py vs prod); Kalshi account history → /deposits and /withdrawals (v1 account/history 404; switch sync to new endpoints); system-wide logging audit (reduce volume); auto_entry_supervisor consolidation (single process, multi-monitor loop). See TODO.md for full checklists.
