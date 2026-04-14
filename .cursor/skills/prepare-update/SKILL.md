# Prepare update (pre-push)

Run when the user is ready to push a commit to the git repository. Orchestrates verification, server-agnostic audit, **plan → changelog handoff**, and reports when the update is ready for publishing with a suggested commit message.

## Workflow (execute in order)

1. **Prod snapshot (revertable backup)** — **BLOCKING.** Run this step first using the project-owned script. From the project root, run:
   - **Production host IPv4** (SSH/Postgres): see `docs/PRODUCTION_HOST.md` (currently **`165.22.13.146`**).
   - `./scripts/do/snapshot_prod.sh rec-io-prod-pre-update-YYYY-MM-DD` (today’s date)
   This script uses `DIGITALOCEAN_API_TOKEN` from `.env` (or the environment) and `doctl` to snapshot droplet **562337636** (current prod **165.22.13.146**; override with `DO_PROD_DROPLET_ID` if needed). If the script exits non‑zero (missing token, doctl not installed, API failure, etc.): **STOP the entire workflow.** Do not run steps 2–7. Output a clear explanation of why the snapshot failed and what needs to be fixed (e.g. set `DIGITALOCEAN_API_TOKEN` in `.env`, install/configure doctl), then wait for the user to address it and rerun `/prepare-update`. Only after the script reports that the snapshot action was submitted should you proceed to step 2.

   - **Optional MCP snapshot (best‑effort):** If the DigitalOcean droplets MCP is available, you **may** also call the **snapshot-droplet** tool (server **project-0-3_0-digitalocean-droplets**, falling back to **digitalocean-droplets** if present) with droplet ID **562337636** and name **rec-io-prod-pre-update-YYYY-MM-DD**. Treat this as non‑blocking: if the MCP call fails (e.g. "MCP server does not exist", HTTP 5xx), mention it briefly but **do not** stop the workflow as long as the script-based snapshot succeeded. See `docs/DEPLOYMENT_GUIDE.md` if you need to diagnose recurring MCP issues.

2. **Verify system**
   - Run the same checks as verify-local: health endpoints (main_app :3000, trade_executor :8001), supervisorctl status, tail recent logs for trade_executor, kalshi_account_sync, main_app, one `market_watchdog_ws` program log. Only treat log errors as current if timestamp is after process start. Conclude with status: All good / Investigate / Critical. If not All good, list issues and continue; include them in the final report.

3. **Server-agnostic audit**
   - Run `git status` and `git diff` (and `git diff --staged` if applicable). For changed files, search for: hardcoded `localhost` or `127.0.0.1` (allow in tests or commented config), absolute paths (e.g. `/Users/`, `C:\`), env vars that might differ by environment and are not documented in docs or .env.example. Flag each finding with file and line or snippet; do not block the workflow.

4. **Resolve release version (`system.version_control`)** — Do this **before** writing the changelog entry and commit message so the same version appears in git, `MASTER_CHANGELOG.md`, and the prod `record_system_version.py` step.
   - **Explicit override:** If the user stated a target version for this push in the **current chat** (e.g. “release as **3.1.0**”), use that string as **NEXT** (normalize a leading `v` if present). Do not auto-bump.
   - **Otherwise (patch bump):** Determine **CURRENT** from the database, preferring **production** so the bump matches what prod is actually on:
     1. If `REC_PROD_SSH_HOST` is set, try (non-interactive SSH, reasonable timeout):  
        `ssh -o BatchMode=yes -o ConnectTimeout=10 root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && venv/bin/python3 scripts/ops/read_system_version.py'`  
        On success, use that output as **CURRENT** (note **source: prod** in the report).
     2. If SSH fails or returns nothing, from **project root** locally:  
        `venv/bin/python3 scripts/ops/read_system_version.py`  
        Use output as **CURRENT** (note **source: local**). If this fails (empty table, no DB), stop and treat as a **blocking** issue unless the user supplies an explicit release string for this push.
   - **NEXT:** If explicit → that value. Else compute patch bump:  
     `venv/bin/python3 scripts/ops/next_system_version.py --bump-from "$CURRENT"`  
     (equivalent to incrementing the last numeric segment, e.g. `3.0.1` → `3.0.2`).
   - **Report** CURRENT (and source), NEXT, and whether the bump was explicit or automatic.

5. **Plans → changelog and DB docs (@updater prepare update)**
   - Treat **`.cursor/plans/*.md`** as the canonical record of what work was done:
     - List plan files (exclude `README.md`), read their `**Status:**` lines, and identify plans with `Status: done` that correspond to the changes in this update.
     - For these completed plans, summarize the user‑visible and DB‑relevant behavior changes in plain language.
   - **You must always ensure that today’s work is represented by a fresh, open changelog entry:**
     - If there is no existing `docs/changelog/MASTER_CHANGELOG.md` entry for this batch of completed plans, **add a new entry at the top** with today’s date, a clear title, a Summary, and a **Production checklist where all new tasks start as `- [ ]` (unchecked)**.
     - **Release metadata (required):** In the **Summary**, include a line **`Release: vNEXT`** (use the **NEXT** value from step 4 exactly, e.g. `Release: v3.0.2`). In the **Production checklist**, add an unchecked item that records that same version on the server after deploy (after migrations/restart/verify as appropriate for this entry):  
       `- [ ] Record release in DB: PYTHONPATH=$(pwd) venv/bin/python scripts/ops/record_system_version.py --version NEXT`  
       (substitute **NEXT** with the same string as in `Release: vNEXT`, **without** the `v` prefix in the command argument, e.g. `--version 3.0.2`).
     - At a minimum, the checklist must include a “Confirm codebase changes (pull latest on production)” item, plus any DB schema / migration / restart / verification steps implied by the plans and code changes.
   - Follow the steps in `.cursor/rules/updater.mdc` "Command: prepare update":
     - Add/update a `docs/changelog/MASTER_CHANGELOG.md` entry (date, title, Summary, Production checklist) that **explicitly references the relevant plan files** (e.g. “Plans: `mtb-account-dashboard`, `account-history-strategy-filters`”) so future readers can trace work back to its plans.
     - Update related docs, and align `docs/MASTER_DB_SCHEMA_REFERENCE.md` and `backend/core/config/database.py` when DB changes occurred. Ensure any DB/schema changes mentioned in plans are fully captured in the schema ref **and** in the changelog checklist (same standard as @db alignment).

6. **Flag other issues**
   - Note: missing migrations, untracked files that might need committing, TODOs in changed code, or anything that should be reviewed before push.

7. **Commit message and readiness**
   - **From staged changes (and associated plans):** Run `git diff --cached --name-status` and identify every substantive change. Use the associated plan titles (from `.cursor/plans/*.md`) and the new changelog entry to shape the message: short title + bullet list (like Generate Commit Message); 3–7 bullets, each naming one change area in plain language; mention every substantive change; no file counts; concise.
   - **The commit title line must include the release tag** matching step 4, e.g. `Release v3.0.2 — Short description` or `v3.0.2 — Short description` (same **NEXT** as `Release: vNEXT` in the changelog). The body may repeat `Release vNEXT` as the first bullet if helpful.
   - The final suggested commit message **must be emitted as a single, copy-pastable block** in the chat (one asset the user can grab and use directly).
   - If no blocking issues: output that single commit-message block clearly.
   - If there are blocking issues: list them and do not output "ready for publishing"; suggest what to fix.

References: .cursor/commands/prepare-update.md, .cursor/rules/updater.mdc, .cursor/commands/verify-local.md, .cursor/commands/verify-local.md, service ports in `backend/supervisord.conf`.