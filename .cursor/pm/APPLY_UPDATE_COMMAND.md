# /apply-update command

**Purpose:** (1) Push committed updates and instructions from this local machine and apply them to remote servers (e.g. prod) from this machine — no agents on prod. (2) Do not litter the repo with one-off DB scripts; for simple one-off DB changes use checklist steps with simple commands, not new migration files. See `.cursor/pm/PROD_MAINTENANCE_FROM_LOCAL.md` and `06_conventions_insights.md` § DB changes: migrations vs one-off commands.

When the user invokes **/apply-update** (or says "apply update" or "follow the changelog instructions"), the agent must run the production update workflow **fully autonomously**: review the latest MASTER_CHANGELOG entries and instruction docs, execute each **open** production checklist (including DB migrations, restarts, and verification), and calibrate the server with the latest update. Equivalent to **@updater new update**. Apply all necessary changes, run `scripts/MASTER_RESTART.sh` when the checklist requires a restart (blocking until complete), then run the verify workflow. Do not pause for permission; execute with the permissions needed for migrations, restart, and verify to succeed.

**Where to run:** Production updates are applied **from your local workspace** via **/apply-update-from-local**: the agent SSHs to prod and runs the checklist there (pull, migrations, restart, verify). Use **/apply-update** only when the agent is already on the production server. See `.cursor/commands/apply-update-from-local.md` and `.cursor/pm/PROD_MAINTENANCE_FROM_LOCAL.md`.

**Migrations:** Migration files reach prod only via git (commit and push; then this workflow runs pull on prod). Never SCP or copy migration files to prod. If the checklist includes "Apply migrations", every referenced migration file must be in the commit being deployed; if not, abort (do not pull, do not restart), report **🔴 Critical — update aborted**, and do not run the update until migration files are in the repo and pushed.

## What the agent does

1. **Read** `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` and follow it in full.
2. **Find open entries** in `docs/changelog/MASTER_CHANGELOG.md` — entries whose Production checklist has at least one unchecked box (`- [ ]`). Process **newest-first**.
3. **Execute** each unchecked task:
   - **When run on prod (`/apply-update`):** Confirm codebase (pull latest on the server where the agent is running), run migrations or one-time scripts as specified, **run `scripts/MASTER_RESTART.sh` when the checklist requires a restart** (blocking until complete), run verification steps. After each completed task, update MASTER_CHANGELOG.md: change that task's `- [ ]` to `- [x]`. If a task cannot be completed (e.g. missing env), report clearly and do not mark it done.
   - **When run from local (`/apply-update-from-local`):** Execute each checklist command on prod via SSH (e.g. `ssh root@137.184.224.94 'cd /opt/rec_io_server && <command>'`), then update MASTER_CHANGELOG.md locally. See `.cursor/commands/apply-update-from-local.md` and `.cursor/skills/apply-update-from-local/SKILL.md` for the SSH pattern and verification/fidelity steps.
4. **After all checklist tasks** — Run the verify workflow (health, supervisor status, recent logs, status block per VERIFY_COMMAND.md) on the target server (prod) to confirm the system is up and running.
5. **Commands** — From project root on the server where the commands run:
   - On prod directly: `cd /opt/rec_io_server`, Python: `PYTHONPATH=$(pwd) venv/bin/python`, restarts via `scripts/MASTER_RESTART.sh` or as specified.
   - From local via SSH: `ssh root@137.184.224.94 'cd /opt/rec_io_server && <command>'` with the same command bodies as above.

## Defined in

- **Slash command (on prod):** `.cursor/commands/apply-update.md`
- **Slash command (from local via SSH):** `.cursor/commands/apply-update-from-local.md`
- **Skills:** `.cursor/skills/apply-update/SKILL.md`, `.cursor/skills/apply-update-from-local/SKILL.md`

If `/apply-update` does not appear when you type `/`, try typing `/apply-update` anyway, or say "apply update" or "run the changelog instructions".

## Reference

- **Prod from local (primary):** `.cursor/pm/PROD_MAINTENANCE_FROM_LOCAL.md`
- **Full step-by-step:** `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`
- **Master checklist:** `docs/changelog/MASTER_CHANGELOG.md`
- **Changelog rule:** `.cursor/rules/changelog.mdc` (same workflow when user says "changelog" or "follow the changelog instructions")
