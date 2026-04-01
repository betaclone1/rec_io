# Prepare update (pre-push)

Run when the user is ready to push a commit to the git repository. Orchestrates verification, server-agnostic audit, **plan → changelog handoff**, and reports when the update is ready for publishing with a suggested commit message.

## Workflow (execute in order)

1. **Prod snapshot (revertable backup)** — **BLOCKING.** Run this step first using the project-owned script. From the project root, run:
   - **Production host IPv4** (SSH/Postgres): see `docs/PRODUCTION_HOST.md` (currently **`165.22.13.146`**).
   - `./scripts/do/snapshot_prod.sh rec-io-prod-pre-update-YYYY-MM-DD` (today’s date)
   This script uses `DIGITALOCEAN_API_TOKEN` from `.env` (or the environment) and `doctl` to snapshot droplet **513735057** (or `DO_PROD_DROPLET_ID` if set). If the script exits non‑zero (missing token, doctl not installed, API failure, etc.): **STOP the entire workflow.** Do not run steps 2–6. Output a clear explanation of why the snapshot failed and what needs to be fixed (e.g. set `DIGITALOCEAN_API_TOKEN` in `.env`, install/configure doctl), then wait for the user to address it and rerun `/prepare-update`. Only after the script reports that the snapshot action was submitted should you proceed to step 2.

   - **Optional MCP snapshot (best‑effort):** If the DigitalOcean droplets MCP is available, you **may** also call the **snapshot-droplet** tool (server **project-0-3_0-digitalocean-droplets**, falling back to **digitalocean-droplets** if present) with droplet ID **513735057** and name **rec-io-prod-pre-update-YYYY-MM-DD**. Treat this as non‑blocking: if the MCP call fails (e.g. "MCP server does not exist", HTTP 5xx), mention it briefly but **do not** stop the workflow as long as the script-based snapshot succeeded. See `docs/DEPLOYMENT_GUIDE.md` if you need to diagnose recurring MCP issues.

2. **Verify system**
   - Run the same checks as verify-local: health endpoints (main_app :3000, trade_executor :8001), supervisorctl status, tail recent logs for trade_executor, kalshi_account_sync, main_app, one `market_watchdog_ws` program log. Only treat log errors as current if timestamp is after process start. Conclude with status: All good / Investigate / Critical. If not All good, list issues and continue; include them in the final report.

3. **Server-agnostic audit**
   - Run `git status` and `git diff` (and `git diff --staged` if applicable). For changed files, search for: hardcoded `localhost` or `127.0.0.1` (allow in tests or commented config), absolute paths (e.g. `/Users/`, `C:\`), env vars that might differ by environment and are not documented in docs or .env.example. Flag each finding with file and line or snippet; do not block the workflow.

4. **Plans → changelog and DB docs (@updater prepare update)**
   - Treat **`.cursor/plans/*.md`** as the canonical record of what work was done:
     - List plan files (exclude `README.md`), read their `**Status:**` lines, and identify plans with `Status: done` that correspond to the changes in this update.
     - For these completed plans, summarize the user‑visible and DB‑relevant behavior changes in plain language.
   - **You must always ensure that today’s work is represented by a fresh, open changelog entry:**
     - If there is no existing `docs/changelog/MASTER_CHANGELOG.md` entry for this batch of completed plans, **add a new entry at the top** with today’s date, a clear title, a Summary, and a **Production checklist where all new tasks start as `- [ ]` (unchecked)**.
     - At a minimum, the checklist must include a “Confirm codebase changes (pull latest on production)” item, plus any DB schema / migration / restart / verification steps implied by the plans and code changes.
   - Follow the steps in `.cursor/rules/updater.mdc` "Command: prepare update":
     - Add/update a `docs/changelog/MASTER_CHANGELOG.md` entry (date, title, Summary, Production checklist) that **explicitly references the relevant plan files** (e.g. “Plans: `mtb-account-dashboard`, `account-history-strategy-filters`”) so future readers can trace work back to its plans.
     - Update related docs, and align `docs/MASTER_DB_SCHEMA_REFERENCE.md` and `backend/core/config/database.py` when DB changes occurred. Ensure any DB/schema changes mentioned in plans are fully captured in the schema ref **and** in the changelog checklist (same standard as @db alignment).

5. **Flag other issues**
   - Note: missing migrations, untracked files that might need committing, TODOs in changed code, or anything that should be reviewed before push.

6. **Commit message and readiness**
   - **From staged changes (and associated plans):** Run `git diff --cached --name-status` and identify every substantive change. Use the associated plan titles (from `.cursor/plans/*.md`) and the new changelog entry to shape the message: short title + bullet list (like Generate Commit Message); 3–7 bullets, each naming one change area in plain language; mention every substantive change; no file counts; concise.
   - The final suggested commit message **must be emitted as a single, copy-pastable block** in the chat (one asset the user can grab and use directly).
   - If no blocking issues: output that single commit-message block clearly.
   - If there are blocking issues: list them and do not output "ready for publishing"; suggest what to fix.

References: .cursor/commands/prepare-update.md, .cursor/rules/updater.mdc, .cursor/commands/verify-local.md, .cursor/commands/verify-local.md, service ports in `backend/supervisord.conf`.