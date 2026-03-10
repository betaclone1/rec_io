# PM memory — Index

Persistent context for the Project Manager agent. **First and foremost for the PM's use.** Read these on session start or when reasoning about the project. Be as technical and detailed as necessary; human readability is not required. Do not modify existing project files; only this folder is PM writable.

## Persistent memory across chats

Cursor does not retain chat context between sessions. **The memory (the docs in .cursor/pm/brain/) is the PM’s persistent context.** Write things down liberally—decisions, outcomes, task lists, open questions, blockers, handoff notes, key facts from conversation—so we do not lose context between chats. **Storage is cheap.** Prefer writing too much over losing context. If we ever run into storage limits we can deal with it; for now, document what’s needed for continuity. See 14_context_retention for what to record and where; use 14 as catch‑all for recent context / handoff when it doesn’t fit elsewhere.

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
| 13_proposed_tasks | PM-proposed starting tasks / next steps (record here when proposed; CEO/future sessions recall from here) |
| 14_context_retention | Why and what to write down; catch‑all for recent context / handoff so next session has continuity |
| 15_chat_summary_log | Dated, timestamped chat summaries (from /log-chat); chronological record of sessions |
| 16_LOGGING_AUDIT_INITIATIVE | Logging audit: script-stack inventory, per-script cleanup, log rotation fix, future consolidated MASTER log; scope, current state, phased plan |
| 17_MONITOR_CONFIRMED_WATCH | Daily-briefing check: PM runs monitor_confirmed script; only report to user when there are failures (last 7d); major indicator of ATS/trading health |
| (PM doc) PROD_MAINTENANCE_FROM_LOCAL | Future/optional: prod maintenance from local via SSH; verify-production and daily-briefing already use SSH; apply-update currently runs with agent on prod (no git sync from local) |
| REDIS_PLATFORM_INITIATIVE | Draft plan: full-scale Redis (pub/sub, optional cache) to replace HTTP broadcast mesh and slim main; scope, phases, risks, agent implications |

## Usage

- **On load / new chat:** Read 00, 01, 02, 06, 14, and **15_chat_summary_log** for quick orientation. Review **all** memory docs including the chat summary log to refresh context at the start of a new chat. Use this memory: write down decisions, outcomes, task lists, open questions, handoff notes (14 for catch‑all; 13 for proposed tasks). **06 includes:** Autonomy (mandatory); **When you don't know:** research first, never guess—say "I couldn't find an answer" if still unknown.
- **DB work:** 03, 04 (connection: load .env + REC_DB_*→DB_*, then backend.core.config.database).
- **Changelog/deploy:** 05, 02 (updater agent, MASTER_CHANGELOG).
- **Google API integrations (Drive, Docs, Sheets, Gmail, Calendar):** .cursor/pm/GOOGLE_DRIVE_MCP_SETUP.md, scripts/gdrive/README.md. **MCP:** gdrive — read (search, gdrive:///); **google-workspace** (@presto-ai/google-workspace-mcp) — Gmail (search, read, send, drafts), Calendar (list/create/update/delete events); one-time OAuth on first use, tokens in ~/.config/google-workspace-mcp/. **Scripts:** create-doc.js (Docs, .txt; create/delete/auth), create-account-history-sheet.js (account_history→Sheet), export_account_history.py (DB→CSV). REC_IO / Cursor. **When user says "write a doc":** create-doc.js without --text-file. **Daily-briefing reviewed log:** .cursor/pm/daily_briefing_reviewed_drive.json.
- **OpSec:** .cursor/pm/OPSEC_AUDIT_AND_UPGRADE.md — current state, security upgrade process, optional @opsec agent.
- **Deep dive:** All; 07 for what was audited and when. **Code behavior:** 08 (trade flow, expiration, simulated path, executor callback, spawn, main routes/DB, ATS, core). **Exhaustive run:** 09 (scope, util/api DB patterns, Eric test). **Broker, data, infra:** 11 (Kalshi, Coinbase, DO, prediction markets, payments; subscribe to Kalshi changelog RSS). **Cursor IDE / UI:** 12 (separate window, shortcuts, modes, rules, indexing, MCP).

## Invariants

- No edits to repo files outside `.cursor/pm/brain/`.
- No DB/schema/table changes; read-only access for audit.
- **Memory docs are for the PM's use first.** Be as technical and detailed as necessary. Human readability is not required; optimize for agent comprehension and continuity.
- **Retain context:** Write down what’s needed so the next chat has continuity. Storage is cheap; write liberally.
