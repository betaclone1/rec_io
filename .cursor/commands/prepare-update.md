---
description: "Before pushing: verify system, audit server-agnostic, update changelog/DB docs, then suggest commit message and report when ready for publishing."
---

# Prepare update (pre-push)

Run when you are ready to push a commit to the git repository. This command ensures scripts are healthy, changes are server-agnostic, changelog and DB docs are updated, and then reports whether the update is ready for publishing (with a suggested commit message).

**Execute the full workflow** (do not just describe it):

1. **Prod snapshot (revertable backup)** — **BLOCKING. Do not run any later step until this succeeds.** Create a snapshot of the production droplet: call the **snapshot-droplet** MCP tool (server **project-0-3_0-digitalocean-droplets**; if that fails, try **digitalocean-droplets**) with droplet ID **513735057** and name **rec-io-prod-pre-update-YYYY-MM-DD** (today’s date). If the MCP is not available (e.g. "MCP server does not exist") or the call fails: **STOP.** Output a clear block: "Prepare-update stopped: prod snapshot required. The digitalocean-droplets MCP is not available in this session. Ensure this workspace is the project root (File → Open Folder → the folder that contains .cursor/mcp.json, e.g. 3_0). Then run /prepare-update again." See .cursor/pm/MCP_DIGITALOCEAN_TROUBLESHOOTING.md. Do not run steps 2–6. Only after the snapshot is created (MCP call succeeded) proceed to step 2.
2. **Verify system** — Run the same checks as /verify: health (main_app :3000, trade_executor :8001), supervisor status, recent logs for key services. Only treat log errors as current if they occurred after process start. If status is not "All good", list the issues and continue; note them in the final report so CEO can decide whether to fix before pushing.
3. **Server-agnostic audit** — Scan changed/staged files for: hardcoded localhost or 127.0.0.1 (except in tests or config comments), absolute paths that would break on other servers, env vars that might differ by environment without being documented. Flag any findings; do not block.
4. **Changelog and DB docs** — Perform the steps in **@updater prepare update**: review git status/diff, add or update MASTER_CHANGELOG.md entry (date, summary, production checklist), update related docs, align docs/MASTER_DB_SCHEMA_REFERENCE.md and backend/core/config/database.py. Ensure all DB changes are reflected in the schema ref and changelog (invoke or mirror @db alignment).
5. **Flag other issues** — Note any other potential issues (e.g. missing migrations, untracked files that should be committed, TODO in changed code) for CEO review.
6. **Commit message and readiness** — If the above is complete and there are no blocking issues: **derive the commit message from staged changes so it mentions every substantive change.**

   - **Review staged changes:** Run `git diff --cached --name-status` (and optionally `--name-only`) and identify every distinct change: each area moved or reorganized, each new feature or doc or script group, each archive, config change, etc. Do not include file counts or numbers.
   - **Commit message:** Short bullet list (like Cursor’s Generate Commit Message). One line title, then 3–7 bullets; each bullet names one change area in plain language (e.g. “Moved PM brain to .cursor”, “Archived corrupted manifests and legacy docs to archive/2026-03-housekeeping”, “Reorganized scripts into backup/, install_deploy/, manage/”). Mention every substantive change; concise; no novel.
   - Then output a clear **Update ready for publishing** block with the message. If there are blocking issues, list them and do not output "ready for publishing".

See .cursor/pm/PREPARE_UPDATE_COMMAND.md for full workflow. Updater: .cursor/rules/updater.mdc. Verify: .cursor/commands/verify.md.