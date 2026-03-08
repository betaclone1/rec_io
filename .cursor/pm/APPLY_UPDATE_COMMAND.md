# /apply-update command

When the user invokes **/apply-update** (or says "apply update" or "follow the changelog instructions"), the agent must run the production update workflow **fully autonomously**: review the latest MASTER_CHANGELOG entries and instruction docs, execute each **open** production checklist (including DB migrations, restarts, and verification), and calibrate this server with the latest update. Equivalent to **@updater new update**. Apply all necessary changes, run `scripts/MASTER_RESTART.sh` when the checklist requires a restart (blocking until complete), then run the verify workflow. Do not pause for permission; execute with the permissions needed for migrations, restart, and verify to succeed.

## What the agent does

1. **Read** `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` and follow it in full.
2. **Find open entries** in `docs/changelog/MASTER_CHANGELOG.md` — entries whose Production agent checklist has at least one unchecked box (`- [ ]`). Process **newest-first**.
3. **Execute** each unchecked task in order: confirm codebase (pull latest on production), run migrations or one-time scripts as specified, **run `scripts/MASTER_RESTART.sh` when the checklist requires a restart** (blocking until complete), run verification steps. After each completed task, update MASTER_CHANGELOG.md: change that task’s `- [ ]` to `- [x]`. If a task cannot be completed (e.g. missing env), report clearly and do not mark it done.
4. **After all checklist tasks** — Run the verify workflow (health, supervisor status, recent logs, status block per VERIFY_COMMAND.md) to confirm the system is up and running.
5. **Commands** — From project root. Python: `PYTHONPATH=$(pwd) venv/bin/python` (or the exact command in the checklist). Restarts: `scripts/MASTER_RESTART.sh` or as specified in the entry.

## Defined in

- **Slash command:** `.cursor/commands/apply-update.md`
- **Skill:** `.cursor/skills/apply-update/SKILL.md`

If `/apply-update` does not appear when you type `/`, try typing `/apply-update` anyway, or say "apply update" or "run the changelog instructions".

## Reference

- **Full step-by-step:** `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`
- **Master checklist:** `docs/changelog/MASTER_CHANGELOG.md`
- **Changelog rule:** `.cursor/rules/changelog.mdc` (same workflow when user says "changelog" or "follow the changelog instructions")
