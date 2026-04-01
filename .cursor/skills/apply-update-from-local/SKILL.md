# Apply update from local (production via SSH)

**Prerequisite:** Export `REC_PROD_SSH_HOST` to the production server IP or DNS name (SSH).

**Current production:** IPv4 **`165.22.13.146`** (SSH and PostgreSQL co-located). Example: `export REC_PROD_SSH_HOST=165.22.13.146` (and `export REC_PROD_DB_HOST=165.22.13.146` when local tooling connects to prod Postgres). Canonical: `docs/PRODUCTION_HOST.md`.

**Primary way to apply updates to production.** Run from your **local workspace**. The agent SSHs to prod and executes every production checklist step there (pull, migrations, restart, verify). No agent runs on the production server.

## CRITICAL — DB migrations. Do not attempt any update on another server unless we are 100% certain we can update the DB.

If an open changelog entry’s checklist includes **Apply migrations** (or running specific migration slugs):

- **Pre-flight (mandatory, before any SSH or pull):** Verify that **every** migration file referenced in that entry (e.g. `scripts/migrations/YYYYMMDD_HHMM_slug.up.sql` and `.down.sql`) exists in the commit you are deploying (e.g. `git show --name-only HEAD`). If any required migration file is **not** in that commit: **do not attempt the update.** Do not SSH to prod for update, do not pull, do not restart. Abort immediately. Report **🔴 Critical — update aborted.** The update must not be run on any other server until migration files are in the commit and pushed; only then can we be 100% certain we can update the DB.
- **When pre-flight passes:** On the target server: pull → apply all required migrations → then restart. Migrations must complete successfully before restart.
- **If a migration task was required and was not successfully completed:** VERIFY STATUS is **🔴 Critical**. Do not report "All good".

## What to do

1. **Confirm code is pushed** — The commit to deploy must already be pushed. This skill never pushes from local; it only pulls on prod.

2. **Read the agent instructions** — `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`.

3. **List open production entries** — In `docs/changelog/MASTER_CHANGELOG.md`, every entry with at least one `- [ ]`. Process **newest-first**.

4. **Execute each open entry on prod via SSH** — For each entry:
   - Read summary and all checklist items.
   - For each unchecked task, run the command on prod via SSH: `ssh root@$REC_PROD_SSH_HOST 'cd /opt/rec_io_server && <command>'`.
   - Examples: code sync (git fetch/pull), migrations (`run_migration.py up <slug>`), restart (`scripts/MASTER_RESTART.sh` — fire and do not hold SSH open).
   - After completing a task, set that item to `- [x]` in MASTER_CHANGELOG.md locally.
   - If a task cannot be completed, report why and do not mark it done.

5. **Verify production (via SSH)** — Health (3000, 8001), supervisor status, tail key logs. Only current errors (after process start) count. End with VERIFY STATUS block (✅ All good / ⚠️ Investigate / 🔴 Critical). If required migrations were not run, status is **🔴 Critical**.

6. **Fidelity check** — Local vs prod: `git rev-parse HEAD` and `run_migration.py list`. Report same commit and migrations or mismatches.

7. **Stage the changelog** — After the changelog has been updated (checkboxes set to `- [x]`), stage it to confirm the operation: `git add docs/changelog/MASTER_CHANGELOG.md`.

8. **Report outcome** — What was completed, what remains open, VERIFY STATUS, fidelity result.

## Reference

- `.cursor/commands/apply-update.md`
- `.cursor/commands/apply-update-from-local.md`
- `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`
- `.cursor/commands/verify-local.md`
