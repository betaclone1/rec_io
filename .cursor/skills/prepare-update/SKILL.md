# Prepare update (pre-push)

Run when the user is ready to push a commit to the git repository. Orchestrates verification, server-agnostic audit, changelog/DB alignment, and reports when the update is ready for publishing with a suggested commit message.

## Workflow (execute in order)

1. **Prod snapshot (revertable backup)** — **BLOCKING.** Run this step first using the project-owned script. From the project root, run:
   - `./scripts/do/snapshot_prod.sh rec-io-prod-pre-update-YYYY-MM-DD` (today’s date)
   This script uses `DIGITALOCEAN_API_TOKEN` from `.env` (or the environment) and `doctl` to snapshot droplet **513735057** (or `DO_PROD_DROPLET_ID` if set). If the script exits non‑zero (missing token, doctl not installed, API failure, etc.): **STOP the entire workflow.** Do not run steps 2–6. Output a clear explanation of why the snapshot failed and what needs to be fixed (e.g. set `DIGITALOCEAN_API_TOKEN` in `.env`, install/configure doctl), then wait for the user to address it and rerun `/prepare-update`. Only after the script reports that the snapshot action was submitted should you proceed to step 2.

   - **Optional MCP snapshot (best‑effort):** If the DigitalOcean droplets MCP is available, you **may** also call the **snapshot-droplet** tool (server **project-0-3_0-digitalocean-droplets**, falling back to **digitalocean-droplets** if present) with droplet ID **513735057** and name **rec-io-prod-pre-update-YYYY-MM-DD**. Treat this as non‑blocking: if the MCP call fails (e.g. "MCP server does not exist", HTTP 5xx), mention it briefly but **do not** stop the workflow as long as the script-based snapshot succeeded. See `.cursor/pm/MCP_DIGITALOCEAN_TROUBLESHOOTING.md` if you need to diagnose recurring MCP issues.

2. **Verify system**
   - Run the same checks as verify-local: health endpoints (main_app :3000, trade_executor :8001), supervisorctl status, tail recent logs for trade_executor, kalshi_account_sync, main_app, one kalshi_market_watchdog. Only treat log errors as current if timestamp is after process start. Conclude with status: All good / Investigate / Critical. If not All good, list issues and continue; include them in the final report.

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

References: .cursor/pm/PREPARE_UPDATE_COMMAND.md, .cursor/rules/updater.mdc, .cursor/commands/verify-local.md, .cursor/pm/VERIFY_COMMAND.md, .cursor/pm/brain/02_services_ports.md.