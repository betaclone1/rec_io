---
description: "Before pushing: verify system, audit server-agnostic, update changelog/DB docs, then suggest commit message and report when ready for publishing."
---

# Prepare update (pre-push)

Run when you are ready to push a commit to the git repository. This command ensures scripts are healthy, changes are server-agnostic, changelog and DB docs are updated, and then reports whether the update is ready for publishing (with a suggested commit message).

**Execute the full workflow** (do not just describe it):

1. **Prod snapshot (revertable backup)** — **BLOCKING. Do not run any later step until this succeeds.** From the project root, run the script `./scripts/do/snapshot_prod.sh rec-io-prod-pre-update-YYYY-MM-DD` (today’s date). This uses `DIGITALOCEAN_API_TOKEN` from `.env` and `doctl` to create the snapshot for droplet **562337636** (current prod **165.22.13.146**; or `DO_PROD_DROPLET_ID` if set). If the script exits non‑zero (e.g. missing token, doctl not installed, other failure): **STOP.** Output a clear block explaining the snapshot failure and what needs to be fixed (e.g. set `DIGITALOCEAN_API_TOKEN` in `.env`, install/configure `doctl`), and do not run steps 2–7. Only after the script reports that the snapshot action was submitted should you proceed to step 2.

   - **Optional MCP snapshot (best‑effort):** If the DigitalOcean droplets MCP is available, you may also call the **snapshot-droplet** tool (server **project-0-3_0-digitalocean-droplets**, falling back to **digitalocean-droplets** if present) with droplet ID **562337636** and name **rec-io-prod-pre-update-YYYY-MM-DD**. Treat this as non‑blocking: if the MCP call fails (e.g. "MCP server does not exist", HTTP 5xx), log/mention it briefly but **do not** stop the workflow as long as the script-based snapshot succeeded. See `docs/DEPLOYMENT_GUIDE.md` if you need to diagnose recurring MCP issues.
2. **Verify system** — Run the same checks as verify-local: health (main_app :3000, trade_executor :8001), supervisor status, recent logs for key services. Only treat log errors as current if they occurred after process start. If status is not "All good", list the issues and continue; note them in the final report so CEO can decide whether to fix before pushing.
3. **Server-agnostic audit** — Scan changed/staged files for: hardcoded localhost or 127.0.0.1 (except in tests or config comments), absolute paths that would break on other servers, env vars that might differ by environment without being documented. Flag any findings; do not block.
4. **Resolve release version** — Follow step 4 in `.cursor/skills/prepare-update/SKILL.md`: determine **NEXT** from `system.version_control` (prefer reading **CURRENT** from prod via SSH, else local DB), or use an explicit version if the user asked for one in this chat. You will use **NEXT** in the changelog, commit title, and the prod `record_system_version.py --version` checklist line.
5. **Changelog and DB docs** — Perform the steps in **@updater prepare update**: review git status/diff, add or update MASTER_CHANGELOG.md entry (date, summary, production checklist) including **`Release: vNEXT`** and a checklist row **`record_system_version.py --version NEXT`**, update related docs, align docs/MASTER_DB_SCHEMA_REFERENCE.md and backend/core/config/database.py. Ensure all DB changes are reflected in the schema ref and changelog (invoke or mirror @db alignment).
6. **Flag other issues** — Note any other potential issues (e.g. missing migrations, untracked files that should be committed, TODO in changed code) for CEO review.
7. **Commit message and readiness** — If the above is complete and there are no blocking issues: **derive the commit message from staged changes so it mentions every substantive change.**

   - **Review staged changes:** Run `git diff --cached --name-status` (and optionally `--name-only`) and identify every distinct change: each area moved or reorganized, each new feature or doc or script group, each archive, config change, etc. Do not include file counts or numbers.
   - **Commit message:** Short bullet list (like Cursor’s Generate Commit Message). **Title must include the same release as the changelog** (e.g. `Release v3.0.2 — …`). Then 3–7 bullets; each bullet names one change area in plain language. Mention every substantive change; concise; no novel.
   - Then output a clear **Update ready for publishing** block with the message. If there are blocking issues, list them and do not output "ready for publishing".

See .cursor/commands/prepare-update.md for full workflow. Updater: .cursor/rules/updater.mdc. Verify: .cursor/commands/verify-local.md and .cursor/commands/verify-local.md.