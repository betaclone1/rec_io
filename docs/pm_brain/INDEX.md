# PM Brain — Index

Persistent context for the Project Manager agent. Read these on session start or when reasoning about the project. Do not modify existing project files; only this folder is PM writable.

## Doc map

| File | Purpose |
|------|--------|
| 00_project_overview | Company, product, repo layout, key paths, one-liner |
| 01_codebase_map | Backend layout, entry points, core/api/util, main services |
| 02_services_ports | Port manifest, MASTER_RESTART, supervisor, service list |
| 03_db_schema_brain | Schemas/tables list, critical tables, init_database, connection |
| 04_config_env | Env vars (DB_*, REC_*), .env loading, config_manager, unified_config |
| 05_docs_changelog | Docs layout, changelog workflow, agent instructions, TODO |
| 06_conventions_insights | Naming, patterns, what not to touch, subagents |
| 07_audit_log | Timestamped audit summary, findings (read-only audit) |
| 08_code_audit | Code-level flows and invariants (trade_manager, AES, executor, monitor_manager, database, main, ATS, core) |
| 09_audit_exhaustive | Exhaustive audit scope, util/api DB patterns, findings summary, Eric test |
| 10_audit_per_file | Per-file audit manifest: every active source file listed and reviewed |
| 11_external_ecosystem | Kalshi (broker, API, docs, changelog, fixed-point), prediction markets, Coinbase API/WS, DO, payments, future agents |
| 12_cursor_ide | Cursor IDE: UI, Chat/Composer separate window, shortcuts, modes, rules, @ refs, indexing, .cursorignore, MCP, settings |

## Usage

- **On load:** Read 00, 01, 02, 06 for quick orientation. **06 includes:** Autonomy (mandatory); **When you don't know:** research first, never guess—say "I couldn't find an answer" if still unknown.
- **DB work:** 03, 04 (connection: load .env + REC_DB_*→DB_*, then backend.core.config.database).
- **Changelog/deploy:** 05, 02 (updater agent, MASTER_CHANGELOG).
- **Deep dive:** All; 07 for what was audited and when. **Code behavior:** 08 (trade flow, expiration, simulated path, executor callback, spawn, main routes/DB, ATS, core). **Exhaustive run:** 09 (scope, util/api DB patterns, Eric test). **Broker, data, infra:** 11 (Kalshi, Coinbase, DO, prediction markets, payments; subscribe to Kalshi changelog RSS). **Cursor IDE / UI:** 12 (separate window, shortcuts, modes, rules, indexing, MCP).

## Invariants

- No edits to repo files outside `docs/pm_brain/`.
- No DB/schema/table changes; read-only access for audit.
- Brain is detailed for PM comprehension; human readability optional.
