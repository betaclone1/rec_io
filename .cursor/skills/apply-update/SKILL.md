# Apply update (production)

When the user invokes **/apply-update** (or "apply update", "follow the changelog instructions"), they want the production server calibrated with the latest update. **Fully autonomous:** apply all necessary changes (including DB migrations), run `scripts/MASTER_RESTART.sh` when the checklist requires a restart (blocking until complete), then run the verify workflow. Do not pause for permission; execute with the permissions needed for migrations, restart, and verify to succeed.

**Current practice:** Apply-update is typically run with an **agent on the production server** (e.g. Cursor/agent in the prod project). The agent on prod does git pull, runs migrations, MASTER_RESTART, and verify there. No git push/pull from local via terminal or SSH. A future option to run from local via SSH is in `.cursor/pm/PROD_MAINTENANCE_FROM_LOCAL.md`.

## What to do

1. **Read the agent instructions** — Open and follow `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md` in full. It defines how to find open entries and how to execute each task.
2. **List open entries** — In `docs/changelog/MASTER_CHANGELOG.md`, find every entry whose **Production agent checklist** has at least one `- [ ]`. Process entries **newest-first** (by date in the heading, e.g. `## 2026-03-08 — ...`).
3. **For each open entry** — In order: read the full entry (summary + every checklist item). Execute each unchecked task: confirm codebase (production has latest `main`), run migrations or one-time scripts exactly as written, **run `scripts/MASTER_RESTART.sh` when the checklist requires a restart** (blocking until complete), run any verification steps. After completing a task, change its `- [ ]` to `- [x]` in MASTER_CHANGELOG.md. If a task cannot be completed (e.g. missing env), report and do not mark it done.
4. **After all checklist tasks** — Run the verify workflow (health endpoints, supervisor status, recent logs, status block per `.cursor/pm/VERIFY_COMMAND.md`) to confirm the system is up and running.

## Reference

- Full instructions: `docs/changelog/CHANGELOG_AGENT_INSTRUCTIONS.md`
- Master checklist: `docs/changelog/MASTER_CHANGELOG.md`
- Command doc: `.cursor/pm/APPLY_UPDATE_COMMAND.md`
