# Prepare update (pre-push)

Run when the user is ready to push a commit to the git repository. Orchestrates verification, server-agnostic audit, changelog/DB alignment, and reports when the update is ready for publishing with a suggested commit message.

## Workflow (execute in order)

1. **Prod snapshot (revertable backup)** — **BLOCKING.** Run this step first. Call the **snapshot-droplet** MCP tool (server **project-0-3_0-digitalocean-droplets**; if that fails, try **digitalocean-droplets**) with droplet ID **513735057**, name **rec-io-prod-pre-update-YYYY-MM-DD** (today’s date). If the MCP is not available ("MCP server does not exist") or the snapshot call fails: **STOP the entire workflow.** Do not run steps 2–6. Output: "Prepare-update stopped: prod snapshot required. The digitalocean-droplets MCP is not available in this session. Ensure this workspace is the project root (File → Open Folder → the folder that contains .cursor/mcp.json). Then run /prepare-update again." See .cursor/pm/MCP_DIGITALOCEAN_TROUBLESHOOTING.md. Only after the snapshot is created, proceed to step 2.

2. **Verify system**
   - Run the same checks as the verify command: health endpoints (main_app :3000, trade_executor :8001), supervisorctl status, tail recent logs for trade_executor, kalshi_account_sync, main_app, one kalshi_market_watchdog. Only treat log errors as current if timestamp is after process start. Conclude with status: All good / Investigate / Critical. If not All good, list issues and continue; include them in the final report.

3. **Server-agnostic audit**
   - Run `git status` and `git diff` (and `git diff --staged` if applicable). For changed files, search for: hardcoded `localhost` or `127.0.0.1` (allow in tests or commented config), absolute paths (e.g. `/Users/`, `C:\`), env vars that might differ by environment and are not documented in docs or .env.example. Flag each finding with file and line or snippet; do not block the workflow.

4. **Changelog and DB docs (@updater prepare update)**
   - Follow the steps in .cursor/rules/updater.mdc "Command: prepare update": review changes, add/update MASTER_CHANGELOG.md entry (date, summary, production checklist), update related docs, align docs/MASTER_DB_SCHEMA_REFERENCE.md and backend/core/config/database.py. Ensure DB changes are in schema ref and changelog (same as @db alignment).

5. **Flag other issues**
   - Note: missing migrations, untracked files that might need committing, TODOs in changed code, or anything that should be reviewed before push.

6. **Commit message and readiness**
   - **From staged changes:** Run `git diff --cached --name-status` and identify every substantive change. Commit message: short title + bullet list (like Generate Commit Message); 3–7 bullets, each naming one change area in plain language; mention every substantive change; no file counts; concise.
   - If no blocking issues: output a clear block with the derived commit message.
   - If there are blocking issues: list them and do not output "ready for publishing"; suggest what to fix.

References: .cursor/pm/PREPARE_UPDATE_COMMAND.md, .cursor/rules/updater.mdc, .cursor/commands/verify.md, .cursor/pm/brain/02_services_ports.md.