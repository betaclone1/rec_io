---
description: "Production: run open MASTER_CHANGELOG checklists and calibrate this server with the latest update."
---

# Apply update (production)

Review the latest MASTER_CHANGELOG entries and instruction docs, run each **open** production checklist, and calibrate this server with the latest update. Equivalent to @updater new update. **This is a fully autonomous operation:** apply all necessary changes (including DB migrations), restart the system when required, and verify it is up and running. Do not pause for permission; run migrations, `scripts/MASTER_RESTART.sh`, and verification with the permissions needed for them to succeed.

**Execute (do not only describe):**

1. **Read agent instructions** — Open and follow `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` in full.
2. **Find open entries** — In `docs/changelog/MASTER_CHANGELOG.md`, list every entry whose **Production agent checklist** has at least one unchecked box (`- [ ]`). Process **newest-first** (by date in the heading).
3. **Execute each open entry** — For each open entry, in order: confirm codebase (pull latest on production), run any migrations or one-time scripts as specified, **run `scripts/MASTER_RESTART.sh` when the checklist requires a restart** (blocking until complete), run verification steps. After completing each task, change its `- [ ]` to `- [x]` in MASTER_CHANGELOG.md. If a task cannot be completed (e.g. missing env), report clearly and do not mark it done.
4. **After all checklist tasks** — Run the verify workflow (health, supervisor status, recent logs, status block) to confirm the system is up and running.
5. **Use project root** — All commands from project root. Python: `PYTHONPATH=$(pwd) venv/bin/python` (or the exact command given in the checklist).

See .cursor/pm/APPLY_UPDATE_COMMAND.md and docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md.
