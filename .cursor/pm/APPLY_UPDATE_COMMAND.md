# /apply-update command

When the user invokes **/apply-update** (or says "apply update" or "follow the changelog instructions"), the agent must run the production update workflow **fully autonomously**: review the latest MASTER_CHANGELOG entries and instruction docs, execute each **open** production checklist (including DB migrations, restarts, and verification), and calibrate the server with the latest update. Equivalent to **@updater new update**. Apply all necessary changes, run `scripts/MASTER_RESTART.sh` when the checklist requires a restart (blocking until complete), then run the verify workflow. Do not pause for permission; execute with the permissions needed for migrations, restart, and verify to succeed.

**Current practice:** Apply-update is typically run with an **agent on the production server** (e.g. Cursor/agent in the prod project). The agent on prod does git pull, runs migrations, MASTER_RESTART, and verify there. No git push/pull is run from local through terminal or SSH. A future option to consolidate more maintenance from local via SSH (including optional fidelity checks) is described in `.cursor/pm/PROD_MAINTENANCE_FROM_LOCAL.md`.

## What the agent does

1. **Read** `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` and follow it in full.
2. **Find open entries** in `docs/changelog/MASTER_CHANGELOG.md` — entries whose Production agent checklist has at least one unchecked box (`- [ ]`). Process **newest-first**.
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

- **Optional future: prod from local via SSH:** `.cursor/pm/PROD_MAINTENANCE_FROM_LOCAL.md`
- **Full step-by-step:** `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`
- **Master checklist:** `docs/changelog/MASTER_CHANGELOG.md`
- **Changelog rule:** `.cursor/rules/changelog.mdc` (same workflow when user says "changelog" or "follow the changelog instructions")
