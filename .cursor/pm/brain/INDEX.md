# PM memory — Index

**On load:** Read 00, 02, 06, 14, 15_chat_summary_log. Then any other doc as needed for the task.

**Write things down.** Cursor doesn't retain chat. Memory is here. Use 14 as catch-all. Storage is cheap.

## Doc map

| Doc | Purpose |
|-----|---------|
| 00 | Project overview, repo layout, key paths |
| 02 | Services, ports, MASTER_RESTART, supervisor |
| 06 | Conventions (autonomy, context commits, project rules) — **single source; do not duplicate** |
| 14 | What to record; recent context / handoff |
| 15 | Chat summary log (/log-chat) |
| 03 | DB schemas, connection (when doing DB work) |
| 05 | Changelog, TODO (when doing deploy/changelog) |
| 11 | Kalshi, broker, API (when doing Kalshi work) |
| analyst/ | Analyst memory; INDEX_ANALYST + listed docs |

Other numbered docs (01, 04, 07–10, 12, 13, 16, 17): read when the task needs them. Command docs: .cursor/pm/ (VERIFY_COMMAND, APPLY_UPDATE_COMMAND, etc.).
