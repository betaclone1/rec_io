---
description: "Production (from local): run open MASTER_CHANGELOG checklists on prod via SSH. This is the primary way to apply updates."
---

# Apply update from local (production via SSH)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`** (SSH and Postgres co-located). Example: `export REC_PROD_SSH_HOST=165.22.13.146`; for local scripts hitting prod DB, `export REC_PROD_DB_HOST=165.22.13.146`. Canonical: `docs/PRODUCTION_HOST.md`.

**This is the primary way to apply updates to production.** Run it in your **local workspace**. The agent SSHs to prod and executes every production checklist step there (pull, migrations, restart, verify). No agent runs on the production server.

**Execute the full workflow** (do not just describe it).

**CRITICAL — DB: never confirm an update unless DB updates are 100% confirmed. We never ever skip this step.**

- **Pre-flight (mandatory, before any SSH or pull):** If an open changelog entry’s checklist includes **Apply migrations** (or running specific migration slugs), verify that **every** migration file referenced in that entry (e.g. `scripts/migrations/YYYYMMDD_HHMM_slug.up.sql` and `.down.sql`) exists in the commit you are deploying (e.g. `git show --name-only HEAD` or the branch prod will pull). If any required migration file is **not** in that commit: **do not attempt the update.** If migration files are not in the commit: verify schema on prod (e.g. information_schema); if already present, mark entry complete with a note; otherwise do not mark complete and do not report "All good." The update must not be run on any other server until migration files are in the commit and pushed; only then can we be 100% certain we can update the DB. Deploying code without applying required migrations can crash the system or corrupt data.
- **When pre-flight passes:** On the target server, run in this order: pull (so migration files are present) → apply all required migrations → then restart. Migrations must complete successfully before restart so the schema exists before the new code runs.
- **No update is ever confirmed** unless every DB-related checklist item is verified on the target server (run the step and verify, or query schema on prod). Do not mark DB items done or report "All good" if any DB step was skipped or left unverified.
- **If any DB task was required and was not successfully completed or verified:** VERIFY STATUS is **🔴 Critical**. Do not report "All good".

1. **Confirm code is pushed** — Ensure the local commit you want to deploy is pushed. The prod server will `git pull` from origin; this command does **not** push from local.

2. **Read agent instructions** — Open and follow `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` in full.

3. **Find open production entries** — In `docs/changelog/MASTER_CHANGELOG.md`, list every entry whose **Production checklist** has at least one unchecked box (`- [ ]`). Process entries **newest-first** (by date in the heading).

4. **Execute each open entry on prod via SSH** — For each open entry, in order:

   - Read the full entry (summary + every checklist item).
   - For each unchecked task, run the corresponding command **over SSH on the production server**:
     - Use `ssh root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && <command>'`.
     - Examples:
       - Code sync: `ssh root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && git fetch && git checkout main && git pull --ff-only origin main'`
       - DB migrations: `ssh root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && PYTHONPATH=. venv/bin/python scripts/db/run_migration.py up <slug>'`
       - Restart: run `ssh root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && scripts/MASTER_RESTART.sh'` but do not hold the SSH session open; fire the restart and rely on verification to confirm completion.
   - After successfully completing each task, update `docs/changelog/MASTER_CHANGELOG.md` **locally** by changing that task's `- [ ]` to `- [x]`.
   - If a task cannot be completed (e.g. missing env, script not found, command fails): report clearly, leave its checkbox unchecked, and continue only with tasks that are safe to run.

5. **Verify production (via SSH)** — Health (main_app :3000, trade_executor :8001), supervisor status, recent logs. Apply the “only current errors after process start” rule. End with the VERIFY STATUS block (✅ All good / ⚠️ Investigate / 🔴 Critical). If any required DB migration was not successfully run on prod, the status is **🔴 Critical**.

6. **Fidelity check (local vs prod)** — Git commit: local `git rev-parse HEAD` vs prod via SSH. Migrations: local `run_migration.py list` vs prod via SSH. Report same commit and migration state or describe mismatches.

7. **Stage the changelog** — After the changelog has been updated (checkboxes set to `- [x]`), stage it to confirm the operation: `git add docs/changelog/MASTER_CHANGELOG.md`.

8. **Report outcome** — Which entries/tasks were completed, which remain open and why, the VERIFY STATUS block, and the fidelity result.

See `.cursor/commands/apply-update.md`, `.cursor/commands/apply-update-from-local.md`, and `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`.
